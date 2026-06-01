# 截图组件标注（Detailed Info）设计

日期：2026-06-01
状态：已批准，待实现

## 目标

在截图时提供一个「详细信息」开关。打开后，bridge 在抓屏的同时抓取设备 UI 层级，把关键组件信息——**尺寸、名称、间距**——用 Pillow 烤进截图，返回一张扁平 PNG 插入 Figma 画布。

目的：让标注后的截图能在写代码时与 AI 对齐到同一组件上下文（组件名、尺寸、位置一目了然）。

参考视觉：每个组件外接彩色框，左上角彩色底块 + 白字标注尺寸（如 `162×162`）/ 名称，相邻组件间标注 gap。

## 范围

- **本期仅 Android（adb）**。数据源 `adb shell uiautomator dump`。
- **HarmonyOS（hdc）已支持**（2026-06-01 真机验证）：层级走 `hdc shell uitest dumpLayout`，输出 `{attributes, children}` 的 JSON。`annotate.parse_harmony` 单独解析，分层 / 间距 / 渲染层与 Android 完全复用。
  - 鸿蒙名称取 `description → text`（**保留 text**：鸿蒙文本多为整块、非逐字；`description` 实测多为空；不取 `id/key`，它们常是图片资源路径噪声）。
  - 鸿蒙无 `focusable` 字段，一级判定用 `clickable`（`focusable` 由 `longClickable` 兜底）。
  - `bounds` 格式 `[x1,y1][x2,y2]` 与 Android 相同，复用 `_parse_bounds`；截图（`snapshot_display`）与层级同分辨率，无需缩放。
- iOS 物理设备不在范围内（已于 2026-05-14 整体放弃）。

## 可行性验证（2026-06-01，实测）

在连接的 Android 设备（Compose 应用 `com.example.celiaapp.celia`）上实测：

1. **坐标系一致**：截图 PNG 尺寸 `1216×2640`，hierarchy 根 bounds `[0,0][1216,2640]`。**bounds 即像素坐标，无需缩放换算。**
2. **Pillow 11.3.0 已安装。**
3. **中文字体可用**：`/System/Library/Fonts/STHeiti Light.ttc`、`Hiragino Sans GB.ttc`、`/Library/Fonts/Arial Unicode.ttf`。组件名中文可正常渲染。
4. **名称字段覆盖现实**（27 个节点）：`resource-id` 仅 1 个有值（Compose 通病）；`content-desc` 5 个（图标：历史对话、记忆、麦克风、键盘、更多）；`text` 8 个（文字：厦门旅行、旅行、厦门…）。有意义的名字主要来自 `content-desc`（图标）和 `text`（文字）；可点击的一级容器 `View` 多半无语义名。

## 总体流程

```
ui.html (勾选项) ──POST /api/screenshot {type, annotate, options}──▶ server.py
                                                                      │ ① adb exec-out screencap -p   → 原图
                                                                      │ ② adb shell uiautomator dump   → 层级 XML
                                                                      │ ③ annotate.py 解析 + 渲染
                                                                      ▼
Figma canvas ◀──插入扁平 PNG────────────────────────── 返回 annotated 文件名
```

Figma 侧（`code.js`）逻辑**不变**，仍只插入一张图。

时序注意：原图与层级是两次设备操作，中间界面可能变化。两步**连续执行、尽量紧邻**（先 screencap 再立即 dump）。

## 面板 UI（ui.html）

Screenshot 区新增详细信息开关组：

```
☐ 详细信息                  ← 总开关，关闭时下方子项隐藏
   ☑ 组件尺寸   ☑ 组件名称   ☐ 组件间距
   层级：  ○ 仅一级   ◉ 一级+二级
```

- 默认：总开关**关闭**；展开后默认勾选「组件尺寸 + 组件名称」，间距默认不勾；层级默认 **一级+二级**。
- 勾选状态随截图请求发给 bridge：
  ```json
  { "type": "adb", "annotate": true,
    "options": { "size": true, "name": true, "spacing": false, "level": "all" } }
  ```
  - `level` 取值：`"primary"`（仅一级）| `"all"`（一级+二级）。
- 「详细信息」关闭时 `annotate=false`，走原有普通截图路径，行为完全不变。

## 标注规则

### 分层（按可点击性）

- **一级**：`clickable="true"` 或 `focusable="true"` 的容器，或顶层有意义容器（卡片、按钮、列表项）。
- **二级**：一级内部的叶子元素（无子节点的 TextView / ImageView / View）。
- **噪声过滤**（`_is_noise`）：先剔除对指代无意义的节点 —— 近全屏容器（宽、高均 ≥ 屏幕 90%，多为背景 / scrim）与退化细条（宽或高 < 4px）。被剔除的节点 `level=None`，不参与标注。
- 视觉：一级框线**粗**，二级框线**细**；颜色用调色板循环分配，保证相邻框不同色（参考图风格）。
- `level="primary"` 时只渲染一级；`level="all"` 时一级 + 二级都渲染。

### 尺寸

- `(x2 - x1) × (y2 - y1)`，设备物理像素，如 `162×162`。
- 勾选「组件尺寸」时，标签包含尺寸数字。

### 编号 ID（始终显示）

- 每个被标注的框左上角始终带一个全局序号 `#N`（按渲染顺序，从 1 起），作为与 agent 沟通时**指代组件的锚点**（"看组件 #7"）。
- ID 独立于三个勾选项，始终显示；每次截图重新编号（用于即时对话，不要求跨截图稳定）。

### 名称（仅真正的语义名）

- 优先级：`content-desc` → `resource-id`，取第一个非空值。**不回退到 `text`** —— 许多 App（如 Compose）逐字渲染文本为独立节点，回退 `text` 会产生大量逐字噪声标注。
- 两者皆空（多为容器 / 纯文本节点）：**只画框 + 编号 + 尺寸，不写名字**，不强凑 `class`。
- 勾选「组件名称」时，标签包含语义名。

### 间距（同容器内相邻组件 gap）

- 同一父容器下，子节点按位置排序，计算相邻两者之间的水平 / 垂直空隙：
  - 水平相邻：`next.x1 - cur.x2`
  - 垂直相邻：`next.y1 - cur.y2`
- gap 标在两组件中间，如 `←32→`。仅 gap > 0 时标注。
- 勾选「组件间距」时渲染。

### 标签样式

框左上角彩色底块 + 白字（同参考图）。底块颜色与所属框同色。标签内容顺序：`#N [语义名] [尺寸]`，例如 `#3 历史对话 162×162`，或无语义名时 `#12 182×161`。底块超出右边界时向左收回，避免被裁切。

## 代码结构

新增独立模块 **`bridge/annotate.py`**，纯逻辑与渲染分离，便于按现有 `unittest` 风格测试：

| 函数 | 类型 | 职责 |
|---|---|---|
| `parse_hierarchy(xml) -> list[Node]` | 纯函数 | 解析 XML，提取 bounds、名称（回退逻辑）、clickable/focusable、是否叶子、父子关系 |
| `classify_levels(nodes) -> None`（标记 primary/secondary） | 纯函数 | 按可点击性 + 叶子判定标层级 |
| `compute_gaps(nodes) -> list[Gap]` | 纯函数 | 同父相邻子组件的水平/垂直 gap |
| `render(image_path, nodes, gaps, options) -> bytes` | Pillow | 唯一依赖图像库的部分，按 options 画框/标签/gap |

`Node` 字段建议：`bounds(x1,y1,x2,y2)`、`name`、`level('primary'|'secondary')`、`clickable`、`focusable`、`is_leaf`、`parent`、`children`。

字体探测：按候选列表 `[STHeiti Light.ttc, Hiragino Sans GB.ttc, Arial Unicode.ttf]` 找第一个存在的；都没有则用 `ImageFont.load_default()`（中文可能显示方块，尺寸数字不受影响）。

### server.py 改动

- `_screenshot` 解析 body 中的 `annotate` / `options`，透传给 `_screenshot_adb`。
- `_screenshot_adb`：拿到原图后，若 `annotate` 为真：
  1. `adb shell uiautomator dump` + `adb pull` 取层级 XML（沿用 `subprocess.run` 风格、设超时）。
  2. `nodes = annotate.parse_hierarchy(xml)`；`annotate.classify_levels(nodes)`；`gaps = annotate.compute_gaps(nodes)`。
  3. `png = annotate.render(原图路径, nodes, gaps, options)`，保存 `screen_xxx_annotated.png`。
  4. 返回 `{"filename": "screen_xxx_annotated.png", "width", "height"}`（另存，原图保留）。

## 错误处理 / 降级

- `uiautomator dump` 失败 / 超时 → 返回**普通截图**，响应携带 `note: "未能获取层级，已返回原图"`，UI 状态栏提示。
- Pillow 缺失（本机已装，仍做判断）→ 同上降级 + 提示安装。
- 中文字体全部找不到 → 退英文/默认字体，尺寸数字仍正常。
- 解析得到 0 个可标注节点 → 返回原图 + 提示。

## 测试（stdlib unittest，沿用 bridge/test_*.py 风格）

新增 `bridge/test_annotate.py`，覆盖纯函数：

- `parse_hierarchy`：喂真实 fixture XML（取自实测 `window_dump.xml`），断言节点数、bounds 解析、名称回退（content-desc 优先于 text、容器留空）。
- `classify_levels`：断言 clickable/focusable 容器为 primary，其下叶子为 secondary。
- `compute_gaps`：构造相邻节点，断言水平/垂直 gap 数值与方向。
- `render` 不强制单测（依赖 Pillow/字体），可做冒烟：跑通不抛异常、输出非空 PNG。

fixture：将实测层级片段存为 `bridge/fixtures/window_dump_sample.xml`。

## 验收

1. 面板「详细信息」关闭 → 截图行为与现状完全一致。
2. 打开 + 勾选尺寸/名称，层级「一级+二级」→ 插入的图上：叶子组件标出 `content-desc`/`text` 名称（历史对话、厦门旅行）+ 尺寸；容器只标尺寸框。
3. 勾选间距 → 同排相邻组件间出现 gap 数值。
4. 层级切到「仅一级」→ 只剩一级容器框。
5. `python -m unittest`（在 bridge/）全绿。
