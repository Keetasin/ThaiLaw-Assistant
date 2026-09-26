# Data Quality Report — พ.ร.บ.คุ้มครองแรงงาน พ.ศ. 2541

Covers Person A's Day 2 data + graph pipeline, per `doc/PLAN.md` §2.5 ("Data Quality
Report") and §4.3 point 5 (triple-validation precision). Numbers below are computed
directly from the committed pipeline output (`data/chunks.jsonl`, `data/sections.json`,
`data/graph.json`, `data/curated/*.csv`) as of the current pipeline code — regenerate
with `python -m src.ingest.chunk && python -m src.index.graph_core data/chunks.jsonl`
to reproduce.

## 1. Corpus overview

| | count |
|---|---|
| Law | 1 (พ.ร.บ.คุ้มครองแรงงาน พ.ศ. 2541, LPA2541) |
| หมวด (chapter) | 18 |
| มาตรา (section), parsed | **187 / 187** — sequential-continuity check (`parse_sections.py`'s `_is_valid_next`) confirms no gaps and no false-positive splits from wrapped citations |
| Section status | 177 `in_force`, 10 `repealed` |
| Chunks (`data/chunks.jsonl`) | 195 (187 sections; 2 sections split into 8 pieces total — see §2) |
| Cross-references extracted (`refs_out`) | 213 |

## 2. Chunking design & token distribution

Rule (PLAN §2.3): 1 มาตรา = 1 chunk, split only when a section exceeds
`SPLIT_THRESHOLD_CHARS = 1600` — first on blank-line paragraph boundaries, then on
`(1)/(2)/...` sub-item boundaries, else left whole rather than risk a bad split
(`_split_long_section`, `src/ingest/chunk.py`).

Chunk length (characters, no whitespace-delimited tokens in Thai so char count is the
practical proxy):

| bucket | chunks |
|---|---|
| ≤200 | 59 |
| 201–500 | 80 |
| 501–1000 | 44 |
| 1001–1600 | 10 |
| >1600 | 2 |

min 8, max 3213, mean 415, median 280. Only 2 sections (มาตรา 5's ~30-term definitions
list, and one other) exceeded the 1600-char threshold and got split — matches the
empirical measurement already documented in `chunk.py`'s own docstring.

## 3. Cleaning: before/after

**Works correctly** (`src/ingest/clean.py`):
- Thai digit → Arabic: `๑` → `1` (verified across all 187 sections' `section_no`).
- Header/footer stripping (`เล่ม ... ตอนที่`, page numbers, ราชกิจจานุเบกษา lines,
  `about:blank`/timestamp lines from the source website).
- Footnote bracket markers `[88]` etc. removed from body text.
- Trailing amendment-history/fee-schedule block cut at the royal-signature line, so it
  doesn't get scanned as if it were section body text (this is what makes the 187/187
  parse rate possible — the raw document restates unrelated "มาตรา N" numbers from
  *amending acts'* own internal numbering in that trailing block, which would otherwise
  corrupt section boundaries).

**Known residual limitation** — PDF text-extraction glyph corruption:

```
expected: มาตรา 1 พระราชบัญญัตินี้เรียกว่า "พระราชบัญญัติคุ้มครองแรงงาน..."
actual:   มาตรา 1 พระราชบัญญัตินีเรยี กว่า "พระราชบัญญัติคุ้มครองแรงงาน..."
```

`นี้เรียก` → `นีเรยี ` — a dropped tone mark (้) plus a transposed vowel/consonant pair,
sourced from the underlying PDF's text layer (`pdf_extract.py`'s PyMuPDF extraction),
not from `clean.py` — confirmed by re-running `clean_text_pipeline()` fresh against
`data/raw/*_raw.txt`: byte-for-byte identical corrupted output. This is a font/glyph
-encoding issue in the source PDF, not a bug in the cleaning regex; it needs a
Thai-specific glyph-reordering correction (or switching the primary source to the
กฤษฎีกา HTML version, already flagged as the risk mitigation in PLAN §13) rather than a
regex patch, which risks corrupting the ~98% of text that extracts correctly.

Quantified: a narrow heuristic scan (the specific `นีเ` corruption signature —
missing-tone-mark-before-เ) hits **3 of 195 chunks (~1.5%)**. This undercounts total
corruption since it only matches one specific pattern; it's reported as a lower bound
on affected chunks, not a full corruption rate. Text remains human-readable around each
instance and section/citation parsing is unaffected (these glyph swaps happen inside
prose, not inside มาตรา numbers or chapter markers, which is why 187/187 sections still
parse correctly).

## 4. Graph: node/edge counts

`data/graph.json`, built by `src/index/graph_core.py`:

| label | nodes | | edge type | edges |
|---|---|---|---|---|
| Section | 188 | | HAS_SECTION | 187 |
| Chapter | 18 | | HAS_CHAPTER | 18 |
| Evidence | 24 | | REFERS_TO | 211 |
| Term | 23 | | PENALIZED_BY | 98 |
| Topic | 30 | | DEFINES | 23 |
| Step | 19 | | HANDLED_BY | 30 |
| Right | 7 | | REQUIRES_EVIDENCE | 30 |
| Duty | 7 | | USES_FORM | 30 |
| Actor | 4 | | HAS_STEP | 30 |
| Agency | 3 | | GRANTS_RIGHT | 7 |
| Form | 2 | | HELD_BY | 7 |
| Law | 1 | | IMPOSES_DUTY | 7 |
| | | | BINDS | 7 |
| **total** | **326** | | **total** | **686** |

vs. PLAN.md §4.2's 13-node-type target: **12/13 present**. `Penalty` is the one
missing type — no `HAS_PENALTY` triple happened to be in the 30-triple LLM-extraction
sample (see §5), so no Penalty nodes exist yet; this is a sampling gap, not a code gap
(`graph_core.merge_triples_and_topics` already handles `HAS_PENALTY` if/when one is
extracted). `AMENDED_BY` (Law→Law) isn't applicable with a single-statute corpus.

Degree distribution (Section nodes): min 1, max 73, mean 4.48 — the max-73 section is
one heavily cross-referenced/penalized section, consistent with PLAN §4.1's premise
that penalty/reference structure clusters around a few hub sections.

**Orphan nodes: 0** (checked across all labels, not just Section).

Before this fix, `graph.json` had only 3 real node types (Law/Chapter/Section) — the 30
LLM-extracted triples and the 30-row Topic/Agency/Evidence/Form/Step CSV existed as
disconnected files, never merged into the graph. See §5 for how the merge is gated.

## 5. Triple extraction & human validation (PLAN §4.3 point 5)

30 triples extracted (`data/triples.jsonl`, 29 via LLM + 1 deterministic fallback),
reviewed by hand (`data/curated/triples_review_approved.csv`):

**Approval: 15/30 (50%)**, but the split by relation type is not uniform — it's
systematic:

| relation | approved | rejected |
|---|---|---|
| GRANTS_RIGHT | 7 | 1 |
| IMPOSES_DUTY | 7 | 0 |
| ABOUT | 1 | 0 |
| BINDS | 0 | 11 |
| HELD_BY | 0 | 3 |

**GRANTS_RIGHT/IMPOSES_DUTY/ABOUT: 93% approved (15/16).** **BINDS/HELD_BY: 0% approved
(0/14).** Root cause, found by inspecting the rejected rows: for every BINDS/HELD_BY
triple, the extractor put the correct Actor's name in the `subject` field but
mislabeled `subject_type` as `Duty`/`Right` (e.g.
`{"subject": "นายจ้าง", "subject_type": "Duty", "relation": "BINDS", "object": "ลูกจ้าง", "object_type": "Actor"}`
— "นายจ้าง" (employer) is obviously an Actor, not a Duty). `triples.py`'s
`validate_triples` only checks that `subject_type`/`object_type` are *in* the allowed
ontology set, not that they match the *named entity* — so these passed schema
validation while being semantically backwards. This is a genuine small-LLM extraction
failure mode specific to relations where subject and object are both plausibly
Actor-shaped strings.

**How this is handled in the graph** (`graph_core.merge_triples_and_topics`): only
reviewer-approved triples are merged (`--review data/curated/triples_review_approved.csv`
gates the merge by default). Since BINDS/HELD_BY have zero valid rows, those edges
aren't sourced from their own triples — instead they're reconstructed from the
*subject* of each approved GRANTS_RIGHT/IMPOSES_DUTY triple (review did confirm those
subjects correctly), recovering PLAN §4.2's intended topology
`(Section)-[:GRANTS_RIGHT]->(Right)-[:HELD_BY]->(Actor)` and
`(Section)-[:IMPOSES_DUTY]->(Duty)-[:BINDS]->(Actor)` from data that actually passed
review, rather than merging the broken direct triples.

## 6. Known limitations / future work

- Penalty nodes: none yet (§4) — next extraction batch should target
  penalty-bearing sections specifically (regex-detectable via "โทษ"/"ระวางโทษ", already
  used by the deterministic `PENALIZED_BY` pass) to get `HAS_PENALTY` triples sampled.
- BINDS/HELD_BY direct extraction: the small-model mislabeling pattern in §5 suggests
  the extraction prompt should require restating which side is the Actor explicitly,
  or these two relations should be derived deterministically from GRANTS_RIGHT/
  IMPOSES_DUTY triples going forward rather than extracted independently.
- PDF glyph corruption (§3): affects ~1.5%+ of chunks; recommend re-sourcing from
  the กฤษฎีกา HTML edition if time permits (per PLAN §13's own risk mitigation),
  otherwise document as an accepted data-quality limitation in the final report.
- Graph is currently built but not yet consumed by the live retrieval path
  (`src/retrieval/graph.py`/`router.py` exist and are unit-tested but `engine.py`
  doesn't call them) — that wiring is Person B's Day 3 scope per `doc/SPLIT.md`, not
  a data-quality issue.
