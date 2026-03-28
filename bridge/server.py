#!/usr/bin/env python3
"""Bridge server for Figma Whiteboard plugin.
Handles adb screenshots and serves images.

Usage: python server.py
"""

import json
import mimetypes
import os
import subprocess
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

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

    def _screenshot(self):
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
            fp.write_bytes(r.stdout)
            self._json({"filename": fn})
        except Exception as e:
            self._json({"error": str(e)})

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
