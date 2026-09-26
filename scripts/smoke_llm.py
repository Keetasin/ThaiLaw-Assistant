"""Day 1 check: confirm both LLM backends are reachable and Thai-capable.



Run: python -m scripts.smoke_llm
"""
from src import config
from src.llm.client import get_llm

PROMPT = "ตอบสั้นๆ 1 ประโยค: กรุงเทพมหานครอยู่ในประเทศอะไร"


def _run(label, provider, model=None):
    print(f"\n--- {label} ---")
    llm = get_llm(provider=provider, model=model)
    try:
        text, usage = llm.chat([{"role": "user", "content": PROMPT}])
        print(f"answer: {text.strip()}")
        print(f"usage:  {usage}")
    except Exception as e:
        print(f"FAILED: {e!r}")


if __name__ == "__main__":
    _run("Ollama (local)", "local", model=config.OLLAMA_MODEL)
    _run("dotBlue API", "api", model=config.DOTBLUE_MODEL)
