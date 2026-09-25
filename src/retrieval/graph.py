"""Safe graph retrieval with fixed Cypher templates and offline fallback."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

SECTION_RE = re.compile(r"มาตรา\s*([๐-๙0-9]+(?:\s*/\s*[๐-๙0-9]+)?)")
THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
QUERY_TYPES = {"lookup", "procedure", "penalty", "definition", "aggregation"}

QUERY_TYPE_KEYWORDS = {
    "procedure": ("ทำอย่างไร", "ขั้นตอน", "หลักฐาน", "ร้องเรียน", "ยื่น"),
    "penalty": ("โทษ", "ปรับ", "จำคุก", "ฝ่าฝืน", "ไม่จ่าย"),
    "definition": ("หมายถึง", "นิยาม", "คืออะไร", "ความหมาย"),
    "aggregation": ("มีสิทธิ", "ประเภทใดบ้าง", "ทั้งหมด", "รวม"),
    "lookup": ("มาตรา",),
}

CYpher_TEMPLATES = {
    "lookup": "MATCH (s:Section) WHERE s.section_no IN $section_nos OPTIONAL MATCH p=(s)-[:REFERS_TO|PENALIZED_BY*1..1]->(related:Section) RETURN s, p, related LIMIT $top_k",
    "procedure": "MATCH (t:Topic)<-[:ABOUT]-(s:Section) WHERE t.name IN $topics OPTIONAL MATCH p=(t)-[:HANDLED_BY|REQUIRES_EVIDENCE|USES_FORM|HAS_STEP*1..2]-(n) RETURN s, p, n LIMIT $top_k",
    "penalty": "MATCH (s:Section)-[r:PENALIZED_BY]->(p:Section) WHERE s.section_no IN $section_nos OR p.section_no IN $section_nos RETURN s, r, p LIMIT $top_k",
    "definition": "MATCH (s:Section)-[:DEFINES]->(t:Term) WHERE t.name IN $terms OR any(x IN $terms WHERE t.name CONTAINS x) RETURN s, t LIMIT $top_k",
    "aggregation": "MATCH (t:Topic)<-[:ABOUT]-(s:Section)-[:GRANTS_RIGHT]->(r:Right) WHERE t.name IN $topics RETURN s, t, r LIMIT $top_k",
}

@dataclass
class GraphResult:
    query_type: str
    sections: list[dict]
    paths: list[dict]
    triples: list[dict]
    entities: list[dict]
    fallback: bool = False

    def as_dict(self) -> dict:
        return {"query_type": self.query_type, "sections": self.sections, "paths": self.paths, "triples": self.triples, "entities": self.entities, "fallback": self.fallback}

def normalize_digits(value: str) -> str:
    return value.translate(THAI_DIGITS).replace(" ", "")

def infer_query_type(query: str) -> str:
    for query_type in ("procedure", "penalty", "definition", "aggregation", "lookup"):
        if any(word in query for word in QUERY_TYPE_KEYWORDS[query_type]): return query_type
    return "lookup"

class GraphRetriever:
    def __init__(self, driver=None, graph: dict | None = None, aliases: dict[str, str] | None = None):
        self.driver = driver
        self.graph = graph or {"nodes": [], "edges": []}
        self.aliases = {key.casefold(): value for key, value in (aliases or {}).items()}
        self._nodes = {node["id"]: node for node in self.graph.get("nodes", [])}
        self._edges = self.graph.get("edges", [])

    @classmethod
    def from_json(cls, graph_file: str | Path, aliases: dict[str, str] | None = None):
        import json
        return cls(graph=json.loads(Path(graph_file).read_text(encoding="utf-8")), aliases=aliases)

    def link_entities(self, query: str) -> dict:
        sections = [normalize_digits(x) for x in SECTION_RE.findall(query)]
        topics = []
        lowered = query.casefold()
        for alias, topic in self.aliases.items():
            if alias in lowered and topic not in topics: topics.append(topic)
        return {"section_nos": sections, "topics": topics, "terms": topics, "query_type": infer_query_type(query)}

    def _offline(self, entities: dict, top_k: int) -> GraphResult:
        wanted = set(entities["section_nos"])
        section_nodes = [n for n in self._nodes.values() if n.get("label") == "Section" and (not wanted or str(n.get("section_no")) in wanted)]
        if not wanted and entities["topics"]:
            section_nodes = [n for n in self._nodes.values() if n.get("label") == "Section"]
        section_nodes = section_nodes[:top_k]
        ids = {n["id"] for n in section_nodes}
        edges = [e for e in self._edges if e["source"] in ids or e["target"] in ids][:top_k]
        triples = [{"subject": e["source"], "relation": e["type"], "object": e["target"]} for e in edges]
        return GraphResult(entities["query_type"], section_nodes, edges, triples, [{"type": "Section", "value": x} for x in entities["section_nos"]], True)

    def search(self, query: str, query_type: str | None = None, top_k: int = 5) -> dict:
        entities = self.link_entities(query)
        if query_type in QUERY_TYPES: entities["query_type"] = query_type
        selected = entities["query_type"]
        if self.driver is None: return self._offline(entities, top_k).as_dict()
        params = {"section_nos": entities["section_nos"], "topics": entities["topics"], "terms": entities["terms"], "top_k": top_k}
        sections, paths, triples = [], [], []
        try:
            with self.driver.session() as session:
                for record in session.run(CYpher_TEMPLATES[selected], **params):
                    for key in ("s", "related", "t", "r"):
                        value = record.get(key)
                        if value and key not in ("r",): sections.append(dict(value))
                    path = record.get("p")
                    if path: paths.append({"length": len(path.relationships), "types": [x.type for x in path.relationships]})
            unique = {str(item.get("id", item.get("section_no", item))): item for item in sections}
            return GraphResult(selected, list(unique.values())[:top_k], paths[:top_k], triples, [{"type": "Section", "value": x} for x in entities["section_nos"]]).as_dict()
        except Exception:
            return self._offline(entities, top_k).as_dict()

def load_aliases(csv_file: str | Path) -> dict[str, str]:
    import csv
    aliases = {}
    with open(csv_file, encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            topic = row.get("topic", "").strip()
            if topic: aliases[topic] = topic
    return aliases
