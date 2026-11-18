"""Past searches, kept in history.json so the app can show this week's
jobs whenever it opens, not only right after a search. It's a personal
file: it stays on this computer, like your tracker. About 8 weeks are
kept; the full record is always your tracker.
"""
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from settings import ROOT

PATH = ROOT / "history.json"
WEEKS_KEPT = 8
FIELDS = ("finished_at", "state", "message", "scanned", "matches", "already",
          "skipped", "source_problem", "draft_problem")


def _when(run: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(run["finished_at"])
    except (KeyError, TypeError, ValueError):
        return None


def load(path: Path | None = None) -> list[dict]:
    """Every saved search, oldest first. A missing or damaged file is empty."""
    try:
        data = json.loads((path or PATH).read_text())
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [r for r in data if isinstance(r, dict) and _when(r)]


def add(summary: dict, path: Path | None = None, now: datetime | None = None) -> None:
    """Saves one finished search (the app's summary of it) and drops
    searches older than WEEKS_KEPT."""
    path = path or PATH
    now = now or datetime.now()
    record = {k: summary.get(k) for k in FIELDS}
    record["finished_at"] = record["finished_at"] or now.isoformat(timespec="seconds")
    record["added"] = summary.get("added") or []
    cutoff = now - timedelta(weeks=WEEKS_KEPT)
    runs = [r for r in load(path) if _when(r) >= cutoff] + [record]
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(runs, ensure_ascii=False, indent=1))
        tmp.replace(path)
    except OSError:
        pass  # the jobs are already in the tracker; only the app's list misses them


def week_start(when: datetime) -> date:
    """The Monday of that week."""
    return (when - timedelta(days=when.weekday())).date()


def latest_week(runs: list[dict], now: datetime | None = None) -> dict | None:
    """The most recent week with a search: every job it added (newest
    first, no repeats) and its latest search. None before the first one."""
    if not runs:
        return None
    last = runs[-1]
    start = week_start(_when(last))
    jobs, seen = [], set()
    for run in reversed(runs):
        if week_start(_when(run)) != start:
            continue
        for job in run.get("added") or []:
            key = job.get("url") or (job.get("company"), job.get("title"))
            if key not in seen:
                seen.add(key)
                jobs.append(job)
    return {
        "start": start.isoformat(),
        "this_week": start == week_start(now or datetime.now()),
        "jobs": jobs,
        "last": {k: v for k, v in last.items() if k != "added"},
    }
