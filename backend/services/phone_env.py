"""The environment the phone project's own processes run in: Metro, Expo, npm and its package scripts.

PR #28 review (2026-10-22): these processes ran in the platform's environment (`{**os.environ}`), so `DATABASE_URL`, `SECRET_KEY` and
the model keys reached code the project controls: a package's install script, an `app.config.js` (its `extra` is served from the
live preview's manifest without a sign-in) and Expo's `+api` routes. `preview.app_env` already keeps those out of an app's own
processes; since 2026-11-01 it gives them only what a toolchain needs, so this is the same environment.
"""
from __future__ import annotations

from pathlib import Path


def phone_env(output_dir: str | Path, **extra: str) -> dict[str, str]:
    """`preview.app_env` for the project, plus `extra`."""
    from preview import app_env

    return app_env(str(output_dir), **extra)
