import unittest

from src.retrieval.fusion import graph_seeded_expand, hybrid_search
from src.retrieval.router import RouteDecision


class _StubRetriever:
    """Fakes just enough of Retriever's surface for fusion.py: .chunks and
    .search_raw(). No real Chroma/BM25/model I/O."""

    def __init__(self, chunks, dense_ids, word_ids, gram_ids):
        self.chunks = chunks
        self._dense_ids, self._word_ids, self._gram_ids = dense_ids, word_ids, gram_ids

    def search_raw(self, query, pool=None):
        return self._dense_ids, self._word_ids, self._gram_ids, 0.9


class _StubGraphRetriever:
    def __init__(self, sections):
        self._sections = sections

    def search(self, query, top_k=None):
        return {"sections": self._sections}


def chunk(chunk_id, section_no, law_id="LAW", text="text"):
    return {"chunk_id": chunk_id, "law_id": law_id, "section_no": section_no, "text": text}


CHUNKS = {
    "c1": chunk("c1", "1"),
    "c2": chunk("c2", "2"),
    "c3": chunk("c3", "3"),
}


class HybridSearchTests(unittest.TestCase):
    def test_graph_leg_wins_when_graph_weight_dominates(self):
        retriever = _StubRetriever(CHUNKS, dense_ids=["c1"], word_ids=["c2"], gram_ids=[])
        graph_retriever = _StubGraphRetriever([{"law_id": "LAW", "section_no": "3"}])
        route = RouteDecision(query_type="lookup", alpha_dense=0.05, alpha_bm25=0.05, alpha_graph=0.9)
        hits = hybrid_search(retriever, graph_retriever, "q", route)
        self.assertEqual(hits[0]["chunk_id"], "c3")

    def test_dense_leg_wins_when_dense_weight_dominates(self):
        retriever = _StubRetriever(CHUNKS, dense_ids=["c1"], word_ids=["c2"], gram_ids=[])
        graph_retriever = _StubGraphRetriever([{"law_id": "LAW", "section_no": "3"}])
        route = RouteDecision(query_type="general", alpha_dense=0.9, alpha_bm25=0.05, alpha_graph=0.05)
        hits = hybrid_search(retriever, graph_retriever, "q", route)
        self.assertEqual(hits[0]["chunk_id"], "c1")

    def test_degrades_to_dense_bm25_only_when_graph_retriever_missing(self):
        retriever = _StubRetriever(CHUNKS, dense_ids=["c1"], word_ids=["c2"], gram_ids=[])
        route = RouteDecision(query_type="lookup", alpha_dense=0.2, alpha_bm25=0.4, alpha_graph=0.4)
        hits = hybrid_search(retriever, None, "q", route)  # graph_retriever=None -> Neo4j-down-equivalent
        self.assertEqual({h["chunk_id"] for h in hits}, {"c1", "c2"})

    def test_degrades_cleanly_when_graph_search_returns_no_sections(self):
        retriever = _StubRetriever(CHUNKS, dense_ids=["c1"], word_ids=["c2"], gram_ids=[])
        graph_retriever = _StubGraphRetriever([])  # empty offline graph
        route = RouteDecision(query_type="lookup", alpha_dense=0.2, alpha_bm25=0.4, alpha_graph=0.4)
        hits = hybrid_search(retriever, graph_retriever, "q", route)
        self.assertEqual({h["chunk_id"] for h in hits}, {"c1", "c2"})


GRAPH = {
    "nodes": [
        {"id": "Section:LAW:1", "label": "Section", "law_id": "LAW", "section_no": "1"},
        {"id": "Section:LAW:2", "label": "Section", "law_id": "LAW", "section_no": "2"},
        {"id": "Term:LAW:x", "label": "Term", "name": "x"},
    ],
    "edges": [
        {"source": "Section:LAW:1", "type": "REFERS_TO", "target": "Section:LAW:2"},
        {"source": "Section:LAW:1", "type": "DEFINES", "target": "Term:LAW:x"},  # not an expand edge type
    ],
}


class GraphSeededExpandTests(unittest.TestCase):
    def test_adds_a_new_chunk_via_refers_to(self):
        retriever = _StubRetriever(CHUNKS, [], [], [])
        expanded, paths = graph_seeded_expand([CHUNKS["c1"]], GRAPH, retriever)
        self.assertIn("c2", {h["chunk_id"] for h in expanded})
        self.assertEqual(paths, [{"from": "Section:LAW:1", "type": "REFERS_TO", "to": "Section:LAW:2"}])

    def test_never_duplicates_an_already_present_chunk(self):
        retriever = _StubRetriever(CHUNKS, [], [], [])
        expanded, paths = graph_seeded_expand([CHUNKS["c1"], CHUNKS["c2"]], GRAPH, retriever)
        ids = [h["chunk_id"] for h in expanded]
        self.assertEqual(ids, ["c1", "c2"])  # c2 already present -> no duplicate append
        self.assertEqual(paths, [])

    def test_noop_on_empty_graph_neo4j_down_equivalent(self):
        retriever = _StubRetriever(CHUNKS, [], [], [])
        expanded, paths = graph_seeded_expand([CHUNKS["c1"]], {"nodes": [], "edges": []}, retriever)
        self.assertEqual(expanded, [CHUNKS["c1"]])
        self.assertEqual(paths, [])

    def test_ignores_non_expand_edge_types(self):
        retriever = _StubRetriever(CHUNKS, [], [], [])
        # DEFINES edge from Section:LAW:1 must not pull in the Term node as a "chunk"
        expanded, _paths = graph_seeded_expand([CHUNKS["c1"]], GRAPH, retriever)
        self.assertTrue(all("chunk_id" in h for h in expanded))


if __name__ == "__main__":
    unittest.main()
