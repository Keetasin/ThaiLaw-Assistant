"""Cross-encoder rerank — CPU only (keeps VRAM headroom for the local LLM).

bge-reranker-v2-m3 must give 0-1 scores (sigmoid), not raw logits, or every
TAU_* threshold in config.py is meaningless (copied from
aj-krit/Project2/core/reranker.py — see check_score_range()).
"""
import numpy as np
from sentence_transformers import CrossEncoder

from src import config

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = CrossEncoder(config.RERANK_MODEL, device="cpu", max_length=512)
    return _model


def passage_text(c):
    # Public so build_vector.py's embed text uses this exact same shape —
    # a wrong-topic chunk can outscore the right one if the reranker only
    # sees raw body text without its chapter/section label for context, and
    # a format that drifts between embed-time and rerank-time silently hurts
    # both without ever raising an error.
    # c["chapter"] is None for sections before หมวด 1 starts (บททั่วไป-ish
    # definitions/scope sections 1-6) — omit the label rather than print "None".
    label = f'{c["chapter"]} — มาตรา {c["section_no"]}' if c["chapter"] else f'มาตรา {c["section_no"]}'
    return f'{label}\n{c["text"]}'


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
