# Data Quality Report (short snapshot)

Generated directly from the checked-in `data/chunks.jsonl` and `data/graph.json`
artifacts. Full detail (chunking design, cleaning, triple-validation precision,
known limitations) is in `doc/data_quality_report.md` — this file is just the
current-numbers snapshot for quick cross-checking.

## Current snapshot (as of 2026-09-27, round 2)

- 1 law, 187 unique sections, 195 chunks (2 sections split into 8 pieces total).
- Section status: 177 `in_force`, 10 `repealed`.
- Graph (`data/graph.json`): **326 nodes, 720 edges**, 12/13 of PLAN.md §4.2's
  node types present (missing only `Penalty` — no `HAS_PENALTY` triple in the
  30-triple LLM-extraction sample; not a code gap, see `data_quality_report.md` §4).
- Node labels: Section 188, Topic 30, Evidence 24, Term 23, Step 19, Chapter 18,
  Right 7, Duty 7, Actor 4, Agency 3, Form 2, Law 1.
- Edge types: REFERS_TO 211, HAS_SECTION 187, PENALIZED_BY 98, HANDLED_BY 30,
  REQUIRES_EVIDENCE 30, USES_FORM 30, HAS_STEP 30, DEFINES 23, HAS_CHAPTER 18,
  ABOUT 35, GRANTS_RIGHT 7, HELD_BY 7, IMPOSES_DUTY 7, BINDS 7.
- Orphan nodes: 0 (checked across all labels).
- **ABOUT edges 1 → 35** (round-2 fix, see `data_quality_report.md` §4): the
  curated topic CSV gained a hand-verified `sections` column for 9 topics
  directly tied to known retrieval-miss test cases, and a real bug in
  `GraphRetriever._offline()` that ignored ABOUT edges entirely (returned
  arbitrary sections instead) is fixed. Verified live in Neo4j: `MATCH
  ()-[r:ABOUT]->() RETURN count(r)` → 35, matching `data/graph.json`.

## Known limitations

**`eval/neo4j_results/table_node_counts.csv`/`table_relationship_counts.csv`
are now current** (regenerated live against the reloaded graph above, matches
this snapshot exactly). **The `screenshot_*.png`/`graph_*.svg` image files are
still STALE** (211-node deterministic-only graph, pre-dating both the Day2
topic/triple merge and this round's ABOUT-edge fix) — re-taking them needs a
real browser open on Neo4j Browser (http://localhost:7474), which isn't
automatable from this shell:
```bash
docker compose up -d neo4j
python -m src.index.graph_core data/chunks.jsonl --neo4j \
  --triples data/triples.jsonl --review data/curated/triples_review_approved.csv \
  --topics data/curated/topic_agency_evidence_form_step.csv
```

**The PDF/glyph corruption is more pervasive than the original ~1.5%+ estimate
suggested.** That number came from one narrow regex signature; while manually
verifying section text for the ABOUT-edge fix above, sections 32/34/41/57/59
etc. all showed the same underlying pattern — dropped tone marks (่/้) and
misplaced vowels (ลูกจ้าง → ลกู จ้าง, ป่วย → ปวย) — which is why an automated
keyword search for "ลาป่วย"/"ลากิจ" against the raw section text found **zero**
matches despite those exact leave types being present (section 32 *is* sick
leave, just spelled "ลาปวย" in the corrupted text). The section→topic mapping
above was done by manually reading and verifying each section instead of
keyword-matching the corrupted text, which sidesteps the problem for this one
fix but doesn't fix the underlying corruption — that still needs the กฤษฎีกา
HTML re-source PLAN.md §13 already flags, which is out of scope for this round.
