import json
import re
import os

if __name__ == "__main__":
    from .day2_chunk import main as _day2_main
    _day2_main()
    raise SystemExit

def create_chunks_and_metadata(input_file, output_file, law_id, law_name, source_url):
    print(f"กำลังสร้าง Chunks และ Metadata จาก: {input_file}")
    
    if not os.path.exists(input_file):
        print(f"❌ ไม่พบไฟล์ {input_file}")
        return

    with open(input_file, 'r', encoding='utf-8') as f:
        parsed_sections = json.load(f)

    chunks = []
    
    for sec in parsed_sections:
        section_no = sec["section_no"]
        text = sec["text"]
        
        # สกัดการอ้างอิงข้ามมาตรา
        refs_out = re.findall(r'มาตรา\s*(\d+)', text)
        refs_out = list(set([r for r in refs_out if r != section_no]))
        
        # สร้าง Schema ตาม PLAN.md 2.4
        chunk = {
            "chunk_id": f"{law_id}-s{section_no}",
            "law_id": law_id,
            "law_name": law_name,
            "chapter": sec["chapter"],
            "section_no": section_no,
            "paragraph": 1, # โครงสร้างเบื้องต้นให้ทั้งมาตราเป็น 1 chunk
            "doc_type": "statute",
            "status": sec["status"],
            "amended_by": [], 
            "refs_out": refs_out,
            "source_url": source_url,
            "retrieved_date": "2026-09-25",
            "text": text
        }
        chunks.append(chunk)

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + '\n')
            
    print(f"✅ สร้าง Chunks เสร็จสิ้น เตรียมพร้อมสำหรับ Vector/Graph")
    print(f"💾 บันทึกไฟล์ JSONL ที่: {output_file}")

if __name__ == "__main__":
    input_json = "data/clean/parsed_LPA2541.json"
    output_jsonl = "data/chunks.jsonl"
    
    create_chunks_and_metadata(
        input_file=input_json,
        output_file=output_jsonl,
        law_id="LPA2541",
        law_name="พระราชบัญญัติคุ้มครองแรงงาน พ.ศ. 2541",
        source_url="https://www.ocs.go.th"
    )

# Canonical Day 2 implementation. Keeps existing import path stable.
try:
    from .day2_chunk import create_chunks, create_chunks_and_metadata, write_chunks
except ImportError:
    pass
