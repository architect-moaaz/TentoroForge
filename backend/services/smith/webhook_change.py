"""Let an outside system call the application.

"Let Shopify tell the app when an order is paid": the integration gets an
`inbound` block — the events it sends, how its call is verified, the NAME of
its signing secret — and the reply says the address to give the other end,
the header it signs with and the name to set on the platform. The process
that starts on the event is a workflow with a `webhook` trigger, added by
`add_workflow` once the integration calls in.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from services.llm_client import tell

logger = logging.getLogger(__name__)

_EVENT = re.compile(r"\b[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+\b")


def _envelope(applied: bool, *, reason: str = "", diff: str = "", paths: list[str] | None = None,
              options: list[str] | None = None, **more: Any) -> dict:
    return {"applied": applied, "reason": reason, "diff_summary": diff,
            "edited_paths": list(paths or []), "options": list(options or []), **more}


def _live(doc: dict) -> list[dict]:
    return [i for i in doc.get("integrations") or []
            if isinstance(i, dict) and str(i.get("status") or "").upper() not in ("DEPRECATED", "REMOVED")]


def find_integration(doc: dict, ref: str) -> dict | None:
    want = (ref or "").strip().lower()
    if not want:
        return None
    rows = _live(doc)
    for row in rows:
        if want in (str(row.get("id") or "").lower(), str(row.get("name") or "").lower()):
            return row
    hits = [row for row in rows if want in str(row.get("name") or "").lower()
            or str(row.get("provider") or "").lower() == want]
    return hits[0] if len(hits) == 1 else None


def events_in(text: str) -> list[str]:
    """`order.paid`, `payment.succeeded` as written in the ask."""
    return list(dict.fromkeys(m.group(0) for m in _EVENT.finditer(text or "")))


def how_to_call(row: dict) -> str:
    from services.blueprint.projection import integration_slug
    inbound = row.get("inbound") or {}
    slug = integration_slug(row)
    ref = str(inbound.get("signingSecretRef") or "")
    verify = str(inbound.get("verify") or "hmac_sha256")
    how = {"hmac_sha256": f"sign each call with `X-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256 of \"<t>.<body>\">` using {ref}",
           "bearer": f"send `Authorization: Bearer <{ref}>`",
           "provider": f"its own signature, checked by the {row.get('provider')} adapter with {ref}"}[verify]
    events = ", ".join(str(e) for e in inbound.get("events") or []) or "any event"
    return (f"{row.get('name')} calls the application at `/api/webhooks/{slug}` (POST, JSON) and must {how}. "
            f"Set {ref} under Settings → Integrations to the secret you give the other end. "
            f"Events it may send: {events}; each starts the processes whose trigger names it.")


def add_webhook(svc: Any, output_dir: str, *, integration: str, change: str = "", reasoning: Any = None) -> dict:
    row = find_integration(svc.doc, integration)
    if row is None:
        names = ", ".join(str(i.get("name")) for i in _live(svc.doc)) or "(none yet)"
        return _envelope(False, reason=f"I cannot tell which system {integration!r} is. The systems this application "
                                       f"talks to are: {names}. Connect or declare it first (`connect_service`), then ask again.")
    events = events_in(change)
    inbound = dict(row.get("inbound") or {})
    if inbound.get("signingSecretRef") and not [e for e in events if e not in (inbound.get("events") or [])]:
        return _envelope(True, diff=how_to_call(row), integration=str(row.get("id") or ""))
    from services.blueprint.projection import integration_slug
    ref = str(inbound.get("signingSecretRef") or "") or f"{integration_slug(row).replace('-', '_').upper()}_WEBHOOK_SECRET"
    refs = [str(r) for r in row.get("secretRefs") or []]
    before = svc.snapshot()
    if ref not in refs:
        refs.append(ref)
    row["secretRefs"] = refs
    row["inbound"] = {"events": list(dict.fromkeys([*(inbound.get("events") or []), *events])) or ["received"],
                      "verify": str(inbound.get("verify") or "hmac_sha256"), "signingSecretRef": ref}
    svc.commit(user_request=change or f"let {row.get('name')} call the application",
               smith_interpretation=f"{row.get('name')} calls in; verified with {ref}", before=before,
               affected=[str(row.get("id") or "")])
    paths: list[str] = []
    app_root = Path(output_dir) / "app"
    if app_root.is_dir():
        from services.blueprint.projection import project_integrations
        paths = list(project_integrations(svc.doc, app_root).get("files") or [])
    tell(reasoning, f"{row.get('name')} may now call the application.", "step")
    return _envelope(True, diff=how_to_call(row), paths=paths, integration=str(row.get("id") or ""))


def run(output_dir: str, *, integration: str, change: str = "", reasoning: Any = None) -> dict:
    from services.blueprint.service import BlueprintService
    try:
        svc = BlueprintService.load(output_dir=output_dir)
    except FileNotFoundError:
        return _envelope(False, reason="this project has no Blueprint yet.")
    try:
        return add_webhook(svc, output_dir, integration=integration, change=change, reasoning=reasoning)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[webhook-change] failed", exc_info=True)
        return _envelope(False, reason=f"{type(exc).__name__}: {str(exc)[:300]}")


__all__ = ["add_webhook", "events_in", "find_integration", "how_to_call", "run"]
