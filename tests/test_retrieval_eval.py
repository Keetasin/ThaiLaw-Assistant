import tempfile
import unittest
from pathlib import Path

from eval.run_retrieval import CorpusBackend, Neo4jBackend, metrics, run, run_tuning
from src.index.build_bm25 import build as build_bm25


class RetrievalEvaluationTests(unittest.TestCase):
    def setUp(self):
        chunks = {
            "LPA-s1-p1": {"chunk_id": "LPA-s1-p1", "section_no": "1", "text": "มาตรา 1 ค่าจ้างและสิทธิของลูกจ้าง", "refs_out": ["2"]},
            "LPA-s2-p1": {"chunk_id": "LPA-s2-p1", "section_no": "2", "text": "มาตรา 2 บทลงโทษค่าจ้าง", "refs_out": []},
        }
        self.backend = CorpusBackend(chunks, {"edges": [{"source": "LPA-s1-p1", "target": "LPA-s2-p1"}]})

    def test_metrics(self):
        result = metrics(["LPA-s2-p1", "LPA-s1-p1"], ["LPA-s1-p1"])
        self.assertEqual(result["hit_at_1"], 0.0)
        self.assertEqual(result["mrr"], 0.5)
        self.assertEqual(result["recall_at_5"], 1.0)

    def test_configs_and_csv_outputs(self):
        rows = [{"id": "A-1", "category": "lookup", "question": "มาตรา 1 ว่าด้วยอะไร", "gold_sections": ["LPA-s1-p1"]}]
        with tempfile.TemporaryDirectory() as directory:
            result = run(self.backend, rows, output_dir=Path(directory))
            self.assertEqual({row["config"] for row in result}, {"D", "D+R", "G", "H1", "H2", "H3", "H4", "H5"})
            self.assertTrue((Path(directory) / "retrieval_H5.csv").exists())

    def test_tuning_covers_all_dimensions(self):
        rows = [{"id": "A-1", "category": "lookup", "question": "มาตรา 1", "gold_sections": ["LPA-s1-p1"]}]
        with tempfile.TemporaryDirectory() as directory:
            path = run_tuning(self.backend, rows, Path(directory))
            with path.open(encoding="utf-8") as stream:
                self.assertEqual(sum(1 for _ in stream) - 1, 3 * 3 * 2 * 2)

    def test_neo4j_backend_maps_section_and_related_rows(self):
        chunks = {key.replace("LPA-", "LPA2541-"): value for key, value in self.backend.chunks.items()}
        backend = Neo4jBackend(chunks, "bolt://localhost:7687", "user", "password")
        backend._query = lambda _statement, _parameters: [["1", ["2"]]]
        self.assertEqual(backend.graph_search("มาตรา 1 ว่าด้วยอะไร"), [("LPA2541-s1-p1", 1.0), ("LPA2541-s2-p1", 0.8)])

    def test_bm25_builder_writes_both_indexes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = build_bm25(list(self.backend.chunks.values()), Path(directory) / "bm25.pkl")
            self.assertTrue(path.exists())
            self.assertGreater(path.stat().st_size, 0)


if __name__ == "__main__": unittest.main()
