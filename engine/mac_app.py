"""Builds the "Job Finder" Mac app (the installer runs this).

Clicking it opens Job Finder in its own window, starting it first if
needed. It's built on your own Mac, so
macOS doesn't show a "can't be opened" warning for it.

  python engine/mac_app.py            build ~/Applications/Job Finder.app
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

APP_NAME = "Job Finder"
BUNDLE_ID = "com.productdesignjobfinder.app"
ICON = ROOT / "assets" / "JobFinder.icns"


def default_app_path() -> Path:
    folder = os.environ.get("JOBSEARCH_APP_DIR") or str(Path.home() / "Applications")
    return Path(folder) / f"{APP_NAME}.app"


def launcher_script(root: Path) -> str:
    python = shlex.quote(str(root / "venv" / "bin" / "python"))
    server = shlex.quote(str(root / "engine" / "app_server.py"))
    return f"""#!/bin/bash
# Opens Job Finder. Made by the installer; it's rebuilt when you update.
PY={python}
if [ ! -x "$PY" ]; then
  osascript -e 'display dialog "Job Finder can'"'"'t find its folder. Paste the install line into Terminal again to fix it." buttons {{"OK"}} default button 1 with title "Job Finder"'
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


def add_to_dock(app: Path) -> bool:
    """Adds the app to the Dock once. Returns True if it was added."""
    if in_dock(app):
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
        print("Added Job Finder to your Dock.")
