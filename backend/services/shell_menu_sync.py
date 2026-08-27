"""Derive the sidebar menu in ``shell.json`` from ``contracts/nav-flow.json``.

Before this sync, the shell's menu (``.props.groups``) was written once
at initial generation and never updated when refine added or removed a
top-level feature. Now the shell is a *derivative* of the nav-flow —
one source of truth for what the app's real routes are, and the
sidebar always agrees.

Contract:
  * ``derive_shell_groups(nav_flow)`` — pure function; returns a list
    of ``{label, route, icon}`` dicts, one per top-level shell page.
  * ``sync_shell_menu(output_dir)`` — reads nav-flow, derives the
    groups, replaces the groups array in shell.json (wherever it
    lives in the tree) atomically. Idempotent.

Design choices:
  * The whole (potentially nested) shell root is walked to find any
    node with ``props.groups: [...]`` — we don't hardcode a shape
    because shells vary (SideNav, AppShell, custom LayoutShell).
  * A page is a "top-level feature" iff its route has exactly one
    non-dynamic segment (``/candidates`` yes, ``/candidates/[id]`` no)
    and its ``shell`` flag is true.
  * The label comes from the route slug humanized (``/recruiters`` →
    ``"Recruiters"``), never from the page title (those end in
    ``…Page`` and read wrong in a sidebar).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.nav_icon_map import icon_for, icon_for_with_llm


def sync_shell_menu(output_dir: str) -> dict:
    """Read ``nav-flow.json``, derive the groups, write them into
    ``shell.json``. Returns ``{synced, groups, message}``. Never raises
    — a missing input file is a no-op.

    Group source, in priority order:
      0. **Plan-declared** ``plan.nav.sidebar`` — when the planner has
         explicitly authored the sidebar (labels, order, grouping), that
         shape wins verbatim. Preserves LLM judgment about how to organize
         the app's IA — the derivation is only a fallback for plans that
         don't declare their sidebar.
      1. Derivation from nav-flow.json pages (existing behavior).
    """
    from services.plan_field_lookup import load_plan

    root = Path(output_dir)
    nav_flow_path = root / "src" / "contracts" / "nav-flow.json"
    shell_path    = root / "src" / "schemas"   / "shell.json"

    if not nav_flow_path.exists() or not shell_path.exists():
        return {
            "synced": False,
            "groups": [],
            "message": "nav-flow.json or shell.json missing — skipped",
        }

    try:
        nav_flow = json.loads(nav_flow_path.read_text())
    except Exception as exc:  # noqa: BLE001
        return {"synced": False, "groups": [], "message": f"nav-flow parse failed: {exc}"}

    try:
        shell = json.loads(shell_path.read_text())
    except Exception as exc:  # noqa: BLE001
        return {"synced": False, "groups": [], "message": f"shell parse failed: {exc}"}

    plan = load_plan(str(root))

    # IRF-M3-T4: honour plan.app_shape.nav.menu. When the shape declares
    # "none" (single-page consumer utility, hero-CTA app), skip menu
    # synthesis entirely — a shell-less app has nothing to render the
    # menu into, and populating shell.json.props.groups just adds junk
    # a downstream renderer would ignore anyway.
    if isinstance(plan, dict):
        _app_shape = plan.get("app_shape")
        if isinstance(_app_shape, dict):
            _nav = _app_shape.get("nav") or {}
            if _nav.get("menu") == "none":
                return {
                    "synced": False,
                    "groups": [],
                    "message": "shape.nav.menu=none — menu synthesis skipped by design",
                }

    # Template-emitted pages (the /tasks inbox is a .tsx template, not a
    # schema) never appear in nav-flow, so menu derivation can't see them.
    # Union in the top-level template routes that actually exist on disk.
    extra_routes = _template_routes_on_disk(root)

    derived = derive_shell_groups(nav_flow, plan=plan, extra_routes=extra_routes)
    declared = _plan_declared_sidebar(plan)
    if declared:
        # Plan judgment owns labels/order/grouping — but completeness and
        # correctness are ours: drop entries pointing at join-entity or
        # nonexistent routes, then top-up sections the plan forgot.
        groups = _reconcile_declared_sidebar(declared, derived, nav_flow, plan)
    else:
        groups = derived
    # Shell schemas historically have two shapes: some use a top-level
    # ``root`` key (the newer form), some use ``children`` directly (the
    # legacy form). Walk from whichever exists.
    entry = shell.get("root") if isinstance(shell.get("root"), dict) else shell
    changed = _replace_groups_in_place(entry, groups)
    if not changed:
        # No ``props.groups`` anchor — some frames (e.g. the split icon
        # rail) bake LITERAL nav Buttons instead. Those freeze at
        # shell-build time and drift as pages are added later (qeqorfii:
        # missing Organizers/Tasks, a mis-wired navigate). Rebuild the
        # labeled button strip from the derived groups.
        changed = _rebuild_button_menu(entry, groups)
    if not changed:
        return {
            "synced": False,
            "groups": groups,
            "message": "shell.json has no props.groups anchor or button menu strip to update",
        }

    shell_path.write_text(json.dumps(shell, indent=2))
    return {
        "synced": True,
        "groups": groups,
        "message": f"synced {len(groups)} group(s) into shell.json",
    }


_AUTH_ROUTES = {"/login", "/signup"}


def _plan_declared_sidebar(plan: dict | None) -> list[dict] | None:
    """Return the plan's ``nav.sidebar`` normalized to a flat list of
    ``{label, route, icon}`` groups (matching what ``derive_shell_groups``
    produces), or None when the plan is silent.

    Supports two plan shapes:

    a. **Per-role** (canonical, what the planner prompt emits):
       ``[{"role": "admin", "items": ["/dashboard", "/roles", ...]}]``
       — routes are bare strings. We flatten across roles into a
       deduplicated, first-seen-order list. The runtime shell today serves
       one sidebar per app; per-role rendering can layer on later.

    b. **Flat** (LLM-authored, judgment sidebar):
       ``[{"label": "Candidate", "items": [{"label": "Dashboard",
       "route": "/dashboard"}, ...]}]`` — labels + nested items are
       preserved verbatim.

    Auth routes (``/login``, ``/signup``) are filtered from both shapes:
    the LLM occasionally slips them in and they never belong in a
    signed-in user's shell.
    """
    if not isinstance(plan, dict):
        return None
    nav = plan.get("nav") or plan.get("navigation")
    if not isinstance(nav, dict):
        return None
    raw = nav.get("sidebar") or nav.get("menu")
    if not isinstance(raw, list) or not raw:
        return None

    # Detect shape by the first non-empty entry.
    is_per_role = any(
        isinstance(e, dict)
        and "role" in e
        and isinstance(e.get("items"), list)
        and (not e["items"] or isinstance(e["items"][0], str))
        for e in raw
    )
    if is_per_role:
        return _flatten_per_role_sidebar(raw)
    return _clean_flat_sidebar(raw)


def _flatten_per_role_sidebar(raw: list) -> list[dict] | None:
    """Turn ``[{role, items: [routes]}, …]`` into a flat
    ``[{label, route, icon}, …]`` union (first-seen order, deduped)."""
    seen: set[str] = set()
    out: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        items = entry.get("items")
        if not isinstance(items, list):
            continue
        for route in items:
            if not isinstance(route, str) or not route.startswith("/"):
                continue
            if route in _AUTH_ROUTES or route in seen:
                continue
            seen.add(route)
            label = _humanize_route(route)
            out.append({"label": label, "route": route, "icon": icon_for_with_llm(label)})
    return _dedupe_by_label(out) or None


def _dedupe_by_label(items: list[dict]) -> list[dict]:
    """Collapse entries whose normalized label collides with an earlier entry.

    Real-defect this repairs: a plan's per-role sidebar can list two different
    routes that ``_humanize_route`` maps to the same string (e.g. ``/profile``
    and ``/member-profile`` both → "Member Profile"), and the shell renders
    both — the top-nav shows the label twice back-to-back. First-seen wins;
    later collisions drop.
    """
    seen_labels: set[str] = set()
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        if not isinstance(label, str) or not label.strip():
            out.append(item)  # can't dedup without a label; keep as-is
            continue
        norm = label.strip().casefold()
        if norm in seen_labels:
            continue
        seen_labels.add(norm)
        out.append(item)
    return out


def _clean_flat_sidebar(raw: list) -> list[dict] | None:
    """Normalize a hand-authored flat sidebar with nested items[]."""
    def _clean(entry) -> dict | None:
        if not isinstance(entry, dict):
            return None
        label = entry.get("label") or entry.get("title")
        route = entry.get("route") or entry.get("to") or entry.get("href")
        if not isinstance(label, str) or not label.strip():
            return None
        if route in _AUTH_ROUTES:
            return None
        out: dict = {"label": label.strip()}
        if isinstance(route, str) and route.startswith("/"):
            out["route"] = route
        icon = entry.get("icon")
        if isinstance(icon, str) and icon.strip():
            out["icon"] = icon
        elif "route" in out:
            out["icon"] = icon_for_with_llm(out["label"])
        sub = entry.get("items") or entry.get("children")
        if isinstance(sub, list) and sub:
            cleaned_sub = [c for c in (_clean(s) for s in sub) if c]
            if cleaned_sub:
                out["items"] = cleaned_sub
        return out if ("route" in out or "items" in out) else None

    out = [c for c in (_clean(e) for e in raw) if c]
    return out or None


def _template_routes_on_disk(root: Path) -> list[str]:
    """Top-level routes served by TEMPLATE .tsx pages (not schema pages),
    which therefore never appear in nav-flow. Only the known inventory —
    scanning src/app blindly would drag auth/dev routes into the menu."""
    out: list[str] = []
    # /tasks is the workflow-approval inbox UNLESS the domain has a Task
    # entity — then the inbox relocates to /inbox (runtime_injector
    # collision guard) and /tasks belongs to the entity's own pages.
    for route, rel in (
        ("/tasks", "src/app/tasks/page.tsx"),
        ("/inbox", "src/app/inbox/page.tsx"),
    ):
        if (root / rel).is_file():
            out.append(route)
    return out


def _reconcile_declared_sidebar(
    declared: list[dict],
    derived: list[dict],
    nav_flow: dict,
    plan: dict | None,
) -> list[dict]:
    """Plan-declared sidebar, made correct and complete.

    * drops entries whose route is a join-entity slug (DB detail in the IA)
      or points at a route with no real landing page;
    * appends derived groups the plan forgot (completeness top-up), so a
      section that exists in the app is always reachable from the shell.
    """
    from services.entity_shape import join_route_slugs

    joins = join_route_slugs(plan)
    real: set[str] = {"/"}
    for p in (nav_flow or {}).get("pages") or []:
        if isinstance(p, dict):
            r = p.get("route")
            if isinstance(r, str) and r.startswith("/") and "[" not in r:
                real.add(r)
    real.update(g["route"] for g in derived if isinstance(g.get("route"), str))

    def _keep(entry: dict) -> bool:
        route = entry.get("route")
        if not isinstance(route, str):
            return bool(entry.get("items"))  # pure group label with children
        slug = route.strip("/").split("/", 1)[0] if route != "/" else "/"
        if slug in joins:
            return False
        return route in real

    kept: list[dict] = []
    for e in declared:
        if not isinstance(e, dict):
            continue
        sub = e.get("items")
        if isinstance(sub, list):
            e = dict(e)
            e["items"] = [s for s in sub if isinstance(s, dict) and _keep(s)]
            if not e["items"] and "route" not in e:
                continue
        if _keep(e):
            kept.append(e)

    def _routes_in(items: list[dict]) -> set[str]:
        acc: set[str] = set()
        for it in items:
            if isinstance(it.get("route"), str):
                acc.add(it["route"])
            for s in it.get("items") or []:
                if isinstance(s, dict) and isinstance(s.get("route"), str):
                    acc.add(s["route"])
        return acc

    present = _routes_in(kept)
    for g in derived:
        if g.get("route") not in present:
            kept.append(g)
    return _dedupe_by_label(kept)


def derive_shell_groups(
    nav_flow: dict,
    plan: dict | None = None,
    extra_routes: list[str] | None = None,
) -> list[dict]:
    """Return one ``{label, route, icon}`` per top-level shell route.

    ``plan`` (optional) lets the derivation exclude pure-join entities'
    routes; ``extra_routes`` unions in top-level routes that exist on disk
    but not in nav-flow (template pages like the /tasks inbox).
    """
    from services.entity_shape import join_route_slugs

    join_slugs = join_route_slugs(plan) if plan else set()
    pages = (nav_flow or {}).get("pages") or []
    # Auth routes are NEVER menu items — a signed-in user in the app shell
    # should not see "Sign up" in their sidebar. We honour two sources of
    # truth: nav_flow.auth_routes (populated when the plan tagged the page
    # with type=auth) and a hardcoded safety net for the two conventional
    # route names, because plans sometimes fail to mark auth pages and
    # they'd leak into the sidebar via shell:true.
    _HARDCODED_AUTH = {"/login", "/signup"}
    auth_routes = set(nav_flow.get("auth_routes") or []) | _HARDCODED_AUTH
    # Only routes that have a REAL landing page qualify — a top like
    # ``/apply`` that exists only as a dynamic child (``/apply/[role-id]``)
    # would 404 when the sidebar links to it. Collect the set of plain,
    # non-dynamic routes actually declared in nav-flow, then require each
    # sidebar target to be one of them.
    real_routes: set[str] = set()
    for p in pages:
        if not isinstance(p, dict):
            continue
        r = p.get("route")
        if isinstance(r, str) and r.startswith("/") and "[" not in r:
            real_routes.add(r)
    # First-segment routes with shell:true, deduped, in first-seen order.
    seen_routes: set[str] = set()
    top_level: list[str] = []
    for p in pages:
        if not isinstance(p, dict):
            continue
        if p.get("shell") is False:
            continue
        route = p.get("route")
        if not isinstance(route, str) or not route.startswith("/"):
            continue
        top = _top_route(route)
        if top in auth_routes:
            continue
        if top != "/" and top.lstrip("/") in join_slugs:
            # Pure-join entity (SessionSpeaker → /session-speaker): a DB
            # implementation detail. Never a sidebar destination — its UX
            # lives inline on the parent detail page.
            continue
        if _junk_route_slug(top):
            # Workflow-artifact route (/scanproductworkflow-scansession):
            # a machine-name mash the LLM emitted as a page. Its label can
            # only ever be junk, and users never navigate there directly.
            continue
        if top not in real_routes:
            # Dynamic-only top (e.g. only ``/apply/[role-id]`` exists) —
            # nothing to land on. Drop it to avoid the sidebar 404.
            continue
        if top in seen_routes:
            continue
        seen_routes.add(top)
        top_level.append(top)

    # Template-page routes that exist on disk but not in nav-flow
    # (the /tasks inbox is a .tsx template): union them in so the app's
    # real sections are all reachable.
    for r in extra_routes or []:
        if isinstance(r, str) and r.startswith("/") and r not in seen_routes \
                and r not in auth_routes:
            seen_routes.add(r)
            top_level.append(r)

    # Home ('/') anchors position 0 when present.
    top_level.sort(key=lambda r: (0 if r == "/" else 1, r))

    # Aggregate visibleTo across every page under each top route so the
    # runtime shell can filter the sidebar per role. A group's roles is
    # the UNION of every page's visibleTo under that top route. If ANY
    # page is public (visibleTo=None), the group is public — because a
    # user hitting the top route lands on the public page. Only when
    # EVERY page under the top route is scoped to a role does the
    # group carry the role list.
    roles_per_top: dict[str, set[str] | None] = {}
    for p in pages:
        if not isinstance(p, dict):
            continue
        route = p.get("route")
        if not isinstance(route, str) or not route.startswith("/"):
            continue
        top = _top_route(route)
        if top not in seen_routes:
            continue
        vt = p.get("visibleTo")
        prior = roles_per_top.get(top)
        if vt is None:
            # A single public page under this top → group is public.
            roles_per_top[top] = None
            continue
        if isinstance(vt, list):
            role_set = {r for r in vt if isinstance(r, str) and r.strip()}
            if prior is None and top in roles_per_top:
                continue  # already known public — public wins
            if isinstance(prior, set):
                prior.update(role_set)
            else:
                roles_per_top[top] = set(role_set)

    # Prefer the authored nav-flow title for the landing page of each top
    # route ("Staff") over the mechanical slug humanization ("Staffs") —
    # but only when the title reads as human copy. A glued CamelCase token
    # ("CandidateListPage") is a codebase name, not a label.
    def _human_title(t: str) -> bool:
        # A single "word" past ~14 chars is a glued machine name
        # ("Scanproductworkflow") — lowercase mashes defeat the camel
        # splitter, so fall back to the route-derived label instead.
        if any(len(w) > 14 for w in t.split()):
            return False
        return " " in t or not any(c.isupper() for c in t[1:])

    titles: dict[str, str] = {}
    for p in pages:
        if isinstance(p, dict) and isinstance(p.get("route"), str) \
                and isinstance(p.get("title"), str) and p["title"].strip() \
                and _human_title(p["title"].strip()):
            titles.setdefault(p["route"], p["title"].strip())

    groups: list[dict] = []
    for route in top_level:
        label = titles.get(route) or _humanize_route(route)
        group = {
            "label": label,
            "route": route,
            "icon":  icon_for_with_llm(label),
        }
        roles = roles_per_top.get(route)
        if isinstance(roles, set) and roles:
            group["roles"] = sorted(roles)
        kids = _child_menu_routes(pages, route, real_routes, auth_routes)
        if kids:
            group["items"] = [
                {
                    "label": titles.get(k) or _humanize_route("/" + k.strip("/").split("/")[-1]),
                    "route": k,
                    "icon":  icon_for_with_llm(
                        titles.get(k) or _humanize_route("/" + k.strip("/").split("/")[-1])),
                }
                for k in kids
            ]
        groups.append(group)
    return _dedupe_by_label(groups)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _junk_route_slug(top: str) -> bool:
    """True for machine-artifact top routes that must never reach the menu.

    The tell is "workflow" glued into a longer slug (``/scanproductworkflow-
    scansession``) — a plain ``/workflows`` admin section stays legitimate.
    """
    slug = top.lstrip("/").lower()
    if not slug:
        return False
    if slug in ("workflow", "workflows"):
        return False
    return "workflow" in slug


# Route leaves that are reached from the parent list's own buttons, never
# from the sidebar. "New Product" sitting under "Products" in the nav is
# noise; the Products page already owns that affordance.
_CRUD_LEAVES = {"new", "create", "edit", "add"}


def _child_menu_routes(pages, top: str, real_routes: set[str],
                       auth_routes: set[str]) -> list[str]:
    """Sub-screens of ``top`` that deserve their own menu entry.

    The menu used to be first-segment-only, so a plan that declared
    ``/stock/adjust``, ``/stock/transfer`` and ``/stock/movements``
    produced a single "Stock" item and three pages nothing linked to.

    A child qualifies when it is exactly one level under ``top``, has a
    real (non-dynamic) landing page, is not an auth route, and is not a
    CRUD leaf. Deeper routes stay out — ``/products/[id]/skus/new`` is
    reached from the record it belongs to, not from the shell.
    """
    if top == "/":
        return []
    seg = top.strip("/")
    out: list[str] = []
    for p in pages:
        if not isinstance(p, dict) or p.get("shell") is False:
            continue
        r = p.get("route")
        if not isinstance(r, str) or not r.startswith("/") or "[" in r:
            continue
        if r in auth_routes or r not in real_routes:
            continue
        parts = [x for x in r.strip("/").split("/") if x]
        if len(parts) != 2 or parts[0] != seg:
            continue
        if parts[1].lower() in _CRUD_LEAVES:
            continue
        out.append(r)
    return sorted(set(out))


def _top_route(route: str) -> str:
    """``/candidates/[id]/edit`` → ``/candidates`` — the sidebar target."""
    if route == "/":
        return "/"
    parts = [p for p in route.strip("/").split("/") if p]
    if not parts:
        return "/"
    return "/" + parts[0]


def _humanize_route(route: str) -> str:
    """``/recruiters`` → ``Recruiters``; ``/`` → ``Home``."""
    if route == "/":
        return "Home"
    slug = route.strip("/").split("/", 1)[0]
    # Split on -/_ or camelCase boundaries, title-case each piece.
    import re
    pieces = re.split(r"[-_\s]+|(?<=[a-z0-9])(?=[A-Z])", slug)
    return " ".join(p.capitalize() for p in pieces if p)


def _rebuild_button_menu(node: Any, groups: list[dict]) -> bool:
    """Rebuild a LITERAL-button nav strip from the derived groups.

    Some shell frames (the split icon-rail) render the menu as plain
    ``Button`` nodes instead of a ``props.groups``-driven component, so
    the menu freezes at shell-build time: pages added later never appear,
    and hand-authored buttons can carry mis-wired targets (qeqorfii's
    Organizers button navigated to /staffs). Find the labeled nav strip —
    the container with the most Button children that have BOTH a label
    and a navigate target (the icon-only rail has aria-labels, not
    labels, so it never wins) — and regenerate its buttons 1:1 from the
    groups, cloning the first existing button's className so the frame's
    styling survives. Returns True iff a strip was rebuilt.
    """
    flat_groups: list[dict] = []
    for g in groups:
        if isinstance(g.get("route"), str):
            flat_groups.append(g)
        for s in g.get("items") or []:
            if isinstance(s, dict) and isinstance(s.get("route"), str):
                flat_groups.append(s)
    if not flat_groups:
        return False

    def _is_nav_button(c: Any) -> bool:
        if not (isinstance(c, dict) and c.get("type") == "Button"):
            return False
        p = c.get("props")
        return (isinstance(p, dict)
                and isinstance(p.get("label"), str) and p["label"].strip()
                and isinstance(p.get("navigate"), str))

    best: dict | None = None
    best_count = 0

    def _walk(n: Any) -> None:
        nonlocal best, best_count
        if isinstance(n, dict):
            kids = n.get("children")
            if isinstance(kids, list):
                count = sum(1 for c in kids if _is_nav_button(c))
                if count >= 3 and count > best_count:
                    best, best_count = n, count
                for c in kids:
                    _walk(c)
            for v in n.values():
                if isinstance(v, (dict, list)) and v is not kids:
                    _walk(v)
        elif isinstance(n, list):
            for v in n:
                _walk(v)

    _walk(node)
    if best is None:
        return False

    exemplar = next(c for c in best["children"] if _is_nav_button(c))
    cls = (exemplar.get("props") or {}).get("className")
    non_buttons = [c for c in best["children"] if not _is_nav_button(c)]
    rebuilt = []
    for g in flat_groups:
        props: dict = {
            "icon": g.get("icon") or "circle",
            "variant": "ghost",
            "navigate": g["route"],
            "onClick": {"action": "navigate", "to": g["route"]},
            "label": g.get("label") or _humanize_route(g["route"]),
        }
        if isinstance(cls, str):
            props["className"] = cls
        rebuilt.append({"type": "Button", "props": props})
    best["children"] = non_buttons + rebuilt
    return True


def _replace_groups_in_place(node: Any, new_groups: list[dict]) -> bool:
    """Walk the shell root, replace any ``props.groups`` array we find.
    Returns True iff at least one array was replaced."""
    replaced = False
    def _walk(n: Any) -> None:
        nonlocal replaced
        if isinstance(n, dict):
            p = n.get("props")
            if isinstance(p, dict) and isinstance(p.get("groups"), list):
                p["groups"] = list(new_groups)  # shallow copy — deterministic
                replaced = True
            for v in n.values():
                _walk(v)
        elif isinstance(n, list):
            for v in n:
                _walk(v)
    _walk(node)
    return replaced
