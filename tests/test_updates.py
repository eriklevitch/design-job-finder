"""Tests for updates: spotting a newer version and running the installer.
Nothing here contacts GitHub or installs anything."""
import json
import sys
import time

import pytest

import app_server
import updates


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """An installed copy (no .git folder) at version 1.1."""
    monkeypatch.setattr(updates, "ROOT", tmp_path)
    monkeypatch.setattr(updates, "VERSION_PATH", tmp_path / "VERSION")
    monkeypatch.setattr(updates, "CHECK_PATH", tmp_path / ".update_check.json")
    (tmp_path / "VERSION").write_text("1.1\n")
    return tmp_path


def test_versions_compare_as_numbers():
    assert updates.parse("1.10") > updates.parse("1.9")
    assert updates.parse("2") > updates.parse("1.99")
    assert updates.parse("nonsense") == ()


def test_offers_only_a_newer_version(installed):
    assert updates.newer_version() is None  # never checked
    for latest, offered in [("1.2", "1.2"), ("1.1", None), ("1.0", None), ("oops", None)]:
        (installed / ".update_check.json").write_text(json.dumps({"latest": latest}))
        assert updates.newer_version() == offered


def test_a_git_copy_never_offers_updates(installed):
    (installed / ".update_check.json").write_text(json.dumps({"latest": "9.0"}))
    (installed / ".git").mkdir()
    assert updates.newer_version() is None
    assert not updates.can_update()


def test_checks_github_at_most_once_a_day(installed):
    asked = []

    def fetch():
        asked.append(1)
        return "1.2"

    now = time.time()
    updates.check(now, fetch)
    updates.check(now + 60 * 60, fetch)
    assert len(asked) == 1
    assert updates.newer_version() == "1.2"
    updates.check(now + 25 * 60 * 60, fetch)
    assert len(asked) == 2


def test_offline_check_changes_nothing(installed):
    updates.check(time.time(), lambda: None)
    assert not (installed / ".update_check.json").exists()


def wait(updater):
    updater.process.wait(timeout=10)
    return updater.status()


def test_updater_reports_a_failure_without_keys(tmp_path):
    u = updates.Updater([sys.executable, "-c", "print('key=sk-ant-abc123'); raise SystemExit(1)"],
                        log=tmp_path / "update.log")
    u.start(in_window=True)
    status = wait(u)
    assert status["state"] == "error"
    assert "sk-ant-abc123" not in status["details"]


def test_updater_tells_the_installer_the_window_reopens_itself(tmp_path):
    script = "import os; print(os.environ.get('JOBSEARCH_FROM_APP', 'no'))"
    u = updates.Updater([sys.executable, "-c", script], log=tmp_path / "update.log")
    u.start(in_window=True)
    assert wait(u)["state"] == "done"
    assert (tmp_path / "update.log").read_text().strip() == "1"
    u.start(in_window=False)
    wait(u)
    assert (tmp_path / "update.log").read_text().strip() == "no"


def test_no_update_during_a_search(installed, monkeypatch):
    app = app_server.App(0, "t")
    monkeypatch.setattr(app.runner, "busy", lambda: True)
    with pytest.raises(ValueError, match="search"):
        app.handle("/api/update", {})


def test_alive_is_false_when_nothing_answers():
    assert not app_server.alive("http://127.0.0.1:9/#t=abc")
