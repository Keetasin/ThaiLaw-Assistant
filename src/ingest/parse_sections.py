import re
import json
import os

if __name__ == "__main__":
    from .parse_core import main as _core_main
    _core_main()
    raise SystemExit

def parse_law_text(input_file, output_file):
    print(f"กำลังแยกโครงสร้างมาตราจาก: {input_file}")
    
    if not os.path.exists(input_file):
        print(f"❌ ไม่พบไฟล์ {input_file}")
        return

    with open(input_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    parsed_sections = []
    current_chapter = "ไม่ระบุหมวด"
    current_section_no = ""
    current_section_text = []

    def save_current_section():
        if current_section_no and current_section_text:
            full_text = "\n".join(current_section_text).strip()
            # ตัดบรรทัดว่างที่อาจแทรกอยู่ออก
            full_text = re.sub(r'\n+', '\n', full_text)
            
            status = "repealed" if "(ยกเลิก)" in full_text or "ยกเลิกโดย" in full_text else "in_force"
            
            parsed_sections.append({
                "chapter": current_chapter,
                "section_no": current_section_no,
                "text": full_text,
                "status": status
            })

    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # จับ หมวด หรืิอ ลักษณะ
        if line.startswith("หมวด") or line.startswith("ลักษณะ"):
            current_chapter = line
            continue
            
        # จับ มาตรา (ตัวเลขเท่านั้น ป้องกันความผิดพลาด)
        sec_match = re.match(r'^มาตรา\s*(\d+)(.*)', line)
        if sec_match:
            save_current_section()
            current_section_no = sec_match.group(1)
            current_section_text = [line]
        else:
            if current_section_no: # เก็บเฉพาะบรรทัดที่ตามหลังมาตราแล้วเท่านั้น
                current_section_text.append(line)

    save_current_section() # บันทึกมาตราสุดท้าย

    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        # ใช้ indent=2 เพื่อให้อ่านด้วยตาเปล่าง่ายขึ้น
        json.dump(parsed_sections, f, ensure_ascii=False, indent=2)
        
    print(f"✅ สกัดโครงสร้างเสร็จสิ้น ได้ทั้งหมด {len(parsed_sections)} มาตรา")
    print(f"💾 บันทึกข้อมูลที่: {output_file}")

if __name__ == "__main__":
    # ตรวจสอบชื่อไฟล์ให้ตรงกับที่ได้จาก clean.py (แนะนำให้เปลี่ยนชื่อไฟล์ตั้งต้นให้สั้นลงถ้าเป็นไปได้)
    input_txt = "data/clean/พ.ร.บ.คุ้มครองแรงงาน พ.ศ. 2541 (ฉบับปรังปรุงล่าสุด).txt"
    output_json = "data/clean/parsed_LPA2541.json"
    
    # กรณีไฟล์หาไม่เจอ ให้เช็คชื่อไฟล์ใน data/clean/ แทน
    if not os.path.exists(input_txt):
        clean_dir = "data/clean"
        if os.path.exists(clean_dir):
            files = [f for f in os.listdir(clean_dir) if "คุ้มครองแรงงาน" in f and f.endswith(".txt")]
            if files:
                input_txt = os.path.join(clean_dir, files[0])
                
    parse_law_text(input_txt, output_json)

# Canonical Day 2 implementation. Keeps existing import path stable.
try:
    from .parse_core import parse_lines, parse_law_text, normalize_digits
except ImportError:
    pass
