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
        # 纯文本节点不再回退到 text，名字为空（避免逐字噪声）
        text_node = next(n for n in self.nodes if n.bounds == (438, 469, 779, 564))
        self.assertEqual(text_node.name, "")

    def test_container_without_name_is_empty(self):
        card = next(n for n in self.nodes if n.bounds == (54, 0, 1162, 1297))
        self.assertEqual(card.name, "")

    def test_parent_child_links(self):
        card = next(n for n in self.nodes if n.bounds == (54, 0, 1162, 1297))
        # 4 个文本子节点：名字不再取 text（故都为空），但父子链接仍完整
        self.assertEqual(len(card.children), 4)
        self.assertTrue(all(c.name == "" for c in card.children))

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
        # 麦克风：非可点击、有 content-desc 的叶子 → secondary
        mic = self._by_bounds((568, 2458, 649, 2539))
        self.assertEqual(mic.level, "secondary")
        self.assertEqual(mic.name, "麦克风")

    def test_non_clickable_container_is_none(self):
        self.assertIsNone(self._by_bounds((0, 0, 1216, 2640)).level)

    def test_fullscreen_node_skipped_as_noise(self):
        # 近全屏可点击容器（背景/scrim）应被剔除，不参与标注
        nodes = annotate.parse_hierarchy(
            '<hierarchy><node class="android.view.View" content-desc="" '
            'clickable="true" focusable="true" bounds="[0,0][1216,2640]" />'
            '</hierarchy>')
        annotate.classify_levels(nodes)
        self.assertIsNone(nodes[0].level)

    def test_thin_strip_node_skipped_as_noise(self):
        # 退化细条（高 < 4px）应被剔除
        nodes = annotate.parse_hierarchy(
            '<hierarchy><node class="android.view.View" content-desc="bar" '
            'clickable="true" bounds="[0,0][1216,1]" /></hierarchy>')
        annotate.classify_levels(nodes)
        self.assertIsNone(nodes[0].level)

    def test_select_targets_primary_only(self):
        prim = annotate.select_targets(self.nodes, "primary")
        self.assertTrue(all(n.level == "primary" for n in prim))
        self.assertTrue(len(prim) >= 1)

    def test_select_targets_all_includes_secondary(self):
        allt = annotate.select_targets(self.nodes, "all")
        self.assertTrue(any(n.level == "secondary" for n in allt))
        self.assertGreaterEqual(len(allt), len(annotate.select_targets(self.nodes, "primary")))


class TestComputeGaps(unittest.TestCase):
    def _row(self):
        parent = annotate.Node(bounds=(0, 0, 400, 100), name="", clickable=False,
                               focusable=False, cls="View")
        a = annotate.Node(bounds=(0, 10, 100, 90), name="a", clickable=False,
                          focusable=False, cls="View", parent=parent)
        b = annotate.Node(bounds=(150, 10, 250, 90), name="b", clickable=False,
                          focusable=False, cls="View", parent=parent)
        c = annotate.Node(bounds=(300, 10, 400, 90), name="c", clickable=False,
                          focusable=False, cls="View", parent=parent)
        parent.children = [a, b, c]
        return [parent, a, b, c]

    def test_horizontal_gaps(self):
        gaps = annotate.compute_gaps(self._row())
        h = [g for g in gaps if g.orientation == "h"]
        self.assertEqual(len(h), 2)
        self.assertEqual(sorted(g.value for g in h), [50, 50])
        # 第一个间隙在 a(…100) 与 b(150…) 之间，中点 x=125，行内 y=50
        first = min(h, key=lambda g: g.x)
        self.assertEqual((first.x, first.y), (125, 50))

    def test_no_gap_for_single_child(self):
        parent = annotate.Node(bounds=(0, 0, 100, 100), name="", clickable=False,
                               focusable=False, cls="View")
        only = annotate.Node(bounds=(10, 10, 90, 90), name="x", clickable=False,
                             focusable=False, cls="View", parent=parent)
        parent.children = [only]
        self.assertEqual(annotate.compute_gaps([parent, only]), [])

    def test_vertical_gap(self):
        parent = annotate.Node(bounds=(0, 0, 100, 300), name="", clickable=False,
                               focusable=False, cls="View")
        top = annotate.Node(bounds=(10, 0, 90, 100), name="t", clickable=False,
                            focusable=False, cls="View", parent=parent)
        bot = annotate.Node(bounds=(10, 160, 90, 260), name="b", clickable=False,
                            focusable=False, cls="View", parent=parent)
        parent.children = [top, bot]
        gaps = annotate.compute_gaps([parent, top, bot])
        v = [g for g in gaps if g.orientation == "v"]
        self.assertEqual([g.value for g in v], [60])


class TestRenderSmoke(unittest.TestCase):
    def test_render_returns_png_bytes(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow 未安装")
        import tempfile
        img = Image.new("RGB", (1216, 2640), (240, 240, 240))
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            img.save(tf.name)
            path = tf.name
        try:
            with open(path, "rb") as fh:
                original = fh.read()
            nodes = annotate.parse_hierarchy(load_fixture())
            annotate.classify_levels(nodes)
            gaps = annotate.compute_gaps(nodes)
            opts = {"size": True, "name": True, "spacing": True, "level": "all"}
            out = annotate.render(path, nodes, gaps, opts)
            self.assertTrue(out.startswith(b"\x89PNG"))
            self.assertGreater(len(out), 100)
            self.assertNotEqual(out, original)  # 确认确实画了标注
        finally:
            os.unlink(path)

    def test_render_primary_only_subset(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow 未安装")
        import tempfile
        img = Image.new("RGB", (1216, 2640), (255, 255, 255))
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            img.save(tf.name)
            path = tf.name
        try:
            nodes = annotate.parse_hierarchy(load_fixture())
            annotate.classify_levels(nodes)
            out = annotate.render(path, nodes, [], {"size": True, "name": False,
                                                    "spacing": False, "level": "primary"})
            self.assertTrue(out.startswith(b"\x89PNG"))
            self.assertGreater(len(out), 100)
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
