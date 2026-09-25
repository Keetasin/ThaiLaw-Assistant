"""Retrieval-only evaluation: Recall@k, MRR, Hit@1 against a gold test set.

No LLM calls — this only exercises Retriever (dense+BM25+RRF), optionally
GraphRetriever+fusion (--mode hybrid), and, with --rerank, the cross-encoder
reranker, so it's free to run repeatedly.

Now runs against eval/testset.jsonl — the combined 50-question A+B
cross-checked set (PLAN.md §8.1) built in Day 3 (see doc/SPLIT.md; the
25-question eval/testset_a.jsonl this ran against in Day 2 is still there
and still usable via --testset). This script's output is Day 2/3's
retrieval/fusion comparison (dense-only vs hybrid, rerank on/off), NOT the
full Day-4 ablation matrix (Top-K sweep, threshold sweep, chunking ablation,
H1-H5 configs) that PLAN.md §3/§5 ask for — that table stays Day-4 scope.

Usage:
    python -m eval.run_retrieval [--mode dense|hybrid] [--rerank] [--k 5] [--testset eval/testset.jsonl]
"""
import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from src.app.engine import _load_graph_retriever
from src.retrieval.fusion import graph_seeded_expand, hybrid_search
from src.retrieval.reranker import rerank as rerank_fn
from src.retrieval.retriever import Retriever
from src.retrieval.router import classify_query

ROOT = Path(__file__).parents[1]


def load_testset(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def evaluate_row(retriever, graph_retriever, row, k, mode, use_rerank):
    if mode == "hybrid":
        route = classify_query(row["question"])
        hits = hybrid_search(retriever, graph_retriever, row["question"], route)
        if graph_retriever is not None:
            hits, _paths = graph_seeded_expand(hits, graph_retriever.graph, retriever)
    else:
        hits, _score = retriever.search(row["question"])

    if use_rerank:
        hits, _score = rerank_fn(row["question"], hits, k=k)
    else:
        hits = hits[:k]

    retrieved_ids = [h["chunk_id"] for h in hits]
    gold = set(row["gold_sections"])

    hit_at_1 = 1.0 if retrieved_ids and retrieved_ids[0] in gold else 0.0
    recall_at_k = 1.0 if any(cid in gold for cid in retrieved_ids) else 0.0
    rr = 0.0
    for rank, cid in enumerate(retrieved_ids, 1):
        if cid in gold:
            rr = 1.0 / rank
            break
    return {"hit_at_1": hit_at_1, "recall_at_k": recall_at_k, "mrr": rr}


def run(testset_path, k, mode, use_rerank):
    rows = load_testset(testset_path)
    retriever = Retriever()
    graph_retriever = _load_graph_retriever() if mode == "hybrid" else None

    per_row = []
    by_category = defaultdict(list)
    for row in rows:
        metrics = evaluate_row(retriever, graph_retriever, row, k, mode, use_rerank)
        metrics["id"] = row["id"]
        metrics["category"] = row["category"]
        per_row.append(metrics)
        by_category[row["category"]].append(metrics)

    def _avg(rows_, key):
        return sum(r[key] for r in rows_) / len(rows_) if rows_ else 0.0

    summary = []
    for category, rows_ in sorted(by_category.items()):
        summary.append({
            "category": category, "n": len(rows_),
            "recall_at_k": round(_avg(rows_, "recall_at_k"), 3),
            "mrr": round(_avg(rows_, "mrr"), 3),
            "hit_at_1": round(_avg(rows_, "hit_at_1"), 3),
        })
    summary.append({
        "category": "OVERALL", "n": len(per_row),
        "recall_at_k": round(_avg(per_row, "recall_at_k"), 3),
        "mrr": round(_avg(per_row, "mrr"), 3),
        "hit_at_1": round(_avg(per_row, "hit_at_1"), 3),
    })
    return summary


def write_csv(summary, output_file, config_label, k, testset_path):
    target = Path(output_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    is_new = not target.exists()
    with target.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["config", "k", "testset", "category", "n", "recall_at_k", "mrr", "hit_at_1"])
        if is_new:
            writer.writeheader()
        for row in summary:
            writer.writerow({"config": config_label, "k": k, "testset": Path(testset_path).name, **row})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--testset", default=str(ROOT / "eval/testset.jsonl"))
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--mode", choices=("dense", "hybrid"), default="dense")
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument("--output", default=str(ROOT / "eval/results/retrieval_baseline.csv"))
    args = parser.parse_args()

    config_label = f"{args.mode}" + ("+rerank" if args.rerank else "")
    summary = run(args.testset, args.k, args.mode, args.rerank)
    write_csv(summary, args.output, config_label, args.k, args.testset)

    print(f"config={config_label} k={args.k} testset={Path(args.testset).name}")
    print(f"{'category':<15} {'n':>3} {'recall@k':>9} {'mrr':>6} {'hit@1':>6}")
    for row in summary:
        print(f"{row['category']:<15} {row['n']:>3} {row['recall_at_k']:>9} {row['mrr']:>6} {row['hit_at_1']:>6}")
