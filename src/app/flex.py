"""LINE Flex Message answer card (PLAN.md §7): สิทธิ / มาตรา / แหล่งอ้างอิง +
ปุ่ม URI ไปตัวบทต้นฉบับ / footer คำเตือน.

หลักฐาน/หน่วยงาน/ขั้นตอน ต้องมาจาก curated CSV + Graph Topic node (PLAN.md
§4.2/§4.3) ซึ่งเป็นงาน Day3 ของ A ที่ยังไม่มี ณ Day2 — เจตนาไม่ render 3
หัวข้อนี้เลย (ไม่ใส่ placeholder หลอกผู้ใช้ว่า "ไม่มีข้อมูล") จนกว่าจะมีข้อมูลจริง.
"""
from linebot.v3.messaging import (
    FlexBox,
    FlexBubble,
    FlexButton,
    FlexMessage,
    FlexSeparator,
    FlexText,
    URIAction,
)


def _section_label(h):
    return f'มาตรา {h["section_no"]}' + (f' ({h["chapter"]})' if h.get("chapter") else "")


def build_answer_flex(answer_text, hits, alt_text=None):
    """hits: list of chunk/section dicts used to produce answer_text — each
    needs section_no, source_url, retrieved_date (chapter optional)."""
    if not hits:
        raise ValueError("build_answer_flex requires at least one hit to cite")

    sections_label = ", ".join(dict.fromkeys(_section_label(h) for h in hits))
    source_url = hits[0]["source_url"]
    retrieved_date = hits[0]["retrieved_date"]

    body_contents = [
        FlexText(text="สิทธิ", weight="bold", size="sm", color="#888888"),
        FlexText(text=answer_text, wrap=True, size="md"),
        FlexSeparator(margin="md"),
        FlexText(text="มาตรา", weight="bold", size="sm", color="#888888", margin="md"),
        FlexText(text=sections_label, wrap=True, size="sm"),
    ]

    bubble = FlexBubble(
        body=FlexBox(layout="vertical", contents=body_contents, spacing="sm"),
        footer=FlexBox(
            layout="vertical",
            spacing="sm",
            contents=[
                FlexButton(
                    action=URIAction(label="อ่านตัวบทต้นฉบับ", uri=source_url),
                    style="link",
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

    return FlexMessage(alt_text=alt_text or answer_text[:60], contents=bubble)
