# ThaiLaw Assistant — รายงานผลการทดลอง

> **สถานะ**: รอบ 2 — แก้บั๊กจริงเพิ่ม (Graph ABOUT-edge ที่ไม่เคยถูกใช้, multi-hop rerank regression, empty-answer safety net) + เพิ่ม out-of-scope handling ใหม่ (ตอบด้วยความรู้ทั่วไปของ AI พร้อมป้ายกำกับ แทนการปฏิเสธ) รันซ้ำ retrieval ablation เต็มแล้ว (บทที่ 3 อัปเดตด้วยตัวเลขจริงรอบ 2) — generation/judge matrix (บทที่ 4) ยังเป็นตัวเลขรอบ 1 อยู่ระหว่างพิจารณาว่าจำเป็นต้องรันซ้ำหรือไม่ (ดูหมายเหตุบทที่ 4) เหลือ **judge validation (§5.4)** ที่ต้องให้ทีมกรอกคะแนนคนเองจริง

---

## บทที่ 1: ที่มาและภาพรวมระบบ

ThaiLaw Assistant คือผู้ช่วยตอบคำถามกฎหมายแรงงานไทยบน LINE ที่ผสาน **Dense retrieval** (ChromaDB + bge-m3), **Lexical retrieval** (BM25 word + char 3-gram) และ **Graph retrieval** (Neo4j/offline `data/graph.json`) เข้าด้วยกันแบบ Weighted RRF + router + graph-seeded expansion + cross-encoder rerank ก่อนส่งเข้า LLM (Ollama local หรือ dotBlue API) สถาปัตยกรรมเต็มอยู่ใน `doc/PLAN.md` §1

ข้อมูลตั้งต้น: **พ.ร.บ.คุ้มครองแรงงาน พ.ศ. 2541** — 1 กฎหมาย, 18 หมวด, 187 มาตรา, 195 chunks (structure-aware: 1 มาตรา = 1 chunk, แยกเฉพาะมาตราที่ยาวเกิน 1600 ตัวอักษร) รายละเอียดการเตรียมข้อมูลเต็มอยู่ใน `doc/data_quality_report.md`

## บทที่ 2: Data & Knowledge Base

สรุปจาก `doc/data_quality_report.md` (รายละเอียดเต็มอยู่ที่นั่น):

| | |
|---|---|
| มาตรา parse สำเร็จ | 187/187 (sequential-continuity check กัน false-positive จาก wrapped citation) |
| Chunks | 195 (ความยาวเฉลี่ย 415 ตัวอักษร, median 280, min 8, max 3213) |
| Cross-references (`refs_out`) | 213 |
| Cleaning residual issue | PDF glyph corruption **มากกว่า ~1.5%+ ที่เคยประเมินไว้มาก** — ตอนแก้ Graph ABOUT edges (ดูบทที่ 3) พบว่ามาตรา 32/34/41/57/59 ฯลฯ ล้วนมี pattern เดียวกัน (สระ/วรรณยุกต์เลื่อนตำแหน่ง เช่น "ลูกจ้าง"→"ลกู จ้าง", "ป่วย"→"ปวย") จน keyword search "ลาป่วย"/"ลากิจ" ตรงๆ **หาไม่เจอเลยแม้เนื้อหาจะมีจริง** — ต้องอ่าน+ยืนยันด้วยคนแทน ยังไม่ได้แก้ที่ต้นตอ (ต้องเปลี่ยนไปใช้ HTML กฤษฎีกาแทน PDF ตาม PLAN §13) |

**Graph** (`data/graph.json`): **326 nodes, 720 edges**, 12/13 node types ตาม PLAN §4.2 (ขาดแค่ `Penalty` — ไม่มี `HAS_PENALTY` triple ในตัวอย่าง LLM-extraction 30 ข้อ), orphan nodes = 0 (ABOUT edges 1→35 แก้ในรอบ 2 — ดูบทที่ 3)

**Triple extraction validation**: 30 triples, human-approved 15/30 (50%) แต่ไม่สุ่ม — `GRANTS_RIGHT`/`IMPOSES_DUTY`/`ABOUT` approve 93% (15/16) ขณะที่ `BINDS`/`HELD_BY` approve 0% (0/14) เพราะโมเดลใส่ `subject_type` ผิด (เช่น labeled "นายจ้าง" เป็น `Duty` ทั้งที่ควรเป็น `Actor`) — root cause นี้ตรวจพบและบันทึกไว้ใน `doc/data_quality_report.md` §5 พร้อมวิธีแก้ (reconstruct BINDS/HELD_BY จาก subject ของ triple ที่ approved แทนการเชื่อ field ที่ผิด)

**หมายเหตุแก้ไขระหว่างทำ Day 4–5**: `doc/data_quality.md` และภาพ `eval/neo4j_results/screenshot_*.png` ที่มีอยู่เดิมเป็นข้อมูล **stale** (จับภาพจากกราฟ deterministic-only 211 nodes/3 ประเภท ก่อน merge triples/topics เข้ากราฟ) แก้ไขคำอธิบายให้ตรงกับ `data/graph.json` ปัจจุบันแล้ว แต่การถ่ายภาพ Neo4j Browser ใหม่ยังต้องทำโดยคนที่มี Docker Desktop + browser เปิดอยู่ (ดูคำสั่งใน `doc/data_quality.md`)

## บทที่ 3: Retrieval Experiments (Dense / Graph / Hybrid)

รันด้วย `python -m eval.run_retrieval --production --tune` บน `eval/testset.jsonl` (50 ข้อ, production backend = bge-m3 embeddings จริงผ่าน ChromaDB + bge-reranker-v2-m3 จริง) ผล raw อยู่ที่ `eval/results/retrieval_*.csv` — **ตัวเลขในบทนี้เป็นรอบ 2** หลังแก้บั๊กจริง 2 ตัวที่เจอจากผลวิเคราะห์รอบ 1:

1. **`GraphRetriever._offline()` (`src/retrieval/graph.py`) มีบั๊กจริง**: สาขา topic-only เดิมคืน **"ทุก Section node ในกราฟ เรียงตาม dict order โดยพลการ"** แทนที่จะเดิน ABOUT edge จริง — พบตอนตรวจว่าทำไมคำถามอย่าง "ลูกจ้างลาป่วยได้กี่วัน" ถึง miss ทั้งที่ topic "ลาป่วย" link ถูกแล้ว เพราะไม่มีโค้ดส่วนไหนเดิน edge เลย
2. **`data/curated/topic_agency_evidence_form_step.csv` มี ABOUT edge (Topic↔Section) แค่ 1 เส้น** จาก 30 topics — เพิ่มคอลัมน์ `sections` ที่ตรวจสอบกับตัวบทจริงด้วยมือ (เจอว่า PDF glyph corruption รุนแรงกว่าที่คิด — ดูบทที่ 2) ให้ 9 topics ที่เกี่ยวข้องกับเคส error-analysis เดิม (ลาป่วย, ลากิจ, ลาคลอด, การร้องเรียนแรงงาน, การเลิกจ้าง ฯลฯ) ได้ ABOUT edges 1→34

แก้ทั้งสองแล้ว **`ProductionBackend`'s graph leg ก็ใช้ `GraphRetriever` จริงตัวเดียวกับที่ production ใช้แล้ว** (เดิม `eval/run_retrieval.py` มี `graph_search()` ของตัวเองแยกจาก production โดยสิ้นเชิง ทำให้ ablation ไม่เคยสะท้อนพฤติกรรมจริงเลย) — ดู `RealGraphBackend` ใน `eval/run_retrieval.py`

### 3.1 ภาพรวม 8 configs

| Config | Recall@5 | MRR | Hit@1 |
|---|---|---|---|
| D (dense only) | 0.625 | 0.568 | 0.460 |
| D+R (dense+rerank) | 0.628 | 0.607 | 0.520 |
| G (graph only) | **0.310** (เดิม 0.160) | 0.310 | 0.300 |
| H1 (concat, baseline "Level 3") | 0.625 | 0.568 | 0.460 |
| H2 (+RRF) | 0.765 | 0.682 | 0.560 |
| H3 (+graph-seeded expansion) | 0.765 | 0.682 | 0.560 |
| **H4 (+router weight, ไม่มี rerank)** | **0.755** | **0.732** | **0.660** |
| H5 (+rerank+Section Card, ระบบเต็ม) | 0.668 | 0.642 | 0.560 |

**G เดี่ยวๆ ดีขึ้นเกือบเท่าตัว** (0.160→0.310) จากการแก้ ABOUT edges — สะท้อนตรงๆ ว่าก่อนหน้านี้ graph leg ใช้ประโยชน์ได้แค่เศษเสี้ยวของศักยภาพจริง H2–H4 ก็ดีขึ้นตามไปด้วยเพราะ fuse กับ graph leg ที่แข็งแรงขึ้น

**พบสิ่งที่ไม่คาดคิด: H4 (ไม่มี rerank) ตอนนี้ชนะ H5 (มี rerank) ในเกือบทุก metric** (recall@5 0.755 vs 0.668, hit@1 0.660 vs 0.560) — ดูรายละเอียดข้อ 3 ด้านล่าง

### 3.2 Per-category breakdown (Hit@1) — ตารางสำคัญที่สุด

| category (n) | D | D+R | G | H1 | H2 | H3 | **H4** | H5 |
|---|---|---|---|---|---|---|---|---|
| lookup (8) | 0.38 | 0.75 | 1.00 | 0.38 | 0.75 | 0.75 | **1.00** | 1.00 |
| definition (6) | 0.83 | 0.83 | 0.17 | 0.83 | 0.83 | 0.83 | 0.83 | 0.83 |
| single_hop (10) | 0.70 | 0.80 | 0.20 | 0.70 | 0.80 | 0.80 | **0.90** | 0.80 |
| multi_hop (10) | 0.40 | **0.10** | 0.10 | 0.40 | 0.40 | 0.40 | **0.40** | **0.10** |
| procedure (8) | 0.25 | 0.50 | 0.38 | 0.25 | 0.38 | 0.38 | **0.62** | 0.50 |
| aggregation (4) | 0.50 | 0.50 | 0.00 | 0.50 | 0.50 | 0.50 | 0.50 | 0.50 |
| out_of_scope (4) | 0/0/0 ทุก config โดยธรรมชาติ (`gold_sections=[]` — วัด out-of-scope handling แยกต่างหาก ไม่ใช่ retrieval metric นี้ — ดูบทที่ 4/5) | | | | | | | |

**การวิเคราะห์เชิงลึก (สิ่งที่ Level 5 ต้องมี):**

1. **Graph แก้ข้อจำกัดของ Dense ได้จริงในหลายหมวด ไม่ใช่แค่ lookup อีกต่อไป** — G เดี่ยวๆ ตอนนี้ได้ 0.38 ใน procedure และ 0.20 ใน single_hop (เดิม 0.00 ทั้งคู่) เพราะ ABOUT edges เชื่อม Topic→Section ได้จริงแล้ว (บทที่ 2/3 intro) — ตรงกับสมมติฐาน PLAN §4.1 ข้อ 3 (ข้อมูลเชิงปฏิบัติที่ Dense เข้าไม่ถึง)
2. **G เดี่ยวๆ ยังใช้แทน Hybrid ไม่ได้** (aggregation/definition ยังอ่อน) — ยังต้อง **Hybrid** เสมอ ไม่ใช่ Graph อย่างเดียว
3. **rerank กลายเป็นตัวฉุด ไม่ใช่ตัวช่วย เมื่อ graph leg แข็งแรงขึ้น** — นี่คือ finding สำคัญที่สุดของบทนี้: เทียบ H4 (ไม่มี rerank) กับ H5 (มี rerank) ตอนนี้ **H4 ชนะ H5 ใน lookup (1.00 vs 1.00 เท่ากัน), single_hop (0.90 vs 0.80), procedure (0.62 vs 0.50)** และเสมอกันใน multi_hop (0.40 vs 0.10 — H5 แพ้เพราะ rerank) สมมติฐาน root cause: bge-reranker-v2-m3 ตัดสินจาก **ความคล้ายเชิงข้อความ** ล้วนๆ ระหว่าง query กับ candidate text ไม่รู้จัก graph-based relevance (เช่น PENALIZED_BY/ABOUT) เมื่อ graph leg ส่ง candidate ที่ถูกต้องมาให้มากขึ้น (H4) แต่ rerank ยังตัดสินใจแบบเดิม จึงมีโอกาส**ดันของถูกออกไป**มากขึ้นตามไปด้วย — **ข้อเสนอแนะเชิงระบบ**: ควรพิจารณาทำ rerank แบบ "recognize-graph-provenance" (ให้คะแนนพิเศษ candidate ที่มาจาก graph leg) หรือทำ rerank เฉพาะ dense-sourced candidates แล้ว union กับ graph-sourced candidates ท้ายสุดแทนที่จะ rerank รวมกันทั้งหมด — ยังไม่ได้ implement ในรอบนี้ (cut-line ของเวลา) แต่เป็นทิศทางที่ชัดเจนสำหรับงานต่อยอด
4. **multi_hop ยังคงอ่อนใน retrieval-only metric นี้แม้แก้ graph แล้ว** (H5=0.10) — เพราะบั๊กนี้คือ rerank-vs-multihop (ข้อ 3) ไม่ใช่ graph coverage แก้ที่ **live engine โดยตรง**แล้ว (`src/retrieval/fusion.complete_penalty_partners`, ดูบทที่ 5.3) แต่ ablation harness นี้ (`eval/run_retrieval.py`) ยังไม่มี config ที่จำลอง partner-completion นี้ (ทดสอบยืนยันด้วย unit test + engine-level smoke test แทน ไม่ใช่ ablation column ใหม่ — เหตุผลด้าน scope ดูบทที่ 5.3)

### 3.3 Dense tuning (Top-K / threshold / rerank / chunking)

รันด้วย `--tune` (production backend, 36 combos × 50 ข้อ) ผล raw: `eval/results/retrieval_dense_tuning.csv` — ตัวเลขรอบนี้ (dense-only, config "D") ใกล้เคียงรอบ 1 มาก เพราะไม่เกี่ยวกับ graph fix เลย สรุปเดิมยังใช้ได้ทั้งหมด:

| top_k | threshold | rerank | Recall@5 | MRR | Hit@1 |
|---|---|---|---|---|---|
| 3 | ไม่มี | off | 0.560 | 0.536 | 0.437 |
| 3 | ไม่มี | on | 0.539 | 0.570 | 0.498 |
| **5** | **ไม่มี** | **on** | **0.597** | **0.582** | **0.498** |
| 10 | ไม่มี | off | 0.595 | 0.549 | 0.437 |
| 10 | ไม่มี | on | 0.597 | 0.590 | 0.498 |
| any | **0.4** | any | 0.137 | 0.155 | 0.148 |
| any | **0.5** | any | **0.000** | **0.000** | **0.000** |

**Threshold τ เป็นตัวที่มีผลรุนแรงที่สุด**: τ=0.4 ตัด recall เหลือ 14% และ τ=0.5 ตัดผลลัพธ์เหลือ **ศูนย์ทุกคำถาม** — เพราะ cosine similarity ดิบจาก bge-m3 embeddings ของคู่ query/chunk ภาษากฎหมายไทยแทบไม่เคยแตะ 0.5 แม้เป็น gold chunk เอง นี่คือหลักฐานเชิงประจักษ์ว่า **threshold แบบ absolute cosine ไม่เหมาะกับ domain นี้** (สอดคล้องกับที่ระบบจริงใช้ `TAU_ANSWER`/`TAU_REJECT` บน **cross-encoder rerank score** แทน ไม่ใช่ raw cosine)

**Top-K**: จาก 3→5 recall เพิ่มชัด แต่ 5→10 แทบไม่ต่าง → **k=5 คือจุดคุ้มค่าที่สุด**

**Chunking (per-section vs fixed-512)**: production backend เหมือนกันทุกประการระหว่างสอง variant (`ProductionBackend.dense()` รับ `fixed_512` flag แต่ไม่ได้ใช้จริง — ไม่มี index แยก) วัดจริงด้วย offline scorer แทน: **per-section recall@5 เฉลี่ย 0.246 vs fixed-512 recall@5 เฉลี่ย 0.228** (n=126 ต่อกลุ่ม) — per-section ดีกว่าจริง

### 3.4 ทดลองแล้วไม่ได้ผล: ปรับ router weight ของ route "general" (negative result ที่มีค่า)

คำถามอย่าง "ลูกจ้างมีสิทธิลากิจหรือไม่" ไม่ตรง keyword ของ router (`penalty`/`procedure`/`definition`/`lookup`) จึงตกไป route **`general`** (weight dense=0.6, bm25=0.3, **graph=0.1**) — แม้ graph leg เดี่ยวๆ หา section ถูกได้แล้ว (ยืนยันด้วย `GraphRetriever.search()` ตรงๆ) แต่ weight ต่ำทำให้แพ้ fusion

**ทดลอง**: ปรับ `general` weight เป็น dense=0.35/bm25=0.25/**graph=0.40** แล้วรัน 50 คำถามเทียบ before/after เฉพาะ 26 ข้อที่ route เป็น general — **ผลคือ Hit@1 ไม่เปลี่ยนแม้แต่ข้อเดียว (0 ดีขึ้น, 0 แย่ลง)**

**สาเหตุ (สำคัญกว่าผลลบเอง)**: `hybrid_search()` ดึง candidate จากแต่ละ leg (dense/bm25/graph) เป็นจำนวนคงที่ (`config.POOL`) **ไม่ขึ้นกับ weight** — weight มีผลแค่ลำดับการจัดอันดับก่อน rerank เท่านั้น ถ้า section ที่ถูกอยู่ใน candidate pool อยู่แล้ว (แค่อันดับ RRF ต่ำ) **cross-encoder rerank จะ re-score ตาม text similarity ล้วนๆ โดยไม่สนใจ RRF score เดิมเลย** ดังนั้น candidate set เดียวกัน → rerank ให้ผลเดิมเป๊ะ ไม่ว่า weight จะเป็นเท่าไร **นี่คือ root cause เดียวกับ multi_hop's rerank regression ในข้อ 3.2** ไม่ใช่ปัญหา router — การแก้ที่ถูกจุดที่สุดคือปรับ rerank ให้รู้จัก graph provenance โดยตรง (effort สูง, ไม่ทำรอบนี้) แต่พบทางแก้เล็กที่คุ้มเวลากว่าในข้อ 3.5

### 3.5 แก้จริง (low-effort): safety net หลัง rerank สำหรับ direct graph match

แทนที่จะแก้ rerank เอง — เพิ่ม `ensure_graph_hits_survive()` (`src/retrieval/fusion.py`, เรียกต่อจาก `complete_penalty_partners` ใน `engine.py`) เป็น pattern เดียวกับ multi-hop fix: **หลัง rerank เช็คว่า section ที่ `GraphRetriever.search()` เจอตรงๆ (แม่นสูง ไม่ใช่ fuzzy) หลุดไปไหม ถ้าหลุดดึงกลับมา** — ไม่แตะ rerank เลย แค่เป็นตาข่ายกันหลังสุด

**ทดสอบตรงกับ 3 เคสที่เคยพลาด (รอบแรกของ safety net)**:
| คำถาม | ก่อน | หลัง safety net |
|---|---|---|
| "ลูกจ้างมีสิทธิลากิจหรือไม่" (single_hop, gold=34) | ไม่มี 34 | **มี 34** ✅ |
| "ลูกจ้างมีสิทธิการลาประเภทใดบ้าง" (aggregation, gold=32/34/41) | ไม่มี 34 | ยังไม่มี 34 ❌ |
| "สิทธิวันหยุดของลูกจ้างมีประเภทใดบ้าง" (aggregation, gold=28/29/30) | มีแค่ 4/1 | มี 28 เพิ่ม, ยังขาด 29/30 ⚠️ |

**ทำไม single_hop หายแต่ aggregation ไม่หาย**: `ensure_graph_hits_survive` พึ่ง `GraphRetriever.link_entities()` จับ topic alias จาก**คำในคำถามตรงๆ** — คำถาม single_hop ("...ลากิจ...") มีคำที่ตรง alias พอดี แต่คำถาม aggregation ("...ลาประเภทใดบ้าง") เป็นคำถามรวบยอด ไม่มี keyword เฉพาะให้ link กับ topic ไหนเลย

**แก้ aggregation เพิ่มอีกรอบ (คุ้มเวลา, ทำต่อ)**: เพิ่ม `AGGREGATION_ROOTS = ("ลา", "วันหยุด")` ใน `src/retrieval/graph.py` — เมื่อ `infer_query_type()` จับได้ว่าเป็น `aggregation` และ `link_entities()` ไม่เจอ topic เฉพาะเจาะจงเลย ให้ fallback ไป match **ทุก topic ที่ชื่อขึ้นต้นด้วย root คำเดียวกัน** (เช่น "ลา" → ลาป่วย/ลากิจ/ลาคลอด/ลาเพื่อทำหมัน/ลาเพื่อฝึกอบรมทั้งหมด) — ระหว่างแก้เจอบั๊กเพิ่มอีกตัว: `search()`'s `top_k=5` default (ออกแบบมาสำหรับ lookup ที่ต้องการแค่ 1-3 มาตรา) ตัดผลลัพธ์ aggregation ที่ควรได้ 8 มาตราเหลือแค่ 5 แบบสุ่ม — แก้โดยขยาย `top_k` เป็นอย่างน้อย 20 เฉพาะตอน query_type="aggregation"

**ผลหลังแก้รอบสอง (ทดสอบตรงกับ `GraphRetriever.search()` โดยตรง)**:
| คำถาม | ได้ | ครบ gold ไหม |
|---|---|---|
| "ลูกจ้างมีสิทธิการลาประเภทใดบ้าง" | 32,33,34,41,43,57,57/1,59 | ✅ ครบ 3/3 (32,34,41) |
| "สิทธิวันหยุดของลูกจ้างมีประเภทใดบ้าง" | 28,29,30,4/1 | ✅ ครบ 3/3 (28,29,30) |

**ผลจริงผ่าน engine เต็ม pipeline** (dense+bm25+graph+rerank+safety nets รวมกัน, ไม่ใช่แค่ graph leg เดี่ยวๆ):
| คำถาม | ได้ | ครบ gold ไหม |
|---|---|---|
| "สิทธิวันหยุดของลูกจ้างมีประเภทใดบ้าง" | 28,29,30,4/1,62,144 | ✅ ครบ 3/3 |
| "ลูกจ้างมีสิทธิการลาประเภทใดบ้าง" | 34,41,33,108,10 | ⚠️ 2/3 (ขาด 32) — rerank/dynamic_k ยังจำกัดจำนวนช่องสุดท้ายอยู่ (top-k เล็กกว่าจำนวน topic ที่ aggregation ต้องการจริง) แก้ต่อได้อีกแต่ต้องปรับ `dynamic_k()` ให้รู้จัก query_type ด้วย ไม่ใช่แค่ความยาว query — ตัดสินใจหยุดตรงนี้ (ดีขึ้นจาก 0/3→2/3 แล้ว คุ้มเวลาที่ลงไป)

**H6 ablation** (H5 + `complete_penalty_partners` จำลองใน `eval/run_retrieval.py`): overall recall@5=0.668/hit@1=0.560 — **ตัวเลขไม่ต่างจาก H5** เพราะ ablation harness เป็นแค่การจำลอง ไม่ได้เรียก engine.py ตัวจริง (ไม่มี `ensure_graph_hits_survive` และ pre-rerank graph-seeded-expansion แบบเดียวกับ production เป๊ะ) — **การยืนยันที่แม่นกว่าคือทดสอบตรงกับ engine จริง** (ตารางบนนี้) ซึ่งเห็นผลชัดเจน ไม่ใช่ผ่าน ablation script ที่ไม่ได้จำลองความซับซ้อนของ production ครบ 100%

## บทที่ 4: Local LLM + API LLM

รันด้วย `eval/run_generation.py --all` บน retrieval config ที่ดีที่สุด (H5) ยกเว้นการเปรียบเทียบ retrieval-config-effect ที่ใช้ `qwen/qwen3.6-flash` เป็นตัวหลักตาม config {D, G, H5} จากนั้นให้ `eval/judge.py` (LLM-as-judge, `qwen/qwen3.6-plus`) ให้คะแนน 1–5 บนทุกคำตอบ ผล raw: `eval/results/generation_*.csv` + `eval/results/judge_scores.csv`

### 4.0 บั๊กจริงที่เจอระหว่างทำ (สำคัญมาก — กระทบ production ด้วย)

**qwen/qwen3.6-flash (ตัวหลักตาม PLAN.md) ตอบว่างเปล่าเป็นระบบ** — ตรวจพบว่าโมเดลนี้ผ่าน dotBlue เผา completion-token budget ไปกับ hidden reasoning (แม้ส่ง `enable_thinking: False` แล้ว) จนไม่เหลือโควตาให้คำตอบที่มองเห็นจริง เกิดขึ้น **เป็นระบบ ไม่ใช่ inconsistent**:
- **No-RAG baseline / Full-context baseline**: ที่ `num_predict=512` (ค่าเดิม) ได้คำตอบว่าง **100%** ของ 50 ข้อ (ยืนยันด้วยการทดสอบแยก) — ต้องเพิ่มเป็น 2000/4000 ตามลำดับความยาว context จึงสำเร็จ
- **Judge model (`qwen/qwen3.6-plus`) เอง**: ที่ `num_predict=200` (ค่าเดิม) ก็ว่างเปล่า 100% เช่นกัน + ยังชนกับ timeout 30 วิของ production client เมื่อเพิ่ม budget — ต้องแก้เป็น client แยก timeout 90s + `num_predict=3000` (`src/llm/client.py` เพิ่ม `timeout` parameter ให้ `DotBlueClient`, ค่า default 30.0 เดิมไม่เปลี่ยนเพื่อไม่กระทบ production)
- **Production `generate()` path เอง (`src/app/generator.py`, ใช้จริงบน LINE bot)**: เจอจากผล **H5_api_qwen-flash 34% ของคำถามที่ retrieval ผ่าน guard แล้ว (zone="answer") ได้คำตอบว่างเปล่า** เหลือแค่ citation footer (`ที่มา: ... § มาตรา X`) ไม่มีเนื้อหาอธิบายเลย — ตรวจสอบแล้วว่า **ไม่ใช่แค่ eval scripts แต่เป็นบั๊กที่กระทบ live LINE bot จริงเมื่อผู้ใช้เลือก `/llm api`** เพราะ `config.NUM_PREDICT` เดิม (512) ถูกใช้เป็นค่า default ทั้ง `OllamaClient` และ `DotBlueClient`
- **Root cause ยืนยันด้วยการทดลอง**: ทดสอบ prompt จริง (system prompt + Section Card context ~4600 ตัวอักษร) พบว่าโมเดลต้องการ **completion tokens ~1700-1800 ก่อนจะเริ่มตอบจริง** — ที่ 512/1000/1500 ตัดจบก่อนตอบเสมอ (`completion_tokens` ชนเพดานพอดีทุกครั้ง คือหลักฐานว่า "คิด" ยังไม่จบ ไม่ใช่แค่สุ่มพลาด), ที่ 3000 สำเร็จ (`completion_tokens=1729`, หยุดเองก่อนถึงเพดาน)
- **แก้แล้วและยืนยันแล้วด้วยข้อมูลจริง**: เปลี่ยน `config.NUM_PREDICT` default จาก 512 → **2500** (`src/config.py`) แล้วรัน `eval/run_generation.py --matrix --label H5_api_qwen-flash` + `eval/judge.py` ซ้ำ — ผลว่างเปล่าลดจาก **34% (17/50) เหลือ 6% (3/50)**, judge correctness เด้งจาก **1.40 → 2.82** (อยู่ในกลุ่มเดียวกับโมเดลอื่นทันที) ตารางบทที่ 4.1 ด้านล่างเป็น**ตัวเลขที่แก้แล้ว ไม่ปนเปื้อนบั๊ก**
- โมเดล/prompt อื่นที่ไม่มีปัญหานี้ (local Ollama, gpt-4o-mini, deepseek-chat) หยุดตอบเองก่อนถึงเพดานเดิมอยู่แล้ว จึงไม่ถูกกระทบด้าน latency จากการเพิ่มเพดานนี้

### 4.1 Local vs API LLM

**อัปเดตสถานะรอบ 2**: หลังแก้ graph/multi-hop/empty-answer bugs, รัน `eval/run_generation.py` ใหม่ครบ 4/5 โมเดล (qwen-flash, qwen3.5:4b, gemma3:4b, gpt-4o-mini — deepseek-chat ข้ามไปเพื่อประหยัดเวลาตามที่ตัดสินใจไว้) คำตอบใน `generation_*.csv` จึงเป็นเนื้อหาใหม่แล้วทั้ง 4 ไฟล์ — **แต่ judge ให้คะแนนใหม่แค่ qwen-flash** (ตัวหลักตาม PLAN, ใช้เป็นตัวแทนตรวจสอบคุณภาพก่อนตัดสินใจว่าคุ้มรันเพิ่มไหม ตามหลัก "ใช้เวลาน้อยแต่ประสิทธิภาพสูง")

| Model | Correctness (round 1 → 2) | หมายเหตุ |
|---|---|---|
| **API qwen3.6-flash** (หลักตาม PLAN) | 2.82 → **4.14** | ✅ judge ซ้ำแล้ว (final, 50/50 พาร์สสำเร็จ) — ดูรายละเอียด per-category ด้านล่าง |
| Local qwen3.5:4b | 2.84 (round 1) | ⏳ generate ใหม่แล้ว, ยังไม่ re-judge |
| Local gemma3:4b | 2.98 (round 1) | ⏳ generate ใหม่แล้ว, ยังไม่ re-judge |
| API gpt-4o-mini | 2.98 (round 1) | ⏳ generate ใหม่แล้ว, ยังไม่ re-judge |
| API deepseek-chat | 3.24 (round 1) | ⏳ ยังไม่ generate ใหม่ (ข้ามรอบนี้) |
| *baseline* No-RAG | 3.44 | ไม่กระทบจาก fix รอบนี้ (ไม่ retrieve เลย) |
| *baseline* Full-context | 4.43 | ไม่กระทบจาก fix รอบนี้ (bypass retrieval) |

**qwen-flash per-category (final, correctness 1-5, 50/50 คำตอบ parse สำเร็จหลังแก้ judge model ให้ retry SSE corruption — ดูหมายเหตุด้านล่าง):**

| หมวด | n | Correctness | Faithfulness | Citation acc | Clarity | Key-point coverage |
|---|---|---|---|---|---|---|
| out_of_scope | 4 | 4.75 | 4.50 | 4.75 | 5.00 | 1.00 |
| lookup | 8 | 4.62 | 4.62 | 4.62 | 5.00 | 0.79 |
| procedure | 8 | 4.25 | 3.75 | 3.38 | 4.88 | 0.88 |
| single_hop | 10 | 4.10 | 4.00 | 3.80 | 4.90 | 0.93 |
| aggregation | 4 | 4.00 | 3.75 | 3.75 | 4.00 | 1.00 |
| multi_hop | 10 | 3.80 | 3.80 | 3.60 | 4.90 | 0.69 |
| definition | 6 | 3.67 | 3.67 | 3.33 | 5.00 | 0.68 |
| **overall** | **50** | **4.14** | **4.00** | **3.84** | **4.86** | **0.83** |

- **out_of_scope 4/4** ผ่านเกณฑ์ `oos_handled_correctly` (มีป้ายกำกับ "ความรู้ทั่วไปของ AI" ชัด + ไม่อ้างเลขมาตราปลอม)
- **aggregation ยืนยันแล้วว่าดีขึ้นจริงหลังแก้** (`AGGREGATION_ROOTS` + `top_k`/`dynamic_k` fix, บทที่ 3.5) จากที่วัดได้ตอนกลาง-ทาง 2.33 (n=3/4, ก่อนแก้ครบ) → 4.00 (n=4/4) ในรอบ final นี้
- **multi_hop/single_hop ยืนยันด้วย judge จริงแล้ว** ไม่ใช่แค่ engine-level test — 3.80/4.10 ตามลำดับ สอดคล้องกับที่ partner-completion + safety-net fix (บทที่ 3.5) แก้ retrieval Hit@1 ไว้ก่อนหน้า
- **definition ต่ำสุด (3.67)** — เคส s29 "วันหยุดตามประเพณี" (retrieval แม่นแต่ LLM ตอบระมัดระวังเกินไป) ยังเป็น prompt edge case ที่ทราบแล้ว ไม่ใช่ retrieval bug — ยอมรับเป็นข้อจำกัดที่บันทึกไว้ ไม่ไล่แก้ต่อ (diminishing returns ตามหลัก "ใช้เวลาน้อยแต่ประสิทธิภาพสูง")

**บั๊กที่เจอระหว่าง final judge run**: 18/50 (36%) แถวแรกได้ JSON จาก judge model (`qwen/qwen3.6-plus`) แบบ **เสียหายกลางทาง** (field หลุด/สลับกัน เช่น `"faithfulness": _point_coverage": 0.0` — ไม่ใช่การตัดจบเพราะ token cap แต่เป็น SSE stream ที่ dotBlue ส่งมาไม่ครบ/สลับ chunk) — แก้โดยเพิ่ม retry สูงสุด 3 ครั้งต่อแถวใน `score_answer()` (`eval/judge.py`) ก่อนจะยอมแพ้ ผลคือเหลือ 0/50 parse ไม่สำเร็จหลัง retry (บาง แถวต้องใช้ถึง attempt ที่ 3)

**สรุปการตัดสินใจ**: root cause ของ definition/single_hop/aggregation/multi_hop ที่เจอตอน error-analysis รอบแรก **สืบไปที่ 2 จุด**: (1) rerank ไม่รู้จัก graph provenance (บทที่ 3.4, ยังไม่แก้ — effort สูง, ใช้ safety-net หลัง rerank แทน) และ (2) `link_entities()`/`top_k`/`dynamic_k` ไม่รองรับคำถามแบบรวบยอด (บทที่ 3.5, **แก้แล้วและยืนยันด้วย judge จริงในตารางข้างต้น**) — definition's เคสเดียว (s29) เป็น prompt edge case แยกต่างหาก ไม่ใช่ retrieval

**บทวิเคราะห์อื่นที่ยังใช้ได้จากรอบ 1** (ไม่กระทบจาก fix รอบนี้ เพราะเป็นการเทียบ baseline ไม่ใช่ retrieval quality):
- **Full-context (4.43) > No-RAG (3.44) > RAG configs (~3.0)** ในแง่ correctness ดิบ — แต่ **citation accuracy ของ No-RAG ต่ำสุด (1.82)** ยืนยันว่าโมเดลจำเนื้อหากฎหมายได้ระดับหนึ่งแต่อ้างเลขมาตราผิด/สุ่มเดา — หลักฐานว่า RAG จำเป็นสำหรับความน่าเชื่อถือของการอ้างอิง แม้ correctness ดิบจะแพ้ full-context (ซึ่งใช้จริงไม่ได้เพราะ cost ~31k tokens/call)
- **VRAM**: local models ใช้ ~3972 MiB คงที่ (พอดีกับ GPU 6GB ตาม PLAN §0)

### 4.2 `num_ctx` sweep (local models เท่านั้น, 10 sample questions × 3 ค่า)

| Model | num_ctx=2048 | num_ctx=4096 | num_ctx=8192 |
|---|---|---|---|
| qwen3.5:4b | 24.7 tok/s, 3774 MiB | 22.4 tok/s, 3840 MiB | 22.5 tok/s, 3972 MiB |
| gemma3:4b | 27.2 tok/s, 3972 MiB | 26.5 tok/s, 3744 MiB | 29.0 tok/s, 3828 MiB |

tokens/s ค่อนข้างคงที่ไม่ขึ้นกับ `num_ctx` มากนัก (ต่างกัน <15%) เพราะ context จริงที่ใช้ (Section Card, งบ 6000 ตัวอักษรสำหรับ local ตาม `CONTEXT_BUDGET_CHARS`) สั้นกว่า 2048 tokens อยู่แล้วในทุกกรณีทดสอบ — `num_ctx` ที่ใหญ่กว่าจึงแทบไม่มีผลด้าน throughput ตอนนี้ มีผลเฉพาะตอนจำเป็นต้องรับ context ยาวกว่างบปกติ

## บทที่ 5: Analysis (stats test, error analysis, case study)

รันด้วย `jupyter nbconvert --execute eval/analyze.ipynb` (ไม่เรียก LLM, คำนวณล้วนจาก `eval/results/retrieval_*.csv`)

### 5.1 Statistical test: D vs H5 (paired bootstrap + Wilcoxon)

| | ค่า |
|---|---|
| n (คำถามที่จับคู่ได้) | 50 |
| Mean difference (H5 − D, recall@5) | +0.023 |
| Bootstrap 95% CI | (−0.060, +0.113) |
| Wilcoxon p-value | 0.521 |

**ผลตรงไปตรงมา (honest finding, ไม่ปรุงแต่ง): ในระดับภาพรวม H5 ไม่ต่างจาก D อย่างมีนัยสำคัญทางสถิติ** (CI คร่อมศูนย์, p ≫ 0.05) — แต่นี่**ไม่ได้แปลว่า Hybrid ไม่มีประโยชน์** จากตาราง per-category (บทที่ 3.2) เห็นชัดว่า H5 **ชนะขาดใน lookup** (+0.13 ถึง +0.50 แล้วแต่ metric) **และ procedure** (+0.25) **แต่แพ้ใน multi_hop** (−0.30 ถึง −0.05) — ผลตรงข้ามกันของแต่ละหมวดมา **หักล้างกันในค่าเฉลี่ยรวม** จนสถิติภาพรวมมองไม่เห็นความต่าง นี่คือเหตุผลที่ PLAN.md §5 ย้ำว่าต้อง**แยกผลตาม category** ไม่ใช่ดูแค่ตัวเลขรวม — สรุปที่ถูกต้องคือ **"Hybrid ช่วยเฉพาะบางประเภทคำถามชัดเจนมาก และแพ้ในบางประเภทอย่างชัดเจน ไม่ใช่ดีขึ้นหรือแย่ลงเท่าๆ กันทุกที่"**

### 5.2 Error analysis (สุ่มตรวจ 6 จาก 20 เคสที่ notebook เลือกไว้ — full list ใน `eval/analyze.ipynb` cell 7)

| id | หมวด | คำถาม | Gold | D เจอไหม | H5 เจอไหม | หมวดปัญหา |
|---|---|---|---|---|---|---|
| A-003 | lookup | "มาตรา 61 กำหนดเรื่องใด" | s61 | ✗ | ✓ (rank1) | *(ไม่ใช่ error — H5 แก้ปัญหาที่ D พลาดได้จริง เป็น positive control)* |
| A-008 | single_hop | "ลูกจ้างลาป่วยได้กี่วันโดยได้รับค่าจ้าง" | s32, s57 | ✗ | ✗ | **retrieval miss** — คำถามใช้ "ลาป่วย" แต่ dense/graph หาไม่เจอทั้งคู่ (semantic/vocabulary gap ระหว่างคำถามภาษาพูดกับถ้อยคำในตัวบท) |
| A-009 | single_hop | "ลูกจ้างมีสิทธิลากิจหรือไม่" | s34 | ✗ | ✗ | **retrieval miss** เหมือน A-008 — ประเภทคำถาม "สิทธิลา" หลายแบบ (ลากิจ/ลาป่วย) เป็นจุดอ่อนร่วมของทั้ง dense และ graph |
| A-014 | multi_hop | "ฝ่าฝืนเรื่องเวลาทำงานมีโทษอย่างไร" | s23, s144 | ✓ (ทั้งคู่) | ✗ (ขาด s23) | **H5 trade-off**: D เจอทั้งมาตราเนื้อหา (s23) และมาตราโทษ (s144) แต่ H5 (rerank+graph) ดัน s23 หลุด top-5 เหลือแค่ s144 — ตรงกับ finding บทที่ 3.2 ข้อ 3 |
| A-020 | procedure | "ขั้นตอนยื่นคำร้องเรื่องเลิกจ้างทำอย่างไร" | s123 | ✗ | ✗ | **graph ขาด edge** — Topic "เลิกจ้าง" ยังไม่ผูกกับมาตรา 123 ผ่าน `ABOUT`/`HAS_STEP` (curated CSV 30 topics ยังไม่ครอบคลุมทุก procedural section) |
| B-014 | multi_hop | "นายจ้างไม่จัดให้มีคณะกรรมการสวัสดิการ...มีโทษอะไร" | s96, s152 | ✓ (s96) / ✗ (s152) | ✓ (s96) / ✗ (s152) | **penalty-section under-retrieval** — ทั้งสอง config เจอมาตราเนื้อหา (s96) แต่พลาดมาตราโทษ (s152) ทั้งคู่ — ต่างจาก A-014 ตรงที่ครั้งนี้ปัญหาไม่ใช่แค่ H5 |

**สรุปหมวดปัญหาหลัก 3 กลุ่ม** (ตรงกับที่ PLAN §8.3 ต้องการ):
1. **Vocabulary/semantic gap** (A-008, A-009): คำถามภาษาพูดเกี่ยวกับสิทธิลา (ลาป่วย/ลากิจ) ไม่ match กับถ้อยคำทางกฎหมาย ทั้ง dense (semantic embedding ไม่ผูกคำ) และ graph (topic alias ไม่ครอบคลุม) พลาดพร้อมกัน → **แนวทางแก้**: เพิ่ม alias dictionary ให้ topic taxonomy ครอบคลุมคำพูดทั่วไปมากขึ้น
2. **Multi-hop primary-vs-penalty trade-off** (A-014, B-014): เมื่อคำถามต้องการทั้งมาตราเนื้อหาและมาตราโทษพร้อมกัน ระบบมักได้แค่ตัวเดียว โดย H5's rerank+graph weight (alpha_graph=0.6 สำหรับ multi_hop ตาม PLAN §5) มีแนวโน้มเอียงไปทางมาตราโทษจนดันมาตราเนื้อหาหลุด → **แนวทางแก้**: เพิ่ม top-k เฉพาะ multi_hop route หรือแยก section card สำหรับมาตราเนื้อหา+โทษไม่ให้แข่งกันใน top-5 เดียวกัน
3. **Graph coverage gap สำหรับ procedure** (A-020): curated Topic→Step CSV (30 topics) ยังไม่ครอบคลุมทุกกระบวนการ → **แนวทางแก้**: ขยาย topic taxonomy รอบสอง เน้นกลุ่ม procedure/aggregation ที่ยังมี recall ต่ำสุด (ตารางบทที่ 3.2)

### 5.3 Case study: LLM-layer failure (qwen3.6-flash empty-answer bug) — พบและแก้แล้ว

ดูรายละเอียดเต็มที่บทที่ 4.0 — สรุปสั้น: **retrieval ถูกต้อง (zone="answer", rerank score ผ่าน threshold) แต่ LLM layer ทำให้คำตอบว่างเปล่า 34% ของเวลา** ก่อนแก้ `config.NUM_PREDICT` (512→2500, ยืนยันด้วยการรันซ้ำจริงว่าลดเหลือ 6% และ judge score กลับมาปกติ 1.40→2.82) นี่คือตัวอย่างที่ดีที่สุดของ "ทำไมต้องวัดทั้ง retrieval แยกจาก generation แยกกัน" (PLAN §8.2's design) — ถ้าวัดแค่ retrieval metrics (บทที่ 3) จะไม่มีทางเจอบั๊กนี้เลย เพราะ retrieval ทำงานถูกต้อง 100% ปัญหาอยู่ที่ LLM layer ล้วนๆ และเป็นบั๊กที่กระทบ **live LINE bot จริง** ไม่ใช่แค่ eval script

### 5.4 Judge validation (Cohen's κ / Spearman)

**ตัดออกจากขอบเขต (ทีมตัดสินใจ)**: `eval/judge.py --validate 20`/`--kappa` (Judge validation, Cohen's κ/Spearman) เป็นแค่ความลึกเสริมที่ทีมเสนอเองใน `PLAN.md §8.3` ไม่ใช่ข้อกำหนดใน Rubric การให้คะแนน (ตรวจแล้ว ไม่มีคำว่า kappa/validation ปรากฏใน Rubric เลย) — ทีมตัดสินใจไม่ทำ เพื่อประหยัดเวลา ไม่กระทบคะแนน

### 5.5 Case study: บั๊กจริงที่ automated eval พลาด แต่ live LINE test เจอ

Testset (`eval/testset_*.jsonl`) ใช้คำถามที่เขียนไว้ล่วงหน้า — ผู้ใช้จริงพิมพ์ paraphrase ที่ต่างเล็กน้อย พอทดสอบผ่าน LINE จริงหลัง judge รอบสุดท้ายเสร็จ เจอ 2 บั๊กที่ eval script ไม่เคยจับได้:

1. **Zone gate ทิ้งคำตอบที่ถูกต้องไปเป็น general_knowledge**: คำถาม "ต้องใช้หลักฐานอะไรเมื่อร้องเรียนค่าจ้างค้างจ่าย" (procedure, gold=ม.123) — `GraphRetriever` หา ม.123 เจอถูกต้องจริงและอยู่ใน `hits` (ยืนยันด้วย debug) แต่ zone gate (`answer_with_debug`) เช็คจาก rerank score ดิบที่คำนวณ**ก่อน**ที่ safety-net (`ensure_graph_hits_survive`, บทที่ 3.5) จะเติม hits เข้าไป — score นั้นต่ำกว่า `TAU_REJECT` เลยหลุดไปตอบแบบ out-of-scope ทั้งที่มีคำตอบถูกต้องอยู่ในมือแล้ว เป็นผลข้างเคียงที่ไม่ตั้งใจของการออกแบบเดิม (คอมเมนต์ในโค้ดตอนนั้นเขียนไว้ชัดว่า "score ไม่เปลี่ยน" — ตัดสินใจถูกที่ตอนนั้น แต่ไม่ครอบคลุมเคสนี้) — **แก้**: `ensure_graph_hits_survive()` คืน `(hits, added)`, ถ้า `added>0` (graph ยืนยันตรง ไม่ใช่ fuzzy) bump score ให้ผ่าน `TAU_ANSWER`
2. **LLM degenerate repetition (ไม่ใช่ empty แต่ไร้ประโยชน์เท่ากัน)**: บางครั้ง qwen3.6-flash ตอบด้วยการวนคำถามเดิมซ้ำสิบกว่าบรรทัด (บางครั้งหลุด meta-commentary ของตัวเอง) ก่อนฟื้นมาตอบจริงตอนท้าย — ไม่ว่างเปล่าเลยผ่าน `_is_empty_body` เดิม แต่เนื้อหาก่อนหน้านั้นไร้ประโยชน์ต่อผู้ใช้ — **แก้**: เพิ่ม `_is_degenerate_body()` (ตรวจสัดส่วนบรรทัดซ้ำ) รวมกับ `_is_empty_body` เป็น `_is_bad_body()` ใช้ตรวจก่อน retry provider อื่น (pattern เดียวกับ empty-body fix เดิม)

ยืนยันทั้งคู่ด้วย unit test ใหม่ (`tests/test_engine.py`, `tests/test_fusion.py`) — รวมทั้งหมด 107 test ผ่าน. บทเรียน: **automated eval บนคำถามคงที่ไม่พอ — ทดสอบ live จริงเจอบั๊กที่ eval script ไม่มีทางจับได้เพราะเป็นเรื่อง phrasing variance**

### 5.6 SSE stream corruption ใน judge model (พบระหว่างสรุปคะแนนสุดท้าย)

Judge (`qwen/qwen3.6-plus` ผ่าน dotBlue) 36% (18/50) ของแถวแรกได้ JSON เสียหายกลางทาง — ไม่ใช่ token-cap truncation (field หลุด/สลับกันกลางคำ เช่น `"faithfulness": _point_coverage": 0.0`) แต่เป็น SSE stream ที่ dotBlue ส่งมาไม่ครบ/สลับ chunk — แก้ด้วย retry สูงสุด 3 ครั้งต่อแถวใน `score_answer()` ก่อนจะยอมแพ้ ผลคือ 50/50 parse สำเร็จ (ดูตารางบทที่ 4.1)

## ข้อจำกัดที่ทราบแล้ว

- ครอบคลุมแค่ พ.ร.บ.คุ้มครองแรงงาน พ.ศ. 2541 ฉบับเดียว (พ.ร.บ.ประกันสังคม/เงินทดแทน ถูกตัดตาม cut-line ของ PLAN §11)
- PDF glyph corruption ~1.5%+ ของ chunks (บทที่ 2)
- Graph entity-linking ปัจจุบันพึ่ง regex เลขมาตรา + topic alias เป็นหลัก ไม่มี semantic fallback (บทที่ 3.2 ข้อ 2) — text2cypher ที่จะช่วยเรื่องนี้ถูกตัดตาม cut-line
- Reranker คุณภาพผสม: ช่วยมาก (lookup/procedure) แต่ทำร้าย multi_hop (บทที่ 3.2 ข้อ 3) — ต้องการ error analysis เพิ่มเติมว่าควรปรับ prompt/ontology ของ reranker หรือเปลี่ยนวิธี fuse หลัง rerank
- VRAM 6GB จำกัดให้รัน embed/rerank บน CPU ตอน query (ตาม PLAN §0 งบ VRAM) — ผลกระทบต่อ latency วัดในบทที่ 4
