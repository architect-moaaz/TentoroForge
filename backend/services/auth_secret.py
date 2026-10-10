"""Give each generated app a unique NEXTAUTH_SECRET.

The .env.local template ships a shared placeholder
(`NEXTAUTH_SECRET=dev-secret-change-me-in-production`). Because every app then signs
JWTs with the SAME secret, a session cookie minted by one app on a shared origin
(e.g. localhost:3000 across regenerations) is accepted by the next — so a stale token
carrying another app's user id leaks in, breaking owner-scoped queries and FK inserts.
Replace any placeholder/empty secret with a per-app random value.
"""
from __future__ import annotations

import re
import secrets
from pathlib import Path

_PLACEHOLDERS = {
    "", "dev-secret-change-me-in-production", "please-change-me",
    "generate-a-random-secret-here", "change-me", "changeme", "secret",
}
_KEY_RE = re.compile(r"^\s*(NEXTAUTH_SECRET|AUTH_SECRET)\s*=\s*(.*)$")


def ensure_unique_auth_secret(output_dir: str | Path) -> dict:
    p = Path(output_dir) / ".env.local"
    if not p.exists():
        return {"set": False, "reason": "no .env.local"}
    new_secret = secrets.token_hex(32)
    lines = p.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    changed = False
    have = False
    for ln in lines:
        m = _KEY_RE.match(ln)
        if m:
            have = True
            val = m.group(2).strip().strip('"').strip("'")
            if val in _PLACEHOLDERS:
                out.append(f"{m.group(1)}={new_secret}")
                changed = True
                continue
        out.append(ln)
    if not have:
        out.append(f"NEXTAUTH_SECRET={new_secret}")
        changed = True
    if changed:
        p.write_text("\n".join(out) + "\n", encoding="utf-8")
    return {"set": changed}


_SENSITIVE_RE = re.compile(r"^\s*SENSITIVE_ENCRYPTION_KEY\s*=\s*(.*)$")


def sensitive_key(output_dir: str | Path) -> str:
    """The app's sensitive-column key as `.env.local` holds it, or ""."""
    p = Path(output_dir) / ".env.local"
    if not p.exists():
        return ""
    for ln in p.read_text(encoding="utf-8").splitlines():
        m = _SENSITIVE_RE.match(ln)
        if m:
            return m.group(1).strip().strip('"').strip("'")
    return ""


def ensure_sensitive_key(output_dir: str | Path) -> dict:
    """Give the app a SENSITIVE_ENCRYPTION_KEY of its own when it has none.

    A `sensitive: true` column is encrypted at rest with this key, and the
    runtime refuses to write or read one without it. The key was written only
    when a person pasted one on /settings/integrations, so every Vendor a
    statement tried to make answered HTTP 500 "SENSITIVE_ENCRYPTION_KEY is
    not set" and 16 of 17 statements of a feature went untried (ecom v2,
    forge-v3, 2026-10-10). Generated once per app — base64 of 32 random
    bytes, the AES-256 key the runtime expects — and kept: rows encrypted
    with it must stay readable, so an existing key is never replaced."""
    import base64

    p = Path(output_dir) / ".env.local"
    if sensitive_key(output_dir):
        return {"set": False}
    key = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    out = [ln for ln in lines if not _SENSITIVE_RE.match(ln)]
    out.append(f"SENSITIVE_ENCRYPTION_KEY={key}")
    p.write_text("\n".join(out) + "\n", encoding="utf-8")
    return {"set": True}
