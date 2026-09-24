"""LLM call — grounded answer generation.

STAGED FOR DAY 2/3, NOT DOMAIN-ADAPTED YET: copied from
aj-krit/Project2/core/generator.py almost verbatim. SYSTEM_PROMPT below is
still the *university handbook* prompt (page citations, "คู่มือนักศึกษาใหม่")
— it must be rewritten for the legal domain before use: citation format
should become "[มาตรา X]" (see doc/PLAN.md §6.1/§2.3), context format should
match the "Section Card" shape from doc/PLAN.md §5 point 4, not raw page
numbers. Left untouched today so the citation-parsing logic (the part that
actually matters and is non-obvious, see the comment below) isn't rewritten
twice.

Uses src.llm.client so the same code runs against either the local Ollama
model or a dotBlue API model — swap via get_llm(provider=...).
"""
import re

from src import config
from src.llm.client import get_llm

SYSTEM_PROMPT = """คุณคือผู้ช่วยตอบคำถามสำหรับนักศึกษาใหม่ คณะวิศวกรรมศาสตร์ ม.อ.
ตอบเป็นภาษาไทย กระชับ ตรงประเด็น

กติกา:
- ตอบโดยอ้างอิงจาก "ข้อมูลอ้างอิง" ด้านล่างเท่านั้น
- ถ้าข้อมูลอ้างอิงไม่พอ ให้ตอบว่า "ไม่พบข้อมูลนี้ในคู่มือนักศึกษา"
- ห้ามเดา ห้ามแต่งตัวเลข วันที่ หรือชื่อหน่วยงานขึ้นเอง
- ถ้าตอบได้ (ไม่ใช่กรณี "ไม่พบข้อมูล") ให้จบคำตอบด้วยบรรทัดใหม่รูปแบบตายตัวนี้เท่านั้น:
  "ใช้ข้อมูลจาก: [n], [n]" — ใส่เฉพาะหมายเลขที่ใช้ตอบจริงเท่านั้น ห้ามพิมพ์บรรทัดนี้ถ้าตอบว่า
  "ไม่พบข้อมูล"

TODO (Day 2/3): rewrite this prompt + _format_pages/build_context for the
legal domain — see doc/PLAN.md §5 point 4 (Section Card) and §6.1."""


def _format_pages(pages):
    pages = sorted(set(pages))
    if len(pages) == 1:
        return f"หน้า {pages[0]}"
    return f"หน้า {pages[0]}-{pages[-1]}"


def build_context(sections):
    lines = []
    for i, s in enumerate(sections, 1):
        lines.append(f'[{i}] ({_format_pages(s["pages"])} — {s["heading"]} › {s["section"]}) {s["text"]}')
    return "\n".join(lines)


def generate(sections, question, provider="local"):
    context = build_context(sections)
    prompt = f'{SYSTEM_PROMPT}\n\nข้อมูลอ้างอิง:\n{context}\n\nคำถาม: {question}'

    llm = get_llm(provider=provider)
    answer, _usage = llm.chat([{"role": "user", "content": prompt}])

    # Defensive strip in case a thinking model ignores think=False.
    if "<think>" in answer:
        answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.S).strip()

    # Citation numbering: a bare `\[(\d+)\]` match also catches the model
    # EXPLAINING it isn't using a section, so we require one strict trailer
    # line ("ใช้ข้อมูลจาก: [n], [n]") that is not part of the answer's prose,
    # parse only that, and strip it from what's shown to the user.
    trailer = re.search(r"^ใช้ข้อมูลจาก:\s*((?:\[\d+\]\s*,?\s*)*)\s*$", answer, re.M)
    if trailer:
        cited_idx = {int(n) for n in re.findall(r"\d+", trailer.group(1))}
        answer = answer[: trailer.start()].rstrip()
    else:
        cited_idx = {int(n) for n in re.findall(r"\[(\d+)\]", answer)}
    cited_sections = [s for i, s in enumerate(sections, 1) if i in cited_idx] or sections

    citation = "\n".join(
        f'  § {s["heading"]} › {s["section"]} — {_format_pages(s["pages"])}' for s in cited_sections
    )
    return f'{answer}\n\nที่มา: {config.__dict__.get("SOURCE_NAME", "ตัวบทกฎหมาย")}\n{citation}'
