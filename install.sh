#!/bin/bash
# Installs (or updates) Design Job Finder.
#
#   curl -fsSL https://raw.githubusercontent.com/eriklevitch/design-job-finder/main/install.sh | bash
#
# What it does, in order:
#   1. Downloads this project into a "job-search" folder in your home folder.
#      If the folder already exists, it updates the code and leaves your
#      settings, notes, keys and tracker alone.
#   2. Fetches a private copy of Python (using uv) that only this tool uses,
#      so it works the same on every Mac and never touches the Mac's own.
#   3. Installs the exact library versions in constraints.txt into that
#      folder (nothing system-wide).
#   4. Makes the "Design Job Finder" app, adds it to the Dock and opens it.
#
# Everything lives in the job-search folder, so deleting it removes it all.
set -e

REPO="${JOBSEARCH_REPO:-eriklevitch/design-job-finder}"
DEST="${JOBSEARCH_DIR:-$HOME/job-search}"
# For testing: copy from a local folder instead of downloading.
LOCAL_SOURCE="${JOBSEARCH_SOURCE_DIR:-}"

bold() { printf "\n\033[1m%s\033[0m\n" "$1"; }

bold "Design Job Finder: installing"

# 1. Download -------------------------------------------------------
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
    --exclude='./.uv' --exclude='./venv.new' --exclude='./venv.old' --exclude='./.window.json' \
    --exclude='./.update_check.json' \
    --exclude='__pycache__' --exclude='.pytest_cache' -cf - . ) |
  ( cd "$DEST" && tar -xf - )
# Older versions used double-click .command files; the app replaces them.
rm -f "$DEST"/*.command

# 2. Python ---------------------------------------------------------
# Always the same private Python (not whatever the Mac has), so every
# install behaves alike, and a Homebrew upgrade can't break it.
PYTHON_VERSION=3.12
UV_DIR="$DEST/.uv"
UV="$UV_DIR/uv"
export UV_PYTHON_INSTALL_DIR="$UV_DIR/python" UV_CACHE_DIR="$UV_DIR/cache"
if [ ! -x "$UV" ]; then
  echo "Getting Python (only used by Design Job Finder)..."
  curl -LsSf https://astral.sh/uv/install.sh |
    env UV_INSTALL_DIR="$UV_DIR" UV_NO_MODIFY_PATH=1 INSTALLER_NO_MODIFY_PATH=1 sh >/dev/null
fi
# Keep the existing setup if it works and already uses that private Python.
# Older installs used the Mac's Python, or were built without
# --relocatable (so venv/bin/pip still pointed at venv.new after the
# rename below); those get rebuilt once.
VENV="$DEST/venv"
if ! { grep -qF "home = $UV_DIR/python/" "$DEST/venv/pyvenv.cfg" 2>/dev/null &&
       grep -qx "relocatable = true" "$DEST/venv/pyvenv.cfg" 2>/dev/null &&
       "$DEST/venv/bin/python" -c '' 2>/dev/null; }; then
  VENV="$DEST/venv.new"
  rm -rf "$VENV"
  # --relocatable: it's built as venv.new and renamed to venv, so its
  # scripts (pip and others) must find Python by their own location.
  "$UV" venv --quiet --seed --relocatable --python "$PYTHON_VERSION" --managed-python "$VENV"
fi

# 3. Libraries ------------------------------------------------------
echo "Installing (this takes a minute the first time)..."
"$UV" pip install --quiet --python "$VENV/bin/python" \
  -r "$DEST/requirements.txt" -c "$DEST/constraints.txt"
if [ "$VENV" != "$DEST/venv" ]; then
  # Swap in the new setup only once it's complete, so a failed install
  # leaves the old one working.
  rm -rf "$DEST/venv.old"
  [ -d "$DEST/venv" ] && mv "$DEST/venv" "$DEST/venv.old"
  mv "$VENV" "$DEST/venv"
  rm -rf "$DEST/venv.old"
fi
rm -rf "$UV_CACHE_DIR"

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
    # Updating from inside the app: its window reopens on its own.
    if [ -n "$JOBSEARCH_FROM_APP" ]; then
      bold "Updated."
      exit 0
    fi
    # Open it the way the Dock does, so it gets its own window (and Terminal is free).
    open "${JOBSEARCH_APP_DIR:-$HOME/Applications}/Design Job Finder.app" \
      || "$DEST/venv/bin/python" "$DEST/engine/app_server.py" --browser >/dev/null
    bold "Done. Design Job Finder is open."
    echo "Next time, click Design Job Finder in your Dock (or search for it with ⌘ Space)."
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
