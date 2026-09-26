"""Cross-encoder rerank — CPU only (keeps VRAM headroom for the local LLM).

bge-reranker-v2-m3 must give 0-1 scores (sigmoid), not raw logits, or every
TAU_* threshold in config.py is meaningless (copied from
aj-krit/Project2/core/reranker.py — see check_score_range()).

STAGED FOR DAY 2: not wired into anything yet, requires bge-reranker-v2-m3
downloaded (Day 2 ingest/index step).
"""
import numpy as np
import torch
from sentence_transformers import CrossEncoder

from src import config

_model = None


def _get_model():
    global _model
    if _model is None:
        requested = str(config.RERANK_DEVICE).lower()
        device = requested if requested == "cpu" or torch.cuda.is_available() else "cpu"
        _model = CrossEncoder(config.RERANK_MODEL, device=device, max_length=512)
    return _model


def passage_text(c):
    """Canonical chapter/section/body representation for all indexes."""
    chapter = c.get("chapter") or c.get("heading") or c.get("law_name") or ""
    section = c.get("section_no") or c.get("section") or ""
    body = c.get("text") or ""
    label = f"{chapter} — มาตรา {section}" if chapter else (f"มาตรา {section}" if section else "")
    return f"{label}\n{body}" if label else body


def rerank(query, candidates, k=config.RERANK_K):
    if not candidates:
        return [], 0.0
    ce = _get_model()
    pairs = [(query, passage_text(c)) for c in candidates]
    scores = ce.predict(pairs)
    order = np.argsort(-scores)[:k]
    hits = [candidates[i] for i in order]
    top_score = float(scores[order[0]])
    return hits, top_score


def check_score_range():
    """Confirm scores are 0-1 (sigmoid), not raw logits, before trusting any
    TAU_* threshold in config.py."""
    ce = _get_model()
    probe = [
        ("นายจ้างไม่จ่ายค่าล่วงเวลาต้องทำอย่างไร", "ลูกจ้างมีสิทธิได้รับค่าล่วงเวลาตามมาตรา 61"),
        ("นายจ้างไม่จ่ายค่าล่วงเวลาต้องทำอย่างไร", "ร้านอาหารแถวมหาวิทยาลัยมีหลายร้าน"),
    ]
    scores = ce.predict(probe)
    lo, hi = float(min(scores)), float(max(scores))
    ok = 0.0 <= lo and hi <= 1.0
    print(f"reranker score range: [{lo:.3f}, {hi:.3f}]  {'OK (0-1)' if ok else 'NOT 0-1 — fix activation_fn'}")
    return ok
