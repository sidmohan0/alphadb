"""Live-first AlphaDB operator console."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs

from alphadb.config import Settings, settings_from_env
from alphadb.dashboard.auth import DashboardAuthConfig, evaluate_access
from alphadb.health import HealthReport, collect_health
from alphadb.live_runtime import (
    FAIR_VALUE_LIVE_STRATEGY,
    LiveRunStatusRepository,
    LiveRuntimeConfig,
    LiveRuntimeConfigRepository,
)


ConfigRepositoryFactory = Callable[[str], LiveRuntimeConfigRepository]
StatusRepositoryFactory = Callable[[str], LiveRunStatusRepository]
HealthCollector = Callable[[Settings], HealthReport]


@dataclass(frozen=True)
class DashboardService:
    settings: Settings
    config_repository_factory: ConfigRepositoryFactory = LiveRuntimeConfigRepository
    status_repository_factory: StatusRepositoryFactory = LiveRunStatusRepository
    health_collector: HealthCollector = collect_health

    def live_payload(self) -> dict[str, Any]:
        config_repository = self.config_repository_factory(self.settings.database_url)
        active = config_repository.seed_defaults(strategy=FAIR_VALUE_LIVE_STRATEGY)
        history = config_repository.recent_revisions(strategy=FAIR_VALUE_LIVE_STRATEGY, limit=6)
        status_repository = self.status_repository_factory(self.settings.database_url)
        latest_status = status_repository.latest_status(strategy=FAIR_VALUE_LIVE_STRATEGY)
        live_status = latest_status.as_dict()
        live_status.pop("summary", None)
        report = self.health_collector(self.settings)
        return {
            "health": {
                "ok": report.ok,
                "environment": report.environment,
                "generated_at_utc": report.generated_at_utc.isoformat(),
                "components": report.as_rows(),
            },
            "active_config": active.as_dict(),
            "config_history": [revision.as_dict() for revision in history],
            "live_status": live_status,
            "recent_runs": status_repository.recent_details(
                strategy=FAIR_VALUE_LIVE_STRATEGY,
                limit=8,
            ),
        }

    def save_config(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        config_repository = self.config_repository_factory(self.settings.database_url)
        current = config_repository.seed_defaults(strategy=FAIR_VALUE_LIVE_STRATEGY).config
        config = LiveRuntimeConfig.from_payload(payload, current=current)
        saved = config_repository.save_config(
            config,
            strategy=FAIR_VALUE_LIVE_STRATEGY,
            created_by="dashboard",
        )
        return {
            "ok": True,
            "active_config": saved.as_dict(),
            "config_history": [
                revision.as_dict()
                for revision in config_repository.recent_revisions(
                    strategy=FAIR_VALUE_LIVE_STRATEGY,
                    limit=6,
                )
            ],
        }


def dashboard_auth_config(settings: Settings) -> DashboardAuthConfig:
    return DashboardAuthConfig.from_settings(settings).validate()


def make_handler(service: DashboardService) -> type[BaseHTTPRequestHandler]:
    auth_config = dashboard_auth_config(service.settings)

    class DashboardRequestHandler(BaseHTTPRequestHandler):
        server_version = "AlphaDBDashboard/1.0"

        def do_GET(self) -> None:
            if self.path == "/healthz":
                self._json({"ok": True})
                return
            if self.path == "/favicon.ico":
                self.send_response(HTTPStatus.NO_CONTENT)
                self.end_headers()
                return
            if self.path.startswith("/api/live"):
                if not self._authenticated():
                    self._json({"ok": False, "error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
                    return
                self._json(service.live_payload())
                return
            if self.path == "/" or self.path.startswith("/?"):
                if not self._authenticated():
                    self._html(login_html(), status=HTTPStatus.UNAUTHORIZED)
                    return
                self._html(DASHBOARD_HTML)
                return
            self._json({"ok": False, "error": "not_found"}, status=HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:
            if self.path == "/auth/login":
                self._login()
                return
            if self.path == "/api/live/config":
                if not self._authenticated():
                    self._json({"ok": False, "error": "unauthorized"}, status=HTTPStatus.UNAUTHORIZED)
                    return
                try:
                    payload = json.loads(self._body().decode("utf-8"))
                    if not isinstance(payload, Mapping):
                        raise ValueError("request body must be a JSON object")
                    self._json(service.save_config(payload))
                except Exception as exc:
                    self._json(
                        {"ok": False, "error": str(exc)},
                        status=HTTPStatus.BAD_REQUEST,
                    )
                return
            self._json({"ok": False, "error": "not_found"}, status=HTTPStatus.NOT_FOUND)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _login(self) -> None:
            form = parse_qs(self._body().decode("utf-8"))
            pin = form.get("pin", [""])[0]
            decision = evaluate_access(auth_config, submitted_pin=pin)
            if not decision.authenticated or not decision.remember_token:
                self._html(login_html(error="Invalid PIN"), status=HTTPStatus.UNAUTHORIZED)
                return
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/")
            self.send_header(
                "Set-Cookie",
                cookie_header(
                    auth_config.cookie_name,
                    decision.remember_token,
                    max_age=auth_config.cookie_ttl_seconds,
                ),
            )
            self.end_headers()

        def _authenticated(self) -> bool:
            if not auth_config.enabled:
                return True
            token = cookie_value(self.headers.get("Cookie"), auth_config.cookie_name)
            return evaluate_access(auth_config, remember_token=token).authenticated

        def _body(self) -> bytes:
            size = int(self.headers.get("Content-Length", "0"))
            return self.rfile.read(size)

        def _json(
            self,
            payload: Mapping[str, Any],
            *,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            body = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _html(self, html: str, *, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = html.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return DashboardRequestHandler


def cookie_value(header: str | None, name: str) -> str | None:
    if not header:
        return None
    cookie = SimpleCookie()
    try:
        cookie.load(header)
    except Exception:
        return None
    morsel = cookie.get(name)
    return None if morsel is None else morsel.value


def cookie_header(name: str, value: str, *, max_age: int) -> str:
    cookie = SimpleCookie()
    cookie[name] = value
    cookie[name]["max-age"] = str(max_age)
    cookie[name]["path"] = "/"
    cookie[name]["httponly"] = True
    cookie[name]["samesite"] = "Lax"
    return cookie.output(header="").strip()


def login_html(*, error: str | None = None) -> str:
    error_html = f"<p class='login-error'>{error}</p>" if error else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AlphaDB</title>
  <style>{BASE_CSS}</style>
</head>
<body class="login-body">
  <main class="login-panel">
    <h1>AlphaDB</h1>
    <form method="post" action="/auth/login">
      <label for="pin">PIN</label>
      <input id="pin" name="pin" type="password" inputmode="numeric" maxlength="4" autofocus>
      {error_html}
      <button type="submit">Unlock</button>
    </form>
  </main>
</body>
</html>"""


BASE_CSS = """
:root {
  color-scheme: dark;
  --bg: #080b0d;
  --panel: #11171a;
  --panel-2: #151d21;
  --line: #263238;
  --text: #edf3f4;
  --muted: #8da1a8;
  --green: #5ee2a0;
  --amber: #f6c85f;
  --red: #f07178;
  --blue: #7dc7ff;
  --input: #0b1114;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  background: var(--bg);
  color: var(--text);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  letter-spacing: 0;
}
button, input { font: inherit; }
.login-body { display: grid; place-items: center; padding: 24px; }
.login-panel {
  width: min(360px, 100%);
  border: 1px solid var(--line);
  background: var(--panel);
  padding: 24px;
  border-radius: 8px;
}
.login-panel h1 { margin: 0 0 20px; font-size: 24px; }
.login-panel label { display: block; color: var(--muted); margin-bottom: 8px; }
.login-panel input {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--input);
  color: var(--text);
  padding: 12px;
}
.login-panel button, .save-button {
  border: 0;
  border-radius: 6px;
  background: var(--green);
  color: #06100b;
  padding: 10px 14px;
  font-weight: 700;
  cursor: pointer;
}
.login-panel button { width: 100%; margin-top: 16px; }
.login-error, .error { color: var(--red); }
"""


DASHBOARD_CSS = BASE_CSS + """
.shell {
  display: grid;
  grid-template-columns: 212px minmax(0, 1fr);
  min-height: 100vh;
}
.nav {
  border-right: 1px solid var(--line);
  background: #0a0f12;
  padding: 16px 12px;
}
.brand { font-size: 18px; font-weight: 800; margin: 4px 8px 18px; }
.nav a {
  display: block;
  color: var(--muted);
  text-decoration: none;
  padding: 9px 10px;
  border-radius: 6px;
  margin-bottom: 4px;
}
.nav a.active {
  color: var(--text);
  background: var(--panel-2);
  border: 1px solid var(--line);
}
.main { min-width: 0; }
.topbar {
  min-height: 58px;
  border-bottom: 1px solid var(--line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 18px;
  background: #0b1013;
  gap: 12px;
}
.topbar h1 { font-size: 19px; margin: 0; }
.status-strip { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
.pill {
  border: 1px solid var(--line);
  color: var(--muted);
  background: var(--panel);
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 12px;
}
.pill.good { color: var(--green); }
.pill.warn { color: var(--amber); }
.pill.bad { color: var(--red); }
.content { padding: 16px 18px 28px; }
.grid {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(320px, .9fr);
  gap: 14px;
}
.panel {
  border: 1px solid var(--line);
  background: var(--panel);
  border-radius: 8px;
  padding: 14px;
  min-width: 0;
}
.panel h2 {
  margin: 0 0 12px;
  font-size: 14px;
  color: var(--muted);
  font-weight: 700;
  text-transform: uppercase;
}
.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(120px, 1fr));
  gap: 10px;
}
.metric {
  border: 1px solid var(--line);
  background: var(--panel-2);
  border-radius: 6px;
  padding: 12px;
  min-height: 82px;
}
.label { color: var(--muted); font-size: 12px; margin-bottom: 7px; }
.value { font-size: 24px; font-weight: 800; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.detail { color: var(--muted); font-size: 12px; margin-top: 6px; min-height: 16px; }
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}
.field label {
  display: block;
  color: var(--muted);
  font-size: 12px;
  margin-bottom: 6px;
}
.field input {
  width: 100%;
  min-height: 38px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--input);
  color: var(--text);
  padding: 8px 10px;
}
.field .error { min-height: 16px; font-size: 12px; margin-top: 4px; }
.save-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
}
.save-state { min-height: 18px; color: var(--muted); font-size: 12px; }
.lower {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(300px, .75fr);
  gap: 14px;
  margin-top: 14px;
}
table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
  font-size: 12px;
}
th, td {
  border-bottom: 1px solid var(--line);
  text-align: left;
  padding: 8px 6px;
  vertical-align: top;
  overflow-wrap: anywhere;
}
th { color: var(--muted); font-weight: 700; }
@media (max-width: 920px) {
  .shell { grid-template-columns: 1fr; }
  .nav { display: flex; align-items: center; gap: 8px; border-right: 0; border-bottom: 1px solid var(--line); }
  .brand { margin: 0 10px 0 0; }
  .nav a { margin-bottom: 0; }
  .grid, .lower { grid-template-columns: 1fr; }
  .summary-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .form-grid { grid-template-columns: 1fr; }
}
"""


DASHBOARD_HTML = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AlphaDB Live</title>
  <style>{DASHBOARD_CSS}</style>
</head>
<body>
  <div class="shell">
    <nav class="nav">
      <div class="brand">AlphaDB</div>
      <a class="active" href="/">Live</a>
    </nav>
    <main class="main">
      <header class="topbar">
        <h1>Live Operator Console</h1>
        <div class="status-strip">
          <span class="pill" id="env-pill">env</span>
          <span class="pill" id="health-pill">health</span>
          <span class="pill" id="orders-pill">live orders</span>
          <span class="pill" id="config-pill">config</span>
        </div>
      </header>
      <section class="content">
        <div class="grid">
          <section class="panel">
            <h2>Live State</h2>
            <div class="summary-grid">
              <div class="metric"><div class="label">Market</div><div class="value" id="market">--</div><div class="detail" id="run-id">--</div></div>
              <div class="metric"><div class="label">Decision</div><div class="value" id="decision">--</div><div class="detail" id="decision-detail">--</div></div>
              <div class="metric"><div class="label">Risk</div><div class="value" id="risk">--</div><div class="detail" id="risk-detail">--</div></div>
              <div class="metric"><div class="label">Execution</div><div class="value" id="execution">--</div><div class="detail" id="execution-detail">--</div></div>
            </div>
          </section>
          <section class="panel">
            <h2>Runtime Config</h2>
            <form id="config-form" novalidate>
              <div class="form-grid">
                <div class="field"><label for="max_order_dollars">Max order dollars</label><input id="max_order_dollars" name="max_order_dollars" type="number" min="0.01" step="0.01"><div class="error" data-error-for="max_order_dollars"></div></div>
                <div class="field"><label for="max_market_exposure_dollars">Max market exposure dollars</label><input id="max_market_exposure_dollars" name="max_market_exposure_dollars" type="number" min="0.01" step="0.01"><div class="error" data-error-for="max_market_exposure_dollars"></div></div>
                <div class="field"><label for="max_daily_loss_dollars">Max daily loss dollars</label><input id="max_daily_loss_dollars" name="max_daily_loss_dollars" type="number" min="0.01" step="0.01"><div class="error" data-error-for="max_daily_loss_dollars"></div></div>
                <div class="field"><label for="min_edge">Min edge</label><input id="min_edge" name="min_edge" type="number" min="0" max="1" step="0.0001"><div class="error" data-error-for="min_edge"></div></div>
                <div class="field"><label for="max_markets">Max markets</label><input id="max_markets" name="max_markets" type="number" min="1" max="500" step="1"><div class="error" data-error-for="max_markets"></div></div>
              </div>
              <div class="save-row"><button class="save-button" type="submit">Save</button><span class="save-state" id="save-state"></span></div>
            </form>
          </section>
        </div>
        <div class="lower">
          <section class="panel">
            <h2>Recent Attempts</h2>
            <table><thead><tr><th>Time</th><th>Market</th><th>Status</th><th>Reason</th><th>Fill</th></tr></thead><tbody id="attempts-body"></tbody></table>
          </section>
          <section class="panel">
            <h2>Config History</h2>
            <table><thead><tr><th>Version</th><th>Order</th><th>Exposure</th><th>Daily</th><th>Saved</th></tr></thead><tbody id="history-body"></tbody></table>
          </section>
        </div>
      </section>
    </main>
  </div>
  <script>
const fields = ["max_order_dollars","max_market_exposure_dollars","max_daily_loss_dollars","min_edge","max_markets"];
function text(id, value) {{ document.getElementById(id).textContent = value ?? "--"; }}
function cls(id, name) {{ document.getElementById(id).className = name; }}
function money(value) {{ const n = Number(value || 0); return "$" + n.toFixed(2); }}
function shortTime(value) {{
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {{ month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }});
}}
function setErrors(errors) {{
  document.querySelectorAll("[data-error-for]").forEach(el => el.textContent = "");
  Object.entries(errors).forEach(([key, value]) => {{
    const el = document.querySelector(`[data-error-for="${{key}}"]`);
    if (el) el.textContent = value;
  }});
}}
function validate(payload) {{
  const errors = {{}};
  ["max_order_dollars","max_market_exposure_dollars","max_daily_loss_dollars"].forEach(key => {{
    if (!Number.isFinite(payload[key]) || payload[key] <= 0) errors[key] = "Must be positive.";
  }});
  if (!Number.isFinite(payload.min_edge) || payload.min_edge < 0 || payload.min_edge > 1) errors.min_edge = "Use 0 through 1.";
  if (!Number.isInteger(payload.max_markets) || payload.max_markets < 1 || payload.max_markets > 500) errors.max_markets = "Use 1 through 500.";
  return errors;
}}
async function loadLive() {{
  const res = await fetch("/api/live");
  const data = await res.json();
  render(data);
}}
function render(data) {{
  const status = data.live_status || {{}};
  const config = data.active_config || {{}};
  text("env-pill", data.health?.environment || "env");
  text("health-pill", data.health?.ok ? "health ok" : "health error");
  cls("health-pill", "pill " + (data.health?.ok ? "good" : "bad"));
  text("orders-pill", status.live_orders_enabled ? "live runner active" : "live runner inactive");
  cls("orders-pill", "pill " + (status.live_orders_enabled ? "good" : "bad"));
  text("config-pill", "config v" + (config.version ?? "--"));
  text("market", status.current_market_ticker || "No run");
  text("run-id", status.run_id || "no recent run");
  text("decision", status.decision_outcome || "--");
  text("decision-detail", status.selected_side || status.skip_reason || "--");
  text("risk", money(status.daily_loss_used_dollars));
  text("risk-detail", "daily limit " + money(status.daily_loss_limit_dollars) + " · market " + money(status.market_exposure_used_dollars) + " / " + money(status.market_exposure_limit_dollars));
  text("execution", status.latest_attempt_status || status.fill_status || "--");
  text("execution-detail", status.latest_attempt_reason || status.fill_status || "--");
  fields.forEach(key => {{ if (key in config) document.getElementById(key).value = config[key]; }});
  const attempts = status.recent_attempts || [];
  document.getElementById("attempts-body").innerHTML = attempts.length ? attempts.map(row => `<tr><td>${{shortTime(row.submitted_at)}}</td><td>${{row.market_ticker || ""}}</td><td>${{row.status || ""}}</td><td>${{row.reason || ""}}</td><td>${{row.fill_status || ""}}</td></tr>`).join("") : "<tr><td colspan='5'>No recent attempts</td></tr>";
  const history = data.config_history || [];
  document.getElementById("history-body").innerHTML = history.map(row => `<tr><td>${{row.version}}</td><td>${{money(row.max_order_dollars)}}</td><td>${{money(row.max_market_exposure_dollars)}}</td><td>${{money(row.max_daily_loss_dollars)}}</td><td>${{shortTime(row.created_at)}}</td></tr>`).join("");
}}
document.getElementById("config-form").addEventListener("submit", async event => {{
  event.preventDefault();
  const payload = Object.fromEntries(fields.map(key => [key, key === "max_markets" ? Number.parseInt(document.getElementById(key).value, 10) : Number.parseFloat(document.getElementById(key).value)]));
  const errors = validate(payload);
  setErrors(errors);
  if (Object.keys(errors).length) return;
  text("save-state", "Saving...");
  const res = await fetch("/api/live/config", {{ method: "POST", headers: {{ "Content-Type": "application/json" }}, body: JSON.stringify(payload) }});
  const data = await res.json();
  if (!res.ok || data.ok === false) {{
    text("save-state", data.error || "Save failed");
    return;
  }}
  text("save-state", "Saved");
  await loadLive();
}});
loadLive().catch(error => text("save-state", error.message));
  </script>
</body>
</html>"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alphadb-dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=None)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = settings_from_env()
    port = args.port or int(settings.dashboard_port)
    service = DashboardService(settings=settings)
    server = ThreadingHTTPServer((args.host, port), make_handler(service))
    print(f"alphadb-dashboard listening on http://{args.host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
