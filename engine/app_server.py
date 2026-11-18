"""The Job Finder app: a small page in your browser with a "Find new jobs"
button, your settings and the weekly schedule.

It runs only on your Mac. The page is served from 127.0.0.1, which other
computers can't reach, and every action needs a secret code made fresh
each time the app starts, so websites you visit can't use it either.
It quits on its own about 15 minutes after you close the page.

  python engine/app_server.py          open the app (start it if needed)
  python engine/app_server.py --serve  run the server in this window
"""
import json
import os
import secrets
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

try:
    import fcntl  # Mac and Linux
except ImportError:  # Windows: searches aren't locked, so there's nothing to follow
    fcntl = None

import config_store as store
import history
import schedule
from settings import CONFIG_PATH, CRASH_MESSAGE, ROOT, load_env, scrub

STATIC = Path(__file__).resolve().parent / "app"
STATE_PATH = ROOT / ".app_state.json"
LOGS = ROOT / "logs"
RUN_SUMMARY = LOGS / "app_run.json"
RUN_LOG = LOGS / "app_run.log"
LAST_RUN = ROOT / "last_run.json"  # older versions; only read when there's no history yet
LOCK_PATH = ROOT / ".run.lock"                  # held by whichever search is running
SCHEDULED_SUMMARY = LOGS / "scheduled_summary.json"  # the Monday check's progress
FIRST_PORT = 8765
IDLE_SECONDS = 15 * 60
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml",
                 ".woff2": "font/woff2"}


# ── Turning the app's form into settings, and back ──────────────────

def settings_for_page() -> dict:
    cfg = store.current_settings()
    locations = cfg.get("locations") or []
    return {
        "level": store.level_choice(cfg),
        "role": cfg.get("your_role") or "",
        "cities": [l for l in locations if l != "remote"],
        "remote": "remote" in locations or not locations,
        "min_salary": cfg.get("min_salary") or 0,
        "companies": [{"key": key, "slug": slug} for key in store.COMPANY_KEYS.values()
                      for slug in cfg.get(key) or []],
        "tracker": (cfg.get("tracker") or "spreadsheet").lower(),
    }


def settings_from_page(form: dict) -> dict:
    level = int(form.get("level") or 3)
    if level not in range(1, len(store.LEVEL_CHOICES) + 1):
        raise ValueError("Pick a level.")
    role = (form.get("role") or "").strip()
    if not role or role in store.ROLE_DEFAULTS.values():
        role = store.ROLE_DEFAULTS[level]  # follow the level unless they typed their own
    cities = [c.strip() for c in form.get("cities") or [] if c.strip()]
    pay = store.parse_money(form.get("min_salary") or 0)
    if pay is None:
        raise ValueError("Type the minimum pay as a number, like 150k.")
    lists = {key: [] for key in store.COMPANY_KEYS.values()}
    for c in form.get("companies") or []:
        if c.get("key") in lists and c.get("slug") and c["slug"] not in lists[c["key"]]:
            lists[c["key"]].append(c["slug"])
    tracker = "notion" if form.get("tracker") == "notion" else "spreadsheet"
    return {
        "seniority_keywords": store.LEVEL_CHOICES[level - 1][1],
        "your_role": role,
        "locations": [c.lower() for c in cities] + (["remote"] if form.get("remote") else []),
        "search_location": cities[0] if cities else "United States",
        "min_salary": pay,
        "tracker": tracker,
        **lists,
    }


def next_check() -> str | None:
    return schedule.next_run(datetime.now()).isoformat() if schedule.is_on() else None


def home_data() -> dict:
    """What the home page shows: the last few weeks of jobs, when the
    latest search finished, and when the next one runs."""
    runs = history.load()
    return {
        "weeks": history.weeks(runs),
        "last_checked": runs[-1]["finished_at"] if runs else None,
        "last_run": read_json(LAST_RUN),
        "next_check": next_check(),
    }


def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


# ── Running a search in the background ──────────────────────────────

def search_running(lock_path: Path) -> bool:
    """True while any search holds the lock (the app's, or the Monday check)."""
    if fcntl is None:
        return False
    try:
        with open(lock_path, "a") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return True
            fcntl.flock(f, fcntl.LOCK_UN)
            return False
    except OSError:
        return False


def log_tail(path: Path, lines: int = 25) -> str:
    try:
        return "\n".join(path.read_text(errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


class Runner:
    def __init__(self, command=None, summary: Path = RUN_SUMMARY, log: Path = RUN_LOG,
                 lock: Path = LOCK_PATH, other_summary: Path = SCHEDULED_SUMMARY):
        self.command = command or [sys.executable, "-u", str(ROOT / "engine" / "main.py")]
        self.summary = summary
        self.log = log
        self.lock_path = lock
        self.other_summary = other_summary
        self.process = None
        self.lock = threading.Lock()

    def busy(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self) -> dict:
        with self.lock:
            if self.busy():
                return self.status()
            self.log.parent.mkdir(exist_ok=True)
            self.summary.unlink(missing_ok=True)
            log = open(self.log, "w")
            self.process = subprocess.Popen(
                [*self.command, "--summary", str(self.summary)],
                cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            log.close()
        return {"state": "running", "step": "Starting…"}

    def other_search(self) -> dict | None:
        """Progress of a search this app didn't start (the Monday check)."""
        if not search_running(self.lock_path):
            return None
        other = read_json(self.other_summary) or {}
        step = other.get("step") if other.get("state") == "running" else None
        return {"state": "running", "sites": other.get("sites") or [],
                "step": f"The Monday check is running. {step or 'Looking for jobs…'}"}

    def status(self) -> dict | None:
        if self.process is None:
            return self.other_search()
        summary = read_json(self.summary) or {"state": "running", "step": "Starting…"}
        if self.process.poll() is None:
            return summary
        if summary.get("state") == "busy":  # another search had started first: follow it
            return self.other_search() or {"state": "done"}
        if summary.get("state") == "running":  # stopped without saying why
            return {"state": "error", "message": CRASH_MESSAGE,
                    "details": scrub(log_tail(self.log))}
        return summary


# ── The web server ──────────────────────────────────────────────────

class App:
    def __init__(self, port: int, token: str):
        self.port = port
        self.token = token
        self.runner = Runner()
        self.last_seen = time.time()

    def state(self) -> dict:
        return {
            "set_up": CONFIG_PATH.exists(),
            "settings": settings_for_page(),
            "levels": [label for label, _ in store.LEVEL_CHOICES],
            "connected": store.connected(),
            **home_data(),
            "schedule_on": schedule.is_on(),
            "can_schedule": sys.platform == "darwin",
            "run": self.runner.status(),
            "notes": store.read_notes(),
        }

    def handle(self, path: str, body: dict) -> tuple[int, dict]:
        if path == "/api/state":
            return 200, self.state()
        if path == "/api/settings":
            store.save_settings(settings_from_page(body))
            return 200, self.state()
        if path == "/api/company":
            return 200, store.lookup_company(str(body.get("name", ""))[:100])
        if path == "/api/keys":
            problems = store.save_keys(str(body.get("anthropic", "")),
                                       str(body.get("adzuna_id", "")),
                                       str(body.get("adzuna_key", "")))
            return 200, {"problems": problems, "connected": store.connected()}
        if path == "/api/notion":
            ok, message = store.connect_notion(str(body.get("token", "")),
                                               str(body.get("link", "")))
            if ok:
                store.save_settings({"tracker": "notion"})
            return 200, {"ok": ok, "message": message, "connected": store.connected()}
        if path == "/api/notes":
            store.save_notes(str(body.get("text", "")))
            return 200, {"ok": True}
        if path == "/api/run":
            if not CONFIG_PATH.exists():
                return 400, {"error": "Answer the setup questions first."}
            return 200, self.runner.start()
        if path == "/api/run/status":
            return 200, {"run": self.runner.status(), **home_data()}
        if path == "/api/open-tracker":
            from open_tracker import open_tracker
            opened, message = open_tracker()
            return 200, {"ok": opened, "message": message}
        if path == "/api/schedule":
            if sys.platform != "darwin":
                return 400, {"error": "Monday checks only work on a Mac."}
            schedule.turn_on() if body.get("on") else schedule.turn_off()
            return 200, {"schedule_on": schedule.is_on(), "next_check": next_check()}
        if path == "/api/ping":
            return 200, {"ok": True}
        return 404, {"error": "Not found"}

    def idle(self) -> bool:
        return time.time() - self.last_seen > IDLE_SECONDS and not self.runner.busy()


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # keep the window quiet
            pass

        def host_ok(self) -> bool:
            # Blocks "DNS rebinding": a website pretending to be localhost.
            return self.headers.get("Host", "") in (f"127.0.0.1:{app.port}",
                                                    f"localhost:{app.port}")

        def send(self, code: int, data: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.end_headers()
            self.wfile.write(data)

        def send_json(self, code: int, payload: dict) -> None:
            self.send(code, json.dumps(payload, ensure_ascii=False).encode(), "application/json")

        def do_GET(self):
            if not self.host_ok():
                return self.send(403, b"Forbidden", "text/plain")
            path = urlparse(self.path).path
            name = "index.html" if path == "/" else path.removeprefix("/static/")
            file = (STATIC / name).resolve()
            inside = file.is_relative_to(STATIC.resolve())
            if path != "/" and not path.startswith("/static/") or not inside or \
                    not file.is_file() or file.suffix not in CONTENT_TYPES:
                return self.send(404, b"Not found", "text/plain")
            self.send(200, file.read_bytes(), CONTENT_TYPES.get(file.suffix, "text/plain"))

        def do_POST(self):
            if not self.host_ok():
                return self.send(403, b"Forbidden", "text/plain")
            if not secrets.compare_digest(self.headers.get("X-Token", ""), app.token):
                return self.send_json(403, {"error": "This window is out of date. Click Job Finder in your Dock to open it again."})
            try:
                length = min(int(self.headers.get("Content-Length") or 0), 1_000_000)
                body = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError("bad request")
            except ValueError:
                return self.send_json(400, {"error": "Bad request"})
            app.last_seen = time.time()
            try:
                code, payload = app.handle(urlparse(self.path).path, body)
            except ValueError as e:
                code, payload = 400, {"error": str(e)}
            except Exception as e:  # show it on the page instead of a blank failure
                code, payload = 500, {"error": f"Something went wrong: {e}"}
            self.send_json(code, payload)

    return Handler


def bind(port: int = FIRST_PORT) -> ThreadingHTTPServer:
    for p in range(port, port + 20):
        try:
            return ThreadingHTTPServer(("127.0.0.1", p), None)
        except OSError:
            continue
    raise OSError("No free port for Job Finder")


def serve() -> None:
    load_env()
    token = secrets.token_urlsafe(24)
    server = bind()
    app = App(server.server_address[1], token)
    server.RequestHandlerClass = make_handler(app)
    STATE_PATH.write_text(json.dumps({"port": app.port, "token": token, "pid": os.getpid()}))
    STATE_PATH.chmod(0o600)

    def watch_idle():
        while not app.idle():
            time.sleep(30)
        server.shutdown()

    threading.Thread(target=watch_idle, daemon=True).start()
    try:
        server.serve_forever()
    finally:
        if (read_json(STATE_PATH) or {}).get("pid") == os.getpid():
            STATE_PATH.unlink(missing_ok=True)


# ── Opening the app (what the Dock icon runs) ───────────────────────

def running_url() -> str | None:
    """The page's address if the app is already running."""
    state = read_json(STATE_PATH)
    if not state:
        return None
    url = f"http://127.0.0.1:{state['port']}"
    req = urllib.request.Request(f"{url}/api/ping", data=b"{}", method="POST",
                                 headers={"X-Token": state["token"]})
    try:
        urllib.request.urlopen(req, timeout=2).read()
    except Exception:
        return None
    return f"{url}/#t={state['token']}"


def open_app() -> int:
    url = running_url()
    if not url:
        STATE_PATH.unlink(missing_ok=True)
        LOGS.mkdir(exist_ok=True)
        with open(LOGS / "app.log", "a") as log:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve"],
                             cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        for _ in range(100):
            time.sleep(0.1)
            url = running_url()
            if url:
                break
    if not url:
        print("Job Finder couldn't start. See logs/app.log in your job-search folder.")
        return 1
    webbrowser.open(url)
    return 0


if __name__ == "__main__":
    if "--serve" in sys.argv:
        serve()
    else:
        sys.exit(open_app())
