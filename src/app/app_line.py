"""Day 2 production LINE webhook: RAGEngine (Dense RAG) + Flex answer card +
Neo4j turn logging via chat_history. Day 1's echo_app.py is left untouched
as a plain-echo diagnostic fallback.

Note: RAGEngine keeps its own in-memory per-session history (for multi-turn
query rewrite, see src/app/engine.py) — chat_history.py's Neo4j store here is
a separate durable log of turns, not fed back into the engine. Unifying the
two is out of scope for Day 2.
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


def get_engine():
    # Lazy so importing this module (e.g. for tests) doesn't require
    # data/chunks.jsonl + Chroma + BM25 to already be built.
    global _engine
    if _engine is None:
        _engine = RAGEngine()
    return _engine


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

    try:
        answer, debug = get_engine().answer_with_debug(text, session_id=user_id)
        reply = build_answer_flex(answer, debug["hits"]) if debug["hits"] else TextMessage(text=answer)
    except Exception:
        log.exception("answer generation failed")
        answer = "ขออภัย ระบบขัดข้อง กรุณาลองใหม่อีกครั้ง"
        reply = TextMessage(text=answer)

    try:
        chat_history.save_turn(user_id, "user", text)
        chat_history.save_turn(user_id, "assistant", answer)
    except Exception:
        log.exception("chat_history save failed")

    try:
        with ApiClient(line_config) as api_client:
            MessagingApi(api_client).reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[reply])
            )
    except Exception:
        log.exception("reply failed")


if __name__ == "__main__":
    log.info("Day 2 app_line starting on port %s", config.APP_PORT)
    app.run(port=config.APP_PORT)
