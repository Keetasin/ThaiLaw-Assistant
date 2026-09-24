# แผนโครงงาน ThaiLaw Assistant: ผู้ช่วยกฎหมายแรงงานไทยด้วย Hybrid GraphRAG บน LINE

> เป้าหมายคือ Level 5 ทุกด้านของ Rubric (100 คะแนน) · ทีม 2 คน · เวลา 5 วัน
> หลักคิดจาก Rubric: **"มีเทคโนโลยี ≠ ได้คะแนน"** ทุกองค์ประกอบต้องมี **(1) ทำงานจริงในระบบเดียว (2) มีการปรับจูน (3) มีผลการทดลองยืนยัน (4) อธิบายได้ว่าทำไม**

---

## 0. สรุปการตัดสินใจหลัก

| เรื่อง | เลือก | เหตุผล |
|---|---|---|
| Domain | **กฎหมายแรงงาน** (พ.ร.บ.คุ้มครองแรงงาน + ประกันสังคม + เงินทดแทน) + คู่มือ/FAQ ของหน่วยงานรัฐ | ตรง MVP ในหัวข้อ, ทำ 5 วันทัน, มีโครงสร้างอ้างอิงข้ามมาตราเยอะ ซึ่งเหมาะกับ Graph |
| Vector DB | **ChromaDB** (persistent, embedded) | ผล Lab FAISS-vs-Chroma: ranking เท่ากัน แต่ Chroma ใช้ `where` filter แล้วตรงรหัส 4/4 ขณะที่ FAISS ตรง 2/4 จึงใช้ filter ตาม `law_id`/`status` ได้ |
| Lexical | **BM25 2 ขา**: word (PyThaiNLP `newmm`) + **char 3-gram** (รองรับพิมพ์ผิด) | reuse จาก Project2; query แบบ "มาตรา 61" หรือศัพท์เฉพาะ dense มักพลาด |
| Graph DB | **Neo4j 5** (Docker) + APOC | ตรงกับที่ทำมาทุกแลบ (`Graph-RAG/`, `Hybrid-Graph-RAG-Chatbot/`) ใช้แบบเดียวกันหมด — ต้องเปิดแอป **Docker Desktop ให้ทำงานอยู่ก่อน** (แค่ติดตั้งไว้ไม่พอ ต้องเปิดแอปให้ daemon รันด้วย) แล้ว `docker compose up -d neo4j` ถึงจะต่อได้ |
| Embedding | **BAAI/bge-m3** (568M) | รองรับภาษาไทยดี, context ยาว 8192 |
| Reranker | **BAAI/bge-reranker-v2-m3** | cross-encoder หลายภาษา ใช้ทำ context selection |
| Local LLM | Ollama: **qwen3.5:4b** (มีในเครื่องแล้ว), **gemma3:4b** (มีแล้ว), + **Typhoon2.1-gemma3-4b** (ปรับจูนภาษาไทย) | RTX 3050 **6GB** รุ่น 4B Q4 ได้ประมาณ 3–3.5GB พอรันบน GPU ได้เต็มตัว ส่วนรุ่น 7–8B จะล้นไป CPU และช้ามาก |
| API LLM | dotBlue (PSU) OpenAI-compatible `https://ai.psu.blue/v1` | **qwen3.6-flash / gpt-4o-mini** (x1) เป็นตัวหลัก, **PSU-gemma** (ฟรี) ใช้ตอน dev และสกัดกราฟ, **qwen3.6-plus** (x3) ใช้เป็น Judge |
| UI | **LINE Messaging API** (line-bot-sdk v3) + **Flask** webhook + **cloudflared** tunnel | ตรงกับที่เรียนและ reuse `Project2/app_line.py` ได้ + มีคำสั่ง `/debug` เพื่อโชว์ข้างในระบบ |
| Chat memory | **Neo4j** `(:ChatUser)-[:HAS_MESSAGE]->(:ChatMessage{seq})` | ตามที่เรียนในแลบ Hybrid-Graph-RAG-Chatbot, restart แล้วประวัติไม่หาย, reuse `chat_history.py` |
| Router | **MoE-style router** (Pydantic `RouteDecision` + α gating) | ตามที่เรียนในแลบ rag-router-mixture-of-experts |
| LLM client | ใช้ **OpenAI SDK ตัวเดียว** ต่อทั้ง Ollama (`localhost:11434/v1`) และ dotBlue | abstraction เดียว สลับ Local/API ได้ด้วย config ทำให้เปรียบเทียบได้แฟร์ |

### 0.1 Reuse จากงานในรายวิชา (ประหยัดเวลาเกือบทั้งวันที่ 2)
| ใช้ทำ | ไฟล์เดิม (`D:\Python_lab\4_1\ai4social\aj-krit\...`) | ปรับอะไร |
|---|---|---|
| Dense + BM25 word/3-gram + weighted RRF + `dynamic_k()` | `Project2/core/retriever.py` | เพิ่มขา graph ใน `rrf()` |
| Cross-encoder rerank (CPU) | `Project2/core/reranker.py` | ใช้ได้เลย |
| Thai tokenizer / clean ZWSP | `Project2/core/thai.py`, `core/rag.py` | ระวัง `keep_whitespace=False` |
| History rewrite, guard zones (TAU_ANSWER/TAU_REJECT), small-to-big `expand()` | `Project2/core/rag.py` | `expand()` → ขยายจากวรรคเป็นทั้งมาตรา |
| Citation trailer `ใช้ข้อมูลจาก: [n]` | `Project2/core/generator.py` | เปลี่ยนเป็น `[มาตรา X]` |
| Per-stage latency JSONL | `Project2/core/tracing.py` | ใช้ได้เลย |
| LINE v3 + Flex + thread + `OLLAMA_LOCK` | `Project2/app_line.py` | เพิ่มคำสั่ง `/mode` `/llm` `/debug` |
| Eval R@k/MRR/threshold sweep, BERTScore/SBERT/Faithfulness, tok/s, full-context baseline | `Project2/eval/*.py` | ใช้ test set ใหม่ |
| Neo4j chat memory | `RAG/Hybrid-Graph-RAG-Chatbot/chat_history.py` | เปลี่ยนแค่ env var เป็น `NEO4J_USER` (จากเดิม `NEO4J_USERNAME`) ให้ตรง `.env.example` |
| Neo4j docker (5.24 + APOC + healthcheck) | `RAG/Hybrid-Graph-RAG-Chatbot/docker-compose.yml` | ใช้ได้เลย — ใช้ได้จริงหลังเปิดแอป Docker Desktop |
| LLM extraction + ontology validation | `Hybrid-Graph-RAG-Chatbot/pdf2neo4j/build_kg.py`, `Graph-RAG/handbook-knowledge-graph/` | เปลี่ยน ontology เป็น schema กฎหมาย (4.2) |
| Regex NER กฎหมาย | `NER/thai_legal_ner_pattern.py` | ปรับให้สกัด มาตรา / หน่วยงาน / ลูกจ้าง-นายจ้าง |
| Router | `RAG/rag-router-mixture-of-experts/MoE-2/rag_moe_pipeline.py` | route เป็น dense/graph/hybrid/direct_llm |

> ข้อค้นพบเดิมจาก Project2: **RRF แบบเท่ากันแพ้ dense อย่างเดียว** (R@1 0.778 vs 0.889) → ตั้งต้นที่ **dense weight 2.0** แล้ว tune ใหม่กับข้อมูลกฎหมาย ควรเล่าไว้ในรายงานเพื่อแสดงว่าเรียนรู้ต่อยอดจากงานเดิม

### งบ VRAM (6GB)
- LLM 4B Q4 ประมาณ 3.3GB, `num_ctx=8192` KV cache ประมาณ 0.5–1GB
- bge-m3 fp16 ประมาณ 1.1GB, reranker fp16 ประมาณ 1.1GB
- **รวมเกิน 6GB** จึงแนะนำให้ **รัน embed/rerank ตอน query บน CPU** (query สั้น ใช้เวลาประมาณ 0.1–0.5 วินาที) หรือใช้ GPU เฉพาะตอน index offline ต้องวัดจริงแล้วรายงานใน Local LLM analysis (ได้คะแนนด้าน Resource)
- ดิสก์เหลือ 25GB: pull โมเดลเพิ่มแค่ 1–2 ตัวพอ

---

## 1. Architecture

```text
LINE User
   │  (webhook, verify X-Line-Signature)
   ▼
FastAPI  ──► Session store (SQLite: history ต่อ userId, mode, logs)
   │
   ▼
Query Processing
   ├─ normalize ภาษาไทย (pythainlp.normalize, เลขไทย→อารบิก)
   ├─ follow-up rewrite (ใช้ history → standalone query)
   ├─ extract: เลขมาตรา (regex), Topic/Actor (dictionary + LLM เล็ก)
   └─ Router: จำแนก query type → {lookup, definition, penalty, procedure, multi-hop, out-of-scope}
   │
   ├───────────────┬──────────────────┐
   ▼               ▼                  ▼
Dense (bge-m3    BM25              Graph Retrieval (Neo4j)
 + Chroma)       (Thai tokens)      ├─ entity linking → Topic/Section nodes
   │               │                ├─ Cypher templates (1–2 hop)
   │               │                └─ seed expansion จากผล Dense
   └───────┬───────┴──────────────────┘
           ▼
Hybrid Fusion
   ├─ Weighted RRF (น้ำหนักตาม route)
   ├─ Graph expansion ของ top seeds (บทลงโทษ / นิยาม / มาตราที่อ้างถึง)
   ├─ Cross-encoder rerank
   └─ Context Aggregation: รวมเป็น "Section Card" + triples, dedupe, token budget
           ▼
LLM Layer (Local | API)  ── retry/backoff, timeout, fallback, token counting
           ▼
Answer Formatter → LINE Flex Message
   (สิทธิ / มาตรา / หลักฐาน / หน่วยงาน / ขั้นตอน / แหล่งอ้างอิง+URL / วันที่ข้อมูล / คำเตือน)
```

---

## 2. Data & Knowledge Base (10 คะแนน)

### 2.1 แหล่งข้อมูล (จำกัดให้ทัน 5 วัน)
1. **พ.ร.บ.คุ้มครองแรงงาน พ.ศ. 2541** ฉบับรวมแก้ไขล่าสุด (กฤษฎีกา ocs.go.th) เป็นแกนหลัก
2. **พ.ร.บ.ประกันสังคม พ.ศ. 2533** (เฉพาะหมวดสิทธิประโยชน์ ถ้าเวลาไม่พอ)
3. **พ.ร.บ.เงินทดแทน พ.ศ. 2537**
4. คู่มือ/FAQ/infographic ของ **กรมสวัสดิการและคุ้มครองแรงงาน**, **สำนักงานประกันสังคม** ใช้สำหรับขั้นตอน หลักฐาน และช่องทางร้องเรียน (เช่น สายด่วน 1546 / 1506 ต้องตรวจจากเว็บจริง)
5. ตาราง Agency/Form ที่ทีมทำเอง (curated CSV) มี URL ประกอบทุกแถว

> ⚠️ ต้องเก็บ `source_url`, `retrieved_date`, `version/amendment` ทุก chunk เพราะหัวข้อบังคับให้ระบุวันที่ปรับปรุงข้อมูล และต้องระวังมาตราที่ถูกแก้ไขหรือยกเลิก

### 2.2 Pipeline
```text
PDF/HTML → extract (PyMuPDF / BeautifulSoup)
        → Clean: แก้สระอำแตก "ํา"→"ำ", ลบ header/footer/เลขหน้า, เลขไทย→อารบิก,
                 รวมบรรทัดที่ขาด, pythainlp.util.normalize
        → Structure parse (regex): หมวด → มาตรา → วรรค/อนุมาตรา (1)(2)
        → Detect: "(ยกเลิก)", "แก้ไขโดย พ.ร.บ.… ฉบับที่ …"
        → Chunk + Metadata → JSONL (single source of truth สำหรับทั้ง Vector และ Graph)
```

### 2.3 Chunking Strategy (ต้องอธิบายเหตุผลในรายงาน)
- **ตัวบท: ใช้ Structure-aware chunk = 1 มาตรา ต่อ 1 chunk** เพราะมาตราคือหน่วยอ้างอิงตามกฎหมาย citation จึงแม่นยำ
  - มาตรายาวเกิน ~800 tokens ให้แยกตามวรรค/อนุมาตรา โดยใส่ **prefix บริบท** (`[พ.ร.บ.คุ้มครองแรงงาน > หมวด 3 ค่าจ้าง… > มาตรา 61]`) ไว้ทุกชิ้น
  - มาตราสั้นมาก (เช่น มาตราบทลงโทษ "ผู้ใดฝ่าฝืนมาตรา 61 …") ให้เก็บเดี่ยวไว้ เพราะ Graph จะช่วยเชื่อมให้ (เป็นจุดขาย ดู 4.1)
- **คู่มือ/FAQ: semantic chunk ~400–500 tokens overlap 15%**
- **Ablation**: เปรียบเทียบ chunk ตามมาตรา vs fixed-size 512 tokens ด้วย Recall@5 เป็นหลักฐานว่าการออกแบบ chunk มีผล

### 2.4 Metadata Schema
```json
{
  "chunk_id": "LPA2541-s61-p1",
  "law_id": "LPA2541", "law_name": "พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. 2541",
  "chapter": "หมวด 3 ค่าจ้าง ค่าล่วงเวลา ...", "section_no": "61", "paragraph": 1,
  "doc_type": "statute | guide | faq | agency",
  "status": "in_force | amended | repealed", "amended_by": ["..."],
  "refs_out": ["24", "5"],
  "source_url": "https://...", "retrieved_date": "2026-09-25",
  "text": "..."
}
```

### 2.5 Data Quality Report (ต้องมีเพื่อได้ Level 5)
- จำนวนกฎหมาย / มาตรา / chunk / token distribution (histogram)
- % มาตราที่ parse สำเร็จ, จำนวน cross-reference ที่สกัดได้
- ตัวอย่างก่อนและหลัง cleaning
- สถิติกราฟ: จำนวน node/edge แยกตามประเภท, degree distribution, orphan nodes

---

## 3. Dense RAG (15 คะแนน)

**Pipeline:** query → (rewrite) → bge-m3 embed → Chroma top-K₀=20 (cosine) → similarity threshold τ → bge-reranker → top-k=5 → context → LLM

**สิ่งที่ต้องทดลองและรายงาน (Level 5 ต้องมี "ปรับ + ผลยืนยัน"):**
| Experiment | ค่าที่ลอง | Metric |
|---|---|---|
| Top-K | 3, 5, 10 | Recall@k, MRR, คุณภาพคำตอบ |
| Threshold τ | ไม่มี, 0.4, 0.5 | precision / อัตรา refusal ที่ถูกต้องใน out-of-scope |
| Reranking | off / on | nDCG@5, latency เพิ่มเท่าไร |
| Lexical | dense / BM25 / dense+BM25 (RRF) | Recall@5 บนกลุ่ม query ที่ระบุเลขมาตรา |
| Chunking | per-section / fixed-512 | Recall@5 |
| (optional) Embedding | bge-m3 vs multilingual-e5-base | Recall@5 |

---

## 4. Graph RAG (15 คะแนน)

### 4.1 ทำไมต้อง Graph (ตอบข้อ Level 5: "Graph ช่วยแก้ข้อจำกัดของ Dense อย่างไร")
ข้อจำกัดของ Dense ในกฎหมายที่จะพิสูจน์ด้วยการทดลอง:
1. **บทลงโทษแยกหมวด**: มาตราโทษเขียนแค่ "ผู้ใดฝ่าฝืนมาตรา …" แทบไม่มี semantic เรื่องนั้นเลย จึงค้นด้วย embedding ไม่เจอ แต่ Graph เดิน `Section -[:PENALIZED_BY]-> PenaltySection` ได้ทันที
2. **การอ้างอิงข้ามมาตรา**: มาตราหนึ่งอ้าง "ตามมาตรา 24" หรือใช้นิยามใน มาตรา 5 ซึ่ง Dense ได้มาแค่ชิ้นเดียว แต่ Graph ขยายตาม `REFERS_TO` และ `USES_TERM`
3. **ข้อมูลเชิงปฏิบัติไม่อยู่ในตัวบท**: หน่วยงาน หลักฐาน และแบบฟอร์มอยู่ในคู่มือคนละเอกสาร Graph ผูกทุกอย่างไว้ที่ `Topic`
4. **คำถามเชิงสรุปรวม (aggregation)**: เช่น "ลูกจ้างมีสิทธิลาอะไรบ้าง" ต้องการทุกมาตราที่ `GRANTS_RIGHT` + `ABOUT: การลา` ซึ่ง top-k ของ Dense ตัดข้อมูลทิ้งบางส่วน

> *ตัวอย่างเลขมาตราในแผนนี้ต้องตรวจกับตัวบทจริงก่อนใช้งาน*

### 4.2 Schema (ขยายจาก 4 ประเภทขั้นต่ำให้มีความหมาย)
```text
Nodes:
  Law{law_id,name,year,status,url}   Chapter{name}   Section{id,no,text,status,url}
  Term{name,definition}              Topic{name,aliases[]}   Actor{name: ลูกจ้าง/นายจ้าง/...}
  Right{desc}  Duty{desc}  Penalty{desc,max_fine,max_prison}
  Agency{name,hotline,url}  Evidence{name}  Form{name,url}  Step{order,desc}

Relationships:
  (Law)-[:HAS_CHAPTER]->(Chapter)-[:HAS_SECTION]->(Section)
  (Section)-[:REFERS_TO]->(Section)                 # regex "มาตรา \d+"
  (Section)-[:PENALIZED_BY]->(Section)              # จากมาตราในหมวดบทกำหนดโทษ
  (Section)-[:DEFINES]->(Term) , (Section)-[:USES_TERM]->(Term)
  (Section)-[:GRANTS_RIGHT]->(Right)-[:HELD_BY]->(Actor)
  (Section)-[:IMPOSES_DUTY]->(Duty)-[:BINDS]->(Actor)
  (Section)-[:HAS_PENALTY]->(Penalty)
  (Section)-[:ABOUT]->(Topic)
  (Topic)-[:HANDLED_BY]->(Agency) , (Topic)-[:REQUIRES_EVIDENCE]->(Evidence)
  (Topic)-[:USES_FORM]->(Form) , (Topic)-[:HAS_STEP]->(Step)
  (Law)-[:AMENDED_BY]->(Law)
```

### 4.3 การสร้างกราฟ (ผสม deterministic + LLM เพื่อความแม่น)
1. **Deterministic** (แม่น 100%): Law/Chapter/Section, REFERS_TO, PENALIZED_BY (parse หมวดบทกำหนดโทษ), DEFINES (มาตรานิยาม)
2. **LLM extraction** (PSU-gemma ฟรี / qwen3.6-flash, JSON schema output): Right/Duty/Penalty/Topic/Actor ต่อมาตรา
3. **Entity resolution**: ใช้ **Topic taxonomy ที่ทีม curate ~30 หัวข้อ** (ค่าล่วงเวลา, ค่าชดเชยเลิกจ้าง, วันลา, ค่าจ้างขั้นต่ำ, …) และบังคับให้ LLM เลือกจาก list เพื่อกันโหนดซ้ำ
4. **Curated CSV**: Topic→Agency/Evidence/Form/Step จากคู่มือรัฐ
5. **Validation**: สุ่ม 30 triples มาตรวจด้วยคน แล้วรายงาน precision ของการสกัด (หลักฐาน Level 5 ด้าน Data)
6. เก็บ embedding ของ Topic/Term ไว้ใน Neo4j vector index เพื่อใช้ทำ entity linking แบบ fuzzy

### 4.4 Graph Retrieval
- **Entity linking**: เลขมาตรา (regex) → Section; alias dictionary + embedding similarity → Topic/Term
- **Cypher templates** (ปลอดภัยกว่า text2cypher และ debug ง่าย) ตาม query type:
  - `lookup`: Section + REFERS_TO 1 hop + PENALIZED_BY
  - `procedure`: Topic → Section(ABOUT) + Agency + Evidence + Step
  - `penalty`: Topic/Section → PENALIZED_BY → Penalty
  - `definition`: Term ← DEFINES
  - `aggregation`: Topic ← ABOUT ← Section → GRANTS_RIGHT
- **Output**: (a) รายการ Section ที่จัดอันดับด้วย path-length และ edge-type weight (b) triples เป็นข้อความ เช่น `มาตรา 61 —PENALIZED_BY→ มาตรา 144`
- (optional ถ้ามีเวลา) text2cypher เป็น fallback แบบ read-only และมี allowlist ของ clause

---

## 5. Hybrid RAG (20 คะแนน, หัวใจของงาน)

ออกแบบเป็น **4 กลไก** และทำ **ablation ทีละชั้น** เพื่อพิสูจน์ว่าแต่ละชั้นช่วยอะไร

1. **Routing แบบ MoE gating (ตามที่เรียน)**: rule (regex เลขมาตรา/NER) + LLM ขนาดเล็กคืน Pydantic `RouteDecision{query_type, alpha_dense, alpha_bm25, alpha_graph}` แล้ว softmax เป็น α; ใช้ **sparse gating** เรียกเฉพาะ expert ที่ α > 0.3 (ประหยัด latency) และมี route `direct_llm` สำหรับคำทักทาย/ขอบคุณ ค่าตั้งต้นของ α:
   | type | w_dense | w_bm25 | w_graph |
   |---|---|---|---|
   | lookup (มีเลขมาตรา) | 0.2 | 0.4 | 0.4 |
   | definition | 0.3 | 0.2 | 0.5 |
   | procedure / penalty / multi-hop | 0.3 | 0.1 | 0.6 |
   | general / ไม่มี entity | 0.6 | 0.3 | 0.1 |
   | out-of-scope | ปฏิเสธอย่างสุภาพ + แนะนำหน่วยงาน | | |
2. **Fusion**: Weighted **Reciprocal Rank Fusion** `score = Σ w_i / (60 + rank_i)` บนระดับ Section id
3. **Graph-seeded expansion (Dense → Graph)**: เอา top-3 จาก fusion เป็น seed แล้วเดินกราฟ 1 hop (PENALIZED_BY, REFERS_TO, USES_TERM→DEFINES) ดึงมาตราที่ Dense ไม่มีทางเจอ จากนั้น **rerank รวม** ด้วย cross-encoder
4. **Context Aggregation**: จัด context เป็น **Section Card** ต่อ 1 ประเด็น
   ```text
   [มาตรา 61 | พ.ร.บ.คุ้มครองแรงงาน | ใช้บังคับ | url]
   ตัวบท: ...
   บทลงโทษที่เกี่ยวข้อง: มาตรา ... (ย่อ)
   นิยามที่ใช้: "ค่าล่วงเวลา" (มาตรา 5)
   หน่วยงาน: ... | หลักฐาน: ... | ขั้นตอน: ...
   ```
   dedupe, จัดลำดับตามคะแนน, ตัดตาม **token budget** (Local 3k / API 6k)

**Ablation ที่ต้องรายงาน (ตารางสำคัญที่สุดในรายงาน):**
| Config | คำอธิบาย |
|---|---|
| D | Dense only |
| D+R | Dense + rerank |
| G | Graph only |
| H1 | Dense + Graph, concat ธรรมดา (baseline ระดับ Level 3) |
| H2 | + RRF |
| H3 | + Graph-seeded expansion |
| H4 | + Router weights |
| H5 | + Rerank + Section Card (ระบบเต็ม) |

→ แยกผลตาม **ประเภทคำถาม** ต้องเห็นว่า Hybrid ชนะมากในกลุ่ม multi-hop/penalty/procedure แต่ในกลุ่ม lookup ง่ายๆ อาจไม่ต่าง แล้ว **อธิบายเหตุผล** (นี่คือ "วิเคราะห์เชิงลึก" ของ Level 5)

---

## 6. Local LLM + API LLM (15 คะแนน)

### 6.1 Local (Ollama)
- โมเดล: `qwen3.5:4b`, `gemma3:4b`, (+ Typhoon 4B ถ้า pull ทัน)
- Config ที่ปรับ: **`num_ctx` sweep 2048/4096/8192** เทียบ VRAM (`nvidia-smi -l 1`) และเวลา, `num_gpu` (สัดส่วน offload GPU/CPU), quantization Q4_K_M vs Q8 (ถ้าดิสก์พอ), `temperature` 0.1–0.3, **`think=False`** สำหรับ qwen3.5, `keep_alive` กันโหลดโมเดลซ้ำ
- **Model routing ตาม Low-VRAM lab**: คำถามง่าย (lookup/definition) ส่งให้โมเดลเล็ก ส่วน multi-hop ส่งให้โมเดลใหญ่หรือ API แล้ววัดว่าประหยัดเวลาได้เท่าไร
- Prompt: system prompt ภาษาไทยสั้น + บังคับ output format + บังคับอ้าง [มาตรา X] เฉพาะที่อยู่ใน context
- **วัดอย่างเป็นระบบ**: TTFT, tokens/s (จาก `eval_count/eval_duration` ของ Ollama), peak VRAM (`nvidia-smi` sampling), RAM (psutil), GPU/CPU offload %, อัตรา hallucinate citation
- วิเคราะห์ข้อจำกัด: 6GB รันเกิน 4B ไม่ได้, context ยาวแล้วช้าลง, ภาษาไทยของ 4B ยังเพี้ยนบ้าง

### 6.2 API (dotBlue)
- ตัวหลัก `qwen3.6-flash`, เทียบกับ `gpt-4o-mini`, `deepseek-chat` (x1 ทั้งหมด)
- **Token management**: นับ token ก่อนส่ง (tiktoken ประมาณ) แล้ว trim context ตาม budget, log `usage` จาก response
- **Error handling**: timeout 30s, retry 3 ครั้ง exponential backoff (tenacity) กับ 429/5xx, **fallback chain API → Local** (และ Local → API ถ้า Ollama ล่ม), ตอบข้อความ graceful ใน LINE
- **Cost**: บันทึกเครดิต dotBlue ที่ใช้ต่อคำถาม (เช็คหน้า dashboard ก่อน/หลังรัน batch) + คำนวณเทียบราคา public ต่อ 1,000 คำถาม
- ⚠️ เครดิต 1,000/วัน (ตัวคูณ x1–x3) → **วันที่ 1 ต้องวัดว่า 1 call กินกี่เครดิต** แล้วค่อยวางงบ eval; ใช้ PSU-gemma (ฟรี) กับงาน bulk
- ⚠️ ชื่อโมเดลต้องยืนยันด้วย `GET /v1/models`

### 6.3 ตารางเปรียบเทียบ (ใช้ retrieval config ดีที่สุด H5 คงที่)
| LLM | Correctness | Faithfulness | Citation acc. | Thai clarity | p50/p95 latency | tokens | cost/credit | VRAM |

---

## 7. System Integration + LINE (10 คะแนน)

- **Flask** `/callback` (reuse `Project2/app_line.py`): ตรวจ `X-Line-Signature` → ตอบ 200 ทันที → ประมวลผลใน background thread + `OLLAMA_LOCK` กัน GPU ชนกัน
- **Latency กับ LINE**: reply token มีอายุจำกัด จึงเรียก **Loading Animation API** ระหว่างรอ แล้วใช้ reply ถ้าเสร็จทัน; ถ้าเกินเวลาให้ fallback เป็น push (โควตา push ของแพ็กเกจฟรีจำกัด จึงใช้เฉพาะที่จำเป็น)
- **Flex Message**: การ์ดคำตอบแยกหัวข้อ สิทธิ / มาตรา / หลักฐาน / หน่วยงาน / ขั้นตอน + ปุ่ม URI ไปที่ตัวบทต้นฉบับ + footer "ข้อมูล ณ วันที่ … · ไม่ใช่คำปรึกษาทางกฎหมาย"
- **Quick Reply / คำสั่งสำหรับ demo**:
  - `/mode dense|graph|hybrid` และ `/llm local|api` เพื่อสลับสดตอนนำเสนอ ให้กรรมการเห็นความต่าง
  - `/debug` แสดง route, top sections+scores, graph path, latency ต่อ stage, tokens
  - `/reset` ล้าง history
- **Memory**: เก็บ history ใน **Neo4j** (`chat_history.py`) ใช้ 3 turns ล่าสุด rewrite คำถามต่อเนื่อง ("แล้วถ้าไม่จ่ายล่ะ") + คำสั่ง `ล้างประวัติ`
- **Logging**: ทุก request ลง JSONL (`tracing.py`) (query, route, retrieved ids, latency ต่อ stage, tokens, model, error) ใช้เป็นข้อมูล latency analysis ในรายงาน
- **Error handling**: Neo4j ล่มให้ degrade เป็น dense-only พร้อมแจ้งใน debug, LLM ล่มให้ใช้ fallback, input ยาว/ว่าง/สติกเกอร์ให้ตอบ guide
- **Guardrails**: ไม่อ้างว่าเป็นทนาย, ไม่มี context ให้ปฏิเสธ + แนะนำหน่วยงาน, กรณีซับซ้อน (คดีความ, จำนวนเงินสูง) ให้แนะนำปรึกษาทนาย/หน่วยงานรัฐ
- **Deploy**: `docker compose up -d neo4j` (ต้องเปิดแอป Docker Desktop ให้ daemon รันอยู่ก่อนเสมอ) + รัน Flask app local + เปิด HTTPS webhook ด้วย `cloudflared.exe tunnel --url http://localhost:5000` (binary มีอยู่แล้วที่ `Final-Project/cloudflared.exe`)

---

## 8. Evaluation & Analysis (10 คะแนน)

### 8.1 Test set: **50 คำถาม** (MVP กำหนด ≥20) มี gold label ครบ
| กลุ่ม | จำนวน | ตัวอย่าง |
|---|---|---|
| Lookup เจาะจงมาตรา | 8 | "มาตรา 118 ว่าด้วยอะไร" |
| Definition | 6 | "ค่าจ้างในวันหยุด หมายถึงอะไร" |
| Single-hop สิทธิ/หน้าที่ | 10 | "ลาป่วยได้กี่วันโดยได้ค่าจ้าง" |
| Multi-hop / บทลงโทษ | 10 | "นายจ้างไม่จ่าย OT มีโทษอะไร" |
| Procedure (หน่วยงาน/หลักฐาน/ขั้นตอน) | 8 | "นายจ้างไม่จ่ายค่าล่วงเวลา ต้องทำอย่างไร" |
| Aggregation | 4 | "ลูกจ้างมีสิทธิลาประเภทใดบ้าง" |
| Out-of-scope / ไม่มีคำตอบ | 4 | "ฟ้องหย่าต้องทำอย่างไร" |

Gold ต่อข้อ: `gold_sections[]`, `key_points[]` (3–5 ข้อ), `gold_agency`, `category`
แบ่งกันเขียน คนละ 25 ข้อ แล้ว **cross-check** กัน

### 8.2 Metrics
- **Retrieval** (ไม่ใช้ LLM ประหยัดเครดิต): Recall@5, MRR, nDCG@5, Hit@1 ระดับมาตรา
- **Generation**:
  - Citation Precision/Recall (มาตราที่อ้างในคำตอบเทียบ gold) วัดอัตโนมัติด้วย regex
  - Key-point coverage (LLM judge ตรวจทีละ key point)
  - Faithfulness (ทุก claim มีใน context ไหม) และ Answer relevance (LLM judge = qwen3.6-plus, prompt แบบ rubric 1–5)
  - **BERTScore + SBERT cosine** เทียบกับคำตอบ gold (reuse `eval_answers.py`)
  - Refusal accuracy ในกลุ่ม out-of-scope + **guard threshold sweep** (TAU_REJECT)
- **Baselines**: **No-RAG** (LLM ตอบเองเพื่อวัด hallucination) และ **Full-context** (ยัด พ.ร.บ.ทั้งฉบับเฉพาะ API ที่ context ยาว) ใช้พิสูจน์ว่า retrieval มีประโยชน์จริง
- **System**: latency p50/p95 ต่อ stage, tokens, credits, VRAM
- **Human eval**: ผู้ใช้ 5–8 คนลองผ่าน LINE ให้คะแนนความเข้าใจง่าย/ความพึงพอใจ 1–5 (ตรงกับหัวข้อการประเมินใน proposal)

### 8.3 ความลึกที่ทำให้ได้ Level 5
- **Judge validation**: ทีมให้คะแนนเอง 20 ข้อ เทียบกับ LLM judge (Cohen's κ / Spearman) เพื่อพิสูจน์ว่าเชื่อ judge ได้
- **Statistical test**: paired bootstrap 95% CI หรือ Wilcoxon ระหว่าง D vs H5
- **Per-category breakdown** (heatmap config × category)
- **Error analysis**: จัดหมวด failure 20 เคส → retrieval miss / entity-linking fail / graph ขาด edge / LLM hallucinate / ภาษาไทยตัดคำผิด พร้อมตัวอย่างจริงและแนวทางแก้
- **Case study** 2–3 ข้อ แสดง trace ของ Dense vs Graph vs Hybrid ด้านข้างกัน (เช่น คำถาม OT)

### 8.4 งบการรัน (ประมาณ)
- Retrieval ablation 8 configs × 50 ข้อ: ไม่ใช้ LLM
- Generation: {D, G, H5} × API หลัก = 150 calls + H5 × {2 local + 2 API เพิ่ม} = 200 calls → local ฟรี, API ราว 250 calls
- Judge ราว 350 calls → กระจายรันวันที่ 3–5 ให้อยู่ในเครดิตต่อวัน

---

## 9. Documentation / Presentation (5 คะแนน)
- `README.md`: setup (docker compose, .env, ollama pull, ingest, run, tunnel)
- **รายงาน** (ตามโครงบทที่ 1–5): ที่มา → Architecture diagram → Data/Graph design + เหตุผล → ผลการทดลองทุกตาราง + กราฟ → error analysis → ข้อจำกัด/จริยธรรม → งานต่อยอด
- **Slides ~12 หน้า** + **Demo video 3 นาที** (สำรองไว้กันเน็ต/LINE ล่มตอนนำเสนอ)
- Screenshot Neo4j Browser ของ subgraph คำถาม OT
- Diagram: architecture, graph schema, hybrid flow

---

## 10. โครงสร้าง Repo
```text
Final-Project/
├─ doc/                       # โจทย์, rubric, report, slides
├─ data/{raw,clean,chunks.jsonl,curated/*.csv}
├─ src/
│  ├─ ingest/  (scrape.py, pdf_extract.py, clean.py, parse_sections.py, chunk.py)
│  ├─ index/   (build_vector.py, build_bm25.py, build_graph.py, extract_triples.py)
│  ├─ retrieval/ (dense.py, bm25.py, graph.py, router.py, fusion.py, rerank.py, context.py)
│  ├─ llm/     (client.py  ← OpenAI SDK สำหรับ Ollama+dotBlue, prompts.py, budget.py)
│  ├─ app/     (app_line.py Flask, flex.py, chat_history.py)
│  └─ config.py
├─ eval/ (testset.jsonl, run_retrieval.py, run_generation.py, judge.py, analyze.ipynb, results/)
├─ docker-compose.yml  .env.example  requirements.txt  README.md
```

---

## 11. แผน 5 วัน (A = Data/Graph/Eval, B = Retrieval/LLM/LINE)

| วัน | คน A | คน B | Deliverable ปลายวัน |
|---|---|---|---|
| **D1** | ดึงตัวบท 3 พ.ร.บ. + คู่มือ, clean, parse มาตรา, chunks.jsonl + metadata | **Copy โมดูลจาก Project2 + chat_history + docker-compose**, LLM client (Ollama+dotBlue), **วัดเครดิต/call**, LINE channel + cloudflared | chunks.jsonl, LINE ตอบได้, เรียก LLM ได้ทั้งคู่ |
| **D2** | Graph: deterministic edges + LLM extraction (ontology validation จาก build_kg.py) + Topic taxonomy + curated CSV, validate 30 triples | Dense/BM25/rerank ต่อกับ chunks ใหม่ (reuse), Flex การ์ดกฎหมาย, เริ่ม MoE router | **Dense RAG ใช้บน LINE ได้**, กราฟอยู่ใน Neo4j |
| **D3** | Graph retrieval (entity linking + Cypher templates), **เขียน test set 50 ข้อ** (แบ่งกับ B คนละ 25) | Router + RRF + graph expansion + Section Card, `/mode` `/llm` `/debug`, logging, error handling/fallback | **Hybrid ครบ end-to-end บน LINE**, test set พร้อม |
| **D4** | รัน retrieval ablation 8 configs, Dense tuning (k/τ/rerank/chunk) | รัน generation eval Local vs API + judge, วัด latency/VRAM/credits, judge validation 20 ข้อ (ทำร่วมกัน) | ตารางผลทั้งหมด (raw) |
| **D5** | Analysis: stats, heatmap, error analysis, case study, เขียนรายงาน | แก้บั๊กตามผล eval (1 รอบ), README, user test 5–8 คน, ถ่าย demo video | รายงาน + slides + video + code |

**จุดตัดสินใจ (cut line) ถ้าเวลาไม่พอ** เรียงจากตัดก่อน: text2cypher → Typhoon model → embedding ablation → พ.ร.บ.ประกันสังคม/เงินทดแทน (เหลือแค่คุ้มครองแรงงาน) → human eval เหลือ 3 คน
**ห้ามตัด**: Hybrid ablation table, Local vs API table, error analysis ของส่วนนี้คือส่วนที่คะแนนเยอะที่สุด

---

## 12. Rubric → หลักฐานที่ต้องโชว์

| ด้าน (คะแนน) | สิ่งที่ทำให้ได้ Level 5 | หลักฐานในรายงาน/demo |
|---|---|---|
| Data (10) | structure-aware chunk, metadata ครบ, cleaning, graph-ready JSONL, quality report | สถิติ, ตัวอย่าง before/after, chunk ablation |
| Dense (15) | rerank + threshold + BM25 + tuning k | ตาราง Dense experiments |
| Graph (15) | schema 13 node types มีความหมาย, multi-hop Cypher, อธิบายข้อจำกัด Dense 4 ข้อ | schema diagram, Neo4j screenshot, D vs G ในกลุ่ม multi-hop |
| Hybrid (20) | Router + Weighted RRF + Graph expansion + Rerank + Section Card | **ablation D→H5 × category** + stats test |
| LLM (15) | 2–3 local + 3 API, config tuning, VRAM/tokens/s/cost, fallback/retry | ตาราง Local vs API + resource plot |
| Integration (10) | LINE→Router→Hybrid→LLM→Flex, error handling, logging, docker | architecture diagram + live demo `/debug` |
| Eval (10) | 50 Q gold, metrics 3 ระดับ, judge validation, CI, error analysis | notebook + figures |
| Docs (5) | README, report, slides, video | ไฟล์ส่ง |

---

## 13. ความเสี่ยงและแผนรับมือ
| ความเสี่ยง | แผนรับมือ |
|---|---|
| PDF ภาษาไทยสกัดแล้วเพี้ยน | ใช้ HTML ของกฤษฎีกา/คลังกฎหมายก่อน, PDF เป็นรอง, มี fix-table สำหรับสระ |
| เครดิต API หมด | cache ผล LLM ตาม hash(prompt), ใช้ PSU-gemma ตอน dev, retrieval eval ไม่ใช้ LLM |
| Local LLM ช้าเกินอายุ reply token | loading animation + push fallback, `num_ctx` 4096, โหลดโมเดลค้างไว้ |
| VRAM ไม่พอ | embed/rerank บน CPU ตอน query |
| LINE/tunnel ล่มวันนำเสนอ | demo video + CLI mode สำรอง |
| กฎหมายแก้ไข/ข้อมูลผิด | เก็บ status/amended_by/retrieved_date และแสดงใน footer ทุกคำตอบ |
| Docker Desktop ไม่ได้เปิด (daemon ไม่รัน) | เปิดแอป Docker Desktop ทิ้งไว้ตลอดช่วงพัฒนา/เดโม ตรวจด้วย `docker info` ก่อนรัน `docker compose up` ทุกครั้ง |

## 14. ความปลอดภัย
- เก็บ `DOTBLUE_API_KEY`, `LINE_CHANNEL_SECRET`, `LINE_CHANNEL_ACCESS_TOKEN`, `NEO4J_PASSWORD` ใน `.env` เท่านั้น และใส่ `.gitignore` ห้าม commit
- ตรวจ signature ของ LINE ทุก request, Cypher ใช้ parameter เสมอ (ห้าม f-string ต่อ query จากผู้ใช้)
- ไม่เก็บข้อมูลส่วนบุคคลเกินจำเป็น: log เก็บ userId แบบ hash
