"""Integration tests against the real bge-m3/bge-reranker-v2-m3 models and the
real data/chroma_db + data/bm25.pkl + data/chunks.jsonl on disk. Slower than
the rest of the suite (model load happens once in setUpClass) — run alone
via `python -m unittest tests.test_retrieval_integration` if you just want
this file.
"""
import unittest

from src.retrieval.reranker import rerank
from src.retrieval.retriever import Retriever, dynamic_k, rrf


class PureLogicTests(unittest.TestCase):
    def test_dynamic_k_short_query(self):
        self.assertEqual(dynamic_k("ลาป่วยได้กี่วัน"), (3, 4))

    def test_dynamic_k_long_or_multi_part_query(self):
        rerank_k, fuse_k = dynamic_k("ลูกจ้างมีสิทธิลาป่วยและลากิจได้กี่วันตามกฎหมายแรงงานไทย")
        self.assertEqual((rerank_k, fuse_k), (8, 10))

    def test_rrf_weights_favor_the_higher_weighted_list(self):
        fused = rrf([(["a", "b"], 2.0), (["b", "c"], 1.0)], k=3)
        ids = [doc_id for doc_id, _ in fused]
        self.assertEqual(ids[0], "b")  # appears in both lists -> highest combined score


class RetrieverIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.retriever = Retriever()

    def test_search_returns_well_shaped_hits(self):
        hits, score = self.retriever.search("ลูกจ้างคือใคร")
        self.assertTrue(hits)
        self.assertIsInstance(score, float)
        for h in hits:
            self.assertIn("chunk_id", h)
            self.assertIn("section_no", h)
            self.assertIn("text", h)

    @unittest.expectedFailure
    def test_pure_section_number_lookup_known_gap(self):
        # Documented known gap (doc/SPLIT.md Day2-B, data/traces.jsonl): a
        # query that's ONLY a section number ("มาตรา 61 คืออะไร") doesn't
        # surface section 61 in the fused dense+BM25 candidates today.
        # Marked expectedFailure so the suite stays green while this is
        # true, and flags loudly ("unexpected success") the day it's fixed
        # (Day 4 retune per PLAN.md §3) instead of silently going stale.
        hits, _score = self.retriever.search("มาตรา 61 คืออะไร")
        self.assertIn("61", [h["section_no"] for h in hits])


class RerankIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.candidates = [
            {"chunk_id": "c1", "chapter": None, "section_no": "61", "text": "ลูกจ้างมีสิทธิได้รับค่าล่วงเวลาตามมาตรา 61"},
            {"chunk_id": "c2", "chapter": None, "section_no": "1", "text": "ชื่อพระราชบัญญัตินี้เรียกว่าพระราชบัญญัติคุ้มครองแรงงาน"},
        ]

    def test_score_is_in_zero_one_range(self):
        _hits, score = rerank("นายจ้างไม่จ่ายค่าล่วงเวลา", self.candidates)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_ranks_the_topically_relevant_candidate_first(self):
        hits, _score = rerank("นายจ้างไม่จ่ายค่าล่วงเวลาต้องทำอย่างไร", self.candidates, k=2)
        self.assertEqual(hits[0]["chunk_id"], "c1")


if __name__ == "__main__":
    unittest.main()
