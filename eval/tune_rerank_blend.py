"""Tune fusion.blend_rerank (provenance-aware rerank) without leaking the test set.

Protocol: caches each question's pre-rerank candidates, cross-encoder scores and
graph provenance ONCE (the expensive part), then replays the engine's post-rerank
steps (blend -> complete_penalty_partners -> ensure_graph_hits_survive) over a
(w_prior, graph_bonus) grid.  Parameters are chosen on testset_a.jsonl (ids A-*)
only and then reported on the untouched testset_b.jsonl (ids B-*).

Selection rule (fixed in advance): maximise mean(Hit@1 + Recall@5) on A; ties ->
smaller (w_prior, graph_bonus) (closest to the original pure cross-encoder).

Output: eval/results/rerank_blend_grid.csv, eval/results/rerank_blend_summary.json
"""
from __future__ import annotations

import csv
import itertools
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.run_retrieval import metrics  # noqa: E402
from src import config  # noqa: E402
from src.app.engine import GRAPH_ONLY_ROUTE, RAGEngine  # noqa: E402
from src.retrieval.fusion import (blend_rerank, complete_penalty_partners, ensure_graph_hits_survive,  # noqa: E402
                                  graph_seeded_expand, hybrid_search)
from src.retrieval.graph import infer_query_type  # noqa: E402
from src.retrieval.reranker import rerank_scores  # noqa: E402
from src.retrieval.retriever import dynamic_k  # noqa: E402
from src.retrieval.router import classify_query  # noqa: E402

RESULTS = ROOT / "eval" / "results"
TESTSET = ROOT / "eval" / "testset.jsonl"
W_GRID = [0.0, 0.05, 0.1, 0.2, 0.3, 0.5]
B_GRID = [0.0, 0.05, 0.1, 0.2, 0.3, 0.5]


def prepare(engine, q):
    route = classify_query(q)
    rerank_k, fuse_k = dynamic_k(q)
    if infer_query_type(q) == "aggregation":
        rerank_k, fuse_k = max(rerank_k, 10), max(fuse_k, 15)
    graph_ids = set()
    cands = hybrid_search(engine.retriever, engine.graph_retriever, q, route, fuse_k=fuse_k, graph_ids_out=graph_ids)
    cands, _paths = graph_seeded_expand(cands, engine.graph_retriever.graph, engine.retriever)
    ce = rerank_scores(q, cands)
    return {"cands": cands, "ce": ce, "graph_ids": graph_ids, "k": rerank_k}


def replay(engine, q, prep, w, b):
    hits, score = blend_rerank(prep["cands"], prep["ce"], prep["graph_ids"], prep["k"], w, b)
    hits = complete_penalty_partners(hits, prep["cands"], engine.graph_retriever.graph)
    hits, confirmed = ensure_graph_hits_survive(hits, engine.retriever, engine.graph_retriever, q)
    if confirmed and score < config.TAU_ANSWER:
        score = config.TAU_ANSWER
    return hits, score


def main():
    rows = [json.loads(line) for line in TESTSET.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows = [r for r in rows if r["category"] != "out_of_scope"]
    engine = RAGEngine()
    cache = {}
    for i, r in enumerate(rows, 1):
        cache[r["id"]] = prepare(engine, r["question"])
        print(f"[prep] {i}/{len(rows)}", flush=True)

    grid = []
    for w, b in itertools.product(W_GRID, B_GRID):
        per = {}
        for r in rows:
            hits, _ = replay(engine, r["question"], cache[r["id"]], w, b)
            pred = [h["chunk_id"] for h in hits]
            m = metrics(pred, r["gold_sections"], k=5)
            m["recall_ctx"] = len(set(pred) & set(r["gold_sections"])) / max(1, len(r["gold_sections"]))
            m["n_ctx"] = len(pred)
            per[r["id"]] = m
        for split, pre in (("A", "A-"), ("B", "B-"), ("ALL", "")):
            sel = [v for k, v in per.items() if k.startswith(pre)]
            grid.append({"w_prior": w, "graph_bonus": b, "split": split, "n": len(sel),
                         **{k: sum(x[k] for x in sel) / len(sel) for k in ("hit_at_1", "recall_at_5", "mrr", "ndcg_at_5", "recall_ctx", "n_ctx")}})
    path = RESULTS / "rerank_blend_grid.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w_ = csv.DictWriter(f, fieldnames=list(grid[0].keys()))
        w_.writeheader()
        w_.writerows(grid)

    a_rows = [g for g in grid if g["split"] == "A"]
    best = min(a_rows, key=lambda g: (-(g["hit_at_1"] + g["recall_at_5"]), g["w_prior"] + g["graph_bonus"], g["w_prior"]))
    pick = lambda split, w, b: next(g for g in grid if g["split"] == split and g["w_prior"] == w and g["graph_bonus"] == b)
    summary = {
        "selection_rule": "max mean(hit@1+recall@5) on A; tie -> smaller (w_prior+graph_bonus)",
        "chosen": {"w_prior": best["w_prior"], "graph_bonus": best["graph_bonus"]},
        "baseline_A": pick("A", 0.0, 0.0), "baseline_B": pick("B", 0.0, 0.0), "baseline_ALL": pick("ALL", 0.0, 0.0),
        "chosen_A": pick("A", best["w_prior"], best["graph_bonus"]),
        "chosen_B": pick("B", best["w_prior"], best["graph_bonus"]),
        "chosen_ALL": pick("ALL", best["w_prior"], best["graph_bonus"]),
    }
    (RESULTS / "rerank_blend_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
