"""Regex-parse the cleaned law text into a structured list of section dicts:
หมวด (chapter) -> มาตรา (section) boundaries, plus amendment-history detection.

Scope note: this file only handles พ.ร.บ.คุ้มครองแรงงาน พ.ศ. 2541 (the single
statute currently in data/clean/) — LAW_ID/LAW_NAME/SOURCE_URL/RETRIEVED_DATE
below are for that document specifically, not a general multi-law parser.

Document layout quirks this parser works around (verified by inspection):
- Chapter headers are "หมวด N" alone on its own line, with the chapter TITLE
  on the line immediately after (e.g. "หมวด 1\nบททั่วไป"). The transitional
  provisions block has no "หมวด N" header at all, just a bare "บทเฉพาะกาล"
  line, so it's matched separately.
- The real, sequential มาตรา numbering (1..166 plus sub-numbered ones like
  4/1, 39/1) runs continuously through all หมวด + บทเฉพาะกาล, and ends right
  before the royal-signature line "ผู้รับสนองพระบรมราชโองการ". Everything
  after that line (fee schedule, then repeated "หมายเหตุ :-" blocks — one per
  amending act's own explanatory notes) is NOT part of any มาตรา's body text:
  those notes blocks themselves contain "มาตรา N" mentions that belong to a
  DIFFERENT act's own internal numbering (e.g. an amending act's own
  "บทเฉพาะกาล มาตรา 11"), which would corrupt section boundaries if scanned
  as if they were this act's sections. So section-boundary scanning stops
  dead at the signature line; only a separate bracket-footnote scan runs
  over the tail.
- Amendment history is NOT attached inline in a machine-friendly way: a
  section's "(ยกเลิก)" is written directly in its own body (e.g. "มาตรา 154
  [88] (ยกเลิก)"), but "แก้ไขเพิ่มเติมโดย...(ฉบับที่ N) พ.ศ. YYYY" only
  appears in the numbered footnote list near the end of the document (e.g.
  "[88] มาตรา 154 ยกเลิกโดยพระราชบัญญัติคุ้มครองแรงงาน (ฉบับที่ 4) พ.ศ.
  2553"), which restates the มาตรา number explicitly — so footnotes are
  matched back to sections by that restated number, not by lining up
  bracket-index [N] positions (those don't correspond 1:1 to reading order).
"""
import re

LAW_ID = "LPA2541"
LAW_NAME = "พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. 2541"
CLEAN_TEXT_PATH = "data/clean/พ.ร.บ.คุ้มครองแรงงาน พ.ศ. 2541 (ฉบับปรังปรุงล่าสุด).txt"

CHAPTER_RE = re.compile(r"^หมวด\s+([0-9]+)\s*$")
TRANSITIONAL_RE = re.compile(r"^บทเฉพาะกาล\s*$")
SECTION_RE = re.compile(r"^มาตรา\s+([0-9]+(?:/[0-9]+)?)\s*(.*)$")
END_OF_ACT_RE = re.compile(r"^ผู้รับสนองพระบรมราชโองการ\s*$")

# Footnote definitions live after the signature block, e.g.:
#   "[88] มาตรา 154 ยกเลิกโดยพระราชบัญญัติคุ้มครองแรงงาน (ฉบับที่ 4) พ.ศ. 2553"
#   "[86] มาตรา 151 วรรคสอง แก้ไขเพิ่มเติมโดยพระราชบัญญัติ...(ฉบับที่ 7) พ.ศ. 2562"
FOOTNOTE_RE = re.compile(
    r"^\[(\d+)\]\s*มาตรา\s*([0-9]+(?:/[0-9]+)?)"
    r".*?(ยกเลิกโดย|แก้ไขเพิ่มเติมโดย).*?\(ฉบับที่\s*([0-9]+)\)\s*พ\.ศ\.\s*([0-9]{4})"
)

BRACKET_MARKER_RE = re.compile(r"\[\d+\]")
REF_OUT_RE = re.compile(r"มาตรา\s*([0-9]+(?:/[0-9]+)?)")


def _parse_footnote_amendments(lines):
    """Scan the whole document (footnotes only match past the signature
    line in practice) for '[N] มาตรา X ยกเลิก/แก้ไขเพิ่มเติมโดย...' and
    return {section_no: {"status": ..., "amended_by": [...]}}."""
    amendments = {}
    for line in lines:
        m = FOOTNOTE_RE.match(line.strip())
        if not m:
            continue
        _footnote_no, section_no, action, ed_no, year = m.groups()
        entry = amendments.setdefault(section_no, {"status": "in_force", "amended_by": []})
        cite = f"(ฉบับที่ {ed_no}) พ.ศ. {year}"
        if cite not in entry["amended_by"]:
            entry["amended_by"].append(cite)
        if action == "ยกเลิกโดย":
            entry["status"] = "repealed"
        elif entry["status"] != "repealed":
            entry["status"] = "amended"
    return amendments


def _parse_no(s):
    parts = s.split("/")
    return int(parts[0]), (int(parts[1]) if len(parts) > 1 else 0)


def _is_valid_next(prev, cand):
    """Thai statute section numbering is strictly sequential with no gaps
    (a repealed section keeps its number, marked "(ยกเลิก)", rather than
    being removed) — so the only two legal next numbers after (base, sub)
    are the next sub-number under the same base, or the next base with no
    sub-number. Anything else appearing at a line's start is a citation
    (e.g. "...ให้นำมาตรา\nมาตรา 82 วรรคหนึ่ง มาตรา 83...") that happened to
    wrap exactly at a "มาตรา" token, not a real section header."""
    pbase, psub = prev
    cbase, csub = cand
    return (cbase == pbase and csub == psub + 1) or (cbase == pbase + 1 and csub == 0)


def parse_sections(text=None):
    """Return a list of section dicts:
    {section_no, chapter, text, status, amended_by, refs_out}
    ordered as they appear in the document."""
    if text is None:
        with open(CLEAN_TEXT_PATH, encoding="utf-8") as f:
            text = f.read()
    lines = text.split("\n")

    amendments = _parse_footnote_amendments(lines)

    sections = []
    current = None
    current_chapter = None
    expect_chapter_title = False
    last_no = (0, 0)

    for line in lines:
        if END_OF_ACT_RE.match(line):
            break

        if expect_chapter_title:
            title = BRACKET_MARKER_RE.sub("", line).strip()
            current_chapter = f"หมวด {current_chapter_no} {title}".strip()
            expect_chapter_title = False
            continue

        m_chap = CHAPTER_RE.match(line)
        if m_chap:
            current_chapter_no = m_chap.group(1)
            expect_chapter_title = True
            continue

        if TRANSITIONAL_RE.match(line):
            current_chapter = "บทเฉพาะกาล"
            continue

        m_sec = SECTION_RE.match(line)
        if m_sec:
            section_no, rest = m_sec.groups()
            cand_no = _parse_no(section_no)
            if not _is_valid_next(last_no, cand_no):
                # Not the expected next section number -> this is a citation
                # that happened to wrap at a "มาตรา" token, not a real header.
                if current is not None:
                    current["lines"].append(line)
                continue
            last_no = cand_no
            if current is not None:
                sections.append(current)
            current = {"section_no": section_no, "chapter": current_chapter, "lines": [rest] if rest else []}
            continue

        if current is not None:
            current["lines"].append(line)

    if current is not None:
        sections.append(current)

    out = []
    for sec in sections:
        raw_text = "\n".join(sec["lines"]).strip()
        clean_text = BRACKET_MARKER_RE.sub("", raw_text).strip()
        clean_text = re.sub(r"[ \t]+", " ", clean_text)

        section_no = sec["section_no"]
        amend = amendments.get(section_no, {"status": "in_force", "amended_by": []})
        status = amend["status"]
        if clean_text.startswith("(ยกเลิก)"):
            status = "repealed"  # direct in-body marker overrides footnote lookup

        refs_out = sorted(set(REF_OUT_RE.findall(raw_text)) - {section_no}, key=lambda n: [int(p) for p in n.split("/")])

        out.append({
            "section_no": section_no,
            "chapter": sec["chapter"],
            "text": clean_text,
            "status": status,
            "amended_by": amend["amended_by"],
            "refs_out": refs_out,
        })
    return out


if __name__ == "__main__":
    result = parse_sections()
    chapters = sorted({s["chapter"] for s in result}, key=lambda c: c or "")
    print(f"parsed {len(result)} sections across {len(chapters)} chapters")
    repealed = [s for s in result if s["status"] == "repealed"]
    amended = [s for s in result if s["status"] == "amended"]
    print(f"repealed: {len(repealed)}  amended: {len(amended)}")
    print("repealed section_nos:", [s["section_no"] for s in repealed])
