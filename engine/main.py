"""Finds new jobs and adds them to your tracker.

Most people run this from the Job Finder app ("Find new jobs"). From
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
from datetime import datetime
from pathlib import Path

try:
    import fcntl  # Mac and Linux
except ImportError:  # Windows: no lock, runs simply aren't guarded
    fcntl = None

from settings import ROOT, load_config, load_env, resolve_path
from sources import fetch_adzuna, fetch_greenhouse, fetch_lever, fetch_ashby, fetch_jobspy, filter_jobs
from tracker_csv import CsvTracker
from draft import drafting_key, load_portfolio_notes, generate_draft

LAST_RUN = ROOT / "last_run.json"
LOCK_PATH = ROOT / ".run.lock"

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


def job_card(job: dict) -> dict:
    return {k: job.get(k, "") for k in ("company", "title", "location", "salary", "url",
                                        "match_reason")}


def get_tracker(config: dict):
    """The spreadsheet by default; Notion if chosen and set up."""
    if (config.get("tracker") or "spreadsheet").lower() == "notion":
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


def fetch_all(config: dict) -> list[dict]:
    jobs = []
    for fetch in (fetch_adzuna, fetch_greenhouse, fetch_lever, fetch_ashby, fetch_jobspy):
        try:
            jobs += fetch(config)
        except Exception as e:  # one broken source never stops the run
            print(f"  [{fetch.__name__.removeprefix('fetch_')}] error, skipped: {e}")
    return jobs


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


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    dry_run = "--dry-run" in argv
    summary_path = argv[argv.index("--summary") + 1] if "--summary" in argv else None
    report = Report(summary_path, dry_run)
    lock = take_lock()  # released automatically when this program ends
    if lock is None:
        print("A search is already running. Try again when it finishes.")
        report.update(state="error", message="Job Finder is already looking for jobs. "
                                             "Try again in a few minutes.")
        return 1
    load_env()
    config = load_config()

    n = count_companies(config)
    report.update(step=f"Checking Indeed and {n} company career page{'s' if n != 1 else ''}…"
                  if n else "Checking Indeed…")
    print("=== Looking for jobs ===")
    jobs = fetch_all(config)
    print(f"Postings found: {len(jobs)}")

    report.update(step=f"Comparing {len(jobs)} jobs with your settings…")
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
        print("search: open Job Finder → Settings, or see 'Change your search' in the README.")
        report.finish("No jobs matched your settings this time.", added=[])
        save_last_run(report, dry_run)
        return 0

    if dry_run:
        print("\n=== PREVIEW (nothing saved) ===")
        for job in matches:
            print(f"\n{job['company']}: {job['title']}")
            print(f"  {job['url']}")
            print(f"  why: {job['match_reason']}")
        print(f"\n{len(matches)} matches. Nothing was saved. Run without --dry-run to save them.")
        report.finish(f"{len(matches)} jobs match. Nothing was saved.",
                      added=[job_card(j) for j in matches])
        return 0

    tracker = get_tracker(config)
    existing = tracker.existing_job_keys()

    # Also skip repeats within this run (the same job can appear twice,
    # e.g. on two pages of results).
    seen = set()
    new_matches = []
    for j in matches:
        key = j.get("job_key", "")
        if key in existing or key in seen:
            continue
        seen.add(key)
        new_matches.append(j)

    print(f"Already in your tracker: {len(matches) - len(new_matches)}  |  New: {len(new_matches)}")
    report.update(already=len(matches) - len(new_matches))
    if not new_matches:
        print("\nNothing new since last time.")
        report.finish("Nothing new since last time.", added=[])
        save_last_run(report, dry_run)
        return 0

    drafting = drafting_key(config) is not None
    notes = load_portfolio_notes(config) if drafting else ""
    print(f"\n=== Adding to {tracker.describe()} ===")
    added = []
    draft_errors = []
    for i, job in enumerate(new_matches, 1):
        report.update(step=f"{'Writing drafts and adding' if drafting else 'Adding'} jobs to "
                           f"{friendly_name(tracker)} ({i} of {len(new_matches)})…")
        draft_text = None
        note = ""
        if drafting:
            try:
                draft_text = generate_draft(job, notes, config)
            except Exception as e:
                # The job is still added, just without a draft.
                note = f"  (draft failed: {e})"
                draft_errors.append(str(e))
        try:
            tracker.add_job(job, draft_text)
        except PermissionError:
            print(f"\nCouldn't write to {tracker.describe()}. If it's open in another app,")
            print("close it and run Find Jobs again.")
            report.update(state="error", added=[job_card(j) for j in added],
                          message=f"Saved {len(added)} jobs, then couldn't save more. If your "
                                  "spreadsheet is open in another app, close it and try again.")
            return 1
        added.append(job)
        print(f"  + {job['company']}: {job['title']}{note}")

    print(f"\nDone. Added {len(added)} new job(s) to {tracker.describe()}.")
    if not drafting:
        print("Tip: add an Anthropic key (Job Finder → Settings) to get tailored resume")
        print("bullets and a cover letter opening with every job.")
    report.finish(f"Added {len(added)} new job{'s' if len(added) != 1 else ''} to "
                  f"{friendly_name(tracker)}.", added=[job_card(j) for j in added],
                  draft_problem=draft_problem(draft_errors, len(added)))
    save_last_run(report, dry_run)
    return 0


def friendly_name(tracker) -> str:
    return "Notion" if type(tracker).__name__ == "NotionTracker" else "your spreadsheet"


def draft_problem(errors: list[str], total: int) -> str:
    """One plain sentence about drafts that couldn't be written."""
    if not errors:
        return ""
    if any("401" in e or "authentication" in e or "x-api-key" in e for e in errors):
        return ("Drafts couldn't be written because Anthropic didn't accept your key. "
                "Check it in Settings → Drafts.")
    if any("credit" in e.lower() or "billing" in e.lower() for e in errors):
        return "Drafts couldn't be written: your Anthropic account is out of credit."
    return f"{len(errors)} of {total} drafts couldn't be written. The jobs were still added."


def save_last_run(report: Report, dry_run: bool) -> None:
    """Remembers the latest real run for the app's "Last checked" line."""
    if dry_run:
        return
    try:
        LAST_RUN.write_text(json.dumps({
            "finished_at": report.data.get("finished_at"),
            "added": len(report.data.get("added") or []),
            "message": report.data.get("message", ""),
        }))
    except OSError:
        pass


if __name__ == "__main__":
    sys.exit(main())
