"""MoE-style query router — Day 2 skeleton only (PLAN.md §5 point 1).

Classifies a query into one of the types below with a rule-based classifier
(regex section numbers + keyword lists), then looks up the default
{alpha_dense, alpha_bm25, alpha_graph} weight table from PLAN.md §5. Every
row already sums to 1.0 as designed, so no softmax step is needed here.

NOT wired into engine.py or graph retrieval yet — graph retrieval doesn't
exist until person A's Day 3 work (PLAN.md §11: D2 = "เริ่ม MoE router",
D3 = "Router + RRF + graph expansion"), so `alpha_graph` is structurally
present but has nothing to route to today. The full LLM-assisted classifier
PLAN.md describes ("rule + LLM ขนาดเล็ก") is also deferred — the rule-based
half fully covers what Day2's dense-only engine needs to classify against.
"""
import re
from typing import Literal

from pydantic import BaseModel, Field

QueryType = Literal[
    "lookup", "definition", "penalty", "procedure", "multi_hop", "general", "out_of_scope", "direct_llm",
]


class RouteDecision(BaseModel):
    query_type: QueryType
    alpha_dense: float = Field(ge=0.0, le=1.0)
    alpha_bm25: float = Field(ge=0.0, le=1.0)
    alpha_graph: float = Field(ge=0.0, le=1.0)


# PLAN.md §5 point 1 default table — every row already sums to 1.0.
_WEIGHTS = {
    "lookup": (0.2, 0.4, 0.4),
    "definition": (0.3, 0.2, 0.5),
    "penalty": (0.3, 0.1, 0.6),
    "procedure": (0.3, 0.1, 0.6),
    "multi_hop": (0.3, 0.1, 0.6),
    "general": (0.6, 0.3, 0.1),
    "out_of_scope": (0.0, 0.0, 0.0),
    "direct_llm": (0.0, 0.0, 0.0),
}

_SECTION_NO_RE = re.compile(r"มาตรา\s*[0-9]+(?:/[0-9]+)?")
_GREETING_RE = re.compile(r"^(สวัสดี|หวัดดี|ขอบคุณ|ขอบใจ|hi|hello|thanks?)\b", re.I)
_DEFINITION_KW = ("หมายความว่า", "นิยาม", "คือใคร", "คืออะไร")
_PENALTY_KW = ("โทษ", "ระวางโทษ", "ผิดกฎหมาย", "ผิดทางพินัย", "ปรับเท่าไร", "ปรับเท่าไหร่")
_PROCEDURE_KW = ("ขั้นตอน", "วิธี", "ทำอย่างไร", "ต้องทำไง", "ยื่นคำร้อง")


def classify_query(q: str) -> RouteDecision:
    query_type = _classify_type(q)
    w_dense, w_bm25, w_graph = _WEIGHTS[query_type]
    return RouteDecision(query_type=query_type, alpha_dense=w_dense, alpha_bm25=w_bm25, alpha_graph=w_graph)


def _classify_type(q: str) -> QueryType:
    if _GREETING_RE.match(q.strip()):
        return "direct_llm"
    if _SECTION_NO_RE.search(q):
        return "lookup"
    if any(kw in q for kw in _DEFINITION_KW):
        return "definition"
    if any(kw in q for kw in _PENALTY_KW):
        return "penalty"
    if any(kw in q for kw in _PROCEDURE_KW):
        return "procedure"
    return "general"


if __name__ == "__main__":
    test_queries = [
        "นายจ้างไม่จ่ายค่าล่วงเวลาต้องทำอย่างไร",
        "มาตรา 61 คืออะไร",
        "ลูกจ้างคือใคร",
        "ฝ่าฝืนมาตรา 61 มีโทษอย่างไร",
        "ลาป่วยได้กี่วัน",
        "สวัสดีครับ",
        "วันนี้อากาศเป็นอย่างไร",
    ]
    for q in test_queries:
        print(f"{classify_query(q).model_dump()}  <- {q}")
