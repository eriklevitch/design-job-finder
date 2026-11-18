"""Tests for the Job Finder app: settings, the local server, the weekly
schedule and the Mac app bundle. Nothing here touches your real files,
Dock or schedule."""
import json
import plistlib
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta

import pytest
import requests
import yaml

import app_server
import config_store
import history
import main as main_module
import mac_app
import schedule
import scheduled_run


@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    """Points the settings code at a temporary folder."""
    monkeypatch.setattr(config_store, "CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(config_store, "NOTES", tmp_path / "portfolio_notes.md")
    monkeypatch.setattr(app_server, "CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(app_server, "LAST_RUN", tmp_path / "last_run.json")
    monkeypatch.setattr(history, "PATH", tmp_path / "history.json")
    return tmp_path


# ── Settings ────────────────────────────────────────────────────────

def test_save_settings_creates_config_and_keeps_advanced(tmp_config):
    config_store.save_settings({"min_salary": 150000, "locations": ["remote"]})
    data = yaml.safe_load((tmp_config / "config.yaml").read_text())
    assert data["min_salary"] == 150000 and data["locations"] == ["remote"]
    assert data["title_excludes"]  # advanced section kept
    assert (tmp_config / "portfolio_notes.md").exists()


def test_save_settings_refuses_other_keys(tmp_config):
    with pytest.raises(ValueError):
        config_store.save_settings({"title_excludes": []})


def test_page_settings_round_trip(tmp_config):
    form = {"level": 2, "cities": ["New York", "Brooklyn"], "remote": True,
            "min_salary": "180k", "tracker": "spreadsheet",
            "companies": [{"key": "lever_companies", "slug": "acme"},
                          {"key": "lever_companies", "slug": "acme"},
                          {"key": "nonsense", "slug": "x"}]}
    config_store.save_settings(app_server.settings_from_page(form))
    data = yaml.safe_load((tmp_config / "config.yaml").read_text())
    assert data["locations"] == ["new york", "brooklyn", "remote"]
    assert data["search_location"] == "New York"
    assert data["min_salary"] == 180000
    assert data["lever_companies"] == ["acme"]
    assert data["your_role"] == "design leader"
    page = app_server.settings_for_page()
    assert page["level"] == 2 and page["remote"] and page["cities"] == ["new york", "brooklyn"]
    assert page["companies"] == [{"key": "lever_companies", "slug": "acme"}]


def test_typed_role_is_kept_but_default_role_follows_level():
    base = {"cities": [], "remote": True, "min_salary": 0}
    assert app_server.settings_from_page({**base, "level": 4, "role": "senior product designer"}
                                         )["your_role"] == "product designer"
    assert app_server.settings_from_page({**base, "level": 4, "role": "brand designer"}
                                         )["your_role"] == "brand designer"


def test_bad_pay_is_explained():
    with pytest.raises(ValueError, match="number"):
        app_server.settings_from_page({"level": 1, "min_salary": "lots"})


def test_save_keys_checks_anthropic_key(monkeypatch):
    saved = {}
    monkeypatch.setattr(config_store, "save_env", saved.update)
    assert config_store.save_keys(anthropic="nope")
    assert config_store.save_keys(adzuna_id="only-id")
    assert config_store.save_keys(anthropic="sk-ant-123", adzuna_id="a", adzuna_key="b") == []
    assert saved == {"ANTHROPIC_API_KEY": "sk-ant-123", "ADZUNA_APP_ID": "a", "ADZUNA_APP_KEY": "b"}


# ── The local server ────────────────────────────────────────────────

@pytest.fixture
def server(tmp_config):
    httpd = app_server.bind(18765)
    app = app_server.App(httpd.server_address[1], "secret-token")
    httpd.RequestHandlerClass = app_server.make_handler(app)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield app
    httpd.shutdown()
    httpd.server_close()


def call(app, path, body=None, token="secret-token", host=None, method="POST"):
    url = f"http://127.0.0.1:{app.port}{path}"
    data = json.dumps(body or {}).encode() if method == "POST" else None
    req = urllib.request.Request(url, data=data, method=method)
    if token:
        req.add_header("X-Token", token)
    if host:
        req.add_header("Host", host)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_server_serves_page(server):
    status, body = call(server, "/", method="GET")
    assert status == 200 and b"Job Finder" in body
    assert call(server, "/static/fonts/Inter.woff2", method="GET")[0] == 200


def test_server_blocks_files_outside_the_app(server):
    assert call(server, "/static/../app_server.py", method="GET")[0] == 404
    assert call(server, "/static/%2e%2e/settings.py", method="GET")[0] == 404
    assert call(server, "/config.yaml", method="GET")[0] == 404


def test_server_needs_the_token(server):
    assert call(server, "/api/state", token=None)[0] == 403
    assert call(server, "/api/state", token="wrong")[0] == 403
    status, body = call(server, "/api/state")
    assert status == 200
    state = json.loads(body)
    assert state["set_up"] is False and len(state["levels"]) == 4


def test_server_blocks_other_hosts(server):
    assert call(server, "/api/state", host="evil.example").__getitem__(0) == 403
    assert call(server, "/", host="evil.example", method="GET")[0] == 403


def test_state_never_includes_keys(server, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-very-secret")
    status, body = call(server, "/api/state")
    assert b"very-secret" not in body
    assert json.loads(body)["connected"]["anthropic"] is True


def test_cant_run_before_setup(server):
    assert call(server, "/api/run")[0] == 400


# ── Running a search ────────────────────────────────────────────────

FAKE_SEARCH = """
import json, sys, time
path = sys.argv[sys.argv.index("--summary") + 1]
json.dump({"state": "running", "step": "Checking..."}, open(path, "w"))
time.sleep(0.3)
json.dump({"state": "done", "message": "Added 1 new job.", "added": [{"title": "Designer"}]},
          open(path, "w"))
"""


def wait_until_done(runner):
    for _ in range(100):
        if not runner.busy():
            return runner.status()
        time.sleep(0.05)
    raise AssertionError("run didn't finish")


def test_runner_reports_progress_and_result(tmp_path):
    script = tmp_path / "fake.py"
    script.write_text(FAKE_SEARCH)
    runner = app_server.Runner([sys.executable, str(script)], tmp_path / "s.json", tmp_path / "r.log",
                              lock=tmp_path / ".run.lock", other_summary=tmp_path / "other.json")
    assert runner.status() is None
    runner.start()
    assert runner.busy()
    runner.start()  # a second click doesn't start a second search
    result = wait_until_done(runner)
    assert result["state"] == "done" and result["added"][0]["title"] == "Designer"


def test_runner_explains_a_crash(tmp_path):
    script = tmp_path / "crash.py"
    script.write_text("raise SystemExit(3)")
    runner = app_server.Runner([sys.executable, str(script)], tmp_path / "s.json", tmp_path / "r.log",
                              lock=tmp_path / ".run.lock", other_summary=tmp_path / "other.json")
    runner.start()
    assert wait_until_done(runner)["state"] == "error"


def test_only_one_search_at_a_time(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "LOCK_PATH", tmp_path / ".run.lock")
    first = main_module.take_lock()
    assert first is not None
    assert main_module.take_lock() is None
    first.close()
    assert main_module.take_lock() is not None


def test_report_writes_summary(tmp_path):
    report = main_module.Report(str(tmp_path / "s.json"), dry_run=False)
    report.update(step="Checking")
    report.finish("Added 2 new jobs.", added=[{}, {}])
    data = json.loads((tmp_path / "s.json").read_text())
    assert data["state"] == "done" and len(data["added"]) == 2


# ── Weekly schedule and the Mac app ─────────────────────────────────

def test_schedule_runs_monday_morning(tmp_path):
    p = schedule.plist_content(root=tmp_path, python="/x/python")
    assert p["StartCalendarInterval"] == {"Weekday": 1, "Hour": 9, "Minute": 0}
    assert p["ProgramArguments"] == ["/x/python", str(tmp_path / "engine" / "scheduled_run.py")]
    plistlib.dumps(p)  # valid plist


def test_scheduled_run_messages():
    assert scheduled_run.message_for({"state": "done", "added": [1, 2]}, 0).startswith("Found 2 new jobs")
    assert scheduled_run.message_for({"state": "done", "added": []}, 0) == "No new jobs this week."
    assert "didn't finish" in scheduled_run.message_for({}, 1)


def test_mac_app_bundle(tmp_path):
    app = mac_app.build(tmp_path / "Job Finder.app", root=tmp_path / "my folder")
    info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
    assert info["CFBundleExecutable"] == "Job Finder"
    exe = app / "Contents" / "MacOS" / "Job Finder"
    assert exe.stat().st_mode & 0o111
    script = exe.read_text()
    assert "'" + str(tmp_path / "my folder" / "venv" / "bin" / "python") + "'" in script
    assert (app / "Contents" / "Resources" / "JobFinder.icns").exists()


# ── This week's jobs (history.json) ─────────────────────────────────

def _run(when: datetime, *titles, **fields) -> dict:
    return {"state": "done", "finished_at": when.isoformat(timespec="seconds"),
            "added": [{"title": t, "url": f"https://x/{t}"} for t in titles], **fields}


def test_history_keeps_about_eight_weeks(tmp_path):
    path = tmp_path / "history.json"
    now = datetime(2026, 11, 16, 9, 0)
    history.add(_run(now - timedelta(weeks=9), "Old"), path, now=now)
    history.add(_run(now - timedelta(weeks=1), "Recent"), path, now=now)
    history.add(_run(now, "New"), path, now=now)
    assert [r["added"][0]["title"] for r in history.load(path)] == ["Recent", "New"]


def test_damaged_history_reads_as_empty(tmp_path):
    path = tmp_path / "history.json"
    path.write_text("{not json")
    assert history.load(path) == []
    path.write_text('[{"no": "date"}, 3]')
    assert history.load(path) == []


def test_weeks_gather_every_search_that_week():
    monday = datetime(2026, 11, 16, 9, 0)
    runs = [_run(monday - timedelta(days=7), "Last week"),
            _run(monday, "A", "B"),
            _run(monday + timedelta(days=2), "C", "A")]  # A again: shown once
    weeks = history.weeks(runs, now=monday + timedelta(days=3))
    assert [w["start"] for w in weeks] == ["2026-11-09", "2026-11-16"]  # nothing before the first search
    this = weeks[-1]
    assert this["this_week"] and this["checked"]
    assert [j["title"] for j in this["jobs"]] == ["C", "A", "B"]
    assert "added" not in this["last"]
    assert history.weeks([]) == []


def test_weeks_keep_gaps_and_show_four():
    monday = datetime(2026, 11, 16, 9, 0)
    runs = [_run(monday - timedelta(weeks=6), "Long ago"),
            _run(monday - timedelta(weeks=2), "Two weeks ago")]
    weeks = history.weeks(runs, now=monday + timedelta(days=1))
    assert [w["start"] for w in weeks] == ["2026-10-26", "2026-11-02", "2026-11-09", "2026-11-16"]
    assert [w["checked"] for w in weeks] == [False, True, False, False]
    assert weeks[-1]["last"] is None and weeks[-1]["jobs"] == []


def test_week_with_a_problem_is_flagged():
    monday = datetime(2026, 11, 16, 9, 0)
    runs = [_run(monday, "A", source_problem="Indeed didn't respond, so this list may be incomplete.")]
    assert history.weeks(runs, now=monday)[-1]["problem"]
    runs = [_run(monday, "A")]
    assert not history.weeks(runs, now=monday)[-1]["problem"]


def test_next_check_is_the_coming_monday_morning():
    wednesday = datetime(2026, 11, 18, 14, 0)
    assert schedule.next_run(wednesday) == datetime(2026, 11, 23, 9, 0)
    early_monday = datetime(2026, 11, 16, 8, 0)
    assert schedule.next_run(early_monday) == datetime(2026, 11, 16, 9, 0)
    assert schedule.next_run(datetime(2026, 11, 16, 9, 0)) == datetime(2026, 11, 23, 9, 0)


def test_state_includes_this_weeks_jobs(server, tmp_config):
    history.add(_run(datetime.now(), "Senior Product Designer"))
    state = json.loads(call(server, "/api/state")[1])
    week = state["weeks"][-1]
    assert week["this_week"] and week["jobs"][0]["title"] == "Senior Product Designer"
    assert state["last_checked"]


def test_job_card_carries_what_the_page_shows():
    card = main_module.job_card({"title": "Designer", "posted_date": "2026-11-14",
                                 "why": ["Senior"], "has_draft": True, "description": "long"})
    assert card["posted_date"] == "2026-11-14" and card["why"] == ["Senior"] and card["draft"]
    assert "description" not in card


def test_unreachable_sites_named_plainly():
    assert main_module.source_problem([]) == ""
    assert main_module.source_problem(["Indeed"]).startswith("Indeed didn't respond")
    assert main_module.source_problem(["Indeed", "Acme"]).startswith("Indeed and Acme didn't")
    assert main_module.source_problem(["A", "B", "C", "D"]).startswith("A, B and 2 more didn't")


def test_no_internet_is_not_reported_as_no_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "PATH", tmp_path / "history.json")
    monkeypatch.setattr(main_module, "LOCK_PATH", tmp_path / ".run.lock")
    monkeypatch.setattr(main_module, "load_env", lambda: None)
    monkeypatch.setattr(main_module, "load_config", lambda: {})

    def offline(config):
        raise OSError("no network")
    for name in ("fetch_adzuna", "fetch_greenhouse", "fetch_lever", "fetch_ashby", "fetch_jobspy"):
        monkeypatch.setattr(main_module, name, offline)
    summary = tmp_path / "s.json"
    assert main_module.main(["--summary", str(summary)]) == 1
    data = json.loads(summary.read_text())
    assert data["state"] == "error" and "internet" in data["message"]
    assert history.load()[-1]["state"] == "error"


# ── Problems explained plainly ──────────────────────────────────────

def test_scrub_hides_keys():
    from settings import scrub
    text = ("GET https://api.adzuna.com/search?app_id=abc&app_key=xyz123 failed; "
            "key sk-ant-api03-SECRET and secret_ABC123 and ntn_456")
    clean = scrub(text)
    for secret in ("abc&", "xyz123", "sk-ant-api03-SECRET", "secret_ABC123", "ntn_456"):
        assert secret not in clean
    assert "app_key=[hidden]" in clean


def _http_error(status):
    resp = requests.Response()
    resp.status_code = status
    return requests.HTTPError(f"{status} error from Notion: nope", response=resp)


def test_notion_problems_say_what_to_do():
    lost = main_module.notion_problem(_http_error(401))
    assert "Reconnect" in lost.message and lost.fix["section"] == "sec-tracker"
    assert main_module.notion_problem(_http_error(404)).fix
    offline = main_module.notion_problem(requests.ConnectionError("down"))
    assert "internet" in offline.message and offline.fix is None
    assert "error 500" in main_module.notion_problem(_http_error(500)).message


def test_only_notion_errors_are_translated():
    class NotionTracker:
        def add_job(self, *a):
            raise _http_error(401)

    class CsvTracker(NotionTracker):
        pass
    with pytest.raises(main_module.TrackerProblem):
        main_module.tracker_call(NotionTracker(), NotionTracker().add_job)
    with pytest.raises(requests.HTTPError):
        main_module.tracker_call(CsvTracker(), CsvTracker().add_job)


def test_crash_is_explained_and_saved(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "PATH", tmp_path / "history.json")
    monkeypatch.setattr(main_module, "LOCK_PATH", tmp_path / ".run.lock")
    monkeypatch.setattr(main_module, "load_env", lambda: None)

    def broken():
        raise RuntimeError("boom with sk-ant-api03-SECRET")
    monkeypatch.setattr(main_module, "load_config", broken)
    summary = tmp_path / "s.json"
    assert main_module.main(["--summary", str(summary)]) == 1
    data = json.loads(summary.read_text())
    assert data["state"] == "error" and data["message"] == main_module.CRASH_MESSAGE
    assert "boom" in data["details"] and "SECRET" not in data["details"]
    assert history.load()[-1]["details"] == data["details"]


def test_second_search_reports_busy_not_error(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "LOCK_PATH", tmp_path / ".run.lock")
    first = main_module.take_lock()
    summary = tmp_path / "s.json"
    assert main_module.main(["--summary", str(summary)]) == 1
    assert json.loads(summary.read_text())["state"] == "busy"
    first.close()


def test_app_follows_the_monday_check(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "LOCK_PATH", tmp_path / ".run.lock")
    (tmp_path / "other.json").write_text(json.dumps({"state": "running", "step": "Checking Indeed…"}))
    runner = app_server.Runner(["x"], tmp_path / "s.json", tmp_path / "r.log",
                               lock=tmp_path / ".run.lock", other_summary=tmp_path / "other.json")
    assert runner.status() is None  # nothing running
    held = main_module.take_lock()
    status = runner.status()
    assert status["state"] == "running" and "Monday check" in status["step"]
    assert "Checking Indeed" in status["step"]
    held.close()
    assert runner.status() is None


def test_busy_click_follows_the_other_search(tmp_path):
    script = tmp_path / "busy.py"
    script.write_text("import json, sys\n"
                      "json.dump({'state': 'busy'}, open(sys.argv[sys.argv.index('--summary') + 1], 'w'))")
    runner = app_server.Runner([sys.executable, str(script)], tmp_path / "s.json", tmp_path / "r.log",
                               lock=tmp_path / ".run.lock", other_summary=tmp_path / "other.json")
    runner.start()
    assert wait_until_done(runner) == {"state": "done"}  # the other one already finished


def test_silent_crash_shows_details_without_keys(tmp_path):
    script = tmp_path / "crash.py"
    script.write_text("print('oops: key=TOPSECRET'); raise SystemExit(3)")
    runner = app_server.Runner([sys.executable, str(script)], tmp_path / "s.json", tmp_path / "r.log",
                               lock=tmp_path / ".run.lock", other_summary=tmp_path / "other.json")
    runner.start()
    result = wait_until_done(runner)
    assert result["message"] == app_server.CRASH_MESSAGE
    assert "oops" in result["details"] and "TOPSECRET" not in result["details"]


def test_monday_check_stays_quiet_when_it_waited():
    assert scheduled_run.message_for({"state": "busy"}, 1) == ""
