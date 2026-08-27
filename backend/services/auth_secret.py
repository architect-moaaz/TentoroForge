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
