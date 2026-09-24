"""Day 1 minimal LINE webhook: verifies signature, replies with whatever the
user sent (echo). Proves the webhook + signature + reply pipeline works
before RAGEngine exists (Day 2 wires in src.app.engine.RAGEngine instead of
this echo, once data/chunks.jsonl + Chroma + BM25 exist).

Pattern copied from aj-krit/Project2/app_line.py: Flask must not block on
slow work, so on_message spawns a thread and callback() returns 200
immediately; reply_token is valid long enough to cover a short wait.
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

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("echo_app")

app = Flask(__name__)
handler = WebhookHandler(os.environ["LINE_CHANNEL_SECRET"])
line_config = Configuration(access_token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"])


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
    text = event.message.text
    reply_text = f"(echo) {text}"
    try:
        with ApiClient(line_config) as api_client:
            MessagingApi(api_client).reply_message(
                ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text=reply_text)])
            )
    except Exception:
        log.exception("reply failed")


if __name__ == "__main__":
    log.info("Day 1 echo app starting on port %s", config.APP_PORT)
    app.run(port=config.APP_PORT)
