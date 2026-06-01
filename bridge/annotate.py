"""UI 层级解析与截图标注（Whiteboard Bridge）。

解析/分层/间距为纯函数，无 Pillow 依赖，可单测。
仅 render() 依赖 Pillow。
"""
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field


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
