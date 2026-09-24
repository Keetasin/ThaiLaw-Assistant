"""Per-query JSONL trace log — self-hosted, no external service. A line per
query answers "where did the latency actually go" without guessing by hand.
Copied from aj-krit/Project2/core/tracing.py.

Must never break answer(): a disk-full or permission error here is not
worth failing a user's request over, so every write is best-effort.
"""
import json
import os
import time

from src import config


def log_trace(*, session, q, q_used, zone, rerank_score, hits, latency, answer, provider=None):
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "session": session,
        "q": q,
        "q_used": q_used,
        "zone": zone,
        "rerank_score": rerank_score,
        "provider": provider,
        "hits": [
            {"id": h.get("chunk_id", h.get("id")), "section_no": h.get("section_no"), "heading": h.get("heading")}
            for h in hits
        ],
        "latency": latency,
        "answer_len": len(answer),
    }
    try:
        os.makedirs(os.path.dirname(config.TRACE_PATH), exist_ok=True)
        with open(config.TRACE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass  # tracing is best-effort -- never break answer() over a log write
