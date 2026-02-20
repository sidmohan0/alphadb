#!/usr/bin/env python3
"""API server for the AlphaDB trading dashboard.

Serves the frontend and proxies requests to the trading gate via Unix socket.
Includes a WebSocket endpoint (/ws/terminal) that spawns Claude Code in a PTY.
"""
import atexit
import base64
import fcntl
import hashlib
import http.server
import json
import os
import pty
import select
import signal
import socket
import struct
import subprocess
import termios
import threading
import time
from collections import deque

PORT = 8787
ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(ROOT, "config", "safety.yaml")
STRATEGY_CONFIG = os.path.join(ROOT, "config", "strategies", "mean-reversion-funding.yaml")
DASHBOARD = os.path.join(ROOT, "dashboard.html")
GATE_SOCKET = os.environ.get("TRADING_GATE_SOCKET", "/tmp/trading-gate.sock")
RESTART_SCRIPT = os.path.join(ROOT, "scripts", "start-live-tmux.sh")
GATE_LOG = os.path.join(ROOT, "logs", "gate.log")
AGENT_LOG = os.path.join(ROOT, "logs", "agent.log")
AUDIT_LOG = os.path.join(ROOT, "data", "audit.log")
ENV_FILE = os.path.join(ROOT, ".env")


def gate_request(req: dict, timeout: float = 3.0) -> dict:
    """Send a JSON request to the trading gate and return the response."""
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(GATE_SOCKET)
        payload = json.dumps(req) + "\n"
        sock.sendall(payload.encode())
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
        sock.close()
        return json.loads(buf.decode().strip())
    except Exception as e:
        return {"error": str(e)}


def tail_file(path: str, lines: int = 80) -> str:
    """Read the last N lines of a file."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            block = min(size, lines * 200)
            f.seek(max(0, size - block))
            data = f.read().decode(errors="replace")
            return "\n".join(data.splitlines()[-lines:])
    except FileNotFoundError:
        return f"[file not found: {path}]"
    except Exception as e:
        return f"[error reading {path}: {e}]"


def check_process(name: str) -> bool:
    """Check if a process matching `name` is running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", name], capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


def read_env() -> dict:
    """Parse .env file into a dict."""
    env = {}
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip().strip("'\"")
    except FileNotFoundError:
        pass
    return env


# ── WebSocket helpers (RFC 6455) ──

class WebSocketConnection:
    """Minimal RFC 6455 WebSocket over an http.server request handler."""

    GUID = "258EAFA5-E914-47DA-95CA-5AB5-E911A5DB5A"  # not used inline
    OP_TEXT = 0x1
    OP_BINARY = 0x2
    OP_CLOSE = 0x8
    OP_PING = 0x9
    OP_PONG = 0xA

    def __init__(self, handler):
        self.rfile = handler.rfile
        self.wfile = handler.wfile
        self._lock = threading.Lock()
        self.closed = False

    @staticmethod
    def handshake(handler) -> "WebSocketConnection":
        key = handler.headers.get("Sec-WebSocket-Key", "")
        accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-5AB5E911A5DB").encode()).digest()
        ).decode()
        handler.send_response(101)
        handler.send_header("Upgrade", "websocket")
        handler.send_header("Connection", "Upgrade")
        handler.send_header("Sec-WebSocket-Accept", accept)
        handler.end_headers()
        return WebSocketConnection(handler)

    def read_frame(self):
        """Read one WebSocket frame. Returns (opcode, payload_bytes) or None."""
        try:
            b0b1 = self.rfile.read(2)
            if not b0b1 or len(b0b1) < 2:
                return None
            b0, b1 = b0b1[0], b0b1[1]
            opcode = b0 & 0x0F
            masked = b1 & 0x80
            length = b1 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self.rfile.read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self.rfile.read(8))[0]
            mask_key = self.rfile.read(4) if masked else None
            data = self.rfile.read(length) if length > 0 else b""
            if mask_key:
                data = bytes(b ^ mask_key[i % 4] for i, b in enumerate(data))
            return (opcode, data)
        except Exception:
            return None

    def send_frame(self, data: bytes, opcode=0x1):
        """Send a WebSocket frame."""
        if self.closed:
            return
        with self._lock:
            try:
                frame = bytearray()
                frame.append(0x80 | opcode)
                length = len(data)
                if length < 126:
                    frame.append(length)
                elif length < 65536:
                    frame.append(126)
                    frame.extend(struct.pack(">H", length))
                else:
                    frame.append(127)
                    frame.extend(struct.pack(">Q", length))
                frame.extend(data)
                self.wfile.write(bytes(frame))
                self.wfile.flush()
            except Exception:
                self.closed = True

    def send_text(self, text: str):
        self.send_frame(text.encode("utf-8"), self.OP_TEXT)

    def send_binary(self, data: bytes):
        self.send_frame(data, self.OP_BINARY)

    def send_close(self):
        self.send_frame(b"", self.OP_CLOSE)
        self.closed = True


# ── PTY Session ──

def find_claude_binary() -> str:
    """Locate the claude CLI binary."""
    # Check common locations
    candidates = [
        os.path.expanduser("~/.claude/local/claude"),
        "/usr/local/bin/claude",
        os.path.expanduser("~/.local/bin/claude"),
    ]
    # Also check via shutil.which
    import shutil
    w = shutil.which("claude")
    if w:
        candidates.insert(0, w)
    for c in candidates:
        if os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    # Fallback: search Application Support
    app_support = os.path.expanduser("~/Library/Application Support/Claude/claude-code")
    if os.path.isdir(app_support):
        for d in sorted(os.listdir(app_support), reverse=True):
            p = os.path.join(app_support, d, "claude")
            if os.path.isfile(p) and os.access(p, os.X_OK):
                return p
    raise FileNotFoundError("claude binary not found")


_pty_sessions = {}  # id -> PTYSession
_pty_lock = threading.Lock()
_session_counter = 0


class PTYSession:
    """Manages a single Claude Code process running in a PTY."""

    def __init__(self, session_id: str, name: str = "", cols: int = 120, rows: int = 30):
        self.session_id = session_id
        self.name = name or session_id
        self.created_at = time.time()
        self.pid = None
        self.fd = None
        self.alive = False
        self._start(cols, rows)

    def _start(self, cols, rows):
        claude_bin = find_claude_binary()
        env = os.environ.copy()
        # Remove CLAUDECODE to allow nesting
        env.pop("CLAUDECODE", None)
        env["TERM"] = "xterm-256color"
        env["COLORTERM"] = "truecolor"

        system_prompt = (
            "You are an embedded agent inside the AlphaDB trading dashboard. "
            "Key files: dashboard.html (frontend), dashboard-server.py (backend), "
            "config/safety.yaml (risk limits), config/strategies/ (strategy configs), "
            "logs/ (gate.log, agent.log), data/audit.log. "
            "The dashboard server runs on port 8787. "
            "You can modify any file in this project."
        )

        pid, fd = pty.fork()
        if pid == 0:
            # Child process
            os.chdir(ROOT)
            os.execve(claude_bin, [
                claude_bin,
                "--system-prompt", system_prompt,
                "--add-dir", ROOT,
            ], env)
        else:
            self.pid = pid
            self.fd = fd
            self.alive = True
            # Set initial terminal size
            self.resize(cols, rows)
            # Make fd non-blocking
            import fcntl as _fcntl
            flags = _fcntl.fcntl(fd, _fcntl.F_GETFL)
            _fcntl.fcntl(fd, _fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def resize(self, cols: int, rows: int):
        if self.fd is not None:
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self.fd, termios.TIOCSWINSZ, winsize)

    def read(self, size=4096) -> bytes:
        if self.fd is None:
            return b""
        try:
            return os.read(self.fd, size)
        except (OSError, IOError):
            return b""

    def write(self, data: bytes):
        if self.fd is not None:
            os.write(self.fd, data)

    def kill(self):
        self.alive = False
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
        if self.pid is not None:
            try:
                os.kill(self.pid, signal.SIGTERM)
                # Give it a moment, then force kill
                threading.Timer(2.0, self._force_kill).start()
            except OSError:
                pass

    def _force_kill(self):
        if self.pid:
            try:
                os.kill(self.pid, signal.SIGKILL)
            except OSError:
                pass
            try:
                os.waitpid(self.pid, os.WNOHANG)
            except Exception:
                pass


def cleanup_pty_sessions():
    with _pty_lock:
        for s in _pty_sessions.values():
            s.kill()
        _pty_sessions.clear()


atexit.register(cleanup_pty_sessions)


# ── Decision Engine ──

def parse_strategy_threshold():
    """Parse funding_zscore_entry from strategy YAML without PyYAML."""
    try:
        with open(STRATEGY_CONFIG) as f:
            in_params = False
            for line in f:
                stripped = line.strip()
                if stripped == "parameters:":
                    in_params = True
                    continue
                if in_params and stripped.startswith("funding_zscore_entry:"):
                    return float(stripped.split(":", 1)[1].strip())
                if in_params and not line.startswith(" "):
                    in_params = False
    except Exception:
        pass
    return 2.0  # default


_decision_cycles = deque(maxlen=500)
_decision_lock = threading.Lock()
_decision_cycle_counter = 0
_audit_offset = 0


def _read_new_audit_entries():
    """Read new JSON lines from audit.log since last offset."""
    global _audit_offset
    entries = []
    try:
        with open(AUDIT_LOG, "r") as f:
            f.seek(_audit_offset)
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
            _audit_offset = f.tell()
    except FileNotFoundError:
        pass
    except Exception:
        pass
    return entries


def _decision_engine_loop():
    """Background thread that mirrors the agent's 2s decision cycle."""
    global _decision_cycle_counter, _audit_offset

    threshold = parse_strategy_threshold()

    # Initialize audit offset to end of file
    try:
        with open(AUDIT_LOG, "r") as f:
            f.seek(0, 2)
            _audit_offset = f.tell()
    except Exception:
        _audit_offset = 0

    while True:
        _decision_cycle_counter += 1
        cycle_num = _decision_cycle_counter
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")

        # Query gate for market and portfolio data
        env = read_env()
        product = env.get("TRADING_GATE_PRODUCT", "BTC-USD")

        market_resp = gate_request({"request_type": "GetMarketData", "symbol": product}, timeout=1.5)
        portfolio_resp = gate_request({"request_type": "GetPortfolio"}, timeout=1.5)

        gate_reachable = "error" not in market_resp or "error" not in portfolio_resp

        # Extract market data
        mk = None
        if "error" not in market_resp:
            mk = market_resp.get("payload", market_resp)

        pf = None
        if "error" not in portfolio_resp:
            pf = portfolio_resp.get("payload", portfolio_resp)

        # Build market snapshot
        price = float(mk["price"]) if mk and "price" in mk else None
        funding_zscore = mk.get("funding_rate_zscore") if mk else None
        spread = mk.get("spread_pct") if mk else None
        volatility = mk.get("realized_volatility") if mk else None
        regime = mk.get("regime_id") if mk else None

        # Evaluate signal (mirrors strategy.rs:40-76)
        signal = "HOLD"
        planned_entry = None
        planned_stop = None
        strength = 0.0
        distance = None

        if funding_zscore is not None:
            distance = threshold - abs(funding_zscore)
            strength = min(abs(funding_zscore) / threshold, 2.0)

            if funding_zscore <= -threshold:
                signal = "BUY"
                if price is not None:
                    planned_entry = round(price * 0.999, 2)
                    planned_stop = round(planned_entry * 0.985, 2)
            elif funding_zscore >= threshold:
                signal = "SELL"
                if price is not None:
                    planned_entry = round(price * 1.001, 2)
                    planned_stop = round(planned_entry * 1.015, 2)

        # Determine action
        if not gate_reachable:
            action = "GATE_UNREACHABLE"
        elif signal in ("BUY", "SELL"):
            action = "SIGNAL_ACTIVE"
        else:
            action = "MONITORING"

        # Read new audit entries
        audit_events = _read_new_audit_entries()

        # If we have a signal but audit shows rejection, mark blocked
        if signal in ("BUY", "SELL") and any(
            e.get("decision") == "rejected" for e in audit_events
        ):
            action = "SIGNAL_BLOCKED"

        # Build cycle record
        record = {
            "cycle": cycle_num,
            "timestamp": timestamp,
            "market": {
                "price": price,
                "funding_zscore": funding_zscore,
                "spread": spread,
                "volatility": volatility,
                "regime": regime,
                "symbol": product,
            },
            "portfolio": {
                "account_value": pf.get("account_value") if pf else None,
                "cash": pf.get("available_cash") if pf else None,
                "positions": pf.get("open_position_count") if pf else None,
                "daily_pnl": pf.get("daily_pnl") if pf else None,
                "drawdown": pf.get("drawdown_from_peak") if pf else None,
            },
            "signal": signal,
            "signal_detail": {
                "funding_zscore": funding_zscore,
                "threshold": threshold,
                "distance_to_threshold": round(distance, 4) if distance is not None else None,
                "strength": round(strength, 4),
                "planned_entry": planned_entry,
                "planned_stop": planned_stop,
            },
            "action": action,
            "audit_events": audit_events,
        }

        with _decision_lock:
            _decision_cycles.append(record)

        time.sleep(2)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json_response(self, data, status=200):
        body = json.dumps(data)
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body.encode())

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]
        query = {}
        if "?" in self.path:
            for part in self.path.split("?", 1)[1].split("&"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    query[k] = v

        # WebSocket upgrade for terminal
        if path == "/ws/terminal":
            self._handle_ws_terminal(query.get("session"))
            return

        if path == "/api/sessions":
            with _pty_lock:
                sessions = []
                for s in _pty_sessions.values():
                    sessions.append({
                        "id": s.session_id,
                        "name": s.name,
                        "status": "running" if s.alive else "dead",
                        "created_at": s.created_at,
                    })
            self._json_response(sessions)
            return

        if path == "/":
            with open(DASHBOARD) as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body.encode())

        elif path == "/api/status":
            gate_up = os.path.exists(GATE_SOCKET) and check_process("trading-gate")
            agent_up = check_process("trading-agent")
            exchange = "unknown"
            product = "BTC-USD"
            dry_run = True
            env = read_env()
            exchange = env.get("TRADING_GATE_EXCHANGE", "coinbase_advanced")
            product = env.get("TRADING_GATE_PRODUCT", "BTC-USD")
            dry_run = env.get("TRADING_GATE_DRY_RUN", "true").lower() in ("true", "1", "yes")
            self._json_response({
                "gate": "running" if gate_up else "stopped",
                "agent": "running" if agent_up else "stopped",
                "exchange": exchange,
                "product": product,
                "dry_run": dry_run,
                "socket": GATE_SOCKET,
                "socket_exists": os.path.exists(GATE_SOCKET),
            })

        elif path == "/api/portfolio":
            resp = gate_request({"request_type": "GetPortfolio"})
            self._json_response(resp)

        elif path == "/api/market":
            env = read_env()
            product = env.get("TRADING_GATE_PRODUCT", "BTC-USD")
            resp = gate_request({"request_type": "GetMarketData", "symbol": product})
            self._json_response(resp)

        elif path == "/api/orders":
            resp = gate_request({"request_type": "GetOpenOrders"})
            self._json_response(resp)

        elif path == "/api/fills":
            since = "2020-01-01T00:00:00Z"
            resp = gate_request({"request_type": "GetFillHistory", "since": since})
            self._json_response(resp)

        elif path == "/api/config":
            try:
                with open(CONFIG) as f:
                    body = f.read()
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "text/yaml")
                self.end_headers()
                self.wfile.write(body.encode())
            except Exception as e:
                self._json_response({"error": str(e)}, 500)

        elif path == "/api/strategy":
            try:
                with open(STRATEGY_CONFIG) as f:
                    body = f.read()
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "text/yaml")
                self.end_headers()
                self.wfile.write(body.encode())
            except Exception as e:
                self._json_response({"error": str(e)}, 500)

        elif path == "/api/logs/gate":
            self._json_response({"log": tail_file(GATE_LOG)})

        elif path == "/api/logs/agent":
            self._json_response({"log": tail_file(AGENT_LOG)})

        elif path == "/api/logs/audit":
            self._json_response({"log": tail_file(AUDIT_LOG)})

        elif path == "/api/env":
            env = read_env()
            safe_env = {k: v for k, v in env.items()
                        if "SECRET" not in k and "KEY" not in k and "PASSPHRASE" not in k}
            self._json_response(safe_env)

        elif path == "/api/decisions/latest":
            with _decision_lock:
                if _decision_cycles:
                    self._json_response(_decision_cycles[-1])
                else:
                    self._json_response({"cycle": 0, "signal": "HOLD", "action": "INITIALIZING"})

        elif path == "/api/decisions":
            since = int(query.get("since", "0"))
            with _decision_lock:
                results = [d for d in _decision_cycles if d["cycle"] > since]
            # Cap at 100
            self._json_response(results[-100:])

        else:
            self.send_response(404)
            self.end_headers()

    def _handle_ws_terminal(self, session_id=None):
        """Handle WebSocket connection for embedded terminal.

        If session_id is provided, reattach to an existing PTY session.
        Otherwise create a new one (legacy behavior).
        """
        upgrade = self.headers.get("Upgrade", "").lower()
        if upgrade != "websocket":
            self.send_response(400)
            self.end_headers()
            return

        ws = WebSocketConnection.handshake(self)

        # Determine whether to reattach or create new
        reattach = False
        session = None
        if session_id:
            with _pty_lock:
                session = _pty_sessions.get(session_id)
            if session and session.alive:
                reattach = True
            else:
                ws.send_text(f"\r\nError: session '{session_id}' not found or dead\r\n")
                ws.send_close()
                return
        else:
            # Legacy: create a new session on the fly
            global _session_counter
            _session_counter += 1
            session_id = f"session-{_session_counter}"
            name = f"Session {_session_counter}"
            try:
                session = PTYSession(session_id, name=name)
            except FileNotFoundError as e:
                ws.send_text(f"\r\nError: {e}\r\n")
                ws.send_close()
                return
            with _pty_lock:
                _pty_sessions[session_id] = session

        stop_event = threading.Event()

        def pty_reader():
            """Read from PTY, send to WebSocket."""
            while not stop_event.is_set() and session.alive:
                try:
                    r, _, _ = select.select([session.fd], [], [], 0.1)
                    if r:
                        data = session.read()
                        if data:
                            ws.send_binary(data)
                        else:
                            break
                except Exception:
                    break
            stop_event.set()

        reader_thread = threading.Thread(target=pty_reader, daemon=True)
        reader_thread.start()

        # Main loop: read from WebSocket, write to PTY
        try:
            while not stop_event.is_set():
                frame = ws.read_frame()
                if frame is None:
                    break
                opcode, data = frame
                if opcode == WebSocketConnection.OP_CLOSE:
                    break
                elif opcode == WebSocketConnection.OP_PING:
                    ws.send_frame(data, WebSocketConnection.OP_PONG)
                elif opcode in (WebSocketConnection.OP_TEXT, WebSocketConnection.OP_BINARY):
                    # Check for control messages (resize)
                    if opcode == WebSocketConnection.OP_TEXT:
                        try:
                            msg = json.loads(data.decode("utf-8"))
                            if msg.get("type") == "resize":
                                session.resize(msg.get("cols", 120), msg.get("rows", 30))
                                continue
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            pass
                    # Regular input → PTY
                    if session.alive:
                        session.write(data)
        except Exception:
            pass
        finally:
            stop_event.set()
            # On disconnect, do NOT kill the session — it persists for reattach.
            # Only close the WebSocket side.
            try:
                ws.send_close()
            except Exception:
                pass
            reader_thread.join(timeout=2)

    def do_DELETE(self):
        path = self.path.split("?")[0]

        # DELETE /api/sessions/<id>
        if path.startswith("/api/sessions/"):
            session_id = path.split("/api/sessions/", 1)[1]
            with _pty_lock:
                session = _pty_sessions.pop(session_id, None)
            if session:
                session.kill()
                self._json_response({"ok": True})
            else:
                self._json_response({"error": "session not found"}, 404)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        path = self.path.split("?")[0]
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode() if length > 0 else ""

        if path == "/api/sessions":
            global _session_counter
            _session_counter += 1
            session_id = f"session-{_session_counter}"
            name = f"Session {_session_counter}"
            try:
                session = PTYSession(session_id, name=name)
                with _pty_lock:
                    _pty_sessions[session_id] = session
                self._json_response({
                    "id": session_id,
                    "name": name,
                    "status": "running",
                    "created_at": session.created_at,
                })
            except FileNotFoundError as e:
                self._json_response({"error": str(e)}, 500)
            return

        elif path == "/api/config":
            with open(CONFIG, "w") as f:
                f.write(body)
            self._json_response({"ok": True})

        elif path == "/api/restart":
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
                self._json_response({"ok": ok, "message": msg}, 200 if ok else 500)
            except Exception as e:
                self._json_response({"ok": False, "message": str(e)}, 500)

        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    # Start decision engine background thread
    decision_thread = threading.Thread(target=_decision_engine_loop, daemon=True)
    decision_thread.start()
    print(f"AlphaDB Dashboard: http://localhost:{PORT}")
    print("Decision engine started (2s cycle)")
    server = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        cleanup_pty_sessions()
        server.shutdown()
