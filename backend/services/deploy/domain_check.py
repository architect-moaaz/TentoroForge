"""Whether a live address really works for the people who use it.

Answering with a certificate is not enough: an app on its own domain must
also build its sign-in on that domain, or a person who signs in at
app.acme.com is sent to Vercel's own host to finish (sign-in that "does not
stick"). NextAuth's provider list says where it sends people back; it must be
the address itself. The result goes on the app's scorecard under routes, as
"Answers at <address>", so it is seen where every other check is.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

Fetch = Callable[[str], Awaitable[tuple[int, Any]]]


async def _fetch(url: str) -> tuple[int, Any]:
    import httpx
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as c:
        r = await c.get(url)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text


async def check_address(name: str, fetch: Fetch = _fetch) -> tuple[bool, str]:
    """`(works, why not)` for a live address."""
    try:
        status, _ = await fetch(f"https://{name}/")
    except Exception as exc:  # noqa: BLE001 — not answering is the finding
        return False, f"https://{name}/ does not answer: {type(exc).__name__}."
    if status >= 500:
        return False, f"https://{name}/ answers {status}."
    try:
        status, body = await fetch(f"https://{name}/api/auth/providers")
    except Exception:  # noqa: BLE001
        return True, ""          # no sign-in to check
    if status != 200 or not isinstance(body, dict) or not body:
        return True, ""          # an app without sign-in
    urls = [str(v.get("callbackUrl") or v.get("signinUrl") or "") for v in body.values() if isinstance(v, dict)]
    wrong = [u for u in urls if u and not u.startswith(f"https://{name}/")]
    if wrong:
        host = wrong[0].split("/")[2] if "//" in wrong[0] else wrong[0]
        return False, (f"Sign-in at {name} still finishes at {host}: people would be sent away to sign in. "
                       "A redeploy with the new address may still be finishing; Check now again in a minute.")
    return True, ""


def record_on_card(output_dir: str | Path, name: str, works: bool, why: str, before: str | None) -> str | None:
    """Put the result on the scorecard's routes, replacing what this address
    put there last (`before`: "green", "red" or None, kept in the domains
    ledger). Returns what it put now, or None before the app has a card."""
    from services.blueprint import scorecard as sc
    from services.blueprint.service import BlueprintService
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return before
    card = sc.read(svc.doc)
    if not card:
        return before
    rid = f"domain:{name}"
    routes = dict((card.get("criteria") or {}).get("routes") or {"total": 0, "green": 0, "red": [], "untried": []})
    red = [r for r in routes.get("red") or [] if isinstance(r, dict) and r.get("id") != rid]
    green, total = int(routes.get("green") or 0), int(routes.get("total") or 0)
    if before is None:
        total += 1
    if before == "green":
        green -= 1
    if works:
        green += 1
    else:
        red.append(sc.item(rid, f"Answers at {name}", why, "deployment"))
    routes.update({"green": max(green, 0), "total": total, "red": red})
    routes.setdefault("untried", [])
    card.setdefault("criteria", {})["routes"] = routes
    sc._save(svc, card)
    return "green" if works else "red"


__all__ = ["check_address", "record_on_card"]
