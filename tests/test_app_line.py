import unittest
from unittest.mock import MagicMock, patch

from src.app import app_line


class HandleCommandTests(unittest.TestCase):
    def setUp(self):
        app_line._session_state.clear()

    def test_plain_text_is_not_a_command(self):
        self.assertIsNone(app_line._handle_command("u1", "มาตรา 61 คืออะไร"))

    def test_mode_command_sets_valid_mode(self):
        reply = app_line._handle_command("u1", "/mode graph")
        self.assertIn("graph", reply)
        self.assertEqual(app_line._state("u1")["mode"], "graph")

    def test_mode_command_rejects_invalid_mode(self):
        reply = app_line._handle_command("u1", "/mode banana")
        self.assertIn("/mode dense|graph|hybrid", reply)
        self.assertEqual(app_line._state("u1")["mode"], "hybrid")  # unchanged default

    def test_llm_command_sets_valid_provider(self):
        reply = app_line._handle_command("u1", "/llm api")
        self.assertIn("api", reply)
        self.assertEqual(app_line._state("u1")["provider"], "api")

    def test_llm_command_rejects_invalid_provider(self):
        reply = app_line._handle_command("u1", "/llm banana")
        self.assertIn("/llm local|api", reply)

    def test_debug_command_toggles(self):
        self.assertFalse(app_line._state("u1")["debug"])
        app_line._handle_command("u1", "/debug")
        self.assertTrue(app_line._state("u1")["debug"])
        app_line._handle_command("u1", "/debug")
        self.assertFalse(app_line._state("u1")["debug"])

    @patch("src.app.app_line.chat_history")
    @patch("src.app.app_line.get_engine")
    def test_reset_command_clears_engine_and_neo4j_history_and_local_state(self, mock_get_engine, mock_chat_history):
        mock_engine = MagicMock()
        mock_get_engine.return_value = mock_engine
        app_line._state("u1")["mode"] = "graph"  # prove state gets wiped

        reply = app_line._handle_command("u1", "/reset")

        mock_engine.clear_history.assert_called_once_with("u1")
        mock_chat_history.clear_history.assert_called_once_with("u1")
        self.assertIn("ล้างประวัติ", reply)
        self.assertEqual(app_line._state("u1")["mode"], "hybrid")  # back to default, not "graph"

    @patch("src.app.app_line.chat_history")
    @patch("src.app.app_line.get_engine")
    def test_reset_survives_chat_history_failure(self, mock_get_engine, mock_chat_history):
        mock_chat_history.clear_history.side_effect = ConnectionError("neo4j down")
        reply = app_line._handle_command("u1", "/reset")  # must not raise
        self.assertIn("ล้างประวัติ", reply)

    def test_unknown_command_returns_help(self):
        reply = app_line._handle_command("u1", "/foo")
        self.assertEqual(reply, app_line.COMMAND_HELP)


class FormatDebugTests(unittest.TestCase):
    def test_includes_mode_zone_score_and_route(self):
        debug = {
            "mode": "hybrid", "zone": "answer", "rerank_score": 0.178,
            "provider": "local", "provider_fallback": False,
            "route": {"query_type": "lookup", "alpha_dense": 0.2, "alpha_bm25": 0.4, "alpha_graph": 0.4},
            "hits": [{"section_no": "61"}, {"section_no": "144"}],
            "graph_paths": [{"from": "Section:LPA2541:61", "type": "REFERS_TO", "to": "Section:LPA2541:65"}],
            "latency": {"retrieve": 0.1, "rerank": 0.05, "generate": 1.2},
        }
        text = app_line._format_debug(debug)
        self.assertIn("mode=hybrid", text)
        self.assertIn("zone=answer", text)
        self.assertIn("score=0.178", text)
        self.assertIn("route=lookup", text)
        self.assertIn("61", text)
        self.assertIn("REFERS_TO", text)
        self.assertIn("provider=local", text)
        self.assertNotIn("(fallback)", text)

    def test_marks_provider_fallback(self):
        debug = {
            "mode": "dense", "zone": "answer", "rerank_score": 0.5,
            "provider": "local", "provider_fallback": True,
            "route": None, "hits": [], "graph_paths": [], "latency": {},
        }
        text = app_line._format_debug(debug)
        self.assertIn("provider=local (fallback)", text)

    def test_handles_empty_route_and_paths_without_crashing(self):
        debug = {
            "mode": "dense", "zone": "reject", "rerank_score": 0.01,
            "provider": "local", "provider_fallback": False,
            "route": None, "hits": [], "graph_paths": [], "latency": {},
        }
        text = app_line._format_debug(debug)  # must not raise
        self.assertIn("zone=reject", text)


if __name__ == "__main__":
    unittest.main()
