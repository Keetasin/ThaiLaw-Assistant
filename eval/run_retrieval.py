"""Retrieval-only ablations and dense tuning experiments."""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import urllib.request
import base64
from collections import defaultdict
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
RESULTS = ROOT / "eval" / "results"
CHUNKS = ROOT / "data" / "chunks.jsonl"
GRAPH = ROOT / "data" / "graph.json"
TESTSET = ROOT / "eval" / "testset.jsonl"
TESTSET_A = ROOT / "eval" / "testset_a.jsonl"
TOKEN_RE = re.compile(r"[\w๐-๙]+", re.UNICODE)
SECTION_RE = re.compile(r"(?:มาตรา|section)\s*([0-9๐-๙]+(?:\s*/\s*[0-9๐-๙]+)?)", re.I)
CONFIGS = ("D", "D+R", "G", "H1", "H2", "H3", "H4", "H5")
TUNING = {"top_k": (3, 5, 10), "threshold": (None, 0.4, 0.5), "rerank": (False, True), "chunking": ("per-section", "fixed-512")}


def _norm(text: str) -> str:
    return text.translate(str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789"))


def load_rows(path: Path = TESTSET) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []
    return rows or [json.loads(line) for line in TESTSET_A.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_chunks(path: Path = CHUNKS) -> dict[str, dict]:
    return {row["chunk_id"]: row for row in (json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip())}


def tokenize(text: str) -> set[str]:
    return set(TOKEN_RE.findall(_norm(text).casefold()))


class CorpusBackend:
    """Deterministic local backend; real model backends can be injected later."""
    def __init__(self, chunks: dict[str, dict], graph: dict | None = None):
        self.chunks = chunks
        self.edge_by_source: dict[str, list[str]] = defaultdict(list)
        for edge in (graph or {}).get("edges", []):
            self.edge_by_source[edge["source"]].append(edge["target"])

    def dense(self, query: str, limit: int = 20, threshold: float | None = None, fixed_512: bool = False) -> list[tuple[str, float]]:
        query_tokens = tokenize(query)
        sections = {x.group(1).replace(" ", "") for x in SECTION_RE.finditer(_norm(query))}
        scored = []
        for cid, chunk in self.chunks.items():
            text = chunk.get("text", "")[:512] if fixed_512 else chunk.get("text", "")
            score = len(query_tokens & tokenize(text)) / max(1, len(query_tokens))
            if chunk.get("section_no") in sections:
                score += 1.0
            if score > 0 and (threshold is None or score >= threshold):
                scored.append((cid, score))
        return sorted(scored, key=lambda item: (-item[1], item[0]))[:limit]

    def graph_search(self, query: str, limit: int = 10) -> list[tuple[str, float]]:
        sections = {x.group(1).replace(" ", "") for x in SECTION_RE.finditer(_norm(query))}
        result = {}
        for cid, chunk in self.chunks.items():
            if chunk.get("section_no") in sections:
                result[cid] = 1.0
            if any(ref in sections for ref in chunk.get("refs_out", [])):
                result[cid] = max(result.get(cid, 0), 0.8)
        return sorted(result.items(), key=lambda item: (-item[1], item[0]))[:limit]


class Neo4jBackend(CorpusBackend):
    """Read-only graph backend through Neo4j's HTTP transaction endpoint."""
    def __init__(self, chunks: dict[str, dict], uri: str, user: str, password: str, database: str = "neo4j"):
        super().__init__(chunks)
        self.endpoint = uri.replace("bolt://", "http://").replace(":7687", ":7474") + f"/db/{database}/tx/commit"
        self.auth = base64.b64encode(f"{user}:{password}".encode()).decode()

    def _query(self, statement: str, parameters: dict) -> list[list]:
        payload = json.dumps({"statements": [{"statement": statement, "parameters": parameters}]}).encode()
        request = urllib.request.Request(self.endpoint, data=payload, headers={"Authorization": f"Basic {self.auth}", "Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=10) as response:
            body = json.loads(response.read().decode())
        if body.get("errors"):
            raise RuntimeError(body["errors"])
        result = body.get("results", [{}])[0]
        return [item.get("row", []) for item in result.get("data", [])]

    def graph_search(self, query: str, limit: int = 10) -> list[tuple[str, float]]:
        sections = sorted({x.group(1).replace(" ", "") for x in SECTION_RE.finditer(_norm(query))})
        if not sections:
            return []
        rows = self._query(
            "MATCH (s:Section) WHERE s.section_no IN $section_nos "
            "OPTIONAL MATCH (s)-[:REFERS_TO|PENALIZED_BY]->(related:Section) "
            "RETURN s.section_no, collect(related.section_no) LIMIT $top_k",
            {"section_nos": sections, "top_k": limit},
        )
        result = []
        for section_no, related in rows:
            result.append((f"LPA2541-s{section_no}-p1", 1.0))
            for related_no in related or []:
                result.append((f"LPA2541-s{related_no}-p1", 0.8))
        unique = {}
        for cid, score in result:
            if cid in self.chunks:
                unique[cid] = max(unique.get(cid, 0), score)
        return sorted(unique.items(), key=lambda item: (-item[1], item[0]))[:limit]


class ProductionBackend(CorpusBackend):
    """Chroma + BM25-capable dense retriever with optional live Neo4j graph."""
    def __init__(self, chunks: dict[str, dict], use_neo4j: bool = True):
        super().__init__(chunks)
        from src.retrieval.retriever import Retriever
        self.retriever = Retriever()
        self.graph_backend = neo4j_backend(chunks) if use_neo4j else CorpusBackend(chunks, json.loads(GRAPH.read_text(encoding="utf-8")))
        self._rerank_cache = {}
        self._rerank_by_query = {}
        self._dense_cache = {}

    def dense(self, query: str, limit: int = 20, threshold: float | None = None, fixed_512: bool = False) -> list[tuple[str, float]]:
        key = (query, threshold, fixed_512)
        if key in self._dense_cache:
            return self._dense_cache[key][:limit]
        vector = self.retriever.emb.encode([query], normalize_embeddings=True)
        result = self.retriever.col.query(query_embeddings=vector.tolist(), n_results=max(10, limit))
        pairs = [(cid, 1.0 - distance) for cid, distance in zip(result["ids"][0], result["distances"][0])]
        filtered = [(cid, score) for cid, score in pairs if threshold is None or score >= threshold]
        self._dense_cache[key] = filtered
        return filtered[:limit]

    def graph_search(self, query: str, limit: int = 10) -> list[tuple[str, float]]:
        return self.graph_backend.graph_search(query, limit)

    def rerank_results(self, query: str, result: list[tuple[str, float]], limit: int) -> list[tuple[str, float]]:
        from src.retrieval.reranker import rerank
        candidate_ids = tuple(cid for cid, _score in result)
        key = (query, candidate_ids)
        ranked = self._rerank_cache.get(key)
        if ranked is None:
            prior = self._rerank_by_query.get(query)
            if prior and all(cid in prior for cid in candidate_ids):
                ranked = [self.chunks[cid] for cid in prior if cid in candidate_ids]
            else:
                candidates = [self.chunks[cid] for cid, _score in result if cid in self.chunks]
                ranked, _score = rerank(query, candidates, k=len(candidates))
                if candidate_ids and all(cid in self.chunks for cid in candidate_ids):
                    self._rerank_by_query[query] = [chunk["chunk_id"] for chunk in ranked]
            self._rerank_cache[key] = ranked
        ranked = ranked[:limit]
        return [(chunk["chunk_id"], 1.0 - index / max(1, len(ranked))) for index, chunk in enumerate(ranked)]

    def warm_dense(self, rows: list[dict], tuning: bool = False) -> None:
        """Populate all dense variants before handing VRAM to the reranker."""
        thresholds = TUNING["threshold"] if tuning else [None]
        chunkings = TUNING["chunking"] if tuning else ["per-section"]
        for row in rows:
            for threshold in thresholds:
                for chunking in chunkings:
                    self.dense(row["question"], 10, threshold, chunking == "fixed-512")

    def release_embedder(self) -> None:
        """Release the embedding model so a GPU reranker can load on small GPUs."""
        import gc
        import torch
        self.retriever.emb = None
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


def neo4j_backend(chunks: dict[str, dict]) -> Neo4jBackend:
    """Build a backend from the repository .env without importing app code."""
    values = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    uri = os.getenv("NEO4J_URI", values.get("NEO4J_URI", "bolt://localhost:7687"))
    user = os.getenv("NEO4J_USER", values.get("NEO4J_USER", "neo4j"))
    password = os.getenv("NEO4J_PASSWORD", values.get("NEO4J_PASSWORD", "changeme"))
    return Neo4jBackend(chunks, uri, user, password)


def rrf(*ranked_lists: Iterable[tuple[str, float]], limit: int = 10, weights: Iterable[float] | None = None) -> list[tuple[str, float]]:
    weights = list(weights or [1.0] * len(ranked_lists)); scores = defaultdict(float)
    for weight, items in zip(weights, ranked_lists):
        for rank, (cid, _score) in enumerate(items, 1):
            scores[cid] += weight / (60 + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]


def retrieve(row: dict, backend: CorpusBackend, config: str, top_k: int = 5, threshold: float | None = None, rerank: bool = False, chunking: str = "per-section") -> list[str]:
    dense = backend.dense(row["question"], max(10, top_k), threshold, chunking == "fixed-512")
    graph = backend.graph_search(row["question"], max(10, top_k)) if config not in ("D", "D+R") else []
    if config == "D": result = dense
    elif config == "D+R": result = dense
    elif config == "G": result = graph
    elif config == "H1": result = list(dict.fromkeys(dense + graph))
    elif config == "H2": result = rrf(dense, graph)
    elif config == "H3": result = rrf(dense, graph + [(target, score * .8) for cid, score in dense for target in backend.edge_by_source.get(cid, [])])
    elif config == "H4": result = rrf(dense, graph, weights=(.4, .6))
    elif config == "H5": result = rrf(dense, graph, weights=(.4, .6))
    else: raise ValueError(f"unknown config: {config}")
    if rerank or config in ("D+R", "H5"):
        if hasattr(backend, "rerank_results"):
            result = backend.rerank_results(row["question"], result, top_k)
        else:
            result = sorted(result, key=lambda item: (-item[1], item[0]))
    return [cid for cid, _score in result[:top_k]]


def metrics(predicted: list[str], gold: list[str], k: int = 5) -> dict[str, float]:
    gold_set = set(gold); top = predicted[:k]
    hits = [cid in gold_set for cid in top]
    dcg = sum(1 / math.log2(index + 2) for index, hit in enumerate(hits) if hit)
    ideal = sum(1 / math.log2(index + 2) for index in range(min(len(gold_set), k)))
    first = next((index + 1 for index, cid in enumerate(predicted) if cid in gold_set), None)
    return {"recall_at_5": len(set(top) & gold_set) / max(1, len(gold_set)), "mrr": 1 / first if first else 0.0, "ndcg_at_5": dcg / ideal if ideal else 0.0, "hit_at_1": float(bool(top and top[0] in gold_set))}


def run(backend: CorpusBackend, rows: list[dict], configs: Iterable[str] = CONFIGS, output_dir: Path = RESULTS) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True); all_results = []
    for config in configs:
        output = []
        for row in rows:
            predicted = retrieve(row, backend, config); output.append({"id": row["id"], "category": row["category"], "config": config, "predicted": "|".join(predicted), **metrics(predicted, row.get("gold_sections", []))})
        path = output_dir / f"retrieval_{config.replace('+', '_')}.csv"
        with path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(output[0]) if output else ["id", "category", "config"]); writer.writeheader(); writer.writerows(output)
        all_results.extend(output)
    return all_results


def run_tuning(backend: CorpusBackend, rows: list[dict], output_dir: Path = RESULTS) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True); path = output_dir / "retrieval_dense_tuning.csv"
    fields = ["top_k", "threshold", "rerank", "chunking", "category", "recall_at_5", "mrr", "ndcg_at_5", "hit_at_1"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        for top_k in TUNING["top_k"]:
            for threshold in TUNING["threshold"]:
                for rerank in TUNING["rerank"]:
                    for chunking in TUNING["chunking"]:
                        grouped = defaultdict(list)
                        for row in rows:
                            grouped[row["category"]].append(metrics(retrieve(row, backend, "D", top_k, threshold, rerank, chunking), row.get("gold_sections", [])))
                        for category, values in grouped.items():
                            writer.writerow({"top_k": top_k, "threshold": threshold, "rerank": rerank, "chunking": chunking, "category": category, **{key: sum(value[key] for value in values) / len(values) for key in fields[5:]}})
    return path


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--tune", action="store_true"); parser.add_argument("--tune-only", action="store_true", help="run only dense tuning"); parser.add_argument("--neo4j", action="store_true", help="use Neo4j for graph retrieval"); parser.add_argument("--production", action="store_true", help="use Chroma/BM25 embeddings and reranker"); parser.add_argument("--output", type=Path, default=RESULTS); args = parser.parse_args()
    chunks = load_chunks(); backend = ProductionBackend(chunks, args.neo4j) if args.production else (neo4j_backend(chunks) if args.neo4j else CorpusBackend(chunks, json.loads(GRAPH.read_text(encoding="utf-8")))); rows = load_rows()
    if args.neo4j:
        (backend.graph_backend if args.production else backend)._query("RETURN 1 AS ok", {})
    if args.production:
        backend.warm_dense(rows, tuning=(args.tune or args.tune_only))
        backend.release_embedder()
    if not args.tune_only:
        run(backend, rows, output_dir=args.output)
    if args.tune or args.tune_only: run_tuning(backend, rows, args.output)
    mode = "production+Neo4j" if args.production and args.neo4j else "production" if args.production else "Neo4j" if args.neo4j else "offline"
    print(f"evaluated {len(rows)} questions with {mode} backend; results: {args.output}")


if __name__ == "__main__": main()
