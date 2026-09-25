import os
import re
import time
import requests
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (compatible; ThaiLawAssistant-Ingest/1.0; educational research project)"

# กรมสวัสดิการและคุ้มครองแรงงาน (labour.go.th) — 3 หมวด FAQ, เป็น Joomla article
# แบบ static HTML (ตรวจสอบแล้วว่าไม่ต้องพึ่ง JS) โครงสร้าง:
#   <div itemprop="articleBody"> <p><strong>คำถามที่ N</strong><br/>
#     <strong>ถาม :</strong> ... <br/><strong>ตอบ :</strong> ... <br/><br/> ... </p>
LABOUR_FAQ_SOURCES = [
    ("FAQ_คุ้มครองแรงงาน_labour.go.th", "https://www.labour.go.th/index.php/faq/47773-faq2"),
    ("FAQ_แรงงานสัมพันธ์_labour.go.th", "https://www.labour.go.th/index.php/faq/47774-faq3"),
    ("FAQ_สวัสดิการแรงงาน_labour.go.th", "https://www.labour.go.th/index.php/faq/47772-faq1"),
]

# หมายเหตุ: FAQ ของ สนง.ประกันสังคม (sso.go.th/wpr/main/faq/...) โหลดคำตอบผ่าน
# DataTable AJAX (Liferay) ไม่มีอยู่ใน static HTML — ต้องใช้ browser render ซึ่งเกิน
# scope ของ scraper นี้ ใช้ "คู่มือนายจ้าง กองทุนเงินทดแทน" (PDF ทางการจาก sso.go.th)
# แทนสำหรับฝั่งประกันสังคม ดู data/raw/*สปส*.pdf + pdf_extract.py

QA_PATTERN = re.compile(
    r"ถาม\s*[:：]\s*(.+?)\s*ตอบ\s*[:：]\s*(.+?)(?=(?:คำถามที่\s*\d+)|\Z)",
    re.S,
)


def fetch(url, timeout=20):
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding
    return resp.text


def parse_joomla_faq(html):
    """แกะคู่ ถาม/ตอบ จาก div[itemprop=articleBody] ของหน้า FAQ labour.go.th"""
    soup = BeautifulSoup(html, "lxml")
    body = soup.find("div", itemprop="articleBody")
    if body is None:
        return []

    for br in body.find_all("br"):
        br.replace_with("\n")

    text = body.get_text()
    pairs = []
    for q, a in QA_PATTERN.findall(text):
        q = re.sub(r"\s+", " ", q).strip()
        a = re.sub(r"\s+", " ", a).strip()
        if q and a:
            pairs.append((q, a))
    return pairs


def scrape_labour_faq(output_dir="data/raw"):
    """ดึง FAQ ทั้ง 3 หมวดจากกรมสวัสดิการและคุ้มครองแรงงาน บันทึกเป็น _raw.txt
    (รูปแบบเดียวกับ pdf_extract.py เพื่อให้ clean.py รันต่อได้ทันที)"""
    os.makedirs(output_dir, exist_ok=True)

    for name, url in LABOUR_FAQ_SOURCES:
        print(f"กำลังดึง FAQ: {url} ...")
        try:
            html = fetch(url)
        except requests.RequestException as e:
            print(f"❌ ดึงไม่สำเร็จ {url}: {e}")
            continue

        pairs = parse_joomla_faq(html)
        if not pairs:
            print(f"❌ ไม่พบคู่ ถาม/ตอบ ใน {url} (โครงสร้างหน้าอาจเปลี่ยนไป)")
            continue

        out_path = os.path.join(output_dir, f"{name}_raw.txt")
        with open(out_path, "w", encoding="utf-8") as f:
            for i, (q, a) in enumerate(pairs, 1):
                f.write(f"คำถามที่ {i}\nถาม: {q}\nตอบ: {a}\n\n")

        print(f"✅ บันทึก {len(pairs)} คู่ ถาม/ตอบ ไว้ที่: {out_path}")
        time.sleep(1)  # กันยิง request รัวเกินไปใส่เซิร์ฟเวอร์ราชการ


if __name__ == "__main__":
    scrape_labour_faq()
