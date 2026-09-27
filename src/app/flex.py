"""LINE Flex Message answer card (PLAN.md §7): คำตอบ / มาตรา / แหล่งอ้างอิง +
ปุ่ม URI ไปตัวบทต้นฉบับ / footer คำเตือน.

หลักฐาน/หน่วยงาน/ขั้นตอน ต้องมาจาก curated CSV + Graph Topic node (PLAN.md
§4.2/§4.3) ซึ่งเป็นงาน Day3 ของ A ที่ยังไม่มี ณ Day2 — เจตนาไม่ render 3
หัวข้อนี้เลย (ไม่ใส่ placeholder หลอกผู้ใช้ว่า "ไม่มีข้อมูล") จนกว่าจะมีข้อมูลจริง.
"""
import re

from linebot.v3.messaging import (
    FlexBox,
    FlexBubble,
    FlexButton,
    FlexMessage,
    FlexSeparator,
    FlexText,
    URIAction,
)
from pythainlp.tokenize import word_tokenize

_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_BULLET_RE = re.compile(r"(?m)^[ \t]*\*[ \t]+")
_ZWSP = "​"


def _strip_markdown(text):
    """LINE's FlexText has no markdown renderer -- **bold**/`*  bullet`
    syntax the LLM sometimes emits (despite the plain-text system prompt)
    would otherwise show up as literal asterisks in the chat bubble."""
    text = _BOLD_RE.sub(r"\1", text)
    return _BULLET_RE.sub("• ", text)


def _insert_word_breaks(text):
    """Thai script has no spaces between words, and LINE's FlexText wraps
    purely by character count (no built-in Thai dictionary line-breaker),
    so long lines split mid-word (seen live: "ลูกจ้ / างที่เลิกจ้าง"). Insert
    an invisible U+200B at each word boundary -- same `newmm` tokenizer
    src/retrieval/thai.py already uses for BM25 -- so the client has a real
    word boundary to wrap at instead of an arbitrary character position."""
    return "\n".join(
        _ZWSP.join(word_tokenize(line, engine="newmm", keep_whitespace=True)) if line else line
        for line in text.split("\n")
    )


def clean_for_line(text):
    """Shared by both reply paths: the Flex card body below, and
    app_line.py's plain TextMessage branch (out-of-scope/general_knowledge
    answers, which never go through build_answer_flex) -- both need the
    same markdown-strip + Thai word-break treatment."""
    return _insert_word_breaks(_strip_markdown(text))


_HEADER_BG = "#10243E"
_BODY_BG = "#FBF7EE"
_MATTRA_COLOR = "#1D4ED8"
_SEPARATOR_COLOR = "#F4A261"
_BUTTON_COLOR = "#10243E"


def _section_label(h):
    return f'มาตรา {h["section_no"]}' + (f' ({h["chapter"]})' if h.get("chapter") else "")


def build_answer_flex(answer_text, hits, alt_text=None):
    """hits: list of chunk/section dicts used to produce answer_text — each
    needs section_no, source_url, retrieved_date (chapter optional).

    answer_text carries its own "\\n\\nที่มา: ..." citation trailer
    (generator.py always appends one) -- drop it here since the card
    already renders its own deduped "มาตรา" section below from `hits`;
    keeping both showed the same section list twice."""
    if not hits:
        raise ValueError("build_answer_flex requires at least one hit to cite")

    body_text = answer_text.split("\n\nที่มา:", 1)[0]
    sections_label = ", ".join(dict.fromkeys(_section_label(h) for h in hits))
    source_url = hits[0]["source_url"]
    retrieved_date = hits[0]["retrieved_date"]

    body_contents = [
        FlexText(text=clean_for_line(body_text), wrap=True, size="md"),
        FlexSeparator(margin="md", color=_SEPARATOR_COLOR),
        FlexText(text="มาตรา", weight="bold", size="sm", color=_MATTRA_COLOR, margin="md"),
        FlexText(text=sections_label, wrap=True, size="sm"),
    ]

    bubble = FlexBubble(
        header=FlexBox(
            layout="vertical",
            background_color=_HEADER_BG,
            padding_all="lg",
            contents=[FlexText(text="⚖️ ผู้ช่วยกฎหมายแรงงาน", weight="bold", size="md", color="#FFFFFF")],
        ),
        body=FlexBox(layout="vertical", background_color=_BODY_BG, contents=body_contents, spacing="sm"),
        footer=FlexBox(
            layout="vertical",
            background_color=_BODY_BG,
            spacing="sm",
            contents=[
                FlexButton(
                    action=URIAction(label="อ่านตัวบทต้นฉบับ", uri=source_url),
                    style="primary",
                    color=_BUTTON_COLOR,
                    height="sm",
                ),
                FlexText(
                    text=f"ข้อมูล ณ วันที่ {retrieved_date} · ไม่ใช่คำปรึกษาทางกฎหมาย",
                    size="xxs",
                    color="#aaaaaa",
                    wrap=True,
                ),
            ],
        ),
    )

    return FlexMessage(alt_text=alt_text or body_text[:60], contents=bubble)

def build_intro_flex():
    """Tapping the rich menu's banner (setup_richmenu.py) sends a fixed
    "สวัสดีครับ" greeting (app_line.py intercepts it before the RAG engine)
    -- this is the reply: what the bot answers, not an answer card, so it
    skips the มาตรา/citation sections entirely."""
    body_text = (
        "แชทนี้คือผู้ช่วยตอบคำถามเกี่ยวกับ พ.ร.บ.คุ้มครองแรงงาน พ.ศ. 2541\n"
        "ถามเกี่ยวกับสิทธิลูกจ้าง/นายจ้างได้เลย"
    )

    bubble = FlexBubble(
        header=FlexBox(
            layout="vertical",
            background_color=_HEADER_BG,
            padding_all="lg",
            contents=[FlexText(text="⚖️ ผู้ช่วยกฎหมายแรงงาน", weight="bold", size="md", color="#FFFFFF")],
        ),
        body=FlexBox(
            layout="vertical",
            background_color=_BODY_BG,
            spacing="sm",
            contents=[FlexText(text=clean_for_line(body_text), wrap=True, size="md")],
        ),
    )
    return FlexMessage(alt_text="แนะนำการใช้งาน", contents=bubble)
