import os
import re
from pythainlp.util import normalize

def thai_num_to_arabic(text):
    thai_nums = "๐๑๒๓๔๕๖๗๘๙"
    arabic_nums = "0123456789"
    trans = str.maketrans(thai_nums, arabic_nums)
    return text.translate(trans)

def clean_text_pipeline(text):
    # 1. แก้ไขสระอำแตก
    text = text.replace("\u0E4D\u0E32", "\u0E33")
    # 2. แปลงเลขไทยเป็นอารบิก
    text = thai_num_to_arabic(text)
    
    lines = text.split('\n')
    clean_lines = []
    
    for line in lines:
        line = line.strip()
        # 3. ลบ Header/Footer ขยะ
        if re.search(r'เล่ม\s*\d+\s*ตอนที่', line) or \
           re.search(r'หน้า\s*\d+', line) or \
           re.search(r'ราชกิจจานุเบกษา', line) or \
           re.search(r'สำนักงานคณะกรรมการกฤษฎีกา', line) or \
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