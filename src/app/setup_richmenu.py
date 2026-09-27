"""One-off admin script: upload the LINE Rich Menu image + create tappable
areas, set as default for every user. Run manually after the bot is
deployed: `python -m src.app.setup_richmenu` (needs LINE_CHANNEL_ACCESS_TOKEN
in .env, same as app_line.py).

Image: src/app/assets/richmenu_reference.png (user-supplied design, 1536x1024)
resized to 2500-wide (LINE's max) keeping its exact aspect ratio -- a navy
title banner on top (tappable: sends a fixed "สวัสดีครับ" greeting
app_line.py intercepts before the RAG engine, replying with
build_intro_flex()'s "what this bot does + example questions" card), 3
tappable link tiles below.
The banner/tiles boundary (BANNER_H) was measured from the actual image
(row-average brightness jump from dark navy to light cream around
y=485/1024), not guessed -- rescale it if the source image changes.
"""
import os
import sys

from dotenv import load_dotenv
from linebot.v3.messaging import (
    ApiClient,
    Configuration,
    MessageAction,
    MessagingApi,
    MessagingApiBlob,
    RichMenuArea,
    RichMenuBounds,
    RichMenuRequest,
    RichMenuSize,
    URIAction,
)
from PIL import Image

load_dotenv()

REFERENCE_PATH = os.path.join(os.path.dirname(__file__), "assets", "richmenu_reference.png")
IMAGE_PATH = os.path.join(os.path.dirname(__file__), "assets", "richmenu.jpg")

WIDTH = 2500
_ref_w, _ref_h = Image.open(REFERENCE_PATH).size
HEIGHT = round(WIDTH * _ref_h / _ref_w)
BANNER_H = round(485 * HEIGHT / _ref_h)  # measured boundary, scaled to HEIGHT
TILE_Y0 = BANNER_H
TILE_H = HEIGHT - BANNER_H
TILE_W = WIDTH // 3

TILES = [
    {"label": "เปิดลิ้ง", "uri": "https://legal.labour.go.th/images/law/Protection2541/2568_protectionpdf.pdf"},
    {"label": "เข้าเว็ป", "uri": "https://legal.labour.go.th/2015-12-03-05-01-09"},
    {"label": "ติดต่อ", "uri": "https://legal.labour.go.th/2015-12-03-05-07-59"},
]


def build_image(path=IMAGE_PATH):
    # LINE's rich menu image upload caps out at 1MB -- the resized reference
    # (photographic gradients/shadows) is ~1.9MB as PNG, a 413 on upload.
    # JPEG quality=90 compresses the same image to ~380KB with no visible
    # loss on the crisp Thai text (checked directly, not assumed).
    img = Image.open(REFERENCE_PATH).convert("RGB").resize((WIDTH, HEIGHT), Image.LANCZOS)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, "JPEG", quality=90, optimize=True)
    print(f"[richmenu] resized reference -> {path} ({WIDTH}x{HEIGHT}, banner_h={BANNER_H}, {os.path.getsize(path)} bytes)")
    return path


def create_and_set_default(image_path=IMAGE_PATH):
    areas = [
        RichMenuArea(
            bounds=RichMenuBounds(x=0, y=0, width=WIDTH, height=BANNER_H),
            action=MessageAction(text="สวัสดีครับ", label="แนะนำการใช้งาน"),
        )
    ]
    for i, tile in enumerate(TILES):
        x0 = i * TILE_W
        w = WIDTH - x0 if i == len(TILES) - 1 else TILE_W  # last tile absorbs integer-division remainder
        areas.append(
            RichMenuArea(
                bounds=RichMenuBounds(x=x0, y=TILE_Y0, width=w, height=TILE_H),
                action=URIAction(uri=tile["uri"], label=tile["label"]),
            )
        )

    request = RichMenuRequest(
        size=RichMenuSize(width=WIDTH, height=HEIGHT),
        selected=True,
        name="thailaw-assistant-main",
        chatBarText="เมนู",
        areas=areas,
    )

    line_config = Configuration(access_token=os.environ["LINE_CHANNEL_ACCESS_TOKEN"])
    with ApiClient(line_config) as api_client:
        api = MessagingApi(api_client)
        blob_api = MessagingApiBlob(api_client)

        rich_menu_id = api.create_rich_menu(request).rich_menu_id
        print(f"[richmenu] created rich menu id={rich_menu_id}")

        # linebot SDK quirk: without an explicit Content-Type, rest.py's
        # request() treats any body as JSON and json.dumps() the raw PNG
        # bytes, crashing with "Object of type bytes is not JSON
        # serializable" -- `_headers` (not `_content_type`, despite what the
        # method's docstring implies) is what actually reaches the header
        # dict rest.py checks to route bytes straight through instead.
        with open(image_path, "rb") as f:
            blob_api.set_rich_menu_image(rich_menu_id, f.read(), _headers={"Content-Type": "image/jpeg"})
        print("[richmenu] uploaded image")

        api.set_default_rich_menu(rich_menu_id)
        print(f"[richmenu] set as default for all users -> id={rich_menu_id}")
        return rich_menu_id


if __name__ == "__main__":
    path = build_image()
    if "--upload" in sys.argv:
        create_and_set_default(path)
    else:
        print("[richmenu] image built. Run again with --upload to create+set it on LINE.")
