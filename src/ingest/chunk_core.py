"""Stable JSONL chunk builder for statutes."""
from __future__ import annotations
import argparse, json, re
from collections import Counter
from datetime import date
from pathlib import Path

REF_RE = re.compile(r"มาตรา\s*([๐-๙0-9]+(?:\s*/\s*[๐-๙0-9]+)?)")
THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")

def _tokens(text: str) -> int: return max(1, len(re.findall(r"\S+", text)))
def _refs(text: str, current: str) -> list[str]:
    refs = {x.translate(THAI_DIGITS).replace(" ", "") for x in REF_RE.findall(text)}; refs.discard(current)
    return sorted(refs, key=lambda x: tuple(int(p) for p in x.split("/")))

def create_chunks(sections: list[dict], law_id: str, law_name: str, source_url: str,
                  retrieved_date: str | None = None, max_tokens: int = 800,
                  doc_type: str = "statute") -> list[dict]:
    result, retrieved, occurrences = [], retrieved_date or date.today().isoformat(), Counter()
    for section in sections:
        number, text = str(section["section_no"]).translate(THAI_DIGITS), section["text"].strip()
        occurrences[number] += 1
        paragraphs, pieces, current, size = section.get("paragraphs") or text.splitlines(), [], [], 0
        if _tokens(text) <= max_tokens: pieces = [text]
        else:
            for paragraph in paragraphs:
                if current and size + _tokens(paragraph) > max_tokens: pieces.append("\n".join(current)); current, size = [], 0
                current.append(paragraph); size += _tokens(paragraph)
            if current: pieces.append("\n".join(current))
        for index, piece in enumerate(pieces or [text], 1):
            version = "" if occurrences[number] == 1 else f"-v{occurrences[number]}"
            result.append({"chunk_id": f"{law_id}-s{number}{version}-p{index}", "law_id": law_id,
                "law_name": law_name, "chapter": section.get("chapter", "ไม่ระบุหมวด"),
                "section_no": number, "paragraph": index, "doc_type": doc_type,
                "status": section.get("status", "in_force"), "amended_by": section.get("amended_by", []),
                "version": section.get("version"), "refs_out": _refs(piece, number),
                "source_url": source_url, "retrieved_date": retrieved, "text": piece})
    return result

def write_chunks(chunks: list[dict], output_file: str | Path) -> None:
    ids = [x["chunk_id"] for x in chunks]
    if len(ids) != len(set(ids)): raise ValueError("duplicate chunk_id")
    target = Path(output_file); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in chunks), encoding="utf-8")

def create_chunks_and_metadata(input_file: str, output_file: str, law_id: str, law_name: str, source_url: str) -> list[dict]:
    sections = json.loads(Path(input_file).read_text(encoding="utf-8")); chunks = create_chunks(sections, law_id, law_name, source_url)
    write_chunks(chunks, output_file); return chunks

def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("input_file"); parser.add_argument("output_file"); parser.add_argument("--law-id", required=True); parser.add_argument("--law-name", required=True); parser.add_argument("--source-url", required=True)
    args = parser.parse_args(); print(f"wrote {len(create_chunks_and_metadata(args.input_file, args.output_file, args.law_id, args.law_name, args.source_url))} chunks")

if __name__ == "__main__":
    main()
