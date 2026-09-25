"""Reliable Day 2 parser. Kept separate while legacy entrypoint is migrated."""
from __future__ import annotations
import argparse, json, re
from pathlib import Path

THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
SECTION_RE = re.compile(r"^\s*มาตรา\s*([๐-๙0-9]+(?:\s*/\s*[๐-๙0-9]+)?)\s*(.*)$")
HEADING_RE = re.compile(r"^\s*(หมวด|ลักษณะ|ส่วน)\s*.*$")

def normalize_digits(value: str) -> str:
    return value.translate(THAI_DIGITS)

def parse_lines(lines: list[str]) -> list[dict]:
    result, chapter, number, body = [], "ไม่ระบุหมวด", None, []
    def save() -> None:
        nonlocal body, number
        if number is None or not body: return
        text = "\n".join(body).strip()
        result.append({"chapter": chapter, "section_no": number, "text": text,
                       "paragraphs": [x for x in body if x],
                       "status": "repealed" if "ยกเลิก" in text else "amended" if "แก้ไข" in text or "เพิ่มเติม" in text else "in_force",
                       "amended_by": re.findall(r"แก้ไขโดย\s*(.+)", text)})
        body = []
    for raw in lines:
        line = re.sub(r"\s+", " ", raw.strip())
        if not line: continue
        if HEADING_RE.match(line): chapter = line; continue
        match = SECTION_RE.match(line)
        if match:
            save(); number = normalize_digits(re.sub(r"\s*", "", match.group(1)))
            body = [f"มาตรา {number}{match.group(2)}".rstrip()]
        elif number is not None: body.append(line)
    save(); return result

def parse_law_text(input_file: str | Path, output_file: str | Path) -> list[dict]:
    source = Path(input_file)
    if not source.exists(): raise FileNotFoundError(source)
    sections = parse_lines(source.read_text(encoding="utf-8").splitlines())
    target = Path(output_file); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sections, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return sections

def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("input_file"); parser.add_argument("output_file")
    args = parser.parse_args(); print(f"parsed {len(parse_law_text(args.input_file, args.output_file))} sections")

if __name__ == "__main__":
    main()
