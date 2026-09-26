# Data Quality Report

This report is generated from the checked-in `data/chunks.jsonl` and
`data/graph.json` artifacts and cross-checked against the live local Neo4j
database on 2026-09-26.

## Current snapshot

- 1 law, 187 unique sections, and 209 chunks.
- Chunk status: 193 `in_force`, 4 `amended`, and 12 `repealed`.
- Graph: 211 nodes and 505 edges in both the JSON artifact and Neo4j.
- Node labels: 1 Law, 22 Chapter, 188 Section.
- Edge types: 203 `HAS_SECTION`, 22 `HAS_CHAPTER`, 197 `REFERS_TO`, and 83 `PENALIZED_BY`.
- Parse success and cross-reference counts are computed directly from the
  current generated artifacts; the graph currently contains no orphan Section
  nodes disconnected from the Law/Chapter hierarchy.

## Known limitations

The local Neo4j HTTP transaction endpoint is available and was queried
read-only. A GUI Browser screenshot could not be produced automatically in
this shell environment; `visualisation.svg`, `graph_schema.md`, and the live
counts above provide reproducible evidence instead.
The chunk text also contains OCR errors inherited from the source extraction;
this is a data-quality issue, not silently corrected by the evaluator.
