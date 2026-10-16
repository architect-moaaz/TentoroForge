"""Where a published application tells an identity provider to send people back.

`NEXTAUTH_URL` is left unset on a publish (NextAuth reads Vercel's own host),
except when the Blueprint declares a sign-in through an identity provider:
then the application must know its address before its first request, and the
address must be the one registered at the provider. That is the project's
production alias, `https://<name>.vercel.app`, which exists before any
deployment does. The redirect to register is `<address>/api/auth/callback/<id>`.
"""
from __future__ import annotations

import json
from pathlib import Path


def sso_declared(output_dir: str | Path) -> bool:
    for blueprint in (Path(output_dir).parent / ".forge" / "blueprint" / "current.json",
                      Path(output_dir) / ".forge" / "blueprint" / "current.json"):
        if blueprint.is_file():
            doc = json.loads(blueprint.read_text("utf-8"))
            from services.blueprint.projection import sign_in_policy
            return bool(sign_in_policy(doc)["sso"])
    return False


def production_alias(project_name: str) -> str:
    return f"https://{project_name}.vercel.app"


def main_domain(output_dir: str | Path) -> str:
    """`https://<name>` for the app's main address when it is live, else "".

    On its own domain the app must know that address: left unset, NextAuth
    builds its callbacks from Vercel's per-deployment host, and a person who
    signs in at app.acme.com is sent somewhere else to finish."""
    for blueprint in (Path(output_dir).parent / ".forge" / "blueprint" / "current.json",
                      Path(output_dir) / ".forge" / "blueprint" / "current.json"):
        if blueprint.is_file():
            doc = json.loads(blueprint.read_text("utf-8"))
            for e in ((doc.get("deployment") or {}).get("domains") or []):
                if isinstance(e, dict) and e.get("main") and e.get("status") == "live" and e.get("name"):
                    return f"https://{e['name']}"
            return ""
    return ""


def published_address(output_dir: str | Path, project_name: str) -> str:
    """The address to pin: the live main domain; else the production alias
    when a provider needs one; else "" (NextAuth reads Vercel's own host)."""
    main = main_domain(output_dir)
    if main:
        return main
    return production_alias(project_name) if sso_declared(output_dir) else ""


def stable_address(output_dir: str | Path, project_name: str, alias: str = "") -> str:
    """THE APP'S OWN ADDRESS, the one people are given: its live main domain;
    else the production alias Vercel reports (or `<name>.vercel.app`). The
    per-deployment address Vercel also mints is frozen at that build — a
    tester kept the first publish's and saw a fault fixed in the second
    (pcn4owv7, 2026-10-15); it belongs in the history, not in the toolbar."""
    main = main_domain(output_dir)
    if main:
        return main
    alias = str(alias or "").strip()
    if alias:
        return alias if alias.startswith("http") else f"https://{alias}"
    return production_alias(project_name)


def callback_addresses(address: str, entry_ids: list[str]) -> list[str]:
    return [f"{address.rstrip('/')}/api/auth/callback/{eid}" for eid in entry_ids]


__all__ = ["callback_addresses", "main_domain", "production_alias", "published_address", "sso_declared", "stable_address"]
