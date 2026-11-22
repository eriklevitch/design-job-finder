"""Opens your tracker: the spreadsheet, or Notion in your browser.
The Design Job Finder app's "Open spreadsheet" button runs this."""
import subprocess
import sys
import webbrowser

from settings import SANDBOX, env, load_config, load_env, resolve_path


def open_file(path) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    elif sys.platform.startswith("win"):
        import os
        os.startfile(str(path))  # noqa: only exists on Windows
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def open_tracker() -> tuple[bool, str]:
    """Opens the tracker. Returns (opened, message)."""
    load_env()
    config = load_config()
    if (config.get("tracker") or "spreadsheet").lower() == "notion" and not SANDBOX:
        db = env((config.get("notion") or {}).get("database_id_env", "NOTION_DATABASE_ID"))
        if db:
            webbrowser.open(f"https://www.notion.so/{db.replace('-', '')}")
            return True, "Opened your Notion tracker in the browser."
        print("Notion isn't set up yet, so opening the spreadsheet instead.")
    path = resolve_path(config.get("spreadsheet_path", "applications.csv"))
    if not path.exists():
        return False, "No jobs saved yet. Click “Find new jobs” first."
    open_file(path)
    return True, f"Opened {path.name}."


def main() -> int:
    opened, message = open_tracker()
    print(message)
    return 0 if opened else 1


if __name__ == "__main__":
    sys.exit(main())
