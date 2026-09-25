import os
import re
from pythainlp.util import normalize

def thai_num_to_arabic(text):
    thai_nums = "๐๑๒๓๔๕๖๗๘๙"
    arabic_nums = "0123456789"
    trans = str.maketrans(thai_nums, arabic_nums)
    return text.translate(trans)

def clean_text_pipeline(text):
    # 1. ลบอักขระ Null (\u0000, \x00) ทีทำให้ JSON มีปัญหา
    text = text.replace('\x00', '').replace('\u0000', '')
    
    # 2. แก้ไขสระอำแตก
    text = text.replace("\u0E4D\u0E32", "\u0E33")
    
    # 3. แปลงเลขไทยเป็นอารบิก
    text = thai_num_to_arabic(text)
    
    # 4. ลบวงเล็บอ้างอิงเชิงอรรถ เช่น [1], [2 ], [ 12] ออกจากข้อความ
    text = re.sub(r'\[\s*\d+\s*\]', '', text)
    
    lines = text.split('\n')
    clean_lines = []
    
    for line in lines:
        line = line.strip()
        
        # 5. ลบ Header/Footer ขยะ (เพิ่มการดักจับ about:blank และ วันที/เวลา ของเว็บกฤษฎีกา)
        if re.search(r'เล่ม\s*\d+\s*ตอนที่', line) or \
           re.search(r'หน้า\s*\d+', line) or \
           re.search(r'ราชกิจจานุเบกษา', line) or \
           re.search(r'สำนักงานคณะกรรมการกฤษฎ', line.replace(' ', '')) or \
           re.search(r'about:blank', line) or \
           re.search(r'\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}', line) or \
           line == "-" or re.match(r'^-\s*\d+\s*-$', line):
            continue
            
        if line:
            # ลบช่องว่างซ้ำซ้อน
            line = re.sub(r' +', ' ', line)
            clean_lines.append(line)
            
    combined_text = "\n".join(clean_lines)
    
    # 6. ตัดส่วนท้ายที่เป็นประวัติการแก้ไขและบรรณานุกรมทิ้งไป (ไม่นำมาทำ RAG)
    split_keywords = ["ผู้รบั สนองพระบรมราชโองการ", "ผู้รับสนองพระบรมราชโองการ", "อัตราค่าธรรมเนียม"]
    for kw in split_keywords:
        if kw in combined_text:
            combined_text = combined_text.split(kw)[0]
            
    # 7. จัดการลำดับสระด้วย PyThaiNLP
    return normalize(combined_text).strip()

def clean_raw_files(input_dir="data/raw", output_dir="data/clean"):
    # อ่านเฉพาะไฟล์ .txt
    raw_files = [f for f in os.listdir(input_dir) if f.endswith(".txt") and not f.startswith(".")]
    
    if not raw_files:
        print(f"❌ ไม่พบไฟล์ .txt ใน {input_dir} (ต้องรัน pdf_extract.py ก่อน)")
        return

    for raw_file in raw_files:
        input_path = os.path.join(input_dir, raw_file)
        clean_filename = raw_file.replace("_raw.txt", ".txt").replace("_2.txt", ".txt")
        output_path = os.path.join(output_dir, clean_filename)
        
        print(f"กำลังทำความสะอาด: {raw_file} ...")
        with open(input_path, "r", encoding="utf-8") as f:
            raw_text = f.read()
            
        cleaned_text = clean_text_pipeline(raw_text)
        
        os.makedirs(output_dir, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(cleaned_text)
            
        print(f"✅ ทำความสะอาดเสร็จสิ้น บันทึกไว้ที่: {output_path}")

if __name__ == "__main__":
    clean_raw_files()