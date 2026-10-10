"""Clean latency / resource benchmark: each LLM answers the same 10 questions
sequentially through the real RAGEngine (hybrid mode), run with nothing else
competing for the machine.  The 50-question matrix runs overlap other jobs
(parallel API runs, document builds) so their wall-clock latency is noisy;
this benchmark is the reference for Response-Time / VRAM / RAM figures.

For each model: warm-up question (not counted; loads the Ollama model and
caches), then N timed questions.  Records total / generate latency, prompt and
completion tokens, tokens/s, peak GPU VRAM (nvidia-smi, whole GPU), peak
process RSS and whole-system RAM.

Output: eval/results/bench_latency.csv  (one row per timed question)
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.run_generation import RAMSampler, VRAMSampler  # noqa: E402
from src import config  # noqa: E402
from src.app.engine import RAGEngine  # noqa: E402

TESTSET = ROOT / "eval" / "testset.jsonl"
OUT = ROOT / "eval" / "results" / "bench_latency.csv"
MODELS = [
    ("qwen3.6-flash", "api", "qwen/qwen3.6-flash"),
    ("gpt-4o-mini", "api", "gpt-4o-mini"),
    ("deepseek-chat", "api", "deepseek-chat"),
    ("qwen3.5:4b", "local", "qwen3.5:4b"),
    ("gemma3:4b", "local", "gemma3:4b"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=10)
    args = ap.parse_args()
    rows = [json.loads(line) for line in TESTSET.read_text(encoding="utf-8").splitlines() if line.strip()]
    # fixed, spread across categories: every 5th in-scope question
    qs = [r for r in rows if r["category"] != "out_of_scope"][:: 4][: args.n]
    engine = RAGEngine()
    out = []
    for name, provider, model in MODELS:
        if provider == "local":
            config.OLLAMA_MODEL = model
        else:
            config.DOTBLUE_MODEL = model
        engine.answer_with_debug("มาตรา 61 กำหนดเรื่องใด", session_id=f"warm-{name}", provider=provider, mode="hybrid")  # warm-up
        vram = VRAMSampler() if provider == "local" else None
        with RAMSampler() as ram:
            if vram:
                vram.__enter__()
            for i, r in enumerate(qs):
                t0 = time.time()
                _ans, dbg = engine.answer_with_debug(r["question"], session_id=f"bench-{name}-{i}", provider=provider, mode="hybrid")
                tot = time.time() - t0
                lat = dbg["latency"]
                u = dbg.get("usage", {})
                ct = u.get("completion_tokens") or 0
                gen = lat.get("generate") or 0
                out.append({"model": name, "kind": provider, "id": r["id"], "total_s": tot, "retrieve_s": lat.get("retrieve", 0),
                            "rerank_s": lat.get("rerank", 0), "generate_s": gen, "prompt_tokens": u.get("prompt_tokens"),
                            "completion_tokens": ct, "tok_per_s": (ct / gen) if gen else None,
                            "peak_vram_mib": vram.peak if vram else None, "peak_ram_proc_mib": ram.peak_rss, "peak_ram_sys_mib": ram.peak_system,
                            "fallback": dbg.get("provider_fallback")})
                print(f"[bench] {name} {i + 1}/{len(qs)} {tot:.1f}s", flush=True)
            if vram:
                vram.__exit__(None, None, None)
        print(name, "median total", statistics.median(x["total_s"] for x in out if x["model"] == name), flush=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
        w.writeheader()
        w.writerows(out)
    print("saved", OUT)


if __name__ == "__main__":
    main()
