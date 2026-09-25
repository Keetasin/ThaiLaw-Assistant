import csv, tempfile, unittest
from pathlib import Path

from src.ingest.day2_parse import parse_lines
from src.ingest.day2_chunk import create_chunks
from src.index.day2_graph import build_graph, cypher_statements
from src.index.day2_triples import load_topics, validate_triples
from src.ingest.parse_sections import parse_lines as canonical_parse_lines
from src.ingest.chunk import create_chunks as canonical_create_chunks
from src.index.build_graph import build_graph as canonical_build_graph

class Day2Tests(unittest.TestCase):
    def setUp(self):
        self.sections = parse_lines(["หมวด 1 ทั่วไป", "มาตรา ๑ นายจ้างต้องจ่ายค่าจ้าง", "ตามมาตรา ๒", "มาตรา ๒ ค่าจ้างหมายความว่า เงิน", "มาตรา ๓ (ยกเลิก)"])

    def test_parser_structure_and_status(self):
        self.assertEqual([x["section_no"] for x in self.sections], ["1", "2", "3"])
        self.assertEqual(self.sections[0]["chapter"], "หมวด 1 ทั่วไป")
        self.assertEqual(self.sections[2]["status"], "repealed")
        self.assertEqual(len(canonical_parse_lines(["มาตรา ๑ ทดสอบ"])), 1)

    def test_chunks_schema_and_refs(self):
        chunks = create_chunks(self.sections, "LAW", "Law", "https://example.test", retrieved_date="2026-09-25")
        self.assertEqual(chunks[0]["chunk_id"], "LAW-s1-p1")
        self.assertEqual(chunks[0]["refs_out"], ["2"])
        self.assertTrue(all(x["source_url"] and x["retrieved_date"] for x in chunks))
        self.assertEqual(len(canonical_create_chunks(self.sections, "LAW", "Law", "https://example.test")), len(chunks))

    def test_graph_is_idempotent(self):
        chunks = create_chunks(self.sections, "LAW", "Law", "https://example.test")
        graph = build_graph(chunks + chunks)
        self.assertEqual(len([x for x in graph["edges"] if x["type"] == "HAS_SECTION"]), 3)
        self.assertTrue(any(x["type"] == "REFERS_TO" for x in graph["edges"]))
        self.assertTrue(cypher_statements(graph))
        self.assertEqual(len(canonical_build_graph(chunks)["nodes"]), len(graph["nodes"]))

    def test_triple_validation(self):
        topics = {"ค่าจ้าง"}
        items = [{"subject": "นายจ้าง", "subject_type": "Actor", "relation": "IMPOSES_DUTY", "object": "จ่ายค่าจ้าง", "object_type": "Duty"},
                 {"subject": "x", "subject_type": "Actor", "relation": "BAD", "object": "y", "object_type": "Topic"},
                 {"subject": "x", "subject_type": "Actor", "relation": "ABOUT", "object": "ค่าจ้าง", "object_type": "Topic"}]
        self.assertEqual(len(validate_triples(items, topics)), 2)

    def test_taxonomy_has_topics_and_urls(self):
        path = Path("data/curated/topic_agency_evidence_form_step.csv")
        with path.open(encoding="utf-8-sig") as stream:
            rows = list(csv.DictReader(stream))
        self.assertGreaterEqual(len(load_topics(path)), 30)
        self.assertTrue(all(row["source_url"].startswith("http") for row in rows))

if __name__ == "__main__": unittest.main()
