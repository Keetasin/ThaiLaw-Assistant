import os
import pdfplumber

def extract_pdf_to_text(input_dir="data/raw"):
    """อ่านไฟล์ PDF ทั้งหมดในโฟลเดอร์ และบันทึกเป็นไฟล์ข้อความดิบ"""
    pdf_files = [f for f in os.listdir(input_dir) if f.endswith(".pdf")]
    
    if not pdf_files:
        print(f"❌ ไม่พบไฟล์ PDF ใน {input_dir}")
        return

    for pdf_file in pdf_files:
        pdf_path = os.path.join(input_dir, pdf_file)
        raw_txt_filename = os.path.splitext(pdf_file)[0] + "_raw.txt"
        output_path = os.path.join(input_dir, raw_txt_filename)
        
        print(f"กำลังสกัดข้อความดิบจาก: {pdf_file} ...")
        full_text = []
        
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages:
                text = page.extract_text(x_tolerance=2, y_tolerance=3)
                if text:
                    full_text.append(text)
                    
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(full_text))
            
        print(f"✅ สกัดข้อความสำเร็จ บันทึกไว้ที่: {output_path}")

if __name__ == "__main__":
    extract_pdf_to_text()