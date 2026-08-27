"""Follow-up actions the chat offers after a build finishes, plus the app's admin
login. Drives the post-generation UX:

  build complete  → offer [Seed demo data] · [Test, Validate & Repair]
  after seeding   → show admin credentials, then offer [Test, Validate & Repair] · [Do something else]

Admin credentials are deterministic (the seed template creates admin@example.com /
admin1234 unless SEED_ADMIN_* is set in the app's .env), so the chat can show them
the moment seeding runs.
"""
from __future__ import annotations

import re
from pathlib import Path

_SEED = {
    "id": "seed",
    "label": "Seed demo data",
    "message": "[SEED_DATA]",
    "description": "Populate the database and get an admin login to test the app.",
    "icon": "zap",
}
_VALIDATE = {
    "id": "validate_repair",
    "label": "Test, Validate & Repair",
    "message": "[VALIDATE_REPAIR]",
    "description": "Boot the app, click through every page + button, and auto-repair what's broken.",
    "variant": "primary",
    "icon": "check",
}
_ELSE = {
    "id": "something_else",
    "label": "Do something else",
    "message": "I'd like to do something else.",
    "description": "Change the design, add a page, or ask for anything.",
}


def post_build_actions() -> list[dict]:
    """Chips offered as soon as the app build completes."""
    return [_SEED, _VALIDATE]


def post_seed_actions() -> list[dict]:
    """Chips offered after the user seeds the data."""
    return [_VALIDATE, _ELSE]


_ENV_RE = {
    "email": re.compile(r"^\s*SEED_ADMIN_EMAIL\s*=\s*(.+?)\s*$", re.M),
    "password": re.compile(r"^\s*SEED_ADMIN_PASSWORD\s*=\s*(.+?)\s*$", re.M),
}


def admin_credentials(output_dir: str | Path | None = None) -> dict:
    """The admin login the seed creates. Defaults match the seed template; an
    app's `.env`/`.env.local` SEED_ADMIN_* override wins."""
    creds = {"email": "admin@example.com", "password": "admin1234"}
    if output_dir:
        base = Path(output_dir)
        for fn in (".env", ".env.local"):
            f = base / fn
            if not f.exists():
                continue
            try:
                text = f.read_text()
            except OSError:
                continue
            for key, rx in _ENV_RE.items():
                m = rx.search(text)
                if m:
                    creds[key] = m.group(1).strip().strip('"').strip("'")
    return creds
