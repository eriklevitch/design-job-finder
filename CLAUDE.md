# Notes for AI assistants (Claude Code and similar)

People using this project are often designers, not developers. Keep
explanations plain and avoid jargon.

- **The app:** people use **Design Job Finder**, a small page served on 127.0.0.1 by
  `engine/app_server.py` (page in `engine/app/`) and shown in its own window
  (pywebview; `--browser` uses the browser instead), opened from a Dock app
  that `engine/mac_app.py` builds in `~/Applications`. Don't send them back
  to Terminal or to editing files when the app can do it.
- **Setup:** point them to Design Job Finder → Settings, or edit the "YOUR SEARCH"
  section of `config.yaml` for them (`engine/setup_wizard.py` is the Terminal
  version). If `venv/` is missing, run `bash install.sh` with
  `JOBSEARCH_SOURCE_DIR=.` set to install from this folder.
- **Run:** `venv/bin/python engine/main.py --dry-run` previews and changes
  nothing; without `--dry-run` it adds new jobs to the tracker.
- **Test copy:** `venv/bin/python engine/sandbox.py [fresh|set-up|with-jobs|problems]`
  opens the same app with made-up files in `sandbox/` (via
  `JOBSEARCH_DATA_DIR`), so the whole flow can be tried without touching
  real files, keys or the Monday check. A menu at the top of its window
  starts over from any starting point. Use it to check UI changes.
- **Personal files** (`config.yaml`, `portfolio_notes.md`, `.env`,
  `applications.csv`, `drafts/`, `logs/`, `last_run.json`, `history.json`) are gitignored. Never commit them or paste
  their contents anywhere outside this computer.
- **Tests:** `venv/bin/pip install pytest` (once), then `venv/bin/python -m pytest -q`. If you change filter rules,
  add a test in `tests/test_sources.py`. App and settings tests are in
  `tests/test_app.py`.
- **Company lists:** `venv/bin/python engine/check_boards.py` checks every
  company in `config.yaml` and says which ones are on the wrong list or
  have the wrong name.
- **Releasing:** installed copies offer an update when the number in
  `VERSION` on GitHub's `main` is higher than theirs (`engine/updates.py`).
  Raise it when a change is ready for everyone; leave it for small fixes.
- **Library versions:** the installer uses the exact versions in
  `constraints.txt` with its own Python 3.12. After changing
  `requirements.txt`, refresh it with the command at the top of that file
  and run the tests.
