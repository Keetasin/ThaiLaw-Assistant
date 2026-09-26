"""Build the persistent Chroma dense index from data/chunks.jsonl."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import chromadb
import torch
from sentence_transformers import SentenceTransformer
from src import config
from src.retrieval.reranker import passage_text


def load_chunks(path: str | Path = config.CHUNKS_PATH) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]

def build(chunks: list[dict], model_name: str = config.EMBED_MODEL, db_path: str = config.CHROMA_DIR, batch_size: int = 32) -> int:
    device = config.EMBED_DEVICE if config.EMBED_DEVICE == "cpu" or torch.cuda.is_available() else "cpu"
    model = SentenceTransformer(model_name, device=device)
    client = chromadb.PersistentClient(path=db_path)
    try:
        client.delete_collection("law")
    except Exception:
        pass
    collection = client.create_collection(name="law", metadata={"hnsw:space": "cosine"})
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start:start + batch_size]
        texts = [passage_text(x) for x in batch]
        collection.add(ids=[x["chunk_id"] for x in batch], embeddings=model.encode(texts, normalize_embeddings=True).tolist(), documents=texts, metadatas=[{"law_id": x.get("law_id", ""), "section_no": str(x.get("section_no", "")), "status": x.get("status", ""), "source_url": x.get("source_url", "")} for x in batch])
    return collection.count()

def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--model", default=config.EMBED_MODEL); parser.add_argument("--chunks", default=config.CHUNKS_PATH); parser.add_argument("--db", default=config.CHROMA_DIR); args = parser.parse_args()
    print(f"indexed {build(load_chunks(args.chunks), args.model, args.db)} chunks in {args.db}")

if __name__ == "__main__": main()
