import os
import re
from pythainlp.util import normalize

# Header/footer ขยะจากหน้าเว็บกฤษฎีกาที่ print เป็น PDF (เช่น "11/12/68 13:54
# สำนักงานคณะกรรมการกฤษฎีกา", "about:blank", เลขหน้า "N/52") — match แบบทั้งบรรทัด
# เท่านั้น ห้ามใช้ substring กว้างๆ เช่น "หน้า"/"เล่ม"/"ราชกิจจานุเบกษา" เพราะคำพวกนี้
# ปรากฏจริงในบรรทัดอ้างอิงแก้ไขกฎหมาย (เช่น "ราชกิจจานุเบกษา เล่ม 119/ตอนที่ 102 ก/
# หน้า 66/8 ตุลาคม 2545") ซึ่งเป็นเนื้อหาจริงที่ Day2 ต้องใช้ตาม "(ยกเลิก)/แก้ไขโดย"
# — ของเดิม match กว้างเกินจนลบบรรทัดอ้างอิงพวกนี้ทิ้งไปทั้งหมด
FOOTER_LINE_PATTERNS = [
    re.compile(r'^\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}(\s+สำนักงานคณะกรรมการกฤษฎีกา)?$'),
    re.compile(r'^สำนักงานคณะกรรมการกฤษฎีกา$'),
    re.compile(r'about:blank'),
    re.compile(r'^\d+/\d+$'),
]

def thai_num_to_arabic(text):
    thai_nums = "๐๑๒๓๔๕๖๗๘๙"
    arabic_nums = "0123456789"
    trans = str.maketrans(thai_nums, arabic_nums)
    return text.translate(trans)

def clean_text_pipeline(text):
    # 1. แก้ไขสระอำแตก
    text = text.replace("ํา", "ำ")
    # 1b. บางไฟล์ (เช่น PDF ของ สปส.) ใช้ font ที่มี ToUnicode CMap ผิด แปลงสระ "ำ"
    # เป็น "Ğ" (U+011E) หรือหายไปเป็น U+FFFD (unknown glyph) แทน — สุ่มตรวจทุกจุด
    # (47 จุดใน SSO PDF) พบว่าอยู่ในบริบท "ำ" ล้วน (ดำเนิน, ชำระ, ทำงาน, คำตอบ ฯลฯ)
    # และไม่พบอักขระทั้งสองตัวนี้เลยในเอกสารกฎหมายที่ extract ถูกต้อง จึง replace
    # กลับเป็น "ำ" ได้อย่างปลอดภัย
    text = text.replace("Ğ", "ำ").replace("�", "ำ")
    # 2. แปลงเลขไทยเป็นอารบิก
    text = thai_num_to_arabic(text)

    lines = text.split('\n')
    clean_lines = []

    for line in lines:
        line = line.strip()
        # 3. ลบ Header/Footer ขยะ (match ทั้งบรรทัด ไม่ใช้ substring กว้าง)
        if any(p.search(line) for p in FOOTER_LINE_PATTERNS) or \
           line == "-" or re.match(r'^-\s*\d+\s*-$', line):
            continue

        if line:
            # 4. ลบช่องว่างซ้ำซ้อน
            line = re.sub(r' +', ' ', line)
            clean_lines.append(line)

    combined_text = "\n".join(clean_lines)
    # 5. จัดการลำดับสระด้วย PyThaiNLP
    return normalize(combined_text).strip()

def clean_raw_files(input_dir="data/raw", output_dir="data/clean"):
    """อ่านไฟล์ _raw.txt มาทำความสะอาด แล้วบันทึกลง data/clean"""
    os.makedirs(output_dir, exist_ok=True)
    raw_files = [f for f in os.listdir(input_dir) if f.endswith("_raw.txt")]

    if not raw_files:
        print(f"❌ ไม่พบไฟล์ _raw.txt ใน {input_dir} (ต้องรัน pdf_extract.py ก่อน)")
        return

    for raw_file in raw_files:
        input_path = os.path.join(input_dir, raw_file)

        # ตัดคำว่า _raw ออก เพื่อให้ชื่อไฟล์ปลายทางสวยงาม
        clean_filename = raw_file.replace("_raw.txt", ".txt")
        output_path = os.path.join(output_dir, clean_filename)

        print(f"กำลังทำความสะอาด: {raw_file} ...")
        with open(input_path, "r", encoding="utf-8") as f:
            raw_text = f.read()

        cleaned_text = clean_text_pipeline(raw_text)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(cleaned_text)

        print(f"✅ ทำความสะอาดเสร็จสิ้น บันทึกไว้ที่: {output_path}")

if __name__ == "__main__":
    clean_raw_files()
