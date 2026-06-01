"""UI 层级解析与截图标注（Whiteboard Bridge）。

解析/分层/间距为纯函数，无 Pillow 依赖，可单测。
仅 render() 依赖 Pillow。
"""
import io
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

# macOS 系统字体（含中文）；非 macOS 环境会回退到默认字体
FONT_CANDIDATES = [
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]

PALETTE = [
    (229, 57, 53), (30, 136, 229), (67, 160, 71), (251, 140, 0),
    (142, 36, 170), (0, 172, 193), (216, 27, 96), (124, 179, 66),
]


@dataclass
class Node:
    bounds: tuple[int, int, int, int]
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


@dataclass
class Gap:
    orientation: str   # 'h' | 'v'
    value: int
    x: int
    y: int


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


def classify_levels(nodes):
    """按可点击性分层：clickable/focusable → primary；具名叶子 → secondary；其余 None。"""
    for n in nodes:
        if n.clickable or n.focusable:
            n.level = "primary"
        elif n.is_leaf and n.name:
            n.level = "secondary"
        else:
            n.level = None


def _overlap(a1, a2, b1, b2):
    return a1 < b2 and b1 < a2


def compute_gaps(nodes):
    """同一父容器下、相邻兄弟之间的水平/垂直空隙。

    实现：按位置排序兄弟并对相邻对取间隙。混合排布的容器（如换行的
    网格、非线性 ConstraintLayout）可能漏算部分间隙——这是已知取舍，
    截图标注场景下以行/列线性排布为主，够用。
    """
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


def _load_font(size):
    from PIL import ImageFont
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def select_targets(nodes, level):
    """按 level 选出要标注的节点：'primary' 仅一级；其余（含 'all'）一级+二级。"""
    if level == "primary":
        return [n for n in nodes if n.level == "primary"]
    return [n for n in nodes if n.level in ("primary", "secondary")]


def render(image_path, nodes, gaps, options):
    """在 image_path 上画标注，返回 PNG bytes。需要 Pillow。"""
    from PIL import Image, ImageDraw

    level = options.get("level", "all")
    show_size = options.get("size", True)
    show_name = options.get("name", True)
    show_spacing = options.get("spacing", False)

    targets = select_targets(nodes, level)

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
            lx = max(0, min(x1, img.width - tw - 8))
            ly = max(0, y1 - th - 8)
            draw.rectangle([lx, ly, lx + tw + 8, ly + th + 8], fill=color)
            draw.text((lx + 4, ly + 3), label, fill=(255, 255, 255), font=font)

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
