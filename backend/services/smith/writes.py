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
     "It cannot make records change by itself: a change to data (add, delete, "
     "approve, update) runs a workflow, so when none does what is asked, "
     "`add_workflow` first. For a page that does not exist yet, `compose_route`. "
     "`whole: true` lays the page out AGAIN FROM THE START to the brief — its "
     "structure, sections and look decided afresh, everything it does kept — "
     "for \"redesign this screen\", \"make it look like…\", \"a grid instead of "
     "the list\"; without it the page is changed by small edits inside the "
     "layout it has.",
     {"route": "string", "brief": "string", "whole": "boolean"}),
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
     "the data model (`data.entities`: rename a record, change a field's type — a "
     "FIELD's rename is `rename_field`, which moves its data; here it would drop "
     "the old field and start the new one empty), "
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

WRITES = WRITES + (
    ("rewrite_pages",
     "Lay out SEVERAL screens again from the start, at once, to one brief — "
     "\"rebuild every screen like Myntra\", \"make all the pages cards\", a new "
     "direction for the whole app. `routes`: the screens, or [\"all\"] for every "
     "screen written as code. Each keeps everything it does; all of them land "
     "as one change. Do the frame first (`write_section designSystem` for the "
     "shell and the look, `navigation` for the menu), then this, so the screens "
     "are laid out inside the new frame. Several minutes for a whole app.",
     {"routes": "array", "brief": "string"}),
)

def _frame_files_said() -> str:
    from services.smith.frame_change import FRAME_PARTS
    return "; ".join(f"`{f}` — {what}" for f, what in FRAME_PARTS.items())


WRITES = WRITES + (
    ("write_frame",
     "Change any part of the application's FRAME — what is around every screen — "
     "however small: \"centre the menu\", \"a search box in the top bar\", \"move "
     "the bell to the left\", \"a footer with our address\", \"bigger logo in the "
     "header\". `file` is the frame file the ask is about (read it first with "
     "`read_file` under `app/`): " + _frame_files_said() + ". `brief` names the change "
     "in the code's terms. Edited, compiled, committed as one version; from then on "
     "that file is the application's own. To switch the KIND of frame (side rail, "
     "top bar, bottom dock, its tone) use `write_section` on `designSystem`.",
     {"file": "string", "brief": "string"}),
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
    # A PAGE THAT WAS NEVER WRITTEN IS WRITTEN, NOT REVIEWED. F&B's tester
    # said "Incoming Orders page is not done"; its build had failed, the
    # review had nothing to open, and "no coded pages" was the whole reply.
    from services.blueprint.page_review import unbuilt_pages
    unbuilt = [p for p in unbuilt_pages(svc.doc) if only is None or str(p.get("id")) in only]
    if unbuilt and (only is not None and all(str(p.get("id")) in {str(u.get("id")) for u in unbuilt} for p in
                                             (pages[pid] for pid in only))):
        names = ", ".join(f"{p.get('name') or p.get('id')} ({p.get('route')})" for p in unbuilt)
        return _finding(f"{names} has no code yet — its page was never written (its build step failed), so "
                        "there is nothing to open. Write it with `compose_route` on that route, adding first "
                        "any workflow it needs to change its records, then verify it.")
    app_root = str(Path(output_dir) / "app")
    try:
        from services.smith.asked import with_their_words
        outcome = review_coded_pages(svc, app_root, only=only, asked=with_their_words("").strip())
    except ReviewUnavailable as exc:
        return _finding(f"The pages could not be opened in a browser here: {exc}")
    except Exception as exc:  # noqa: BLE001
        logger.exception("[smith] verify_pages failed")
        return _finding(f"The review did not finish — {type(exc).__name__}: {exc}")
    report = outcome.get("pages") or {}
    if not report:
        return _finding("No page of this application is written as code yet, so there is nothing to open in "
                        "a browser. Write the pages first (`compose_route`), then verify them.")
    rewritten = sorted(route_of.get(p, p) for p, r in report.items() if r.get("rewritten"))
    passing = sorted(route_of.get(p, p) for p, r in report.items() if r.get("passed"))
    short = {route_of.get(p, p): r for p, r in report.items() if not r.get("passed")}
    never = [p for p in unbuilt if str(p.get("id")) not in report]
    said = (f"Opened {len(report)} page(s) in a browser and pressed every control."
            + (" Never written, so not opened: " + ", ".join(f"{p.get('name')} ({p.get('route')})" for p in never)
               + " — each needs `compose_route`." if never else "")
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
    tables_before = _tables_by_entity(svc.doc)
    from services.blueprint.field_changes import field_settings, what_changed
    fields_before = {"data": {"entities": [{"name": n, "fields": [{"name": f, **v}]}
                                           for (n, f), v in field_settings(svc.doc).items()]}}
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
    # A RECORD RENAMED KEEPS ITS ROWS: the entity is the same id under a new
    # table name, and that is written down for prepare-schema to rename.
    from services.blueprint.migrations_ledger import table_renamed
    ledger: list[str] = []
    for eid, table in _tables_by_entity(svc.doc).items():
        old_table = tables_before.get(eid)
        if old_table and old_table != table and (Path(app_root) / "package.json").is_file():
            ledger = [table_renamed(app_root, old_table, table)]
    touched = _reproject(svc, app_root, section) + ledger
    after = int(svc.doc.get("version") or before)
    changed = ", ".join(sorted({str(getattr(p, "natural_key", "") or "") for p in props if getattr(p, "natural_key", "")})[:8])
    # THE DATABASE TAKES IT NOW, OR SMITH HEARS WHY. Making a dish name
    # unique also brought in a `photo` field the database did not have; the
    # schema files changed, nothing pushed, and the turn said "Changed" over a
    # preview whose every read of that record failed (2026-10-02). The record
    # types are not changed until the app's own database is too.
    # FIELD BY FIELD WHAT IT DID — the ask's change and anything else the
    # agent altered with it, so an unasked rename is seen and put back.
    fields = what_changed(fields_before, svc.doc) if section.startswith("data") else []
    field_note = (" Fields: " + "; ".join(fields[:12]) + "." if fields else "")
    if section.startswith("data") and (Path(app_root) / "package.json").is_file():
        from services.blueprint.schema_push import push_now
        pushed = push_now(app_root)
        if not pushed.get("applied") and pushed.get("lines"):
            return {"applied": True, "touched": touched, "version": after,
                    "finding": (f"The record types changed (version {after}), but the app's own database "
                                f"would not take it: {pushed.get('reason')}.{field_note} Anything in that list "
                                "the ask did not want — a field renamed or retyped along the way — put back "
                                "as it was, so the definition and the database agree; then try the screens "
                                "that use it."),
                    "said": ""}
    return {"applied": True, "finding": "", "touched": touched, "version": after,
            "said": (f"Changed {SECTION_WORDS.get(section, section)} (version {after})"
                     + (f": {changed}" if changed else "") + "." + field_note
                     + (f" Updated: {', '.join(touched[:6])}." if touched else ""))}


def _tables_by_entity(doc: dict) -> dict[str, str]:
    from services.blueprint.projection import to_snake
    return {str(e.get("id")): str(e.get("table") or to_snake(str(e.get("name") or "")))
            for e in (doc.get("data") or {}).get("entities") or []
            if isinstance(e, dict) and e.get("id") and e.get("status") != "DEPRECATED"}


def _reproject(svc: Any, app_root: str, section: str) -> list[str]:
    """What a changed section writes to disk. Each section's own projection,
    the way its change seam calls it; a section with none returns nothing."""
    try:
        if section.startswith("data"):
            from services.smith.entity_change import _project_data
            return _project_data(svc, app_root)
        if section == "designSystem":
            # HOW IT LOOKS IS MORE THAN ITS COLOURS: the shell (chrome, tone,
            # sign-in layout) is the design system's too, and only the tokens
            # were written — a new chrome stayed in the document.
            from services.blueprint.projection import (project_design_tokens, project_navigation,
                                                       project_shell_identity)
            from services.smith.sync_app import refresh_frame
            files = list(project_design_tokens(svc.doc, app_root).get("files") or [])
            files += list(project_navigation(svc.doc, app_root).get("files") or [])
            files += list(project_shell_identity(svc.doc, app_root).get("files") or [])
            files += refresh_frame(app_root, svc.doc)
            return files
        if section in ("pages", "navigation", "modules"):
            from services.blueprint.projection import apply_frontend_projection
            return list((apply_frontend_projection(svc, app_root) or {}).get("files") or [])
    except Exception as exc:  # noqa: BLE001 — the Blueprint changed; the projection is reported, not fatal
        logger.warning("[smith] re-projection after %s failed: %s", section, exc)
        return []
    return []


def rewrite_pages(output_dir: str, routes: list[str], brief: str, *, reasoning: Any = None) -> dict:
    """Several coded pages laid out again at once (`compose.relayout_pages`)."""
    from services.blueprint.service import BlueprintService
    from services.smith.compose import code_row, relayout_pages

    brief = (brief or "").strip()
    if not brief:
        return _finding("`rewrite_pages` needs `brief`: what the screens should become.")
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return _finding("This project has no Blueprint, so there are no screens to lay out.")
    wanted = [str(r).strip() for r in routes or [] if str(r).strip()]
    if not wanted or any(r.lower() in ("all", "*", "every") for r in wanted):
        wanted = [str(p.get("route")) for p in svc.doc.get("pages") or []
                  if isinstance(p, dict) and p.get("status") != "DEPRECATED"
                  and code_row(svc.doc, str(p.get("id"))) is not None]
    if not wanted:
        return _finding("No screen of this application is written as code, so none can be laid out "
                        "again this way; `compose_route` changes a laid-out screen.")
    try:
        out = relayout_pages(svc, wanted, app_root=str(Path(output_dir) / "app"), request=brief,
                             reasoning=reasoning)
    except Exception as exc:  # noqa: BLE001 — a tool degrades, it does not crash
        logger.exception("[smith] rewrite_pages failed")
        return _finding(f"The screens were not laid out again — {type(exc).__name__}: {exc}")
    done, failed = out.get("done") or [], out.get("failed") or {}
    said = (f"Laid out {len(done)} screen(s) again (version {out.get('version')}): "
            + ", ".join(f"`{r}`" for r in done) + "." if done else "")
    finding = ("; ".join(f"{r} was not laid out again: {why}" for r, why in sorted(failed.items()))
               if failed else "")
    if not done:
        return _finding(finding or "No screen was laid out again.")
    return {"applied": True, "said": said, "finding": finding, "touched": list(out.get("committed") or []),
            "version": out.get("version")}


def write_page_code(output_dir: str, route: str, brief: str, *,
                    reasoning: Any = None, whole: bool = False) -> dict:
    """Rewrite one page's code to `brief`. Returns
    `{applied, said, finding, touched, version}` — `finding` set when an
    oracle refused, in its words; `said` for the person either way."""
    from services.blueprint.service import BlueprintService
    from services.smith.compose import (ComposeError, NeedsWorkflowError, _page_for_route, code_row,
                                        coded_app, recode_page)

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
        out = recode_page(svc, route, app_root=app_root, request=brief, reasoning=reasoning, whole=whole)
    except NeedsWorkflowError as exc:
        # WORKFLOW FIRST: the page said what it needs; the next step adds it.
        return _finding(str(exc))
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
    # WHAT CHANGED, NOT ONLY THAT SOMETHING DID. "Rewrote /register
    # (version 27)" was the whole report of a rewrite that took the Delete
    # button away (Test 5); the writer's own account of the change is said.
    what = str(out.get("rationale") or "").strip()
    said = f"Rewrote **{route}** (version {version})" + (f": {what}" if what else ".")
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


WRITES = WRITES + (
    ("set_field",
     "Change one field's own rules and NOTHING else: `unique` (true: the "
     "database refuses a second record with the same value) and `required` "
     "(true: a record is never saved without it). `entity` and `field` by name. "
     "The way to keep \"names must be unique\", \"a phone is always given\" — "
     "a business rule only states it. Pushed to the app's database at once; if "
     "the records already there break it, nothing is changed and you are told "
     "which records, to settle with the person.",
     {"entity": "string", "field": "string", "unique": "boolean", "required": "boolean"}),
)


WRITE_NAMES = frozenset(name for name, _d, _a in WRITES)


def _flag(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    return str(value).strip().lower() in ("true", "1", "yes")


def set_field(output_dir: str, entity: str, field: str, *, unique: Any = None,
              required: Any = None) -> dict:
    """One field's `unique` / `required`, set in the definition, projected
    and pushed — or, when the app's own records break it, put back and said.

    Asked to make dish names unique, `write_section` briefed the data agent,
    which returned the whole record type: `image` renamed to `photo`, ids
    turned to strings, `isAvailable` dropped — every run differently
    (2026-10-02). A rule on one field is a setting, not a re-authoring."""
    import copy

    from services.blueprint.service import BlueprintService
    from services.smith.entity_change import _project_data
    from services.smith.section_change import find_named, names

    want = {k: v for k, v in (("unique", _flag(unique)), ("required", _flag(required))) if v is not None}
    if not want:
        return _finding("`set_field` needs `unique` or `required` (true or false).")
    try:
        svc = BlueprintService.load(output_dir=output_dir)
    except FileNotFoundError:
        return _finding("This project has no Blueprint, so there is no field to change.")
    entities = [e for e in (svc.doc.get("data") or {}).get("entities") or [] if isinstance(e, dict)]
    import re as _re
    canon = lambda t: _re.sub(r"[^a-z0-9]", "", str(t or "").lower())   # noqa: E731
    ent = find_named(entities, entity, id_prefix="ENTITY-") or next(
        (e for e in entities if canon(entity) in {canon(e.get("name")), canon(e.get("table")), canon(e.get("id"))}),
        None)
    if ent is None:
        return _finding(f"No record type called {entity!r}. The app has: {names(entities)}.")
    fields = [f for f in ent.get("fields") or [] if isinstance(f, dict)]
    fld = next((f for f in fields if str(f.get("name") or "").lower() == str(field or "").strip().lower()), None)
    if fld is None:
        return _finding(f"{ent.get('name')} has no field {field!r}. It has: "
                        + ", ".join(str(f.get("name")) for f in fields) + ".")
    if all(bool(fld.get(k)) == v for k, v in want.items()):
        return {"applied": True, "finding": "", "touched": [], "said":
                f"{ent.get('name')}.{fld.get('name')} is already " + " and ".join(
                    ("unique" if k == "unique" else "required") if v else f"not {k}" for k, v in want.items()) + "."}
    before = copy.deepcopy(svc.doc)
    for k, v in want.items():
        if v:
            fld[k] = True
        else:
            fld.pop(k, None)
    words = "; ".join(f"{ent.get('name')}.{fld.get('name')} is {'now' if v else 'no longer'} {k}"
                      for k, v in want.items())
    svc.commit(user_request=f"set {ent.get('name')}.{fld.get('name')}: {want}", smith_interpretation=words,
               before=before, affected=[str(ent.get("id"))])
    app_root = str(Path(output_dir) / "app")
    touched = _project_data(svc, app_root) if (Path(app_root) / "package.json").is_file() else []
    if (Path(app_root) / "package.json").is_file():
        from services.blueprint.schema_push import push_now
        pushed = push_now(app_root)
        if not pushed.get("applied") and pushed.get("lines"):
            # PUT BACK: a definition the app's own database will not take
            # leaves every read of that record failing.
            svc.doc = before
            svc.save()
            _project_data(svc, app_root)
            push_now(app_root)
            named = "; ".join(l.strip(" -") for l in pushed["lines"] if l.strip().startswith("-")) or pushed["reason"]
            return _finding(f"Not changed: the records already in the app break it — {named}. They are the "
                            "person's: say which, and ask whether to change those records or keep the rule as it was.")
    return {"applied": True, "finding": "", "touched": touched, "version": int(svc.doc.get("version") or 0),
            "said": f"{words} — the database keeps it from now on."}


def run(name: str, args: dict, *, output_dir: str, reasoning: Any = None) -> dict:
    """Carry out one write. The result's `finding` is the observation when an
    oracle refused; `said` is what the person is told."""
    args = {k: v for k, v in (args or {}).items() if v not in (None, "")}
    if name in ("write_page_code", "rewrite_pages", "write_frame") and args.get("brief"):
        from services.smith.asked import with_their_words
        args["brief"] = with_their_words(str(args["brief"]))
    if name == "write_page_code":
        whole = str(args.get("whole") or "").strip().lower() in ("true", "1", "yes")
        return write_page_code(output_dir, str(args.get("route") or ""),
                               str(args.get("brief") or ""), reasoning=reasoning, whole=whole)
    if name == "write_frame":
        from services.smith.frame_change import run as frame_run
        return frame_run(output_dir, str(args.get("file") or ""), str(args.get("brief") or ""),
                         reasoning=reasoning)
    if name == "rewrite_pages":
        routes = args.get("routes")
        return rewrite_pages(output_dir, list(routes) if isinstance(routes, list) else
                             ([str(routes)] if routes else []), str(args.get("brief") or ""),
                             reasoning=reasoning)
    if name == "verify_pages":
        routes = args.get("routes")
        return verify_pages(output_dir, list(routes) if isinstance(routes, list) else [], reasoning=reasoning)
    if name == "set_field":
        return set_field(output_dir, str(args.get("entity") or ""), str(args.get("field") or ""),
                         unique=args.get("unique"), required=args.get("required"))
    if name == "write_section":
        return write_section(output_dir, str(args.get("section") or ""), str(args.get("brief") or ""),
                             subject=str(args.get("subject") or ""), reasoning=reasoning)
    raise KeyError(name)


__all__ = ["WRITES", "WRITE_NAMES", "SECTION_NODE", "SECTION_WORDS", "run", "rewrite_pages", "set_field",
           "verify_pages", "write_page_code", "write_section"]
