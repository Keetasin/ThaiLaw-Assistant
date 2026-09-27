import unittest

from src.app.flex import _insert_word_breaks, _strip_markdown, build_answer_flex

_ZWSP = "​"


def hit(section_no="61", chapter=None):
    return {
        "section_no": section_no,
        "chapter": chapter,
        "source_url": "https://example.com/law",
        "retrieved_date": "2026-01-01",
    }


class StripMarkdownTests(unittest.TestCase):
    def test_removes_bold_markers(self):
        self.assertEqual(_strip_markdown("**ห้าม**ทำงาน"), "ห้ามทำงาน")

    def test_converts_asterisk_bullets(self):
        self.assertEqual(_strip_markdown("*   งานเหมืองแร่"), "• งานเหมืองแร่")

    def test_leaves_plain_text_untouched(self):
        self.assertEqual(_strip_markdown("ลูกจ้างมีสิทธิลากิจ"), "ลูกจ้างมีสิทธิลากิจ")


class InsertWordBreaksTests(unittest.TestCase):
    def test_inserts_zwsp_between_tokens(self):
        # real live-test miss: LINE's FlexText wraps Thai purely by
        # character count (no built-in word-segmentation), splitting lines
        # mid-word -- ZWSP at real word boundaries gives it somewhere sane
        # to break instead.
        out = _insert_word_breaks("ลูกจ้างมีสิทธิ")
        self.assertIn(_ZWSP, out)
        self.assertEqual(out.replace(_ZWSP, ""), "ลูกจ้างมีสิทธิ")  # invisible only, no content change

    def test_preserves_line_breaks(self):
        out = _insert_word_breaks("บรรทัดหนึ่ง\nบรรทัดสอง")
        self.assertEqual(out.count("\n"), 1)


def _collect_text(component):
    texts = []
    if hasattr(component, "text") and component.text:
        texts.append(component.text)
    for child in getattr(component, "contents", None) or []:
        texts.extend(_collect_text(child))
    return texts


class BuildAnswerFlexTests(unittest.TestCase):
    def _body(self, msg):
        return "".join(_collect_text(msg.contents.body)).replace(_ZWSP, "")

    def test_drops_citation_trailer_from_body_not_just_the_mattra_section(self):
        # LINE Flex renders its own deduped "มาตรา" section from `hits`
        # already -- if the raw answer_text's own "\n\nที่มา: ..." trailer
        # is shown too, the section list appears twice in the same card.
        answer = "คำตอบจริง\n\nที่มา: พ.ร.บ.คุ้มครองแรงงาน\n  § มาตรา 61"
        body = self._body(build_answer_flex(answer, [hit()]))
        self.assertIn("คำตอบจริง", body)
        self.assertNotIn("ที่มา:", body)

    def test_no_longer_shows_a_sitthi_header(self):
        body = self._body(build_answer_flex("คำตอบ", [hit()]))
        self.assertNotIn("สิทธิ", body)

    def test_strips_markdown_from_body(self):
        answer = "**1. ข้อห้าม:**\n*   งานเหมืองแร่"
        body = self._body(build_answer_flex(answer, [hit()]))
        self.assertNotIn("**", body)
        self.assertNotIn("*   ", body)

    def test_raises_without_hits(self):
        with self.assertRaises(ValueError):
            build_answer_flex("x", [])

    def test_has_branded_header_bar(self):
        msg = build_answer_flex("คำตอบ", [hit()])
        header_texts = _collect_text(msg.contents.header)
        self.assertTrue(any("ผู้ช่วยกฎหมายแรงงาน" in t for t in header_texts))

    def test_mattra_label_is_blue(self):
        msg = build_answer_flex("คำตอบ", [hit()])
        label = next(c for c in msg.contents.body.contents if getattr(c, "text", None) == "มาตรา")
        self.assertEqual(label.color, "#1D4ED8")

    def test_separator_above_mattra_is_orange(self):
        from linebot.v3.messaging import FlexSeparator
        msg = build_answer_flex("คำตอบ", [hit()])
        sep = next(c for c in msg.contents.body.contents if isinstance(c, FlexSeparator))
        self.assertEqual(sep.color, "#F4A261")

    def test_footer_background_matches_body(self):
        msg = build_answer_flex("คำตอบ", [hit()])
        self.assertEqual(msg.contents.footer.background_color, msg.contents.body.background_color)

    def test_button_is_a_filled_primary_button_not_a_plain_link(self):
        msg = build_answer_flex("คำตอบ", [hit()])
        button = msg.contents.footer.contents[0]
        self.assertEqual(button.style, "primary")
        self.assertIsNotNone(button.color)


if __name__ == "__main__":
    unittest.main()
