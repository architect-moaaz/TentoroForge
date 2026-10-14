"""The paths people take through the application (`flows`), read three ways.

A flow is a person's route to one of their goals: the screen they are on, what
they do there, the process that does it, and how they reach the next screen —
taken there, shown the way, or by the menu (`AppFlow`, `FlowStep`).

  * `hand_offs` — what one screen hands to the next: the page writer is told
    them, so placing an order opens the order rather than leaving an empty
    cart (ToroCommerce, forge-v3, 2026-10-07).
  * `landing` — where a process leaves the person once it has worked, read
    from the flow, never stored twice.
  * `flow_findings` — what in a flow names nothing: a screen that is gone, a
    section the screen does not have, a process not started where the step
    says it is done. Refusals the author answers, like any other contract.

`graph` is the same flows as boxes and arrows, for the App Flow view.
"""
from __future__ import annotations

import re
from typing import Any

THEN = ("go", "offer", "menu")


def _live(rows: Any) -> list[dict]:
    return [r for r in rows or [] if isinstance(r, dict) and r.get("status") not in ("DEPRECATED", "SUPERSEDED")]


def flows(doc: dict) -> list[dict]:
    return [f for f in _live(doc.get("flows")) if isinstance(f.get("steps"), list)]


def _pages(doc: dict) -> dict[str, dict]:
    return {str(p.get("id")): p for p in _live(doc.get("pages")) if p.get("id")}


def _section(page: dict, key: Any) -> dict | None:
    return next((s for s in page.get("sections") or [] if isinstance(s, dict) and str(s.get("key")) == str(key)), None)


def address(doc: dict, step: dict, carries: str | None = None) -> str:
    """Where a step is, as a link: its screen, its tab (`?tab=`), or the panel
    that opens the record it is handed (`?<param>={id}`)."""
    page = _pages(doc).get(str(step.get("page"))) or {}
    route = str(page.get("route") or "")
    sec = _section(page, step.get("section")) if step.get("section") else None
    if sec is not None and sec.get("placement") == "tab":
        return f"{route}?tab={sec['key']}"
    if sec is not None and sec.get("placement") == "panel" and sec.get("param") and carries:
        return f"{route}?{sec['param']}={{id}}"
    if carries and "[" in route:
        return re.sub(r"\[[^\]/]+\]", "{id}", route, count=1)
    if carries and sec is None:
        # The screen's own panel for that record, when it has one.
        panel = next((s for s in page.get("sections") or [] if isinstance(s, dict)
                      and s.get("placement") == "panel" and s.get("param")
                      and str(s.get("entity") or "") == str(carries)), None)
        if panel is not None:
            return f"{route}?{panel['param']}={{id}}"
    return route


def carried(doc: dict, step: dict, nxt: dict) -> str | None:
    """The record a step hands the next one: the one it names, or — when its
    process creates records of a kind and the next step is the panel or page
    of that kind — the one it made. "Place order" then "the order" was
    written without `carries`, and the hand-off opened the orders list rather
    than the order (ToroCommerce, 2026-10-07)."""
    if step.get("carries"):
        return str(step["carries"])
    wid = str(step.get("workflow") or "")
    if not wid:
        return None
    from services.blueprint.functional_completeness import _workflow_db_ops
    from services.blueprint.screen_parts import _workflow_entities
    wf = next((w for w in _live(doc.get("workflows")) if str(w.get("id")) == wid), None)
    if wf is None or "db_insert" not in _workflow_db_ops(wf):
        return None
    page = _pages(doc).get(str(nxt.get("page"))) or {}
    sec = _section(page, nxt.get("section")) if nxt.get("section") else None
    target = str((sec or {}).get("entity") or (page.get("data") or {}).get("primaryEntity") or "")
    opens_one = (sec is not None and sec.get("placement") == "panel" and sec.get("param")) \
        or (sec is None and "[" in str(page.get("route") or ""))
    return target if target and opens_one and target in _workflow_entities(wf) else None


def hand_offs(doc: dict, page_id: str) -> list[dict]:
    """What a screen hands on: `{does, workflow, then, to, toName, address,
    carries, flow}` for every flow step on `page_id` that has a next step."""
    pages = _pages(doc)
    ents = {str(e.get("id")): str(e.get("name")) for e in (doc.get("data") or {}).get("entities") or []
            if isinstance(e, dict)}
    out: list[dict] = []
    for flow in flows(doc):
        steps = flow["steps"]
        for i, step in enumerate(steps[:-1]):
            if str(step.get("page")) != str(page_id):
                continue
            nxt = steps[i + 1]
            to = pages.get(str(nxt.get("page"))) or {}
            carries = carried(doc, step, nxt)
            sec = _section(to, nxt.get("section")) if nxt.get("section") else None
            out.append({
                "flow": str(flow.get("name") or flow.get("id")),
                "does": str(step.get("does") or ""),
                "workflow": str(step.get("workflow") or "") or None,
                "then": str(step.get("then") or "go"),
                "to": str(nxt.get("page")),
                "toName": str(to.get("name") or to.get("route") or nxt.get("page"))
                          + (f" — {sec.get('label') or sec.get('key')}" if sec else ""),
                "address": address(doc, nxt, carries),
                "carries": ents.get(carries or "", carries),
            })
    return out


def landing(doc: dict, workflow_id: str) -> dict | None:
    """Where a process leaves the person once it has worked: the step after
    the first flow step it does — `{then, to, address, carries}` — or None."""
    for flow in flows(doc):
        steps = flow["steps"]
        for i, step in enumerate(steps[:-1]):
            if str(step.get("workflow") or "") == str(workflow_id):
                nxt = steps[i + 1]
                carries = carried(doc, step, nxt)
                return {"then": str(step.get("then") or "go"), "to": str(nxt.get("page")),
                        "address": address(doc, nxt, carries), "carries": carries,
                        "flow": str(flow.get("name") or flow.get("id"))}
    return None


def flow_findings(doc: dict) -> list[str]:
    """What in the flows names nothing, each said so the author can mend it."""
    pages = _pages(doc)
    workflows = {str(w.get("id")): w for w in _live(doc.get("workflows")) if w.get("id")}
    roles = {str(r.get("id")) for r in _live(doc.get("roles"))}
    ents = {str(e.get("id")) for e in (doc.get("data") or {}).get("entities") or [] if isinstance(e, dict)}
    out: list[str] = []
    for flow in flows(doc):
        name = str(flow.get("name") or flow.get("id"))
        if flow.get("role") and str(flow["role"]) not in roles:
            out.append(f"flow {name!r}: role {flow['role']} is not one of the application's roles")
        steps = flow["steps"]
        if len(steps) < 2:
            out.append(f"flow {name!r}: a flow goes somewhere — it needs at least two steps")
        for i, step in enumerate(steps, 1):
            where = f"flow {name!r}, step {i}"
            page = pages.get(str(step.get("page")))
            if page is None:
                out.append(f"{where}: {step.get('page')} is not a screen of the application")
                continue
            if step.get("section") and _section(page, step["section"]) is None:
                keys = ", ".join(str(s.get("key")) for s in page.get("sections") or [] if isinstance(s, dict))
                out.append(f"{where}: {page.get('route')} has no section {step['section']!r}"
                           + (f" (it has: {keys})" if keys else " (it has none)"))
            if step.get("then") and str(step["then"]) not in THEN:
                out.append(f"{where}: `then` is one of {', '.join(THEN)}")
            if step.get("carries") and str(step["carries"]) not in ents:
                out.append(f"{where}: carries {step['carries']}, which is not a record type")
            wid = str(step.get("workflow") or "")
            if wid:
                wf = workflows.get(wid)
                if wf is None:
                    out.append(f"{where}: {wid} is not a process of the application")
                elif str(page.get("id")) not in [str(x) for x in wf.get("launchedFrom") or []] \
                        and str((wf.get("trigger") or {}).get("kind") or "manual") == "manual":
                    out.append(f"{where}: {wf.get('name')} ({wid}) is done on {page.get('route')}, which does not "
                               "start it — name the screen it starts from, or a process that screen starts")
            if i < len(steps) and not str(step.get("does") or "").strip():
                out.append(f"{where}: say what the person does here to move on")
    return out


def graph(doc: dict) -> dict:
    """The flows as a diagram: `{flows: [{id, name, role, goal, ends, nodes,
    edges}]}` — a node per step (its screen, and the part of it), an edge per
    move, labelled with what the person does and how they get there."""
    pages = _pages(doc)
    roles = {str(r.get("id")): str(r.get("name")) for r in _live(doc.get("roles"))}
    workflows = {str(w.get("id")): str(w.get("name")) for w in _live(doc.get("workflows"))}
    out = []
    for flow in flows(doc):
        nodes, edges = [], []
        for i, step in enumerate(flow["steps"]):
            page = pages.get(str(step.get("page"))) or {}
            sec = _section(page, step.get("section")) if step.get("section") else None
            nodes.append({
                "id": f"s{i}",
                "page": str(step.get("page")),
                "screen": str(page.get("name") or step.get("page")),
                "route": str(page.get("route") or ""),
                "part": (str(sec.get("label") or sec.get("key")) if sec else ""),
                "placement": (str(sec.get("placement") or "") if sec else ""),
                "last": i == len(flow["steps"]) - 1,
                # WHAT IS DONE WHERE A FLOW ENDS, drawn in its box: the last
                # step is often the work itself ("Edit profile").
                **({"does": str(step.get("does") or ""),
                    "process": workflows.get(str(step.get("workflow") or ""), "")}
                   if i == len(flow["steps"]) - 1 and (step.get("does") or step.get("workflow")) else {}),
            })
            if i:
                prev = flow["steps"][i - 1]
                edges.append({"from": f"s{i - 1}", "to": f"s{i}",
                              "does": str(prev.get("does") or ""),
                              "process": workflows.get(str(prev.get("workflow") or ""), ""),
                              "then": str(prev.get("then") or "go")})
        out.append({"id": str(flow.get("id")), "name": str(flow.get("name") or ""),
                    "role": roles.get(str(flow.get("role") or ""), ""), "goal": str(flow.get("goal") or ""),
                    "ends": str(flow.get("ends") or ""), "nodes": nodes, "edges": edges})
    return {"flows": out}


FLOWS_PROMPT = (
    "Write the FLOWS of this application: the paths its people take through it to reach their "
    "goals. The screens and the processes are decided — this is how a person moves between them.\n\n"
    "For every person below, a flow for each of their goals (two goals may share one), from where they "
    "start — the screen they land on, or the menu — to where the goal is reached: the record they made, "
    "open and showing its state; what they sent, confirmed; what they changed, visible. Each step is a screen "
    "they are on (`page`, and `section` when it is one part of it — a tab, the panel a record opens "
    "in); what they `does` there, in their words; the `workflow` that does it, when a process does — "
    "one the screen starts; and `then`: `go` when finishing the step takes them to the next screen "
    "(what they just made opens), `offer` when they stay and are shown the way on (a link to where it "
    "went), `menu` when they go on by themselves. When the next step opens a "
    "record this step chose or made, name its record type in `carries`.\n\n"
    "A goal no flow reaches is a path missing, and a step with no way to the next is a dead end: say it "
    "in `issues` rather than invent a screen. `ends` says what the person sees when it is done.\n\n"
    "Return the flows as `flows` proposals, one per flow, each with `name`, `role` (the role id of who "
    "takes it), `goal`, `steps` and `ends`."
)


def flows_brief(doc: dict) -> dict:
    """What the flows are written from: the people and their goals, the
    screens with their sections and actions, and what each screen starts."""
    roles = {str(r.get("id")): str(r.get("name")) for r in _live(doc.get("roles"))}
    ents = {str(e.get("id")): str(e.get("name")) for e in (doc.get("data") or {}).get("entities") or []
            if isinstance(e, dict)}
    launched: dict[str, list[dict]] = {}
    for w in _live(doc.get("workflows")):
        for pid in w.get("launchedFrom") or []:
            launched.setdefault(str(pid), []).append({"id": w.get("id"), "name": w.get("name"),
                                                      "purpose": w.get("purpose") or ""})
    screens = []
    for p in _live(doc.get("pages")):
        if str(p.get("pattern") or "") == "auth":
            continue
        screens.append({
            "id": p.get("id"), "name": p.get("name"), "route": p.get("route"),
            "for": [roles.get(str(u), str(u)) for u in p.get("users") or []],
            "access": p.get("access") or "authenticated",
            "sections": [{"key": s.get("key"), "label": s.get("label"), "placement": s.get("placement"),
                          "records": ents.get(str(s.get("entity") or ""), ""), "actions": s.get("actions") or []}
                         for s in p.get("sections") or [] if isinstance(s, dict)],
            "starts": launched.get(str(p.get("id")), []),
        })
    people = [{"persona": x.get("name"), "goals": x.get("goals") or [], "description": x.get("description") or ""}
              for x in (doc.get("product") or {}).get("personas") or [] if isinstance(x, dict)]
    return {"people": people, "roles": [{"id": k, "name": v} for k, v in roles.items()],
            "screens": screens, "menu": (doc.get("navigation") or {}).get("tree") or []}


__all__ = ["flows", "address", "hand_offs", "landing", "flow_findings", "graph", "flows_brief",
           "FLOWS_PROMPT", "THEN"]
