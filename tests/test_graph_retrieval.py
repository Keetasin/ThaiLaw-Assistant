import json
import unittest
from collections import Counter
from pathlib import Path

from src.retrieval.graph import CYpher_TEMPLATES, GraphRetriever, infer_query_type, load_aliases

ROOT = Path(__file__).parents[1]

class GraphRetrievalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.retriever = GraphRetriever.from_json(ROOT / "data/graph.json", load_aliases(ROOT / "data/curated/topic_agency_evidence_form_step.csv"))
        cls.rows = [json.loads(line) for line in (ROOT / "eval/testset_a.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        cls.chunk_ids = {json.loads(line)["chunk_id"] for line in (ROOT / "data/chunks.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()}

    def test_query_type_inference(self):
        self.assertEqual(infer_query_type("นายจ้างไม่จ่ายมีโทษอะไร"), "penalty")
        self.assertEqual(infer_query_type("ต้องใช้หลักฐานอะไร"), "procedure")
        self.assertEqual(infer_query_type("ค่าจ้างหมายถึงอะไร"), "definition")

    def test_section_linking_supports_thai_digits_and_slash(self):
        entities = self.retriever.link_entities("มาตรา ๔/๑ ว่าด้วยอะไร")
        self.assertEqual(entities["section_nos"], ["4/1"])

    def test_offline_lookup_returns_graph_result(self):
        result = self.retriever.search("มาตรา 61 ว่าด้วยอะไร")
        self.assertEqual(result["query_type"], "lookup")
        self.assertTrue(result["fallback"])
        self.assertTrue(result["sections"])

    def test_aggregation_query_expands_across_every_topic_in_the_category(self):
        # doc/report.md §3.5: "ลาประเภทใดบ้าง"-style queries don't name any
        # one topic alias, so link_entities' normal substring match finds
        # nothing -- AGGREGATION_ROOTS fans out to every topic starting with
        # a category root word ("ลา", "วันหยุด") instead. Also regresses the
        # top_k=5 truncation bug this uncovered (search() bumps top_k for
        # aggregation specifically, see graph.py).
        result = self.retriever.search("สิทธิวันหยุดของลูกจ้างมีประเภทใดบ้าง")
        secs = {s.get("section_no") for s in result["sections"]}
        self.assertEqual(result["query_type"], "aggregation")
        self.assertTrue({"28", "29", "30"}.issubset(secs))

    def test_templates_are_parameterized(self):
        self.assertEqual(set(CYpher_TEMPLATES), {"lookup", "procedure", "penalty", "definition", "aggregation"})
        self.assertTrue(all("$" in query for query in CYpher_TEMPLATES.values()))

    def test_testset_has_25_rows_and_expected_distribution(self):
        self.assertEqual(len(self.rows), 25)
        self.assertEqual(Counter(row["category"] for row in self.rows), Counter({"single_hop": 5, "multi_hop": 5, "procedure": 4, "lookup": 4, "definition": 3, "aggregation": 2, "out_of_scope": 2}))
        for row in self.rows:
            self.assertTrue(row["id"].startswith("A-"))
            for field in ("question", "category", "gold_sections", "key_points", "gold_agency", "expected_query_type"):
                self.assertIn(field, row)
            self.assertTrue(all(section in self.chunk_ids for section in row["gold_sections"]))

if __name__ == "__main__": unittest.main()
