"""Day 3 production LINE webhook: RAGEngine (Hybrid RAG: dense+BM25+graph,
router-weighted) + Flex answer card + chat_history (Neo4j) + demo commands
(/mode, /llm, /debug, /reset — PLAN.md §7).

Note: RAGEngine keeps its own in-memory per-session history (for multi-turn
query rewrite, see src/app/engine.py) — chat_history.py's Neo4j store here is
a separate durable log of turns, not fed back into the engine. Unifying the
two is out of scope.

Per-user command state (mode/llm/debug) lives in this module's
`_session_state` dict, same lazy in-memory pattern as `_engine` below — not
persisted, resets on restart, which is fine for a demo toggle.
"""
import logging
import os
import threading

from dotenv import load_dotenv
from flask import Flask, abort, request
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import ApiClient, Configuration, MessagingApi, ReplyMessageRequest, TextMessage
from linebot.v3.webhooks import MessageEvent, TextMessageContent

from src import config
from src.app import chat_history
from src.app.engine import RAGEngine
from src.app.flex import build_answer_flex

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("app_line")

app = Flask(__name__)
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])
line_config = Configuration(access_token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"])

_engine = None
_session_state = {}

MODES = ("dense", "graph", "hybrid")
PROVIDERS = ("local", "api")

COMMAND_HELP = (
    "คำสั่งที่ใช้ได้:\n"
    "/mode dense|graph|hybrid — สลับโหมดการค้นหา\n"
    "/llm local|api — สลับโมเดลที่ใช้ตอบ\n"
    "/debug — เปิด/ปิดโหมดแสดงรายละเอียด\n"
    "/reset — ล้างประวัติการสนทนา"
)


def get_engine():
    # Lazy so importing this module (e.g. for tests) doesn't require
    # data/chunks.jsonl + Chroma + BM25 to already be built.
    global _engine
    if _engine is None:
        _engine = RAGEngine()
    return _engine


def _state(user_id):
    return _session_state.setdefault(user_id, {"mode": "hybrid", "provider": "local", "debug": False})


def _handle_command(user_id, text):
    """Returns a reply string if `text` is a recognized /command, else None
    (meaning: treat `text` as a normal question)."""
    parts = text.strip().split()
    if not parts or not parts[0].startswith("/"):
        return None
    cmd, args = parts[0].lower(), parts[1:]

    if cmd == "/mode":
        if args and args[0] in MODES:
            _state(user_id)["mode"] = args[0]
            return f"เปลี่ยนโหมดเป็น {args[0]} แล้ว"
        return "ใช้: /mode dense|graph|hybrid"

    if cmd == "/llm":
        if args and args[0] in PROVIDERS:
            _state(user_id)["provider"] = args[0]
            return f"เปลี่ยน LLM เป็น {args[0]} แล้ว"
        return "ใช้: /llm local|api"

    if cmd == "/debug":
        state = _state(user_id)
        state["debug"] = not state["debug"]
        return f"โหมด debug: {'เปิด' if state['debug'] else 'ปิด'}"

    if cmd == "/reset":
        get_engine().clear_history(user_id)
        try:
            chat_history.clear_history(user_id)
        except Exception:
            log.exception("chat_history clear failed")
        _session_state.pop(user_id, None)
        return "ล้างประวัติการสนทนาแล้ว"

    return COMMAND_HELP


def _format_debug(debug):
    lines = [f'[DEBUG] mode={debug["mode"]} zone={debug["zone"]} score={debug["rerank_score"]:.3f}']
    provider_line = f'provider={debug["provider"]}'
    if debug.get("provider_fallback"):
        provider_line += " (fallback)"
    lines.append(provider_line)
    if debug.get("route"):
        r = debug["route"]
        lines.append(f'route={r["query_type"]} α(dense={r["alpha_dense"]}, bm25={r["alpha_bm25"]}, graph={r["alpha_graph"]})')
    top = debug.get("hits") or []
    if top:
        lines.append("top sections: " + ", ".join(str(h.get("section_no")) for h in top[:5]))
    paths = debug.get("graph_paths") or []
    if paths:
        lines.append("graph paths: " + "; ".join(f'{p["from"]}-{p["type"]}->{p["to"]}' for p in paths[:5]))
    latency = debug.get("latency") or {}
    if latency:
        lines.append("latency(s): " + ", ".join(f"{k}={v:.2f}" for k, v in latency.items()))
    return "\n".join(lines)


def _reply(event, messages):
    try:
        with ApiClient(line_config) as api_client:
            MessagingApi(api_client).reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=messages)
            )
    except Exception:
        log.exception("reply failed")


@app.post("/callback")
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"


@handler.add(MessageEvent, message=TextMessageContent)
def on_message(event):
    threading.Thread(target=_work, args=(event,), daemon=True).start()


def _work(event):
    user_id = event.source.user_id
    text = event.message.text

    command_reply = _handle_command(user_id, text)
    if command_reply is not None:
        _reply(event, [TextMessage(text=command_reply)])
        return

    state = _state(user_id)
    try:
        answer, debug = get_engine().answer_with_debug(
            text, session_id=user_id, provider=state["provider"], mode=state["mode"]
        )
        reply = build_answer_flex(answer, debug["hits"]) if debug["hits"] else TextMessage(text=answer)
    except Exception:
        log.exception("answer generation failed")
        answer = "ขออภัย ระบบขัดข้อง กรุณาลองใหม่อีกครั้ง"
        reply = TextMessage(text=answer)
        debug = None

    try:
        chat_history.save_turn(user_id, "user", text)
        chat_history.save_turn(user_id, "assistant", answer)
    except Exception:
        log.exception("chat_history save failed")

    messages = [reply]
    if debug is not None and state["debug"]:
        messages.append(TextMessage(text=_format_debug(debug)))
    _reply(event, messages)


if __name__ == "__main__":
    log.info("Day 3 app_line starting on port %s", config.APP_PORT)
    app.run(port=config.APP_PORT)
