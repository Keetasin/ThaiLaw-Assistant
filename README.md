# ThaiLaw Assistant — ผู้ช่วยกฎหมายแรงงานไทยด้วย Hybrid GraphRAG บน LINE

ระบบตอบคำถามกฎหมายแรงงานไทยด้วย Dense + BM25 + GraphRAG (Neo4j) แล้วสร้างคำตอบผ่าน Local LLM (Ollama) หรือ API LLM (dotBlue) ส่งกลับผู้ใช้ทาง LINE Chatbot

รายละเอียดออกแบบเต็ม ๆ ดู [`doc/PLAN.md`](./doc/PLAN.md) · การแบ่งงาน 2 คนดู [`doc/SPLIT.md`](./doc/SPLIT.md)

---

## 1. Prerequisites

| เครื่องมือ | ตรวจสอบ | ติดตั้ง |
|---|---|---|
| Python 3.12 | `python --version` | https://python.org |
| Docker Desktop | `docker --version` แล้ว **เปิดแอปทิ้งไว้** (เช็คด้วย `docker info`) | https://docker.com |
| Ollama | `ollama --version` | https://ollama.com |
| LINE Developers account | — | https://developers.line.biz/console/ (สร้าง Messaging API channel) |
| dotBlue API key | — | ขอจากระบบ PSU dotBlue |
| GPU (option) | `nvidia-smi` | driver + CUDA สำหรับ RTX 3050 |

`cloudflared.exe` มีอยู่แล้วที่ root ของ repo นี้ (ไม่ต้องติดตั้งเพิ่ม)

---

## 2. Setup

```bash
# 1) สร้าง/เปิดใช้งาน virtual environment (สร้างไว้แล้วที่ .venv)
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Git Bash:
source .venv/Scripts/activate

# 2) ติดตั้ง dependencies
pip install -r requirements.txt

# 3) (GPU) ติดตั้ง torch รุ่น CUDA ทับของเดิม ถ้าต้องการรัน embedding/rerank บน GPU
pip install torch --index-url https://download.pytorch.org/whl/cu121
python -c "import torch; print(torch.cuda.is_available())"

# 4) ตั้งค่า environment variables
copy .env.example .env      # PowerShell
# cp .env.example .env      # Git Bash
# แล้วกรอกค่าใน .env: LINE_CHANNEL_SECRET, LINE_CHANNEL_ACCESS_TOKEN, DOTBLUE_API_KEY, NEO4J_PASSWORD

# 5) ดึงโมเดล Local LLM (ถ้ายังไม่มี)
ollama pull qwen3.5:4b
ollama pull gemma3:4b

# 6) เปิดแอป Docker Desktop ทิ้งไว้ก่อน (ต้องเห็น icon ว่า running ไม่ใช่แค่ติดตั้งไว้)
docker info   # ถ้า error "cannot connect" แปลว่ายังไม่ได้เปิดแอป
docker compose up -d neo4j
# เปิด http://localhost:7474 ตรวจว่า login ได้ด้วย NEO4J_USER/NEO4J_PASSWORD ใน .env
python -m src.app.chat_history   # ทดสอบว่า driver ต่อได้จริง
```

---

## 3. Data ingest & index build (รันครั้งเดียวหรือทุกครั้งที่ข้อมูลกฎหมายเปลี่ยน)

```bash
python -m src.ingest.scrape          # ดึงตัวบท/คู่มือตาม PLAN.md 2.1
python -m src.ingest.clean_chunk     # clean + parse มาตรา + chunk -> data/chunks.jsonl
python -m src.index.build_vector     # embed ด้วย bge-m3 -> ChromaDB
python -m src.index.build_bm25       # build BM25 word + 3-gram index
python -m src.index.build_graph      # deterministic edges + LLM extraction -> Neo4j
```

> สคริปต์ข้างต้นเป็นโครงตาม `doc/PLAN.md` ส่วน 10 (โครงสร้าง Repo) — ยังไม่ได้สร้าง (Day 2, คน A)

---

## 4. Run the app

**Day 1 (ตอนนี้)** — echo bot เท่านั้น ใช้ตรวจ webhook/signature/reply pipeline ก่อน RAGEngine จะพร้อม (Day 2):

```bash
# Terminal 1: sanity check LLM ทั้งสองฝั่งก่อน (ไม่ต้องมี LINE)
python -m scripts.smoke_llm

# Terminal 2: Flask echo webhook
python -m src.app.echo_app
# ค่าเริ่มต้นรันที่ http://localhost:5000

# Terminal 3: เปิด tunnel ให้ LINE เรียกเข้ามาได้
./cloudflared.exe tunnel --url http://localhost:5000
# copy https://xxxx.trycloudflare.com/callback ไปใส่ใน LINE Developers Console -> Webhook URL
```

**Day 2+** — สลับไปใช้ `src/app/engine.py` (`RAGEngine`) แทน echo หลัง `data/chunks.jsonl` + Chroma + BM25 พร้อม แล้วเพิ่มคำสั่งสำหรับ demo:
- `/mode dense|graph|hybrid` — สลับโหมด retrieval
- `/llm local|api` — สลับ Local/API LLM
- `/debug` — โชว์ route, top sections, latency, tokens
- `/reset` หรือ `ล้างประวัติ` — ล้าง chat history ใน Neo4j (`src/app/chat_history.py`)

---

## 5. Evaluation

```bash
python -m eval.run_retrieval    # Recall@k, MRR, nDCG@5 (ไม่ใช้ LLM)
python -m eval.run_generation   # Local vs API generation metrics
python -m eval.judge            # LLM-as-judge scoring
jupyter notebook eval/analyze.ipynb   # กราฟ/ตาราง สำหรับรายงาน
```

---

## 6. Project structure

ดูโครงสร้างเต็มใน [`doc/PLAN.md`](./doc/PLAN.md) ส่วนที่ 10

```text
Final-Project/
├─ doc/            # โจทย์, rubric, PLAN.md, SPLIT.md, รายงาน, slides
├─ data/           # raw/clean/chunks/curated (ignored ยกเว้น curated/)
├─ src/
│  ├─ config.py
│  ├─ llm/client.py         # Ollama (native) + dotBlue (OpenAI SDK), one .chat() interface
│  ├─ retrieval/            # dense+BM25 retriever, reranker, thai tokenizer — staged, wired Day 2
│  └─ app/                  # echo_app.py (Day 1), engine.py + generator.py + chat_history.py (Day 2)
├─ scripts/        # smoke_llm.py, measure_dotblue_credit.py
├─ eval/           # test set, eval scripts, results
├─ .venv/          # virtual environment (ignored)
├─ cloudflared.exe # tunnel binary
├─ docker-compose.yml
├─ .env.example
└─ requirements.txt
```

---

## 7. Security notes
- ห้าม commit `.env` (มีอยู่ใน `.gitignore` แล้ว) — เก็บเฉพาะ `.env.example`
- ตรวจ `X-Line-Signature` ทุก webhook request
- Cypher query ใช้ parameter binding เสมอ ห้าม string-concat query จาก user input
