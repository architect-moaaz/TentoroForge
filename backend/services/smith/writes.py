"""Smith writes code — through the build's own seam (§0 of `2026-09-24-smith-as-a-loop`).

`write_page_code` is the first write primitive: the loop, having READ a page
(`read_page_code`, `grep`), says precisely what its code should do differently,
and the UI engineer that wrote the page in the first place rewrites it. It is
not a verb. Verbs are the vocabulary of the first interpretation call — the
classifier's — and this is the loop's: it exists so that a change no verb
describes ("accepted rentals should count as needing attention", "put the
filters above the list") is still a change Smith makes, rather than one of
`limits.py`'s honest refusals.

THE SAME SEAM AS THE BUILD, WHICH IS WHAT MAKES IT ALLOWED. §5 of the spec
refuses "a free-form file-edit tool", and this is not one: nothing here opens
`view.tsx`. `compose.recode_page` briefs `ui_engineer`, whose code goes to
`tsc` against the typed SDK for `COMPILE_ROUNDS`, and what compiles becomes a
`pageCode` row through `apply_agent_result` and one commit — exactly the path
a page takes during a build. The Blueprint stays the record; `view.tsx` is
projected from it afterwards, as always.

WHAT THE COMPILER SAYS IS A FINDING. A page that does not compile after three
rounds used to end the turn as `needs_user` with the error in a chat bubble.
It is a proof — the one oracle the build trusts most — and so it is handed
back as `finding`, and the loop, which can now read the error and the code,
gets to try again with a better brief. The same for a contract refusal and
for a widget the new code does not draw.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: (name, description, {argument: type}). Written for the model choosing it.
WRITES: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("write_page_code",
     "Rewrite the React of a page that EXISTS, by route, to do what `brief` "
     "says. Use it after reading the page: the brief names the concrete "
     "change — the constant, the component, the query, the layout order — in "
     "terms of the code you read, not the user's sentence. The page is "
     "rewritten by the engineer that wrote it, type-checked against the SDK, "
     "and committed as one version. The compiler's verdict comes back to you. "
     "For a page that does not exist yet, `compose_route`.",
     {"route": "string", "brief": "string"}),
)

#: Which node re-decides a section when the loop asks for it changed. The
#: same nodes the change seams use (`entity_change`, `rule_change`,
#: `access_change`, `restyle`, `definition_change`); a test holds each to
#: `DAG` and to the agent's declared `writes`. Dotted names reach the data
#: model's parts; `data.entities` goes to the fields author, which is the
#: one that knows a field's type and what a migration costs.
SECTION_NODE: dict[str, str] = {
    "data.entities": "entity_fields",
    "data.relationships": "data_model",
    "data.constraints": "data_model",
    "apis": "apis",
    "integrations": "integrations",
    "businessRules": "business_rules",
    "permissions": "security",
    "roles": "security",
    "security": "security",
    "workflows": "workflow_steps",
    "designSystem": "design_system",
    "navigation": "ux_architecture",
    "modules": "ux_architecture",
    "pages": "page_contracts",
    "requirements": "requirements",
    "product": "requirements",
    "widgets": "analytics",
}

#: What each section is called to the person. The key is for the tool call;
#: "Changed **data.entities**" is a sentence nobody outside the platform can
#: read.
SECTION_WORDS: dict[str, str] = {
    "data.entities": "the kinds of record it keeps",
    "data.relationships": "how its records relate",
    "data.constraints": "the constraints on its records",
    "apis": "its endpoints",
    "integrations": "the outside services it talks to",
    "businessRules": "its rules",
    "permissions": "who may do what",
    "roles": "its roles",
    "security": "its security model",
    "workflows": "its processes",
    "designSystem": "how it looks",
    "navigation": "its menu",
    "modules": "how it is organised",
    "pages": "its screens",
    "requirements": "what it has to do",
    "product": "what it is",
    "widgets": "its charts and counts",
}

WRITES = WRITES + (
    ("write_section",
     "Change one section of the Blueprint by briefing the agent that owns it — "
     "the data model (`data.entities`: rename a record, change a field's type), "
     "`apis`, `businessRules`, `permissions`, `workflows`, `designSystem`, "
     "`navigation`, `pages`, `requirements`, `product`. `brief` says what "
     "should be different and what must stay, in terms of what you read "
     "(`read_section`). `subject` narrows it to one artifact's id. The reply "
     "is held to the contract and committed as one version; what changed on "
     "disk is re-projected. A refusal comes back to you with its reason. For a "
     "page's React use `write_page_code`; for one new field, `add_field`.",
     {"section": "string", "brief": "string", "subject": "string"}),
)

WRITES = WRITES + (
    ("verify_pages",
     "Open the application's coded pages in a browser — with data, with none, "
     "on a missing record — press every control, judge each page, and have the "
     "ones below the bar rewritten by their author and compiled. `routes` "
     "narrows it (a list); empty means every coded page. Slow: a minute or two "
     "per page. The verdict per page comes back to you; a page still below the "
     "bar is a finding you can act on with `write_page_code`.",
     {"routes": "array"}),
)

WRITE_NAMES: frozenset[str] = frozenset(name for name, _d, _a in WRITES)


def verify_pages(output_dir: str, routes: list[str] | None = None, *, reasoning: Any = None) -> dict:
    """Verify & fix, as the loop's own move: `orchestrator.review_coded_pages`."""
    from services.blueprint.orchestrator import review_coded_pages
    from services.blueprint.page_review import ReviewUnavailable
    from services.blueprint.service import BlueprintService

    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return _finding("This project has no Blueprint, so there are no pages to verify.")
    pages = {str(p.get("id")): p for p in svc.doc.get("pages") or [] if isinstance(p, dict)}
    route_of = {pid: str(p.get("route") or pid) for pid, p in pages.items()}
    wanted = [str(r).strip() for r in (routes or []) if str(r).strip()]
    only = {pid for pid, r in route_of.items() if r in set(wanted)} if wanted else None
    if wanted and not only:
        return _finding(f"None of {', '.join(wanted)} is a page here. Routes: "
                        + ", ".join(sorted(route_of.values()))[:500] + ".")
    app_root = str(Path(output_dir) / "app")
    try:
        outcome = review_coded_pages(svc, app_root, only=only)
    except ReviewUnavailable as exc:
        return _finding(f"The pages could not be opened in a browser here: {exc}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("[smith] verify_pages failed")
        return _finding(f"The review did not finish — {type(exc).__name__}: {exc}")
    report = outcome.get("pages") or {}
    if not report:
        return {"applied": True, "said": str(outcome.get("skipped") or "No coded pages to verify."),
                "finding": "", "touched": [], "version": 0}
    rewritten = sorted(route_of.get(p, p) for p, r in report.items() if r.get("rewritten"))
    passing = sorted(route_of.get(p, p) for p, r in report.items() if r.get("passed"))
    short = {route_of.get(p, p): r for p, r in report.items() if not r.get("passed")}
    said = (f"Opened {len(report)} page(s) in a browser and pressed every control."
            + (f" Rewrote: {', '.join(rewritten)}." if rewritten else "")
            + (f" Passing: {', '.join(passing)}." if passing else ""))
    finding = ""
    if short:
        lines = []
        for route, r in sorted(short.items()):
            v = r.get("review") or {}
            why = (v.get("broken") or [None])[0] or next(
                (f"{i.get('where')}: {i.get('problem')}" for i in v.get("issues") or []), "")
            score = (r.get("scores") or [None])[-1]
            lines.append(f"{route} ({score}/10){': ' + str(why)[:200] if why else ''}")
        finding = "Still below the bar after the review: " + "; ".join(lines)
    return {"applied": True, "said": said, "finding": finding, "touched": [], "version": 0}


def write_section(output_dir: str, section: str, brief: str, *, subject: str = "",
                  reasoning: Any = None) -> dict:
    """Re-decide `section` against `brief` through the node that owns it.

    `section_change.rerun` is the seam every change verb already uses: brief
    the owning agent, hold its reply to the contract, commit, say what was
    refused. This is that seam with the section and the brief chosen by the
    loop instead of by a verb — which is what lets a change no verb describes
    ("rename the Nurse record to Colleague everywhere") still be made."""
    from services.blueprint.service import BlueprintService
    from services.smith.section_change import SectionChangeError, record_requirement, rerun

    section, brief, subject = (section or "").strip(), (brief or "").strip(), (subject or "").strip()
    if not section or not brief:
        return _finding("`write_section` needs both `section` and `brief`.")
    node = SECTION_NODE.get(section)
    if node is None:
        return _finding(f"`{section}` is not a section this can change. Sections: "
                        + ", ".join(sorted(SECTION_NODE)) + ".")
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return _finding("This project has no Blueprint, so there is no section to change.")
    app_root = str(Path(output_dir) / "app")
    before = int(svc.doc.get("version") or 0)
    try:
        req = record_requirement(svc, brief, owner=section.split(".")[0])
        framed = ("THIS IS A CHANGE to an application that is already built, not a first authoring. "
                  f"Change ONLY what this asks and keep everything else exactly as it is: \"{brief}\". "
                  f"It satisfies {req.get('id')}. Return the artifacts of `{section}` that change, "
                  "keyed as they are now, and nothing that does not.")
        props, _ = rerun(svc, node, brief=framed, request=brief, subject=subject,
                         interpretation=f"change {section}: {brief}", reasoning=reasoning,
                         app_root=app_root, say=f"Re-deciding {section} for: {brief}.")
    except SectionChangeError as exc:
        return _finding(f"{section} was not changed: {exc}")
    except Exception as exc:  # noqa: BLE001 — a tool degrades, it does not crash
        logger.exception("[smith] write_section %s failed", section)
        return _finding(f"{section} was not changed — {type(exc).__name__}: {exc}")
    touched = _reproject(svc, app_root, section)
    after = int(svc.doc.get("version") or before)
    changed = ", ".join(sorted({str(getattr(p, "natural_key", "") or "") for p in props if getattr(p, "natural_key", "")})[:8])
    return {"applied": True, "finding": "", "touched": touched, "version": after,
            "said": (f"Changed {SECTION_WORDS.get(section, section)} (version {after})"
                     + (f": {changed}" if changed else "") + "."
                     + (f" Updated: {', '.join(touched[:6])}." if touched else ""))}


def _reproject(svc: Any, app_root: str, section: str) -> list[str]:
    """What a changed section writes to disk. Each section's own projection,
    the way its change seam calls it; a section with none returns nothing."""
    try:
        if section.startswith("data"):
            from services.smith.entity_change import _project_data
            return _project_data(svc, app_root)
        if section == "designSystem":
            from services.blueprint.projection import project_design_tokens
            return list(project_design_tokens(svc.doc, app_root).get("files") or [])
        if section in ("pages", "navigation", "modules"):
            from services.blueprint.projection import apply_frontend_projection
            return list((apply_frontend_projection(svc, app_root) or {}).get("files") or [])
    except Exception as exc:  # noqa: BLE001 — the Blueprint changed; the projection is reported, not fatal
        logger.warning("[smith] re-projection after %s failed: %s", section, exc)
        return []
    return []


def write_page_code(output_dir: str, route: str, brief: str, *,
                    reasoning: Any = None) -> dict:
    """Rewrite one page's code to `brief`. Returns
    `{applied, said, finding, touched, version}` — `finding` set when an
    oracle refused, in its words; `said` for the person either way."""
    from services.blueprint.service import BlueprintService
    from services.smith.compose import ComposeError, _page_for_route, code_row, coded_app, recode_page

    route = (route or "").strip()
    brief = (brief or "").strip()
    if not route or not brief:
        return _finding(f"`write_page_code` needs both `route` and `brief`; got route={route!r}.")
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return _finding("This project has no Blueprint, so there is no page to rewrite.")
    page = _page_for_route(svc.doc, route)
    if page is None:
        routes = ", ".join(str(p.get("route")) for p in svc.doc.get("pages") or []
                           if isinstance(p, dict))[:500]
        return _finding(f"There is no page at `{route}`. Routes: {routes}. "
                        "A page that does not exist is created with `compose_route`.")
    if code_row(svc.doc, str(page.get("id"))) is None and not coded_app(svc.doc):
        return _finding(f"`{route}` is not written as code — it renders from its layout "
                        "tree, which `compose_route` and `add_widgets` change.")
    app_root = str(Path(output_dir) / "app")
    try:
        out = recode_page(svc, route, app_root=app_root, request=brief, reasoning=reasoning)
    except ComposeError as exc:
        # The compiler's (or the contract's) own words, unparaphrased.
        return _finding(f"{route} was not changed: {exc}")
    except Exception as exc:  # noqa: BLE001 — a tool degrades, it does not crash
        logger.exception("[smith] write_page_code %s failed", route)
        return _finding(f"{route} was not changed — {type(exc).__name__}: {exc}")
    if not out.get("applied"):
        return _finding(f"{route} was not changed: {out.get('reason') or 'the change was refused'}")
    missing = [str(m) for m in out.get("missing") or []]
    version = int(out.get("version") or 0)
    said = f"Rewrote **{route}** (version {version})."
    if missing:
        return {"applied": True, "said": said, "touched": list(out.get("committed") or []),
                "version": version,
                "finding": (f"{route} was rewritten (version {version}), but the new code does "
                            f"not draw: {', '.join(missing)}. The brief asked for it; the code "
                            "does not show it.")}
    return {"applied": True, "said": said, "finding": "",
            "touched": list(out.get("committed") or []), "version": version}


def _finding(text: str) -> dict:
    return {"applied": False, "said": text, "finding": text, "touched": [], "version": 0}


def run(name: str, args: dict, *, output_dir: str, reasoning: Any = None) -> dict:
    """Carry out one write. The result's `finding` is the observation when an
    oracle refused; `said` is what the person is told."""
    args = {k: v for k, v in (args or {}).items() if v not in (None, "")}
    if name == "write_page_code":
        return write_page_code(output_dir, str(args.get("route") or ""),
                               str(args.get("brief") or ""), reasoning=reasoning)
    if name == "verify_pages":
        routes = args.get("routes")
        return verify_pages(output_dir, list(routes) if isinstance(routes, list) else [], reasoning=reasoning)
    if name == "write_section":
        return write_section(output_dir, str(args.get("section") or ""), str(args.get("brief") or ""),
                             subject=str(args.get("subject") or ""), reasoning=reasoning)
    raise KeyError(name)


__all__ = ["WRITES", "WRITE_NAMES", "SECTION_NODE", "SECTION_WORDS", "run", "verify_pages", "write_page_code", "write_section"]
