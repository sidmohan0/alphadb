#!/usr/bin/env python3
"""Tiny config server for trading-gate safety.yaml."""
import http.server
import json
import os
import subprocess

PORT = 8787
ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(ROOT, "config", "safety.yaml")
UI = os.path.join(ROOT, "config-ui.html")
RESTART_SCRIPT = os.path.join(ROOT, "scripts", "start-live-tmux.sh")


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # quiet

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/config":
            with open(CONFIG) as f:
                body = f.read()
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "text/yaml")
            self.end_headers()
            self.wfile.write(body.encode())
        elif self.path == "/":
            with open(UI) as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/config":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode()
            with open(CONFIG, "w") as f:
                f.write(body)
            self.send_response(200)
            self._cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True}).encode())
        elif self.path == "/restart":
            try:
                result = subprocess.run(
                    ["bash", RESTART_SCRIPT],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                ok = result.returncode == 0
                msg = result.stdout.strip() or result.stderr.strip()
                self.send_response(200 if ok else 500)
                self._cors()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": ok, "message": msg}).encode())
            except Exception as e:
                self.send_response(500)
                self._cors()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "message": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    print(f"Config UI: http://localhost:{PORT}")
    http.server.HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
