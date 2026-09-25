import json
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).parents[1]

# PLAN.md §8.1's target distribution for the combined 50-question gold set.
EXPECTED_CATEGORY_COUNTS = Counter({
    "lookup": 8, "definition": 6, "single_hop": 10, "multi_hop": 10,
    "procedure": 8, "aggregation": 4, "out_of_scope": 4,
})
REQUIRED_FIELDS = {"id", "question", "category", "gold_sections", "key_points", "gold_agency", "expected_query_type"}


def _load(path):
    return [json.loads(line) for line in (ROOT / path).read_text(encoding="utf-8").splitlines() if line.strip()]


class CombinedTestsetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = _load("eval/testset.jsonl")
        cls.chunk_ids = {json.loads(line)["chunk_id"] for line in (ROOT / "data/chunks.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()}

    def test_has_50_rows(self):
        self.assertEqual(len(self.rows), 50)

    def test_no_id_collisions(self):
        ids = [r["id"] for r in self.rows]
        self.assertEqual(len(ids), len(set(ids)))

    def test_matches_plan_8_1_category_distribution(self):
        self.assertEqual(Counter(r["category"] for r in self.rows), EXPECTED_CATEGORY_COUNTS)

    def test_every_row_has_required_fields(self):
        for row in self.rows:
            self.assertTrue(REQUIRED_FIELDS.issubset(row.keys()), row.get("id"))

    def test_every_gold_section_chunk_id_exists(self):
        for row in self.rows:
            for chunk_id in row["gold_sections"]:
                self.assertIn(chunk_id, self.chunk_ids, f'{row["id"]}: {chunk_id} not in data/chunks.jsonl')

    def test_out_of_scope_rows_have_no_gold_sections(self):
        for row in self.rows:
            if row["category"] == "out_of_scope":
                self.assertEqual(row["gold_sections"], [])


class PerSourceTestsetTests(unittest.TestCase):
    """A and B's individual 25-question files, checked separately so a
    regression in one doesn't hide behind the combined file's totals."""

    def test_a_and_b_each_have_25_rows_covering_all_7_categories(self):
        for path in ("eval/testset_a.jsonl", "eval/testset_b.jsonl"):
            rows = _load(path)
            self.assertEqual(len(rows), 25, path)
            self.assertEqual(set(r["category"] for r in rows), set(EXPECTED_CATEGORY_COUNTS), path)

    def test_a_and_b_ids_are_prefixed_by_source(self):
        for path, prefix in (("eval/testset_a.jsonl", "A-"), ("eval/testset_b.jsonl", "B-")):
            for row in _load(path):
                self.assertTrue(row["id"].startswith(prefix), row["id"])


if __name__ == "__main__":
    unittest.main()
