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
