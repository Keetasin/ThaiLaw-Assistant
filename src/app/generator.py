"""LLM call — grounded answer generation for the labor-law RAG (adapted from
aj-krit/Project2/core/generator.py for this domain, see doc/PLAN.md §5 point
4 and §6.1).

Citation format is "[มาตรา X]" using the section's own real number directly
— unlike Project2's synthetic "[n]" list-position index, there's no need for
an index-to-source lookup table here since the มาตรา number already *is* the
real-world identifier a reader can look up on their own.

Uses src.llm.client so the same code runs against either the local Ollama
model or a dotBlue API model — swap via get_llm(provider=...).
"""
import re

from src.llm.client import get_llm

SYSTEM_PROMPT = """คุณคือผู้ช่วยตอบคำถามเกี่ยวกับพระราชบัญญัติคุ้มครองแรงงาน พ.ศ. 2541
ตอบเป็นภาษาไทย กระชับ ตรงประเด็น

กติกา:
- ตอบโดยอ้างอิงจาก "ข้อมูลอ้างอิง" ด้านล่างเท่านั้น
- ถ้าข้อมูลอ้างอิงไม่พอ ให้ตอบว่า "ไม่พบข้อมูลนี้ในตัวบทกฎหมายที่มี"
- ห้ามเดา ห้ามแต่งเลขมาตรา วันที่ หรือชื่อหน่วยงานขึ้นเอง
- ถ้าตอบได้ (ไม่ใช่กรณี "ไม่พบข้อมูล") ให้จบคำตอบด้วยบรรทัดใหม่รูปแบบตายตัวนี้เท่านั้น:
  "ใช้ข้อมูลจาก: [มาตรา X], [มาตรา Y]" — ใส่เฉพาะเลขมาตราที่ใช้ตอบจริงเท่านั้น ห้ามพิมพ์บรรทัดนี้
  ถ้าตอบว่า "ไม่พบข้อมูล\""""


def build_context(sections):
    lines = []
    for s in sections:
        label = f'มาตรา {s["section_no"]}' + (f' ({s["chapter"]})' if s["chapter"] else "")
        lines.append(f"[{label}] {s['text']}")
    return "\n".join(lines)


def parse_citation(answer, sections):
    """Split the LLM's raw answer into (clean_answer, cited_sections).

    A bare `\\[มาตรา\\s*(\\d+...)\\]` match anywhere would also catch the model
    mentioning a section number mid-prose, so we require one strict trailer
    line ("ใช้ข้อมูลจาก: [มาตรา X], ...") that is not part of the answer's
    prose, parse only that, and strip it from what's shown to the user. If no
    such trailer line is present (e.g. the "ไม่พบข้อมูล" refusal case), fall
    back to scanning the whole answer for `[มาตรา X]` mentions. If neither
    finds a citation, every retrieved section is treated as cited — better to
    over-cite than to show an unsourced answer.
    """
    trailer = re.search(r"^ใช้ข้อมูลจาก:\s*((?:\[มาตรา\s*[0-9/]+\]\s*,?\s*)*)\s*$", answer, re.M)
    if trailer:
        cited_nos = set(re.findall(r"\[มาตรา\s*([0-9/]+)\]", trailer.group(1)))
        clean_answer = answer[: trailer.start()].rstrip()
    else:
        cited_nos = set(re.findall(r"\[มาตรา\s*([0-9/]+)\]", answer))
        clean_answer = answer
    cited_sections = [s for s in sections if s["section_no"] in cited_nos] or sections
    return clean_answer, cited_sections


def _generate_from_context_text(context, sections_for_citation, question, provider="local"):
    prompt = f'{SYSTEM_PROMPT}\n\nข้อมูลอ้างอิง:\n{context}\n\nคำถาม: {question}'

    llm = get_llm(provider=provider)
    answer, _usage = llm.chat([{"role": "user", "content": prompt}])

    # Defensive strip in case a thinking model ignores think=False.
    if "<think>" in answer:
        answer = re.sub(r"<think>.*?</think>", "", answer, flags=re.S).strip()

    answer, cited_sections = parse_citation(answer, sections_for_citation)

    # No URL here — the Flex card (src/app/flex.py) already carries a
    # dedicated "อ่านตัวบทต้นฉบับ" button for that; repeating it as plain
    # text just clutters the citation line.
    citation = "\n".join(
        f'  § มาตรา {s["section_no"]}' + (f' ({s["chapter"]})' if s["chapter"] else "")
        for s in cited_sections
    )
    return f"{answer}\n\nที่มา: พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. 2541\n{citation}"


def generate(sections, question, provider="local"):
    return _generate_from_context_text(build_context(sections), sections, question, provider)


def generate_from_cards(cards, sections, question, provider="local"):
    """Hybrid mode: `cards` are pre-built, graph-enriched Section Cards
    (src.retrieval.context.build_section_cards) used as the LLM context
    verbatim instead of build_context()'s plain per-section formatting.
    `sections` (the same section dicts the cards were built from) is still
    needed for parse_citation()'s section_no matching in the citation
    trailer."""
    return _generate_from_context_text("\n\n".join(cards), sections, question, provider)
