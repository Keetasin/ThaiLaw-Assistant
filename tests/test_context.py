import unittest

from src import config
from src.retrieval.context import build_section_cards

GRAPH = {
    "nodes": [
        {"id": "Section:LAW:61", "label": "Section", "law_id": "LAW", "section_no": "61"},
        {"id": "Section:LAW:144", "label": "Section", "law_id": "LAW", "section_no": "144"},
        {"id": "Term:LAW:ค่าจ้าง", "label": "Term", "name": "ค่าจ้าง"},
        {"id": "Topic:ค่าล่วงเวลา", "label": "Topic", "name": "ค่าล่วงเวลา"},
        {"id": "Agency:กรมสวัสดิการ", "label": "Agency", "name": "กรมสวัสดิการ"},
        {"id": "Evidence:สลิปเงินเดือน", "label": "Evidence", "name": "สลิปเงินเดือน"},
        {"id": "Section:LAW:2", "label": "Section", "law_id": "LAW", "section_no": "2"},  # no edges at all
    ],
    "edges": [
        {"source": "Section:LAW:61", "type": "PENALIZED_BY", "target": "Section:LAW:144"},
        {"source": "Section:LAW:61", "type": "DEFINES", "target": "Term:LAW:ค่าจ้าง"},
        {"source": "Section:LAW:61", "type": "ABOUT", "target": "Topic:ค่าล่วงเวลา"},
        {"source": "Topic:ค่าล่วงเวลา", "type": "HANDLED_BY", "target": "Agency:กรมสวัสดิการ"},
        {"source": "Topic:ค่าล่วงเวลา", "type": "REQUIRES_EVIDENCE", "target": "Evidence:สลิปเงินเดือน"},
    ],
}


def section(section_key, section_no, text="ตัวบทตัวอย่าง", law_id="LAW"):
    return {
        "section_key": section_key, "law_id": law_id, "law_name": "กฎหมายทดสอบ",
        "chapter": None, "section_no": section_no, "status": "in_force",
        "source_url": "https://example.test", "text": text,
    }


class SectionCardContentTests(unittest.TestCase):
    def test_includes_graph_derived_fields_when_present(self):
        cards = build_section_cards([section("LAW-s61", "61")], GRAPH, budget_chars=10_000)
        card = cards[0]
        self.assertIn("บทลงโทษที่เกี่ยวข้อง: มาตรา 144", card)
        self.assertIn('นิยามที่ใช้: "ค่าจ้าง"', card)
        self.assertIn("หน่วยงาน: กรมสวัสดิการ", card)
        self.assertIn("หลักฐาน: สลิปเงินเดือน", card)

    def test_omits_absent_graph_fields_cleanly(self):
        cards = build_section_cards([section("LAW-s2", "2")], GRAPH, budget_chars=10_000)
        card = cards[0]
        self.assertNotIn("None", card)
        self.assertNotIn("บทลงโทษที่เกี่ยวข้อง", card)
        self.assertNotIn("นิยามที่ใช้", card)
        self.assertNotIn("หน่วยงาน", card)
        self.assertIn("ตัวบทตัวอย่าง", card)  # the raw text itself is still there

    def test_dedupes_by_section_key(self):
        cards = build_section_cards(
            [section("LAW-s61", "61"), section("LAW-s61", "61")], GRAPH, budget_chars=10_000
        )
        self.assertEqual(len(cards), 1)


class SectionCardBudgetTests(unittest.TestCase):
    def test_always_keeps_at_least_the_first_card_even_if_oversized(self):
        long_section = section("LAW-s61", "61", text="x" * 5000)
        cards = build_section_cards([long_section], GRAPH, budget_chars=10)
        self.assertEqual(len(cards), 1)  # not dropped just because it exceeds budget alone

    def test_drops_later_cards_that_would_exceed_budget(self):
        sections = [section("LAW-s2", "2", text="a" * 100), section("LAW-s61", "61", text="b" * 100)]
        cards = build_section_cards(sections, GRAPH, budget_chars=120)
        self.assertEqual(len(cards), 1)  # second card would push past budget -> dropped, not truncated

    def test_never_cuts_a_card_in_half(self):
        sections = [section("LAW-s2", "2", text="a" * 50)]
        cards = build_section_cards(sections, GRAPH, budget_chars=10_000)
        self.assertIn("a" * 50, cards[0])  # full text present, not sliced

    def test_local_and_api_budgets_are_provider_aware(self):
        self.assertLess(config.CONTEXT_BUDGET_CHARS["local"], config.CONTEXT_BUDGET_CHARS["api"])


if __name__ == "__main__":
    unittest.main()
