"""Re-score only the rows a judge run left unscored (judge_parse_error set / empty correctness),
in place, in every eval/results/judge_scores_*.csv, then re-merge judge_scores.csv."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from eval.judge import RESULTS, load_testset_index, merge_judge_outputs, read_csv, score_answer, write_csv  # noqa: E402


def main():
    testset = load_testset_index()
    for path in sorted(RESULTS.glob("judge_scores_*.csv")):
        rows = read_csv(path)
        todo = [r for r in rows if not (r.get("correctness") or "").strip()]
        if not todo:
            continue
        print(f"[retry] {path.name}: {len(todo)} unscored rows", flush=True)
        for r in todo:
            gold = testset.get(r["id"], {})
            for _ in range(3):
                s = score_answer(gold.get("question", ""), r.get("answer", ""), r.get("category", gold.get("category", "")), gold.get("key_points", []))
                if s.get("correctness") is not None:
                    break
            for k, v in s.items():
                r[k] = "" if v is None else v
            print(f"[retry] {r['id']} -> correctness={r.get('correctness')!r}", flush=True)
        write_csv(path, rows)
    merge_judge_outputs()


if __name__ == "__main__":
    main()
