"""Day 1: measure token usage per call against the PAID dotBlue model
(config.DOTBLUE_MODEL, e.g. qwen/qwen3.6-flash).

This script only prints token usage per call — the actual credit delta has
no API; check the dotBlue dashboard's remaining-credit number before and
after running this, then divide by N_CALLS yourself.

Run: python -m scripts.measure_dotblue_credit
"""
from src import config
from src.llm.client import get_llm

N_CALLS = 5
PROMPTS = [
    "นายจ้างไม่จ่ายค่าล่วงเวลาต้องทำอย่างไร ตอบสั้นๆ",
    "ลาป่วยได้กี่วันโดยได้รับค่าจ้าง ตอบสั้นๆ",
    "ค่าจ้างขั้นต่ำคืออะไร ตอบสั้นๆ",
    "ลูกจ้างมีสิทธิลาประเภทใดบ้าง ตอบสั้นๆ",
    "นายจ้างเลิกจ้างโดยไม่บอกล่วงหน้าผิดกฎหมายหรือไม่ ตอบสั้นๆ",
][:N_CALLS]

if __name__ == "__main__":
    print(f"Model: {config.DOTBLUE_MODEL}")
    print("Check the dotBlue dashboard credit number NOW (before), then run this script.\n")

    llm = get_llm(provider="api", model=config.DOTBLUE_MODEL)
    total_prompt, total_completion = 0, 0
    for i, p in enumerate(PROMPTS, 1):
        text, usage = llm.chat([{"role": "user", "content": p}])
        pt, ct = usage.get("prompt_tokens") or 0, usage.get("completion_tokens") or 0
        total_prompt += pt
        total_completion += ct
        print(f"[{i}] tokens: prompt={pt} completion={ct} latency={usage['latency_s']:.2f}s")

    print(f"\nTotal over {len(PROMPTS)} calls: prompt={total_prompt} completion={total_completion}")
    print("Now check the dotBlue dashboard credit number again (after) and record the delta")
    print("in doc/SPLIT.md's Day-1 notes or doc/dotblue_credits.md, e.g.:")
    print("  qwen/qwen3.6-flash (x1): N credits / 5 calls -> N/5 credits per call")
