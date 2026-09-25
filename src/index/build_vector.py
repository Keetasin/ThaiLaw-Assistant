"""Embed data/chunks.jsonl with bge-m3 into a persistent ChromaDB collection
named "law" (config.CHROMA_DIR) — the shape src/retrieval/retriever.py
already expects.

Uses reranker.passage_text() for the embedded text, not raw chunk["text"]
alone, so the dense index and the cross-encoder rerank step see the exact
same chapter/section-labeled passage shape (see that function's docstring
for why a format mismatch here would silently degrade both).
"""
import json

import chromadb
from sentence_transformers import SentenceTransformer

from src import config
from src.retrieval.reranker import passage_text


def build_vector_index():
    with open(config.CHUNKS_PATH, encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f]

    texts = [passage_text(c) for c in chunks]

    model = SentenceTransformer(config.EMBED_MODEL, device="cpu")
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=True, batch_size=16)

    client = chromadb.PersistentClient(config.CHROMA_DIR)
    try:
        client.delete_collection("law")
    except Exception:
        pass
    col = client.create_collection("law")

    col.add(
        ids=[c["chunk_id"] for c in chunks],
        embeddings=embeddings.tolist(),
        metadatas=[{"law_id": c["law_id"], "status": c["status"], "section_no": c["section_no"]} for c in chunks],
        documents=texts,
    )

    print(f"indexed {col.count()} chunks into Chroma collection 'law' at {config.CHROMA_DIR}")


if __name__ == "__main__":
    build_vector_index()
