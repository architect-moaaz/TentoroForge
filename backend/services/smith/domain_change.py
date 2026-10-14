"""The app's own addresses, from a conversation: "put it on app.acme.com",
"is my domain working?", "where do I point my DNS?", "remove the old domain",
"call our address aqua" (the free address the platform gives the app).

The same service the Publish dialog and App settings use
(`services.deploy.domains`): Smith never writes a record or a key; it says
which records to add and where the address stands."""
from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_NAME = re.compile(r"(?<![\w@.-])((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63})(?![\w-])", re.I)


def _envelope(applied: bool, *, reason: str = "", diff: str = "") -> dict:
    return {"applied": applied, "reason": reason, "diff_summary": diff, "edited_paths": []}


def name_in(text: str) -> str:
    """The first domain-looking word: "put it on App.Acme.com please" → app.acme.com."""
    for m in _NAME.finditer(str(text or "")):
        cand = m.group(1).lower()
        if not cand.endswith((".tsx", ".ts", ".json", ".md", ".png", ".jpg")):
            return cand
    return ""


def _records_said(view: dict) -> str:
    rows = view.get("records") or []
    if not rows:
        return ""
    lines = [f"{r['type']} {r['host']} → {r['value']}" for r in rows]
    return " Add " + ("this record" if len(rows) == 1 else "these records") + " where its DNS is managed: " + "; ".join(lines) + "."


def _said(view: dict) -> str:
    name, status = view.get("name"), view.get("status")
    if status == "live":
        out = f"{name} is live" + (", and it is the main address" if view.get("main") else "") + "."
        if view.get("works") is False:
            out += f" {view.get('worksDetail')}"
        return out
    if status == "failed":
        return f"{name} is not working: {view.get('detail')}" + _records_said(view)
    return f"{name} is waiting: {view.get('detail')}" + _records_said(view)


def run(output_dir: str, verb: str, *, domain: str = "", change: str = "", reasoning: Any = None) -> dict:
    from services.deploy.domains import (DomainRefused, DomainService, project_root, run_sync,
                                         vercel_project_name)
    root = project_root(output_dir)
    if not (root / ".forge" / "blueprint" / "current.json").is_file():
        return _envelope(False, reason="This application has no definition yet; build it, then give it an address.")
    name = name_in(domain) or name_in(change)
    said: list[str] = []
    client = None
    if not os.environ.get("VERCEL_TOKEN"):
        if verb in ("connect_domain", "remove_domain", "rename_app_address"):
            return _envelope(False, reason="Publishing is not set up on this platform, so I cannot attach addresses.")
    else:
        # A status question checks now, like Check now does.
        from services.deploy.vercel_client import VercelClient
        client = VercelClient()
    from services.deploy.domain_check import check_address
    svc = DomainService(output_dir=str(root), client=client, project_name=vercel_project_name(Path(root).name),
                        say=said.append, address_check=check_address)

    async def act() -> str:
        try:
            if verb == "connect_domain":
                if not name:
                    raise DomainRefused("Which address? Give it in full, for example app.your-company.com.")
                known = {e["name"] for e in svc.entries()}
                if name in known and re.search(r"\bmain\b|\bprimary\b|\bdefault\b", change or "", re.I):
                    view = await svc.make_main(name)
                    return f"{name} is the main address now; sign-in and links follow it once it is live. " + _said(view)
                view = await svc.connect(name)
                tail = (" I will say here when it is live; App settings → Domains shows its progress."
                        if view.get("status") != "live" else "")
                return _said(view) + tail
            if verb == "rename_app_address":
                label = name or str(domain or "").strip()
                if not label:
                    raise DomainRefused("What should the address be called? Give the name, for example aqua.")
                view = await svc.rename_tentoro(label)
                return (f"The app's address is {view['name']} now. " + _said(view)
                        + (" Sign-in and links follow it." if view.get("main") else ""))
            if verb == "remove_domain":
                if not name:
                    raise DomainRefused("Which address should I remove? "
                                        + ", ".join(e["name"] for e in svc.entries()) or "This app has no own address.")
                await svc.remove(name)
                return f"{name} is removed; the app no longer answers there."
            # domain_status
            names = [name] if name else [e["name"] for e in svc.entries()]
            if not names:
                return (f"This app answers at {svc.view()['vercelAddress']} only. Tell me the address you want, "
                        "for example \"put it on app.your-company.com\", and I will say which record to add.")
            parts = []
            for n in names:
                view = await svc.refresh(n) if client is not None else svc.view_of(n)
                parts.append(_said(view))
            return " ".join(parts)
        finally:
            if client is not None:
                await client.close()

    try:
        text = run_sync(act())
    except DomainRefused as exc:
        return _envelope(False, reason=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[domain-change] %s failed", verb, exc_info=True)
        return _envelope(False, reason=f"I could not reach Vercel to do that: {type(exc).__name__}: {str(exc)[:200]}")
    extra = [s for s in said if s not in text]
    return _envelope(True, diff=" ".join([text, *extra]).strip())


__all__ = ["name_in", "run"]
