"""The design system is a Blueprint section; a theme change is a change to it.

"Change the theme colour from blue to green" was answered twice with "I
looked for 'Soft Care — white and muted lavender-blue…' in /nurse-registration
and could not find it". Smith had the palette in view — `designSystem.colors`
and the decision that chose it are in every slice — and no move that touches
either, so the ask was squeezed into a rename of a decision's wording.

A restyle is Blueprint-first like every other change: the user's words become
the binding decision on the design system, superseding the palette decision
made in discovery; the `design_system` agent — the same one the build runs —
is re-run against a brief that says what changed and what must stay; the
result is committed through `apply_change`, held to the same schema as the
build's; and the tokens are re-projected. No page is re-composed: every
component reads the colour roles as CSS tokens, so the app changes colour
without a single layout changing.
"""
from __future__ import annotations

import copy
import json
import logging
import re
from pathlib import Path
from typing import Any

from services.llm_client import tell

logger = logging.getLogger(__name__)

NODE = "design_system"
MAX_ATTEMPTS = 2

#: The colour roles a restyle is about. Listed so the reply can say what
#: moved rather than dumping thirteen hex values on the user.
_LEAD_ROLES = ("primary", "primary-hover", "primary-subtle", "accent", "background", "surface")


class RestyleError(Exception):
    """The restyle could not be made, with the reason a user can act on."""


#: The small model that reads which colour roles a request names, on its own:
#: the acting agent naming its own scope was no guard (see `smith4.turn.asked_for`).
ROLES_MODEL = "claude-haiku-4-5-20251001"
#: What `roles_named` answers when the request is about the palette as a whole.
ALL_ROLES = "ALL"


def roles_named(change: str, roles: list[str]) -> list[str] | None:
    """The colour roles the person's words name, from the palette's own role
    names; `[ALL_ROLES]` for the whole palette ("a green theme", "make it
    warmer"); None when it cannot be told — the restyle then runs unscoped,
    as before, and says so. "Change the background colour to white" was
    answered with a new accent, a new primary, a new surface and fourteen
    more roles (Mark 8, cxz95dd1, 2026-10-16): the agent re-derived a scheme
    when one role was asked for."""
    words = " ".join(str(change or "").split())[:800]
    if not words or not roles:
        return None
    try:
        from services.llm_client import complete
        reply = complete(model=ROLES_MODEL, max_tokens=120, temperature=0, content=(
            f"A person asked for a colour change in their application:\n\"{words}\"\n\n"
            f"The application's colour roles are: {', '.join(roles)}.\n\n"
            "Answer with a JSON array of the role names the request names — only those, spelled exactly as "
            "listed. The theme, the brand colour or the main colour is \"primary\". The page or the backdrop "
            "is \"background\". A request about the palette or the look as a whole, or a mood with no role "
            "named (\"warmer\", \"a green theme\"), is [\"ALL\"]. Nothing but the array."))
        text = str(getattr(reply, "text", reply) or "").strip()
        start, end = text.find("["), text.rfind("]")
        named = json.loads(text[start:end + 1]) if start >= 0 and end > start else None
    except Exception:  # noqa: BLE001 — not knowing is "unscoped", never a guess
        logger.warning("[restyle] which roles the request names could not be read", exc_info=True)
        return None
    if not isinstance(named, list):
        return None
    if any(str(n).strip().upper() == ALL_ROLES for n in named):
        return [ALL_ROLES]
    known = {r.lower(): r for r in roles}
    out = [known[str(n).strip().lower()] for n in named if str(n).strip().lower() in known]
    return out or None


def scope_of(named: list[str] | None, roles: list[str]) -> set[str] | None:
    """The roles a restyle may change for what the request names: the named
    roles, their variants (`primary-hover`, `primary-subtle` for `primary`),
    and — when a surface the text sits on changes — the text and border
    roles, which may have to move to stay readable. None means unscoped."""
    if not named or ALL_ROLES in named:
        return None
    allowed: set[str] = set()
    for r in named:
        allowed.add(r)
        allowed |= {x for x in roles if x.startswith(f"{r}-") or x.startswith(f"{r}_")}
        if r in ("background", "surface"):
            allowed |= {x for x in roles if x.startswith("text") or x in ("border", "foreground", "muted-foreground")}
    return allowed


def kept_in_scope(before: dict, proposed: dict, scope: set[str] | None) -> tuple[dict, list[str]]:
    """`proposed` with every role outside `scope` put back as it was; the
    roles put back, by name. Unscoped, nothing is put back."""
    if scope is None:
        return dict(proposed), []
    colors = dict(proposed)
    kept: list[str] = []
    for role, was in before.items():
        if role in scope:
            continue
        if str(colors.get(role) or "").lower() != str(was or "").lower():
            colors[role] = was
            kept.append(role)
    return colors, sorted(kept)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:60] or "restyle"


def palette_decision(doc: dict) -> dict | None:
    """The decision currently binding on the design system: the latest
    APPROVED decision whose wording the design system says it followed, or
    whose reason names the palette question — the one discovery asked."""
    ds = doc.get("designSystem") or {}
    evidence = " ".join(str(ds.get(k) or "") for k in ("visualPersonality", "paletteEvidence")).lower()
    # A decision another one supersedes is no longer binding: the second
    # restyle said it superseded the ORIGINAL palette, skipping the first
    # restyle, and briefed the design agent with the wrong "earlier" palette.
    replaced = {str(d.get("supersedes")) for d in doc.get("decisions") or []
                if isinstance(d, dict) and d.get("supersedes")}
    best = None
    for d in doc.get("decisions") or []:
        if not isinstance(d, dict) or d.get("status") not in (None, "APPROVED") or str(d.get("id")) in replaced:
            continue
        text = str(d.get("decision") or "").strip()
        reason = str(d.get("reason") or "").lower()
        if not text:
            continue
        if (text.lower()[:40] in evidence) or "palette" in reason or "colour" in reason or "color" in reason \
                or "theme" in reason:
            best = d
    return best


def record_decision(svc: Any, change: str) -> dict:
    """The user's words as the decision on the design system, superseding the
    palette decision it replaces. A new id, not an overwrite: the history has
    to read as a change of mind (§20, §92)."""
    previous = palette_decision(svc.doc)
    body = {
        "decision": change,
        "reason": "Asked in conversation after the build; the design system's palette and theme were "
                  "re-decided against it.",
        "source": "user",
        "approvedBy": "user",
        "binding": True,
        "status": "APPROVED",
        "version": svc.doc.get("version", 1),
    }
    if previous and previous.get("decision") != change:
        body["supersedes"] = previous["id"]
    from services.smith.smith import bootstrap as _bind_ids
    _bind_ids(svc)
    written = svc.upsert("decisions", body, natural_key=f"designSystem:{_slug(change)}")
    svc.save()
    return written


def brief_for(change: str, design: dict, previous: dict | None, named: list[str] | None = None) -> str:
    """What this call is for. The standing task tells the agent to use the
    colour the application description names — and the description still
    names the old palette, so briefed only "the user asked for green" the
    agent kept lavender-blue and said the description had decided. The brief
    has to say, first, that the standing rule is superseded for this call."""
    superseded = (f"The earlier palette decision was \"{previous.get('decision')}\" "
                  f"({previous.get('id')}); it is superseded by this request. "
                  if previous else "")
    return (
        "THIS IS A RESTYLE of an application that is already built, not a first authoring.\n"
        f"The user asked: \"{change}\". That is now the binding decision on the design system.\n"
        f"{superseded}"
        "YOUR STANDING RULE ABOUT COLOUR SOURCE IS SUPERSEDED FOR THIS CALL: the colour the "
        "application description names is the palette the user has just decided to leave. Do not "
        "use it, do not keep it, and do not answer that the description decided — the user has "
        "changed their mind, and returning the current colours unchanged is a refusal of the "
        "request, not a reading of the description.\n\n"
        + (
            # ONE ROLE ASKED FOR IS ONE ROLE CHANGED. The scheme is re-derived
            # only when the request is about the palette as a whole.
            f"THE REQUEST NAMES: {', '.join(named)}. Change {'that role' if len(named) == 1 else 'those roles'} "
            "and nothing else. A variant of a changed role (its hover, its subtle) follows it; a text or "
            "border role moves only if the changed surface leaves it unreadable, and then by as little "
            "as readability needs. Every other role keeps its exact value — the accent, the primary and "
            "the status colours are not re-decided because one role changed. "
            if named and ALL_ROLES not in named else
            "Re-decide the colour roles so the primary honours it, and re-derive primary-hover, "
            "primary-subtle, border, surface and the accent from the new primary as a considered scheme "
            "— the accent a true complement or near-triad, status colours still distinguishable for "
            "red-green deficiency, text roles keeping their contrast on the new surfaces. ")
        + "Keep every other decision exactly as it is: "
        "typography, spacing, radius, elevation, information density, navigation approach, "
        "interaction and accessibility conventions. Keep the SAME colour role names — every "
        "page and every token reads them, and a renamed role is a broken app. Say in "
        "`visualPersonality` that the colour now comes from this decision.\n\n"
        "The design system as it stands:\n```json\n"
        + json.dumps(design, indent=1, sort_keys=True, ensure_ascii=False) + "\n```"
    )


def _changed(before: dict, after: dict) -> dict[str, tuple]:
    return {k: (before.get(k), after.get(k)) for k in sorted(set(before) | set(after))
            if str(before.get(k) or "").lower() != str(after.get(k) or "").lower()}


def _proposed_colors(proposals: list) -> dict:
    body = getattr(proposals[0], "body", None) or {}
    return dict((body.get("colors") or {}) if isinstance(body, dict) else {})


def restyle(svc: Any, change: str, *, app_root: str | None = None,
            executor: Any = None, reasoning: Any = None) -> dict:
    """Re-decide the design system for `change`, commit it, re-project the tokens."""
    from services.blueprint.agent_contract import InvalidPatternTemplate, AuthorRefusal
    from services.blueprint.executors import RunUsage, make_executor, tiered_router
    from services.blueprint.orchestrator import DAG, TaskSpec
    from services.blueprint.projection import project_design_tokens
    from services.blueprint.service import BlueprintInvalid
    from services.smith.change import apply_change

    change = (change or "").strip()
    if not change:
        raise RestyleError("no change was described, so there is nothing to restyle.")
    design = svc.doc.get("designSystem") or {}
    if not design.get("colors"):
        raise RestyleError("this application has no design system yet — the build authors it; "
                           "there is nothing to restyle until then.")
    before = copy.deepcopy(design.get("colors") or {})
    previous = palette_decision(svc.doc)
    named = roles_named(change, sorted(before))
    scope = scope_of(named, sorted(before))
    brief = brief_for(change, design, previous, named)
    agent = DAG[NODE].agent
    run = executor or make_executor(svc, tiered_router(reasoning=reasoning),
                                    usage=RunUsage.for_app(svc, phase="change"),
                                    reasoning=reasoning)
    feedback = ""
    out = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        spec = TaskSpec(task_id=f"smith-restyle-{attempt}", node=NODE, agent=agent,
                        attempt=attempt, feedback=feedback, brief=brief)
        tell(reasoning, f"Re-deciding the design system: {change}.", "step")
        result = run(spec)
        proposals = [p for p in (getattr(result, "proposals", None) or [])
                     if getattr(p, "section", "") == "designSystem"]
        if not proposals:
            raise RestyleError("the design agent returned no design system. Nothing has been changed.")
        proposed = _proposed_colors(proposals)
        # HELD TO WHAT WAS ASKED. Roles the request did not name go back to
        # their values before the proposal is judged or committed; what was
        # put back is said. The agent's scheme is advice; the scope is the ask.
        proposed, kept = kept_in_scope(before, proposed, scope)
        if kept:
            body = getattr(proposals[0], "body", None)
            if isinstance(body, dict):
                body["colors"] = dict(proposed)
            logger.info("[restyle] attempt %d: %d role(s) kept as they were (outside the request): %s",
                        attempt, len(kept), ", ".join(kept)[:300])
        logger.info("[restyle] attempt %d: %d role(s) differ: %s", attempt,
                    len(_changed(before, proposed)), json.dumps(_changed(before, proposed))[:400])
        if not _changed(before, proposed):
            # THE PALETTE CAME BACK AS IT WAS. That is the agent following its
            # standing colour-source rule over the brief — a refusal of the
            # request dressed as a result. Reported as a rejection so the
            # retry is told, and never committed as a restyle.
            out = None
            feedback = ("Every colour role came back exactly as it was, so the request was not "
                        "honoured. The application description's colour wording is superseded by "
                        f"the user's request — \"{change}\" — and "
                        + (f"the role(s) it names ({', '.join(named)}) must change to honour it."
                           if named and ALL_ROLES not in named else
                           "the primary, its hover and subtle variants, the border, the surface and the "
                           "accent must change to honour it."))
            if attempt == MAX_ATTEMPTS:
                raise RestyleError(f"the design agent kept the palette unchanged {MAX_ATTEMPTS} times, "
                                   f"so nothing has been changed. It was asked for: {change}.")
            tell(reasoning, "The design agent kept the palette as it was — asking again.", "step")
            continue
        try:
            out = apply_change(svc, change, proposals=proposals,
                               interpretation=f"restyle the design system: {change}",
                               agent=agent, app_root=app_root, regenerate=False)
        except (BlueprintInvalid, AuthorRefusal) as exc:
            out = None
            feedback = f"{type(exc).__name__}: {exc}".replace("\n", " ")[:400]
        if out is not None and out.applied:
            break
        feedback = feedback or str(getattr(out, "reason", "") or "refused")
        if attempt == MAX_ATTEMPTS:
            raise RestyleError(f"the restyled design system was refused {MAX_ATTEMPTS} times and "
                               f"nothing has been changed. The last reason was: {feedback}")
        tell(reasoning, f"That design system was refused — {feedback} Asking again.", "step")
    after = (svc.doc.get("designSystem") or {}).get("colors") or {}
    # The decision is recorded AFTER the design system honours it: a decision
    # standing over a palette that ignores it is the Blueprint lying.
    decision = record_decision(svc, change)
    files: list[str] = []
    if app_root:
        files = list(project_design_tokens(svc.doc, app_root).get("files") or [])
    return {"applied": True, "before": before, "after": after, "changed": _changed(before, after),
            "named": list(named or []), "kept": kept,
            "decision": decision.get("id"), "supersedes": (previous or {}).get("id"),
            "edited_paths": files, "version": getattr(out, "version", svc.doc.get("version", 1))}


def summary_of(out: dict, change: str) -> str:
    """One sentence a user can read: what moved, and what it supersedes."""
    changed = out.get("changed") or {}
    named = [n for n in (out.get("named") or []) if n != ALL_ROLES]
    lead = [f"{k} {v[0]} → {v[1]}" for k, v in changed.items() if k in _LEAD_ROLES or k in named]
    rest = len(changed) - len(lead)
    what = (", ".join(lead) if lead else f"{len(changed)} colour role(s)")
    if rest > 0:
        what += f" and {rest} more role(s)"
    kept = out.get("kept") or []
    if named:
        others = len((out.get("before") or {})) - len(changed)
        what += (f"; every other role kept as it was"
                 + (f" ({', '.join(kept[:4])}{' and more' if len(kept) > 4 else ''} were put back)" if kept else "")
                 if others > 0 else "")
    return (f"Restyled the design system for \"{change}\": {what}. "
            f"Recorded as {out.get('decision')}"
            + (f", superseding {out.get('supersedes')}" if out.get("supersedes") else "")
            + ". The tokens are re-projected; every screen picks the new colours up "
              "without being re-composed.")


def run(output_dir: str, change: str, *, reasoning: Any = None) -> dict:
    """The tool/verb envelope — `{applied, edited_paths, diff_summary, reason}`,
    the shape `compose.run` returns, so the session and the tool loop share
    one implementation."""
    from services.blueprint.service import BlueprintService
    try:
        svc = BlueprintService.load(output_dir=str(output_dir))
    except FileNotFoundError:
        return {"applied": False, "edited_paths": [],
                "reason": "this project has no Blueprint yet, so there is no design system to restyle."}
    app_root = str(Path(output_dir) / "app")
    try:
        out = restyle(svc, change, app_root=app_root, reasoning=reasoning)
    except RestyleError as exc:
        return {"applied": False, "edited_paths": [], "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 — a tool degrades, it does not crash
        logger.exception("[smith] restyle failed")
        # The owner reads this; "MalformedEnvelope: design_system: proposal 0
        # body was not JSON" told a non-technical owner nothing (UAT replay).
        return {"applied": False, "edited_paths": [],
                "reason": ("I could not change the colours this time — the design step's answer came back "
                           "unreadable, so nothing in the app was changed. Ask again and I will retry.")}
    return {"applied": True, "edited_paths": out["edited_paths"],
            "diff_summary": summary_of(out, change), "version": out["version"],
            "changed": out["changed"], "decision": out["decision"], "reason": ""}


__all__ = ["restyle", "run", "record_decision", "palette_decision", "brief_for", "summary_of", "RestyleError",
           "roles_named", "scope_of", "kept_in_scope", "ALL_ROLES"]
