"""The application scored against the definition of success — `runtime.scorecard`.

The owner's bar for a built application: every page built, every route
answering as declared, role-based access holding, the logic right, the
product what its domain expects, and Smith able to close what is left. A
build used to end with "built" the moment the tree compiled, and the checks
that could say more ran inside the build turn, so the person saw "Building…"
for an hour and a half after the app booted (ECom L2, 2026-10-11).

Now the app is handed over the moment it boots, with this card: six
criteria, each `{total, green, red, untried}`. `red` is what the check tried
and found wrong — the fix loop (`fix_to_green`) works through those. `untried`
is what the check could not try: its own browser timed out, the app could not
be started for it. That is the check's failure, never the application's; it
is said as such and never sent to repair (the app check once sent ten pages
to Smith for its own screenshot timeout).

Items are `{id, label, why, cause}`; `cause` is what a repair is addressed to
— a page id, a workflow or rule id, an entity — so reds from different
criteria with one cause are fixed in one turn.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable

logger = logging.getLogger(__name__)

CRITERIA: tuple[str, ...] = ("pages", "routes", "access", "logic", "systems", "audit", "domain", "smith")

LABELS: dict[str, str] = {
    "pages": "Pages built and working",
    "routes": "Routes answer as declared",
    "access": "Each role sees only its own",
    "logic": "Processes and rules",
    "systems": "Runs on time and talks to the outside",
    "audit": "Every change is on the record",
    "domain": "What such products have",
    "smith": "Fixed after hand-over",
}

STATUSES = ("checking", "fixing", "done", "stopped")


def item(id_: str, label: str, why: str, cause: str = "") -> dict:
    return {"id": str(id_), "label": str(label), "why": str(why)[:400], "cause": str(cause or id_)}


def _criterion(total: int = 0, green: int = 0, red: Iterable[dict] = (), untried: Iterable[dict] = ()) -> dict:
    return {"total": int(total), "green": int(green), "red": list(red), "untried": list(untried)}


def empty(doc: dict) -> dict:
    """A card with every criterion untried — the totals the definition
    already knows (pages planned, processes to run); the rest filled by the
    check that measures it."""
    from services.blueprint.process_trials import manual_workflows
    runtime = doc.get("runtime") or {}
    planned = ((runtime.get("pages") or {}).get("planned"))
    if planned is None:
        planned = len([p for p in doc.get("pages") or []
                       if isinstance(p, dict) and str(p.get("status") or "").upper() != "REMOVED"])
    try:
        flows = len(manual_workflows(doc))
    except Exception:  # noqa: BLE001 — a definition without workflows
        flows = 0
    card = {"version": int(doc.get("version") or 0), "at": _now(), "status": "checking",
            "criteria": {c: _criterion() for c in CRITERIA}}
    card["criteria"]["pages"]["total"] = int(planned)
    card["criteria"]["logic"]["total"] = int(flows)
    try:
        from services.blueprint.clock_check import clocked
        from services.blueprint.payment_check import paying
        from services.blueprint.pwa_check import pushing
        card["criteria"]["systems"]["total"] = len(clocked(doc)) + len(paying(doc)) + (1 if pushing(doc) else 0)
    except Exception:  # noqa: BLE001
        pass
    for c in CRITERIA:
        card["criteria"][c]["untried"] = [item(c, LABELS[c], "not checked yet", c)]
    # NO TRAIL DECLARED, NOTHING TO PROVE: the row reads 0 of 0, not "not yet".
    audit = ((doc.get("security") or {}).get("audit") or {}) if isinstance(doc.get("security"), dict) else {}
    if str(audit.get("level") or "none") == "none":
        card["criteria"]["audit"] = _criterion()
    return card


def seed_from_boot(svc: Any) -> dict:
    """The card the hand-over message shows: pages from the build's own
    funnel (a route not served is red before anything is opened), everything
    else not checked yet. Saved on the document."""
    doc = svc.doc
    card = empty(doc)
    funnel = (doc.get("runtime") or {}).get("pages") or {}
    missing = [str(r) for r in funnel.get("missing") or []]
    by_route = {str(p.get("route")): p for p in doc.get("pages") or [] if isinstance(p, dict)}
    reds = [item(str((by_route.get(r) or {}).get("id") or r), str((by_route.get(r) or {}).get("name") or r),
                 "not served — the build could not finish it", str((by_route.get(r) or {}).get("id") or r))
            for r in missing]
    total = int(card["criteria"]["pages"]["total"])
    card["criteria"]["pages"] = _criterion(total, max(total - len(reds), 0), reds,
                                           [item("pages", LABELS["pages"], "not opened yet", "pages")]
                                           if total - len(reds) > 0 else [])
    _save(svc, card)
    return card


def restore(svc: Any, card: dict) -> dict:
    """Put a card back on a document that was reloaded from disk after
    another writer saved an older one."""
    _save(svc, card)
    return card


def read(doc: dict) -> dict | None:
    card = (doc.get("runtime") or {}).get("scorecard")
    return card if isinstance(card, dict) else None


def write(svc: Any, criterion: str, *, green: int | Iterable[Any], red: Iterable[dict] = (),
          untried: Iterable[dict] = (), total: int | None = None) -> dict:
    """Replace one criterion with what a check measured. `green` is a count
    or the green items themselves; `total` defaults to green + red + untried."""
    if criterion not in CRITERIA:
        raise ValueError(f"no such criterion: {criterion}")
    card = read(svc.doc) or empty(svc.doc)
    reds, tried_not = list(red), list(untried)
    g = green if isinstance(green, int) else len(list(green))
    t = total if total is not None else g + len(reds) + len(tried_not)
    card.setdefault("criteria", {})[criterion] = _criterion(t, g, reds, tried_not)
    card["at"] = _now()
    card["version"] = int(svc.doc.get("version") or 0)
    _save(svc, card)
    return card


def set_status(svc: Any, status: str, *, fix: dict | None = None) -> dict:
    if status not in STATUSES:
        raise ValueError(f"no such status: {status}")
    card = read(svc.doc) or empty(svc.doc)
    card["status"] = status
    if fix is not None:
        card["fix"] = {"turns": int(fix.get("turns") or 0), "yield": [int(y) for y in fix.get("yield") or []],
                       "stopped": fix.get("stopped")}
    card["at"] = _now()
    _save(svc, card)
    return card


def reds(doc: dict) -> list[dict]:
    """Every red across the criteria, each tagged with its criterion. What
    was untried is not here: nothing is repaired for a check's own failure."""
    card = read(doc)
    if not card:
        return []
    out: list[dict] = []
    for c in CRITERIA:
        for r in (card.get("criteria") or {}).get(c, {}).get("red") or []:
            if isinstance(r, dict):
                out.append({**r, "criterion": c})
    return out


def summary(doc: dict) -> dict:
    """Counts only, for the run registry and the panel's strip."""
    card = read(doc)
    if not card:
        return {}
    return {c: {"total": int(v.get("total") or 0), "green": int(v.get("green") or 0),
                "red": len(v.get("red") or []), "untried": len(v.get("untried") or [])}
            for c, v in (card.get("criteria") or {}).items() if isinstance(v, dict)}


def opening(doc: dict) -> str:
    """The card as the hand-over message shows it."""
    card = read(doc)
    if not card:
        return ""
    rows = []
    for c in CRITERIA:
        v = (card.get("criteria") or {}).get(c) or {}
        total, green = int(v.get("total") or 0), int(v.get("green") or 0)
        red, untried = len(v.get("red") or []), len(v.get("untried") or [])
        proven = f"{green} of {total}" if total else ("—" if not green else str(green))
        not_yet = str(red) if red else "—"
        could_not = ("not checked yet" if untried and all(
            "not checked" in str(u.get("why") or "") or "not opened" in str(u.get("why") or "")
            for u in v.get("untried") or []) else (str(untried) if untried else "—"))
        rows.append(f"| {LABELS[c]} | {proven} | {not_yet} | {could_not} |")
    return ("\n\n**Scorecard** — what is proven so far:\n\n"
            "| Criterion | Proven | Not yet | Could not try |\n|---|---|---|---|\n" + "\n".join(rows))


def green_line(criterion: str, it: dict, what: str = "") -> str:
    """One line per red that turned green, in the conversation:
    "Checkout: fixed — Proceed to checkout now opens the checkout"."""
    label = str(it.get("label") or it.get("id") or criterion)
    said = what or f"{str(it.get('why') or '').strip()} — no longer"
    return f"{label}: fixed — {said}".rstrip()


def closing(doc: dict) -> str:
    """The line the checks end with: what holds, what does not, what could
    not be tried."""
    card = read(doc)
    if not card:
        return ""
    parts, left, untried = [], [], 0
    platform: list[str] = []
    for c in CRITERIA:
        v = (card.get("criteria") or {}).get(c) or {}
        total, green = int(v.get("total") or 0), int(v.get("green") or 0)
        if total:
            parts.append(f"{LABELS[c].lower()} {green} of {total}")
        if c != "smith":                      # its reds are the others', said once
            left += [str(r.get("label") or r.get("id")) for r in v.get("red") or []
                     if isinstance(r, dict) and not r.get("platform")]
            platform += [f"{r.get('label') or r.get('id')} ({r.get('platform')})" for r in v.get("red") or []
                         if isinstance(r, dict) and r.get("platform")]
        untried += len([u for u in v.get("untried") or []
                        if isinstance(u, dict) and "not checked" not in str(u.get("why") or "")])
    said = "Checks finished: " + ("; ".join(parts) if parts else "nothing to check") + "."
    if left:
        said += f" Still not right ({len(left)}): {', '.join(left[:8])}{' and more' if len(left) > 8 else ''}. Tell me to carry on, or what to fix first."
    if platform:
        seen = list(dict.fromkeys(platform))
        said += (f" Not the app's to fix ({len(seen)}): {', '.join(seen[:6])}{' and more' if len(seen) > 6 else ''} — "
                 "the fault is in the platform's engine; recorded for the platform team.")
    if untried:
        said += f" {untried} I could not try — my own check failed, not the app; I'll try again on the next build."
    return said


def mark_platform(svc: Any, cause: str, where: str) -> None:
    """Every red with this `cause` is the platform's to fix, not the app's:
    `where` names the engine file. The fix loop leaves it alone from here."""
    card = read(svc.doc)
    if not card:
        return
    for c in CRITERIA:
        for r in ((card.get("criteria") or {}).get(c) or {}).get("red") or []:
            if isinstance(r, dict) and str(r.get("cause") or r.get("id")) == str(cause):
                r["platform"] = str(where)
    _save(svc, card)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _save(svc: Any, card: dict) -> None:
    runtime = dict(svc.doc.get("runtime") or {})
    runtime["scorecard"] = card
    svc.doc["runtime"] = runtime
    try:
        svc.save()
    except Exception:  # noqa: BLE001 — the card never fails a build
        logger.warning("[scorecard] could not save", exc_info=True)


__all__ = ["CRITERIA", "LABELS", "closing", "empty", "green_line", "item", "opening", "read", "reds",
           "restore", "seed_from_boot", "set_status", "summary", "write"]
