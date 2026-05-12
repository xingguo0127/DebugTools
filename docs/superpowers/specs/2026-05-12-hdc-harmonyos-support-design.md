# HarmonyOS (hdc) Screenshot Support

**Date:** 2026-05-12
**Status:** Design approved

## Goal

Extend the Figma Whiteboard Bridge plugin to capture screenshots from HarmonyOS / OpenHarmony devices via `hdc`, in addition to the existing Android (`adb`) support. The UI dynamically shows the appropriate screenshot button(s) based on which devices are connected.

## Non-goals

- Selecting between multiple devices of the same type (e.g. two hdc targets) — v1 uses the default target.
- Exposing device IDs in the UI.
- Auto-installing `hdc` or `adb`.
- Changes to the Figma sandbox code (`code.js`) or manifest.

## Architecture

Three components, only two change:

```
ui.html  ──(GET /api/devices)──▶  server.py  ──▶  adb devices
         ──(POST /api/screenshot {type})─▶            hdc list targets
                                                       adb exec-out screencap
                                                       hdc shell snapshot_display
                                                            + hdc file recv
         ──(GET /images/<file>)──▶  bridge/images/
```

- **server.py** — new `/api/devices` endpoint, modified `/api/screenshot` to take `type`, new hdc screenshot flow.
- **ui.html** — dynamic button rendering driven by `/api/devices` response.
- **code.js / manifest.json** — unchanged.

## Backend changes (server.py)

### New endpoint: `GET /api/devices`

Returns connected devices grouped by transport:

```json
{ "adb": ["XJ7N18A4G7"], "hdc": ["ABCDEF1234567890"] }
```

Detection logic:

- **adb:** run `adb devices`. Parse output lines after the header. Keep entries where the second column is exactly `device` (skip `offline`, `unauthorized`).
- **hdc:** run `hdc list targets`. Each non-empty line is a target ID. Filter out the literal string `[Empty]` which hdc emits when no device is connected.
- If either binary is not on PATH (`FileNotFoundError`), treat that platform as having no devices — do not surface this as an error. Users may have installed only one toolchain.
- On any other subprocess error, return an empty list for that platform.

Response always contains both keys, even if empty.

### Modified endpoint: `POST /api/screenshot`

Request body (JSON): `{ "type": "adb" | "hdc" }`. If body is empty or `type` is missing, default to `"adb"` for backward compatibility with any cached UI.

Response on success:
```json
{ "filename": "screen_20260512_153000.jpeg", "width": 1080, "height": 2400 }
```

`width`/`height` are populated when Pillow is available (already an optional dep); omitted otherwise. UI handles both cases.

Response on failure: `{ "error": "<message>" }` — same shape as today.

### New method: `_screenshot_hdc()`

Flow:
1. Generate timestamped filename: `screen_<YYYYmmdd_HHMMSS>.jpeg`.
2. On device, run: `hdc shell snapshot_display -f /data/local/tmp/<filename>`.
3. Pull to bridge: `hdc file recv /data/local/tmp/<filename> <IMAGES_DIR>/<filename>`.
4. Cleanup on device: `hdc shell rm /data/local/tmp/<filename>` — best-effort, run even if recv failed.
5. If Pillow is importable, open the pulled file and read `(width, height)`; include in response.

Why this approach:
- `snapshot_display` is the standard command across HarmonyOS / OpenHarmony versions and outputs JPEG.
- hdc has no `exec-out`-style stream equivalent; recv-from-device is the canonical pattern.
- Per-shot timestamped filenames avoid clobbering when two screenshots overlap.

Errors to surface explicitly:
- `hdc` not on PATH → `{"error": "hdc not found in PATH"}`.
- `snapshot_display` non-zero exit → return stderr.
- `file recv` non-zero exit or destination file missing → return stderr (cleanup still runs).

### Existing `_screenshot()` (adb path)

Renamed conceptually to `_screenshot_adb()` (or kept inline) — same behavior as today. After writing the PNG, if Pillow is available, also read dimensions and add to the response.

## Frontend changes (ui.html)

### Replace static screenshot button with a container

Remove the hardcoded `<button id="btn-screenshot">Take Screenshot (adb)</button>` from the Screenshot section. Replace with:

```html
<div class="section">
  <div class="section-title">Screenshot</div>
  <div id="screenshot-buttons"></div>
</div>
```

### New `renderDeviceButtons(devices)`

Called by `checkConnection()` after a successful connection check. Fetches `/api/devices` and renders into `#screenshot-buttons`:

- `devices.adb.length > 0` → append `<button class="btn-primary">Take Screenshot (Android)</button>` wired to `takeScreenshot('adb')`.
- `devices.hdc.length > 0` → append `<button class="btn-primary">Take Screenshot (HarmonyOS)</button>` wired to `takeScreenshot('hdc')`.
- Both empty → render a single gray line: `No device detected. Connect a device and click Check Connection.`

Both buttons are stacked vertically (one per row) when both transports have devices, matching the existing full-width button style.

### `takeScreenshot(type)`

Takes a `type` parameter. POSTs `/api/screenshot` with `{ type }` as JSON body. Otherwise identical to current implementation.

Dimension handling:
- If response contains `width`/`height`, use them directly and skip PNG-header parsing.
- Otherwise, fall back to existing PNG-header read.
- If neither works, default 360 × 780 as today.

## Data flow (HarmonyOS path, end-to-end)

1. User clicks `Take Screenshot (HarmonyOS)`.
2. UI: `POST /api/screenshot { "type": "hdc" }`.
3. Server: runs `hdc shell snapshot_display -f /data/local/tmp/screen_<ts>.jpeg`.
4. Server: `hdc file recv` → `bridge/images/screen_<ts>.jpeg`.
5. Server: `hdc shell rm` cleanup.
6. Server: reads dimensions via Pillow (if installed).
7. Server: responds `{ "filename": "screen_<ts>.jpeg", "width": ..., "height": ... }`.
8. UI: `GET /images/<filename>` → byte array.
9. UI: `postMessage` to sandbox with bytes + dimensions.
10. `code.js`: creates image, inserts as rectangle on canvas — unchanged code path.

## Error handling summary

| Condition | Response |
|---|---|
| `hdc` not on PATH | `{"error": "hdc not found in PATH"}` (explicit FileNotFoundError check) |
| `adb` not on PATH | existing behavior unchanged — error bubbles up via the generic `except Exception` block |
| No matching device when screenshot called | `hdc`/`adb` stderr passed through |
| `snapshot_display` failure | stderr in error |
| `file recv` failure / missing file | stderr in error; cleanup still attempted |
| Pillow missing | dimensions omitted from response; UI falls back |

## Testing

Manual smoke tests:
1. Only Android connected: UI shows one button, screenshot works as before.
2. Only HarmonyOS connected: UI shows one HarmonyOS button, screenshot inserts correctly.
3. Both connected: UI shows both buttons, each works independently.
4. No device connected: UI shows the "no device detected" message.
5. `hdc` not installed: `/api/devices` returns `hdc: []` without error; only adb button (if any) appears.
6. Pillow not installed: hdc screenshot still works; canvas uses fallback 360×780 dimensions.

No automated tests — this is a small local-only tool.

## Out of scope / future

- Device picker UI when multiple targets of one type are connected.
- iOS support (would need `ios-deploy` / `idevicescreenshot`).
- Wireless adb / hdc.
