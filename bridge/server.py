#!/usr/bin/env python3
"""Bridge server for Figma Whiteboard plugin.
Handles adb screenshots and serves images.

Usage: python server.py
"""

import io
import json
import mimetypes
import os
import struct
import subprocess
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


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


def _image_dimensions(path):
    """Return (width, height) tuple if Pillow can open the file, else None."""
    try:
        from PIL import Image
        with Image.open(path) as img:
            return img.size
    except Exception:
        return None


PORT = 8767
IMAGES_DIR = Path(__file__).parent / "images"
IMAGES_DIR.mkdir(exist_ok=True)
EXPORTS_DIR = Path(__file__).parent / "exports"
EXPORTS_DIR.mkdir(exist_ok=True)


class BridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # quiet

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
            fname = path[len("/images/"):]
            fp = IMAGES_DIR / fname
            if fp.exists():
                self._file(fp)
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/api/screenshot":
            self._screenshot()
        elif path == "/api/export":
            self._export()
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

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

    @staticmethod
    def _raw_to_png(raw):
        """Convert raw RGBA screencap data to PNG using Pillow.
        Raw format: first 12 bytes = width(4) + height(4) + pixel_format(4),
        followed by RGBA pixel data.
        """
        try:
            from PIL import Image
        except ImportError:
            return None
        try:
            # Android raw screencap header: width, height, format (each 4 bytes LE)
            if len(raw) < 12:
                return None
            w = struct.unpack_from('<I', raw, 0)[0]
            h = struct.unpack_from('<I', raw, 4)[0]
            pixel_data = raw[12:]
            expected = w * h * 4  # RGBA
            if len(pixel_data) < expected:
                return None
            img = Image.frombytes('RGBA', (w, h), pixel_data[:expected])
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            return buf.getvalue()
        except Exception:
            return None

    def _export(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            data = json.loads(body)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            name = data.get("name", "frame")
            safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name)

            png_bytes = bytes(data["png"])
            json_str = json.dumps(data.get("json", {}), indent=2)

            png_path = EXPORTS_DIR / f"{safe_name}_{ts}.png"
            json_path = EXPORTS_DIR / f"{safe_name}_{ts}.json"
            png_path.write_bytes(png_bytes)
            json_path.write_text(json_str)

            # Copy prompt + file paths to clipboard via pbcopy
            clip_text = (
                f"请查看以下截图上标注的问题，并根据标注内容进行修复：\n"
                f"截图：{png_path}\n"
                f"标注信息：{json_path}"
            )
            try:
                subprocess.run(
                    ["pbcopy"], input=clip_text.encode("utf-8"),
                    timeout=3, check=True,
                )
                clipboard_ok = True
            except Exception:
                clipboard_ok = False

            self._json({
                "png_path": str(png_path),
                "json_path": str(json_path),
                "clipboard": clipboard_ok,
            })
        except Exception as e:
            self._json({"error": str(e)})

    def _file(self, fp):
        ct, _ = mimetypes.guess_type(str(fp))
        data = fp.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ct or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self._cors()
        self.end_headers()
        self.wfile.write(data)

    def _json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


if __name__ == "__main__":
    print(f"Bridge server: http://localhost:{PORT}")
    ThreadingHTTPServer(("0.0.0.0", PORT), BridgeHandler).serve_forever()
