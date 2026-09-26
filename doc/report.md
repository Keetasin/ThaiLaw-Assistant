# ThaiLaw Assistant — Day 4–5 Report (Person A)

## 1. Objective and data

The evaluation uses the labour-law corpus in `data/chunks.jsonl`, the graph in
`data/graph.json`, and the 50-question gold set in `eval/testset.jsonl`.
Retrieval is evaluated without an LLM using Recall@5, MRR, nDCG@5, and Hit@1.

The intended production design is structure-aware, one-section-per-chunk
retrieval with graph expansion for cross-references and penalties. The data
snapshot contains 209 chunks, 187 sections, 211 graph nodes, and 505 edges.

## 2. Retrieval experiments

The evaluator implements the required ablation configurations:

| Config | Behavior |
|---|---|
| D | Dense/corpus-only retrieval |
| D+R | Dense retrieval with rerank stage |
| G | Graph retrieval |
| H1 | Dense + graph concatenation |
| H2 | Reciprocal Rank Fusion |
| H3 | Graph-seeded expansion |
| H4 | Route-weighted fusion |
| H5 | Full weighted fusion and section-card deduplication |

Raw results are in `eval/results/retrieval_*.csv`. Dense tuning covers
top-k 3/5/10, threshold none/0.4/0.5, rerank on/off, and per-section versus
fixed-512 chunking in `retrieval_dense_tuning.csv`.

## 3. Analysis

`eval/analyze.ipynb` loads the raw CSVs and produces aggregate tables,
category heatmaps, D-versus-H5 statistical comparison, 20-case error-analysis
template, and 2–3 case-study trace tables. The notebook is intentionally
reproducible and does not call an LLM.

## 4. Data quality and graph evidence

See `doc/data_quality.md` and `doc/graph_schema.md`. The local Neo4j HTTP
transaction endpoint was verified and queried read-only; its node and
relationship counts match `data/graph.json`. A GUI Neo4j Browser screenshot
is not available from this shell environment, so `data/graph.json`,
`visualisation.svg`, and `doc/graph_schema.md` are retained as reproducible
evidence.

## 5. Limitations and reproducibility

The production run uses the ChromaDB index built from `BAAI/bge-m3`, the
BM25 index, and `BAAI/bge-reranker-v2-m3`, with live Neo4j graph retrieval.
The final ablation CSVs contain 50 questions per configuration and the dense
tuning CSV contains all 36 parameter combinations by category. On the local
8-GB GPU, dense embeddings are precomputed first and the reranker is then
loaded on CUDA so the two models do not compete for VRAM.

A GUI Neo4j Browser screenshot still cannot be captured from this shell
environment; the read-only live query and repository graph snapshot are the
available evidence. Reproduce the evaluation with:

```powershell
python eval/run_retrieval.py --production --neo4j --tune
```
