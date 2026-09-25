"""Chunk parsed sections into data/chunks.jsonl (per PLAN.md §2.4 schema) and
data/sections.json (whole-section lookup for engine.py's small-to-big
expand() — has no spec in PLAN.md, key = section_key, see docstring there).

Chunking rule (PLAN.md §2.3): keep each มาตรา as one chunk normally; split
into paragraph-sized pieces only when a section runs long enough that a
single embedding would blur multiple distinct clauses together. ~800 tokens
is the PLAN.md threshold; Thai has no whitespace-delimited tokens so this is
approximated as a character-count threshold (measured empirically: only 4 of
187 sections exceed it, the longest being มาตรา 5's ~30-term definitions
list at 3348 chars).
"""
import json
import re

from src import config
from src.ingest.parse_sections import LAW_ID, LAW_NAME, parse_sections

SOURCE_URL = "https://legal.labour.go.th/images/law/Protection2541/2568_protectionpdf.pdf"
RETRIEVED_DATE = "2025-12-11"  # from the source PDF's own footer timestamp (11/12/68 13:54, พ.ศ.2568)
SPLIT_THRESHOLD_CHARS = 1600

SUBITEM_SPLIT_RE = re.compile(r"\n(?=\(\d+\)\s)")


def _split_long_section(text):
    """Blank-line paragraphs first; if the section has none (single flowing
    block, e.g. a long enumeration like มาตรา 5), fall back to splitting at
    each numbered sub-item "(1)/(2)/..." boundary. If neither applies, keep
    it as one piece — better one oversized chunk than a wrong split."""
    if len(text) <= SPLIT_THRESHOLD_CHARS:
        return [text]

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if len(paragraphs) > 1:
        return paragraphs

    subitems = [p.strip() for p in SUBITEM_SPLIT_RE.split(text) if p.strip()]
    if len(subitems) > 1:
        return subitems

    return [text]


def build_chunks_and_sections():
    sections = parse_sections()
    chunks = []
    sections_out = {}

    for sec in sections:
        section_key = f"{LAW_ID}-s{sec['section_no']}"
        pieces = _split_long_section(sec["text"])

        for i, piece in enumerate(pieces, 1):
            chunks.append({
                "chunk_id": f"{section_key}-p{i}",
                "section_key": section_key,
                "law_id": LAW_ID,
                "law_name": LAW_NAME,
                "chapter": sec["chapter"],
                "section_no": sec["section_no"],
                "paragraph": i,
                "doc_type": "statute",
                "status": sec["status"],
                "amended_by": sec["amended_by"],
                "refs_out": sec["refs_out"],
                "source_url": SOURCE_URL,
                "retrieved_date": RETRIEVED_DATE,
                "text": piece,
            })

        sections_out[section_key] = {
            "section_key": section_key,
            "law_id": LAW_ID,
            "law_name": LAW_NAME,
            "chapter": sec["chapter"],
            "section_no": sec["section_no"],
            "status": sec["status"],
            "source_url": SOURCE_URL,
            "text": sec["text"],
        }

    with open(config.CHUNKS_PATH, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    with open(config.SECTIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(sections_out, f, ensure_ascii=False, indent=2)

    print(f"wrote {len(chunks)} chunks ({len(sections)} sections) -> {config.CHUNKS_PATH}")
    print(f"wrote {len(sections_out)} sections -> {config.SECTIONS_PATH}")
    return chunks, sections_out


if __name__ == "__main__":
    build_chunks_and_sections()
