# Neo4j results

เก็บภาพหน้าจอและผลลัพธ์ที่ได้จาก Neo4j Browser สำหรับรายงาน Day 4–5

**`table_node_counts.csv`/`table_relationship_counts.csv` อัปเดตแล้ว** (2026-09-27) ให้ตรงกับกราฟที่ merge triples/topics เข้าครบแล้ว (326 nodes/686 edges, 12 node types) — regenerate ได้ด้วย live query ผ่าน `docker compose up -d neo4j` แล้วโหลดกราฟด้วย `python -m src.index.graph_core data/chunks.jsonl --neo4j --triples data/triples.jsonl --review data/curated/triples_review_approved.csv --topics data/curated/topic_agency_evidence_form_step.csv` (คำสั่งเดียวกับที่ใช้ยืนยันตัวเลขในไฟล์นี้)

**`screenshot_*.png`/`graph_*.svg` ที่มีอยู่ยัง STALE** (จับภาพจากกราฟ deterministic-only 211 nodes/3 labels ก่อน merge) — ตัวเลขในไฟล์ csv ข้างต้นแก้ให้ถูกแล้ว แต่ภาพยังไม่ได้ถ่ายใหม่ (ต้องใช้ Neo4j Browser ในเบราว์เซอร์จริง ทำเองไม่ได้จาก shell) เปิด http://localhost:7474 (ล็อกอิน neo4j/รหัสใน `.env`) แล้วรัน query ใหม่ เช่น `MATCH (n) WHERE NOT n:ChatUser AND NOT n:ChatMessage RETURN n LIMIT 100` เพื่อถ่ายภาพกราฟที่มี Topic/Right/Duty/Agency ครบ ไม่ใช่แค่ Law/Chapter/Section

ไฟล์ภาพที่แนะนำ:

- `01_node_relationship_counts.png`
- `02_law_hierarchy.png`
- `03_refers_to.png`
- `04_penalized_by.png`
