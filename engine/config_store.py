"""Reading and saving your settings. Used by the Design Job Finder app and by
the Terminal setup (setup_wizard.py), so both behave the same way.

Edits config.yaml line by line, so every comment and advanced setting
in the file is kept.
"""
import json
import re
import shutil

import yaml

from settings import CONFIG_PATH, ROOT, env, save_env

EXAMPLE_CONFIG = ROOT / "config.example.yaml"
NOTES = ROOT / "portfolio_notes.md"
NOTES_EXAMPLE = ROOT / "portfolio_notes.example.md"

IC_LEVELS = ["senior", "sr.", "sr ", "staff", "principal", "lead", "founding"]
LEAD_LEVELS = ["manager", "director", "head of", "vp"]
LEVEL_CHOICES = [
    ("Senior (Senior, Staff, Principal, Lead)", IC_LEVELS),
    ("Leadership (Manager, Director, Head of Design, VP)", LEAD_LEVELS),
    ("Both (Senior and leadership)", IC_LEVELS + LEAD_LEVELS),
    ("Any level (Everything but junior and intern roles)", []),
]
LEAD_TITLES = ["design manager", "manager, design", "head of design", "director of design",
               "director, design", "design director", "design lead", "vp of design",
               "vp, design", "vp design"]
PRODUCT_TITLES = ["product design", "ux", "ui designer", "experience designer",
                  "interaction designer"]
BRAND_TITLES = ["brand design", "visual designer", "graphic designer", "marketing designer",
                "communication designer", "identity designer", "art director",
                "creative director"]
# (label, job titles, Indeed/Adzuna searches, word drafts use for you)
FIELD_CHOICES = [
    ("Product design (UX, UI and interaction design)", PRODUCT_TITLES + LEAD_TITLES,
     ["product designer"], "product designer"),
    ("Brand design (Visual, graphic, art direction, creative direction)",
     BRAND_TITLES + LEAD_TITLES, ["brand designer"], "brand designer"),
    ("Both (Product and brand)", PRODUCT_TITLES + BRAND_TITLES + LEAD_TITLES,
     ["product designer", "brand designer"], "designer"),
]


def role_default(level: int, field: int | None) -> str:
    """How drafts describe you unless you type your own title."""
    if level == 2:
        return "design leader"
    noun = FIELD_CHOICES[(field or 1) - 1][3]
    return noun if level == 4 else f"senior {noun}"


ROLE_DEFAULTS = {role_default(level, field) for level in range(1, 5)
                 for field in range(1, len(FIELD_CHOICES) + 1)}
COMPANY_KEYS = {"greenhouse": "greenhouse_companies", "lever": "lever_companies",
                "ashby": "ashby_companies"}

# Settings the app is allowed to change. Everything else in config.yaml
# is left exactly as it is.
EDITABLE = ("title_keywords", "search_terms", "seniority_keywords", "your_role", "locations", "search_location",
            "min_salary", "tracker", *COMPANY_KEYS.values())


def parse_money(text: str) -> int | None:
    """'150k', '$150,000' and '150000' all become 150000."""
    t = str(text).lower().replace("$", "").replace(",", "").replace(" ", "")
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(k?)", t)
    if not m:
        return None
    value = float(m.group(1)) * (1000 if m.group(2) else 1)
    return int(value)


def split_list(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def set_key(text: str, key: str, value) -> str:
    """Replaces a top-level `key: ...` line (and any indented list lines
    under it) with `key: <value>`, keeping every comment and other
    setting in the file. Adds the key if it isn't there."""
    rendered = f"{key}: {json.dumps(value, ensure_ascii=False)}"
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if re.match(rf"^{re.escape(key)}\s*:", line):
            end = i + 1
            while end < len(lines) and lines[end].startswith((" ", "\t")):
                end += 1
            return "\n".join(lines[:i] + [rendered] + lines[end:]) + "\n"
    marker = "# ════ ADVANCED"
    for i, line in enumerate(lines):
        if line.startswith(marker):
            return "\n".join(lines[:i] + [rendered, ""] + lines[i:]) + "\n"
    return text.rstrip("\n") + "\n" + rendered + "\n"


def current_settings() -> dict:
    if CONFIG_PATH.exists():
        return yaml.safe_load(CONFIG_PATH.read_text()) or {}
    return yaml.safe_load(EXAMPLE_CONFIG.read_text()) or {}


def level_choice(cfg: dict) -> int:
    """Which LEVEL_CHOICES entry (1-4) matches the current settings."""
    current = cfg.get("seniority_keywords")
    for i, (_, levels) in enumerate(LEVEL_CHOICES, 1):
        if current is not None and sorted(current) == sorted(levels):
            return i
    return 3


def field_choice(cfg: dict) -> int | None:
    """Which FIELD_CHOICES entry (1-3) matches the job titles in the
    settings, or None if someone wrote their own list."""
    current = cfg.get("title_keywords")
    for i, (_, titles, _, _) in enumerate(FIELD_CHOICES, 1):
        if current is not None and sorted(current) == sorted(titles):
            return i
    return None


def save_settings(updates: dict) -> None:
    """Writes the given settings into config.yaml (creating it from the
    example the first time) and makes a starter portfolio_notes.md."""
    text = CONFIG_PATH.read_text() if CONFIG_PATH.exists() else EXAMPLE_CONFIG.read_text()
    for key, value in updates.items():
        if key not in EDITABLE:
            raise ValueError(f"{key} can't be changed here")
        text = set_key(text, key, value)
    yaml.safe_load(text)  # never write a file that can't be read back
    CONFIG_PATH.write_text(text)
    if not NOTES.exists():
        shutil.copy(NOTES_EXAMPLE, NOTES)


def read_notes() -> str:
    """Your notes, without the how-to comment at the top of the starter
    file (the app shows that advice next to the box instead)."""
    text = NOTES.read_text() if NOTES.exists() else NOTES_EXAMPLE.read_text()
    return re.sub(r"\A\s*<!--.*?-->\s*", "", text, flags=re.S)


def save_notes(text: str) -> None:
    NOTES.write_text(text)


def slug_for(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def lookup_company(name: str) -> dict:
    """Finds a company's job board. Returns
    {"name", "status": "found"|"missing"|"error", "key", "slug", "jobs"}."""
    from check_boards import resolve
    slug = slug_for(name)
    if not slug:
        return {"name": name, "status": "missing"}
    # resolve() checks Greenhouse, then Lever and Ashby, plus common
    # name variations ("acme" -> "acmehq", "acmeai"...).
    r = resolve("greenhouse", slug)
    if r["status"] in ("ok", "moved"):
        return {"name": name, "status": "found", "key": COMPANY_KEYS[r["ats"]],
                "slug": r["slug"], "jobs": r.get("jobs", 0)}
    return {"name": name, "status": "error" if r["status"] == "error" else "missing"}


def save_keys(anthropic: str = "", adzuna_id: str = "", adzuna_key: str = "") -> list[str]:
    """Saves whichever keys were given. Returns problems to show the user."""
    problems = []
    anthropic = anthropic.strip()
    if anthropic:
        if anthropic.startswith("sk-ant-"):
            save_env({"ANTHROPIC_API_KEY": anthropic})
        else:
            problems.append("That doesn't look like an Anthropic key. They start with sk-ant-.")
    adzuna_id, adzuna_key = adzuna_id.strip(), adzuna_key.strip()
    if adzuna_id and adzuna_key:
        save_env({"ADZUNA_APP_ID": adzuna_id, "ADZUNA_APP_KEY": adzuna_key})
    elif adzuna_id or adzuna_key:
        problems.append("Adzuna needs both the App ID and the App Key.")
    return problems


def connected() -> dict:
    """Which extras are set up. Never returns the keys themselves."""
    return {
        "anthropic": bool(env("ANTHROPIC_API_KEY")),
        "adzuna": bool(env("ADZUNA_APP_ID") and env("ADZUNA_APP_KEY")),
        "notion": bool(env("NOTION_TOKEN") and env("NOTION_DATABASE_ID")),
    }


def connect_notion(token: str, link: str) -> tuple[bool, str]:
    """Creates the tracker database in Notion. Returns (ok, message)."""
    from notion_client import create_database, page_id_from_link
    token, page_id = token.strip(), page_id_from_link(link or "")
    if not token or not page_id:
        return False, "Paste both the secret (step 1) and the page link (step 3)."
    try:
        db = create_database(token, page_id)
    except Exception as e:
        return False, (f"Notion didn’t accept that ({e}). Usually this means step 2 was missed: "
                       "on your Notion page, click ••• → Connections and add “Design Job Finder”.")
    save_env({"NOTION_TOKEN": token, "NOTION_DATABASE_ID": db["id"]})
    return True, db["url"]
