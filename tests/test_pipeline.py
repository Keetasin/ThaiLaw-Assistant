import csv
import json
import unittest
from pathlib import Path

from src.ingest.parse_sections import parse_sections
from src.ingest.chunk import _split_long_section
from src.index.graph_core import build_graph, cypher_statements, merge_triples_and_topics
from src.index.triples import load_topics, validate_triples

ROOT = Path(__file__).parents[1]

SAMPLE_TEXT = "\n".join([
    "หมวด 1",
    "ทั่วไป",
    "มาตรา 1 นายจ้างต้องจ่ายค่าจ้าง",
    "ตามมาตรา 2",
    "มาตรา 2 ค่าจ้างหมายความว่า เงิน",
    "มาตรา 3 (ยกเลิก)",
    "ผู้รับสนองพระบรมราชโองการ",
])


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.sections = parse_sections(SAMPLE_TEXT)

    def test_parser_structure_and_status(self):
        self.assertEqual([x["section_no"] for x in self.sections], ["1", "2", "3"])
        self.assertEqual(self.sections[0]["chapter"], "หมวด 1 ทั่วไป")
        self.assertEqual(self.sections[2]["status"], "repealed")
        self.assertEqual(self.sections[0]["refs_out"], ["2"])

    def test_split_long_section_keeps_short_sections_whole(self):
        self.assertEqual(_split_long_section("สั้นมาก"), ["สั้นมาก"])

    def test_graph_is_idempotent(self):
        chunks = [
            {"law_id": "LAW", "law_name": "Law", "chapter": "หมวด 1", "section_no": "1",
             "status": "in_force", "refs_out": ["2"], "text": "มาตรา 1 นายจ้างต้องจ่ายค่าจ้างตามมาตรา 2"},
            {"law_id": "LAW", "law_name": "Law", "chapter": "หมวด 1", "section_no": "2",
             "status": "in_force", "refs_out": [], "text": "มาตรา 2 ค่าจ้างหมายความว่า เงิน"},
        ]
        graph = build_graph(chunks + chunks)
        self.assertEqual(len([x for x in graph["edges"] if x["type"] == "HAS_SECTION"]), 2)
        self.assertTrue(any(x["type"] == "REFERS_TO" for x in graph["edges"]))
        self.assertTrue(cypher_statements(graph))

    def test_define_regex_matches_without_leading_khamwaa(self):
        # This statute's actual phrasing is just "TERM" หมายความว่า, with no
        # "คำว่า" prefix — see doc/data_quality_report.md.
        chunks = [{"law_id": "LAW", "law_name": "Law", "chapter": "หมวด 1", "section_no": "5",
                   "status": "in_force", "refs_out": [], "text": '“นายจ้าง” หมายความว่า ผู้ซึ่งตกลงรับลูกจ้าง'}]
        graph = build_graph(chunks)
        self.assertTrue(any(x["label"] == "Term" for x in graph["nodes"]))
        self.assertTrue(any(x["type"] == "DEFINES" for x in graph["edges"]))

    def test_merge_triples_and_topics_reconstructs_held_by_and_binds(self):
        chunks = [{"law_id": "LAW", "law_name": "Law", "chapter": "หมวด 1", "section_no": "5",
                   "status": "in_force", "refs_out": [], "text": "มาตรา 5"}]
        graph = build_graph(chunks)
        triples = [
            {"subject": "ลูกจ้าง", "subject_type": "Actor", "relation": "GRANTS_RIGHT",
             "object": "ค่าจ้าง", "object_type": "Right", "section_no": "5"},
            {"subject": "นายจ้าง", "subject_type": "Actor", "relation": "IMPOSES_DUTY",
             "object": "เงินสมทบ", "object_type": "Duty", "section_no": "5"},
        ]
        topic_rows = [{"topic": "ค่าจ้างขั้นต่ำ", "agency": "กรมสวัสดิการฯ", "evidence": "สลิปเงินเดือน",
                       "form": "แบบคำร้อง", "step": "ยื่นคำร้อง", "source_url": "https://www.labour.go.th"}]
        merge_triples_and_topics(graph, triples, topic_rows, "LAW")

        edge_types = {(e["type"]) for e in graph["edges"]}
        self.assertIn("GRANTS_RIGHT", edge_types)
        self.assertIn("HELD_BY", edge_types)
        self.assertIn("IMPOSES_DUTY", edge_types)
        self.assertIn("BINDS", edge_types)
        self.assertIn("HANDLED_BY", edge_types)
        self.assertIn("REQUIRES_EVIDENCE", edge_types)

        right_holder = next(e for e in graph["edges"] if e["type"] == "HELD_BY")
        self.assertEqual(right_holder["target"], "Actor:ลูกจ้าง")
        duty_binder = next(e for e in graph["edges"] if e["type"] == "BINDS")
        self.assertEqual(duty_binder["target"], "Actor:นายจ้าง")

    def test_triple_validation(self):
        topics = {"ค่าจ้าง"}
        items = [{"subject": "นายจ้าง", "subject_type": "Actor", "relation": "IMPOSES_DUTY", "object": "จ่ายค่าจ้าง", "object_type": "Duty"},
                 {"subject": "x", "subject_type": "Actor", "relation": "BAD", "object": "y", "object_type": "Topic"},
                 {"subject": "x", "subject_type": "Actor", "relation": "ABOUT", "object": "ค่าจ้าง", "object_type": "Topic"}]
        self.assertEqual(len(validate_triples(items, topics)), 2)

    def test_taxonomy_has_topics_and_urls(self):
        path = ROOT / "data/curated/topic_agency_evidence_form_step.csv"
        with path.open(encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        self.assertGreaterEqual(len(load_topics(path)), 30)
        self.assertTrue(all(row["source_url"].startswith("http") for row in rows))


class RealDataTests(unittest.TestCase):
    """Data-driven checks against the committed data/ pipeline output —
    catches the pipeline drifting from what's actually on disk (see
    doc/data_quality_report.md for the full stats)."""

    def test_chunks_and_sections_match_current_schema(self):
        chunks = [json.loads(line) for line in (ROOT / "data/chunks.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertGreater(len(chunks), 0)
        required = {"chunk_id", "section_key", "law_id", "law_name", "chapter", "section_no",
                    "status", "refs_out", "source_url", "retrieved_date", "text"}
        self.assertTrue(required.issubset(chunks[0].keys()))
        ids = [c["chunk_id"] for c in chunks]
        self.assertEqual(len(ids), len(set(ids)))

    def test_graph_has_full_plan_schema_node_types(self):
        graph = json.loads((ROOT / "data/graph.json").read_text(encoding="utf-8"))
        labels = {n["label"] for n in graph["nodes"]}
        # PLAN.md §4.2's 13 node types minus Penalty (no HAS_PENALTY triples
        # were extracted in this 30-triple sample) minus Actor-to-Law
        # AMENDED_BY (N/A — single-statute corpus).
        expected = {"Law", "Chapter", "Section", "Term", "Topic", "Actor", "Right", "Duty",
                    "Agency", "Evidence", "Form", "Step"}
        self.assertTrue(expected.issubset(labels), f"missing: {expected - labels}")

    def test_graph_has_no_orphan_topic_nodes(self):
        graph = json.loads((ROOT / "data/graph.json").read_text(encoding="utf-8"))
        topic_ids = {n["id"] for n in graph["nodes"] if n["label"] == "Topic"}
        connected = {e["source"] for e in graph["edges"]} | {e["target"] for e in graph["edges"]}
        self.assertTrue(topic_ids.issubset(connected))


if __name__ == "__main__":
    unittest.main()
