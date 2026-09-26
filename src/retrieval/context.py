"""Section Card aggregation for hybrid mode (PLAN.md §5 point 4): one card
per section, graph-enriched with PENALIZED_BY/DEFINES/ABOUT->Topic-> Agency/
Evidence/Form/Step neighbors pulled straight from data/graph.json (the same
graph Day 2's merge_triples_and_topics() built), deduped, truncated to a
provider-aware char budget without ever cutting a card in half.

Takes plain section dicts (the shape RAGEngine.expand() already produces —
section_key/law_id/law_name/chapter/section_no/status/source_url/text) and a
plain {"nodes": [...], "edges": [...]} graph dict — no file I/O here, so
this is unit-testable with small in-memory fixtures (tests/test_context.py).
"""


def _neighbors(nodes_by_id, edges, node_id, edge_type, direction):
    out = []
    for e in edges:
        if e["type"] != edge_type:
            continue
        if direction == "out" and e["source"] == node_id:
            out.append(nodes_by_id.get(e["target"]))
        elif direction == "in" and e["target"] == node_id:
            out.append(nodes_by_id.get(e["source"]))
    return [n for n in out if n is not None]


def _label(node):
    return node.get("name") or f'มาตรา {node.get("section_no", "")}'


def _section_card(section, nodes_by_id, edges):
    section_id = f'Section:{section["law_id"]}:{section["section_no"]}'
    chapter = section.get("chapter")
    header = f'มาตรา {section["section_no"]}' + (f' ({chapter})' if chapter else "")

    lines = [f'[{header} | {section.get("law_name", "")} | {section.get("status", "")} | {section.get("source_url", "")}]']
    lines.append(f'ตัวบท: {section["text"]}')

    penalties = _neighbors(nodes_by_id, edges, section_id, "PENALIZED_BY", "out") + \
        _neighbors(nodes_by_id, edges, section_id, "PENALIZED_BY", "in")
    if penalties:
        lines.append("บทลงโทษที่เกี่ยวข้อง: " + ", ".join(dict.fromkeys(_label(p) for p in penalties)))

    terms = _neighbors(nodes_by_id, edges, section_id, "DEFINES", "out")
    if terms:
        lines.append("นิยามที่ใช้: " + ", ".join(f'"{_label(t)}"' for t in terms))

    for topic in _neighbors(nodes_by_id, edges, section_id, "ABOUT", "out"):
        agencies = _neighbors(nodes_by_id, edges, topic["id"], "HANDLED_BY", "out")
        evidences = _neighbors(nodes_by_id, edges, topic["id"], "REQUIRES_EVIDENCE", "out")
        forms = _neighbors(nodes_by_id, edges, topic["id"], "USES_FORM", "out")
        steps = _neighbors(nodes_by_id, edges, topic["id"], "HAS_STEP", "out")
        if agencies:
            lines.append("หน่วยงาน: " + ", ".join(_label(a) for a in agencies))
        if evidences:
            lines.append("หลักฐาน: " + ", ".join(_label(e) for e in evidences))
        if forms:
            lines.append("แบบฟอร์ม: " + ", ".join(_label(f) for f in forms))
        if steps:
            lines.append("ขั้นตอน: " + ", ".join(_label(s) for s in steps))

    return "\n".join(lines)


def build_section_cards(sections, graph, budget_chars):
    """One Section Card per distinct section (deduped by section_key),
    ordered as given, truncated to `budget_chars` the same way
    RAGEngine.expand() already truncates (always keep at least the first
    card even if it alone exceeds budget — better one oversized card than
    an empty context)."""
    nodes_by_id = {n["id"]: n for n in graph.get("nodes", [])}
    edges = graph.get("edges", [])

    seen, cards, used = set(), [], 0
    for section in sections:
        key = section.get("section_key") or f'{section["law_id"]}-s{section["section_no"]}'
        if key in seen:
            continue
        card = _section_card(section, nodes_by_id, edges)
        if cards and used + len(card) > budget_chars:
            continue
        seen.add(key)
        used += len(card)
        cards.append(card)
    return cards
