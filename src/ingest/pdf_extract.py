import os
import fitz  # PyMuPDF

def extract_pdf_to_text(input_dir="data/raw"):
    """อ่านไฟล์ PDF ทั้งหมดในโฟลเดอร์ และบันทึกเป็นไฟล์ข้อความดิบ

    ใช้ PyMuPDF แทน pdfplumber: ทดสอบแล้วพบว่า pdfplumber สลับลำดับ
    สระ/วรรณยุกต์/ตัวอักษรไทยที่วางซ้อนกัน (เช่น "คุ้มครอง" กลายเป็น "ค้มุ ครอง")
    ซึ่งเป็นปัญหาลำดับตัวอักษรจริง ไม่ใช่แค่ unicode combining order เลย
    pythainlp.normalize() แก้ไม่ได้ ส่วน PyMuPDF (get_text(sort=True))
    คืนลำดับที่ถูกต้องและยังจัดเลขอ้างอิงเชิงอรรถ เช่น "มาตรา ๒ [1]" ให้อยู่ใน
    บรรทัดเดียวกับเนื้อหาด้วย
    """
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

        with fitz.open(pdf_path) as pdf:
            for page in pdf:
                text = page.get_text(sort=True)
                if text:
                    full_text.append(text)

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(full_text))

        print(f"✅ สกัดข้อความสำเร็จ บันทึกไว้ที่: {output_path}")

if __name__ == "__main__":
    extract_pdf_to_text()