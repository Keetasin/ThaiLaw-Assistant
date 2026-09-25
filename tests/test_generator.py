import unittest

from src.app.generator import build_context, parse_citation

SECTIONS = [
    {"section_no": "5", "chapter": "หมวด 1 บททั่วไป", "text": "ค่าจ้างหมายความว่า..."},
    {"section_no": "61", "chapter": None, "text": "ลูกจ้างมีสิทธิได้รับค่าล่วงเวลา"},
]


class BuildContextTests(unittest.TestCase):
    def test_includes_chapter_label_when_present(self):
        ctx = build_context(SECTIONS[:1])
        self.assertIn("[มาตรา 5 (หมวด 1 บททั่วไป)]", ctx)

    def test_omits_chapter_label_when_none(self):
        ctx = build_context(SECTIONS[1:])
        self.assertIn("[มาตรา 61]", ctx)
        self.assertNotIn("(None)", ctx)


class ParseCitationTests(unittest.TestCase):
    def test_strict_trailer_line_is_parsed_and_stripped(self):
        answer = "ลูกจ้างมีสิทธิได้รับค่าล่วงเวลา\nใช้ข้อมูลจาก: [มาตรา 61]"
        clean, cited = parse_citation(answer, SECTIONS)
        self.assertEqual(clean, "ลูกจ้างมีสิทธิได้รับค่าล่วงเวลา")
        self.assertEqual([s["section_no"] for s in cited], ["61"])

    def test_multiple_citations_in_trailer(self):
        answer = "คำตอบ\nใช้ข้อมูลจาก: [มาตรา 5], [มาตรา 61]"
        clean, cited = parse_citation(answer, SECTIONS)
        self.assertEqual({s["section_no"] for s in cited}, {"5", "61"})

    def test_no_trailer_falls_back_to_scanning_whole_answer(self):
        answer = "ตามมาตรา 61 ลูกจ้างมีสิทธิได้รับค่าล่วงเวลา [มาตรา 61]"
        clean, cited = parse_citation(answer, SECTIONS)
        self.assertEqual(clean, answer)
        self.assertEqual([s["section_no"] for s in cited], ["61"])

    def test_no_data_refusal_has_no_citation_and_keeps_all_sections(self):
        answer = "ไม่พบข้อมูลนี้ในตัวบทกฎหมายที่มี"
        clean, cited = parse_citation(answer, SECTIONS)
        self.assertEqual(clean, answer)
        self.assertEqual(cited, SECTIONS)  # no match -> falls back to all retrieved sections

    def test_trailer_citing_a_section_not_in_context_is_ignored(self):
        answer = "คำตอบ\nใช้ข้อมูลจาก: [มาตรา 999]"
        clean, cited = parse_citation(answer, SECTIONS)
        self.assertEqual(cited, SECTIONS)  # no match in `sections` -> falls back to all


if __name__ == "__main__":
    unittest.main()
