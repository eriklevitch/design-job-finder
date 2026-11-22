"""Past searches, kept in history.json so the app can show this week's
jobs whenever it opens, not only right after a search. It's a personal
file: it stays on this computer, like your tracker. About 8 weeks are
kept; the full record is always your tracker.
"""
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from settings import DATA, save_file

PATH = DATA / "history.json"
WEEKS_KEPT = 8
FIELDS = ("finished_at", "state", "message", "scanned", "matches", "already",
          "skipped", "source_problem", "draft_problem", "details", "fix")


def _when(run: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(run["finished_at"])
    except (KeyError, TypeError, ValueError):
        return None


def load(path: Path | None = None) -> list[dict]:
    """Every saved search, oldest first. A missing or damaged file is empty."""
    try:
        data = json.loads((path or PATH).read_text(encoding="utf-8"))
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
        save_file(path, json.dumps(runs, ensure_ascii=False, indent=1))
    except OSError:
        pass  # the jobs are already in the tracker; only the app's list misses them


def week_start(when: datetime) -> date:
    """The Monday of that week."""
    return (when - timedelta(days=when.weekday())).date()


SHOWN_WEEKS = 4


def _week(runs: list[dict], start: date, current: date) -> dict:
    """One week: every job its searches added (newest first, no repeats),
    its latest search, and whether any search that week hit a problem."""
    in_week = [r for r in runs if week_start(_when(r)) == start]
    jobs, seen = [], set()
    for run in reversed(in_week):
        for job in run.get("added") or []:
            key = job.get("url") or (job.get("company"), job.get("title"))
            if key not in seen:
                seen.add(key)
                jobs.append(job)
    last = in_week[-1] if in_week else None
    return {
        "start": start.isoformat(),
        "this_week": start == current,
        "checked": bool(in_week),
        "jobs": jobs,
        "last": {k: v for k, v in last.items() if k != "added"} if last else None,
        "problem": any(r.get("source_problem") or r.get("state") == "error" for r in in_week),
    }


def weeks(runs: list[dict], now: datetime | None = None, count: int = SHOWN_WEEKS) -> list[dict]:
    """The last `count` weeks up to and including this one, oldest first.
    Weeks with no search are kept (so a gap never looks like a week with
    no matches), except weeks before the very first search."""
    if not runs:
        return []
    current = week_start(now or datetime.now())
    first = week_start(_when(runs[0]))
    starts = [current - timedelta(weeks=i) for i in range(count - 1, -1, -1)]
    return [_week(runs, s, current) for s in starts if s >= first]
