# Slides Outline (~12 หน้า) — ThaiLaw Assistant

ตัวเลข/ตารางที่มี `[ ]` ให้ดึงจาก `doc/report.md` ฉบับสมบูรณ์ (เขียนหลัง Day4 experiments เสร็จ) ก่อน present จริง

1. **Title** — ThaiLaw Assistant: ผู้ช่วยกฎหมายแรงงานไทยด้วย Hybrid GraphRAG บน LINE, ชื่อทีม/สมาชิก
2. **ปัญหา + เป้าหมาย** — ลูกจ้าง/นายจ้างเข้าถึงข้อมูลกฎหมายแรงงานยาก, ต้องการผู้ช่วยที่ตอบเร็ว มีอ้างอิงมาตราจริง ตรวจสอบได้
3. **Architecture Diagram** — จาก `doc/PLAN.md` §1 (LINE → Query Processing → Dense/BM25/Graph → Hybrid Fusion → LLM → Flex Message)
4. **Data & Knowledge Base** — 1 พ.ร.บ., 187 มาตรา, 195 chunks, structure-aware chunking (1 มาตรา/chunk), metadata schema, cleaning pipeline + known limitation (glyph corruption ~1.5%)
5. **Graph Schema** — 326 nodes / 686 edges, 12/13 node types ตาม PLAN §4.2, screenshot Neo4j Browser (ของจริง ไม่ใช่ stale), เหตุผลว่าทำไม Graph ช่วยแก้ข้อจำกัดของ Dense (บทลงโทษแยกหมวด/cross-reference/aggregation)
6. **Dense RAG experiments** — ตาราง Top-K/threshold/rerank/chunking sweep `[ผลจาก retrieval_dense_tuning.csv]`
7. **Hybrid RAG ablation (หัวใจของงาน)** — ตาราง D→H5 × category heatmap `[ผลจาก analyze.ipynb]`, ชี้ให้เห็นว่า Hybrid ชนะกลุ่มไหนบ้างและทำไม
8. **Local LLM vs API LLM** — ตารางเทียบ correctness/faithfulness/citation/latency/VRAM/cost `[ผลจาก generation_*.csv + judge_scores.csv]`
9. **Judge validation + Statistical test** — Cohen's κ/Spearman ระหว่างคนกับ judge `[judge_validation_result.json]`, bootstrap CI/Wilcoxon D vs H5
10. **Error Analysis + Case Study** — ตัวอย่างเคสจริงที่พลาด (retrieval miss/entity-linking fail/hallucination), เคส OT trace Dense vs Graph vs Hybrid ข้างกัน
11. **System Integration + Demo** — `/mode` `/llm` `/debug` `/reset`, error handling/fallback, screenshot LINE จริง, ลิงก์ demo video
12. **สรุป + ข้อจำกัด + งานต่อยอด** — สิ่งที่ทำสำเร็จ, ข้อจำกัด (VRAM 6GB, ครอบคลุมแค่ พ.ร.บ.เดียว, ภาษาไทยของโมเดลเล็กยังเพี้ยนบ้าง), แนวทางต่อยอด (text2cypher, พ.ร.บ.เพิ่มเติม, human eval ขยาย)

## Design notes
- ใส่ตัวเลขจริงเท่านั้น (ห้าม placeholder ตอน present จริง) — ถ้าตัวไหนยังไม่มีให้ตัดสไลด์นั้นออกดีกว่าใส่เลขมั่ว
- หน้า 6–10 คือหน้าที่กรรมการดูนานที่สุด (ตรง Rubric ข้อ Dense/Graph/Hybrid/Eval ที่คะแนนเยอะสุด) ให้เวลาทำมากที่สุด
