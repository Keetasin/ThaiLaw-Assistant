"""Create a human-review CSV linking triples to source law text."""
import argparse, csv, json
from pathlib import Path

def create_review(triples_file: str, chunks_file: str, output_file: str) -> int:
    triples = [json.loads(x) for x in Path(triples_file).read_text(encoding="utf-8").splitlines() if x.strip()]
    chunks = {x["chunk_id"]: x for x in (json.loads(line) for line in Path(chunks_file).read_text(encoding="utf-8").splitlines() if line.strip())}
    target = Path(output_file); target.parent.mkdir(parents=True, exist_ok=True)
    fields = ["review_id", "chunk_id", "section_no", "subject", "subject_type", "relation", "object", "object_type", "source", "law_text", "approved", "reviewer_note"]
    with target.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        for index, triple in enumerate(triples, 1):
            row = {key: triple.get(key, "") for key in fields}
            row.update({"review_id": index, "law_text": chunks.get(triple.get("chunk_id"), {}).get("text", ""), "approved": "", "reviewer_note": ""})
            writer.writerow(row)
    return len(triples)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("triples"); parser.add_argument("chunks"); parser.add_argument("--output", default="data/curated/triples_review.csv"); args = parser.parse_args()
    print(f"wrote {create_review(args.triples, args.chunks, args.output)} review rows")
