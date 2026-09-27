"""Generation eval: Local vs API LLM matrix on the best retrieval config
(H5/hybrid), num_ctx sweep, No-RAG and Full-context baselines (PLAN.md §6, §8).

Reuses RAGEngine (src/app/engine.py) end-to-end instead of re-implementing
retrieval+generation — this is the exact same code path app_line.py runs on
LINE, so results reflect production behavior, not a parallel eval-only stack.
Model swap per matrix row works by mutating config.OLLAMA_MODEL/DOTBLUE_MODEL
before the call: src/llm/client.py's OllamaClient/DotBlueClient read those
at __init__ time (per-call, not cached), so this is safe and needs no new
plumbing in engine.py or client.py.
"""
from __future__ import annotations

import argparse
import contextlib
import csv
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config
from src.app import generator
from src.app.engine import RAGEngine
from src.llm.client import OllamaClient, get_llm
from src.retrieval.context import build_section_cards

RESULTS = ROOT / "eval" / "results"
TESTSET = ROOT / "eval" / "testset.jsonl"
FULL_TEXT_PATH = ROOT / "data" / "clean" / "พ.ร.บ.คุ้มครองแรงงาน พ.ศ. 2541 (ฉบับปรังปรุงล่าสุด).txt"
SECTION_RE = re.compile(r"มาตรา\s*([0-9๐-๙]+(?:\s*/\s*[0-9๐-๙]+)?)")

# label -> (retrieval mode, provider, model). All 7 rows together match
# PLAN.md §8.4's budget: {D,G,H5} x qwen3.6-flash = 150 API calls (retrieval-
# config comparison on one model) + H5 x {2 local, 2 more API} = 200 calls
# (100 free local + 100 more API) -> ~250 API calls total, well inside the
# >800-credit balance confirmed before this run.
MATRIX = [
    ("D_api_qwen-flash", "dense", "api", config.DOTBLUE_MODEL),
    ("G_api_qwen-flash", "graph", "api", config.DOTBLUE_MODEL),
    ("H5_api_qwen-flash", "hybrid", "api", config.DOTBLUE_MODEL),
    ("H5_local_qwen3.5-4b", "hybrid", "local", "qwen3.5:4b"),
    ("H5_local_gemma3-4b", "hybrid", "local", "gemma3:4b"),
    ("H5_api_gpt-4o-mini", "hybrid", "api", "gpt-4o-mini"),
    ("H5_api_deepseek-chat", "hybrid", "api", "deepseek-chat"),
]
NUM_CTX_MODELS = ("qwen3.5:4b", "gemma3:4b")
NUM_CTX_VALUES = (2048, 4096, 8192)


def load_rows(sample: int | None = None) -> list[dict]:
    rows = [json.loads(line) for line in TESTSET.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows[:sample] if sample else rows


def _gold_section_nos(gold_sections: list[str]) -> set[str]:
    # chunk_id shape is "LPA2541-s61-p1" -> section number "61"
    return {g.split("-s", 1)[1].split("-p", 1)[0] for g in gold_sections if "-s" in g}


def citation_metrics(answer: str, gold_sections: list[str]) -> dict:
    gold_nos = _gold_section_nos(gold_sections)
    cited = {n.replace(" ", "") for n in SECTION_RE.findall(answer)}
    if not gold_nos:
        return {"citation_precision": None, "citation_recall": None}
    tp = len(cited & gold_nos)
    return {
        "citation_precision": tp / len(cited) if cited else 0.0,
        "citation_recall": tp / len(gold_nos),
    }


class VRAMSampler:
    """Background nvidia-smi poll; tracks peak MiB used across the `with` block."""

    def __init__(self, interval: float = 0.5):
        self.interval = interval
        self.peak = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _poll(self):
        while not self._stop.is_set():
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, timeout=2,
                )
                self.peak = max(self.peak, int(out.stdout.strip().splitlines()[0]))
            except Exception:
                pass
            self._stop.wait(self.interval)

    def __enter__(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._poll, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else ["id"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_matrix(rows: list[dict], output_dir: Path = RESULTS, only: str | None = None) -> None:
    engine = RAGEngine()
    matrix = [m for m in MATRIX if m[0] == only] if only else MATRIX
    if only and not matrix:
        raise SystemExit(f"no matrix row labeled {only!r} (options: {[m[0] for m in MATRIX]})")
    for label, mode, provider, model in matrix:
        if provider == "local":
            config.OLLAMA_MODEL = model
        else:
            config.DOTBLUE_MODEL = model
        print(f"[matrix] {label}: mode={mode} provider={provider} model={model}")
        vram = VRAMSampler() if provider == "local" else None
        out_rows = []
        with (vram if vram else contextlib.nullcontext()):
            for row in rows:
                session_id = f"eval-{label}-{row['id']}"  # unique per row -> history always empty, no spurious rewrite
                t0 = time.time()
                try:
                    answer, debug = engine.answer_with_debug(row["question"], session_id=session_id, provider=provider, mode=mode)
                    error = None
                except Exception as exc:
                    answer, debug, error = "", {}, repr(exc)
                elapsed = time.time() - t0
                latency = debug.get("latency", {})
                out_rows.append({
                    "id": row["id"], "category": row["category"], "config": label,
                    "mode": mode, "provider": provider, "model": model,
                    "zone": debug.get("zone"), "provider_fallback": debug.get("provider_fallback"),
                    "latency_total": latency.get("total", elapsed), "latency_generate": latency.get("generate"),
                    "answer": answer, "error": error,
                    **citation_metrics(answer, row.get("gold_sections", [])),
                })
        if vram:
            for r in out_rows:
                r["peak_vram_mib"] = vram.peak
        write_csv(output_dir / f"generation_{label}.csv", out_rows)
    print("[matrix] done")


def run_num_ctx_sweep(rows: list[dict], output_dir: Path = RESULTS, sample: int = 10) -> None:
    engine = RAGEngine()
    sample_rows = rows[:sample]
    out_rows = []
    for model in NUM_CTX_MODELS:
        for num_ctx in NUM_CTX_VALUES:
            print(f"[num_ctx] model={model} num_ctx={num_ctx}")
            client = OllamaClient(model=model)
            with VRAMSampler() as vram:
                for row in sample_rows:
                    hits, _score, _route, _paths = engine.retrieve_and_rerank_hybrid(row["question"], "hybrid")
                    sections = engine.expand(hits)
                    graph = engine.graph_retriever.graph if engine.graph_retriever is not None else {"nodes": [], "edges": []}
                    cards = build_section_cards(sections, graph, config.CONTEXT_BUDGET_CHARS["local"])
                    context_text = "\n\n".join(cards)
                    prompt = f'{generator.SYSTEM_PROMPT}\n\nข้อมูลอ้างอิง:\n{context_text}\n\nคำถาม: {row["question"]}'
                    try:
                        text, usage = client.chat([{"role": "user", "content": prompt}], num_ctx=num_ctx)
                        error = None
                    except Exception as exc:
                        text, usage, error = "", {}, repr(exc)
                    completion = (usage or {}).get("completion_tokens") or 0
                    latency = (usage or {}).get("latency_s") or 0
                    out_rows.append({
                        "id": row["id"], "model": model, "num_ctx": num_ctx,
                        "latency_s": latency, "completion_tokens": completion,
                        "tokens_per_s": completion / latency if latency else None,
                        "error": error,
                    })
            for r in out_rows[-len(sample_rows):]:
                r["peak_vram_mib"] = vram.peak
    write_csv(output_dir / "generation_num_ctx_sweep.csv", out_rows)
    print("[num_ctx] done")


NO_RAG_SYSTEM = """คุณคือผู้ช่วยตอบคำถามเกี่ยวกับกฎหมายแรงงานไทย ตอบเป็นภาษาไทย กระชับ ตรงประเด็น จากความรู้ของคุณเองเท่านั้น (ไม่มีข้อมูลอ้างอิงให้ในครั้งนี้)
ถ้าไม่แน่ใจเลขมาตราที่แน่นอน ให้ตอบเนื้อหาที่รู้แต่ระบุว่าไม่แน่ใจเลขมาตรา ห้ามปฏิเสธที่จะตอบ"""


def _strip_think(text: str) -> str:
    # Same defensive strip as generator.py: a thinking model may ignore
    # enable_thinking=False and wrap reasoning in <think> instead of a
    # separate field — without a strict system prompt like generator.py's
    # SYSTEM_PROMPT, some models also burn the entire num_predict budget on
    # hidden reasoning with zero visible content left; num_predict=800 here
    # (vs the 512 default) is a safety margin for that, found via a 1-sample
    # smoke test that came back completely empty at the 512 default.
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip() if "<think>" in text else text


def run_no_rag(rows: list[dict], output_dir: Path = RESULTS, provider: str = "api", model: str | None = None) -> None:
    llm = get_llm(provider=provider, model=model or config.DOTBLUE_MODEL)
    out_rows = []
    for row in rows:
        messages = [{"role": "system", "content": NO_RAG_SYSTEM}, {"role": "user", "content": row["question"]}]
        try:
            text, usage = llm.chat(messages, num_predict=2000)
            text = _strip_think(text)
            error = None
        except Exception as exc:
            text, usage, error = "", {}, repr(exc)
        out_rows.append({
            "id": row["id"], "category": row["category"], "config": "no_rag",
            "latency_s": (usage or {}).get("latency_s"), "answer": text, "error": error,
            **citation_metrics(text, row.get("gold_sections", [])),
        })
    write_csv(output_dir / "generation_no_rag.csv", out_rows)
    print("[no_rag] done")


def run_full_context(rows: list[dict], output_dir: Path = RESULTS, provider: str = "api", model: str | None = None) -> None:
    full_text = FULL_TEXT_PATH.read_text(encoding="utf-8")
    llm = get_llm(provider=provider, model=model or config.DOTBLUE_MODEL)
    out_rows = []
    for row in rows:
        prompt = f'{generator.SYSTEM_PROMPT}\n\nข้อมูลอ้างอิง (พ.ร.บ.คุ้มครองแรงงาน พ.ศ. 2541 ฉบับเต็ม):\n{full_text}\n\nคำถาม: {row["question"]}'
        try:
            text, usage = llm.chat([{"role": "user", "content": prompt}], num_predict=4000)
            text = _strip_think(text)
            error = None
        except Exception as exc:
            text, usage, error = "", {}, repr(exc)
        answer, _cited = generator.parse_citation(text, []) if text else (text, [])
        out_rows.append({
            "id": row["id"], "category": row["category"], "config": "full_context",
            "latency_s": (usage or {}).get("latency_s"), "answer": answer, "error": error,
            **citation_metrics(answer, row.get("gold_sections", [])),
        })
    write_csv(output_dir / "generation_full_context.csv", out_rows)
    print("[full_context] done")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--matrix", action="store_true")
    parser.add_argument("--num-ctx-sweep", action="store_true")
    parser.add_argument("--no-rag", action="store_true")
    parser.add_argument("--full-context", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--sample", type=int, default=None, help="limit testset rows, for a quick smoke run")
    parser.add_argument("--label", default=None, help="run only this one MATRIX row (see MATRIX for valid labels) -- fresh process per label keeps peak RAM down on small machines")
    args = parser.parse_args()
    if not any([args.matrix, args.num_ctx_sweep, args.no_rag, args.full_context, args.all]):
        parser.error("pick at least one of --matrix/--num-ctx-sweep/--no-rag/--full-context/--all")

    rows = load_rows(args.sample)
    if args.all or args.matrix:
        run_matrix(rows, only=args.label)
    if args.all or args.num_ctx_sweep:
        run_num_ctx_sweep(rows)
    if args.all or args.no_rag:
        run_no_rag(rows)
    if args.all or args.full_context:
        run_full_context(rows)


if __name__ == "__main__":
    main()
