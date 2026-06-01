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

    def test_name_fallback_fields(self):
        names = {n.name for n in self.nodes}
        self.assertIn("历史对话", names)       # 来自 content-desc
        self.assertIn("麦克风", names)         # 来自 content-desc
        self.assertIn("厦门旅行", names)       # 来自 text（该节点无 content-desc）

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

    def test_name_falls_back_to_resource_id(self):
        xml = ('<hierarchy><node class="android.widget.Button" '
               'resource-id="com.app:id/submit_btn" content-desc="" text="" '
               'clickable="true" focusable="false" bounds="[0,0][10,10]" /></hierarchy>')
        nodes = annotate.parse_hierarchy(xml)
        self.assertEqual(nodes[0].name, "submit_btn")


class TestClassifyLevels(unittest.TestCase):
    def setUp(self):
        self.nodes = annotate.parse_hierarchy(load_fixture())
        annotate.classify_levels(self.nodes)

    def _by_bounds(self, b):
        return next(n for n in self.nodes if n.bounds == b)

    def test_clickable_container_is_primary(self):
        self.assertEqual(self._by_bounds((54, 0, 1162, 1297)).level, "primary")

    def test_clickable_leaf_imageview_is_primary(self):
        kb = self._by_bounds((169, 2418, 330, 2579))
        self.assertEqual(kb.level, "primary")
        self.assertEqual(kb.name, "键盘")

    def test_named_leaf_is_secondary(self):
        self.assertEqual(self._by_bounds((438, 469, 779, 564)).level, "secondary")

    def test_non_clickable_container_is_none(self):
        self.assertIsNone(self._by_bounds((0, 0, 1216, 2640)).level)


if __name__ == "__main__":
    unittest.main()
