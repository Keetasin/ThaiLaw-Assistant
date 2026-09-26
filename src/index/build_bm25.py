"""Build word and character 3-gram BM25 indexes."""
from __future__ import annotations
import argparse, json, pickle
from pathlib import Path
from rank_bm25 import BM25Okapi
from src import config
from src.retrieval.thai import tok_gram, tok_word

def load_chunks(path: str | Path = config.CHUNKS_PATH) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]

def build(chunks: list[dict], output: str | Path = config.BM25_PATH) -> Path:
    ids = [chunk["chunk_id"] for chunk in chunks]; texts = [chunk.get("text", "") for chunk in chunks]
    payload = {"word": BM25Okapi([tok_word(text) for text in texts]), "gram": BM25Okapi([tok_gram(text) for text in texts]), "ids": ids}
    target = Path(output); target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as stream: pickle.dump(payload, stream, protocol=pickle.HIGHEST_PROTOCOL)
    return target

def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--chunks", default=config.CHUNKS_PATH); parser.add_argument("--output", default=config.BM25_PATH); args = parser.parse_args()
    print(f"wrote BM25 index: {build(load_chunks(args.chunks), args.output)}")

if __name__ == "__main__": main()
