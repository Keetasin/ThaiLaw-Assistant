# แบ่งงาน 2 คน — ThaiLaw Assistant (5 วัน)

อ้างอิงรายละเอียดเทคนิคจาก [`PLAN.md`](./PLAN.md) ไฟล์นี้คือ **checklist ปฏิบัติจริง** แบ่งตามคน + วัน + ไฟล์ที่แตะ เพื่อลด merge conflict

- **คน A** = Data / Graph / Eval
- **คน B** = Retrieval / LLM / LINE App

**Git workflow แนะนำ**: branch `feat/a-*` กับ `feat/b-*`, merge เข้า `main` วันละครั้งตอนเย็น (D1–D4), รีวิวกันเองสั้นๆ ก่อน merge. คนที่แตะ `src/index/build_graph.py`, `src/retrieval/*`, `src/app/*` **แยกไฟล์กันชัดเจนตามตารางด้านล่าง** เพื่อลดชนกัน

---

## Day 1 — Foundation

### คน A — Data

- [X] ดึงตัวบท พ.ร.บ.คุ้มครองแรงงาน จากกฤษฎีกา → `data/raw/`
- [ ] ~~ดึงคู่มือ/FAQ จากกรมสวัสดิการและคุ้มครองแรงงาน + สนง.ประกันสังคม~~ — **ตัดสินใจตัดออก**: จำกัด scope เหลือแค่ พ.ร.บ.คุ้มครองแรงงานอย่างเดียว (ไม่เอา FAQ labour.go.th, ไม่เอาคู่มือเงินทดแทน สปส.) `src/ingest/scrape.py` ยังอยู่ในโค้ด (เขียน+ทดสอบแล้วว่าดึง FAQ ได้จริง 32 คู่) แต่ไม่ได้ใช้ output ใน corpus รอบนี้
- [X] เขียน `src/ingest/scrape.py`, `src/ingest/pdf_extract.py`
- [X] เริ่ม `src/ingest/clean.py` (แก้สระ, เลขไทย→อารบิก, ลบ header/footer)

- **ส่งท้ายวัน**: raw text ครบ (เฉพาะ พ.ร.บ.คุ้มครองแรงงาน 1 ฉบับ), clean.py รันได้จริงกับไฟล์นี้ ผ่าน pipeline pdf_extract→clean ครบวงจร
  - แก้บั๊กจริงที่เจอ: `pdf_extract.py` เดิมใช้ `pdfplumber` (ไม่ตรง requirements.txt ที่ระบุ `pymupdf`) และมันสลับลำดับตัวอักษรไทยเพี้ยน (เช่น "คุ้มครอง"→"ค้มุ ครอง") จน `pythainlp.normalize()` แก้ไม่ได้ — เปลี่ยนไปใช้ `pymupdf` (`sort=True`) แก้ลำดับถูกหมด
  - แก้บั๊กจริงอีกจุด: regex header/footer เดิมใน `clean.py` (`หน้า\s*\d+`, `เล่ม...ตอนที่`, `ราชกิจจานุเบกษา`) กว้างเกินไป ลบทิ้งบรรทัดอ้างอิงแก้ไขกฎหมายจริง (33 บรรทัด) ไปด้วย — เปลี่ยนเป็น match ทั้งบรรทัดเฉพาะ footer จริง (`about:blank`, timestamp, เลขหน้า) เท่านั้น
  - แก้ font glyph เพี้ยนที่เจอตอนทดสอบกับ PDF สปส. (สระ "ำ" กลายเป็น "Ğ"/replacement char 504 จุด) — เพิ่ม remap ไว้ใน `clean.py` เผื่อเจอไฟล์อื่นที่มีปัญหาเดียวกันในอนาคต (ไม่กระทบไฟล์ พ.ร.บ.คุ้มครองแรงงาน ที่ใช้จริงตอนนี้ — ตรวจแล้วว่ามี 0 จุด)

### คน B — Infra + LLM client

- [X] Copy/adapt โมดูลจาก `aj-krit/Project2/core/*` → `src/retrieval/{retriever,reranker,thai}.py` (staged, รอ Day 2), `src/app/{engine,generator,tracing}.py` (staged, รอ Day 2)
- [X] Copy `chat_history.py` จาก `aj-krit/RAG/Hybrid-Graph-RAG-Chatbot/` → `src/app/chat_history.py` (แก้ env var เป็น `NEO4J_USER` ให้ตรง `.env.example`)
- [X] เขียน `src/llm/client.py`: `OllamaClient` (native `ollama` pkg, `think=False`) + `DotBlueClient` (OpenAI SDK) หลัง `get_llm(provider=...)` เดียวกัน — **ทดสอบแล้วทั้งคู่ทำงานจริง** (`python -m scripts.smoke_llm`)
  - พบบั๊กจริง: dotBlue force stream เสมอไม่สน `stream=False` → แก้เป็น `stream=True` + accumulate ใน `client.py` แล้ว
- [X] เขียน `scripts/measure_dotblue_credit.py` — รันแล้ว: `qwen/qwen3.6-flash`, 5 calls, prompt=109 completion=2264 tokens รวม (เฉลี่ย ~453 tok/call ใกล้ max_tokens=512 บ่อยครั้ง เพราะโมเดลไม่ค่อยฟัง "ตอบสั้นๆ")
- [X] สร้าง LINE Messaging API channel, ตั้งค่า `.env` (`LINE_CHANNEL_SECRET`, `LINE_CHANNEL_ACCESS_TOKEN`) — **เสร็จแล้ว**
- [X] **เปิดแอป Docker Desktop** แล้วรัน `docker compose up -d neo4j` — container `thailaw-neo4j` healthy
- [X] ทดสอบ `python -m src.app.chat_history` ต่อ Neo4j ได้จริง (save/read/clear turn ผ่านหมด)
- [X] เขียน `src/app/echo_app.py` (Flask + LINE v3 SDK, echo only, ไม่ผูก RAGEngine)
- [X] รัน Flask echo bot ผ่าน `cloudflared.exe tunnel --url http://localhost:5000` เชื่อม LINE ได้จริง — ทดสอบส่ง "สวัสดี" จริง, webhook รับ 200 ตรงเวลา, ไม่มี reply-failed error ใน log

- **ส่งท้ายวัน**: ✅ ครบทุกข้อ

---

## Day 2 — Core pipelines

### คน A — Graph build

- [ ] `src/ingest/parse_sections.py`: regex parse หมวด→มาตรา→วรรค/อนุมาตรา, detect "(ยกเลิก)"/"แก้ไขโดย"
- [ ] `src/ingest/chunk.py`: chunk ตามมาตรา + metadata schema (PLAN.md 2.4) → `data/chunks.jsonl`
- [ ] `src/index/build_graph.py`: deterministic edges (HAS_SECTION, REFERS_TO, PENALIZED_BY, DEFINES)
- [ ] `src/index/extract_triples.py`: LLM extraction (Right/Duty/Penalty/Topic/Actor) ด้วย PSU-gemma ฟรี, ontology validation (adapt จาก `build_kg.py`)
- [ ] curate Topic taxonomy ~30 หัวข้อ + CSV (Topic→Agency/Evidence/Form/Step)

- **ส่งท้ายวัน**: `chunks.jsonl` พร้อม, กราฟพื้นฐานอยู่ใน Neo4j (Law/Section/REFERS_TO/PENALIZED_BY)

### คน B — Dense RAG end-to-end

- [ ] `src/index/build_vector.py`: embed ด้วย bge-m3 → ChromaDB (ใช้ `chunks.jsonl` จาก A ทันทีที่มี)
- [ ] `src/index/build_bm25.py`: BM25 word (PyThaiNLP newmm) + char 3-gram
- [ ] ต่อ `retriever.py` (reuse) เข้ากับ chunks ใหม่, ทดสอบ query 5 ข้อ
- [ ] `src/app/flex.py`: Flex Message การ์ดคำตอบ (สิทธิ/มาตรา/หลักฐาน/หน่วยงาน/ขั้นตอน/แหล่งอ้างอิง/คำเตือน)
- [ ] เริ่ม `src/retrieval/router.py` โครง MoE (Pydantic `RouteDecision`)

- **ส่งท้ายวัน**: ถาม LINE บอทแล้วได้คำตอบจาก Dense RAG จริง พร้อม Flex card

---

## Day 3 — Hybrid + Test set

### คน A — Graph retrieval + Test set

- [ ] `src/retrieval/graph.py`: entity linking (regex เลขมาตรา + alias/embedding→Topic), Cypher templates ตาม query type (lookup/procedure/penalty/definition/aggregation)
- [ ] เขียน test set **25 ข้อ** (ของตัวเอง) ครบ 7 กลุ่มตาม PLAN.md 8.1 พร้อม gold labels
- [ ] cross-check test set กับคน B ตอนเย็น (รวมเป็น 50 ข้อ)

- **ส่งท้ายวัน**: graph retrieval คืนผลลัพธ์ได้จริงจาก query type ต่างๆ, ร่าง test set 25 ข้อ

### คน B — Hybrid fusion + App polish

- [ ] `src/retrieval/fusion.py`: Weighted RRF ตาม route, graph-seeded expansion (top-3 → 1 hop)
- [ ] `src/retrieval/context.py`: Section Card aggregation + token budget (Local 3k / API 6k)
- [ ] เชื่อม router → fusion → rerank → context → LLM ครบ pipeline
- [ ] เพิ่มคำสั่ง `/mode dense|graph|hybrid`, `/llm local|api`, `/debug`, `/reset` ใน `app_line.py`
- [ ] error handling: Neo4j ล่ม → degrade dense-only, LLM ล่ม → fallback chain, logging เข้า `tracing.py`
- [ ] เขียน test set **25 ข้อ** (ของตัวเอง)

- **ส่งท้ายวัน**: Hybrid RAG ครบวงจรบน LINE, สลับโหมดสดได้, test set รวม 50 ข้อพร้อม

---

## Day 4 — Experiments

### คน A — Retrieval ablation + Dense tuning

- [ ] รัน retrieval ablation 8 configs (D, D+R, G, H1–H5) × 50 ข้อ ด้วย `eval/run_retrieval.py` (ไม่ใช้ LLM)
- [ ] Dense tuning: Top-K (3/5/10), threshold τ, rerank on/off, chunking (per-section vs fixed-512)
- [ ] เก็บผลลง `eval/results/retrieval_*.csv`

- **ส่งท้ายวัน**: ตาราง Retrieval + Dense experiments ครบ (raw data)

### คน B — Generation eval + LLM tuning

- [ ] รัน `eval/run_generation.py`: Local (qwen3.5:4b, gemma3:4b) vs API (qwen3.6-flash, gpt-4o-mini, deepseek-chat) บน retrieval config ที่ดีที่สุด (H5)
- [ ] `num_ctx` sweep (2048/4096/8192) วัด VRAM (`nvidia-smi -l 1`) และ tokens/s
- [ ] รัน `eval/judge.py` (LLM-as-judge) + no-RAG / full-context baseline
- [ ] **ทำร่วมกับ A ตอนเย็น**: judge validation 20 ข้อ (ทีมให้คะแนนเองเทียบ judge)

- **ส่งท้ายวัน**: ตาราง Local vs API + resource usage ครบ, judge validated

---

## Day 5 — Analysis + Polish + Delivery

### คน A — Analysis + Report

- [ ] `eval/analyze.ipynb`: stats test (bootstrap/Wilcoxon D vs H5), per-category heatmap, error analysis 20 เคส, case study 2–3 ข้อ
- [ ] เขียนรายงานหลัก (บทที่ 1–5 ตาม PLAN.md 9), ใส่ตาราง/กราฟทั้งหมด
- [ ] Data Quality Report + Graph schema diagram + screenshot Neo4j Browser

### คน B — Fix + Demo + Delivery

- [ ] แก้บั๊กจากผล eval วันที่ 4 (1 รอบ เน้นเคสที่พลาดบ่อย)
- [ ] จัด user test 5–8 คนผ่าน LINE จริง เก็บคะแนนความเข้าใจง่าย/พึงพอใจ 1–5
- [ ] ทำ `README.md` ให้ครบ (อัปเดตตามของจริงถ้าต่างจากตอนนี้), ตรวจ `docker-compose.yml` รันซ้ำได้
- [ ] อัด demo video 3 นาที (สำรองกันเน็ต/LINE ล่มตอนนำเสนอ)
- [ ] ทำ slides ~12 หน้า (คนสองคนช่วยกันช่วงบ่าย)

**ส่งท้ายวัน**: รายงาน + slides + video + code push ครบ

---

## จุดตัดถ้าเวลาไม่พอ (เรียงจากตัดก่อน)

1. text2cypher fallback
2. Typhoon model เพิ่ม
3. Embedding ablation (bge-m3 vs e5-base)
4. พ.ร.บ.ประกันสังคม/เงินทดแทน (เหลือแค่คุ้มครองแรงงาน)
5. Human eval ลดเหลือ 3 คน

**ห้ามตัด**: Hybrid ablation table, Local vs API table, error analysis — ส่วนนี้คะแนนเยอะสุด (ดู `PLAN.md` ส่วน 12)

## File ownership กันชน (คร่าวๆ)

| A เป็นเจ้าของ                             | B เป็นเจ้าของ                                                  | ใช้ร่วมกัน (แจ้งก่อนแก้)       |
| ---------------------------------------------------- | ------------------------------------------------------------------------- | --------------------------------------------------- |
| `src/ingest/*`                                     | `src/app/*`                                                             | `src/config.py`                                   |
| `src/index/build_graph.py`, `extract_triples.py` | `src/index/build_vector.py`, `build_bm25.py`                          | `data/chunks.jsonl` schema                        |
| `src/retrieval/graph.py`                           | `src/retrieval/fusion.py`, `router.py`, `context.py`, `rerank.py` | `src/llm/client.py`                               |
| `eval/run_retrieval.py`, `analyze.ipynb`         | `eval/run_generation.py`, `judge.py`                                  | `eval/testset.jsonl` (รวมกันวันที่ 3) |
