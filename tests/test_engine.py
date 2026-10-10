import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src import config
from src.app.engine import RAGEngine, _strip_leading_pronoun, clean_query, needs_rewrite
from src.retrieval.router import RouteDecision


def make_engine():
    engine = RAGEngine.__new__(RAGEngine)  # skip __init__: no real Chroma/BM25/model I/O
    engine.retriever = _StubRetriever()
    engine.graph_retriever = None  # hybrid/graph-mode tests patch what they need directly
    engine.sections = {}  # expand() looks up by section_key and no-ops on a miss
    engine.history = {}
    engine._history_lock = threading.Lock()
    return engine


class _StubRetriever:
    chunks: dict = {}  # ensure_graph_hits_survive's _section_to_chunk_ids reads this

    def search(self, q, fuse_k=None):
        return (["stub_candidate"], 0.5)


def hit(section_key="LPA2541-s61", section_no="61", law_id="LPA2541"):
    return {"section_key": section_key, "section_no": section_no, "chapter": None, "text": "...", "law_id": law_id}


class CleanQueryTests(unittest.TestCase):
    def test_strips_invisible_chars(self):
        self.assertEqual(clean_query("มาตรา​ 61"), "มาตรา 61")

    def test_strips_leading_trailing_whitespace(self):
        self.assertEqual(clean_query("  มาตรา 61  "), "มาตรา 61")


class NeedsRewriteTests(unittest.TestCase):
    def test_false_when_no_history(self):
        self.assertFalse(needs_rewrite("แล้วต้องทำไง", []))

    def test_true_for_short_query_with_history(self):
        self.assertTrue(needs_rewrite("ทำไงดี", [("q", "a")]))

    def test_true_for_pronoun_marker_with_history(self):
        self.assertTrue(needs_rewrite("แล้วถ้าไม่จ่ายล่ะจะเป็นอย่างไรต่อไป", [("q", "a")]))

    def test_false_for_long_self_contained_query_with_history(self):
        self.assertFalse(needs_rewrite("นายจ้างไม่จ่ายค่าล่วงเวลาต้องทำอย่างไรตามกฎหมาย", [("q", "a")]))


class StripLeadingPronounTests(unittest.TestCase):
    def test_strips_known_marker(self):
        self.assertEqual(_strip_leading_pronoun("แล้วถ้าไม่จ่ายล่ะ"), "ถ้าไม่จ่ายล่ะ")

    def test_leaves_text_without_marker_unchanged(self):
        self.assertEqual(_strip_leading_pronoun("ถ้าไม่จ่ายล่ะ"), "ถ้าไม่จ่ายล่ะ")

    def test_falls_back_to_original_if_stripping_empties_it(self):
        self.assertEqual(_strip_leading_pronoun("แล้ว"), "แล้ว")


class HistoryConcurrencyTests(unittest.TestCase):
    def test_get_history_returns_a_copy_not_a_live_reference(self):
        engine = make_engine()
        engine.history["u1"] = [("q1", "a1")]
        snapshot = engine._get_history("u1")
        engine.history["u1"].append(("q2", "a2"))
        self.assertEqual(snapshot, [("q1", "a1")])  # unaffected by the later mutation

    def test_concurrent_appends_stay_well_formed(self):
        engine = make_engine()
        errors = []

        def worker(i):
            try:
                engine._append_history("shared-user", f"q{i}", f"a{i}")
            except Exception as e:  # pragma: no cover - failure path only
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        hist = engine.history["shared-user"]
        self.assertLessEqual(len(hist), 3)
        self.assertTrue(all(isinstance(entry, tuple) and len(entry) == 2 for entry in hist))


class AnswerWithDebugZoneTests(unittest.TestCase):
    """mode="dense" only — the exact pre-Day3 code path, kept as a
    regression guard that it's still byte-for-byte unchanged behavior."""

    def setUp(self):
        self.engine = make_engine()

    @patch("src.app.engine.generate", return_value="GENERATED ANSWER")
    @patch("src.app.engine.rerank")
    @patch("src.app.engine.dynamic_k", return_value=(3, 4))
    def test_high_score_goes_straight_to_answer(self, _dk, mock_rerank, mock_generate):
        mock_rerank.return_value = ([hit()], config.TAU_ANSWER + 0.1)
        out, debug = self.engine.answer_with_debug("มาตรา 61 คืออะไร", mode="dense")
        self.assertEqual(debug["zone"], "answer")
        self.assertEqual(out, "GENERATED ANSWER")
        self.assertEqual(debug["mode"], "dense")
        self.assertIsNone(debug["route"])
        mock_generate.assert_called_once()

    @patch("src.app.engine.generate_general_knowledge", return_value="DISCLAIMED GENERAL-KNOWLEDGE ANSWER")
    @patch("src.app.engine.generate")
    @patch("src.app.engine.rerank")
    @patch("src.app.engine.dynamic_k", return_value=(3, 4))
    def test_low_score_answers_from_llm_general_knowledge_not_rag(self, _dk, mock_rerank, mock_generate, mock_general):
        # Out-of-scope no longer means a flat refusal (doc/report.md's
        # out-of-scope design change): the LLM answers from its own
        # knowledge, clearly disclaimed, instead of the RAG generate() path.
        mock_rerank.return_value = ([hit()], config.TAU_REJECT - 0.01)
        out, debug = self.engine.answer_with_debug("อากาศวันนี้เป็นอย่างไร", mode="dense")
        self.assertEqual(debug["zone"], "general_knowledge")
        self.assertEqual(out, "DISCLAIMED GENERAL-KNOWLEDGE ANSWER")
        self.assertTrue(debug["general_knowledge"])
        mock_generate.assert_not_called()  # never the RAG-grounded generate()
        mock_general.assert_called_once()

    @patch("src.app.engine.llm_normalize")
    @patch("src.app.engine.generate", return_value="GENERATED ANSWER")
    @patch("src.app.engine.rerank")
    @patch("src.app.engine.dynamic_k", return_value=(3, 4))
    def test_borderline_score_that_improves_on_retry_answers(self, _dk, mock_rerank, mock_generate, mock_normalize):
        borderline_score = (config.TAU_REJECT + config.TAU_ANSWER) / 2
        mock_rerank.side_effect = [
            ([hit(section_no="1")], borderline_score),
            ([hit(section_no="61")], config.TAU_ANSWER + 0.1),
        ]
        mock_normalize.return_value = "มาตรา 61 คืออะไร (แก้คำผิดแล้ว)"
        out, debug = self.engine.answer_with_debug("มาตรา 61 คืออาลย", mode="dense")
        # Zone stays "borderline" on a successful retry — engine.py only
        # relabels to "reject-after-retry" on the failure path, never to
        # "answer" on the success path.
        self.assertEqual(debug["zone"], "borderline")
        self.assertEqual(out, "GENERATED ANSWER")
        self.assertEqual(debug["hits"][0]["section_no"], "61")

    @patch("src.app.engine.generate_general_knowledge", return_value="DISCLAIMED GENERAL-KNOWLEDGE ANSWER")
    @patch("src.app.engine.llm_normalize")
    @patch("src.app.engine.generate")
    @patch("src.app.engine.rerank")
    @patch("src.app.engine.dynamic_k", return_value=(3, 4))
    def test_borderline_score_that_does_not_improve_answers_from_general_knowledge(self, _dk, mock_rerank, mock_generate, mock_normalize, mock_general):
        borderline_score = (config.TAU_REJECT + config.TAU_ANSWER) / 2
        mock_rerank.return_value = ([hit()], borderline_score)  # same score every call
        mock_normalize.return_value = "same query rewritten"
        out, debug = self.engine.answer_with_debug("มาตรา 61 คืออาลย", mode="dense")
        self.assertEqual(debug["zone"], "general_knowledge-after-retry")
        self.assertEqual(out, "DISCLAIMED GENERAL-KNOWLEDGE ANSWER")
        self.assertTrue(debug["general_knowledge"])
        mock_generate.assert_not_called()
        mock_general.assert_called_once()

    @patch("src.app.engine.generate_general_knowledge")
    @patch("src.app.engine.llm_normalize")
    @patch("src.app.engine.generate")
    @patch("src.app.engine.rerank")
    @patch("src.app.engine.dynamic_k", return_value=(3, 4))
    def test_general_knowledge_degrades_to_static_refusal_if_both_providers_fail(self, _dk, mock_rerank, mock_generate, mock_normalize, mock_general):
        mock_rerank.return_value = ([hit()], config.TAU_REJECT - 0.01)
        mock_general.side_effect = ConnectionError("both providers down")
        out, debug = self.engine.answer_with_debug("อากาศวันนี้เป็นอย่างไร", mode="dense")
        self.assertIn("ไม่พบข้อมูล", out)
        self.assertFalse(debug["general_knowledge"])


ROUTE_STUB = RouteDecision(query_type="lookup", alpha_dense=0.2, alpha_bm25=0.4, alpha_graph=0.4)


class AnswerWithDebugHybridModeTests(unittest.TestCase):
    def setUp(self):
        # these tests mock `rerank` (the pure cross-encoder path); the blend path has its own tests below
        for name in ("RERANK_BLEND_W", "RERANK_GRAPH_BONUS"):
            patcher = patch.object(config, name, 0.0)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.engine = make_engine()
        # non-None so `_generate`'s `self.graph_retriever.graph` access and
        # the `graph_seeded_expand` call both go through; the "missing
        # graph retriever" test below overrides this back to None. `search`
        # backs `ensure_graph_hits_survive`'s safety-net lookup (doc/report.md
        # §3.4) -- empty result means it's a no-op here, same as a real
        # GraphRetriever over an empty graph would return.
        self.engine.graph_retriever = SimpleNamespace(graph={"nodes": [], "edges": []}, search=lambda *a, **k: {"sections": []})

    @patch("src.app.engine.generate_from_cards", return_value="HYBRID ANSWER")
    @patch("src.app.engine.build_section_cards", return_value=["CARD"])
    @patch("src.app.engine.rerank")
    @patch("src.app.engine.graph_seeded_expand")
    @patch("src.app.engine.hybrid_search")
    @patch("src.app.engine.classify_query", return_value=ROUTE_STUB)
    @patch("src.app.engine.dynamic_k", return_value=(3, 4))
    def test_hybrid_mode_calls_router_fusion_and_expansion_not_dense_search(
        self, _dk, mock_classify, mock_hybrid_search, mock_expand, mock_rerank, _cards, _gen
    ):
        mock_hybrid_search.return_value = ["cand"]
        mock_expand.return_value = ([hit()], [{"from": "a", "type": "REFERS_TO", "to": "b"}])
        mock_rerank.return_value = ([hit()], config.TAU_ANSWER + 0.1)

        out, debug = self.engine.answer_with_debug("มาตรา 61 คืออะไร", mode="hybrid")

        mock_classify.assert_called_once()
        mock_hybrid_search.assert_called_once()
        mock_expand.assert_called_once()
        self.assertEqual(out, "HYBRID ANSWER")
        self.assertEqual(debug["mode"], "hybrid")
        self.assertEqual(debug["route"]["query_type"], "lookup")
        self.assertEqual(debug["graph_paths"], [{"from": "a", "type": "REFERS_TO", "to": "b"}])

    @patch("src.app.engine.generate_from_cards", return_value="HYBRID ANSWER")
    @patch("src.app.engine.build_section_cards", return_value=["CARD"])
    @patch("src.app.engine.rerank")
    @patch("src.app.engine.graph_seeded_expand")
    @patch("src.app.engine.hybrid_search")
    @patch("src.app.engine.dynamic_k", return_value=(3, 4))
    def test_graph_mode_uses_all_graph_route_without_calling_classify_query(
        self, _dk, mock_hybrid_search, mock_expand, mock_rerank, _cards, _gen
    ):
        mock_hybrid_search.return_value = []
        mock_expand.return_value = ([hit()], [])
        mock_rerank.return_value = ([hit()], config.TAU_ANSWER + 0.1)

        with patch("src.app.engine.classify_query") as mock_classify:
            out, debug = self.engine.answer_with_debug("มาตรา 61 คืออะไร", mode="graph")
            mock_classify.assert_not_called()

        route_used = mock_hybrid_search.call_args.args[3]
        self.assertEqual(route_used.alpha_graph, 1.0)
        self.assertEqual(route_used.alpha_dense, 0.0)
        self.assertEqual(debug["mode"], "graph")

    @patch("src.app.engine.graph_seeded_expand", return_value=([hit()], []))
    @patch("src.app.engine.hybrid_search", return_value=[])
    @patch("src.app.engine.dynamic_k", return_value=(3, 4))
    def test_missing_graph_retriever_still_produces_empty_graph_paths(self, _dk, _hs, _expand):
        # Explicitly None here (overriding setUp's stub) — this is the
        # "graph snapshot unavailable" degrade path, distinct from
        # fusion.hybrid_search's own graph_retriever=None handling (already
        # covered in tests/test_fusion.py) — here it's engine.py's own
        # `if self.graph_retriever is not None` guard around
        # graph_seeded_expand being exercised.
        self.engine.graph_retriever = None
        with patch("src.app.engine.rerank", return_value=([hit()], config.TAU_ANSWER + 0.1)):
            with patch("src.app.engine.generate_from_cards", return_value="X"):
                with patch("src.app.engine.build_section_cards", return_value=[]):
                    _out, debug = self.engine.answer_with_debug("q", mode="hybrid")
        self.assertEqual(debug["graph_paths"], [])
        _expand.assert_not_called()  # never called at all when graph_retriever is None

    @patch("src.app.engine.generate_general_knowledge", return_value="SHOULD NOT BE USED")
    @patch("src.app.engine.generate_from_cards", return_value="GROUNDED ANSWER")
    @patch("src.app.engine.build_section_cards", return_value=["CARD"])
    @patch("src.app.engine.rerank")
    @patch("src.app.engine.graph_seeded_expand")
    @patch("src.app.engine.hybrid_search")
    @patch("src.app.engine.classify_query", return_value=ROUTE_STUB)
    @patch("src.app.engine.dynamic_k", return_value=(3, 4))
    def test_confident_graph_match_prevents_misrouting_to_general_knowledge(
        self, _dk, _classify, mock_hybrid_search, mock_expand, mock_rerank, _cards, _gen, mock_general
    ):
        # Real live-test miss (doc/report.md): "ต้องใช้หลักฐานอะไรเมื่อร้อง
        # เรียนค่าจ้างค้างจ่าย" had GraphRetriever correctly find มาตรา 123,
        # but rerank's untouched top-1 score fell below TAU_REJECT, so the
        # whole query got routed to general_knowledge and the correct
        # grounded answer was thrown away. ensure_graph_hits_survive finding
        # a confident match must bump score past the gate instead.
        mock_hybrid_search.return_value = ["cand"]
        mock_expand.return_value = ([hit()], [])
        mock_rerank.return_value = ([hit()], config.TAU_REJECT - 0.01)  # would reject on its own
        self.engine.graph_retriever = SimpleNamespace(
            graph={"nodes": [], "edges": []},
            search=lambda *a, **k: {"sections": [{"law_id": hit()["law_id"], "section_no": "999"}]},
        )
        self.engine.retriever.chunks = {"extra": {**hit(), "chunk_id": "extra", "section_no": "999"}}

        out, debug = self.engine.answer_with_debug("ต้องใช้หลักฐานอะไรเมื่อร้องเรียนค่าจ้างค้างจ่าย", mode="hybrid")

        self.assertEqual(debug["zone"], "answer")
        self.assertFalse(debug["general_knowledge"])
        self.assertEqual(out, "GROUNDED ANSWER")
        mock_general.assert_not_called()


class UsageAccountingTests(unittest.TestCase):
    @patch("src.app.engine.generate")
    @patch("src.app.engine.rerank")
    @patch("src.app.engine.dynamic_k", return_value=(3, 4))
    def test_debug_usage_sums_llm_calls_since_reset(self, _dk, mock_rerank, mock_generate):
        from src.llm import client

        def fake_generate(*_a, **_k):
            client._record_usage({"prompt_tokens": 100, "completion_tokens": 20})
            client._record_usage({"prompt_tokens": 50, "completion_tokens": None})
            return "OK"

        mock_rerank.return_value = ([hit()], config.TAU_ANSWER + 0.1)
        mock_generate.side_effect = fake_generate
        client._record_usage({"prompt_tokens": 999, "completion_tokens": 999})  # stale, must be dropped by reset
        _out, debug = make_engine().answer_with_debug("q", provider="local", mode="dense")
        self.assertEqual(debug["usage"], {"llm_calls": 2, "prompt_tokens": 150, "completion_tokens": 20})


class LLMFallbackTests(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()

    @patch("src.app.engine.generate")
    @patch("src.app.engine.rerank")
    @patch("src.app.engine.dynamic_k", return_value=(3, 4))
    def test_falls_back_to_the_other_provider_when_generate_raises(self, _dk, mock_rerank, mock_generate):
        mock_rerank.return_value = ([hit()], config.TAU_ANSWER + 0.1)
        mock_generate.side_effect = [ConnectionError("api down"), "FALLBACK ANSWER"]

        out, debug = self.engine.answer_with_debug("มาตรา 61 คืออะไร", provider="api", mode="dense")

        self.assertEqual(out, "FALLBACK ANSWER")
        self.assertEqual(debug["provider"], "local")
        self.assertTrue(debug["provider_fallback"])
        self.assertEqual(mock_generate.call_count, 2)
        first_call_kwargs, second_call_kwargs = mock_generate.call_args_list[0].kwargs, mock_generate.call_args_list[1].kwargs
        self.assertEqual(first_call_kwargs.get("provider"), "api")
        self.assertEqual(second_call_kwargs.get("provider"), "local")

    @patch("src.app.engine.generate", return_value="OK")
    @patch("src.app.engine.rerank")
    @patch("src.app.engine.dynamic_k", return_value=(3, 4))
    def test_no_fallback_recorded_when_generate_succeeds(self, _dk, mock_rerank, mock_generate):
        mock_rerank.return_value = ([hit()], config.TAU_ANSWER + 0.1)
        out, debug = self.engine.answer_with_debug("q", provider="local", mode="dense")
        self.assertEqual(debug["provider"], "local")
        self.assertFalse(debug["provider_fallback"])
        mock_generate.assert_called_once()

    @patch("src.app.engine.generate")
    @patch("src.app.engine.rerank")
    @patch("src.app.engine.dynamic_k", return_value=(3, 4))
    def test_retries_other_provider_on_empty_body_not_just_exceptions(self, _dk, mock_rerank, mock_generate):
        # qwen3.6-flash's real failure mode (doc/report.md §4.0): a 200 OK
        # with nothing but the citation trailer, no exception raised.
        mock_rerank.return_value = ([hit()], config.TAU_ANSWER + 0.1)
        mock_generate.side_effect = ["\n\nที่มา: พ.ร.บ.คุ้มครองแรงงาน\n  § มาตรา 61", "REAL ANSWER\n\nที่มา: ..."]

        out, debug = self.engine.answer_with_debug("มาตรา 61 คืออะไร", provider="api", mode="dense")

        self.assertEqual(out, "REAL ANSWER\n\nที่มา: ...")
        self.assertEqual(debug["provider"], "local")
        self.assertTrue(debug["provider_fallback"])
        self.assertEqual(mock_generate.call_count, 2)

    @patch("src.app.engine.generate")
    @patch("src.app.engine.rerank")
    @patch("src.app.engine.dynamic_k", return_value=(3, 4))
    def test_retries_other_provider_on_degenerate_repetition_body(self, _dk, mock_rerank, mock_generate):
        # A second, distinct qwen3.6-flash failure mode found via real live
        # LINE testing: not empty, but the question echoed back verbatim
        # dozens of times (occasionally with leaked meta-commentary) before
        # recovering into a real answer -- non-empty so _is_empty_body alone
        # would have accepted it as-is.
        mock_rerank.return_value = ([hit()], config.TAU_ANSWER + 0.1)
        looped = "\n".join(["ต้องใช้อะไรเมื่อร้องเรียนค่าจ้างค้างจ่าย"] * 20) + "\n\nที่มา: ..."
        mock_generate.side_effect = [looped, "REAL ANSWER\n\nที่มา: ..."]

        out, debug = self.engine.answer_with_debug("ต้องใช้อะไรเมื่อร้องเรียนค่าจ้างค้างจ่าย", provider="api", mode="dense")

        self.assertEqual(out, "REAL ANSWER\n\nที่มา: ...")
        self.assertTrue(debug["provider_fallback"])
        self.assertEqual(mock_generate.call_count, 2)


class BlendRerankEngineTests(unittest.TestCase):
    """retrieve_and_rerank_hybrid with RERANK_BLEND_* on: graph-confirmed candidate survives top-k,
    and the zone-gate score stays the raw cross-encoder maximum."""

    @patch("src.app.engine.rerank_scores")
    @patch("src.app.engine.graph_seeded_expand")
    @patch("src.app.engine.hybrid_search")
    @patch("src.app.engine.classify_query", return_value=RouteDecision(query_type="general", alpha_dense=0.6, alpha_bm25=0.3, alpha_graph=0.1))
    @patch("src.app.engine.dynamic_k", return_value=(2, 3))
    def test_graph_confirmed_candidate_kept_and_score_is_raw_ce_max(self, _dk, _route, mock_hybrid, mock_expand, mock_scores):
        cands = [{**hit(section_key=f"K{i}", section_no=str(i)), "chunk_id": f"c{i}"} for i in range(4)]

        def fake_hybrid(*_a, graph_ids_out=None, **_k):
            graph_ids_out.add("c3")  # last candidate, lowest CE score, but graph-confirmed
            return cands
        mock_hybrid.side_effect = fake_hybrid
        mock_expand.return_value = (cands, [])
        mock_scores.return_value = [0.5, 0.4, 0.3, 0.01]
        engine = make_engine()
        engine.graph_retriever = SimpleNamespace(graph={"nodes": [], "edges": []}, search=lambda *a, **k: {"sections": []})
        with patch.object(config, "RERANK_BLEND_W", 0.0), patch.object(config, "RERANK_GRAPH_BONUS", 0.5):
            hits, score, _route, _paths = engine.retrieve_and_rerank_hybrid("q", "hybrid")
        self.assertIn("c3", [h["chunk_id"] for h in hits])
        self.assertAlmostEqual(score, 0.5)


if __name__ == "__main__":
    unittest.main()
