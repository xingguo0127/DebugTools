import os
import unittest

import annotate

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "window_dump_sample.xml")


def load_fixture():
    with open(FIXTURE, encoding="utf-8") as f:
        return f.read()


class TestParseHierarchy(unittest.TestCase):
    def setUp(self):
        self.nodes = annotate.parse_hierarchy(load_fixture())

    def test_bounds_parsed_as_ints(self):
        root = self.nodes[0]
        self.assertEqual(root.bounds, (0, 0, 1216, 2640))

    def test_name_prefers_text_then_content_desc(self):
        names = {n.name for n in self.nodes}
        self.assertIn("厦门旅行", names)       # 来自 text
        self.assertIn("历史对话", names)       # 来自 content-desc
        self.assertIn("麦克风", names)         # 来自 content-desc

    def test_container_without_name_is_empty(self):
        card = next(n for n in self.nodes if n.bounds == (54, 0, 1162, 1297))
        self.assertEqual(card.name, "")

    def test_parent_child_links(self):
        card = next(n for n in self.nodes if n.bounds == (54, 0, 1162, 1297))
        child_names = {c.name for c in card.children}
        self.assertEqual(child_names, {"厦门旅行", "旅行", "厦门", "带父母"})

    def test_clickable_focusable_flags(self):
        card = next(n for n in self.nodes if n.bounds == (54, 0, 1162, 1297))
        self.assertTrue(card.clickable)
        self.assertTrue(card.focusable)


if __name__ == "__main__":
    unittest.main()
