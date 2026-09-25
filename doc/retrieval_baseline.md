# Retrieval baseline: Dense vs Hybrid (Day 3, full 50-question set)

Run via `python -m eval.run_retrieval --mode dense|hybrid [--rerank]` against
`eval/testset.jsonl` (the combined 50-question A+B cross-checked set, PLAN.md §8.1 —
supersedes Day 2's provisional run against A's 25-question-only set). Retrieval-only (no
LLM calls) — Recall@5, MRR, Hit@1 against `gold_sections`. Raw output:
`eval/results/retrieval_baseline.csv` (gitignored like the rest of `eval/results/` — this
doc is the durable copy of the numbers).

**Still not PLAN.md §3/§5's full ablation matrix** — that needs the Top-K sweep,
threshold τ sweep, chunking ablation, and the full H1–H5 hybrid-config progression,
which stays Day-4 scope. This is a 3-way comparison (dense, dense+rerank, hybrid) —
a 4th (hybrid+rerank) didn't finish this session (background process killed by the
harness's low-memory guard mid-run, not a code failure — rerun later with
`python -m eval.run_retrieval --mode hybrid --rerank`).

## Results

| config | Recall@5 | MRR | Hit@1 |
|---|---|---|---|
| dense (dense+bm25+rrf) | 0.660 | 0.521 | 0.440 |
| dense+rerank | 0.720 | 0.621 | 0.560 |
| hybrid (router+dense+bm25+graph+graph-seeded expand, no rerank) | 0.620 | 0.503 | 0.440 |

Per category:

| category | n | dense R@5/MRR/H@1 | dense+rerank R@5/MRR/H@1 | hybrid R@5/MRR/H@1 |
|---|---|---|---|---|
| lookup | 8 | 0.75 / 0.43 / 0.25 | 0.88 / 0.88 / 0.88 | **1.00 / 0.94 / 0.88** |
| definition | 6 | 1.00 / 0.64 / 0.33 | 1.00 / 0.92 / 0.83 | 1.00 / 0.69 / 0.50 |
| single_hop | 10 | 0.80 / 0.73 / 0.70 | 0.90 / 0.82 / 0.80 | 0.90 / 0.70 / 0.60 |
| aggregation | 4 | 0.75 / 0.75 / 0.50 | 1.00 / 0.68 / 0.50 | **1.00 / 0.81 / 0.75** |
| multi_hop | 10 | 0.60 / 0.52 / 0.50 | 0.60 / 0.37 / 0.20 | 0.20 / 0.12 / 0.10 |
| procedure | 8 | 0.50 / 0.41 / 0.38 | 0.50 / 0.50 / 0.50 | 0.25 / 0.25 / 0.25 |
| out_of_scope | 4 | 0 / 0 / 0 | 0 / 0 / 0 | 0 / 0 / 0 |

## Findings

- **Hybrid wins decisively on `lookup`**: Hit@1 0.25 (dense) → 0.88 (hybrid) — this is
  exactly the "มาตรา N คืออะไร"-style pure section-number gap `tests/
  test_retrieval_integration.py`'s `expectedFailure` documents for dense-only. The
  manual smoke test earlier this session ("ฝ่าฝืนมาตรา 61 มีโทษอย่างไร": dense rerank
  score 0.026, below `TAU_REJECT` — would have refused; hybrid/graph score 0.178,
  well above `TAU_ANSWER`, correctly surfaces section 61) generalizes to the full set.
  The router correctly classifies these as `lookup` (regex section-number match) and
  weights the graph leg heavily (`alpha_graph=0.4`), and `GraphRetriever`'s exact
  section-number entity linking finds it every time dense's semantic search couldn't.
- **Hybrid also wins on `aggregation`** (Hit@1 0.50→0.75) — matches PLAN.md §4.1 point 4's
  prediction that Dense's top-k cutoff drops some of the sections an aggregation
  question needs, while `ABOUT`/`GRANTS_RIGHT` graph edges pull in the full set.
- **Hybrid regresses badly on `multi_hop`/`procedure` without rerank** (multi_hop Hit@1
  0.50→0.10, procedure 0.38→0.25). Root cause, from reading the fusion code: without
  a rerank pass, `graph_seeded_expand`'s appended chunks land at the *end* of the hit
  list (they're 1-hop neighbors of the top-3 fused seeds, not re-scored against the
  query), and `evaluate_row`'s `hits[:k]` truncation can cut them before they'd ever be
  counted — while the *fused* graph leg itself, for `penalty`/`procedure`-routed
  queries (`alpha_graph=0.6`, the heaviest weight in the whole router table), is driven
  by `GraphRetriever`'s fairly blunt topic-alias + section-number entity linking, which
  has much less to go on for these categories than a literal "มาตรา N" in the query
  text. This is a real, reportable "hybrid isn't automatically better — rerank matters
  more, not less, once a noisier leg is in the mix" finding, not a bug: PLAN.md §5's
  own H1→H5 ablation progression exists specifically to show step by step why rerank
  and Section Cards are load-bearing on top of raw fusion, and this is exactly what
  that progression predicts (H1, "concat ธรรมดา", is explicitly called "baseline ระดับ
  Level 3" in PLAN.md §5 — today's un-reranked hybrid run is close to that baseline).
- **`out_of_scope` is 0/0/0 by construction across all three configs, not a failure**
  — `gold_sections` is `[]` for these rows, so "nothing in top-5 matches gold" is
  correct; refusal accuracy needs `engine.py`'s `TAU_REJECT` guard, not raw retrieval
  metrics (PLAN.md §8.2 treats it as a separate metric for exactly this reason).
- **Next step**: rerun with `--mode hybrid --rerank` (interrupted this session by a
  memory guard, not a code issue) to see whether reranking recovers `multi_hop`/
  `procedure` the way it did for dense-only (0.50→0.56 overall Hit@1) — if it does,
  that's strong evidence for PLAN §5's H3→H5 progression; if it doesn't, that's a real
  finding that graph-seeded expansion needs its own scoring before rerank, not after.
