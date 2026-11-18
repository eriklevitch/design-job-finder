# Notes for AI assistants (Claude Code and similar)

People using this project are often designers, not developers. Keep
explanations plain and avoid jargon.

- **The app:** people use **Job Finder**, a small page served on 127.0.0.1 by
  `engine/app_server.py` (page in `engine/app/`), opened from a Dock app
  that `engine/mac_app.py` builds in `~/Applications`. Don't send them back
  to Terminal or to editing files when the app can do it.
- **Setup:** point them to Job Finder → Settings, or edit the "YOUR SEARCH"
  section of `config.yaml` for them (`engine/setup_wizard.py` is the Terminal
  version). If `venv/` is missing, run `bash install.sh` with
  `JOBSEARCH_SOURCE_DIR=.` set to install from this folder.
- **Run:** `venv/bin/python engine/main.py --dry-run` previews and changes
  nothing; without `--dry-run` it adds new jobs to the tracker.
- **Personal files** (`config.yaml`, `portfolio_notes.md`, `.env`,
  `applications.csv`, `drafts/`, `logs/`, `last_run.json`) are gitignored. Never commit them or paste
  their contents anywhere outside this computer.
- **Tests:** `venv/bin/pip install pytest` (once), then `venv/bin/python -m pytest -q`. If you change filter rules,
  add a test in `tests/test_sources.py`. App and settings tests are in
  `tests/test_app.py`.
- **Company lists:** `venv/bin/python engine/check_boards.py` checks every
  company in `config.yaml` and says which ones are on the wrong list or
  have the wrong name.
