"""What went wrong on the platform, as a record the cockpit shows.

A turn the host killed, a build a restart stopped, a fault the fix loop
found to be the platform's and not the app's: each was visible within
seconds in a ledger, a kernel log or a scorecard, and nobody read any of
them for eleven hours (pcn4owv7, 2026-10-15). One file, one line per
incident, newest shown first in the cockpit's Overview.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

FILE = "incidents.jsonl"
KEEP = 2000


def _path() -> Path:
    from services.project_paths import OUTPUT_ROOT
    return Path(OUTPUT_ROOT) / "_platform" / FILE


#: How far back a fault is looked for in other applications.
RECURRING_LOOKBACK = 1000


def signature(kind: str, where: str, reason: str) -> str:
    """The same fault, whichever application it hit: the step, and the error's
    name when the reason starts with one (`InconsistentPageAccess: …`) or else
    the reason with the application's own words — routes, ids, quoted names,
    numbers — taken out. Built only from the record's own fields; nothing here
    decides what a fault is about."""
    reason = str(reason or "").strip()
    head = reason.split(":", 1)[0].strip()
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{2,60}", head) and ":" in reason:
        core = head
    else:
        core = re.sub(r"`[^`]*`|'[^']*'|\"[^\"]*\"|/\S*|\b[A-Z]+-\d+\b|\d+", " ", reason)
        core = " ".join(core.lower().split())[:120]
    return f"{kind}|{where}|{core}"


def record(kind: str, app: str, detail: str, **extra: Any) -> dict[str, Any]:
    """One incident on the record. Never raises: the record is a bonus to
    the work that noticed, not a condition of it.

    A record carrying a `signature` is compared with what came before: the
    same fault in ANOTHER application is almost certainly the platform's, and
    the row says so (`recurring`, `apps`). The Refund And Chargeback build died
    on a refusal three applications had met before it (2026-10-20), and the
    first anyone heard of it was from a person whose build would not finish."""
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "kind": str(kind), "app": str(app or ""),
           "detail": str(detail or "")[:600], **{k: v for k, v in extra.items() if v not in (None, "")}}
    sig = row.get("signature")
    if sig:
        apps = {str(r.get("app")) for r in recent(RECURRING_LOOKBACK)
                if r.get("signature") == sig and r.get("app")}
        if apps - {row["app"]}:
            row["recurring"] = True
            row["apps"] = sorted(apps | {row["app"]})
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return row


def recent(limit: int = 100) -> list[dict[str, Any]]:
    """The newest incidents first."""
    try:
        lines = _path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for line in reversed(lines[-KEEP:]):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
        if len(out) >= limit:
            break
    return out
