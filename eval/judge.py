"""LLM-as-judge (PLAN.md §8.2/§8.3): scores every generation-eval answer on
Correctness/Faithfulness/Citation accuracy/Thai clarity (1-5) plus key-point
coverage and out-of-scope refusal correctness, using DOTBLUE_JUDGE_MODEL
(qwen3.6-plus). Also supports building a human-vs-judge validation sample
and computing Cohen's kappa / Spearman once the team fills in human scores.
"""
from __future__ import annotations

import argparse
import time
import csv
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config
from src.llm.client import DotBlueClient, get_llm

RESULTS = ROOT / "eval" / "results"
TESTSET = ROOT / "eval" / "testset.jsonl"
JSON_RE = re.compile(r"\{.*\}", re.S)

JUDGE_PROMPT = """คุณเป็นกรรมการตรวจคำตอบของระบบผู้ช่วยกฎหมายแรงงานไทย ให้คะแนนคำตอบต่อไปนี้อย่างเข้มงวดและยุติธรรม

คำถาม: {question}
หมวดคำถาม: {category}
ประเด็นสำคัญที่คำตอบที่ดีควรครอบคลุม (gold key points): {key_points}
คำตอบของระบบ: {answer}

ให้คะแนนแต่ละด้าน 1-5 (5=ดีที่สุด) แล้วตอบเป็น JSON เท่านั้น ไม่ต้องอธิบายเพิ่ม รูปแบบตายตัว:
{{"correctness": <1-5>, "faithfulness": <1-5>, "citation_accuracy": <1-5>, "thai_clarity": <1-5>, "key_point_coverage": <0.0-1.0>, "oos_handled_correctly": <true/false/null>}}

หมายเหตุ:
- faithfulness: ทุกข้อความในคำตอบต้องสืบสาวไปยังกฎหมายจริงได้ ถ้าดูเหมือนแต่งเอง ให้คะแนนต่ำ
- citation_accuracy: เลขมาตราที่อ้างต้องสมเหตุสมผลกับคำถาม ถ้าไม่มีการอ้างอิงเลขมาตราทั้งที่ควรมี ให้คะแนนต่ำ
- key_point_coverage: สัดส่วนของ gold key points ที่คำตอบครอบคลุมจริง (0.0 ถึง 1.0)
- oos_handled_correctly: เกณฑ์นี้ใช้เฉพาะคำถาม out-of-scope (ระบบไม่ได้ออกแบบให้ปฏิเสธคำถามเหล่านี้อีกต่อไป แต่ให้ตอบด้วยความรู้ทั่วไปของ AI พร้อมป้ายกำกับชัดเจน) — true ถ้าคำตอบ (1) มีข้อความระบุชัดว่าเป็นความรู้ทั่วไปของ AI ไม่ใช่จากตัวบทกฎหมายที่ระบบมี และ (2) ไม่มีการอ้างเลขมาตรากฎหมายแรงงานปลอมๆ ราวกับเป็นข้อมูลที่ตรวจสอบแล้ว; false ถ้าขาดป้ายกำกับ หรือมีการอ้างมาตราแบบไม่มีป้ายเตือน; null ถ้าไม่ใช่คำถาม out-of-scope"""


def load_testset_index() -> dict[str, dict]:
    rows = [json.loads(line) for line in TESTSET.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {row["id"]: row for row in rows}


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict]) -> None:
    # judge_scores.csv merges rows from source files with different schemas
    # (matrix rows have mode/model/zone/latency_total; no_rag/full_context
    # have latency_s instead) -- fieldnames from just rows[0] crashes
    # DictWriter the first time a later row has a key row[0] didn't, so union
    # every row's keys instead, in first-seen order.
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(dict.fromkeys(key for row in rows for key in row)) if rows else ["id"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def score_answer(question: str, answer: str, category: str, key_points: list[str]) -> dict:
    # qwen3.6-plus (the judge model) burns a highly variable number of hidden
    # reasoning tokens before emitting the JSON -- too small a num_predict
    # (200, then 1500) came back completely empty on most real rows (budget
    # exhausted mid-thought), but simply raising it further hits
    # DotBlueClient's production 30s timeout (built for fast RAG-answer
    # calls, not a slow reasoning judge) before the stream finishes. Needs
    # its own client with a longer timeout, not the shared production one.
    llm = DotBlueClient(model=config.DOTBLUE_JUDGE_MODEL, timeout=90.0)
    prompt = JUDGE_PROMPT.format(question=question, category=category, key_points="; ".join(key_points), answer=answer or "(ไม่มีคำตอบ)")
    last_text = ""
    # dotBlue's SSE stream occasionally comes back with chunks dropped/spliced
    # mid-field (observed: "faithfulness": _point_coverage": 0.0 -- two valid
    # fields fused together, not a length truncation) -- transient, so retry
    # the whole call a few times before giving up rather than losing the row.
    for _attempt in range(3):
        text, _usage = llm.chat([{"role": "user", "content": prompt}], temperature=0.0, num_predict=4500)
        if "<think>" in text:
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
        last_text = text
        match = JSON_RE.search(text)
        if match:
            try:
                parsed = json.loads(match.group(0))
                parsed["judge_parse_error"] = None
                return parsed
            except json.JSONDecodeError:
                continue
    return {"correctness": None, "faithfulness": None, "citation_accuracy": None, "thai_clarity": None, "key_point_coverage": None, "oos_handled_correctly": None, "judge_parse_error": last_text[:200]}


def generation_csvs(results_dir: Path = RESULTS) -> list[Path]:
    skip = {"retrieval", "tuning", "num_ctx_sweep", "judge"}
    return sorted(p for p in results_dir.glob("generation_*.csv") if not any(s in p.stem for s in skip))


def run_judge(results_dir: Path = RESULTS, checkpoint_every: int = 10, skip_configs: set[str] | None = None,
              only_config: str | None = None, out_path: Path | None = None, shard: tuple[int, int] | None = None) -> Path:
    # A single transient API error (a real dotBlue 500 mid-run once burned ~430
    # already-paid-for judge calls with nothing saved, since this used to write
    # only once at the very end) must never lose already-scored rows again --
    # catch per-row and checkpoint the CSV every `checkpoint_every` rows.
    # `only_config` + `out_path` let several configs run as separate parallel
    # processes (each ~45s/call, sequential-in-one-process was ~4.4h for the
    # full matrix) writing to their own file instead of racing on one CSV --
    # merge_judge_outputs() below combines them afterward.
    testset = load_testset_index()
    out_path = out_path or (results_dir / "judge_scores.csv")
    out_rows = []
    for path in generation_csvs(results_dir):
        rows = read_csv(path)
        row_config = rows[0].get("config") if rows else None
        if skip_configs and row_config in skip_configs:
            print(f"[judge] skipping {path.name} (config={row_config!r})")
            continue
        if only_config and row_config != only_config:
            continue
        if shard:  # rows are independent: shard i of n takes every n-th row so n processes split the API-bound wait
            rows = [r for idx, r in enumerate(rows) if idx % shard[1] == shard[0]]
        t_start = time.time()
        for i, row in enumerate(rows, 1):
            gold = testset.get(row["id"], {})
            try:
                scores = score_answer(row["question"] if "question" in row else gold.get("question", ""), row.get("answer", ""), row.get("category", gold.get("category", "")), gold.get("key_points", []))
            except Exception as exc:
                scores = {"correctness": None, "faithfulness": None, "citation_accuracy": None, "thai_clarity": None, "key_point_coverage": None, "oos_handled_correctly": None, "judge_parse_error": f"judge call failed: {exc!r}"}
            out_rows.append({**row, "source_file": path.name, **scores})
            print(f"[judge] {path.stem} {row['id']}: correctness={scores.get('correctness')}")
            el = time.time() - t_start
            print(f"[progress] judge {path.stem} {i}/{len(rows)} ({i / len(rows):.0%}) elapsed {el / 60:.1f} min, ETA ~{el / i * (len(rows) - i) / 60:.1f} min", flush=True)
            if len(out_rows) % checkpoint_every == 0:
                write_csv(out_path, out_rows)
    write_csv(out_path, out_rows)
    print(f"[judge] wrote {len(out_rows)} scored rows -> {out_path}")
    return out_path


def merge_judge_outputs(results_dir: Path = RESULTS, pattern: str = "judge_scores_*.csv") -> Path:
    all_rows = []
    for path in sorted(results_dir.glob(pattern)):
        all_rows.extend(read_csv(path))
    out_path = results_dir / "judge_scores.csv"
    write_csv(out_path, all_rows)
    print(f"[judge] merged {len(all_rows)} rows from {pattern} -> {out_path}")
    return out_path


def build_validation_sample(n: int = 20, results_dir: Path = RESULTS, seed: int = 7) -> Path:
    scored_path = results_dir / "judge_scores.csv"
    rows = read_csv(scored_path)
    if not rows:
        raise SystemExit("run --score first (no judge_scores.csv rows)")
    testset = load_testset_index()
    sample = random.Random(seed).sample(rows, min(n, len(rows)))
    for row in sample:
        gold = testset.get(row["id"], {})
        # a human scoring this needs the actual question + gold key points to
        # judge against -- generation rows only carry the answer, not the
        # question (joined from testset.jsonl at judge time, not stored)
        row["question"] = gold.get("question", "")
        row["gold_key_points"] = "; ".join(gold.get("key_points", []))
        row["human_correctness"] = ""
        row["human_faithfulness"] = ""
    path = results_dir / "judge_validation_sample.csv"
    write_csv(path, sample)
    print(f"[judge] wrote {len(sample)}-row validation sample -> {path}")
    print("Fill human_correctness/human_faithfulness (1-5) by hand, then run --kappa")
    return path


def compute_agreement(results_dir: Path = RESULTS) -> dict:
    from sklearn.metrics import cohen_kappa_score
    from scipy.stats import spearmanr

    path = results_dir / "judge_validation_sample.csv"
    rows = [r for r in read_csv(path) if r.get("human_correctness", "").strip()]
    if len(rows) < 2:
        raise SystemExit(f"need >=2 human-scored rows in {path}, found {len(rows)}")
    judge_c = [round(float(r["correctness"])) for r in rows]
    human_c = [round(float(r["human_correctness"])) for r in rows]
    judge_f = [round(float(r["faithfulness"])) for r in rows]
    human_f = [round(float(r["human_faithfulness"])) for r in rows]
    result = {
        "n": len(rows),
        "correctness_kappa": cohen_kappa_score(judge_c, human_c),
        "correctness_spearman": spearmanr(judge_c, human_c).statistic,
        "faithfulness_kappa": cohen_kappa_score(judge_f, human_f),
        "faithfulness_spearman": spearmanr(judge_f, human_f).statistic,
    }
    out_path = results_dir / "judge_validation_result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"saved -> {out_path}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--score", action="store_true", help="judge every row in eval/results/generation_*.csv")
    parser.add_argument("--skip-config", default="", help="comma-separated 'config' column values to skip (e.g. D_api_qwen-flash,G_api_qwen-flash)")
    parser.add_argument("--only-config", default=None, help="judge only this one 'config' value -- run several as parallel processes, each with --output judge_scores_<name>.csv, then --merge")
    parser.add_argument("--output", type=Path, default=None, help="output CSV path (with --only-config, for parallel runs)")
    parser.add_argument("--shard", default=None, help="i/n: judge only rows i, i+n, ... (run n processes in parallel with different --output, then concatenate)")
    parser.add_argument("--merge", action="store_true", help="merge eval/results/judge_scores_*.csv (from parallel --only-config runs) into judge_scores.csv")
    parser.add_argument("--validate", type=int, default=0, metavar="N", help="write an N-row human-vs-judge validation sample")
    parser.add_argument("--kappa", action="store_true", help="compute Cohen's kappa / Spearman from a filled validation sample")
    args = parser.parse_args()
    if not (args.score or args.validate or args.kappa or args.merge):
        parser.error("pick at least one of --score/--validate N/--kappa/--merge")
    if args.score:
        skip = {c.strip() for c in args.skip_config.split(",") if c.strip()}
        shard = tuple(int(x) for x in args.shard.split("/")) if args.shard else None
        run_judge(skip_configs=skip, only_config=args.only_config, out_path=args.output, shard=shard)
    if args.merge:
        merge_judge_outputs()
    if args.validate:
        build_validation_sample(args.validate)
    if args.kappa:
        compute_agreement()


if __name__ == "__main__":
    main()
