"""Finds new jobs and adds them to your tracker.

Most people run this from the Design Job Finder app ("Find new jobs"). From
Terminal:
  python engine/main.py             find jobs and add new ones to your tracker
  python engine/main.py --dry-run   preview matches; writes nothing, costs nothing
  ... --summary FILE                also write progress and results to FILE
                                    as JSON (the app reads this)

Steps: pull postings from every source -> keep the ones that match your
settings -> skip ones already in your tracker -> (optional) write a
tailored draft -> add them to your tracker. Every step prints a short
summary so you can see what happened.
"""
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path

try:
    import fcntl  # Mac and Linux
except ImportError:  # Windows: no lock, runs simply aren't guarded
    fcntl = None

import history
import sources
import requests

from settings import CRASH_MESSAGE, DATA, SANDBOX, load_config, load_env, resolve_path, scrub
from sources import fetch_adzuna, fetch_greenhouse, fetch_lever, fetch_ashby, fetch_jobspy, filter_jobs
from tracker_csv import CsvTracker
from draft import drafting_key, load_portfolio_notes, generate_draft

LOCK_PATH = DATA / ".run.lock"

DROP_LABELS = [
    ("no_title_match", "title isn't a match"),
    ("no_seniority", "level isn't a match"),
    ("excluded_title", "excluded title word"),
    ("bad_location", "location isn't a match"),
    ("too_old", "posted too long ago"),
    ("salary_too_low", "pay below your minimum"),
]


class Report:
    """Progress and results for the app. Does nothing without --summary."""

    def __init__(self, path: str | None, dry_run: bool):
        self.path = Path(path) if path else None
        self.data = {"state": "running", "dry_run": dry_run, "step": "Starting…",
                     "started_at": datetime.now().isoformat(timespec="seconds")}

    def update(self, **fields) -> None:
        self.data.update(fields)
        if self.path:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False))
            tmp.replace(self.path)

    def finish(self, message: str, **fields) -> None:
        self.update(state="done", message=message,
                    finished_at=datetime.now().isoformat(timespec="seconds"), **fields)

    def fail(self, message: str, **fields) -> None:
        self.update(state="error", message=message,
                    finished_at=datetime.now().isoformat(timespec="seconds"), **fields)


def job_card(job: dict) -> dict:
    """What the app shows for one job."""
    card = {k: job.get(k, "") for k in ("company", "title", "location", "salary", "url",
                                        "posted_date", "match_reason")}
    card["why"] = job.get("why") or []
    card["draft"] = bool(job.get("has_draft"))
    return card


def get_tracker(config: dict):
    """The spreadsheet by default; Notion if chosen and set up."""
    if (config.get("tracker") or "spreadsheet").lower() == "notion" and SANDBOX:
        print("Note: the test copy never writes to Notion. Saving to its spreadsheet instead.\n")
    elif (config.get("tracker") or "spreadsheet").lower() == "notion":
        from notion_client import NotionTracker, NotionNotConfigured
        try:
            return NotionTracker(config)
        except NotionNotConfigured as e:
            print(f"Note: {e}")
            print("Saving to the spreadsheet instead for this run.\n")
    return CsvTracker(resolve_path(config.get("spreadsheet_path", "applications.csv")))


def count_companies(config: dict) -> int:
    return sum(len(config.get(k) or []) for k in
               ("greenhouse_companies", "lever_companies", "ashby_companies"))


def fetch_all(config: dict) -> tuple[list[dict], list[str], bool]:
    """Every source's postings, the names of the sites that didn't answer,
    and whether any site answered at all."""
    sources.reset_reach()
    jobs = []
    for fetch in (fetch_adzuna, fetch_greenhouse, fetch_lever, fetch_ashby, fetch_jobspy):
        name = fetch.__name__.removeprefix("fetch_")
        try:
            jobs += fetch(config)
        except Exception as e:  # one broken source never stops the run
            print(f"  [{name}] error, skipped: {e}")
            display = "Indeed" if name == "jobspy" else name.title()
            sources.reach["failed"].append(display)
            sources._progress(display, "failed")
    return jobs, list(sources.reach["failed"]), sources.reach["ok"] > 0


def track_sites(report: "Report", config: dict) -> list[dict]:
    """The list of sites the app shows while searching, updated as each
    one is checked: waiting, checking, done (with jobs found) or failed."""
    sites = [{"name": n, "state": "waiting", "jobs": 0} for n in sources.planned_sites(config)]

    def on_progress(name: str, state: str, jobs: int) -> None:
        for site in sites:
            if site["name"] == name and site["state"] in ("waiting", "checking"):
                site.update(state=state, jobs=jobs)
                break
        report.update(sites=sites)
    sources.progress = on_progress
    report.update(sites=sites)
    return sites


def source_problem(failed: list[str]) -> str:
    """One plain sentence about sites that didn't answer."""
    if not failed:
        return ""
    if len(failed) == 1:
        who = failed[0]
    elif len(failed) == 2:
        who = f"{failed[0]} and {failed[1]}"
    else:
        who = f"{failed[0]}, {failed[1]} and {len(failed) - 2} more"
    return f"{who} didn't respond, so this list may be incomplete."


def take_lock():
    """Only one search at a time (the app and the weekly schedule share
    this). Returns the open lock file, or None if a search is running."""
    handle = open(LOCK_PATH, "w")
    if fcntl is None:
        return handle
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


class Finish(Exception):
    """How a search ended: the message the app shows, whether it went
    well, and anything else to report (the jobs added, a fix to offer…).
    A step raises it to stop the search early; search() returns one when
    it gets to the end."""

    def __init__(self, message: str, ok: bool = True, **fields):
        super().__init__(message)
        self.message, self.ok, self.fields = message, ok, fields


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    dry_run = "--dry-run" in argv
    summary_path = argv[argv.index("--summary") + 1] if "--summary" in argv else None
    report = Report(summary_path, dry_run)
    lock = take_lock()  # released automatically when this program ends
    if lock is None:
        # Not a problem: the app follows the search that's already running.
        print("A search is already running. Try again when it finishes.")
        report.update(state="busy", message="Design Job Finder is already looking for jobs.")
        return 1
    try:
        outcome = search(report, dry_run)
    except Finish as stopped:
        outcome = stopped
    except Exception:
        details = scrub(traceback.format_exc())
        print(details)
        outcome = Finish(CRASH_MESSAGE, ok=False, details=details[-4000:],
                         added=report.data.get("added") or [])
    return wrap_up(report, outcome, dry_run)


def wrap_up(report: Report, outcome: Finish, dry_run: bool) -> int:
    """The one place every search ends. Tells the app how it went, and
    remembers real searches (history.json) so the app can show this
    week's jobs whenever it opens."""
    if outcome.ok:
        report.finish(outcome.message, **outcome.fields)
    else:
        report.fail(outcome.message, **outcome.fields)
    if not dry_run:
        history.add(report.data)
    return 0 if outcome.ok else 1


class TrackerProblem(Exception):
    """Notion stopped accepting jobs; says why in plain words."""

    def __init__(self, message: str, fix: dict | None = None, details: str = ""):
        super().__init__(message)
        self.message, self.fix, self.details = message, fix, details


def notion_problem(e: requests.RequestException) -> TrackerProblem:
    status = getattr(getattr(e, "response", None), "status_code", None)
    details = scrub(str(e))
    if status in (401, 403, 404):
        return TrackerProblem("Notion isn't accepting new jobs. It may have been disconnected "
                              "from your page. Reconnect it in Settings, then try again.",
                              {"label": "Reconnect Notion", "section": "sec-tracker"}, details)
    if status is None:
        return TrackerProblem("Couldn't reach Notion. Check your internet connection, "
                              "then try again.", None, details)
    return TrackerProblem(f"Notion had a problem saving jobs (error {status}). "
                          "Try again in a few minutes.", None, details)


def tracker_call(tracker, fn, *args):
    """Runs one tracker step, turning Notion's errors into a TrackerProblem."""
    try:
        return fn(*args)
    except requests.RequestException as e:
        if friendly_name(tracker) == "Notion":
            raise notion_problem(e) from e
        raise


def search(report: Report, dry_run: bool) -> Finish:
    """Finds jobs and adds the new ones to the tracker. Each step either
    hands its results to the next or stops the search with a Finish."""
    load_env()
    config = load_config()
    jobs = find_postings(report, config)
    matches = keep_matches(report, jobs, config)
    if dry_run:
        return preview(matches)
    tracker = get_tracker(config)
    new_jobs = skip_tracked(report, tracker, matches)
    return add_jobs(report, tracker, new_jobs, config)


def find_postings(report: Report, config: dict) -> list[dict]:
    """Step 1: every posting from every site, with live progress for the app."""
    n = count_companies(config)
    report.update(step=f"Checking Indeed and {n} careers page{'s' if n != 1 else ''}…"
                  if n else "Checking Indeed…")
    print("=== Looking for jobs ===")
    sites = track_sites(report, config)
    try:
        jobs, failed, reached = fetch_all(config)
    finally:
        sources.progress = None
    for site in sites:  # anything that never finished
        if site["state"] in ("waiting", "checking"):
            site["state"] = "failed" if site["state"] == "checking" else "skipped"
    report.update(sites=sites)
    print(f"Postings found: {len(jobs)}")
    if failed and not reached:
        print("\nCouldn't reach any job sites. Check your internet connection and try again.")
        raise Finish("Couldn't reach any job sites. Check your internet connection, "
                     "then try again.", ok=False, added=[])
    report.update(source_problem=source_problem(failed))
    return jobs


def keep_matches(report: Report, jobs: list[dict], config: dict) -> list[dict]:
    """Step 2: only the postings that match your settings."""
    report.update(step=f"Comparing {len(jobs)} listings with your search…")
    print("\n=== Checking them against your settings ===")
    matches, stats = filter_jobs(jobs, config)
    print(f"Checked:  {stats['scanned']}")
    skipped = {}
    for key, label in DROP_LABELS:
        if stats.get(key):
            skipped[key] = stats[key]
            print(f"  skipped, {label}: {stats[key]}")
    print(f"Matches:  {len(matches)}")
    report.update(scanned=stats["scanned"], skipped=skipped, matches=len(matches))
    if not matches:
        print("\nNo matching jobs this time. If that keeps happening, try a wider")
        print("search: open Design Job Finder → Settings, or see 'Change your search' in the README.")
        raise Finish("No jobs matched your search this time.", added=[])
    return matches


def preview(matches: list[dict]) -> Finish:
    """With --dry-run: show the matches and save nothing."""
    print("\n=== PREVIEW (nothing saved) ===")
    for job in matches:
        print(f"\n{job['company']}: {job['title']}")
        print(f"  {job['url']}")
        print(f"  why: {job['match_reason']}")
    print(f"\n{len(matches)} matches. Nothing was saved. Run without --dry-run to save them.")
    return Finish(f"{len(matches)} jobs match. Nothing was saved.",
                  added=[job_card(j) for j in matches])


def skip_tracked(report: Report, tracker, matches: list[dict]) -> list[dict]:
    """Step 3: drop jobs already in the tracker, and repeats within this
    search (the same job can appear twice, e.g. on two pages of results)."""
    try:
        existing = tracker_call(tracker, tracker.existing_job_keys)
    except TrackerProblem as p:
        print(f"\n{p.message}")
        raise Finish(p.message, ok=False, fix=p.fix, details=p.details, added=[]) from p
    seen = set()
    new_jobs = []
    for j in matches:
        key = j.get("job_key", "")
        if key in existing or key in seen:
            continue
        seen.add(key)
        new_jobs.append(j)
    print(f"Already in your tracker: {len(matches) - len(new_jobs)}  |  New: {len(new_jobs)}")
    report.update(already=len(matches) - len(new_jobs))
    if not new_jobs:
        print("\nNothing new since last time.")
        raise Finish("Nothing new since last time.", added=[])
    return new_jobs


def add_jobs(report: Report, tracker, new_jobs: list[dict], config: dict) -> Finish:
    """Step 4: write a draft for each job (if there's an Anthropic key)
    and add it to the tracker."""
    has_key = drafting_key(config) is not None
    drafting = has_key  # turned off if the key turns out not to work
    notes = load_portfolio_notes(config) if drafting else ""
    print(f"\n=== Adding to {tracker.describe()} ===")
    added = []
    draft_errors = []
    for i, job in enumerate(new_jobs, 1):
        report.update(step=f"{'Writing drafts and adding' if drafting else 'Adding'} jobs to "
                           f"{friendly_name(tracker)} ({i} of {len(new_jobs)})…")
        draft_text = None
        note = ""
        if drafting:
            try:
                draft_text = generate_draft(job, notes, config)
            except Exception as e:
                # The job is still added, just without a draft.
                note = f"  (draft failed: {e})"
                draft_errors.append(str(e))
                if key_problem(str(e)):
                    # A bad key or no credit will fail for every job, so
                    # stop asking and just add the rest.
                    drafting = False
                    note += "\n  Skipping drafts for the rest of this search."
        try:
            tracker_call(tracker, tracker.add_job, job, draft_text)
        except TrackerProblem as p:
            print(f"\n{p.message}")
            message = f"Saved {jobs_text(len(added))}, then stopped. {p.message}" \
                if added else p.message
            raise Finish(message, ok=False, fix=p.fix, details=p.details,
                         added=[job_card(j) for j in added]) from p
        except PermissionError as e:
            print(f"\nCouldn't write to {tracker.describe()}. If it's open in another app,")
            print("close it and run Find Jobs again.")
            raise Finish(f"Saved {jobs_text(len(added))}, then couldn't save more. If your "
                         "spreadsheet is open in another app, close it and try again.",
                         ok=False, added=[job_card(j) for j in added]) from e
        job["has_draft"] = bool(draft_text)
        added.append(job)
        report.data["added"] = [job_card(j) for j in added]  # kept if something breaks later
        print(f"  + {job['company']}: {job['title']}{note}")

    print(f"\nDone. Added {len(added)} new job(s) to {tracker.describe()}.")
    if not has_key:
        print("Tip: add an Anthropic key (Design Job Finder → Settings) to get tailored resume")
        print("bullets and a cover letter opening with every job.")
    return Finish(f"Added {len(added)} new job{'s' if len(added) != 1 else ''} to "
                  f"{friendly_name(tracker)}.", added=[job_card(j) for j in added],
                  draft_problem=draft_problem(draft_errors, len(added),
                                              sum(1 for j in added if j["has_draft"])))


def jobs_text(n: int) -> str:
    """Like "1 job" or "3 jobs"."""
    return f"{n} job{'s' if n != 1 else ''}"


def friendly_name(tracker) -> str:
    return "Notion" if type(tracker).__name__ == "NotionTracker" else "your spreadsheet"


def key_problem(error: str) -> str:
    """"key" if Anthropic didn't accept the key, "credit" if the account
    is out of credit, or "" for any other error. Both of these will fail
    the same way for every job."""
    if "401" in error or "authentication" in error or "x-api-key" in error:
        return "key"
    if "credit" in error.lower() or "billing" in error.lower():
        return "credit"
    return ""


def draft_problem(errors: list[str], total: int, written: int = 0) -> str:
    """One plain sentence about drafts that couldn't be written."""
    if not errors:
        return ""
    problems = {key_problem(e) for e in errors}
    start = (f"Drafts stopped after {jobs_text(written)}" if written
             else "No drafts were written")
    if "key" in problems:
        return (f"{start} because Anthropic didn't accept your key. "
                "Check it in Settings → Extras.")
    if "credit" in problems:
        return (f"{start} because your Anthropic account is out of credit. "
                "Add credit at console.anthropic.com. The jobs were still added.")
    return f"{len(errors)} of {total} drafts couldn't be written. The jobs were still added."


if __name__ == "__main__":
    sys.exit(main())
