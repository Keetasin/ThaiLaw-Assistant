"""RAGEngine — orchestrates retrieval, guard, generation.

STAGED FOR DAY 2, NOT USABLE YET: Retriever() below opens a Chroma
collection + reads data/bm25.pkl + data/chunks.jsonl, none of which exist
until A's Day-2 ingest/index step finishes. Do not instantiate RAGEngine()
from echo_app.py or anywhere else today — that's why Day 1's app is a
separate minimal echo_app.py instead. Copied from
aj-krit/Project2/core/rag.py.

Zone logic (rerank score):
    score >= TAU_ANSWER              -> answer
    TAU_REJECT <= score < TAU_ANSWER -> normalize typo, retry once, then decide
    score <  TAU_REJECT              -> refuse

Multi-turn rewrite happens *before* retrieval; typo normalize happens
*after* the first retrieval (it needs the score to know whether it's
needed).
"""
import re
import time

from src import config
from src.app.generator import generate
from src.app.tracing import log_trace
from src.llm.client import get_llm
from src.retrieval.reranker import rerank
from src.retrieval.retriever import Retriever, dynamic_k

PRONOUN_MARKERS = ("แล้ว", "ด้วย", "นั้น", "อันนี้", "ที่ว่า", "มัน")

# Thai mobile keyboards insert U+200B zero-width space around word
# boundaries as part of predictive-text/IME behavior. Left in, these
# measurably degrade dense/BM25 retrieval scores and can corrupt later
# turns via the rewrite-with-history LLM call. Strip at the single entry
# point so every downstream step sees clean text.
_INVISIBLE_CHARS = re.compile("[​‌‍‎‏﻿]")


def clean_query(q):
    return _INVISIBLE_CHARS.sub("", q).strip()


NORMALIZE_PROMPT = """แก้เฉพาะคำสะกดผิดในประโยคนี้ ตอบกลับเป็นประโยคเดียว ไม่ต้องอธิบาย
ห้ามแก้: เลขมาตรา, ตัวย่อ, ชื่อหน่วยงาน
ถ้าไม่มีคำผิด ให้ตอบประโยคเดิมกลับมา

ประโยค: {q}"""

REWRITE_PROMPT = """ประวัติการสนทนา:
{history}

คำถามล่าสุด: {q}

เขียนคำถามล่าสุดใหม่ให้เป็นประโยคสมบูรณ์ ไม่ต้องพึ่งบริบทก่อนหน้า
ห้ามขึ้นต้นประโยคด้วยคำเชื่อม/สรรพนามที่อ้างอิงบทสนทนาก่อนหน้าโดยเด็ดขาด เช่น "แล้ว", "ด้วย",
"นั้น", "อันนี้" — ต้องเป็นประโยคคำถามที่อ่านเข้าใจได้เองโดยไม่ต้องมีบริบทก่อนหน้าเลย
ตอบกลับเป็นคำถามเดียว ไม่ต้องอธิบาย"""

_LEADING_PRONOUN = re.compile(r"^(?:" + "|".join(re.escape(m) for m in PRONOUN_MARKERS) + r")\s*")


def _strip_leading_pronoun(q):
    return _LEADING_PRONOUN.sub("", q, count=1).strip() or q


def _llm_short(prompt, provider="local"):
    llm = get_llm(provider=provider)
    text, _usage = llm.chat([{"role": "user", "content": prompt}], temperature=0.0, num_predict=100)
    return text.strip()


def llm_normalize(q, provider="local"):
    out = _llm_short(NORMALIZE_PROMPT.format(q=q), provider=provider)
    return out if out else q


def needs_rewrite(q, hist):
    if not hist:
        return False
    return len(q) < 20 or any(m in q for m in PRONOUN_MARKERS)


def rewrite_with_history(q, hist, provider="local"):
    history_text = "\n".join(f"Q: {hq}\nA: {ha[:100]}" for hq, ha in hist[-3:])
    out = _llm_short(REWRITE_PROMPT.format(history=history_text, q=q), provider=provider)
    return _strip_leading_pronoun(out) if out else q


class RAGEngine:
    def __init__(self):
        self.retriever = Retriever()
        import json
        with open(config.SECTIONS_PATH, encoding="utf-8") as f:
            self.sections = json.load(f)
        self.history = {}

    def retrieve_and_rerank(self, q, timing=None):
        rerank_k, fuse_k = dynamic_k(q)
        t0 = time.time()
        cands, _ = self.retriever.search(q, fuse_k=fuse_k)
        t1 = time.time()
        hits, score = rerank(q, cands, k=rerank_k)
        t2 = time.time()
        if timing is not None:
            timing["retrieve"] = timing.get("retrieve", 0.0) + (t1 - t0)
            timing["rerank"] = timing.get("rerank", 0.0) + (t2 - t1)
        return hits, score

    def expand(self, hits, budget_chars=config.EXPAND_BUDGET_CHARS):
        out, seen, used = [], set(), 0
        for h in hits:
            key = h["section_key"]
            if key in seen:
                continue
            sec = self.sections.get(key)
            if sec is None:
                continue
            if out and used + len(sec["text"]) > budget_chars:
                continue
            seen.add(key)
            used += len(sec["text"])
            out.append(sec)
        return out

    def answer(self, q, session_id="default", provider="local"):
        text, _debug = self.answer_with_debug(q, session_id, provider=provider)
        return text

    def answer_with_debug(self, q, session_id="default", provider="local"):
        q = clean_query(q)
        hist = self.history.setdefault(session_id, [])
        t_start = time.time()
        timing = {}

        q_std = rewrite_with_history(q, hist, provider=provider) if needs_rewrite(q, hist) else q

        hits, score = self.retrieve_and_rerank(q_std, timing)
        q_used = q_std
        zone = "answer"

        t_gen0 = None
        if score < config.TAU_REJECT:
            out = "ไม่พบข้อมูลนี้ในตัวบทกฎหมายที่มี กรุณาปรึกษาทนายความหรือหน่วยงานที่เกี่ยวข้อง"
            zone = "reject"
        elif score < config.TAU_ANSWER:
            zone = "borderline"
            q2 = llm_normalize(q_std, provider=provider)
            if q2 != q_std:
                hits2, score2 = self.retrieve_and_rerank(q2, timing)
                if score2 > score:
                    hits, score, q_used = hits2, score2, q2
            if score < config.TAU_ANSWER:
                out = "ไม่พบข้อมูลนี้ในตัวบทกฎหมายที่มี กรุณาปรึกษาทนายความหรือหน่วยงานที่เกี่ยวข้อง"
                zone = "reject-after-retry"
            else:
                t_gen0 = time.time()
                out = generate(self.expand(hits), q_used, provider=provider)
        else:
            t_gen0 = time.time()
            out = generate(self.expand(hits), q_used, provider=provider)
        timing["generate"] = (time.time() - t_gen0) if t_gen0 is not None else 0.0
        timing["total"] = time.time() - t_start

        hist.append((q, out))
        del hist[:-3]

        debug = {
            "q_rewritten": q_std if q_std != q else None,
            "q_used": q_used,
            "zone": zone,
            "rerank_score": score,
            "hits": hits,
            "latency": timing,
        }
        try:
            log_trace(
                session=session_id, q=q, q_used=q_used, zone=zone,
                rerank_score=score, hits=hits, latency=timing, answer=out, provider=provider,
            )
        except Exception:
            pass  # tracing must never break answer()
        return out, debug
