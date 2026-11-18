"""Builds the "Design Job Finder" Mac app (the installer runs this).

Clicking it opens Design Job Finder in its own window, starting it first if
needed. It's built on your own Mac, so
macOS doesn't show a "can't be opened" warning for it.

  python engine/mac_app.py            build ~/Applications/Design Job Finder.app
  python engine/mac_app.py --dock     ...and add it to the Dock
"""
import os
import plistlib
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from settings import ROOT

APP_NAME = "Design Job Finder"
OLD_NAMES = ["Job Finder"]  # earlier names, replaced when you update
BUNDLE_ID = "com.productdesignjobfinder.app"
ICON = ROOT / "assets" / "JobFinder.icns"


def default_app_path() -> Path:
    folder = os.environ.get("JOBSEARCH_APP_DIR") or str(Path.home() / "Applications")
    return Path(folder) / f"{APP_NAME}.app"


def launcher_script(root: Path) -> str:
    python = shlex.quote(str(root / "venv" / "bin" / "python"))
    server = shlex.quote(str(root / "engine" / "app_server.py"))
    return f"""#!/bin/bash
# Opens Design Job Finder. Made by the installer; it's rebuilt when you update.
PY={python}
if [ ! -x "$PY" ]; then
  osascript -e 'display dialog "Design Job Finder can'"'"'t find its folder. Paste the install line into Terminal again to fix it." buttons {{"OK"}} default button 1 with title "Design Job Finder"'
  exit 1
fi
exec "$PY" {server}
"""


def info_plist() -> dict:
    return {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": APP_NAME,
        "CFBundleIconFile": "JobFinder",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
    }


def build(app: Path | None = None, root: Path = ROOT) -> Path:
    app = app or default_app_path()
    if app.exists():
        shutil.rmtree(app)
    for old in OLD_NAMES:
        old_app = app.with_name(f"{old}.app")
        if (old_app / "Contents" / "Info.plist").exists():
            shutil.rmtree(old_app)
    macos = app / "Contents" / "MacOS"
    resources = app / "Contents" / "Resources"
    macos.mkdir(parents=True)
    resources.mkdir(parents=True)
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump(info_plist(), f)
    exe = macos / APP_NAME
    exe.write_text(launcher_script(root))
    exe.chmod(0o755)
    if ICON.exists():
        shutil.copy(ICON, resources / "JobFinder.icns")
    # Tell Finder and the Dock to pick up the (new) icon.
    subprocess.run(["touch", str(app)], check=False)
    return app


def in_dock(app: Path) -> bool:
    out = subprocess.run(["defaults", "read", "com.apple.dock", "persistent-apps"],
                         capture_output=True, text=True).stdout
    return f"{APP_NAME}.app" in out.replace("%20", " ")


def is_old_tile(tile: dict) -> bool:
    url = tile.get("tile-data", {}).get("file-data", {}).get("_CFURLString", "")
    url = url.replace("%20", " ").rstrip("/")
    return any(url.endswith(f"/{old}.app") for old in OLD_NAMES)


def replace_old_tile(app: Path) -> bool:
    """Points a Dock icon for the app's old name at the new app, in the same
    spot. Returns True if there was one."""
    out = subprocess.run(["defaults", "export", "com.apple.dock", "-"],
                         capture_output=True).stdout
    try:
        dock = plistlib.loads(out)
    except Exception:
        return False
    tiles = dock.get("persistent-apps", [])
    if not any(is_old_tile(t) for t in tiles):
        return False
    keep_one = not in_dock(app)
    kept = []
    for t in tiles:
        if not is_old_tile(t):
            kept.append(t)
        elif keep_one:
            data = t["tile-data"]
            data["file-data"]["_CFURLString"] = f"{app.as_uri()}/"
            data["file-label"] = APP_NAME
            data.pop("book", None)  # saved link to the old app
            kept.append(t)
            keep_one = False
    dock["persistent-apps"] = kept
    subprocess.run(["defaults", "import", "com.apple.dock", "-"],
                   input=plistlib.dumps(dock), check=False)
    subprocess.run(["killall", "Dock"], check=False)
    return True


def add_to_dock(app: Path) -> bool:
    """Adds the app to the Dock once. Returns True if it was added."""
    if replace_old_tile(app) or in_dock(app):
        return False
    tile = ("<dict><key>tile-data</key><dict><key>file-data</key><dict>"
            f"<key>_CFURLString</key><string>{app.as_uri()}/</string>"
            "<key>_CFURLStringType</key><integer>15</integer>"
            "</dict></dict></dict>")
    subprocess.run(["defaults", "write", "com.apple.dock", "persistent-apps",
                    "-array-add", tile], check=False)
    subprocess.run(["killall", "Dock"], check=False)
    return True


if __name__ == "__main__":
    built = build()
    print(f"Made {built}")
    if "--dock" in sys.argv and add_to_dock(built):
        print("Added Design Job Finder to your Dock.")
