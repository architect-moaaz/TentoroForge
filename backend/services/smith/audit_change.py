"""The trail is Smith's to show, export, verify and set.

"Who changed the invoices on Tuesday", "export the audit trail", "is the
record intact", "keep the trail for seven years": the first three read the
running copy's `forge_audit`; the last is the security agent re-deciding
`security.audit` (through `access_change`, which already re-runs it).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

VERBS = ("show_audit", "export_audit", "verify_audit", "edit_audit")


def _envelope(applied: bool, *, reason: str = "", diff: str = "", paths: list[str] | None = None,
              options: list[str] | None = None, **more: Any) -> dict:
    return {"applied": applied, "reason": reason, "diff_summary": diff,
            "edited_paths": list(paths or []), "options": list(options or []), **more}


def _level(doc: dict) -> str:
    from services.blueprint.projection import audit_policy
    return audit_policy(doc)["level"]


def _q(s: Any) -> str:
    return str(s).replace("'", "''")


def _where(ask: str) -> str:
    """A few words into a WHERE: an action, a record type, a day."""
    text = (ask or "").lower()
    conds = ["true"]
    for action in ("create", "update", "delete", "export", "login", "read_sensitive"):
        if action in text or (action == "create" and "added" in text) or (action == "update" and "changed" in text) \
                or (action == "delete" and ("removed" in text or "deleted" in text)):
            conds.append(f"action = '{action}'")
            break
    m = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if m:
        conds.append(f"at::date = '{m.group(1)}'")
    elif "today" in text:
        conds.append("at::date = current_date")
    elif "yesterday" in text:
        conds.append("at::date = current_date - 1")
    return " and ".join(conds)


def show_audit(svc: Any, output_dir: str, *, change: str = "", reasoning: Any = None, **_: Any) -> dict:
    if _level(svc.doc) == "none":
        return _envelope(False, reason="This application keeps no audit trail. Say \"keep every change on the record\" and I will set one.",
                         options=["Keep every change on the record", "Keep a regulated audit trail"])
    from services.blueprint.page_review import _query
    from services.smith import trials
    bench = trials.Bench(output_dir)
    try:
        try:
            app = bench.app()
        except trials.TrialUnavailable as exc:
            return _envelope(False, reason=f"I could not start a copy of the app to read the trail: {exc}")
        where = _where(change)
        entities = [str(e.get("name")) for e in (svc.doc.get("data") or {}).get("entities") or [] if isinstance(e, dict)]
        named = next((e for e in entities if e.lower() in (change or "").lower()), None)
        if named:
            where += f" and lower(entity) = '{_q(named.lower())}'"
        rows = _query(app, f"select to_char(at, 'YYYY-MM-DD HH24:MI'), coalesce(actor_role, actor_kind), action, entity, "
                           f"coalesce(entity_id, ''), coalesce(array_to_string(changed, ', '), ''), coalesce(reason, '') "
                           f"from forge_audit where {where} order by seq desc limit 12")
        total = _query(app, f"select count(*) from forge_audit where {where}")
    finally:
        try:
            bench.close()
        except Exception:  # noqa: BLE001
            pass
    n = int(total[0][0]) if total and total[0] and str(total[0][0]).isdigit() else 0
    if not rows:
        return _envelope(True, diff="Nothing on the record for that." if change else "Nothing on the record yet.")
    lines = [f"{r[0]} — {r[1]} {r[2]} {r[3]}" + (f" {r[4][:8]}" if len(r) > 4 and r[4] else "")
             + (f" ({r[5]})" if len(r) > 5 and r[5] else "") + (f" — {r[6]}" if len(r) > 6 and r[6] else "") for r in rows if r]
    return _envelope(True, diff=f"{n} on the record" + (" for that" if change else "") + ". The latest:\n" + "\n".join(lines))


def export_audit(svc: Any, output_dir: str, *, reasoning: Any = None, **_: Any) -> dict:
    if _level(svc.doc) == "none":
        return _envelope(False, reason="This application keeps no audit trail, so there is nothing to export.")
    from services.blueprint.page_review import _query
    from services.smith import trials
    bench = trials.Bench(output_dir)
    try:
        try:
            app = bench.app()
        except trials.TrialUnavailable as exc:
            return _envelope(False, reason=f"I could not start a copy of the app to export the trail: {exc}")
        cols = ["seq", "at", "actor_id", "actor_role", "actor_kind", "via", "action", "entity", "entity_id", "before", "after",
                "changed", "reason", "prev_hash", "hash"]
        rows = _query(app, f"select {', '.join(cols)} from forge_audit order by seq asc")
    finally:
        try:
            bench.close()
        except Exception:  # noqa: BLE001
            pass
    out_dir = Path(output_dir) / ".forge" / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone
    path = out_dir / f"audit-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.csv"
    import csv
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for r in rows:
            w.writerow(r)
    return _envelope(True, diff=f"Exported {len(rows)} entries of the audit trail to {path.name}.", paths=[str(path)], file=str(path))


def verify_audit(svc: Any, output_dir: str, *, reasoning: Any = None, **_: Any) -> dict:
    if _level(svc.doc) == "none":
        return _envelope(False, reason="This application keeps no audit trail, so there is no chain to verify.")
    from services.blueprint.audit_check import _http
    from services.smith import trials
    from services.smith.trials import _session
    bench = trials.Bench(output_dir)
    try:
        try:
            app = bench.app()
        except trials.TrialUnavailable as exc:
            return _envelope(False, reason=f"I could not start a copy of the app to verify the trail: {exc}")
        reviewers = __import__("services.blueprint.projection", fromlist=["audit_policy"]).audit_policy(svc.doc)["reviewers"]
        role = reviewers[0] if reviewers else ""
        _who, jar = _session(app, svc.doc, role)
        status, _l, text = _http(app, "GET", "/api/audit/verify", None, jar)
    finally:
        try:
            bench.close()
        except Exception:  # noqa: BLE001
            pass
    try:
        body = json.loads(text)
    except ValueError:
        body = {}
    if status != 200:
        return _envelope(False, reason=f"the trail could not be verified ({status}): {text[:160]}")
    if body.get("ok"):
        return _envelope(True, diff=f"The audit trail is intact: {body.get('checked', 0)} entries, each chained to the one before.")
    return _envelope(True, diff=f"The audit trail is BROKEN at entry {body.get('brokenAt')}: a row was changed or removed outside "
                                "the application. Treat everything after it as unverified.")


def edit_audit(svc: Any, output_dir: str, *, change: str = "", reasoning: Any = None, **_: Any) -> dict:
    from services.smith.access_change import run as access
    return access(output_dir, f"Audit policy (`security.audit`): {change}", reasoning=reasoning)


def run(output_dir: str, verb: str, *, change: str = "", reasoning: Any = None) -> dict:
    from services.blueprint.service import BlueprintService
    if verb not in VERBS:
        return _envelope(False, reason=f"not an audit verb: {verb}")
    try:
        svc = BlueprintService.load(output_dir=output_dir)
    except FileNotFoundError:
        return _envelope(False, reason="this project has no Blueprint yet.")
    fn = {"show_audit": show_audit, "export_audit": export_audit, "verify_audit": verify_audit, "edit_audit": edit_audit}[verb]
    try:
        return fn(svc, output_dir, change=change, reasoning=reasoning)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[audit-change] %s failed", verb, exc_info=True)
        return _envelope(False, reason=f"{type(exc).__name__}: {str(exc)[:300]}")


__all__ = ["VERBS", "run", "show_audit", "export_audit", "verify_audit", "edit_audit"]
