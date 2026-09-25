"""Build the two-legged BM25 index (word + char 3-gram) from data/chunks.jsonl
into the single pickle that src/retrieval/retriever.py already expects at
config.BM25_PATH: {"word": BM25Okapi, "gram": BM25Okapi, "ids": [chunk_id,...]}
where `ids` is a shared parallel array indexing both BM25 objects' doc order.

Indexes passage_text(c) (chapter + "มาตรา N" label + body), not raw
chunk["text"] alone — a section's own body almost never restates its own
number (e.g. มาตรา 61's text never contains "61" or "มาตรา"), so a literal
"มาตรา 61" lookup query — exactly the case PLAN.md §0 calls out BM25 for
("query แบบ 'มาตรา 61' ... dense มักพลาด") — would otherwise never match it.
"""
import json
import pickle

from rank_bm25 import BM25Okapi

from src import config
from src.retrieval.reranker import passage_text
from src.retrieval.thai import tok_gram, tok_word


def build_bm25_index():
    with open(config.CHUNKS_PATH, encoding="utf-8") as f:
        chunks = [json.loads(line) for line in f]

    ids = [c["chunk_id"] for c in chunks]
    texts = [passage_text(c) for c in chunks]
    word_corpus = [tok_word(t) for t in texts]
    gram_corpus = [tok_gram(t) for t in texts]

    bm25_word = BM25Okapi(word_corpus)
    bm25_gram = BM25Okapi(gram_corpus)

    with open(config.BM25_PATH, "wb") as f:
        pickle.dump({"word": bm25_word, "gram": bm25_gram, "ids": ids}, f)

    print(f"built BM25 index for {len(chunks)} chunks -> {config.BM25_PATH}")


if __name__ == "__main__":
    build_bm25_index()
