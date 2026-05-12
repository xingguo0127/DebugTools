# HarmonyOS (hdc) Screenshot Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add HarmonyOS / OpenHarmony device screenshot support to the Figma Whiteboard Bridge plugin via `hdc`, in addition to the existing `adb` flow.

**Architecture:** Server.py gains a `/api/devices` endpoint that reports connected adb + hdc devices; the existing `/api/screenshot` endpoint accepts a `type` parameter (`"adb"` or `"hdc"`) and dispatches accordingly. The Figma UI fetches `/api/devices` after connection check and dynamically renders one or both screenshot buttons. The hdc flow uses `hdc shell snapshot_display -f <path>` followed by `hdc file recv` to pull the JPEG into `bridge/images/`. Pillow is used (when available) to read JPEG dimensions and return them in the screenshot response, removing the UI's reliance on PNG-header parsing.

**Tech Stack:** Python 3 stdlib (http.server, subprocess), optional Pillow, vanilla JS in ui.html. Tests use `unittest` from stdlib — no new dependencies.

---

## File Structure

- `bridge/server.py` (modify) — add module-level parser functions, add `/api/devices` route + handler, refactor `_screenshot` to dispatch by type, add `_screenshot_hdc` + `_image_dimensions` helper.
- `bridge/test_device_parsers.py` (create) — unit tests for the two parser functions. Lives next to `server.py` so the import is `from server import ...`.
- `ui.html` (modify) — replace the static screenshot button with a dynamic container; add `refreshDevices()`; update `takeScreenshot` to accept a `type` parameter and use server-provided dimensions.

`code.js` and `manifest.json` are unchanged.

---

## Task 1: Device parser functions + unit tests

Pure functions that parse `adb devices` and `hdc list targets` output. TDD applies cleanly here: outputs are deterministic strings, no I/O.

**Files:**
- Create: `bridge/test_device_parsers.py`
- Modify: `bridge/server.py` (add two module-level functions near the top, after imports)

- [ ] **Step 1: Write the failing tests**

Create `bridge/test_device_parsers.py`:

```python
import unittest
from server import parse_adb_devices, parse_hdc_targets


class TestParseAdbDevices(unittest.TestCase):
    def test_empty_list(self):
        out = "List of devices attached\n\n"
        self.assertEqual(parse_adb_devices(out), [])

    def test_single_device(self):
        out = "List of devices attached\nXJ7N18A4G7\tdevice\n"
        self.assertEqual(parse_adb_devices(out), ["XJ7N18A4G7"])

    def test_skips_offline_and_unauthorized(self):
        out = (
            "List of devices attached\n"
            "XJ7N18A4G7\tdevice\n"
            "emulator-5554\toffline\n"
            "ABC123\tunauthorized\n"
        )
        self.assertEqual(parse_adb_devices(out), ["XJ7N18A4G7"])

    def test_multiple_devices(self):
        out = (
            "List of devices attached\n"
            "DEV1\tdevice\n"
            "DEV2\tdevice\n"
        )
        self.assertEqual(parse_adb_devices(out), ["DEV1", "DEV2"])


class TestParseHdcTargets(unittest.TestCase):
    def test_empty_marker(self):
        self.assertEqual(parse_hdc_targets("[Empty]\n"), [])

    def test_blank_input(self):
        self.assertEqual(parse_hdc_targets(""), [])

    def test_single_target(self):
        self.assertEqual(parse_hdc_targets("ABCDEF123\n"), ["ABCDEF123"])

    def test_multiple_targets(self):
        out = "ABCDEF123\nGHIJKL456\n"
        self.assertEqual(parse_hdc_targets(out), ["ABCDEF123", "GHIJKL456"])

    def test_strips_blank_lines(self):
        out = "\nABCDEF123\n\n"
        self.assertEqual(parse_hdc_targets(out), ["ABCDEF123"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd bridge && python -m unittest test_device_parsers -v`
Expected: ImportError — `cannot import name 'parse_adb_devices' from 'server'`.

- [ ] **Step 3: Implement the parsers**

In `bridge/server.py`, immediately after the `from urllib.parse import urlparse` line, add:

```python


def parse_adb_devices(stdout):
    """Parse `adb devices` output. Returns list of device IDs whose status is 'device'."""
    devices = []
    for line in stdout.splitlines()[1:]:  # skip "List of devices attached" header
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def parse_hdc_targets(stdout):
    """Parse `hdc list targets` output. Returns list of connected target IDs."""
    targets = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line or line == "[Empty]":
            continue
        targets.append(line)
    return targets
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd bridge && python -m unittest test_device_parsers -v`
Expected: 9 tests, all OK.

- [ ] **Step 5: Commit**

```bash
git add bridge/server.py bridge/test_device_parsers.py
git commit -m "feat(bridge): add adb/hdc device list parsers + unit tests"
```

---

## Task 2: `/api/devices` endpoint

Wire the parsers into an HTTP endpoint that the UI can call to learn what's connected. Runs both `adb devices` and `hdc list targets`; treats missing binaries as "no devices on that transport" rather than errors.

**Files:**
- Modify: `bridge/server.py` — add `_devices` method, register route in `do_GET`.

- [ ] **Step 1: Add the `_devices` handler**

In `bridge/server.py`, inside class `BridgeHandler`, add this method (place it just below `do_OPTIONS`, before `_screenshot`):

```python
    def _devices(self):
        adb_list = []
        hdc_list = []
        try:
            r = subprocess.run(
                ["adb", "devices"],
                capture_output=True, timeout=5, text=True,
            )
            if r.returncode == 0:
                adb_list = parse_adb_devices(r.stdout)
        except FileNotFoundError:
            pass
        except Exception:
            pass
        try:
            r = subprocess.run(
                ["hdc", "list", "targets"],
                capture_output=True, timeout=5, text=True,
            )
            if r.returncode == 0:
                hdc_list = parse_hdc_targets(r.stdout)
        except FileNotFoundError:
            pass
        except Exception:
            pass
        self._json({"adb": adb_list, "hdc": hdc_list})
```

- [ ] **Step 2: Register the route in `do_GET`**

In `bridge/server.py`, in `do_GET`, change:

```python
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/images":
            imgs = []
            for f in sorted(IMAGES_DIR.iterdir()):
                if f.suffix.lower() in ('.png', '.jpg', '.jpeg'):
                    imgs.append({"name": f.name, "timestamp": os.path.getmtime(f)})
            self._json(imgs)
        elif path.startswith("/images/"):
```

to:

```python
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/images":
            imgs = []
            for f in sorted(IMAGES_DIR.iterdir()):
                if f.suffix.lower() in ('.png', '.jpg', '.jpeg'):
                    imgs.append({"name": f.name, "timestamp": os.path.getmtime(f)})
            self._json(imgs)
        elif path == "/api/devices":
            self._devices()
        elif path.startswith("/images/"):
```

- [ ] **Step 3: Smoke test the endpoint**

Start the server (kill any running one first):

```bash
pkill -f "python.*bridge/server.py" 2>/dev/null; cd bridge && python server.py &
sleep 1
curl -s http://localhost:8767/api/devices
```

Expected: JSON like `{"adb": [...], "hdc": [...]}` (lists may be empty if no devices connected — that's fine, what matters is the shape). No errors thrown when neither tool is installed.

Stop the server: `pkill -f "python.*bridge/server.py"`.

- [ ] **Step 4: Commit**

```bash
git add bridge/server.py
git commit -m "feat(bridge): add /api/devices endpoint reporting adb + hdc targets"
```

---

## Task 3: Refactor screenshot endpoint to dispatch by type + return dimensions

Read the request body to extract `type`; dispatch to `_screenshot_adb` (renamed from current `_screenshot`) or `_screenshot_hdc` (added in Task 4). Add an `_image_dimensions` helper used by both paths.

**Files:**
- Modify: `bridge/server.py`.

- [ ] **Step 1: Add the `_image_dimensions` helper**

In `bridge/server.py`, add this module-level function just below the existing `parse_hdc_targets` function (added in Task 1):

```python


def _image_dimensions(path):
    """Return (width, height) tuple if Pillow can open the file, else None."""
    try:
        from PIL import Image
        with Image.open(path) as img:
            return img.size
    except Exception:
        return None
```

- [ ] **Step 2: Rename `_screenshot` to `_screenshot_adb` and add dimensions to its response**

In `bridge/server.py`, find the existing method `def _screenshot(self):`. Rename it to `_screenshot_adb` and modify the success response to include dimensions. Replace the entire method body:

```python
    def _screenshot_adb(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fn = f"screen_{ts}.png"
        fp = IMAGES_DIR / fn
        try:
            r = subprocess.run(
                ["adb", "exec-out", "screencap", "-p"],
                capture_output=True, timeout=10,
            )
            if r.returncode != 0:
                self._json({"error": f"adb: {r.stderr.decode()}"})
                return
            raw = r.stdout
            if len(raw) < 8:
                self._json({"error": "screencap returned empty data"})
                return
            png_start = raw.find(b'\x89PNG')
            if png_start >= 0:
                fp.write_bytes(raw[png_start:])
            else:
                png_bytes = self._raw_to_png(raw)
                if png_bytes is None:
                    self._json({"error": "screencap output is not PNG and could not be converted. "
                                         "Try: pip install Pillow"})
                    return
                fp.write_bytes(png_bytes)
            resp = {"filename": fn}
            dims = _image_dimensions(fp)
            if dims:
                resp["width"], resp["height"] = dims
            self._json(resp)
        except Exception as e:
            self._json({"error": str(e)})
```

- [ ] **Step 3: Add a new dispatcher `_screenshot` that reads body and routes by type**

In `bridge/server.py`, immediately above the renamed `_screenshot_adb`, insert:

```python
    def _screenshot(self):
        device_type = "adb"
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 0:
                body = self.rfile.read(length)
                data = json.loads(body)
                device_type = data.get("type", "adb")
        except Exception:
            device_type = "adb"

        if device_type == "hdc":
            self._screenshot_hdc()
        else:
            self._screenshot_adb()
```

(The `do_POST` routing still calls `self._screenshot()` — no change needed there. `_screenshot_hdc` is added in Task 4; calling it before then would AttributeError, but the route is only hit when type=="hdc", so adb path still works through this task.)

- [ ] **Step 4: Smoke test the adb path still works**

If you have an Android device connected:

```bash
pkill -f "python.*bridge/server.py" 2>/dev/null; cd bridge && python server.py &
sleep 1
curl -s -X POST http://localhost:8767/api/screenshot -H 'Content-Type: application/json' -d '{"type":"adb"}'
pkill -f "python.*bridge/server.py"
```

Expected: JSON with `filename` (and `width`/`height` if Pillow installed). A new `screen_*.png` appears in `bridge/images/`.

If no Android device available, skip the live test — Task 7 covers full manual verification.

- [ ] **Step 5: Commit**

```bash
git add bridge/server.py
git commit -m "refactor(bridge): split screenshot endpoint into adb/hdc dispatcher + add response dimensions"
```

---

## Task 4: hdc screenshot path

Capture a screenshot on the HarmonyOS device, pull it via `hdc file recv`, clean up the on-device file, optionally read dimensions.

**Files:**
- Modify: `bridge/server.py`.

- [ ] **Step 1: Add `_screenshot_hdc` and `_hdc_cleanup` methods**

In `bridge/server.py`, inside class `BridgeHandler`, immediately after the `_screenshot_adb` method, add:

```python
    def _screenshot_hdc(self):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fn = f"screen_{ts}.jpeg"
        device_path = f"/data/local/tmp/{fn}"
        fp = IMAGES_DIR / fn
        try:
            r = subprocess.run(
                ["hdc", "shell", "snapshot_display", "-f", device_path],
                capture_output=True, timeout=15, text=True,
            )
            if r.returncode != 0:
                self._json({"error": f"hdc snapshot_display: {(r.stderr or r.stdout).strip()}"})
                self._hdc_cleanup(device_path)
                return
            r = subprocess.run(
                ["hdc", "file", "recv", device_path, str(fp)],
                capture_output=True, timeout=30, text=True,
            )
            if r.returncode != 0 or not fp.exists():
                self._json({"error": f"hdc file recv: {(r.stderr or r.stdout).strip()}"})
                self._hdc_cleanup(device_path)
                return
            self._hdc_cleanup(device_path)
            resp = {"filename": fn}
            dims = _image_dimensions(fp)
            if dims:
                resp["width"], resp["height"] = dims
            self._json(resp)
        except FileNotFoundError:
            self._json({"error": "hdc not found in PATH"})
        except Exception as e:
            self._json({"error": str(e)})

    def _hdc_cleanup(self, device_path):
        try:
            subprocess.run(
                ["hdc", "shell", "rm", device_path],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass
```

- [ ] **Step 2: Smoke test (if HarmonyOS device available)**

```bash
pkill -f "python.*bridge/server.py" 2>/dev/null; cd bridge && python server.py &
sleep 1
curl -s -X POST http://localhost:8767/api/screenshot -H 'Content-Type: application/json' -d '{"type":"hdc"}'
pkill -f "python.*bridge/server.py"
```

Expected: JSON with `filename` (e.g. `screen_20260512_153000.jpeg`) and optionally `width`/`height`. A JPEG appears in `bridge/images/`.

If `hdc` is missing: response is `{"error": "hdc not found in PATH"}`. That's the correct behavior; verify it.

If no HarmonyOS device but hdc installed: response surfaces the hdc stderr (commonly "[Fail]No any target"). Also correct.

- [ ] **Step 3: Commit**

```bash
git add bridge/server.py
git commit -m "feat(bridge): add hdc screenshot path using snapshot_display + file recv"
```

---

## Task 5: UI — `takeScreenshot` signature accepts type + uses response dimensions

Change `takeScreenshot()` to take `(type, btn)` and POST a JSON body. Use server-provided `width`/`height` when present; fall back to existing PNG-header parsing; final fallback to 360 × 780. Also update the existing static button's onclick to match the new signature (one task later, Task 6, replaces the static button entirely).

**Files:**
- Modify: `ui.html`.

- [ ] **Step 1: Replace `takeScreenshot` and update the static button's onclick**

In `ui.html`, find and replace the entire current `takeScreenshot` function (lines roughly 105–154 of the existing file — the function starting `async function takeScreenshot() {` through its closing brace) with:

```javascript
async function takeScreenshot(type, btn) {
  setStatus('Taking screenshot...');
  btn.disabled = true;

  try {
    const resp = await fetch(getUrl() + '/api/screenshot', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type }),
      signal: AbortSignal.timeout(30000)
    });
    const data = await resp.json();
    if (data.error) {
      setStatus('Screenshot failed: ' + data.error, 'error');
      btn.disabled = false;
      return;
    }

    // Fetch the image bytes
    const imgResp = await fetch(getUrl() + '/images/' + data.filename);
    const imgBuf = await imgResp.arrayBuffer();
    const bytes = new Uint8Array(imgBuf);

    // Determine display dimensions on the Figma canvas
    let w = 360, h = 780;
    if (data.width && data.height) {
      const scale = 360 / data.width;
      w = 360;
      h = Math.round(data.height * scale);
    } else if (bytes[0] === 0x89 && bytes[1] === 0x50) {
      // PNG header fallback
      const dv = new DataView(imgBuf);
      const imgW = dv.getUint32(16);
      const imgH = dv.getUint32(20);
      const scale = 360 / imgW;
      w = 360;
      h = Math.round(imgH * scale);
    }

    parent.postMessage({ pluginMessage: {
      type: 'insert-screenshot',
      data: Array.from(bytes),
      filename: data.filename,
      width: w,
      height: h
    }}, '*');

    setStatus('Screenshot: ' + data.filename, 'success');
  } catch (e) {
    setStatus('Error: ' + e.message, 'error');
  }
  btn.disabled = false;
}
```

- [ ] **Step 2: Update the static button's onclick to pass the new arguments**

In `ui.html`, find this line:

```html
  <button class="btn-primary" id="btn-screenshot" onclick="takeScreenshot()">Take Screenshot (adb)</button>
```

Replace with:

```html
  <button class="btn-primary" id="btn-screenshot" onclick="takeScreenshot('adb', this)">Take Screenshot (adb)</button>
```

(Task 6 will replace this static button entirely; this interim edit keeps the file in a working state if you stop between tasks.)

- [ ] **Step 3: Smoke test (if Figma + Android device available)**

Open Figma, run the plugin, click "Take Screenshot (adb)". Verify a screenshot is inserted into the canvas at sane dimensions.

If not testable now, defer to Task 7.

- [ ] **Step 4: Commit**

```bash
git add ui.html
git commit -m "refactor(ui): takeScreenshot accepts type + uses server-provided dimensions"
```

---

## Task 6: UI — dynamic button rendering driven by `/api/devices`

Replace the static screenshot button with a container that's populated based on what `/api/devices` reports. Called automatically when `checkConnection` succeeds.

**Files:**
- Modify: `ui.html`.

- [ ] **Step 1: Replace the static button with a container**

In `ui.html`, find the Screenshot section:

```html
<div class="section">
  <div class="section-title">Screenshot</div>
  <button class="btn-primary" id="btn-screenshot" onclick="takeScreenshot('adb', this)">Take Screenshot (adb)</button>
</div>
```

Replace with:

```html
<div class="section">
  <div class="section-title">Screenshot</div>
  <div id="screenshot-buttons"></div>
</div>
```

- [ ] **Step 2: Add `refreshDevices()` and call it from `checkConnection`**

In `ui.html`, find the `checkConnection` function. Replace its entire body with:

```javascript
async function checkConnection() {
  try {
    const resp = await fetch(getUrl() + '/api/images', { signal: AbortSignal.timeout(3000) });
    if (resp.ok) {
      bridgeOk = true;
      dotEl.className = 'dot on';
      connText.textContent = 'Connected';
      setStatus('Bridge server is running', 'success');
      await refreshDevices();
    } else {
      throw new Error('Server returned ' + resp.status);
    }
  } catch (e) {
    bridgeOk = false;
    dotEl.className = 'dot off';
    connText.textContent = 'Disconnected';
    setStatus('Cannot reach bridge: ' + e.message, 'error');
    document.getElementById('screenshot-buttons').innerHTML = '';
  }
}

async function refreshDevices() {
  const container = document.getElementById('screenshot-buttons');
  container.innerHTML = '';
  try {
    const resp = await fetch(getUrl() + '/api/devices', { signal: AbortSignal.timeout(3000) });
    const devices = await resp.json();
    const hasAdb = devices.adb && devices.adb.length > 0;
    const hasHdc = devices.hdc && devices.hdc.length > 0;
    if (hasAdb) {
      const btn = document.createElement('button');
      btn.className = 'btn-primary';
      btn.textContent = 'Take Screenshot (Android)';
      btn.onclick = () => takeScreenshot('adb', btn);
      container.appendChild(btn);
    }
    if (hasHdc) {
      const btn = document.createElement('button');
      btn.className = 'btn-primary';
      btn.textContent = 'Take Screenshot (HarmonyOS)';
      btn.onclick = () => takeScreenshot('hdc', btn);
      container.appendChild(btn);
    }
    if (!hasAdb && !hasHdc) {
      const msg = document.createElement('div');
      msg.style.cssText = 'font-size:12px;color:#999;padding:6px 0;';
      msg.textContent = 'No device detected. Connect a device and click Check Connection.';
      container.appendChild(msg);
    }
  } catch (e) {
    container.innerHTML = '';
  }
}
```

(`refreshDevices` must be defined alongside `checkConnection` in the same `<script>` block — placement just before or after `checkConnection` is fine.)

- [ ] **Step 3: Smoke test by opening the plugin in Figma**

Load the plugin in Figma with the bridge server running. Click "Check Connection". Verify:
- With one device connected, one button appears with the correct label.
- With no devices connected, the "No device detected" message appears.

- [ ] **Step 4: Commit**

```bash
git add ui.html
git commit -m "feat(ui): render screenshot buttons dynamically based on /api/devices"
```

---

## Task 7: Manual smoke test checklist

End-to-end verification across the scenarios from the spec. No code; just run each scenario and confirm expected behavior. Mark each box as you go.

**Setup:** Ensure `bridge/server.py` is running (`cd bridge && python server.py`), the plugin is loaded in Figma, and you can connect/disconnect adb and hdc devices.

- [ ] **Only Android connected:** UI shows one "Take Screenshot (Android)" button. Click it → screenshot inserts on canvas at correct aspect ratio.

- [ ] **Only HarmonyOS connected:** UI shows one "Take Screenshot (HarmonyOS)" button. Click it → JPEG appears in `bridge/images/`, inserts on canvas at correct aspect ratio. Verify no leftover file at `/data/local/tmp/screen_*.jpeg` on device (`hdc shell ls /data/local/tmp/`).

- [ ] **Both connected:** UI shows both buttons. Each works independently. Order: Android above HarmonyOS.

- [ ] **No device connected:** UI shows "No device detected..." message in place of buttons.

- [ ] **`hdc` not installed (uninstall or `PATH` strip):** `/api/devices` returns `{"adb": [...], "hdc": []}` with no error in server logs. UI behaves as if no HarmonyOS device.

- [ ] **Pillow not installed:** `pip uninstall Pillow` temporarily. Take an hdc screenshot — still works, just no `width`/`height` in response; canvas uses 360 × 780 fallback (aspect may be off, image still legible). Reinstall Pillow after test.

- [ ] **Snapshot_display failure simulation:** With hdc installed but no device, click "Take Screenshot (HarmonyOS)" via a stale UI button (force by editing in DevTools, or test by disconnecting device after page load). Verify error message surfaces in the status area rather than silently failing.

- [ ] **Final commit (only if any docs / fixes resulted from smoke testing):**

```bash
git add -A
git commit -m "fix: address issues found during hdc smoke testing"
```

---

## Notes for the implementer

- Run `python -m unittest test_device_parsers -v` from `bridge/` after every change to server.py.
- The bridge server has no auto-reload — kill and restart between server.py edits.
- All hdc commands are best-effort; never let `_hdc_cleanup` failures propagate.
- Do not change `code.js` or `manifest.json` — both Figma-side files work unchanged.
