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
from collections import Counter

from src import config
from src.app.generator import generate, generate_from_cards, generate_general_knowledge
from src.app.tracing import log_trace
from src.llm.client import get_llm
from src.retrieval.context import build_section_cards
from src.retrieval.fusion import complete_penalty_partners, ensure_graph_hits_survive, graph_seeded_expand, hybrid_search
from src.retrieval.graph import GraphRetriever, infer_query_type, load_aliases
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


def _is_empty_body(answer):
    """generator.py always appends "\n\nที่มา: ..." after the real answer
    body -- if that's ALL there is (body blank before it), the LLM produced
    no visible content at all (see _generate_with_fallback's docstring)."""
    body = answer.split("\n\nที่มา:", 1)[0]
    return not body.strip()


def _is_degenerate_body(answer):
    """qwen3.6-flash occasionally loops the question back verbatim dozens
    of times (sometimes even leaking meta-commentary like "Wait, I'm
    generating garbage...") before eventually recovering into a real
    answer at the very end -- a non-empty wall of repeated text that
    _is_empty_body can't catch, but is just as useless to a real user.
    Detect gross repetition: several lines, and the single most-repeated
    non-blank line makes up more than a third of them."""
    body = answer.split("\n\nที่มา:", 1)[0]
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    if len(lines) < 6:
        return False
    _, count = Counter(lines).most_common(1)[0]
    return count / len(lines) > 0.3


def _is_bad_body(answer):
    return _is_empty_body(answer) or _is_degenerate_body(answer)


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
    # qwen3.6-flash (api) spends its completion budget on hidden reasoning
    # before emitting text -- at 100 tokens rewrite/normalize came back ''
    # and silently fell back to the raw query. Give api the full NUM_PREDICT
    # (same reason as generate(), see doc/report.md §4.0).
    num_predict = config.NUM_PREDICT if provider == "api" else 100
    text, _usage = llm.chat([{"role": "user", "content": prompt}], temperature=0.0, num_predict=num_predict)
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
        if infer_query_type(q) == "aggregation":
            # "ลาประเภทใดบ้าง"-style queries are often short (dynamic_k reads
            # that as "simple, few candidates needed") but actually need
            # many distinct sections across several topics -- the same
            # top_k=5 truncation bug fixed in GraphRetriever.search() for
            # the graph leg (doc/report.md §3.5) also applies here to the
            # final fused/reranked window, via router.classify_query's
            # separate "general" route type never covering this case.
            rerank_k, fuse_k = max(rerank_k, 10), max(fuse_k, 15)

        t0 = time.time()
        cands = hybrid_search(self.retriever, self.graph_retriever, q, route, fuse_k=fuse_k)
        t1 = time.time()
        if self.graph_retriever is not None:
            cands, graph_paths = graph_seeded_expand(cands, self.graph_retriever.graph, self.retriever)
        else:
            graph_paths = []
        t2 = time.time()
        hits, score = rerank(q, cands, k=rerank_k)
        if self.graph_retriever is not None:
            # multi-hop content+penalty pairs: rerank alone tends to drop
            # one half (doc/report.md §3.2 point 3) -- widens context only,
            # doesn't touch `score`.
            hits = complete_penalty_partners(hits, cands, self.graph_retriever.graph)
            # A confident (exact section/alias, not fuzzy) graph match found
            # by ensure_graph_hits_survive means this query IS answerable
            # from our corpus even if raw rerank score is low -- bump score
            # to TAU_ANSWER so the zone gate doesn't throw away a correct
            # grounded answer and misroute to general_knowledge (real
            # live-test miss: "ต้องใช้หลักฐานอะไรเมื่อร้องเรียนค่าจ้างค้างจ่าย"
            # had graph correctly find มาตรา 123 in hits, but the untouched
            # rerank score still fell below TAU_REJECT).
            hits, graph_confirmed = ensure_graph_hits_survive(hits, self.retriever, self.graph_retriever, q)
            if graph_confirmed and score < config.TAU_ANSWER:
                score = config.TAU_ANSWER
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
        (answer, provider_actually_used).

        Also retries on a *bad* answer body, not just a raised exception --
        two distinct qwen3.6-flash (dotBlue) failure modes, neither of
        which raises: (1) empty -- burns its whole completion-token budget
        on hidden reasoning, returns a 200 OK with zero visible text before
        the citation trailer (doc/report.md §4.0; config.NUM_PREDICT=2500
        fixed most of this but ~6-9% still slips through empty), and (2)
        degenerate -- loops the question back verbatim dozens of times
        (occasionally even leaking meta-commentary about its own looping)
        before recovering into a real answer at the very end, a non-empty
        wall of repeated text that's just as useless to a real user. Both
        are real, silent answer failures the old exception-only fallback
        never caught."""
        fallback_provider = "local" if provider == "api" else "api"
        try:
            out = self._generate(hits, q_used, provider, mode)
            if not _is_bad_body(out):
                return out, provider
            log.warning("generate() returned an empty/degenerate body on provider=%s, retrying with %s", provider, fallback_provider)
        except Exception:
            log.warning("generate() failed on provider=%s, falling back to %s", provider, fallback_provider, exc_info=True)
        return self._generate(hits, q_used, fallback_provider, mode), fallback_provider

    def _general_knowledge_with_fallback(self, q_used, provider):
        """Out-of-scope answer (zone reject/reject-after-retry): LLM's own
        knowledge, clearly disclaimed (generator.generate_general_knowledge),
        not a flat refusal. Same provider-swap fallback as
        _generate_with_fallback; if BOTH providers fail, degrade to the old
        static refusal rather than surface an error to the user.

        A greeting/thanks ("direct_llm" route) skips the disclaimer banner
        -- see generate_general_knowledge's docstring."""
        disclaim = classify_query(q_used).query_type != "direct_llm"
        fallback_provider = "local" if provider == "api" else "api"
        try:
            out = generate_general_knowledge(q_used, provider=provider, disclaim=disclaim)
            if not _is_bad_body(out):
                return out, provider, True
        except Exception:
            log.warning("generate_general_knowledge() failed on provider=%s, falling back to %s", provider, fallback_provider, exc_info=True)
        try:
            return generate_general_knowledge(q_used, provider=fallback_provider, disclaim=disclaim), fallback_provider, True
        except Exception:
            log.warning("generate_general_knowledge() failed on both providers, degrading to static refusal", exc_info=True)
            return "ไม่พบข้อมูลนี้ในตัวบทกฎหมายที่มี กรุณาปรึกษาทนายความหรือหน่วยงานที่เกี่ยวข้อง", provider, False

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
        general_knowledge = False

        t_gen0 = time.time()
        if score < config.TAU_REJECT:
            out, provider_used, general_knowledge = self._general_knowledge_with_fallback(q_used, provider)
            zone = "general_knowledge"
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
                out, provider_used, general_knowledge = self._general_knowledge_with_fallback(q_used, provider)
                zone = "general_knowledge-after-retry"
            else:
                out, provider_used = self._generate_with_fallback(hits, q_used, provider, mode)
        else:
            out, provider_used = self._generate_with_fallback(hits, q_used, provider, mode)
        timing["generate"] = time.time() - t_gen0
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
            "general_knowledge": general_knowledge,
        }
        try:
            log_trace(
                session=session_id, q=q, q_used=q_used, zone=zone,
                rerank_score=score, hits=hits, latency=timing, answer=out, provider=provider_used,
            )
        except Exception:
            pass  # tracing must never break answer()
        return out, debug
