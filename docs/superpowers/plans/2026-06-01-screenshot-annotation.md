# 截图组件标注 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 Whiteboard Bridge 加一个「详细信息」开关，截图时把组件尺寸/名称/间距用 Pillow 烤进 Android 截图。

**Architecture:** 新增纯逻辑模块 `bridge/annotate.py`（解析 uiautomator XML、分层、算间距、Pillow 渲染），`server.py` 在 adb 截图后按需调用它另存 `_annotated.png`，`ui.html` 加复选框并把选项随请求发出。Figma 侧 `code.js` 不改。

**Tech Stack:** Python 3 stdlib（`xml.etree.ElementTree`、`subprocess`、`unittest`）、Pillow（已装 11.3.0）、原生 HTML/JS。

参考规范：`docs/superpowers/specs/2026-06-01-screenshot-annotation-design.md`

---

## 文件结构

| 文件 | 动作 | 职责 |
|---|---|---|
| `bridge/fixtures/window_dump_sample.xml` | 已创建 | 单测 fixture（真实层级裁剪版） |
| `bridge/annotate.py` | 创建 | 解析/分层/间距（纯函数）+ `render`（Pillow） |
| `bridge/test_annotate.py` | 创建 | `parse_hierarchy`/`classify_levels`/`compute_gaps` 单测 + `render` 冒烟 |
| `bridge/server.py` | 修改 | `_screenshot` 透传 `annotate`/`options`；`_screenshot_adb` 调用标注；新增 `_dump_ui_xml`、`_annotate_into` |
| `ui.html` | 修改 | 详细信息复选框 + 层级单选；`gatherOptions`；`takeScreenshot` 带选项；显示 `note` |

`annotate.py` 内 `Node` 数据结构（贯穿全计划，签名固定）：

```python
@dataclass
class Node:
    bounds: tuple            # (x1, y1, x2, y2)
    name: str                # content-desc → text → resource-id 回退，空则 ""
    clickable: bool
    focusable: bool
    cls: str                 # class 简名
    parent: "Node" = None
    children: list = field(default_factory=list)
    level: str = None        # 'primary' | 'secondary' | None
    # 属性：is_leaf, width, height
```

`Gap` 数据结构：

```python
@dataclass
class Gap:
    orientation: str   # 'h' | 'v'
    value: int         # 像素间距
    x: int             # 标签中心 x
    y: int             # 标签中心 y
```

---

## Task 1: 解析层级 `parse_hierarchy`

**Files:**
- Create: `bridge/annotate.py`
- Create: `bridge/test_annotate.py`
- Fixture: `bridge/fixtures/window_dump_sample.xml`（已存在）

- [ ] **Step 1: 写失败测试**

`bridge/test_annotate.py`：

```python
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
        # 顶层 FrameLayout / 可点击卡片容器无 text/content-desc → name 为空
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
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd bridge && python -m unittest test_annotate -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'annotate'`）

- [ ] **Step 3: 写最小实现**

`bridge/annotate.py`：

```python
"""UI 层级解析与截图标注（Whiteboard Bridge）。

解析/分层/间距为纯函数，无 Pillow 依赖，可单测。
仅 render() 依赖 Pillow。
"""
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


@dataclass
class Node:
    bounds: tuple
    name: str
    clickable: bool
    focusable: bool
    cls: str
    parent: "Node" = None
    children: list = field(default_factory=list)
    level: str = None

    @property
    def is_leaf(self):
        return len(self.children) == 0

    @property
    def width(self):
        return self.bounds[2] - self.bounds[0]

    @property
    def height(self):
        return self.bounds[3] - self.bounds[1]


def _parse_bounds(s):
    nums = s.replace("[", " ").replace("]", " ").replace(",", " ").split()
    if len(nums) != 4:
        raise ValueError(f"bad bounds: {s!r}")
    x1, y1, x2, y2 = (int(n) for n in nums)
    return (x1, y1, x2, y2)


def _node_name(el):
    for attr in ("content-desc", "text", "resource-id"):
        v = (el.get(attr) or "").strip()
        if v:
            return v.split("/")[-1] if attr == "resource-id" else v
    return ""


def parse_hierarchy(xml):
    """解析 uiautomator XML 为扁平 Node 列表，含 parent/children 链接。"""
    root = ET.fromstring(xml)
    nodes = []

    def walk(el, parent):
        next_parent = parent
        if el.tag == "node":
            try:
                bounds = _parse_bounds(el.get("bounds", ""))
            except ValueError:
                bounds = None
            if bounds is not None:
                n = Node(
                    bounds=bounds,
                    name=_node_name(el),
                    clickable=el.get("clickable") == "true",
                    focusable=el.get("focusable") == "true",
                    cls=(el.get("class") or "").rsplit(".", 1)[-1],
                    parent=parent,
                )
                if parent is not None:
                    parent.children.append(n)
                nodes.append(n)
                next_parent = n
        for child in el:
            walk(child, next_parent)

    walk(root, None)
    return nodes
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd bridge && python -m unittest test_annotate -v`
Expected: PASS（5 个 test_ 全绿）

- [ ] **Step 5: 提交**

```bash
git add bridge/annotate.py bridge/test_annotate.py bridge/fixtures/window_dump_sample.xml
git commit -m "feat(annotate): parse uiautomator hierarchy into Node tree"
```

---

## Task 2: 分层 `classify_levels`

**Files:**
- Modify: `bridge/annotate.py`
- Test: `bridge/test_annotate.py`

- [ ] **Step 1: 写失败测试**（追加到 `test_annotate.py`）

```python
class TestClassifyLevels(unittest.TestCase):
    def setUp(self):
        self.nodes = annotate.parse_hierarchy(load_fixture())
        annotate.classify_levels(self.nodes)

    def _by_bounds(self, b):
        return next(n for n in self.nodes if n.bounds == b)

    def test_clickable_container_is_primary(self):
        self.assertEqual(self._by_bounds((54, 0, 1162, 1297)).level, "primary")

    def test_clickable_leaf_imageview_is_primary(self):
        # 键盘 ImageView：clickable 叶子 → primary（且有名字）
        kb = self._by_bounds((169, 2418, 330, 2579))
        self.assertEqual(kb.level, "primary")
        self.assertEqual(kb.name, "键盘")

    def test_named_leaf_is_secondary(self):
        # 厦门旅行 TextView：非可点击叶子且有名字 → secondary
        self.assertEqual(self._by_bounds((438, 469, 779, 564)).level, "secondary")

    def test_non_clickable_container_is_none(self):
        # 顶层 FrameLayout：非可点击、非叶子 → None
        self.assertIsNone(self._by_bounds((0, 0, 1216, 2640)).level)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd bridge && python -m unittest test_annotate.TestClassifyLevels -v`
Expected: FAIL（`AttributeError: module 'annotate' has no attribute 'classify_levels'`）

- [ ] **Step 3: 写最小实现**（追加到 `annotate.py`）

```python
def classify_levels(nodes):
    """按可点击性分层：clickable/focusable → primary；具名叶子 → secondary；其余 None。"""
    for n in nodes:
        if n.clickable or n.focusable:
            n.level = "primary"
        elif n.is_leaf and n.name:
            n.level = "secondary"
        else:
            n.level = None
```

- [ ] **Step 4: 运行确认通过**

Run: `cd bridge && python -m unittest test_annotate -v`
Expected: PASS（全部）

- [ ] **Step 5: 提交**

```bash
git add bridge/annotate.py bridge/test_annotate.py
git commit -m "feat(annotate): classify nodes into primary/secondary levels"
```

---

## Task 3: 间距 `compute_gaps`

**Files:**
- Modify: `bridge/annotate.py`
- Test: `bridge/test_annotate.py`

- [ ] **Step 1: 写失败测试**（追加）

```python
class TestComputeGaps(unittest.TestCase):
    def _row(self):
        # 同一父容器下，一行三个组件：x 间隙各 50
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
        self.assertEqual(sorted(g.value for g in h), [50, 50])

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
```

- [ ] **Step 2: 运行确认失败**

Run: `cd bridge && python -m unittest test_annotate.TestComputeGaps -v`
Expected: FAIL（`AttributeError: ... 'compute_gaps'`）

- [ ] **Step 3: 写最小实现**（追加到 `annotate.py`，`Gap` 放在文件顶部 dataclass 区）

```python
@dataclass
class Gap:
    orientation: str   # 'h' | 'v'
    value: int
    x: int
    y: int


def _overlap(a1, a2, b1, b2):
    return a1 < b2 and b1 < a2


def compute_gaps(nodes):
    """同一父容器下、相邻兄弟之间的水平/垂直空隙。"""
    gaps = []
    parents = {}
    for n in nodes:
        if n.parent is not None:
            parents.setdefault(id(n.parent), []).append(n)
    for sibs in parents.values():
        if len(sibs) < 2:
            continue
        rows = sorted(sibs, key=lambda n: n.bounds[0])
        for a, b in zip(rows, rows[1:]):
            ax1, ay1, ax2, ay2 = a.bounds
            bx1, by1, bx2, by2 = b.bounds
            if _overlap(ay1, ay2, by1, by2) and bx1 >= ax2:
                g = bx1 - ax2
                if g > 0:
                    gaps.append(Gap("h", g, (ax2 + bx1) // 2,
                                    (max(ay1, by1) + min(ay2, by2)) // 2))
        cols = sorted(sibs, key=lambda n: n.bounds[1])
        for a, b in zip(cols, cols[1:]):
            ax1, ay1, ax2, ay2 = a.bounds
            bx1, by1, bx2, by2 = b.bounds
            if _overlap(ax1, ax2, bx1, bx2) and by1 >= ay2:
                g = by1 - ay2
                if g > 0:
                    gaps.append(Gap("v", g, (max(ax1, bx1) + min(ax2, bx2)) // 2,
                                    (ay2 + by1) // 2))
    return gaps
```

- [ ] **Step 4: 运行确认通过**

Run: `cd bridge && python -m unittest test_annotate -v`
Expected: PASS（全部）

- [ ] **Step 5: 提交**

```bash
git add bridge/annotate.py bridge/test_annotate.py
git commit -m "feat(annotate): compute horizontal/vertical sibling gaps"
```

---

## Task 4: 渲染 `render`（Pillow）

**Files:**
- Modify: `bridge/annotate.py`
- Test: `bridge/test_annotate.py`（冒烟测试）

- [ ] **Step 1: 写冒烟测试**（追加）

```python
class TestRenderSmoke(unittest.TestCase):
    def test_render_returns_png_bytes(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow 未安装")
        import io
        import tempfile
        # 造一张纯色底图
        img = Image.new("RGB", (1216, 2640), (240, 240, 240))
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
            img.save(tf.name)
            path = tf.name
        nodes = annotate.parse_hierarchy(load_fixture())
        annotate.classify_levels(nodes)
        gaps = annotate.compute_gaps(nodes)
        opts = {"size": True, "name": True, "spacing": True, "level": "all"}
        out = annotate.render(path, nodes, gaps, opts)
        self.assertTrue(out.startswith(b"\x89PNG"))
        self.assertGreater(len(out), 100)
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
        nodes = annotate.parse_hierarchy(load_fixture())
        annotate.classify_levels(nodes)
        out = annotate.render(path, nodes, [], {"size": True, "name": False,
                                                "spacing": False, "level": "primary"})
        self.assertTrue(out.startswith(b"\x89PNG"))
        os.unlink(path)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd bridge && python -m unittest test_annotate.TestRenderSmoke -v`
Expected: FAIL（`AttributeError: ... 'render'`）

- [ ] **Step 3: 写实现**（追加到 `annotate.py`，顶部常量区加 `FONT_CANDIDATES`、`PALETTE`）

文件顶部常量（紧跟 import 之后）：

```python
FONT_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]

PALETTE = [
    (229, 57, 53), (30, 136, 229), (67, 160, 71), (251, 140, 0),
    (142, 36, 170), (0, 172, 193), (216, 27, 96), (124, 179, 66),
]
```

渲染函数（文件末尾）：

```python
def _load_font(size):
    import os
    from PIL import ImageFont
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def render(image_path, nodes, gaps, options):
    """在 image_path 上画标注，返回 PNG bytes。需要 Pillow。"""
    import io
    from PIL import Image, ImageDraw

    level = options.get("level", "all")
    show_size = options.get("size", True)
    show_name = options.get("name", True)
    show_spacing = options.get("spacing", False)

    if level == "primary":
        targets = [n for n in nodes if n.level == "primary"]
    else:
        targets = [n for n in nodes if n.level in ("primary", "secondary")]

    img = Image.open(image_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    font = _load_font(28)

    for i, n in enumerate(targets):
        color = PALETTE[i % len(PALETTE)]
        x1, y1, x2, y2 = n.bounds
        lw = 5 if n.level == "primary" else 2
        draw.rectangle([x1, y1, x2, y2], outline=color, width=lw)

        parts = []
        if show_name and n.name:
            parts.append(n.name)
        if show_size:
            parts.append(f"{n.width}×{n.height}")
        label = "  ".join(parts)
        if label:
            box = draw.textbbox((0, 0), label, font=font)
            tw, th = box[2] - box[0], box[3] - box[1]
            ly = max(0, y1 - th - 8)
            draw.rectangle([x1, ly, x1 + tw + 8, ly + th + 8], fill=color)
            draw.text((x1 + 4, ly + 3), label, fill=(255, 255, 255), font=font)

    if show_spacing:
        for g in gaps:
            label = str(g.value)
            box = draw.textbbox((0, 0), label, font=font)
            tw, th = box[2] - box[0], box[3] - box[1]
            draw.rectangle([g.x - tw // 2 - 3, g.y - th // 2 - 2,
                            g.x + tw // 2 + 3, g.y + th // 2 + 2], fill=(33, 33, 33))
            draw.text((g.x - tw // 2, g.y - th // 2 - 1), label,
                      fill=(255, 255, 255), font=font)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
```

- [ ] **Step 4: 运行确认通过**

Run: `cd bridge && python -m unittest test_annotate -v`
Expected: PASS（全部，含冒烟）

- [ ] **Step 5: 提交**

```bash
git add bridge/annotate.py bridge/test_annotate.py
git commit -m "feat(annotate): render boxes/labels/gaps onto screenshot via Pillow"
```

---

## Task 5: server.py 接线

**Files:**
- Modify: `bridge/server.py`（`_screenshot`、`_screenshot_adb`，新增 `_dump_ui_xml`、`_annotate_into`）

- [ ] **Step 1: 改 `_screenshot` 透传选项**

把 `_screenshot` 整体替换为：

```python
    def _screenshot(self):
        device_type = "adb"
        annotate = False
        options = {}
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 0:
                body = self.rfile.read(length)
                data = json.loads(body)
                device_type = data.get("type", "adb")
                annotate = bool(data.get("annotate", False))
                options = data.get("options", {}) or {}
        except Exception:
            device_type = "adb"

        if device_type == "hdc":
            self._screenshot_hdc()
        else:
            self._screenshot_adb(annotate, options)
```

- [ ] **Step 2: 改 `_screenshot_adb` 签名并接入标注**

把 `def _screenshot_adb(self):` 改为 `def _screenshot_adb(self, annotate=False, options=None):`，
并把原来这段：

```python
            resp = {"filename": fn}
            dims = _image_dimensions(fp)
            if dims:
                resp["width"], resp["height"] = dims
            self._json(resp)
```

替换为：

```python
            resp = {"filename": fn}
            dims = _image_dimensions(fp)
            if dims:
                resp["width"], resp["height"] = dims
            if annotate:
                self._annotate_into(resp, fp, options or {})
            self._json(resp)
```

- [ ] **Step 3: 新增 `_dump_ui_xml` 与 `_annotate_into`**

在 `_screenshot_adb` 之后插入：

```python
    def _dump_ui_xml(self):
        """adb uiautomator dump → 返回 XML 字符串，失败返回 None。"""
        try:
            r = subprocess.run(
                ["adb", "shell", "uiautomator", "dump", "/sdcard/window_dump.xml"],
                capture_output=True, timeout=15, text=True,
            )
            if r.returncode != 0:
                return None
            r = subprocess.run(
                ["adb", "exec-out", "cat", "/sdcard/window_dump.xml"],
                capture_output=True, timeout=15,
            )
            if r.returncode != 0 or not r.stdout:
                return None
            return r.stdout.decode("utf-8", "replace")
        except Exception:
            return None

    def _annotate_into(self, resp, fp, options):
        """在 resp 上把 filename 换成标注图；任何失败则保留原图并写 note。"""
        try:
            import annotate as ann
        except Exception:
            resp["note"] = "标注模块加载失败，已返回原图"
            return
        xml = self._dump_ui_xml()
        if not xml:
            resp["note"] = "未能获取层级，已返回原图"
            return
        try:
            nodes = ann.parse_hierarchy(xml)
            ann.classify_levels(nodes)
            gaps = ann.compute_gaps(nodes)
            png = ann.render(str(fp), nodes, gaps, options)
        except Exception as e:
            resp["note"] = f"标注失败，已返回原图：{e}"
            return
        ann_fn = fp.stem + "_annotated.png"
        ann_fp = fp.parent / ann_fn
        ann_fp.write_bytes(png)
        resp["filename"] = ann_fn
        dims = _image_dimensions(ann_fp)
        if dims:
            resp["width"], resp["height"] = dims
```

- [ ] **Step 4: 手动集成验证**（需连真机）

启动 bridge 后，对真机发标注请求并确认返回 `_annotated.png`：

Run:
```bash
cd bridge && python server.py >/tmp/bridge.log 2>&1 &
sleep 1
curl -s -X POST http://localhost:8767/api/screenshot \
  -H 'Content-Type: application/json' \
  -d '{"type":"adb","annotate":true,"options":{"size":true,"name":true,"spacing":true,"level":"all"}}'
echo
ls -t bridge/images/*_annotated.png 2>/dev/null | head -1
kill %1 2>/dev/null
```
Expected: JSON 含 `"filename":"screen_..._annotated.png"` 与 `width/height`；`images/` 下出现该文件。打开图片应看到彩色框 + 中文名 + 尺寸 + gap 数值。

- [ ] **Step 5: 确认单测仍全绿并提交**

Run: `cd bridge && python -m unittest -v`
Expected: PASS

```bash
git add bridge/server.py
git commit -m "feat(bridge): wire detailed-info annotation into adb screenshot"
```

---

## Task 6: ui.html 面板

**Files:**
- Modify: `ui.html`（Screenshot section、`<script>`）

- [ ] **Step 1: 加详细信息控件**

把这段：

```html
<div class="section">
  <div class="section-title">Screenshot</div>
  <div id="screenshot-buttons"></div>
</div>
```

替换为：

```html
<div class="section">
  <div class="section-title">Screenshot</div>
  <label style="display:flex;align-items:center;gap:6px;font-size:12px;margin-bottom:6px;cursor:pointer;">
    <input type="checkbox" id="opt-detail" onchange="toggleDetail()"> 详细信息
  </label>
  <div id="detail-opts" style="display:none;padding:0 0 8px 18px;font-size:12px;color:#555;">
    <label style="margin-right:10px;cursor:pointer;"><input type="checkbox" id="opt-size" checked> 组件尺寸</label>
    <label style="margin-right:10px;cursor:pointer;"><input type="checkbox" id="opt-name" checked> 组件名称</label>
    <label style="cursor:pointer;"><input type="checkbox" id="opt-spacing"> 组件间距</label>
    <div style="margin-top:6px;">层级：
      <label style="margin-right:8px;cursor:pointer;"><input type="radio" name="opt-level" value="primary"> 仅一级</label>
      <label style="cursor:pointer;"><input type="radio" name="opt-level" value="all" checked> 一级+二级</label>
    </div>
  </div>
  <div id="screenshot-buttons"></div>
</div>
```

- [ ] **Step 2: 加 `toggleDetail` / `gatherOptions`**

在 `<script>` 内 `getUrl()` 之后加：

```javascript
function toggleDetail() {
  document.getElementById('detail-opts').style.display =
    document.getElementById('opt-detail').checked ? 'block' : 'none';
}

function gatherOptions() {
  if (!document.getElementById('opt-detail').checked) {
    return { annotate: false, options: {} };
  }
  return {
    annotate: true,
    options: {
      size: document.getElementById('opt-size').checked,
      name: document.getElementById('opt-name').checked,
      spacing: document.getElementById('opt-spacing').checked,
      level: document.querySelector('input[name="opt-level"]:checked').value
    }
  };
}
```

- [ ] **Step 3: `takeScreenshot` 带选项并显示 note**

把 `takeScreenshot` 里发请求那段：

```javascript
    const resp = await fetch(getUrl() + '/api/screenshot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type }),
      signal: AbortSignal.timeout(30000)
    });
```

替换为：

```javascript
    const opt = gatherOptions();
    const resp = await fetch(getUrl() + '/api/screenshot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type, annotate: opt.annotate, options: opt.options }),
      signal: AbortSignal.timeout(30000)
    });
```

并把成功提示：

```javascript
    setStatus('Screenshot: ' + data.filename, 'success');
```

替换为：

```javascript
    setStatus('Screenshot: ' + data.filename + (data.note ? '\n' + data.note : ''),
              data.note ? '' : 'success');
```

- [ ] **Step 4: 手动验证**（Figma 内）

在 Figma 打开插件 →「详细信息」打勾 → 出现三个复选框与层级单选 → 点截图 → 画布插入的图带标注；取消「详细信息」→ 插入普通截图。降级时状态栏显示中文 note。

- [ ] **Step 5: 提交**

```bash
git add ui.html
git commit -m "feat(ui): add detailed-info toggle with size/name/spacing options"
```

---

## 完成后

- [ ] `cd bridge && python -m unittest -v` 全绿
- [ ] 真机端到端：详细信息开/关、三选项组合、两种层级各验证一次
- [ ] 用 superpowers:finishing-a-development-branch 决定合并方式
