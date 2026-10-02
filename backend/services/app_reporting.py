"""Where a generated app reports its own failures, so Smith hears of them.

An app's error reporter (`src/lib/error_reporter.ts`) posts crashes and
failed steps to `FORGE_URL/api/projects/FORGE_PROJECT_ID/runtime-exceptions`,
the inbox Smith reads before it answers "something is broken". On forge-v3
no app had either setting, so the reporter stayed silent, the inbox stayed
empty, and Smith told an F&B tester "Nothing has been reported as crashing"
about a form that had never worked (2026-10-01).

Two addresses, because two places run an app:
- inside the platform's container (the preview, a Verify & fix review) the
  backend is `http://127.0.0.1:6500`, or `FORGE_URL` when the platform says;
- a published app reaches the platform's public address, `FORGE_PUBLIC_URL`
  (`https://forge-v3.tentoro.ai`, whose `/api/*` routes to the backend).
`FORGE_PROJECT_ID` is the project's UUID — the endpoint's own key.
"""

from __future__ import annotations

import os
from pathlib import Path

PUBLIC_ENV = "FORGE_PUBLIC_URL"


def internal_url() -> str:
    return (os.environ.get("FORGE_URL") or os.environ.get("FORGE_BACKEND_URL")
            or "http://127.0.0.1:6500").strip().rstrip("/")


def public_url() -> str:
    return os.environ.get(PUBLIC_ENV, "").strip().rstrip("/")


def _set(path: Path, values: dict[str, str]) -> None:
    lines = path.read_text("utf-8").splitlines() if path.exists() else []
    out, done = [], set()
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in values:
            if key not in done:
                out.append(f"{key}={values[key]}")
                done.add(key)
            continue
        out.append(line)
    out += [f"{k}={v}" for k, v in values.items() if k not in done]
    path.write_text("\n".join(out) + "\n", "utf-8")


def wire(app_root: str | Path, project_id: object) -> bool:
    """Point the app's reporter at this platform, by the project's UUID.
    Written into `.env.local` (what the app reads first). False when there is
    no app or no project id to name."""
    root = Path(app_root)
    if not project_id or not (root / "package.json").is_file():
        return False
    _set(root / ".env.local", {"FORGE_URL": internal_url(), "FORGE_PROJECT_ID": str(project_id)})
    return True


def publish_env(project_id: object) -> dict[str, str]:
    """The reporter's settings for a published app — only when the platform
    has a public address a deployed app can reach."""
    base = public_url()
    return {"FORGE_URL": base, "FORGE_PROJECT_ID": str(project_id)} if base and project_id else {}


__all__ = ["PUBLIC_ENV", "internal_url", "public_url", "wire", "publish_env"]
