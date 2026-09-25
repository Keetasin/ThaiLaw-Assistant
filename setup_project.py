import os

# 1. รายชื่อโฟลเดอร์ที่ต้องสร้าง
directories = [
    "doc",
    "data/raw",
    "data/clean",
    "data/curated",
    "src/ingest",
    "src/index",
    "src/retrieval",
    "src/llm",
    "src/app",
    "eval/results"
]

# 2. รายชื่อไฟล์ที่ต้องสร้าง พร้อมคอมเมนต์อธิบายสั้นๆ
files = {
    # ฝั่ง Ingest (ดึงข้อมูลและทำความสะอาด)
    "src/ingest/scrape.py": "# สำหรับดึงข้อมูลจากเว็บ",
    "src/ingest/pdf_extract.py": "# สำหรับสกัดข้อความจาก PDF",
    "src/ingest/clean.py": "# สำหรับทำความสะอาดข้อความ (แก้สระ, เลขไทย)",
    "src/ingest/parse_sections.py": "# สำหรับใช้ Regex แยกมาตรา",
    "src/ingest/chunk.py": "# สำหรับแบ่ง Chunk และใส่ Metadata",
    
    # ฝั่ง Index (จัดทำดัชนีและ Knowledge Graph)
    "src/index/build_vector.py": "# นำข้อมูลทำ Embedding เข้า ChromaDB",
    "src/index/build_bm25.py": "# สร้าง BM25 Index (word + 3-gram)",
    "src/index/build_graph.py": "# สร้าง Knowledge Graph พื้นฐานลง Neo4j",
    "src/index/extract_triples.py": "# ใช้ LLM สกัด Triples (Right/Duty/Penalty)",
    
    # ฝั่ง Retrieval (ดึงข้อมูลมาตอบ)
    "src/retrieval/dense.py": "# ค้นหาด้วย Dense (ChromaDB)",
    "src/retrieval/bm25.py": "# ค้นหาด้วย BM25",
    "src/retrieval/graph.py": "# ค้นหาด้วย Graph (Cypher)",
    "src/retrieval/router.py": "# MoE Router แยกประเภทคำถาม",
    "src/retrieval/fusion.py": "# รวมผลลัพธ์ด้วย Weighted RRF และ Graph Expansion",
    "src/retrieval/rerank.py": "# จัดลำดับใหม่ด้วย Cross-encoder",
    "src/retrieval/context.py": "# จัดโครงสร้าง Section Card ก่อนส่งให้ LLM",
    
    # ฝั่ง LLM
    "src/llm/client.py": "# LLM Client ใช้ OpenAI SDK (สำหรับ Ollama และ dotBlue)",
    "src/llm/prompts.py": "# เก็บ Prompt templates",
    "src/llm/budget.py": "# คำนวณและตัด Token ให้อยู่ใน Budget",
    
    # ฝั่ง App (LINE Bot)
    "src/app/app_line.py": "# Flask Webhook Server",
    "src/app/flex.py": "# สร้างหน้าตา Flex Message",
    "src/app/chat_history.py": "# ดึงและบันทึกประวัติการแชทใน Neo4j",
    
    # ฝั่ง Config
    "src/config.py": "# ตั้งค่า Environment และตัวแปรระบบ",
    
    # ฝั่ง Evaluation
    "eval/testset.jsonl": "",
    "eval/run_retrieval.py": "# รันประเมินผล Retrieval (Recall, MRR, nDCG)",
    "eval/run_generation.py": "# รันประเมินผลฝั่ง LLM Generation",
    "eval/judge.py": "# ใช้ LLM ตรวจคำตอบ (LLM-as-a-judge)",
    "eval/analyze.ipynb": "",
    
    # ไฟล์ตั้งค่าที่ Root
    "docker-compose.yml": "# สำหรับรัน Neo4j",
    ".env.example": "LINE_CHANNEL_SECRET=\nLINE_CHANNEL_ACCESS_TOKEN=\nNEO4J_PASSWORD=\nDOTBLUE_API_KEY=",
    "requirements.txt": "Flask\nline-bot-sdk==3.21.0\nneo4j\npdfplumber\npythainlp\npydantic\nchromadb\nsentence-transformers\ntiktoken\nopenai\nrank_bm25",
    "README.md": "# ThaiLaw Assistant"
}

# 3. เริ่มสร้างโฟลเดอร์
for d in directories:
    os.makedirs(d, exist_ok=True)
    print(f"📁 สร้างโฟลเดอร์: {d}")

# 4. เริ่มสร้างไฟล์
for f_path, content in files.items():
    if not os.path.exists(f_path):
        with open(f_path, "w", encoding="utf-8") as file:
            file.write(content + "\n")
        print(f"📄 สร้างไฟล์: {f_path}")

print("\n✅ สร้างโครงสร้างโปรเจกต์เสร็จสมบูรณ์!")