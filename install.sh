#!/bin/bash
# Installs (or updates) Product Design Job Finder.
#
#   curl -fsSL https://raw.githubusercontent.com/eriklevitch/product-design-job-finder/main/install.sh | bash
#
# What it does, in order:
#   1. Finds Python 3.10 or newer. If your Mac doesn't have it, it fetches
#      a private copy (using uv) that only this tool uses.
#   2. Downloads this project into a "job-search" folder in your home folder.
#      If the folder already exists, it updates the code and leaves your
#      settings, notes, keys and tracker alone.
#   3. Installs the libraries it needs into that folder (nothing system-wide).
#   4. Makes the "Job Finder" app, adds it to the Dock and opens it.
set -e

REPO="${JOBSEARCH_REPO:-eriklevitch/product-design-job-finder}"
DEST="${JOBSEARCH_DIR:-$HOME/job-search}"
# For testing: copy from a local folder instead of downloading.
LOCAL_SOURCE="${JOBSEARCH_SOURCE_DIR:-}"

bold() { printf "\n\033[1m%s\033[0m\n" "$1"; }

bold "Product Design Job Finder: installing"

# 1. Python ---------------------------------------------------------
PY=""
for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1; then
    PY="$(command -v "$candidate")"
    break
  fi
done
if [ -n "$PY" ]; then
  echo "Using $("$PY" --version)"
fi

# 2. Download -------------------------------------------------------
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
if [ -n "$LOCAL_SOURCE" ]; then
  SRC="$LOCAL_SOURCE"
else
  echo "Downloading..."
  curl -fsSL "https://github.com/$REPO/archive/refs/heads/main.zip" -o "$TMP/src.zip"
  unzip -q "$TMP/src.zip" -d "$TMP"
  SRC="$(find "$TMP" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
fi
mkdir -p "$DEST"
# Copy the code. Your own files (config.yaml, portfolio_notes.md, .env,
# applications.csv, drafts/, logs/) aren't part of the download, so they're kept.
( cd "$SRC" && tar --exclude='./venv' --exclude='./.git' --exclude='./config.yaml' \
    --exclude='./portfolio_notes.md' --exclude='./.env' --exclude='./applications.csv' \
    --exclude='./drafts' --exclude='./logs' --exclude='./.app_state.json' \
    --exclude='./last_run.json' --exclude='./history.json' --exclude='./.run.lock' --exclude='./.claude' \
    --exclude='__pycache__' --exclude='.pytest_cache' -cf - . ) |
  ( cd "$DEST" && tar -xf - )
# Older versions used double-click .command files; the app replaces them.
rm -f "$DEST"/*.command

# 3. Libraries ------------------------------------------------------
echo "Installing (this takes a minute the first time)..."
if [ ! -x "$DEST/venv/bin/python" ]; then
  if [ -n "$PY" ]; then
    "$PY" -m venv "$DEST/venv"
  else
    # No suitable Python on this Mac: fetch uv, which brings its own.
    echo "Getting Python (only used by Job Finder)..."
    UV_DIR="$DEST/.uv"
    if [ ! -x "$UV_DIR/uv" ]; then
      curl -LsSf https://astral.sh/uv/install.sh |
        env UV_INSTALL_DIR="$UV_DIR" UV_NO_MODIFY_PATH=1 INSTALLER_NO_MODIFY_PATH=1 sh >/dev/null
    fi
    # Keep uv's Python inside this folder, so deleting the folder removes everything.
    UV_PYTHON_INSTALL_DIR="$UV_DIR/python" UV_CACHE_DIR="$UV_DIR/cache" \
      "$UV_DIR/uv" venv --quiet --seed --python 3.12 --managed-python "$DEST/venv"
    rm -rf "$UV_DIR/cache"
  fi
fi
"$DEST/venv/bin/python" -m pip install --quiet --upgrade pip
"$DEST/venv/bin/python" -m pip install --quiet --upgrade -r "$DEST/requirements.txt"

bold "Installed in $DEST"

# 4. The app --------------------------------------------------------
if [ "$(uname)" = "Darwin" ]; then
  if [ -z "$JOBSEARCH_SKIP_SETUP" ]; then
    DOCK="--dock"
    [ -n "$JOBSEARCH_NO_DOCK" ] && DOCK=""
    "$DEST/venv/bin/python" "$DEST/engine/mac_app.py" $DOCK
    # If an older copy of the app is still running, let it pick up the new code.
    if [ -f "$DEST/.app_state.json" ]; then
      pid="$("$DEST/venv/bin/python" -c 'import json,sys; print(json.load(open(sys.argv[1]))["pid"])' "$DEST/.app_state.json" 2>/dev/null || true)"
      [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
      rm -f "$DEST/.app_state.json"
    fi
    # Open it the way the Dock does, so it gets its own window (and Terminal is free).
    open "${JOBSEARCH_APP_DIR:-$HOME/Applications}/Job Finder.app" \
      || "$DEST/venv/bin/python" "$DEST/engine/app_server.py" --browser >/dev/null
    bold "Done. Job Finder is open."
    echo "Next time, click Job Finder in your Dock (or search for it with ⌘ Space)."
  else
    "$DEST/venv/bin/python" "$DEST/engine/mac_app.py" >/dev/null
  fi
else
  # Not a Mac: ask the setup questions here instead.
  if [ -z "$JOBSEARCH_SKIP_SETUP" ] && { [ -t 0 ] || [ -r /dev/tty ]; }; then
    cd "$DEST"
    "$DEST/venv/bin/python" engine/setup_wizard.py < /dev/tty || true
  fi
fi
