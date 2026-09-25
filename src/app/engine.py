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
import logging
import re
import threading
import time

from src import config
from src.app.generator import generate, generate_from_cards
from src.app.tracing import log_trace
from src.llm.client import get_llm
from src.retrieval.context import build_section_cards
from src.retrieval.fusion import graph_seeded_expand, hybrid_search
from src.retrieval.graph import GraphRetriever, load_aliases
from src.retrieval.reranker import rerank
from src.retrieval.retriever import Retriever, dynamic_k
from src.retrieval.router import RouteDecision, classify_query

log = logging.getLogger(__name__)

GRAPH_ONLY_ROUTE = RouteDecision(query_type="lookup", alpha_dense=0.0, alpha_bm25=0.0, alpha_graph=1.0)

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


def _load_graph_retriever():
    # Content retrieval reads the offline data/graph.json snapshot, not a
    # live Neo4j query — Neo4j is only used for chat_history.py's
    # conversation log. This means "Neo4j ล่ม" (PLAN.md §7) can't affect
    # graph/hybrid retrieval at all; the only failure mode left is the
    # snapshot file itself being missing/corrupt, which this degrades from
    # by falling back to dense-only (fusion.hybrid_search already treats
    # graph_retriever=None as "no graph leg", not an error).
    try:
        aliases = load_aliases(config.TOPICS_PATH)
        return GraphRetriever.from_json(config.GRAPH_PATH, aliases)
    except (OSError, ValueError) as e:
        log.warning("graph retriever unavailable (%s) — hybrid/graph modes degrade to dense-only", e)
        return None


class RAGEngine:
    def __init__(self):
        self.retriever = Retriever()
        self.graph_retriever = _load_graph_retriever()
        import json
        with open(config.SECTIONS_PATH, encoding="utf-8") as f:
            self.sections = json.load(f)
        self.history = {}
        self._history_lock = threading.Lock()

    def _get_history(self, session_id):
        # app_line.py dispatches every message on its own daemon thread, so
        # two messages from the same user can call this concurrently —
        # return a copy under lock rather than the live list, so the rest of
        # this request's processing never touches a list another thread is
        # mutating.
        with self._history_lock:
            return list(self.history.setdefault(session_id, []))

    def _append_history(self, session_id, q, out):
        with self._history_lock:
            hist = self.history.setdefault(session_id, [])
            hist.append((q, out))
            del hist[:-3]

    def clear_history(self, session_id):
        """Backs the /reset command (PLAN.md §7) — engine-side in-memory
        history only; app_line.py separately clears the Neo4j chat_history
        log, which is a distinct store (see engine.py's module docstring)."""
        with self._history_lock:
            self.history.pop(session_id, None)

    def retrieve_and_rerank(self, q, timing=None):
        """Dense-only mode (PLAN.md's original Day 2 path) — unchanged
        behavior, still the mode="dense" code path."""
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

    def retrieve_and_rerank_hybrid(self, q, mode, timing=None):
        """mode="hybrid": router-classified weighted RRF across dense/bm25/
        graph (src.retrieval.fusion.hybrid_search) + graph-seeded expansion.
        mode="graph": same pipeline forced to an all-graph route weight, so
        it shares the exact same degrade-to-empty-hits behavior when the
        graph snapshot is unavailable, instead of a separate code path."""
        route = classify_query(q) if mode == "hybrid" else GRAPH_ONLY_ROUTE
        rerank_k, fuse_k = dynamic_k(q)

        t0 = time.time()
        cands = hybrid_search(self.retriever, self.graph_retriever, q, route, fuse_k=fuse_k)
        t1 = time.time()
        if self.graph_retriever is not None:
            cands, graph_paths = graph_seeded_expand(cands, self.graph_retriever.graph, self.retriever)
        else:
            graph_paths = []
        t2 = time.time()
        hits, score = rerank(q, cands, k=rerank_k)
        t3 = time.time()
        if timing is not None:
            timing["retrieve"] = timing.get("retrieve", 0.0) + (t1 - t0)
            timing["graph_expand"] = timing.get("graph_expand", 0.0) + (t2 - t1)
            timing["rerank"] = timing.get("rerank", 0.0) + (t3 - t2)
        return hits, score, route, graph_paths

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

    def _generate(self, hits, q_used, provider, mode):
        sections = self.expand(hits)
        if mode == "dense":
            return generate(sections, q_used, provider=provider)
        budget = config.CONTEXT_BUDGET_CHARS["api" if provider == "api" else "local"]
        graph = self.graph_retriever.graph if self.graph_retriever is not None else {"nodes": [], "edges": []}
        cards = build_section_cards(sections, graph, budget)
        return generate_from_cards(cards, sections, q_used, provider=provider)

    def _generate_with_fallback(self, hits, q_used, provider, mode):
        """PLAN.md §7's "LLM ล่ม -> fallback chain API -> Local (และ Local ->
        API ถ้า Ollama ล่ม)": one retry against the other provider, at this
        call site (not inside src/llm/client.py) so the fallback stays
        visible in the timing/debug capture below. Returns
        (answer, provider_actually_used)."""
        try:
            return self._generate(hits, q_used, provider, mode), provider
        except Exception:
            fallback_provider = "local" if provider == "api" else "api"
            log.warning("generate() failed on provider=%s, falling back to %s", provider, fallback_provider, exc_info=True)
            return self._generate(hits, q_used, fallback_provider, mode), fallback_provider

    def answer(self, q, session_id="default", provider="local", mode="hybrid"):
        text, _debug = self.answer_with_debug(q, session_id, provider=provider, mode=mode)
        return text

    def answer_with_debug(self, q, session_id="default", provider="local", mode="hybrid"):
        q = clean_query(q)
        hist = self._get_history(session_id)
        t_start = time.time()
        timing = {}

        q_std = rewrite_with_history(q, hist, provider=provider) if needs_rewrite(q, hist) else q

        route, graph_paths = None, []
        if mode == "dense":
            hits, score = self.retrieve_and_rerank(q_std, timing)
        else:
            hits, score, route, graph_paths = self.retrieve_and_rerank_hybrid(q_std, mode, timing)
        q_used = q_std
        zone = "answer"
        provider_used = provider

        t_gen0 = None
        if score < config.TAU_REJECT:
            out = "ไม่พบข้อมูลนี้ในตัวบทกฎหมายที่มี กรุณาปรึกษาทนายความหรือหน่วยงานที่เกี่ยวข้อง"
            zone = "reject"
        elif score < config.TAU_ANSWER:
            zone = "borderline"
            q2 = llm_normalize(q_std, provider=provider)
            if q2 != q_std:
                if mode == "dense":
                    hits2, score2 = self.retrieve_and_rerank(q2, timing)
                    route2, graph_paths2 = None, []
                else:
                    hits2, score2, route2, graph_paths2 = self.retrieve_and_rerank_hybrid(q2, mode, timing)
                if score2 > score:
                    hits, score, q_used, route, graph_paths = hits2, score2, q2, route2, graph_paths2
            if score < config.TAU_ANSWER:
                out = "ไม่พบข้อมูลนี้ในตัวบทกฎหมายที่มี กรุณาปรึกษาทนายความหรือหน่วยงานที่เกี่ยวข้อง"
                zone = "reject-after-retry"
            else:
                t_gen0 = time.time()
                out, provider_used = self._generate_with_fallback(hits, q_used, provider, mode)
        else:
            t_gen0 = time.time()
            out, provider_used = self._generate_with_fallback(hits, q_used, provider, mode)
        timing["generate"] = (time.time() - t_gen0) if t_gen0 is not None else 0.0
        timing["total"] = time.time() - t_start

        self._append_history(session_id, q, out)

        debug = {
            "mode": mode,
            "q_rewritten": q_std if q_std != q else None,
            "q_used": q_used,
            "zone": zone,
            "rerank_score": score,
            "hits": hits,
            "route": route.model_dump() if route is not None else None,
            "graph_paths": graph_paths,
            "latency": timing,
            "provider": provider_used,
            "provider_fallback": provider_used != provider,
        }
        try:
            log_trace(
                session=session_id, q=q, q_used=q_used, zone=zone,
                rerank_score=score, hits=hits, latency=timing, answer=out, provider=provider_used,
            )
        except Exception:
            pass  # tracing must never break answer()
        return out, debug
