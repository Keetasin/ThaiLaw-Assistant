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

    @patch("src.app.engine.generate")
    @patch("src.app.engine.rerank")
    @patch("src.app.engine.dynamic_k", return_value=(3, 4))
    def test_low_score_rejects_without_calling_generate(self, _dk, mock_rerank, mock_generate):
        mock_rerank.return_value = ([hit()], config.TAU_REJECT - 0.01)
        out, debug = self.engine.answer_with_debug("อากาศวันนี้เป็นอย่างไร", mode="dense")
        self.assertEqual(debug["zone"], "reject")
        self.assertIn("ไม่พบข้อมูล", out)
        mock_generate.assert_not_called()

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

    @patch("src.app.engine.llm_normalize")
    @patch("src.app.engine.generate")
    @patch("src.app.engine.rerank")
    @patch("src.app.engine.dynamic_k", return_value=(3, 4))
    def test_borderline_score_that_does_not_improve_rejects(self, _dk, mock_rerank, mock_generate, mock_normalize):
        borderline_score = (config.TAU_REJECT + config.TAU_ANSWER) / 2
        mock_rerank.return_value = ([hit()], borderline_score)  # same score every call
        mock_normalize.return_value = "same query rewritten"
        out, debug = self.engine.answer_with_debug("มาตรา 61 คืออาลย", mode="dense")
        self.assertEqual(debug["zone"], "reject-after-retry")
        self.assertIn("ไม่พบข้อมูล", out)
        mock_generate.assert_not_called()


ROUTE_STUB = RouteDecision(query_type="lookup", alpha_dense=0.2, alpha_bm25=0.4, alpha_graph=0.4)


class AnswerWithDebugHybridModeTests(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()
        # non-None so `_generate`'s `self.graph_retriever.graph` access and
        # the `graph_seeded_expand` call both go through; the "missing
        # graph retriever" test below overrides this back to None.
        self.engine.graph_retriever = SimpleNamespace(graph={"nodes": [], "edges": []})

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


if __name__ == "__main__":
    unittest.main()
