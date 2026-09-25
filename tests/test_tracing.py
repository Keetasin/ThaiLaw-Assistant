import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.app.tracing import log_trace


class LogTraceTests(unittest.TestCase):
    def test_writes_one_valid_json_line_with_expected_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace_path = Path(tmp) / "sub" / "traces.jsonl"
            with patch("src.app.tracing.config.TRACE_PATH", str(trace_path)):
                log_trace(
                    session="s1", q="raw q", q_used="rewritten q", zone="answer",
                    rerank_score=0.42, hits=[{"chunk_id": "LPA2541-s61-p1", "section_no": "61", "chapter": None}],
                    latency={"total": 1.2}, answer="some answer text", provider="local",
                )
            lines = trace_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            record = json.loads(lines[0])
            self.assertEqual(record["session"], "s1")
            self.assertEqual(record["q"], "raw q")
            self.assertEqual(record["q_used"], "rewritten q")
            self.assertEqual(record["zone"], "answer")
            self.assertEqual(record["rerank_score"], 0.42)
            self.assertEqual(record["hits"], [{"id": "LPA2541-s61-p1", "section_no": "61", "chapter": None}])
            self.assertEqual(record["answer_len"], len("some answer text"))
            self.assertIn("ts", record)

    def test_never_raises_on_write_failure(self):
        # An unwritable path (parent is a file, not a dir) must not propagate.
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "not_a_dir"
            blocker.write_text("x", encoding="utf-8")
            bad_path = blocker / "traces.jsonl"
            with patch("src.app.tracing.config.TRACE_PATH", str(bad_path)):
                log_trace(session="s", q="q", q_used="q", zone="reject", rerank_score=0.0,
                          hits=[], latency={}, answer="", provider=None)  # must not raise


if __name__ == "__main__":
    unittest.main()
