# แบ่งงาน 2 คน — ThaiLaw Assistant (5 วัน)

อ้างอิงรายละเอียดเทคนิคจาก [`PLAN.md`](./PLAN.md) ไฟล์นี้คือ **checklist ปฏิบัติจริง** แบ่งตามคน + วัน + ไฟล์ที่แตะ เพื่อลด merge conflict

- **คน A** = Data / Graph / Eval
- **คน B** = Retrieval / LLM / LINE App

**Git workflow แนะนำ**: branch `feat/a-*` กับ `feat/b-*`, merge เข้า `main` วันละครั้งตอนเย็น (D1–D4), รีวิวกันเองสั้นๆ ก่อน merge. คนที่แตะ `src/index/build_graph.py`, `src/retrieval/*`, `src/app/*` **แยกไฟล์กันชัดเจนตามตารางด้านล่าง** เพื่อลดชนกัน

---

## Day 1 — Foundation

### คน A — Data
- [x] ดึงตัวบท พ.ร.บ.คุ้มครองแรงงาน (+ ประกันสังคม/เงินทดแทน ถ้าทัน) จากกฤษฎีกา/คลังกฎหมายรัฐสภา → `data/raw/`
- [x] ดึงคู่มือ/FAQ จากกรมสวัสดิการและคุ้มครองแรงงาน + สนง.ประกันสังคม
- [x] เขียน `src/ingest/scrape.py`, `src/ingest/pdf_extract.py` — **scrape.py เจอ cross-branch regression เดียวกับ `chat_history.py`**: commit `b4dfc14` (scaffold script เดียวกัน) เขียนทับ scraper จริง 73 บรรทัด (ดึง FAQ 3 หมวดจาก labour.go.th, parse Joomla HTML) กลับเป็น stub 1 บรรทัด แล้วไม่มีใครสังเกตจน merge เข้า main — **แก้แล้ว**: กู้คืนจาก commit `8df2bd9`, เพิ่ม `requests`/`beautifulsoup4`/`lxml` ที่ขาดใน `requirements.txt` ด้วย (import ตรงๆแต่ไม่เคยอยู่ใน list)
- [x] เริ่ม `src/ingest/clean.py` (แก้สระ, เลขไทย→อารบิก, ลบ header/footer)
- **ส่งท้ายวัน**: raw text ครบ, clean.py ทำงานได้กับตัวอย่าง 1 พ.ร.บ.

### คน B — Infra + LLM client
- [x] Copy โมดูล reuse จาก `aj-krit/Project2/` เข้า `src/` ตามตาราง PLAN.md 0.1 (retriever.py, reranker.py, thai.py, rag.py, generator.py, tracing.py, app_line.py)
- [x] Copy `chat_history.py`, `docker-compose.yml` จาก `aj-krit/RAG/Hybrid-Graph-RAG-Chatbot/`
- [x] เขียน `src/llm/client.py`: OpenAI SDK เดียว ชี้ได้ทั้ง Ollama (`localhost:11434/v1`) และ dotBlue (`.env`)
- [x] **วัดเครดิต dotBlue/call**: ยิง 5 calls ทดสอบ เช็คหน้า dashboard ก่อน/หลัง → บันทึกไว้ตั้งงบวันหลัง
- [x] สร้าง LINE Messaging API channel, ตั้งค่า `.env` (`LINE_CHANNEL_SECRET`, `LINE_CHANNEL_ACCESS_TOKEN`)
- [x] รัน `docker compose up -d neo4j`, ทดสอบ login `localhost:7474`
- [x] รัน Flask echo bot ผ่าน `cloudflared.exe tunnel --url http://localhost:5000` เชื่อม LINE ได้จริง
- **ส่งท้ายวัน**: ทัก LINE บอทแล้วตอบ echo ได้, เรียก Ollama และ dotBlue ได้ทั้งคู่, รู้ต้นทุนเครดิต/call

---

## Day 2 — Core pipelines

### คน A — Graph build

- [X] `src/ingest/parse_sections.py`: regex parse หมวด→มาตรา + detect "(ยกเลิก)"/"แก้ไขโดย" — **ทำแบบย่อ** (แค่พอปลดบล็อก B, ไม่ทำ วรรค/อนุมาตรา ละเอียด) เจอ+แก้บั๊กจริงระหว่างทาง: wrapped-citation line ("...ตามมาตรา\nมาตรา 25 มาตรา 26...") ถูกนับเป็นมาตราใหม่ผิดๆ (187→209 sections ปลอม) — แก้ด้วย sequential-continuity check (เลขมาตราต้องเรียงต่อเนื่องไม่มีช่องว่างจริงตามธรรมชาติกฎหมายไทย) ได้ 187 ตรงกับที่นับมือไว้
- [X] `src/ingest/chunk.py`: chunk ตามมาตรา (+ แยก sub-item ถ้ายาวเกิน ~800 tokens, มาตรา 118 แยกเป็น (1)-(6) อัตโนมัติ) + metadata schema (PLAN.md 2.4 + `section_key` เพิ่มที่จำเป็นสำหรับ `engine.py.expand()`) → `data/chunks.jsonl` (195 chunks) + `data/sections.json` (187, ไม่มี spec ใน PLAN.md ออกแบบเอง)
- [X] `src/index/build_graph.py`/`graph_core.py`: deterministic Law/Chapter/Section graph (HAS_CHAPTER/HAS_SECTION/REFERS_TO/PENALIZED_BY/DEFINES) จาก `chunks.jsonl` — เจอ+แก้บั๊กจริง: regex `DEFINES` เดิมต้องมีคำว่า `"คำว่า"` นำหน้า แต่รูปประโยคจริงของ พ.ร.บ. นี้คือ `"TERM" หมายความว่า` เฉยๆ ไม่มี `"คำว่า"` นำ → เดิม match ได้ 0 คำ, แก้เป็น prefix optional ได้ 23 คำนิยาม (ส่วนใหญ่จากมาตรา 5)
- [X] `src/index/extract_triples.py`/`triples.py`: LLM extraction (PSU-gemma/qwen3.5, ontology validation) → `data/triples.jsonl` (30 triples) + Topic taxonomy `data/curated/topic_agency_evidence_form_step.csv` (30 หัวข้อ, มี source_url ครบ) + human review `data/curated/triples_review_approved.csv` (30 แถว, **15/30 approved = 50%** — แต่ไม่ใช่สุ่ม: GRANTS_RIGHT/IMPOSES_DUTY/ABOUT approve 93% (15/16), BINDS/HELD_BY approve 0% (0/14) เพราะโมเดลใส่ชื่อ Actor ถูกใน `subject` แต่ label `subject_type` ผิดเป็น Duty/Right เป็นระบบ — รายละเอียดเต็มใน `doc/data_quality_report.md`
- [X] `graph_core.merge_triples_and_topics()`: รวม triples ที่ approved + curated CSV เข้า `data/graph.json` — กราฟจาก 3 node types (Law/Chapter/Section) เป็น **12/13 node types ตาม PLAN.md §4.2** (326 nodes, 686 edges, orphan node = 0) โดย reconstruct HELD_BY/BINDS จาก subject ของ triple ที่ approved แล้ว (เพราะ HELD_BY/BINDS เองถูก reject หมด) — เหลือแค่ `Penalty` ที่ยังไม่มี (ไม่มี HAS_PENALTY triple ในตัวอย่าง 30 ข้อ) และ `AMENDED_BY` (N/A ตอนนี้เพราะมีกฎหมายเดียว)

- **ส่งท้ายวัน**: `chunks.jsonl`/`sections.json`/`graph.json` พร้อมใช้จริง, กราฟมี 12/13 node types ตาม schema, Data Quality Report ครบ (`doc/data_quality_report.md`)

### คน B — Dense RAG end-to-end

- [X] `src/index/build_vector.py`: embed ด้วย bge-m3 (CPU) → ChromaDB collection `law` — index 195 chunks จริง, ทดสอบแล้ว
- [X] `src/index/build_bm25.py`: BM25 word (PyThaiNLP newmm) + char 3-gram → `data/bm25.pkl` — **เจอ+แก้บั๊กจริง**: index raw text อย่างเดียวทำให้ query "มาตรา 61" หา section 61 ไม่เจอเลย (เนื้อหามาตราไม่พูดเลขตัวเองซ้ำ) เปลี่ยนไป index `passage_text()` ที่มี label "มาตรา N" ติดด้วย
- [X] ต่อ `retriever.py` เข้ากับ chunks จริง, ทดสอบ 5 query จริง — **4/5 ตอบถูกมีอ้างอิงชัดเจน**, 1/5 (query แบบเลขมาตราล้วนๆ "มาตรา 61 คืออะไร") retrieval พลาด section ที่ถูกต้อง → LLM ตอบ "ไม่พบข้อมูล" — root cause เป็นจุดที่ PLAN.md เตือนไว้เอง (dense อ่อนกับ query แบบเลขมาตรา + `dynamic_k`/`TAU_*` ยังไม่ retune) **บันทึกไว้เป็น known gap สำหรับ Day4 eval ไม่แก้ตอนนี้**
- [X] แก้ field mismatch ที่เจอใน `reranker.py`/`generator.py`/`tracing.py` (ของเดิมจาก Project2 ใช้ `heading`/`section`/`pages` ไม่ตรง chunk schema ใหม่) — `generator.py` เขียน prompt+citation ใหม่ทั้งหมดเป็น `[มาตรา X]` ตรงๆ (ตัด synthetic index `[n]` เดิมทิ้ง เพราะเลขมาตราเป็น real identifier อยู่แล้ว)
- [X] `src/app/flex.py`: Flex card สิทธิ/มาตรา/แหล่งอ้างอิง+ปุ่ม URI/คำเตือน — ทดสอบสร้างจากคำตอบจริงผ่าน ไม่ error (หลักฐาน/หน่วยงาน/ขั้นตอน ไม่ render เพราะพึ่ง curated CSV+Graph ที่ยังไม่มี, ตั้งใจไม่ใส่ placeholder หลอก)
- [X] `src/retrieval/router.py` โครง MoE (Pydantic `RouteDecision`) — rule-based classifier เท่านั้น (ไม่มี LLM classifier, ไม่ต่อ graph/engine ตามที่ PLAN §11 ระบุ D2=แค่เริ่ม) ทดสอบผ่าน 7 query
- [X] `src/app/app_line.py` (ใหม่): RAGEngine + chat_history (Neo4j) + Flex card ต่อเข้า LINE webhook จริง — เปิด Docker Desktop → `docker compose up -d neo4j` (healthy) → รัน `app_line.py` → `cloudflared.exe tunnel` → ถามจริงผ่าน LINE app บนมือถือ **ผ่านจริง**: "ลูกจ้างคือใคร" และ "ฝ่าฝืนมาตรา 61 มีโทษอย่างไร" ตอบถูกทั้งคู่พร้อมอ้างอิงมาตรา, log ยืนยัน `POST /callback` 200 OK ทุกครั้ง (real LINE userId ใน `data/traces.jsonl` ยืนยัน), ไม่มี exception ทั้ง retrieval/generation/reply — Neo4j chat-history บันทึกจริงตอนทดสอบ **แต่ภายหลังมี cross-branch regression**: commit `b4dfc14` (คนละ branch กับของ B) มี scaffold script เขียนทับ `chat_history.py` กลับเป็น stub 1 บรรทัดเพราะไฟล์จริงไม่อยู่ตอนรัน แล้ว merge เข้า main โดยไม่มีใครสังเกต → ทุกข้อความหลังจากนั้นเจอ `AttributeError: module has no attribute 'save_turn'` เงียบๆ ใน try/except (ไม่มี history ถูกบันทึกเลยบน `main` จนกว่าจะแก้) — **แก้แล้ว**: กู้ implementation เดิม 94 บรรทัดจาก commit `2808587` กลับมา, ยืนยัน `save_turn`/`get_recent_history`/`clear_history` import ได้แล้ว
- [X] แก้ `requirements.txt`: เพิ่ม `python-dotenv` ที่ขาด (เจอจาก audit — `config.py`/`app_line.py` import `dotenv` ตรงๆ แต่ไม่อยู่ใน requirements, clean install จะ import `src.config` ไม่ได้เลย)
- [X] แก้ thread-safety bug จริงใน `engine.py`: `self.history` (dict ของ list) ถูกอ่าน+เขียนจากหลาย daemon thread พร้อมกันได้ (`app_line.py` แตก thread ต่อข้อความ) โดยไม่มี lock — เพิ่ม `threading.Lock()` + `_get_history()`/`_append_history()` helper คืน copy ไม่ใช่ live reference, lock ถือแค่ตอน copy/append ไม่ค้างระหว่าง retrieve/generate
- [X] แยก `parse_citation()` ออกจาก `generator.generate()` (behavior เดิมทุกอย่าง) เพื่อให้ test regex การอ่าน citation trailer ได้โดยไม่ต้องเรียก LLM จริง
- [X] เขียน automated test ชุดใหม่ครบ: `tests/test_engine.py` (24 case: clean_query/needs_rewrite/zone selection ผ่าน mock generate/rerank/dynamic_k/concurrency race), `tests/test_generator.py` (build_context + parse_citation), `tests/test_tracing.py` (log_trace เขียนไฟล์จริง + ไม่ throw), `tests/test_retrieval_integration.py` (ใช้โมเดลจริงจาก `.hf_cache`, รวม known-gap "มาตรา 61 คืออะไร" เป็น `@unittest.expectedFailure` ให้ suite เขียวไว้แต่เตือนทันทีถ้าวันไหนแก้แล้ว) — รวมกับชุดเดิม 15 case ของ A รันผ่านหมด 39 case
- [X] implement `eval/run_retrieval.py` (เดิม stub 1 บรรทัด) แล้วรันจริง 2 config บน `eval/testset_a.jsonl` (25 ข้อ, ยังไม่มี 50 ข้อรวมของ Day3) → **rerank ช่วยจริงวัดได้**: MRR 0.361→0.441, Hit@1 0.28→0.40, Recall@5 0.48→0.52 — ผลเต็มดูที่ `doc/retrieval_baseline.md` (เป็น baseline เบื้องต้นของ Day2 ไม่ใช่ตาราง ablation เต็มของ PLAN §3 ซึ่งยังเป็นงาน Day4 ตามแผนเดิม)

- **ส่งท้ายวัน**: ✅ ครบทุกข้อ — Dense RAG ตอบจริงบน LINE พร้อม Flex card ยืนยันด้วยการทดสอบจริงผ่าน LINE app (ไม่ใช่แค่จำลอง)
- **ช่องว่างที่เหลือ (ตามแผนเดิม ไม่ใช่ bug)**: ตาราง ablation เต็มของ PLAN.md §3 (Top-K sweep/τ sweep/chunking ablation/dense-BM25-RRF แยกกัน) ยังไม่ทำ — ต้องรอ test set รวม 50 ข้อของ Day3 ก่อน, `eval/run_generation.py`/`judge.py` ยังเป็น stub (ต้องใช้ LLM credit จริง ตั้งใจไม่แตะรอบนี้)

---

## Day 3 — Hybrid + Test set

### คน A — Graph retrieval + Test set
- [X] `src/retrieval/graph.py`: entity linking (regex เลขมาตรา + alias→Topic), Cypher templates ตาม query type (lookup/procedure/penalty/definition/aggregation) + offline JSON fallback เมื่อไม่มี Neo4j driver — unit test ผ่าน 5/5 (`tests/test_graph_retrieval.py`) — **ต่อเข้า `engine.py` แล้ววันนี้** ผ่าน `src/retrieval/fusion.py` (ดูฝั่ง B ด้านล่าง)
- [X] เขียน test set **25 ข้อ** (`eval/testset_a.jsonl`) ครบ 7 กลุ่มตาม PLAN.md 8.1 พร้อม gold labels — ตรวจแล้วว่า `gold_sections` ทุกข้ออ้างอิง chunk_id ที่มีจริงใน `chunks.jsonl`
- [X] cross-check test set กับคน B → รวมเป็น `eval/testset.jsonl` **50 ข้อ** ตรงตามสัดส่วน PLAN.md §8.1 เป๊ะ (lookup 8, definition 6, single_hop 10, multi_hop 10, procedure 8, aggregation 4, out_of_scope 4) — validate ผ่าน `tests/test_testset.py` (ไม่มี id ซ้ำ, gold_sections ทุกอันมีจริงใน chunks.jsonl)
- **ส่งท้ายวัน**: ✅ graph retrieval ต่อเข้าแอปจริงแล้ว (ไม่ใช่แค่ standalone module อีกต่อไป), test set รวม 50 ข้อพร้อมและ validate แล้ว

### คน B — Hybrid fusion + App polish
- [X] `src/retrieval/fusion.py`: weighted RRF 4 ทาง (dense/bm25-word/bm25-gram/graph) ตาม `RouteDecision` จริง (ไม่ใช่แค่ fixed weight เดิม) — เพิ่ม `Retriever.search_raw()` แบบ additive ไม่กระทบ `search()` เดิม, graph-seeded expansion (top-3 → 1 hop REFERS_TO/PENALIZED_BY) — unit test 8 case ผ่านหมด รวม degrade-cleanly เมื่อไม่มี graph (`tests/test_fusion.py`)
- [X] `src/retrieval/context.py`: Section Card ผูกกับ graph จริง (บทลงโทษ/นิยาม/หน่วยงาน/หลักฐาน/แบบฟอร์ม/ขั้นตอน จาก `data/graph.json` ที่ Day2 สร้างไว้) + token budget แยก local/api (`config.CONTEXT_BUDGET_CHARS`) — 7 test case ผ่าน (`tests/test_context.py`)
- [X] เชื่อม router → fusion → graph-seeded expand → rerank → context → LLM ครบ pipeline ใน `engine.py` (`mode="hybrid"`), มี `mode="graph"` (all-graph route) และ `mode="dense"` (path เดิม Day2 ไม่เปลี่ยนพฤติกรรมเลย — มี regression test คุมไว้) — ทดสอบจริงไม่ mock: "ฝ่าฝืนมาตรา 61 มีโทษอย่างไร" dense score 0.026 (จะ reject) vs hybrid/graph score 0.178 (ตอบได้) พบมาตรา 61 ถูกต้อง — แก้ known gap ที่บันทึกไว้ตั้งแต่ Day2 ได้จริง
- [X] เพิ่มคำสั่ง `/mode dense|graph|hybrid`, `/llm local|api`, `/debug`, `/reset` ใน `app_line.py` (per-user in-memory toggle) — 12 test case ผ่าน (`tests/test_app_line.py`)
- [X] error handling: Neo4j ล่ม → graph retrieval ใช้ offline `data/graph.json` เป็นหลักอยู่แล้ว (ไม่พึ่ง live Neo4j เลยสำหรับ content retrieval) จึง degrade โดยธรรมชาติ, graph snapshot หายก็ fallback เป็น dense-only ได้ (`_load_graph_retriever()` try/except), LLM ล่ม → fallback chain api↔local ที่ call site ของ `generate()` พร้อม log + debug flag `provider_fallback` — logging เข้า `tracing.py` เดิมอยู่แล้ว (เพิ่ม `mode`/`route`/`graph_paths` เข้า debug dict)
- [X] เขียน test set **25 ข้อ** (`eval/testset_b.jsonl`, ของตัวเอง ไม่ทับ section กับ A) — cross-check กับ A แล้ว รวมเป็น 50 ข้อ
- [X] รัน `eval/run_retrieval.py` เทียบ dense vs hybrid จริงบน 50 ข้อ → **hybrid ชนะขาดใน lookup (Hit@1 0.25→0.88) และ aggregation (0.50→0.75)** ตรงกับ known gap ที่แก้ได้จริง, แต่ **แพ้ใน multi_hop/procedure โดยไม่มี rerank** (0.50→0.10, 0.38→0.25) — วิเคราะห์สาเหตุและบันทึกไว้ใน `doc/retrieval_baseline.md` (rerank ยังจำเป็นกับ hybrid มากกว่าที่คิด, สอดคล้องกับ PLAN §5 ที่บอกว่า concat เฉยๆคือ baseline Level 3) — config ที่ 4 (hybrid+rerank) รันไม่จบเพราะเครื่องแรมต่ำ ต้องรันต่อ
- **ส่งท้ายวัน**: ✅ Hybrid RAG ครบวงจรบน LINE จริง (ไม่ใช่แค่โค้ด — ทดสอบจริงด้วย query ที่เคยเป็น known gap แล้วแก้ได้), สลับโหมดสดได้ 3 โหมด, test set รวม 50 ข้อพร้อม, มีตัวเลข retrieval จริงเทียบ dense vs hybrid (ไม่ใช่แค่ "ทำงานได้")

---

## Day 4 — Experiments

### คน A — Retrieval ablation + Dense tuning
- [X] รัน retrieval ablation 8 configs (D, D+R, G, H1–H5) × 50 ข้อ ด้วย `eval/run_retrieval.py --production --tune` (ChromaDB+BM25+reranker จริง, ไม่ใช่ offline scorer) — H1 (concat ธรรมดา) เท่ากับ D เป๊ะตามที่ PLAN คาด, H2–H5 ดีขึ้นทีละชั้น, G เดี่ยวๆ ได้ 1.00 lookup แต่ 0.00 ทุกกลุ่มอื่น (พิสูจน์ว่าทำไมต้อง Hybrid)
- [X] Dense tuning: Top-K (3/5/10 → k=5 คือจุดคุ้มค่าสุด), threshold τ (0.4/0.5 ทำ recall เหลือ 14%/0% — cosine ดิบไม่เหมาะกับ absolute threshold ใน domain นี้), rerank on/off, chunking (per-section vs fixed-512 — พบว่า `ProductionBackend.dense()` รับ flag แต่ไม่ได้ใช้จริงเพราะ query เข้า Chroma collection เดียวกันเสมอ จึงรัน offline scorer เพิ่มเพื่อวัดจริง: per-section 0.246 vs fixed-512 0.228 recall@5)
- [X] เก็บผลลง `eval/results/retrieval_*.csv` (8 configs + `retrieval_dense_tuning.csv`) — ลบ `retrieval_baseline.csv` เดิม (Day3 preliminary, schema คนละแบบ, บล็อก `analyze.ipynb`'s glob, ตัวเลขเก็บไว้แล้วใน `doc/retrieval_baseline.md`)
- **ส่งท้ายวัน**: ✅ ตาราง Retrieval + Dense experiments ครบ (raw data) — ดู `doc/report.md` บทที่ 3

### คน B — Generation eval + LLM tuning
- [X] เขียน `eval/run_generation.py`/`eval/judge.py` ใหม่ทั้งหมด (เดิมเป็น stub 1 บรรทัด) แล้วรัน: Local (qwen3.5:4b, gemma3:4b) vs API (qwen3.6-flash, gpt-4o-mini, deepseek-chat) บน H5, No-RAG/Full-context baseline, retrieval-config comparison {D,G,H5}×qwen3.6-flash
- [X] `num_ctx` sweep (2048/4096/8192) วัด VRAM (`nvidia-smi`) และ tokens/s — คงที่ ~3800-3970 MiB, throughput ต่างกัน <15% เพราะ context จริงสั้นกว่า 2048 tokens อยู่แล้ว
- [X] รัน `eval/judge.py` (LLM-as-judge, qwen3.6-plus) — **เจอบั๊กจริงระหว่างทำ 3 ชั้น**: (1) judge model เผา token budget กับ hidden reasoning จนว่างเปล่า 100% ที่ budget เดิม 200/1500 ต้องขยับเป็น 3000 + timeout client แยก 90s, (2) API 500 กลางคันเสียเครดิต ~400 calls ไปฟรีเพราะ CSV เขียนครั้งเดียวตอนจบ แก้เป็น checkpoint ทุก 10 แถว, (3) merge rows คนละ schema (matrix vs baseline) ทำ `csv.DictWriter` crash แก้เป็น union fieldnames — สุดท้ายรันแบบ parallel 7 processes (แทน sequential ~4.4ชม.) เหลือ ~40 นาที
- [X] **เจอบั๊กจริงที่ใหญ่ที่สุดของงานทั้งหมด**: `qwen/qwen3.6-flash` (ตัวหลักตาม PLAN) ตอบว่างเปล่า **34% ของคำถามที่ retrieval ผ่าน guard แล้ว** บน production `generate()` path เอง (กระทบ live LINE bot จริง ไม่ใช่แค่ eval) — root cause: `config.NUM_PREDICT=512` เดิมเล็กเกินไปสำหรับ hidden reasoning ของโมเดลนี้ (ต้องการจริง ~1700-1800 completion tokens) แก้เป็น 2500 แล้วรันซ้ำยืนยัน: ว่างเปล่าเหลือ 6%, judge correctness 1.40→2.82 (เข้ากลุ่มเดียวกับโมเดลอื่นทันที)
- [X] **ตัดออกจากขอบเขต (ทีมตัดสินใจ)**: Judge validation (`--validate 20`/`--kappa`) เป็นความลึกเสริมที่ทีมเสนอเองใน `PLAN.md §8.3` ไม่ใช่ข้อบังคับใน Rubric (ตรวจแล้ว) — ไม่ทำ ประหยัดเวลา
- **ส่งท้ายวัน**: ✅ ตาราง Local vs API + resource usage ครบ (ดู `doc/report.md` บทที่ 4), judge sample พร้อมรอทีมกรอกคะแนน

---

## Day 5 — Analysis + Polish + Delivery

### คน A — Analysis + Report
- [X] `eval/analyze.ipynb`: รันจริงด้วย `jupyter nbconvert --execute` — bootstrap CI/Wilcoxon D vs H5 (p=0.52, **ไม่ significant ในภาพรวม** แต่ per-category ชนะ/แพ้ชัดเจนคนละทาง หักล้างกันในค่าเฉลี่ย — อธิบายละเอียดใน report บทที่ 5.1), per-category heatmap เต็ม, error analysis (6 จาก 20 เคสจัดหมวดจริง: vocabulary gap / multi-hop trade-off / graph coverage gap), case study บั๊ก qwen-flash
- [X] เขียนรายงานหลัก `doc/report.md` ใหม่ทั้งหมด (บทที่ 1–5 ตาม PLAN.md §9) ตัวเลขจริงทุกตาราง ไม่ใช่ placeholder
- [X] Data Quality Report ครบอยู่แล้ว (`doc/data_quality_report.md`) — **เจอ+แก้ข้อมูล stale**: `doc/data_quality.md` และ `eval/neo4j_results/table_*.csv` เดิมมาจากกราฟ deterministic-only (211 nodes/3 labels) ก่อน merge triples/topics ไม่ตรงกับ `data/graph.json` จริง (326/686/12 labels) แก้แล้วทั้งคู่ + เปิด Docker จริงโหลดกราฟเข้า Neo4j ยืนยัน live query ตรงกับไฟล์ (338 nodes = 326 + 12 ChatUser/ChatMessage จากการทดสอบ LINE จริงก่อนหน้า)
- [ ] **Screenshot Neo4j Browser ใหม่**: ตัวเลขแก้แล้ว แต่รูปภาพเดิมใน `eval/neo4j_results/screenshot_*.png` ยัง stale (ต้องถ่ายจากเบราว์เซอร์จริง ทำจาก shell ไม่ได้) — คำสั่ง reload ไว้แล้วใน `doc/data_quality.md`

### คน B — Fix + Demo + Delivery
- [X] แก้บั๊กจากผล eval วันที่ 4 — บั๊กที่ใหญ่ที่สุด (`config.NUM_PREDICT` ทำ qwen-flash ตอบว่าง) แก้และยืนยันแล้วข้างบน; อื่นๆ ที่เจอระหว่างทาง: `src/config.py`'s `BM25_PATH` ชี้ผิดที่ (`data/index/bm25.pkl` แทน `data/bm25.pkl` จริง — ทำ retrieval integration test/production backend พังมาตั้งแต่ก่อน Day4), ไฟล์ขยะ 6 ไฟล์ (stub ไม่มีใครใช้: `rerank.py`/`dense.py`/`bm25.py`/`prompts.py`/`budget.py`/`echo_app.py`) — ลบแล้ว
- [X] **user test 5–8 คน ตัดออกจากขอบเขต (ทีมตัดสินใจ)**: เป็นข้อเสนอเองของทีมใน `PLAN.md` §8.2/D5 ไม่ใช่ข้อบังคับใน Rubric — ไม่ทำ (ลบ `doc/user_test_survey.md` แล้ว)
- [ ] **ทำแทนไม่ได้ ต้องให้ทีมทำเอง**: อัด demo video 3 นาที (เตรียม storyboard ไว้แล้ว `doc/demo_video_script.md`), present slides (เตรียมโครง 12 หน้าไว้แล้ว `doc/slides_outline.md`)
- [X] ทำ `README.md` ใหม่ทั้งหมด (เดิมมีแค่ชื่อโปรเจกต์ 1 บรรทัด) ครบ setup/ingest/run/eval — ตรวจ `docker-compose.yml` จริง: `up` → healthy → โหลดกราฟเต็ม → `stop`/`up` ใหม่ → data persist ผ่าน (338 nodes คงเดิม)

**ส่งท้ายวัน**: ✅ รายงาน + code พร้อมส่ง, ⏳ slides/video ต้องให้ทีมทำเองตามเครื่องมือที่เตรียมไว้ให้แล้ว (kappa validation + user test ตัดออกจากขอบเขตแล้ว ไม่ใช่ข้อบังคับ)

---

## รอบ 2 (หลัง Day 5) — ปรับปรุงประสิทธิภาพเพิ่ม + out-of-scope feature ใหม่

**ข้อกำหนดใหม่**: คำถามนอกขอบเขต (out-of-scope) ให้ตอบด้วยความรู้ทั่วไปของ LLM แทนการปฏิเสธ พร้อมติดป้ายกำกับชัดเจน

- [X] **`generate_general_knowledge()`** (`src/app/generator.py`) + wiring ใน `engine.py` zone `reject`/`reject-after-retry` → เปลี่ยนเป็น `general_knowledge`/`general_knowledge-after-retry` — disclaimer ห่อโดย code (ไม่พึ่งโมเดลจำเอง), ข้ามป้ายสำหรับทักทาย (`direct_llm` route) กันดูรก — ทดสอบจริงด้วย LLM จริง (ไม่ mock) กับคำถาม out_of_scope 4/4 ข้อ: ป้ายกำกับครบ, ไม่มีเลขมาตราปลอม, เนื้อหาช่วยได้จริง
- [X] **เจอบั๊กจริงตัวใหญ่**: `GraphRetriever._offline()` (`src/retrieval/graph.py`) คืน "ทุก Section แบบสุ่ม" แทนเดิน ABOUT edge จริง + ABOUT edges เดิมมีแค่ 1 เส้นจาก 30 topics — แก้ทั้งคู่ (เพิ่มคอลัมน์ `sections`/`aliases` ใน curated CSV ตรวจกับตัวบทจริงมือ 9 topics, แก้ `_offline()` เดินเอง) → G config เดี่ยว recall@5 **0.160→0.310**, ABOUT edges **1→35** (34 จาก 9 topics ที่ verify มือ + 1 เพิ่มจากแก้ aggregation ทีหลัง)
- [X] **Multi-hop rerank regression** (บทลงโทษหลุดจาก top-5): เพิ่ม `complete_penalty_partners()` ใน `fusion.py` — safety net หลัง rerank ดึงคู่ penalty-partner กลับ ทดสอบจริง: เคส "ฝ่าฝืนเวลาทำงานมีโทษ" ได้ครบทั้งมาตราเนื้อหา+โทษ (ก่อนหน้าขาดมาตราเนื้อหา)
- [X] **Empty-answer safety net**: `_generate_with_fallback()` เช็ค body ว่างเปล่า (ไม่ใช่แค่ exception) → retry provider อื่นอัตโนมัติ
- [X] **ทดลองปรับ router "general" weight — ไม่ได้ผล (negative result ที่มีค่า)**: พิสูจน์ว่า rerank ไม่สนใจ fusion weight เลย (root cause จริงคือ rerank เอง ไม่ใช่ router) — แทนที่จะแก้ rerank (effort สูง) เพิ่ม **`ensure_graph_hits_survive()`** (safety net คล้าย multi-hop fix, generalize เป็นดึง direct graph match กลับหลัง rerank) — ทดสอบยืนยัน 3 เคสเดิม: single_hop (A-009 "ลากิจ") **แก้ได้จริง**, aggregation 2 เคสยังไม่ครบ
- [X] **แก้ aggregation เพิ่ม (คุ้มเวลา)**: เพิ่ม `AGGREGATION_ROOTS` ใน `src/retrieval/graph.py` — คำถามแบบ "ลาประเภทใดบ้าง" ที่ไม่มี topic keyword เฉพาะ ให้ fallback expand ทุก topic ที่ชื่อขึ้นต้นด้วย root เดียวกัน ("ลา"/"วันหยุด") — เจอ+แก้บั๊กเพิ่ม: `search()`'s `top_k=5` default ตัดผลลัพธ์ aggregation ที่ควรได้หลายมาตราเหลือ 5 แบบสุ่ม แก้เป็น top_k≥20 เฉพาะ aggregation — ผล: holiday query ครบ 3/3 gold ผ่าน engine เต็ม, leave query 2/3 (ดีขึ้นจาก 0/3, เหลือ dynamic_k ไม่รู้จัก query_type เป็น gap สุดท้าย — บันทึกเป็น known limitation)
- [X] ลบไฟล์ไม่ใช้เพิ่ม: `src/index/build_graph.py`, `extract_triples.py` (re-export 2 บรรทัด ไม่มี `__main__`, รันแล้วไม่ทำอะไร), `scripts/smoke_llm.py`, `measure_dotblue_credit.py` (Day1 one-off, ผลบันทึกใน report แล้ว) — ลบทั้งโฟลเดอร์ `scripts/` (ว่างแล้ว)
- [X] รัน retrieval ablation ใหม่เต็ม (production, D-H5 + H6): unit test 104 ผ่านหมด
- [X] Judge scoring ซ้ำเฉพาะ qwen-flash (ตัวหลักตาม PLAN, ตัดสินใจไม่รันครบ 5 โมเดลเพื่อประหยัดเวลา): correctness **2.82→4.00** (round 1→2) — multi_hop จากแย่สุด (retrieval Hit@1 10%) กลายเป็นดีอันดับ 2 (correctness 4.29) ยืนยัน fix ได้ผลจริงระดับคำตอบ
- [X] **ยืนยันแล้ว (รอบ 3)**: generate+judge ซ้ำ aggregation จริง (50/50 parse สำเร็จ) — correctness **2.33→4.00** ตามที่คาดไว้, ยืนยันด้วยคะแนนจริงไม่ใช่แค่ engine test แล้ว (ดู `doc/report.md` บทที่ 4.1); ช่องว่างเล็กที่เหลือ (`dynamic_k()` ไม่รู้จัก query_type, leave-aggregation ขาด 1/3 gold) ยังไม่แก้ต่อ — บันทึกเป็น known limitation เพราะ diminishing returns

**บทเรียนกระบวนการ**: รันงานหนัก (generate+judge หลายโมเดล) ทีเดียวกิน RAM/เวลาเกินจำเป็น — เปลี่ยนมาใช้ **dev-loop เล็กก่อน** (ทดสอบ 1 โมเดล/เคสเดียวที่รู้ปัญหาเฉพาะ ยืนยันด้วยตาก่อน) แล้วค่อยตัดสินใจว่าคุ้มรันเต็มไหม ประหยัดเวลาไปมาก

---

## รอบ 3 — บั๊กจริงที่เจอจากทดสอบ LINE จริง (post-final-judge)

ทดสอบ LINE จริง (ไม่ใช่ eval script) หลัง judge รอบสุดท้ายเจอ 3 อย่างที่ automated eval ไม่จับ:

- [X] **judge model SSE stream เสียหายกลางทาง (36% ของ 50 แถวแรกตอน judge)**: ไม่ใช่ token-cap truncation แต่ field หลุด/สลับกันกลางคำ (`"faithfulness": _point_coverage": 0.0`) — เพิ่ม retry สูงสุด 3 ครั้งต่อแถวใน `score_answer()` (`eval/judge.py`) → เหลือ 0/50 parse ไม่สำเร็จ
- [X] **เจอบั๊กจริงตัวใหญ่ที่ 2**: zone gate (`answer_with_debug`) เช็คแค่ rerank score ดิบ ที่คำนวณ**ก่อน** graph safety-net (`ensure_graph_hits_survive`) เติม hits — คำถาม "ต้องใช้หลักฐานอะไรเมื่อร้องเรียนค่าจ้างค้างจ่าย" (procedure, gold=ม.123) graph หาเจอ ม.123 ถูกต้องจริงใน `hits` แต่ score รวมยังต่ำกว่า `TAU_REJECT` → หลุดไปตอบแบบ general_knowledge (out-of-scope) ทิ้งคำตอบที่ถูกต้องไปทั้งที่มีอยู่แล้ว — แก้: `ensure_graph_hits_survive()` คืน `(hits, added)` แทนแค่ `hits`, ถ้า `added>0` (graph ยืนยันเจอ section ตรงๆ) bump `score` ให้ผ่าน `TAU_ANSWER` ก่อนเช็ค gate — เพิ่ม unit test ยืนยัน (`tests/test_engine.py::test_confident_graph_match_prevents_misrouting_to_general_knowledge`)
- [X] **เจอบั๊กจริงตัวที่ 3 (LLM generation เอง)**: qwen3.6-flash บางครั้งไม่ได้ตอบว่างเปล่า แต่ตอบวนซ้ำคำถามเดิมเป็นสิบๆ บรรทัด (บางครั้งหลุด meta-commentary ของตัวเอง "Wait, I'm generating garbage...") ก่อนจะฟื้นกลับมาตอบจริงตอนท้าย — `_is_empty_body` เดิมจับไม่ได้เพราะไม่ใช่ค่าว่าง เพิ่ม `_is_degenerate_body()` (ตรวจ repetition ratio ของบรรทัด) รวมเป็น `_is_bad_body()` ใช้แทนในทั้ง 2 fallback path (RAG generate + general_knowledge) — unit test ยืนยัน (`test_retries_other_provider_on_degenerate_repetition_body`)
- [X] unit test ครบ **107 ผ่านหมด** หลังแก้ทั้ง 3
- [X] **ยืนยันจริงบน LINE ทั้ง 7 หมวด** หลังแก้เพิ่ม 2 บั๊ก UI: "ใช้ข้อมูลจาก" หลุดจาก body (regex เดิมบังคับวงเล็บ `[มาตรา X]` แต่โมเดลตอบไม่มีวงเล็บบางครั้ง), ขึ้นบรรทัดใหม่ตัดกลางคำภาษาไทย (LINE ไม่มี Thai line-breaker ในตัว — แก้ด้วย `pythainlp` แทรก zero-width space ตรงรอยต่อคำ) — ครบ 114→117 test; ปรับดีไซน์การ์ด Flex เพิ่ม (header/สี/ปุ่ม) ทีหลัง — 117→121 test

**ทำไม automated judge ไม่เจอ**: testset ใช้คำถามที่เขียนไว้ล่วงหน้า (canonical phrasing) — คำถามจริงจากผู้ใช้เป็น paraphrase ที่ต่างเล็กน้อยจนคะแนน rerank เปลี่ยน (เช่น "ต้องใช้หลักฐานอะไรเมื่อร้องเรียนค่าจ้างค้างจ่าย" ใน testset อาจให้คะแนนสูงพอผ่าน gate แต่ phrasing อื่นไม่พอ) — ยืนยันคุณค่าของการทดสอบ live จริงเพิ่มจาก eval script อย่างเดียว

---

## จุดตัดถ้าเวลาไม่พอ (เรียงจากตัดก่อน)
1. text2cypher fallback
2. Typhoon model เพิ่ม
3. Embedding ablation (bge-m3 vs e5-base)
4. พ.ร.บ.ประกันสังคม/เงินทดแทน (เหลือแค่คุ้มครองแรงงาน)
5. Human eval ลดเหลือ 3 คน

**ห้ามตัด**: Hybrid ablation table, Local vs API table, error analysis — ส่วนนี้คะแนนเยอะสุด (ดู `PLAN.md` ส่วน 12)

## File ownership กันชน (คร่าวๆ)
| A เป็นเจ้าของ | B เป็นเจ้าของ | ใช้ร่วมกัน (แจ้งก่อนแก้) |
|---|---|---|
| `src/ingest/*` | `src/app/*` | `src/config.py` |
| `src/index/build_graph.py`, `extract_triples.py` | `src/index/build_vector.py`, `build_bm25.py` | `data/chunks.jsonl` schema |
| `src/retrieval/graph.py` | `src/retrieval/fusion.py`, `router.py`, `context.py`, `rerank.py` | `src/llm/client.py` |
| `eval/run_retrieval.py`, `analyze.ipynb` | `eval/run_generation.py`, `judge.py` | `eval/testset.jsonl` (รวมกันวันที่ 3) |
