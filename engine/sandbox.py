"""The test copy of the app: the same app, with made-up files kept in the
sandbox/ folder, so you can try setup, the Jobs page and Settings again
and again without touching your real settings, tracker or schedule.

  python engine/sandbox.py                open the test copy as you left it
  python engine/sandbox.py with-jobs      start over from a starting point, then open it
  python engine/sandbox.py --list         show the starting points
  ... --browser                           open it in your browser instead

Starting points (also in the test copy's own menu at the top of the window):
  fresh       nothing set up: the first-run questions
  set-up      questions answered, no search yet: the empty Jobs page
  with-jobs   four weeks of made-up jobs, Monday check on
  problems    searches that hit trouble: sites that didn't answer, drafts
              that failed, a week that stopped with an error

What's different in the test copy:
  - It never reads your real files, or keys exported in your shell profile.
  - "Check every Monday" is a pretend switch; your real Monday check stays as it is.
  - Connecting Notion accepts anything and never contacts Notion; jobs go
    to the test copy's spreadsheet instead.
  - "Find new jobs" really searches the job sites (that only reads public
    listings) and saves to sandbox/applications.csv. Drafts are written
    only if you paste an Anthropic key into the test copy.
"""
import csv
import json
import os
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

FOLDER = Path(__file__).resolve().parent.parent / "sandbox"

if __name__ == "__main__":  # must happen before settings is imported
    os.environ.setdefault("JOBSEARCH_DATA_DIR", str(FOLDER))

import config_store as store
import history
import schedule
from settings import DATA, ROOT, SANDBOX
from tracker_csv import COLUMNS

if not SANDBOX:
    raise RuntimeError("sandbox.py only runs in the test copy (JOBSEARCH_DATA_DIR is not set).")

MARKER = DATA / ".sandbox"  # what makes a folder safe to empty
CURRENT = DATA / ".sandbox.json"  # which starting point was loaded last
KEEP = {".sandbox", ".app_state.json", ".window.json", ".run.lock", "logs"}  # the running app's own files


# ── Starting points ─────────────────────────────────────────────────

SETUP_ANSWERS = {
    "field": 1, "level": 1, "cities": ["New York"], "remote": True, "min_salary": "150k",
    "companies": [{"key": "greenhouse_companies", "slug": "figma"},
                  {"key": "ashby_companies", "slug": "linear"}],
    "tracker": "spreadsheet",
}

# Made-up companies and postings. Links go to example.com.
JOBS = [
    ("Northwind", "Senior Product Designer", "New York, NY", "$160,000–$195,000", ["Senior", "New York is on your list"], True),
    ("Lumen Labs", "Staff Product Designer", "Remote (US)", "$185,000–$230,000", ["Staff", "Remote counts"], True),
    ("Parcel", "Senior UX Designer, Checkout", "Remote (US)", "", ["Senior", "Remote counts", "Check pay before applying"], False),
    ("Fieldnote", "Lead Product Designer", "Brooklyn, NY", "$150,000–$170,000", ["Lead", "Brooklyn is on your list"], False),
    ("Harbor Health", "Principal Designer, Patient Apps", "Remote (US)", "$140,000–$210,000", ["Principal", "Remote counts"], True),
    ("Quill", "Senior Interaction Designer", "New York, NY", "$120,000–$155,000", ["Senior", "New York is on your list"], False),
    ("Brightline", "Founding Product Designer", "Remote (US)", "$170,000–$200,000", ["Founding", "Remote counts"], False),
    ("Orbit Pay", "Senior Product Designer, Growth", "New York, NY", "", ["Senior", "New York is on your list", "Check pay before applying"], False),
    ("Canopy", "Staff UX Designer", "Remote (US)", "$190,000–$240,000", ["Staff", "Remote counts"], True),
    ("Tessellate", "Senior Experience Designer", "Remote (US)", "$155,000–$180,000", ["Senior", "Remote counts"], False),
    ("Marigold", "Lead UX Designer, Platform", "New York, NY", "$165,000–$185,000", ["Lead", "New York is on your list"], False),
    ("Pinecrest", "Senior Product Designer", "Remote (US)", "$145,000–$175,000", ["Senior", "Remote counts"], False),
]


def job_card(i: int, posted: datetime) -> dict:
    company, title, location, salary, why, draft = JOBS[i % len(JOBS)]
    slug = f"{company}-{title}".lower().replace(" ", "-").replace(",", "")
    return {"company": company, "title": title, "location": location, "salary": salary,
            "url": f"https://example.com/jobs/{slug}", "posted_date": posted.date().isoformat(),
            "match_reason": f"title matches '{title}'", "why": why, "draft": draft}


def search(when: datetime, jobs: list[dict], **fields) -> dict:
    """One saved search, shaped like the ones real searches save."""
    added = len(jobs)
    run = {"finished_at": when.isoformat(timespec="seconds"), "state": "done",
           "message": f"Added {added} new job{'s' if added != 1 else ''} to your spreadsheet."
           if added else "Nothing new since last time.",
           "scanned": 180 + 13 * added, "matches": added + 3, "already": 3,
           "skipped": {"no_title_match": 120, "no_seniority": 31, "bad_location": 22,
                       "salary_too_low": 4},
           "source_problem": "", "draft_problem": "", "details": None, "fix": None,
           "added": jobs}
    run.update(fields)
    return run


def mondays(now: datetime, weeks_back: int) -> datetime:
    """9:05 on the Monday `weeks_back` weeks ago (or later today if it's Monday)."""
    monday = (now - timedelta(days=now.weekday(), weeks=weeks_back)).replace(
        hour=9, minute=5, second=0, microsecond=0)
    return min(monday, now - timedelta(minutes=5))


def write_history(runs: list[dict]) -> None:
    history.PATH.write_text(json.dumps(runs, ensure_ascii=False, indent=1))


def write_spreadsheet(runs: list[dict]) -> None:
    """The jobs from those searches, as rows in the test spreadsheet."""
    path = DATA / "applications.csv"
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for run in runs:
            for job in run["added"]:
                writer.writerow({"Status": "New", "Company": job["company"], "Title": job["title"],
                                 "Location": job["location"],
                                 "Salary": job["salary"] or "unlisted (check posting)",
                                 "Posted": job["posted_date"], "Link": job["url"],
                                 "Why it matched": job["match_reason"],
                                 "Draft": "drafts/sample.md" if job["draft"] else "",
                                 "Date found": run["finished_at"][:10], "Source": "sandbox",
                                 "ID": job["url"]})


def answer_setup() -> None:
    from app_server import settings_from_page
    store.save_settings(settings_from_page(SETUP_ANSWERS))


def with_jobs(now: datetime) -> None:
    answer_setup()
    runs, n = [], 0
    for weeks_back, count in ((3, 3), (2, 0), (1, 4), (0, 5)):
        when = mondays(now, weeks_back)
        jobs = [job_card(n + i, when - timedelta(days=1 + i)) for i in range(count)]
        n += count
        runs.append(search(when, jobs))
    write_history(runs)
    write_spreadsheet(runs)
    schedule.turn_on()


def problems(now: datetime) -> None:
    answer_setup()
    two = mondays(now, 2)
    last = mondays(now, 1)
    this = mondays(now, 0)
    runs = [
        search(two, [job_card(i, two - timedelta(days=i + 1)) for i in range(3)]),
        search(last, [], state="error", added=[],
               message="Couldn't reach any job sites. Check your internet connection, "
                       "then try again.", scanned=0, matches=0, already=0, skipped={}),
        search(this, [job_card(3 + i, this - timedelta(days=i + 1)) for i in range(4)],
               source_problem="Indeed and Ashby didn't respond, so this list may be incomplete.",
               draft_problem="Drafts stopped after 1 job because Anthropic didn't accept "
                             "your key. Check it in Settings → Extras."),
    ]
    write_history(runs)
    write_spreadsheet([r for r in runs if r["state"] == "done"])


SCENARIOS = {
    "fresh": ("Nothing set up", lambda now: None),
    "set-up": ("Set up, no search yet", lambda now: answer_setup()),
    "with-jobs": ("Four weeks of jobs", with_jobs),
    "problems": ("Searches with problems", problems),
}


# ── Starting over ───────────────────────────────────────────────────

def empty_folder() -> None:
    """Removes the test copy's files, keeping the running app's own ones.
    Refuses any folder that isn't a test copy, so it can never empty your
    real one."""
    if ROOT.is_relative_to(DATA) or DATA == Path.home():
        raise RuntimeError(f"Not a test folder: {DATA}")
    if any(p.name not in KEEP for p in DATA.iterdir()) and not MARKER.exists():
        raise RuntimeError(f"{DATA} has files but isn't a test folder. Pick an empty folder.")
    MARKER.touch()
    for item in DATA.iterdir():
        if item.name in KEEP:
            continue
        shutil.rmtree(item) if item.is_dir() and not item.is_symlink() else item.unlink()


def load(name: str, now: datetime | None = None) -> None:
    if name not in SCENARIOS:
        raise ValueError(f"No starting point called “{name}”.")
    empty_folder()
    SCENARIOS[name][1](now or datetime.now())
    CURRENT.write_text(json.dumps({"scenario": name}))


def current() -> str | None:
    try:
        return json.loads(CURRENT.read_text()).get("scenario")
    except (OSError, ValueError):
        return None


def for_page() -> dict:
    """What the test copy's menu shows."""
    return {"scenario": current(),
            "scenarios": [{"name": k, "label": v[0]} for k, v in SCENARIOS.items()]}


def main(argv: list[str]) -> int:
    if "--list" in argv:
        for name, (label, _) in SCENARIOS.items():
            print(f"  {name:<10}  {label}")
        return 0
    names = [a for a in argv if not a.startswith("-")]
    import app_server
    if names:
        if app_server.search_running(app_server.LOCK_PATH):
            print("The test copy is searching. Try again when it finishes.")
            return 1
        try:
            load(names[0])
        except ValueError as e:
            print(e, "Run with --list to see them.")
            return 1
        print(f"Test copy reset to “{names[0]}”.")
    elif not MARKER.exists():
        load("fresh")
    print(f"Test files: {DATA}")
    return app_server.open_app(use_browser="--browser" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
