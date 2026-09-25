"""LLM triple extraction with strict ontology validation."""
from __future__ import annotations
import argparse, csv, json, urllib.error, urllib.request
from pathlib import Path

ALLOWED = {"Right", "Duty", "Penalty", "Topic", "Actor"}
RELATIONS = {"GRANTS_RIGHT", "IMPOSES_DUTY", "HAS_PENALTY", "ABOUT", "HELD_BY", "BINDS"}

class HTTPLLMClient:
    def __init__(self, model="qwen3.5:4b", timeout=30): self.model, self.timeout = model, timeout
    def __call__(self, prompt):
        payload = json.dumps({"model": self.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0}).encode()
        request = urllib.request.Request("http://localhost:11434/v1/chat/completions", data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode())["choices"][0]["message"]["content"]

def load_topics(csv_file: str | Path) -> set[str]:
    with open(csv_file, encoding="utf-8-sig", newline="") as stream:
        return {row["topic"].strip() for row in csv.DictReader(stream) if row.get("topic", "").strip()}

def validate_triples(items: object, topics: set[str]) -> list[dict]:
    if not isinstance(items, list): raise ValueError("triple response must be a list")
    valid = []
    for item in items:
        if not isinstance(item, dict): continue
        relation = item.get("relation")
        inferred = {"GRANTS_RIGHT": ("Actor", "Right"), "IMPOSES_DUTY": ("Actor", "Duty"), "HAS_PENALTY": ("Actor", "Penalty"), "ABOUT": ("Actor", "Topic"), "HELD_BY": ("Right", "Actor"), "BINDS": ("Duty", "Actor")}
        subject_type, object_type = item.get("subject_type"), item.get("object_type")
        if relation in inferred:
            default_subject, default_object = inferred[relation]
            subject_type, object_type = subject_type or default_subject, object_type or default_object
        if subject_type not in ALLOWED or object_type not in ALLOWED: continue
        if relation not in RELATIONS or not item.get("subject") or not item.get("object"): continue
        if object_type == "Topic" and item["object"] not in topics: continue
        valid.append({"subject": str(item["subject"]), "subject_type": subject_type, "relation": relation, "object": str(item["object"]), "object_type": object_type, "source": "llm"})
    return valid

def _parse_response(response):
    if not isinstance(response, str): return response
    text = response.strip().removeprefix("```json").removesuffix("```").strip()
    try: return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("["), text.rfind("]")
        if start >= 0 and end > start: return json.loads(text[start:end + 1])
        raise

def fallback_triples(chunk: dict, topics: set[str]) -> list[dict]:
    """Conservative offline extraction when LLM is unavailable or invalid."""
    text = chunk.get("text", "")
    matches = [topic for topic in topics if topic in text]
    result = []
    if matches:
        result.append({"subject": "กฎหมายแรงงาน", "subject_type": "Actor", "relation": "ABOUT", "object": matches[0], "object_type": "Topic", "source": "deterministic_fallback"})
    if "ต้อง" in text or "หน้าที่" in text:
        result.append({"subject": "นายจ้าง", "subject_type": "Actor", "relation": "IMPOSES_DUTY", "object": f"หน้าที่ตามมาตรา {chunk.get('section_no')}", "object_type": "Duty", "source": "deterministic_fallback"})
    if "โทษ" in text or "ระวาง" in text:
        result.append({"subject": "ผู้ฝ่าฝืน", "subject_type": "Actor", "relation": "HAS_PENALTY", "object": f"โทษตามมาตรา {chunk.get('section_no')}", "object_type": "Penalty", "source": "deterministic_fallback"})
    return result

def extract_triples(chunk: dict, llm, topics: set[str], use_fallback: bool = True) -> list[dict]:
    prompt = {"task": "Extract legal triples. Return JSON array only.", "allowed_types": sorted(ALLOWED), "allowed_relations": sorted(RELATIONS), "topics": sorted(topics), "text": chunk["text"]}
    try:
        response = llm(json.dumps(prompt, ensure_ascii=False))
        response = _parse_response(response)
        valid = validate_triples(response, topics)
        return valid or (fallback_triples(chunk, topics) if use_fallback else [])
    except (ValueError, TypeError, json.JSONDecodeError, TimeoutError, urllib.error.URLError, OSError):
        return fallback_triples(chunk, topics) if use_fallback else []

def extract_file(chunks_file: str | Path, topics_file: str | Path, output_file: str | Path, llm, limit: int | None = None, target_count: int | None = None) -> int:
    topics = load_topics(topics_file)
    chunks = [json.loads(line) for line in Path(chunks_file).read_text(encoding="utf-8").splitlines() if line.strip()]
    records = []
    for chunk in chunks[:limit]:
        for triple in extract_triples(chunk, llm, topics):
            triple.update({"chunk_id": chunk["chunk_id"], "section_no": chunk["section_no"]})
            records.append(triple)
            if target_count and len(records) >= target_count: break
        if target_count and len(records) >= target_count: break
    target = Path(output_file); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in records), encoding="utf-8")
    return len(records)

if __name__ == "__main__":
    try:
        from src.llm.client import LLMClient
    except ModuleNotFoundError:
        LLMClient = HTTPLLMClient
    parser = argparse.ArgumentParser(); parser.add_argument("chunks"); parser.add_argument("topics"); parser.add_argument("--output", default="data/triples.jsonl"); parser.add_argument("--provider", choices=["ollama", "dotblue"], default="ollama"); parser.add_argument("--limit", type=int); parser.add_argument("--target", type=int, default=30); parser.add_argument("--offline", action="store_true"); args = parser.parse_args()
    llm = (lambda _prompt: "[]") if args.offline else LLMClient(args.provider, timeout=30)
    count = extract_file(args.chunks, args.topics, args.output, llm, args.limit, args.target)
    print(f"wrote {count} validated triples")
