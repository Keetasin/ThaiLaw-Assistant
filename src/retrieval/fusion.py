"""Hybrid fusion (PLAN.md §5): weighted RRF across dense + BM25-word +
BM25-3gram + graph, using the router's per-query-type alpha weights, then
graph-seeded expansion from the top fused hits.

Both functions here are pure given already-constructed Retriever/
GraphRetriever instances and a plain graph dict — no I/O of their own — so
they're unit-testable with small in-memory fixtures (see
tests/test_fusion.py).
"""
from src import config
from src.retrieval.retriever import rrf


def _section_to_chunk_ids(retriever):
    idx = {}
    for chunk_id, chunk in retriever.chunks.items():
        idx.setdefault((chunk["law_id"], str(chunk["section_no"])), []).append(chunk_id)
    return idx


def _graph_chunk_ids(retriever, graph_retriever, query, pool, section_idx):
    result = graph_retriever.search(query, top_k=pool)
    chunk_ids = []
    for sec in result.get("sections", []):
        key = (sec.get("law_id"), str(sec.get("section_no", "")))
        for cid in section_idx.get(key, []):
            if cid not in chunk_ids:
                chunk_ids.append(cid)
    return chunk_ids


def hybrid_search(retriever, graph_retriever, query, route, pool=config.POOL, fuse_k=config.FUSE_K):
    """4-way weighted RRF: dense/bm25-word/bm25-gram/graph, weighted by
    `route` (a router.RouteDecision) rather than the fixed 2.0/1.0/1.0
    weights `Retriever.search()` uses for dense-only mode. BM25's single
    `alpha_bm25` weight is split evenly across the word/gram legs so the
    two BM25 variants keep the same relative treatment as dense-only mode.
    Falls back to a dense+bm25-only result set cleanly if the graph leg
    returns nothing (offline graph missing/empty, or graph_retriever=None)
    — this is what makes a Neo4j-down-equivalent case degrade gracefully
    rather than error."""
    dense_ids, word_ids, gram_ids, _cosine = retriever.search_raw(query, pool)
    section_idx = _section_to_chunk_ids(retriever)
    graph_ids = _graph_chunk_ids(retriever, graph_retriever, query, pool, section_idx) if graph_retriever else []

    fused = rrf([
        (dense_ids, route.alpha_dense),
        (word_ids, route.alpha_bm25 / 2),
        (gram_ids, route.alpha_bm25 / 2),
        (graph_ids, route.alpha_graph),
    ], k=fuse_k)
    hits = [retriever.chunks[cid] for cid, _ in fused if cid in retriever.chunks]
    return hits


_EXPAND_EDGE_TYPES = ("REFERS_TO", "PENALIZED_BY")


def graph_seeded_expand(hits, graph, retriever, seed_n=3, max_new=5):
    """Walk `data/graph.json`'s REFERS_TO/PENALIZED_BY edges 1 hop out from
    each of the top `seed_n` fused hits' Section node, and append any
    chunk not already in `hits` (deduped by chunk_id), up to `max_new`
    extra chunks (PLAN.md §5 point 3). `graph` is a plain
    {"nodes": [...], "edges": [...]} dict — pass GraphRetriever.graph or an
    empty {"nodes": [], "edges": []} directly, no file I/O here.

    Returns (expanded_hits, graph_paths) — graph_paths is a list of
    {"from", "type", "to"} dicts for /debug and doc/case-study traces.
    """
    nodes_by_id = {n["id"]: n for n in graph.get("nodes", [])}
    section_idx = _section_to_chunk_ids(retriever)
    seen_chunk_ids = {h["chunk_id"] for h in hits}
    expanded = list(hits)
    paths = []

    for seed in hits[:seed_n]:
        section_node_id = f'Section:{seed["law_id"]}:{seed["section_no"]}'
        if section_node_id not in nodes_by_id:
            continue
        for edge in graph.get("edges", []):
            if len(expanded) - len(hits) >= max_new:
                break
            if edge["type"] not in _EXPAND_EDGE_TYPES:
                continue
            if edge["source"] == section_node_id:
                neighbor_id = edge["target"]
            elif edge["target"] == section_node_id:
                neighbor_id = edge["source"]
            else:
                continue
            neighbor = nodes_by_id.get(neighbor_id)
            if not neighbor or neighbor.get("label") != "Section":
                continue
            key = (neighbor.get("law_id"), str(neighbor.get("section_no", "")))
            for cid in section_idx.get(key, []):
                if cid in seen_chunk_ids or cid not in retriever.chunks:
                    continue
                seen_chunk_ids.add(cid)
                expanded.append(retriever.chunks[cid])
                paths.append({"from": section_node_id, "type": edge["type"], "to": neighbor_id})

    return expanded, paths
