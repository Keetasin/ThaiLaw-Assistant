"""Hybrid retrieval: dense (bge-m3) + BM25-word + BM25-3gram -> RRF.

The 3-gram leg is the primary typo defense: a single misspelled character
breaks newmm word tokenization completely, but most character trigrams
still match. Copied from aj-krit/Project2/core/retriever.py.

Project2 measured plain (1,1,1)-weighted RRF scoring WORSE than dense alone
(R@1 0.778 vs 0.889) on its corpus, so dense is weighted 2.0 here as a
starting point — re-measure on the legal corpus in Day 4 ablation
(doc/PLAN.md §5, configs H2 vs a naive-RRF variant).

STAGED FOR DAY 2: requires data/chunks.jsonl, data/bm25.pkl and a populated
ChromaDB collection named "law" — none of which exist until A's Day-2 ingest
finishes. Do not import Retriever() before then.
"""
import json
import pickle
from collections import defaultdict

import chromadb
import numpy as np
from sentence_transformers import SentenceTransformer

from src import config
from src.retrieval.thai import tok_gram, tok_word


def dynamic_k(query):
    """Short/simple questions use less k (less noise, faster); long or
    multi-part questions use more k. Returns (rerank_k, fuse_k)."""
    tokens = tok_word(query)
    n = len(tokens)
    multi = any(w in query for w in ("และ", "หรือ", "รวมถึง", "กับ")) or query.count("?") > 1
    if n <= 8 and not multi:
        return 3, 4
    if n >= 16 or multi:
        return 8, 10
    return config.RERANK_K, config.FUSE_K


class Retriever:
    def __init__(self, collection_name="law"):
        self.emb = SentenceTransformer(config.EMBED_MODEL, device="cpu")
        client = chromadb.PersistentClient(config.CHROMA_DIR)
        self.col = client.get_collection(collection_name)

        with open(config.BM25_PATH, "rb") as f:
            bm = pickle.load(f)
        self.bm25_word = bm["word"]
        self.bm25_gram = bm["gram"]
        self.bm25_ids = bm["ids"]

        with open(config.CHUNKS_PATH, encoding="utf-8") as f:
            self.chunks = {c["chunk_id"]: c for c in (json.loads(line) for line in f)}

    def _top_bm25(self, bm25, tokens, n):
        if not tokens:
            return []
        scores = bm25.get_scores(tokens)
        order = np.argsort(-scores)[:n]
        return [self.bm25_ids[i] for i in order if scores[i] > 0]

    def search_raw(self, query, pool=config.POOL):
        """Return the three raw ranked chunk_id lists (dense, bm25-word,
        bm25-gram) without fusing them, plus the top dense cosine score.
        `search()` below is the fixed-weight (2.0/1.0/1.0) dense-only-mode
        path; `src/retrieval/fusion.py` calls this directly to do its own
        router-weighted RRF across dense/bm25/graph (PLAN.md §5 point 2)."""
        qv = self.emb.encode([query], normalize_embeddings=True)
        dense = self.col.query(query_embeddings=qv.tolist(), n_results=pool)
        dense_ids = dense["ids"][0]
        top_cosine = 1.0 - dense["distances"][0][0] if dense_ids else 0.0

        word_ids = self._top_bm25(self.bm25_word, tok_word(query), pool)
        gram_ids = self._top_bm25(self.bm25_gram, tok_gram(query), pool)
        return dense_ids, word_ids, gram_ids, top_cosine

    def search(self, query, pool=config.POOL, fuse_k=config.FUSE_K):
        dense_ids, word_ids, gram_ids, top_cosine = self.search_raw(query, pool)
        fused = rrf([(dense_ids, 2.0), (word_ids, 1.0), (gram_ids, 1.0)], k=fuse_k)
        hits = [self.chunks[cid] for cid, _ in fused if cid in self.chunks]
        return hits, top_cosine


def rrf(weighted_rank_lists, k=10, c=config.RRF_C):
    scores = defaultdict(float)
    for lst, weight in weighted_rank_lists:
        for rank, doc_id in enumerate(lst):
            scores[doc_id] += weight / (c + rank + 1)
    return sorted(scores.items(), key=lambda x: -x[1])[:k]
