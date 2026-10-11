"""The finished application scored against its domain reference.

Two halves. The deterministic one reads the Blueprint: every reference item
not declined is green when something answers it and that thing works — a
screen whose route the app check did not fail, a process the trials ran
through, a record and an integration the model carries. The reviewer's one
looks: one call per role's landing screen plus the public entry (never one
per page — a bounded `roles + 1`), with the reference's screens and
conventions for that role, asking what a practitioner would find missing
or wrong. A miss the reviewer names, when it names a reference item, flips
that item red with the reviewer's reason.

Written into `runtime.scorecard.domain` by the checks after hand-over.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from services.blueprint.scorecard import item

logger = logging.getLogger(__name__)

DOMAIN_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["score", "missing", "wrong"],
    "properties": {
        "score": {"type": "integer", "minimum": 0, "maximum": 10,
                  "description": "How far this screen is what a practitioner in the sub-domain expects: 10 is the standard product."},
        "missing": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["item", "why"],
            "properties": {"item": {"type": "string", "description": "A reference screen, record, process or convention this person would expect here and does not see, by its reference name when it has one."},
                           "why": {"type": "string"}}}},
        "wrong": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["item", "why"],
            "properties": {"item": {"type": "string"}, "why": {"type": "string"}}}},
    },
}

DOMAIN_REVIEW_SYSTEM = (
    "You are a practitioner who has used the standard products of this sub-domain for years, looking "
    "at one screen of a new one — the screen a {role} lands on after signing in. You are shown the "
    "domain reference: what products in this sub-domain are expected to have, and the conventions of "
    "the field. Judge only what this screen shows and reaches: name what such a person would expect "
    "to find from here and does not (`missing`), and what is here but not as the field does it "
    "(`wrong` — the wrong unit, status vocabulary, a step the field never asks of this role). Name "
    "reference items by their exact reference name. Do not judge colour or layout; do not invent "
    "requirements the reference does not state; an empty list is a fine answer."
)


def _norm(name: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def deterministic(doc: dict) -> tuple[list[dict], list[dict]]:
    """`(green, red)` items from the Blueprint and what the checks recorded."""
    from services.blueprint.reference_coverage import coverage
    runtime = doc.get("runtime") or {}
    failing_routes = set((runtime.get("check") or {}).get("failing") or [])
    failing_flows = {str(i.get("workflow")) for i in runtime.get("issues") or []
                     if isinstance(i, dict) and i.get("kind") == "process"}
    pages = {str(p.get("id")): p for p in doc.get("pages") or [] if isinstance(p, dict)}
    green: list[dict] = []
    red: list[dict] = []
    for it in coverage(doc):
        if it.declined is not None:
            continue
        rid = f"{it.kind}:{_norm(it.name)}"
        if it.covered_by is None:
            red.append(item(rid, it.name, f"such products have this {it.kind}; the model has nothing for it", it.name))
            continue
        if it.kind == "screen":
            route = str((pages.get(it.covered_by) or {}).get("route") or "")
            if route and route in failing_routes:
                red.append(item(rid, it.name, f"answered by {route}, which does not work yet", it.covered_by))
                continue
        if it.kind == "process" and it.covered_by in failing_flows:
            red.append(item(rid, it.name, "answered by a process that does not run through yet", it.covered_by))
            continue
        green.append(item(rid, it.name, f"answered by {it.covered_by}", it.covered_by))
    return green, red


def landings(doc: dict) -> list[dict]:
    """One visit per role's landing page, plus the public entry signed out."""
    from services.blueprint.account_model import landing_by_role
    from services.blueprint.projection import _entry_route
    pages = {str(p.get("route")): p for p in doc.get("pages") or []
             if isinstance(p, dict) and p.get("route") and str(p.get("status") or "").upper() not in ("DEPRECATED", "REMOVED")}
    out: list[dict] = []
    for role, route in landing_by_role(doc).items():
        page = pages.get(route)
        if page is not None:
            out.append({"page": str(page.get("id")), "route": route, "name": str(page.get("name") or route),
                        "entity": "", "as": role})
    entry = _entry_route(doc) or "/"
    public = pages.get(entry)
    if public is not None and str(public.get("access") or "authenticated") == "public":
        out.append({"page": str(public.get("id")), "route": entry, "name": str(public.get("name") or entry),
                    "entity": "", "as": "signed out"})
    return out


def _reference_for(doc: dict, role: str) -> dict:
    ref = doc.get("domainReference") or {}
    declined = {(str(d.get("kind")), _norm(d.get("name"))) for d in ref.get("declined") or [] if isinstance(d, dict)}
    mine = lambda rs: not rs or role == "signed out" or role in [str(r) for r in rs]  # noqa: E731
    return {"domain": ref.get("domain"), "subdomain": ref.get("subdomain"), "summary": ref.get("summary"),
            "screens": [s for s in ref.get("screens") or [] if isinstance(s, dict) and mine(s.get("forRoles"))
                        and ("screen", _norm(s.get("name"))) not in declined],
            "processes": [{"name": p.get("name"), "purpose": p.get("purpose")} for p in ref.get("processes") or []
                          if isinstance(p, dict) and mine(p.get("roles"))
                          and ("process", _norm(p.get("name"))) not in declined],
            "conventions": ref.get("conventions") or [],
            "benchmarks": ref.get("benchmarks") or []}


def review(doc: dict, app: Any, client: Any, out_dir: Path) -> tuple[list[dict], list[dict]]:
    """`(reds, untried)` from the reviewer's look at each landing."""
    from services.blueprint.app_check import _entries, visit_id
    from services.blueprint.page_review import ReviewUnavailable, run_shots
    reds: list[dict] = []
    untried: list[dict] = []
    todo = landings(doc)
    if not todo:
        return reds, untried
    try:
        shots = {str(s.get("id")): s for s in run_shots(app, _entries(app, doc, todo), out_dir, probe=False, states=False)
                 if isinstance(s, dict)}
    except ReviewUnavailable as exc:
        return reds, [item("domain:look", "The reviewer's look", f"the screens could not be pictured: {exc}"[:300], "domain")]
    # THE SAME ID AS THE BLUEPRINT HALF, so a reference item the checks already
    # found red is not counted twice when the reviewer names it as well.
    known = {_norm(it.name): (f"{it.kind}:{_norm(it.name)}", it.name) for it in _coverage(doc)}
    for v in todo:
        shot = shots.get(visit_id(v))
        file = (shot or {}).get("file")
        if not shot or not file or not Path(str(file)).exists():
            untried.append(item(f"domain:{v['as']}", f"{v['name']} as {v['as']}",
                                "the landing screen could not be pictured", v["page"]))
            continue
        user = (f"The screen: {v['name']} ({v['route']}), as {v['as']}.\n\nThe domain reference for this person:\n"
                + json.dumps(_reference_for(doc, v["as"]), indent=1, ensure_ascii=False)[:20000])
        try:
            reply = client(system=DOMAIN_REVIEW_SYSTEM.format(role=v["as"]), user=user,
                           schema=DOMAIN_REVIEW_SCHEMA, images=[str(file)])
            body = json.loads(getattr(reply, "text", reply))
        except Exception as exc:  # noqa: BLE001 — the reviewer did not answer: untried, not red
            logger.warning("[domain-score] the reviewer did not answer for %s", v["route"], exc_info=True)
            untried.append(item(f"domain:{v['as']}", f"{v['name']} as {v['as']}",
                                f"the reviewer did not answer: {str(exc)[:160]}", v["page"]))
            continue
        for kind in ("missing", "wrong"):
            for found in (body or {}).get(kind) or []:
                if not isinstance(found, dict) or not found.get("item"):
                    continue
                rid, name = known.get(_norm(found["item"]), (f"domain:{_norm(found['item'])}", str(found["item"])))
                reds.append(item(rid, name,
                                 f"{'missing' if kind == 'missing' else 'not as the field does it'} for a {v['as']} "
                                 f"on {v['route']}: {str(found.get('why') or '')[:200]}", v["page"]))
    return reds, untried


def _coverage(doc: dict):
    from services.blueprint.reference_coverage import coverage
    return coverage(doc)


def score_domain(svc: Any, output_dir: str, *, app: Any = None, client: Any = None) -> dict:
    """`{total, green, red, untried}` — the domain criterion."""
    doc = svc.doc
    if not (doc.get("domainReference") or {}).get("screens") and not (doc.get("domainReference") or {}).get("processes"):
        return {"total": 0, "green": 0, "red": [],
                "untried": [item("domain:reference", "The domain reference", "no domain reference was written for this application", "domain")]}
    green, red = deterministic(doc)
    untried: list[dict] = []
    if app is not None:
        if client is None:
            from services.blueprint.executors import DEFAULT_MODEL, AnthropicModel
            client = AnthropicModel(model=DEFAULT_MODEL, effort="low")
        looked, untried = review(doc, app, client, Path(output_dir) / ".forge" / "check" / "domain")
        named = {r["id"] for r in red}
        for r in looked:
            if r["id"] in named:
                continue
            named.add(r["id"])
            red.append(r)
            green = [g for g in green if g["id"] != r["id"]]
    return {"total": len(green) + len(red), "green": len(green), "red": red, "untried": untried}


__all__ = ["DOMAIN_REVIEW_SCHEMA", "DOMAIN_REVIEW_SYSTEM", "deterministic", "landings", "review", "score_domain"]
