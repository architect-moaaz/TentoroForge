"""The app's own addresses, from a conversation: "put it on app.acme.com",
"is my domain working?", "where do I point my DNS?", "remove the old domain",
"call our address aqua" (the free address the platform gives the app),
"add the DNS records for me" (at the DNS account the organisation connected),
"give each organisation its own address under clinicapp.com".

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


async def _return_to(output_dir: str, root: Path, name: str) -> str:
    """Where the owner lands after approving at their provider (App settings →
    Domains of this app), or "" when the platform's address is not known."""
    from urllib.parse import quote
    base = (os.environ.get("FORGE_APP_BASE_URL") or os.environ.get("FORGE_PUBLIC_URL") or "").rstrip("/")
    if not base:
        return ""
    from sqlalchemy import select

    from models.project import Project
    from services.figma.integrations import _session_on_this_loop
    places = list(dict.fromkeys([str(output_dir).rstrip("/"), str(root), str(Path(root) / "app")]))
    async with _session_on_this_loop() as db:
        project = (await db.execute(select(Project).where(Project.output_dir.in_(places)))).scalars().first()
    if project is None:
        return ""
    return f"{base}/org/{project.org_id}/projects/{project.id}?settings=domains&dc={quote(name, safe='')}"


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
        if verb in ("connect_domain", "remove_domain", "rename_app_address", "add_dns_records",
                    "give_organisations_addresses"):
            return _envelope(False, reason="Publishing is not set up on this platform, so I cannot attach addresses.")
    else:
        # A status question checks now, like Check now does.
        from services.deploy.vercel_client import VercelClient
        client = VercelClient()
    from services.deploy.domain_check import check_address
    svc = DomainService(output_dir=str(root), client=client, project_name=vercel_project_name(Path(root).name),
                        say=said.append, address_check=check_address)

    async def act() -> str:
        if client is not None and verb in ("add_dns_records", "remove_domain"):
            from services.deploy.dns_accounts import load_for_output_dir
            for where in dict.fromkeys([str(output_dir).rstrip("/"), str(root), str(Path(root) / "app")]):
                try:
                    svc.dns = await load_for_output_dir(where)
                except Exception:  # noqa: BLE001 — no store: the owner adds the records
                    logger.info("[domain-change] DNS accounts unavailable for %s", where, exc_info=True)
                if svc.dns:
                    break
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
            if verb == "give_organisations_addresses":
                said_mode = ""
                if re.search(r"\b(separate|own|per[- ]organi[sz]ation)\b[^.]*\bsign[- ]?in|\bsign[- ]?in\b[^.]*\b(separate|per[- ]organi[sz]ation|each)\b",
                             change or "", re.I):
                    await svc.set_organisation_sign_in("per_organisation")
                    said_mode = " Each organisation's address has its own sign-in."
                elif re.search(r"\b(shared|one|single)\b[^.]*\bsign[- ]?in\b", change or "", re.I):
                    await svc.set_organisation_sign_in("shared")
                    said_mode = " One sign-in works across them all."
                if not name:
                    if said_mode:
                        return said_mode.strip()
                    raise DomainRefused("Under which domain? For example clinicapp.com, so an organisation answers at acme.clinicapp.com.")
                view = await svc.connect_organisations(name)
                base = view["name"][2:]
                return (f"Each organisation will answer at its own address under {base}, such as <name>.{base}; "
                        "its admin sees and changes it on the Organisation page. " + _said(view) + said_mode)
            if verb == "add_dns_records":
                targets = [name] if name else [e["name"] for e in svc.entries()
                                               if e.get("kind") != "tentoro" and not e.get("redirectTo")
                                               and e.get("status") != "live"]
                if not targets:
                    raise DomainRefused("Which address? Give it in full, for example app.your-company.com.")
                replace = bool(re.search(r"\b(replace|overwrite)\b", change or "", re.I))
                if not svc.dns:
                    # NO ACCOUNT CONNECTED: approve at the provider in one click, where it offers that.
                    said_links = []
                    for t in targets:
                        view = await svc.refresh(t)
                        back = await _return_to(output_dir, root, t) if view.get("connect") else ""
                        if back:
                            link = await svc.connect_url(t, back)
                            said_links.append(f"Approve {t}'s records at {link['provider']}: {link['url']} "
                                              "— sign in there, approve, and I will say here when it is live.")
                    if said_links:
                        return " ".join(said_links)
                return " ".join([(await svc.write_records(t, replace=replace))["message"] for t in targets])
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
            from services.deploy.dns_accounts import close_all
            await close_all(svc.dns)

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
