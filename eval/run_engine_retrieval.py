"""Retrieval eval of the *real* RAGEngine (src/app/engine.py) in its three modes.

eval/run_retrieval.py's ablation rebuilds each config from parts (fixed 0.4/0.6
RRF weights, no BM25 leg, no router, no post-rerank safety nets). This script
instead calls the exact retrieval path the LINE bot runs, so Dense/Graph/Hybrid
numbers here are apples-to-apples with the generation eval (eval/run_generation.py):

  E_dense   mode="dense"   dense + BM25 (RRF) -> rerank
  E_graph   mode="graph"   graph-only route    -> expansion -> rerank -> safety nets
  E_hybrid  mode="hybrid"  router-weighted 4-way RRF -> graph-seeded expansion ->
                           rerank -> penalty-partner completion -> graph safety net

Metrics: Recall@5 / MRR / nDCG@5 / Hit@1 on the first 5 retrieved chunks, plus
`recall_ctx` over every chunk actually passed on to the LLM (can exceed 5), and
the rerank score used by the zone gate. Output: eval/results/retrieval_E_<mode>.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.run_retrieval import metrics  # noqa: E402
from src import config  # noqa: E402
from src.app.engine import RAGEngine  # noqa: E402

RESULTS = ROOT / "eval" / "results"
TESTSET = ROOT / "eval" / "testset.jsonl"
MODES = ("dense", "graph", "hybrid")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument("--suffix", default="", help="e.g. _v2 when RERANK_BLEND_W/RERANK_GRAPH_BONUS env vars are set")
    args = ap.parse_args()
    rows = [json.loads(line) for line in TESTSET.read_text(encoding="utf-8").splitlines() if line.strip()]
    engine = RAGEngine()
    for mode in args.modes.split(","):
        out = []
        t0 = time.time()
        for row in rows:
            timing = {}
            if mode == "dense":
                hits, score = engine.retrieve_and_rerank(row["question"], timing)
            else:
                hits, score, _route, _paths = engine.retrieve_and_rerank_hybrid(row["question"], mode, timing)
            predicted = [h["chunk_id"] for h in hits]
            gold = row.get("gold_sections", [])
            m = metrics(predicted, gold, k=5)
            ctx_recall = len(set(predicted) & set(gold)) / max(1, len(gold)) if gold else 0.0
            out.append({
                "id": row["id"], "category": row["category"], "config": f"E_{mode}{args.suffix}",
                "predicted": "|".join(predicted), **m, "recall_ctx": ctx_recall, "n_ctx": len(predicted),
                "rerank_score": score, "passes_answer_gate": score >= config.TAU_ANSWER,
                "latency_retrieve_s": sum(timing.values()),
            })
        path = RESULTS / f"retrieval_E_{mode}{args.suffix}.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
            w.writeheader()
            w.writerows(out)
        print(f"[engine-retrieval] {mode}: {len(out)} rows in {time.time() - t0:.0f}s -> {path}", flush=True)


if __name__ == "__main__":
    main()
