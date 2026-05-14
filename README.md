# Whiteboard Bridge

一个 Figma 插件 + 本地 HTTP 桥，把 **Android / HarmonyOS** 设备的实时截图直接插入 Figma 画板，方便在白板上对界面打标注、协作讨论。

## 工作原理

```
┌────────────────────┐    postMessage     ┌──────────────┐    HTTP    ┌──────────────────┐
│  code.js (Figma    │ ←───────────────→  │  ui.html     │ ←────────→ │  bridge/server.py │
│  Plugin Sandbox)   │                    │  (插件面板)   │            │  :8767            │
└────────────────────┘                    └──────────────┘            └──────────────────┘
         ↓                                                                     ↓
    canvas 上                                                            adb exec-out screencap
    插入图片                                                            hdc shell snapshot_display
```

- **`code.js`** — Figma 插件 sandbox，负责接收图片字节并在画板上放置 Rectangle。
- **`ui.html`** — 插件面板，调用 bridge HTTP API，触发截图。
- **`bridge/server.py`** — 本机 Python HTTP server（stdlib 实现，端口 8767），调用系统 CLI 工具截图后写到 `bridge/images/`。

## 支持的设备

| 平台 | 命令 | 输出格式 |
|---|---|---|
| Android | `adb exec-out screencap -p` | PNG |
| HarmonyOS / OpenHarmony | `hdc shell snapshot_display` + `hdc file recv` | JPEG |

UI 会自动检测连接的设备类型，动态显示对应的截图按钮。

## 准备工作

需要本机已经装好对应平台的工具：

```bash
# Android — Android SDK platform-tools
adb devices

# HarmonyOS — HarmonyOS SDK
hdc list targets
```

可选依赖：`pip3 install Pillow`（截图响应里附带宽高信息，UI 用于在画板上按正确比例放置；不装也能用，会回退到默认尺寸）。

## 使用

### 1. 启动 bridge server

```bash
./bridge/bridge.sh start     # 后台启动，日志写到 bridge/bridge.log
./bridge/bridge.sh status    # 查看状态
./bridge/bridge.sh stop      # 停止
./bridge/bridge.sh restart   # 重启
```

### 2. 在 Figma 加载插件

Figma → Menu → Plugins → Development → Import plugin from manifest → 选择本仓库的 `manifest.json`。

之后 Plugins → Development → Whiteboard Bridge 启动。

### 3. 工作流

1. 用 USB 把设备连到 Mac，确保 `adb devices` / `hdc list targets` 看得到。
2. Figma 里启动插件，点 **Check Connection**，连上 bridge。
3. 出现 **Take Screenshot (Android)** 或 **Take Screenshot (HarmonyOS)** 按钮，点击截图，图片会插入到当前 Figma 画板视图中心。
4. 换设备后点 **Refresh Devices** 重新检测。

## 项目结构

```
DebugTools/
├── manifest.json              # Figma 插件清单
├── code.js                    # Figma sandbox 代码
├── ui.html                    # 插件面板 UI
├── bridge/
│   ├── server.py              # Python HTTP bridge
│   ├── bridge.sh              # start/stop/restart/status 控制脚本
│   ├── test_device_parsers.py # adb/hdc 输出解析单元测试
│   ├── images/                # 截图存储（gitignored）
│   ├── bridge.pid             # 运行时 PID 文件（gitignored）
│   └── bridge.log             # 运行时日志（gitignored）
└── docs/superpowers/
    ├── specs/                 # 设计文档
    └── plans/                 # 实现计划
```

## 测试

```bash
cd bridge && python3 -m unittest test_device_parsers -v
```

## API

bridge server 暴露的 endpoint：

| Endpoint | 方法 | 用途 |
|---|---|---|
| `GET /api/images` | GET | 列出 `bridge/images/` 下的图片 |
| `GET /api/devices` | GET | 返回 `{adb: [...], hdc: [...]}`，列出连接的设备 UDID |
| `POST /api/screenshot` | POST | 截图，body `{"type": "adb"\|"hdc"}` |
| `GET /images/<filename>` | GET | 取图片字节 |
