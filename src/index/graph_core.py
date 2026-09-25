"""Deterministic graph builder. Produces data before optional Neo4j write."""
from __future__ import annotations
import argparse, json, os, re
from pathlib import Path

def _key(kind: str, value: str) -> str: return f"{kind}:{value}"

def build_graph(chunks: list[dict]) -> dict:
    nodes, edges, seen = [], [], set()
    laws, chapters, sections = {}, {}, {}
    def node(kind, key, props):
        identity = _key(kind, key)
        if identity not in {x["id"] for x in nodes}: nodes.append({"id": identity, "label": kind, **props})
        return identity
    def edge(source, relation, target, props=None):
        value = (source, relation, target)
        if value not in seen: edges.append({"source": source, "type": relation, "target": target, **(props or {})}); seen.add(value)
    for chunk in chunks:
        law_id, chapter, section_no = chunk["law_id"], chunk.get("chapter", "ไม่ระบุหมวด"), str(chunk["section_no"])
        law = laws.setdefault(law_id, node("Law", law_id, {"law_id": law_id, "law_name": chunk.get("law_name", "")}))
        chapter_id = chapters.setdefault((law_id, chapter), node("Chapter", f"{law_id}:{chapter}", {"name": chapter, "law_id": law_id}))
        section_id = sections.setdefault((law_id, section_no), node("Section", f"{law_id}:{section_no}", {"law_id": law_id, "section_no": section_no, "text": chunk.get("text", ""), "status": chunk.get("status")}))
        edge(law, "HAS_CHAPTER", chapter_id); edge(chapter_id, "HAS_SECTION", section_id)
        for ref in chunk.get("refs_out", []):
            target = sections.get((law_id, str(ref))) or node("Section", f"{law_id}:{ref}", {"law_id": law_id, "section_no": str(ref)})
            sections.setdefault((law_id, str(ref)), target); edge(section_id, "REFERS_TO", target)
        for ref in re.findall(r"(?:ฝ่าฝืน|ตาม|มาตรา)\s*([๐-๙0-9]+(?:\s*/\s*[๐-๙0-9]+)?)", chunk.get("text", "")):
            ref = ref.translate(str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789"))
            if "โทษ" in chunk.get("text", "") or "ระวาง" in chunk.get("text", ""):
                target = sections.get((law_id, ref)) or node("Section", f"{law_id}:{ref}", {"law_id": law_id, "section_no": ref})
                sections.setdefault((law_id, ref), target); edge(target, "PENALIZED_BY", section_id)
        for term in re.findall(r"(?:คำว่า\s*)?[“\"]([^”\"]+)[”\"]\s*หมายความว่า", chunk.get("text", "")):
            # "คำว่า" prefix is optional: this statute's actual style is just
            # "TERM" หมายความว่า ... (no "คำว่า" before the quote) — the stricter
            # prefix-required pattern matched 0 sections despite ~23 defined
            # terms in section 5 alone.
            term_id = node("Term", f"{law_id}:{term}", {"name": term}); edge(section_id, "DEFINES", term_id)
    return {"nodes": nodes, "edges": edges}

def _merge_node(graph: dict, node_ids: set, kind: str, key: str, props: dict) -> str:
    identity = _key(kind, key)
    if identity not in node_ids:
        graph["nodes"].append({"id": identity, "label": kind, **props}); node_ids.add(identity)
    return identity

def _merge_edge(graph: dict, seen: set, source: str, relation: str, target: str) -> None:
    value = (source, relation, target)
    if value not in seen:
        graph["edges"].append({"source": source, "type": relation, "target": target}); seen.add(value)

def merge_triples_and_topics(graph: dict, triples: list[dict], topic_rows: list[dict], law_id: str) -> dict:
    """Fold the human-reviewed LLM triples (PLAN.md §4.3 point 2) and the
    curated Topic->Agency/Evidence/Form/Step CSV (§4.3 point 4) into the
    deterministic Law/Chapter/Section graph, in place, to reach PLAN.md
    §4.2's full node/edge set. `triples` should already be filtered to
    reviewer-approved rows (see doc/data_quality_report.md) — this function
    doesn't filter itself, so it merges whatever it's given.

    Design note: review found 0/14 BINDS and 0/3 HELD_BY triples valid — the
    extractor put the Actor's own name in the subject field but mislabeled
    subject_type as Duty/Right (see doc/data_quality_report.md for the full
    breakdown), so those two relations aren't sourced from their own
    (entirely-rejected) rows. Instead HELD_BY/BINDS are reconstructed from
    the *subject* of each approved GRANTS_RIGHT/IMPOSES_DUTY triple, which
    review did confirm names the correct Actor for that section — this
    recovers PLAN §4.2's intended topology, (Section)-[:GRANTS_RIGHT]->
    (Right)-[:HELD_BY]->(Actor) and (Section)-[:IMPOSES_DUTY]->(Duty)-
    [:BINDS]->(Actor), from data that actually passed review.
    """
    node_ids = {n["id"] for n in graph["nodes"]}
    seen = {(e["source"], e["type"], e["target"]) for e in graph["edges"]}
    node = lambda kind, key, props: _merge_node(graph, node_ids, kind, key, props)
    edge = lambda source, relation, target: _merge_edge(graph, seen, source, relation, target)

    for t in triples:
        section_id = node("Section", f"{law_id}:{t['section_no']}", {"law_id": law_id, "section_no": t["section_no"]})
        object_id = node(t["object_type"], t["object"], {"name": t["object"]})
        relation = t["relation"]
        if relation == "ABOUT":
            # subject here is the fallback extractor's generic placeholder
            # ("กฎหมายแรงงาน"), not a real Actor — not part of PLAN §4.2's
            # ABOUT topology (Section->Topic only), so don't create a node
            # for it; doing so left one orphan Actor node in earlier runs.
            edge(section_id, "ABOUT", object_id)
        elif relation == "GRANTS_RIGHT":
            subject_id = node(t["subject_type"], t["subject"], {"name": t["subject"]})
            edge(section_id, "GRANTS_RIGHT", object_id); edge(object_id, "HELD_BY", subject_id)
        elif relation == "IMPOSES_DUTY":
            subject_id = node(t["subject_type"], t["subject"], {"name": t["subject"]})
            edge(section_id, "IMPOSES_DUTY", object_id); edge(object_id, "BINDS", subject_id)
        elif relation == "HAS_PENALTY":
            edge(section_id, "HAS_PENALTY", object_id)
        # BINDS/HELD_BY triples themselves are not merged directly — see docstring.

    for row in topic_rows:
        topic = (row.get("topic") or "").strip()
        if not topic:
            continue
        topic_id = node("Topic", topic, {"name": topic})
        for kind, col, relation in (
            ("Agency", "agency", "HANDLED_BY"),
            ("Evidence", "evidence", "REQUIRES_EVIDENCE"),
            ("Form", "form", "USES_FORM"),
            ("Step", "step", "HAS_STEP"),
        ):
            value = (row.get(col) or "").strip()
            if not value:
                continue
            value_id = node(kind, value, {"name": value, "source_url": row.get("source_url", "")})
            edge(topic_id, relation, value_id)

    return graph

def write_json(graph: dict, output_file: str | Path) -> None:
    target = Path(output_file); target.parent.mkdir(parents=True, exist_ok=True); target.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def cypher_statements(graph: dict) -> list[tuple[str, dict]]:
    statements = []
    for node in graph["nodes"]:
        statements.append((f"MERGE (n:{node['label']} {{id: $id}}) SET n += $props", {"id": node["id"], "props": {k:v for k,v in node.items() if k not in ("id", "label")}}))
    for edge in graph["edges"]:
        statements.append(("MATCH (a {id: $source}), (b {id: $target}) MERGE (a)-[r:" + edge["type"] + "]->(b) SET r += $props", {"source": edge["source"], "target": edge["target"], "props": {k:v for k,v in edge.items() if k not in ("source", "type", "target")}}))
    return statements

def write_to_neo4j(driver, graph: dict) -> None:
    with driver.session() as session:
        for query, params in cypher_statements(graph): session.run(query, **params)

def _load_jsonl(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]

def _load_approved_triples(triples_file: str | Path, review_file: str | Path | None) -> list[dict]:
    """All triples if no review file given, else only rows the CSV marks approved=="yes"."""
    triples = _load_jsonl(triples_file)
    if not review_file or not Path(review_file).exists():
        return triples
    import csv
    with open(review_file, encoding="utf-8-sig", newline="") as stream:
        approved_ids = {int(row["review_id"]) for row in csv.DictReader(stream) if row.get("approved", "").strip().lower() == "yes"}
    return [t for i, t in enumerate(triples, 1) if i in approved_ids]

def _load_topic_rows(topics_file: str | Path) -> list[dict]:
    import csv
    with open(topics_file, encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("input_file")
    parser.add_argument("--output", default="data/graph.json")
    parser.add_argument("--triples", default="data/triples.jsonl")
    parser.add_argument("--review", default="data/curated/triples_review_approved.csv")
    parser.add_argument("--topics", default="data/curated/topic_agency_evidence_form_step.csv")
    parser.add_argument("--law-id")
    parser.add_argument("--skip-merge", action="store_true", help="deterministic Law/Chapter/Section graph only")
    parser.add_argument("--neo4j", action="store_true")
    args = parser.parse_args()

    chunks = _load_jsonl(args.input_file)
    graph = build_graph(chunks)

    if not args.skip_merge:
        law_id = args.law_id or (chunks[0]["law_id"] if chunks else "")
        triples = _load_approved_triples(args.triples, args.review) if Path(args.triples).exists() else []
        topic_rows = _load_topic_rows(args.topics) if Path(args.topics).exists() else []
        merge_triples_and_topics(graph, triples, topic_rows, law_id)

    write_json(graph, args.output)
    if args.neo4j:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(os.getenv("NEO4J_URI", "bolt://localhost:7687"), auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "changeme")))
        try: write_to_neo4j(driver, graph)
        finally: driver.close()

    by_label = {}
    for n in graph["nodes"]: by_label[n["label"]] = by_label.get(n["label"], 0) + 1
    by_type = {}
    for e in graph["edges"]: by_type[e["type"]] = by_type.get(e["type"], 0) + 1
    print(f"nodes={len(graph['nodes'])} edges={len(graph['edges'])}")
    print("nodes by label:", by_label)
    print("edges by type:", by_type)
