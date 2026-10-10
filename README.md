# ThaiLaw Assistant

ผู้ช่วยกฎหมายแรงงานไทยด้วย Hybrid Dense+Graph RAG บน LINE — ตอบคำถามจาก **พ.ร.บ.คุ้มครองแรงงาน พ.ศ. 2541** (ตัวบท + คู่มือ/FAQ ของกรมสวัสดิการและคุ้มครองแรงงาน) โดยผสาน Dense retrieval (ChromaDB + BM25) กับ Graph retrieval (เดินกราฟจาก `data/graph.json` ในหน่วยความจำ; Neo4j ใช้เก็บ/สำรวจกราฟและประวัติสนทนา) แล้วส่งเข้า LLM (Ollama local หรือ dotBlue API) เพื่อสร้างคำตอบพร้อมอ้างอิงมาตราจริง

**เล่มรายงานฉบับสมบูรณ์**: `doc/Final_Report.docx` / `doc/Final_Report.pdf`

---

## 1. Setup

### 1.1 Prerequisites

- Python 3.12, Docker Desktop, [Ollama](https://ollama.com) ติดตั้งแล้ว, [cloudflared](https://github.com/cloudflare/cloudflared) (ดาวน์โหลด `cloudflared.exe` มาวางที่ root ของโปรเจกต์)
- GPU แนะนำ (RTX 3050 6GB ขึ้นไป) สำหรับรัน embedding/rerank/local LLM เร็วขึ้น — ไม่มี GPU ก็รันได้แต่ช้ากว่า (ระบบ fallback ไป CPU โดยอัตโนมัติผ่าน `EMBED_DEVICE`/`RERANK_DEVICE`)

### 1.2 Python environment

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
```

### 1.3 ตั้งค่า `.env`

```bash
copy .env.example .env
```

แก้ค่าต่อไปนี้ใน `.env`:

- `LINE_CHANNEL_SECRET`, `LINE_CHANNEL_ACCESS_TOKEN` — จาก [LINE Developers Console](https://developers.line.biz/console/) (สร้าง Messaging API channel)
- `DOTBLUE_API_KEY` — จาก dotBlue (PSU) dashboard
- `NEO4J_PASSWORD` — ตั้งรหัสผ่านเอง (ต้องตรงกับที่ `docker-compose.yml` ใช้)

**ห้าม commit ไฟล์ `.env` จริง** (มีอยู่ใน `.gitignore` แล้ว)

### 1.4 Ollama models (local LLM)

```bash
ollama pull qwen3.5:4b
ollama pull gemma3:4b
```

โมเดล 4B ทั้งสองตัวใช้ VRAM สูงสุดราว 3.9–4.1GB ต่อตัว (Q4, วัดจริงในรายงานหัวข้อ 4.3.3) — พอดีกับ GPU 6GB ถ้ารัน embed/rerank บน CPU ระหว่าง query (ค่าตั้งต้นของ `RERANK_DEVICE=cpu` ใน `src/config.py` ทำแบบนี้อยู่แล้ว)

### 1.5 Neo4j (Docker)

```bash
docker compose up -d neo4j
```

ตรวจว่า healthy: เปิด http://localhost:7474 ล็อกอินด้วย `neo4j` / รหัสผ่านที่ตั้งใน `.env`

---

## 2. Ingest pipeline (สร้างข้อมูลตั้งแต่ต้น)

ข้อมูลที่ประมวลผลไว้แล้วอยู่ใน `data/` (`chunks.jsonl`, `sections.json`, `graph.json`, `bm25.pkl`, `chroma_db/`) — **ข้ามขั้นตอนนี้ได้ถ้าใช้ข้อมูลที่มีอยู่แล้ว** ทำตามลำดับนี้เฉพาะตอนอยากสร้างใหม่ทั้งหมด หรือเพิ่ม พ.ร.บ. ฉบับอื่น:

```bash
# 1) ดึงตัวบท + คู่มือ/FAQ
python -m src.ingest.scrape
python -m src.ingest.pdf_extract

# 2) ทำความสะอาดข้อความ (แก้สระ, เลขไทย->อารบิก, ลบ header/footer)
python -m src.ingest.clean

# 3) parse โครงสร้างหมวด/มาตรา + chunk ตามมาตรา
python -m src.ingest.parse_sections
python -m src.ingest.chunk

# 4) build vector index (bge-m3 -> ChromaDB) + BM25 index (word + char 3-gram)
python -m src.index.build_vector
python -m src.index.build_bm25

# 5) build knowledge graph: deterministic edges (Law/Chapter/Section/REFERS_TO/PENALIZED_BY/DEFINES)
python -m src.index.graph_core data/chunks.jsonl --output data/graph.json --skip-merge

# 6) LLM extraction ของ Right/Duty/Penalty/Topic/Actor ต่อมาตรา (ใช้ --offline เพื่อ smoke-test โดยไม่เรียก LLM จริง)
python -m src.index.triples data/chunks.jsonl data/curated/topic_agency_evidence_form_step.csv --output data/triples.jsonl --provider ollama --target 30

# 7) รีวิว triples ด้วยคน (สุ่มตรวจ precision) -> data/curated/triples_review_approved.csv
python -m src.index.review_triples data/triples.jsonl data/chunks.jsonl --output data/curated/triples_review.csv
# (แก้ตรวจแล้ว save เป็น triples_review_approved.csv ด้วยมือ)

# 8) รวม triples ที่ approved + curated CSV เข้ากราฟเต็ม (ใช้จริง 12 จาก 13 node types ตาม ontology ในรายงานหัวข้อ 3.2.4)
python -m src.index.graph_core data/chunks.jsonl --output data/graph.json --triples data/triples.jsonl --review data/curated/triples_review_approved.csv --topics data/curated/topic_agency_evidence_form_step.csv
```

---

## 3. รันแอปจริงบน LINE

```bash
# Terminal 1: Neo4j (ถ้ายังไม่ได้ up)
docker compose up -d neo4j

# Terminal 2: Flask webhook
python -m src.app.app_line

# Terminal 3: เปิด HTTPS tunnel แล้วเอา URL ไปตั้งเป็น Webhook URL ใน LINE Developers Console (path /callback)
.\cloudflared.exe tunnel --url http://localhost:5000
```

คำสั่งทดสอบผ่าน LINE (ดู `src/app/app_line.py`):

- `/mode dense|graph|hybrid` — สลับ retrieval mode
- `/llm local|api` — สลับ local Ollama / dotBlue API
- `/debug` — โชว์ route, top sections+scores, graph path, latency ต่อ stage, tokens
- `/reset` — ล้างประวัติสนทนา
- `/intro` — การ์ดแนะนำการใช้งาน (ตัวอย่างคำถาม) — ปกติผู้ใช้กดจาก rich menu ไม่ต้องพิมพ์เอง

**Rich Menu** (พิมพ์ครั้งเดียวตอน deploy, ตั้ง default ให้ผู้ใช้ทุกคนทันที):

```bash
python -m src.app.setup_richmenu           # แค่ build รูป src/app/assets/richmenu.jpg ดูก่อน (resize จาก richmenu_reference.png)
python -m src.app.setup_richmenu --upload  # สร้าง+อัปโหลด+ตั้งเป็น default บน LINE จริง
```

---

## 4. ดูกราฟความรู้ (Neo4j Browser)

เปิด **http://localhost:7474** (login `neo4j` / รหัสใน `.env`'s `NEO4J_PASSWORD`)

ดูกราฟทั้งหมด:

```cypher
MATCH (n)-[r]->(m) RETURN n,r,m LIMIT 300
```

ดูเฉพาะ Topic↔Section (ABOUT edges):

```cypher
MATCH (s:Section)-[:ABOUT]->(t:Topic) RETURN s,t
```

**ให้แต่ละ node label สีต่างกัน**: ต้องรัน query กราฟข้างบนก่อน 1 ครั้ง (ให้ Browser auto-generate style ก่อน) แล้วพิมพ์ `:style` ในช่อง query อีกที (ถ้ายังไม่เคยรัน query กราฟมาก่อน `:style` จะขึ้น "No styles yet" แก้ไม่ได้) จะเจอกล่อง editable — เลือกทั้งหมด (Ctrl+A) ลบ แล้ว paste ก้อนนี้แทน กด ▶ รัน:

```
node.Law        { color: #E63946; border-color: #B5222D; text-color-internal: #FFFFFF; caption: '{law_name}'; }
node.Chapter    { color: #F4A261; border-color: #C97F3E; text-color-internal: #000000; caption: '{name}'; }
node.Section    { color: #457B9D; border-color: #2F5A76; text-color-internal: #FFFFFF; caption: 'ม.{section_no}'; }
node.Term       { color: #A8DADC; border-color: #6FB1B4; text-color-internal: #000000; caption: '{name}'; }
node.Right      { color: #2A9D8F; border-color: #1D7268; text-color-internal: #FFFFFF; caption: '{name}'; }
node.Duty       { color: #E9C46A; border-color: #C79E3F; text-color-internal: #000000; caption: '{name}'; }
node.Penalty    { color: #D62828; border-color: #A61E1E; text-color-internal: #FFFFFF; caption: '{name}'; }
node.Actor      { color: #6D6875; border-color: #4A4650; text-color-internal: #FFFFFF; caption: '{name}'; }
node.Topic      { color: #8AC926; border-color: #669916; text-color-internal: #000000; caption: '{name}'; }
node.Agency     { color: #FF9F1C; border-color: #CC7D16; text-color-internal: #000000; caption: '{name}'; }
node.Evidence   { color: #B5838D; border-color: #8F5F68; text-color-internal: #FFFFFF; caption: '{name}'; }
node.Form       { color: #6A4C93; border-color: #4D3670; text-color-internal: #FFFFFF; caption: '{name}'; }
node.Step       { color: #1982C4; border-color: #14618F; text-color-internal: #FFFFFF; caption: '{name}'; }
node.ChatUser   { color: #ADB5BD; border-color: #868E96; text-color-internal: #000000; caption: '{user_id}'; }
node.ChatMessage{ color: #495057; border-color: #343A40; text-color-internal: #FFFFFF; caption: '{role}'; }
```

(`Penalty` label ไม่มีข้อมูลในตัวอย่าง 30 triples ปัจจุบัน — style ไว้เผื่ออนาคต ไม่กระทบอะไร)

---

## 5. Testing

```bash
python -m unittest discover -s tests
```

133 test cases ครอบคลุม parser/chunker/graph build, retrieval (dense/BM25/graph/fusion/rerank), engine (rewrite/zone/concurrency/safety-net/degenerate-answer), generator (context/citation), Flex card (markdown-strip/word-wrap), tracing, app_line command handling. `test_retrieval_integration.py`'s "มาตรา 61 คืออะไร" case เป็น `@unittest.expectedFailure` ที่ตั้งใจไว้ (documented known gap ของ dense-only ต่อ query แบบเลขมาตราล้วน — hybrid mode แก้ปัญหานี้แล้ว)

---

## 6. Evaluation (Day 4-5 experiments)

```bash
# Retrieval ablation 9 configs (D, D+R, G, H1-H6) + dense tuning (top-k/threshold/rerank/chunking)
python -m eval.run_retrieval --production --tune

# Generation eval: Local vs API matrix + num_ctx sweep + no-RAG/full-context baselines
python -m eval.run_generation --all

# LLM-as-judge scoring
python -m eval.judge --score

# (ทางเลือกเสริม ไม่บังคับตาม Rubric — เพิ่มความน่าเชื่อถือของ judge เฉยๆ)
python -m eval.judge --validate 20   # เติมคะแนนคนด้วยมือใน eval/results/judge_validation_sample.csv แล้วรัน:
python -m eval.judge --kappa

# Retrieval ของ RAGEngine จริง 3 โหมด (ผลเทียบกับ generation ได้ตรง)
python -m eval.run_engine_retrieval

# จูน Rerank แบบรู้ที่มา: จูนบนชุด A แล้วทดสอบบนชุด B (held-out)
python -m eval.tune_rerank_blend

# วัด latency/VRAM/RAM แบบเครื่องว่าง (10 คำถามต่อ LLM)
python -m eval.bench_latency

# วิเคราะห์ผล (stats test, heatmap, error analysis, case study)
jupyter nbconvert --to notebook --execute eval/analyze.ipynb
```

ผลลัพธ์ทั้งหมดอยู่ใน `eval/results/*.csv` และรายงานสรุปใน `doc/Final_Report.docx`

---

## 7. Repo structure

```text
src/ingest/    ดึง+ทำความสะอาด+parse+chunk ข้อมูล
src/index/     build vector/BM25/graph index, LLM triple extraction
src/retrieval/ dense, graph, router (MoE), fusion (weighted RRF), rerank, context (Section Card)
src/llm/       client interface เดียวสำหรับ Ollama (native) + dotBlue (OpenAI SDK), retry, token accounting
src/app/       Flask webhook, RAGEngine, Flex message, Neo4j chat history, tracing
eval/          testset (50 ข้อ), retrieval/generation eval scripts, judge, analyze.ipynb
doc/           เล่มรายงานฉบับสมบูรณ์ (Final_Report.docx/.pdf), โครงร่างรายงาน
```

---

## 8. ความปลอดภัย

- `.env` เก็บ secret ทั้งหมด (`DOTBLUE_API_KEY`, `LINE_CHANNEL_SECRET/ACCESS_TOKEN`, `NEO4J_PASSWORD`) — ไม่ commit
- ทุก webhook request ตรวจ `X-Line-Signature` ก่อนประมวลผล
- Graph query ทั้งหมดใช้ Cypher parameter เสมอ (ไม่มีการต่อ query string จาก user input โดยตรง)
