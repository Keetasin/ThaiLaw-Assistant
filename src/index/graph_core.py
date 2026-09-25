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
        for term in re.findall(r"คำว่า\s*[“\"]([^”\"]+)[”\"]\s*หมายความว่า", chunk.get("text", "")):
            term_id = node("Term", f"{law_id}:{term}", {"name": term}); edge(section_id, "DEFINES", term_id)
    return {"nodes": nodes, "edges": edges}

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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("input_file"); parser.add_argument("--output", default="data/graph.json"); parser.add_argument("--neo4j", action="store_true"); args = parser.parse_args()
    chunks = [json.loads(line) for line in Path(args.input_file).read_text(encoding="utf-8").splitlines() if line.strip()]; graph = build_graph(chunks); write_json(graph, args.output)
    if args.neo4j:
        from neo4j import GraphDatabase
        driver = GraphDatabase.driver(os.getenv("NEO4J_URI", "bolt://localhost:7687"), auth=(os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "changeme")))
        try: write_to_neo4j(driver, graph)
        finally: driver.close()
    print(f"nodes={len(graph['nodes'])} edges={len(graph['edges'])}")
