"""Planner Agent (#1) — multi-turn requirement gathering and structured plan output.

Takes a user's app description, clarifies requirements through conversation,
and produces a detailed structured plan (entities, pages, workflows, RBAC).
Org-aware: infers roles and permissions from org structure.
"""

import logging
import os
import re
from typing import Any, AsyncIterator

from services.agent_messages import ClaudeAgentOptions

from services.sdk_agent_runner import query
from services.agent_messages import Message

# Module logger. Used across the file (see e.g. run_planner_oneshot's
# fast-build skip note); Areeb's Task-3 speed edits added a `logger.info`
# call without adding the module-level init, so every fast-profile gen
# crashed on `NameError: name 'logger' is not defined`.
logger = logging.getLogger(__name__)
from services.register_selector import (
    classify_register as _classify,
    classify_register_llm as _classify_llm,
)
from services.app_design_catalog import catalog_for_prompt
from services.workflow_node_contracts import format_node_catalog

# Module logger. Its sole consumer today is the fast-build completeness-revise
# skip below — which referenced `logger` before this was defined, raising
# NameError inside run_planner_oneshot and crashing planning for EVERY fast
# build whose plan had any completeness gap (i.e. almost all of them). The
# smith-arch path and the classic produce_plan fallback both funnel through
# that function, so the crash took down planning entirely ("never builds").
# Reproduced live 2026-08-07; this line is the fix.
logger = logging.getLogger(__name__)


# --- inlined from the former services.page_type_classifier -----------------
# The planner is the sole caller of this taxonomy; it runs only when a page
# lacks a planner-authored `type`. Six-type precedence:
#   error > auth > form > detail > dashboard > list > fallback(list)
_AUTH_RE = re.compile(
    r"(?:^|/)(?:login|signup|sign-?in|sign-?up|forgot[- ]?password|reset[- ]?password|register)(?:$|/)",
    re.I,
)
_FORM_SUFFIX_RE = re.compile(r"/(?:new|create|edit)$", re.I)
_DYNAMIC_SEG_RE = re.compile(r"\[\w+\]|:\w+")
_ERROR_ROUTES = {"/error", "/not-found", "/404", "/500"}
_DASHBOARD_KEYWORDS = ("dashboard", "overview", "summary", "metrics", "analytics")
_FORM_KEYWORDS = ("form", "input", "create", "submit")
_LIST_KEYWORDS = ("list", "browse", "catalog", "directory")


def _classify_page_from_route(
    route: str,
    name: str = "",
    description: str = "",
    entity: str | None = None,
) -> str:
    """Deterministic route/description-based page-type taxonomy — one of
    ``error / auth / form / detail / dashboard / list``. Only used when the
    planner did not author a `page.type` value."""
    r = (route or "").strip()
    desc_lower = (description or "").lower()

    # 1. Error pages — never reclassify.
    if r in _ERROR_ROUTES:
        return "error"
    stem = r.lstrip("/").split("/")[0] if r else ""
    if stem in {"error", "not-found", "404", "500"}:
        return "error"

    # 2. Auth pages.
    if _AUTH_RE.search(r):
        return "auth"

    # 3. Form pages.
    if _FORM_SUFFIX_RE.search(r):
        return "form"
    if any(k in desc_lower for k in _FORM_KEYWORDS):
        return "form"

    # 4. Detail — dynamic route segment.
    if _DYNAMIC_SEG_RE.search(r):
        return "detail"

    # 5. Dashboard.
    if r in ("/", "/home", "/dashboard", ""):
        return "dashboard"
    if any(k in desc_lower for k in _DASHBOARD_KEYWORDS):
        return "dashboard"

    # 6. List.
    if any(k in desc_lower for k in _LIST_KEYWORDS):
        return "list"
    if entity and r.rstrip("/").split("/")[-1].endswith("s"):
        return "list"

    # Fallback.
    return "list"


def _infer_entity_for_page(page: dict, entity_names: list[str]) -> str | None:
    """Infer a primary entity name for a page that is missing one.

    Strategy (deterministic, no LLM):
    1. If the page's `entity` is set and is a real entity name (not "N/A",
       "none", "null", "", etc.), return it as-is.
    2. Try to match the route segments against entity names — e.g.
       "/leave-requests/[id]" → "LeaveRequest".
    3. Return None if no match (entity-free pages like dashboards won't have
       entity; dashboards call _entity_summary_for_dashboard instead).
    """
    raw = (page.get("entity") or "").strip()
    _NA = {"n/a", "none", "null", "unknown", "-", ""}
    if raw and raw.lower() not in _NA:
        # Validate it's actually a known entity before trusting it.
        if raw in entity_names:
            return raw
        # LLM sometimes returns camelCase that differs in capitalisation.
        raw_lower = raw.lower()
        for name in entity_names:
            if name.lower() == raw_lower:
                return name

    # Route-based inference: /leave-requests → LeaveRequest, /users → User
    route = (page.get("route") or "").strip("/")
    # Take the first non-dynamic segment
    first_seg = route.split("/")[0] if route else ""
    if first_seg and not first_seg.startswith("["):
        # Convert kebab-case to PascalCase and try to match
        candidate = "".join(w.capitalize() for w in first_seg.replace("-", "_").split("_"))
        if candidate in entity_names:
            return candidate
        # Also try singular if plural (strip trailing 's')
        if candidate.endswith("s") and candidate[:-1] in entity_names:
            return candidate[:-1]

    return None


def _entity_summary_for_dashboard(page: dict, entity_names: list[str]) -> list[str]:
    """Return the list of entity names a dashboard page should summarize.

    For entity-free pages (dashboard, team calendar, etc.), returns the full
    entity list so the page-schema-agent knows what to aggregate.
    For pages with a real entity, returns an empty list (use entity field instead).
    """
    raw = (page.get("entity") or "").strip()
    _NA = {"n/a", "none", "null", "unknown", "-", ""}
    # If it already has a real entity, don't add entity_summary
    if raw and raw.lower() not in _NA and raw in entity_names:
        return []
    page_type = (page.get("type") or "").lower()
    if page_type == "dashboard":
        return entity_names
    return []


def _decide_auth_gating(plan: dict) -> bool:
    """Decide once whether the app is auth-gated. Deterministic, idempotent.

    IRF-M3-T3: highest priority is the four-axis shape's ``auth.surface``.
      * ``none`` → un-gated (single-session utility, tip calc, marketing).
      * ``modal`` / ``route`` / ``sso-only`` → gated (auth exists, just
        differs in how the user sees it).
    The historic gating heuristic (any entities → gated) runs as fallback
    for plans without an ``app_shape`` field.

    An explicit ``plan['authGated']`` bool still overrides everything —
    manual user preference wins over automatic derivation.
    """
    v = plan.get("authGated")
    if isinstance(v, bool):
        return v
    # IRF-M3-T3: shape.auth.surface is authoritative when declared.
    shape = plan.get("app_shape") if isinstance(plan, dict) else None
    if isinstance(shape, dict):
        auth = shape.get("auth")
        if isinstance(auth, dict):
            surface = auth.get("surface")
            if surface == "none":
                return False
            if surface in ("modal", "route", "sso-only"):
                return True
    # Fallback heuristic (existing behaviour for plans without app_shape).
    if bool(plan.get("entities")):
        return True
    # A plan that already declares a login/signup page is gated even with no
    # entities (e.g. an auth-first flow).
    for p in plan.get("pages") or []:
        if isinstance(p, dict) and (
            (p.get("type") or "").lower() == "auth"
            or (p.get("route") or "") in ("/login", "/signup")
        ):
            return True
    return False


def _ensure_auth_pages(plan: dict, gated: bool) -> dict:
    """When gated, guarantee login (+ signup only for self-signup apps) so they
    flow into real schemas + nav-flow. When not gated, strip any auth pages so
    the entry point is ``/``. Idempotent.

    Slice B: signup only makes sense when at least one actor has
    ``onboarding.source == "self_signup"``. For invite-only apps (every actor
    is ``invited_by`` or ``platform_org``) the public signup page is a dead
    end — dropped from the plan + stripped from any prior page list."""
    pages = plan.get("pages")
    if not isinstance(pages, list):
        return plan

    def _is_auth(p: object) -> bool:
        return isinstance(p, dict) and (
            (p.get("type") or "").lower() == "auth"
            or (p.get("route") or "") in ("/login", "/signup")
        )

    def _is_signup(p: object) -> bool:
        return isinstance(p, dict) and (p.get("route") or "") == "/signup"

    if not gated:
        plan["pages"] = [p for p in pages if not _is_auth(p)]
        return plan

    # IRF-M3-T3: shape.auth.surface="modal" means the auth flow is a
    # <LoginModal> component overlaid on regular pages — NO /login or
    # /signup route pages needed. Strip any existing ones (planner
    # sometimes emits them even when the shape says modal) and skip the
    # "gated but missing auth pages" addition below. The dashboard-shell
    # `useRequireAuth` hook triggers the modal on gated-page load.
    shape = plan.get("app_shape") if isinstance(plan, dict) else None
    auth_surface = None
    if isinstance(shape, dict):
        _auth = shape.get("auth")
        if isinstance(_auth, dict):
            auth_surface = _auth.get("surface")
    if auth_surface == "modal":
        plan["pages"] = [p for p in pages if not _is_auth(p)]
        return plan

    # Actor-aware: if actors block exists, honour it. When it doesn't (legacy
    # plans), default to allowing signup so we don't regress those flows.
    self_signup_ok = _has_self_signup_actor(plan.get("actors"))
    if not self_signup_ok:
        pages = [p for p in pages if not _is_signup(p)]
        plan["pages"] = pages

    # Gated. If the planner already declared any auth page, respect its choice
    # (some apps are login-only, admin-provisioned — don't force a signup).
    if any(_is_auth(p) for p in pages):
        return plan

    # Gated but NO auth pages at all (the common miss): add login always, plus
    # signup only when the actors block permits public self-signup.
    to_add: list[dict] = [
        {"route": "/login", "name": "Login", "type": "auth", "entity": None},
    ]
    if self_signup_ok:
        to_add.append({"route": "/signup", "name": "Sign Up", "type": "auth", "entity": None})
    plan["pages"] = pages + to_add
    return plan


def _has_self_signup_actor(actors: object) -> bool:
    """True IFF the actors block is present and at least one actor has
    ``onboarding.source == "self_signup"``. Missing actors block → True
    (legacy behaviour: always add signup, so pre-slice-B plans don't
    regress)."""
    if actors is None:
        return True
    if not isinstance(actors, list) or not actors:
        return True  # empty/invalid: treat as unknown → keep signup
    for a in actors:
        if not isinstance(a, dict):
            continue
        ob = a.get("onboarding") or {}
        if isinstance(ob, dict) and ob.get("source") == "self_signup":
            return True
    return False


def _kebab(s: str) -> str:
    """'WatchlistItem' → 'watchlist-item', 'Portfolio Page' → 'portfolio-page'."""
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", s)          # split camelCase
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()  # non-alnum → '-'
    return s or "page"


def _slug_for_page(p: dict) -> str:
    """Derive a route slug from a page's identity (entity → name → id)."""
    for key in ("entity", "name", "id"):
        v = (p.get(key) or "").strip()
        if v and v.lower() not in ("n/a", "none", "null", "unknown", "-"):
            return _kebab(v)
    return "page"


def _sanitize_page_routes(plan: dict) -> dict:
    """Enforce unique, normalised routes on plan.pages BEFORE schema-gen.

    Two pages that resolve to the same URL can't both exist: the schema file
    (named `slugify_route(route).json`) and its registry key are derived from the
    route, so a duplicate route means one page silently overwrites the other and
    the nav links to a route only one page claims. The LLM planner occasionally
    collapses distinct pages onto one route (e.g. two overview pages both
    "/dashboard"). Normalise every route (`:param` → `[param]`) and give any
    collision a distinct route derived from the page's own entity/name/id.

    Deterministic, idempotent, mutates and returns plan. This is the plan-level
    invariant that keeps schema file, registry key, internal `route`, and nav
    link consistent by construction — page_schema_agent then pins each schema's
    route to its slug, and nav_route_reconcile_guard is the final backstop.
    """
    from services.route_slug import normalise_route, slugify_route

    pages = plan.get("pages")
    if not isinstance(pages, list):
        return plan

    seen: set[str] = set()
    for p in pages:
        if not isinstance(p, dict):
            continue
        route = normalise_route((p.get("route") or "").strip()) or f"/{_slug_for_page(p)}"
        # Reject routes with filesystem-hostile segments (would crash slugify).
        try:
            slugify_route(route)
        except ValueError:
            route = f"/{_slug_for_page(p)}"
        if route in seen:
            base = f"/{_slug_for_page(p)}"
            cand = base
            i = 2
            while cand in seen or cand == route:
                cand = f"{base}-{i}"
                i += 1
            route = cand
        p["route"] = route
        seen.add(route)
    return plan


_ALLOWED_ACTION_KINDS = ("row_action", "page_action")


def _sanitize_page_actions(plan: dict) -> dict:
    """Normalize per-page `actions[]`: keep only well-formed actions whose
    `workflow` is declared in plan['workflows'] and whose `kind` is allowed;
    set `actions: []` on pages that have none. Mutates and returns plan.

    Slice 3 (ADDITIVE, backward-compatible): an action MAY additionally carry an
    OPTIONAL `input_map` ({formField: entityColumn}) and `requires_record` (bool)
    expressing how the button/form feeds its workflow. These are preserved when
    well-formed and simply absent otherwise — an action without them is emitted
    exactly as before ({label, workflow, kind}). The post-gen
    action_contract_guard reconciles/derives these against the REAL workflows;
    the planner's values are only a hint."""
    pages = plan.get("pages")
    if not isinstance(pages, list):
        return plan
    known = {w["name"] for w in (plan.get("workflows") or [])
             if isinstance(w, dict) and w.get("name")}
    for p in pages:
        if not isinstance(p, dict):
            continue
        clean = []
        for a in p.get("actions") or []:
            if (isinstance(a, dict) and a.get("label") and a.get("workflow") in known
                    and a.get("kind") in _ALLOWED_ACTION_KINDS):
                action = {"label": a["label"], "workflow": a["workflow"], "kind": a["kind"]}
                im = a.get("input_map")
                if isinstance(im, dict):
                    clean_im = {str(k): str(v) for k, v in im.items()
                                if isinstance(k, str) and isinstance(v, (str, int, float))}
                    if clean_im:
                        action["input_map"] = clean_im
                rr = a.get("requires_record")
                if isinstance(rr, bool):
                    action["requires_record"] = rr
                clean.append(action)
        p["actions"] = clean
    return plan


_FIELD_SEMANTIC = ("currency", "percent", "email", "phone", "url", "multiline")


def _sanitize_page_fields(plan: dict) -> dict:
    """Normalize per-page `fields[]` — the planner's COMPLETE per-field form spec for a
    form/create/edit page. Mirrors `_sanitize_page_actions`: keep only well-formed field
    entries and pass them through normalization; drop malformed ones.

    A field entry MUST carry a non-empty string `name`. It MAY additionally carry an
    OPTIONAL `semanticType` (currency/percent/…), `label`, `required` (bool), `enum`
    (literal option values), and `order` (int). The control type is NOT authored here —
    it is DERIVED downstream by the shared `resolve_control` authority from the real SQL
    column + the semanticType hint, so any `control` key is stripped/ignored. Each
    optional key is preserved only when well-formed and simply absent otherwise. The
    deterministic form builder merges these OVER the registry-derived defaults — the
    registry backfills any omitted column — so a partial or wholly-absent spec still
    yields a complete, correct form."""
    pages = plan.get("pages")
    if not isinstance(pages, list):
        return plan
    for p in pages:
        if not isinstance(p, dict) or not isinstance(p.get("fields"), list):
            continue
        clean = []
        for f in p["fields"]:
            if not isinstance(f, dict):
                continue
            name = f.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            entry: dict = {"name": name.strip()}
            # `control` is intentionally NOT carried through — the control type is derived
            # downstream from the SQL column + semanticType, so any planner `control` is dropped.
            if f.get("semanticType") in _FIELD_SEMANTIC:
                entry["semanticType"] = f["semanticType"]
            lbl = f.get("label")
            if isinstance(lbl, str) and lbl.strip():
                entry["label"] = lbl.strip()
            if isinstance(f.get("required"), bool):
                entry["required"] = f["required"]
            en = f.get("enum")
            if isinstance(en, list):
                vals = [str(v).strip() for v in en
                        if isinstance(v, (str, int, float)) and str(v).strip()]
                if vals:
                    entry["enum"] = vals
            order = f.get("order")
            if isinstance(order, int) and not isinstance(order, bool):
                entry["order"] = order
            clean.append(entry)
        p["fields"] = clean
    return plan


_WIDGET_TYPES = ("stat", "chart", "table")
_WIDGET_METRIC_FNS = ("count", "sum", "avg", "min", "max")
_WIDGET_BUCKETS = ("day", "week", "month")


def _sanitize_page_widgets(plan: dict) -> dict:
    """Normalize per-page `widgets[]` — the planner's dashboard/report widget spec the
    deterministic dashboard builder renders from the registry. Mirrors
    `_sanitize_page_fields`/`_sanitize_page_actions`: keep only well-formed widgets, drop
    malformed ones.

    A widget MUST carry `type` ∈ stat|chart|table and a non-empty string `entity`. Per type:
      * stat  — `metric: {fn ∈ count|sum|avg|min|max, field?, filter?}` (required; a non-count
                fn needs a `field`).
      * chart — `groupBy` (required string) + optional `agg: {fn, field?}`, `bucket`, `filter`.
      * table — optional `filter`, `limit` (int), `columns` (list of column names).
    Every widget MAY carry a `title`. The deterministic builder VALIDATES each widget's
    entity + referenced columns against the registry and DROPS any that reference a
    non-existent entity/column — these planner values are intent, the registry is truth."""
    pages = plan.get("pages")
    if not isinstance(pages, list):
        return plan
    for p in pages:
        if not isinstance(p, dict) or not isinstance(p.get("widgets"), list):
            continue
        clean = []
        for w in p["widgets"]:
            if not isinstance(w, dict):
                continue
            wtype = w.get("type")
            ent = w.get("entity")
            if wtype not in _WIDGET_TYPES or not isinstance(ent, str) or not ent.strip():
                continue
            entry: dict = {"type": wtype, "entity": ent.strip()}
            title = w.get("title")
            if isinstance(title, str) and title.strip():
                entry["title"] = title.strip()

            if wtype == "stat":
                metric = w.get("metric")
                if not isinstance(metric, dict):
                    continue
                fn = metric.get("fn")
                if fn not in _WIDGET_METRIC_FNS:
                    continue
                m: dict = {"fn": fn}
                field = metric.get("field")
                if isinstance(field, str) and field.strip():
                    m["field"] = field.strip()
                if fn != "count" and "field" not in m:
                    continue  # sum/avg/… needs a field
                if isinstance(metric.get("filter"), dict):
                    m["filter"] = {str(k): v for k, v in metric["filter"].items()
                                   if isinstance(k, str) and isinstance(v, (str, int, float, bool))}
                    if not m["filter"]:
                        m.pop("filter")
                entry["metric"] = m

            elif wtype == "chart":
                gb = w.get("groupBy")
                if not isinstance(gb, str) or not gb.strip():
                    continue
                entry["groupBy"] = gb.strip()
                agg = w.get("agg")
                if isinstance(agg, dict) and agg.get("fn") in _WIDGET_METRIC_FNS:
                    a: dict = {"fn": agg["fn"]}
                    af = agg.get("field")
                    if isinstance(af, str) and af.strip():
                        a["field"] = af.strip()
                    entry["agg"] = a
                bucket = w.get("bucket")
                if isinstance(bucket, str) and bucket.strip().lower() in _WIDGET_BUCKETS:
                    entry["bucket"] = bucket.strip().lower()
                if isinstance(w.get("filter"), dict):
                    filt = {str(k): v for k, v in w["filter"].items()
                            if isinstance(k, str) and isinstance(v, (str, int, float, bool))}
                    if filt:
                        entry["filter"] = filt

            else:  # table
                limit = w.get("limit")
                if isinstance(limit, int) and not isinstance(limit, bool) and limit > 0:
                    entry["limit"] = limit
                cols = w.get("columns")
                if isinstance(cols, list):
                    names = [str(c).strip() for c in cols if isinstance(c, str) and c.strip()]
                    if names:
                        entry["columns"] = names
                if isinstance(w.get("filter"), dict):
                    filt = {str(k): v for k, v in w["filter"].items()
                            if isinstance(k, str) and isinstance(v, (str, int, float, bool))}
                    if filt:
                        entry["filter"] = filt

            clean.append(entry)
        p["widgets"] = clean
    return plan


# ── Sprint 4 (Forge Great Again): page.purpose + page.reading_priority ──
#
# The Design Context Pack in page_schema_agent needs to tell the Designer
# LLM what the reader needs from THIS specific page ("Manager needs a
# scan-first view of collection status and one-click access to any
# overdue payment"). Sprint 1 synthesized this from page.name + entity +
# widgets as a fallback. Sprint 4 lets the planner author it directly —
# the planner has full domain context and can write a better purpose than
# any downstream synthesis.
#
# Field contract:
#   page.purpose          — one string, ≤240 chars, plain-language sentence
#                            answering "what does the reader need when
#                            they open this page?"
#   page.reading_priority — list[str], 1-4 items, ordered top→bottom, each
#                            ≤80 chars. E.g. ["Collection status this
#                            month", "The one overdue payment", "Recent
#                            activity"].
#
# Both fields OPTIONAL. When absent, the DCP synthesizes a fallback from
# page shape. When present, the DCP passes them through verbatim.

_PURPOSE_MAX_CHARS = 240
_READING_PRIORITY_MAX_ITEMS = 4
_READING_PRIORITY_ITEM_MAX_CHARS = 80


def _sanitize_page_purpose(plan: dict) -> dict:
    """Normalize per-page ``purpose`` + ``reading_priority`` fields.

    Design intent: pass through the planner's authored purpose exactly,
    trimmed and length-capped. Never invent or transform — if the
    planner didn't emit a field, that page uses the DCP's fallback.
    """
    pages = plan.get("pages")
    if not isinstance(pages, list):
        return plan
    for p in pages:
        if not isinstance(p, dict):
            continue

        # purpose — single string
        raw_purpose = p.get("purpose")
        if isinstance(raw_purpose, str):
            purpose = raw_purpose.strip()
            if purpose:
                if len(purpose) > _PURPOSE_MAX_CHARS:
                    purpose = purpose[: _PURPOSE_MAX_CHARS - 1].rstrip() + "…"
                p["purpose"] = purpose
            else:
                p.pop("purpose", None)
        elif "purpose" in p:
            # Wrong type — drop it so downstream doesn't have to guess.
            p.pop("purpose", None)

        # reading_priority — list of strings
        raw_priorities = p.get("reading_priority")
        if isinstance(raw_priorities, list):
            clean_priorities: list[str] = []
            for item in raw_priorities:
                if not isinstance(item, str):
                    continue
                s = item.strip()
                if not s:
                    continue
                if len(s) > _READING_PRIORITY_ITEM_MAX_CHARS:
                    s = s[: _READING_PRIORITY_ITEM_MAX_CHARS - 1].rstrip() + "…"
                clean_priorities.append(s)
                if len(clean_priorities) >= _READING_PRIORITY_MAX_ITEMS:
                    break
            if clean_priorities:
                p["reading_priority"] = clean_priorities
            else:
                p.pop("reading_priority", None)
        elif "reading_priority" in p:
            p.pop("reading_priority", None)
    return plan


def _sanitize_page_wave3_ux(plan: dict) -> dict:
    """Normalize per-page + per-journey Wave 3 (advanced UX) declarations.

    Recognised shapes (all optional; silently dropped when malformed to
    match the pattern used by ``_sanitize_page_interactions``):

        page.wizard: {
            "steps": [
                {"id": str, "title": str,
                 "fields": [str, ...],
                 "nextIf": str?}
            ]
        }
        page.list.editable_columns: [col_name, ...]
        page.list.filter_fields: [
            {"name": str, "type": "string|number|boolean|date|enum",
             "operators": [str]?}
        ]
        page.layout: "master_detail"  (with page.list.detail_route: str)
        journey.onboarding: {
            "steps": [
                {"page": str, "target_selector": str,
                 "title": str, "body": str?}
            ]
        }

    The deterministic post-gen passes are the actual source of truth
    (they render schemas from these declarations); here we only enforce
    SHAPE so an obviously wrong value doesn't hit the downstream builder.
    """
    pages = plan.get("pages")
    if isinstance(pages, list):
        for p in pages:
            if not isinstance(p, dict):
                continue

            # page.wizard
            wiz = p.get("wizard")
            if isinstance(wiz, dict):
                raw_steps = wiz.get("steps")
                clean_steps: list[dict] = []
                if isinstance(raw_steps, list):
                    for i, s in enumerate(raw_steps):
                        if not isinstance(s, dict):
                            continue
                        title = s.get("title")
                        if not (isinstance(title, str) and title.strip()):
                            continue
                        fields_raw = s.get("fields") or []
                        if not isinstance(fields_raw, list):
                            continue
                        fields = [f.strip() for f in fields_raw
                                  if isinstance(f, str) and f.strip()]
                        if not fields:
                            continue
                        entry: dict = {
                            "id": (
                                s.get("id") if isinstance(s.get("id"), str) and s["id"].strip()
                                else f"step_{i + 1}"
                            ),
                            "title": title.strip(),
                            "fields": fields,
                        }
                        if isinstance(s.get("nextIf"), str) and s["nextIf"].strip():
                            entry["nextIf"] = s["nextIf"].strip()
                        clean_steps.append(entry)
                if clean_steps:
                    p["wizard"] = {"steps": clean_steps}
                else:
                    p.pop("wizard", None)

            # page.layout = "master_detail" (only that value is
            # recognised for now; anything else is left untouched so
            # existing archetype-driven layouts survive).
            layout = p.get("layout")
            if isinstance(layout, str) and layout.strip().lower() == "master_detail":
                p["layout"] = "master_detail"
            elif layout == "master_detail":
                pass  # already canonical

            # page.list.editable_columns / .filter_fields / .detail_route
            plist = p.get("list") if isinstance(p.get("list"), dict) else None
            if plist:
                # editable_columns
                ec = plist.get("editable_columns")
                if isinstance(ec, list):
                    cols = [c.strip() for c in ec
                            if isinstance(c, str) and c.strip()]
                    if cols:
                        plist["editable_columns"] = cols
                    else:
                        plist.pop("editable_columns", None)
                elif ec is not None:
                    plist.pop("editable_columns", None)

                # filter_fields
                ff = plist.get("filter_fields")
                if isinstance(ff, list):
                    clean_ff: list[dict] = []
                    for f in ff:
                        if not isinstance(f, dict):
                            continue
                        n = f.get("name")
                        if not (isinstance(n, str) and n.strip()):
                            continue
                        t = f.get("type")
                        if t not in ("string", "number", "boolean", "date", "enum"):
                            t = "string"
                        entry = {"name": n.strip(), "type": t}
                        ops = f.get("operators")
                        if isinstance(ops, list):
                            op_list = [o.strip() for o in ops
                                       if isinstance(o, str) and o.strip()]
                            if op_list:
                                entry["operators"] = op_list
                        clean_ff.append(entry)
                    if clean_ff:
                        plist["filter_fields"] = clean_ff
                    else:
                        plist.pop("filter_fields", None)
                elif ff is not None:
                    plist.pop("filter_fields", None)

                # detail_route — only carried through if a string.
                dr = plist.get("detail_route")
                if isinstance(dr, str) and dr.strip():
                    plist["detail_route"] = dr.strip()
                elif dr is not None:
                    plist.pop("detail_route", None)

    # journey.onboarding
    journey = plan.get("journey")
    if isinstance(journey, dict):
        onb = journey.get("onboarding")
        if isinstance(onb, dict):
            raw_steps = onb.get("steps")
            clean_steps: list[dict] = []
            if isinstance(raw_steps, list):
                for s in raw_steps:
                    if not isinstance(s, dict):
                        continue
                    page = s.get("page")
                    sel = s.get("target_selector") or s.get("target")
                    title = s.get("title")
                    if not (isinstance(sel, str) and sel.strip()):
                        continue
                    if not (isinstance(title, str) and title.strip()):
                        continue
                    entry = {
                        "target_selector": sel.strip(),
                        "title": title.strip(),
                    }
                    if isinstance(page, str) and page.strip():
                        entry["page"] = page.strip()
                    body = s.get("body")
                    if isinstance(body, str) and body.strip():
                        entry["body"] = body.strip()
                    clean_steps.append(entry)
            if clean_steps:
                journey["onboarding"] = {"steps": clean_steps}
            else:
                journey.pop("onboarding", None)

    return plan


def _sanitize_page_interactions(plan: dict) -> dict:
    """Normalize per-page `interactions` (Spec E Wave 1).

    Recognised shape::

        interactions: {
            reorderable?: bool,
            movable_between_lanes?: {sourceField: str},
            bulk_actions?: [workflow_name: str]
        }

    Applies to list / kanban pages only. Malformed / unknown-shape
    entries are dropped silently — the deterministic
    ``interaction_authority`` post-gen pass is the source of truth for
    entity/column/workflow existence; here we only enforce SHAPE so a
    stray string in ``bulk_actions`` doesn't hit the schema agent.
    """
    pages = plan.get("pages")
    if not isinstance(pages, list):
        return plan
    for p in pages:
        if not isinstance(p, dict):
            continue
        raw = p.get("interactions")
        if not isinstance(raw, dict):
            continue
        clean: dict = {}
        if isinstance(raw.get("reorderable"), bool):
            clean["reorderable"] = raw["reorderable"]
        mbl = raw.get("movable_between_lanes")
        if isinstance(mbl, dict) and isinstance(mbl.get("sourceField"), str) \
                and mbl["sourceField"].strip():
            clean["movable_between_lanes"] = {"sourceField": mbl["sourceField"].strip()}
        ba = raw.get("bulk_actions")
        if isinstance(ba, list):
            names = [str(x).strip() for x in ba if isinstance(x, str) and x.strip()]
            if names:
                clean["bulk_actions"] = names
        if clean:
            p["interactions"] = clean
        else:
            p.pop("interactions", None)
    return plan


def _sanitize_page_design(plan: dict) -> dict:
    """Normalize per-page `archetype` + `features` against the capability catalog
    (mirrors the guardrail; runs at plan time so the schema agent sees clean
    values). Invalid archetype → the page's `type`; unsupported features dropped."""
    from services.app_design_guardrail import normalize_app_design
    if not isinstance(plan.get("pages"), list):
        return plan
    plan, _ = normalize_app_design(plan)
    return plan


_BRANCHING_STEP_TYPES = {"exclusive_gateway", "condition", "decision"}
_END_STEP_TYPES = {"end", "end_event"}


def _sanitize_workflow_connectivity(plan: dict) -> dict:
    """Backfill flow connectivity for pure-LINEAR planner workflows only.

    The planner emits rich step dicts ({id,type,config,...}) but sometimes
    omits flow connectivity (`next`/`branches`) — the "array-order" variant.
    The faithful workflow translator needs connectivity to build a graph, so
    for the SAFE case (linear workflows with no branching step) we deterministically
    wire each non-end step to the next one in array order, terminating at a
    single `end` step. This is written back into the plan so ALL consumers see it.

    Left untouched (can't be safely inferred deterministically):
    - workflows whose steps already carry connectivity (any `next` / dict `branches`);
    - branching workflows (any step type in {exclusive_gateway, condition, decision}) —
      branch membership is unknowable from array order, so we defer to the planner
      prompt + the translator's heuristic-branch fallback.

    Deterministic, idempotent, mutates and returns plan.
    """
    if not isinstance(plan, dict):
        return plan
    workflows = plan.get("workflows")
    if not isinstance(workflows, list):
        return plan

    for wf in workflows:
        if not isinstance(wf, dict):
            continue
        steps = wf.get("steps")
        # 1. Non-empty list of dicts only.
        if not isinstance(steps, list) or not steps:
            continue
        if not all(isinstance(s, dict) for s in steps):
            continue
        # 2. Steps must look rich (at least one has config/type/id).
        if not any(("config" in s or "type" in s or "id" in s) for s in steps):
            continue
        # 3. Respect explicit graphs — any truthy next or dict branches.
        if any(s.get("next") or isinstance(s.get("branches"), dict) for s in steps):
            continue
        # 4. Skip branching workflows — branch membership can't be inferred.
        if any(str(s.get("type", "")).lower() in _BRANCHING_STEP_TYPES for s in steps):
            continue

        # 5. Pure-linear workflow missing connectivity → backfill.
        # Ensure every step has an id.
        for i, s in enumerate(steps):
            if not s.get("id"):
                s["id"] = s.get("name") or f"step_{i}"

        # Ensure exactly one terminal end step.
        end_step = next(
            (s for s in steps if str(s.get("type", "")).lower() in _END_STEP_TYPES),
            None,
        )
        if end_step is None:
            end_step = {"id": "end", "type": "end"}
            steps.append(end_step)
        end_id = end_step["id"]

        # Wire each non-end step to the next non-end step, or to end if last.
        non_end = [s for s in steps if s is not end_step]
        for i, s in enumerate(non_end):
            if s.get("next") or isinstance(s.get("branches"), dict):
                continue
            if i + 1 < len(non_end):
                s["next"] = non_end[i + 1]["id"]
            else:
                s["next"] = end_id

        wf["steps"] = steps

    return plan


# Actor / person FK column-name pattern: a column that names SOMEONE (a user who
# owns, is assigned to, or acts on a record) and therefore must FK-target the User
# entity. The pipeline needs a persisted, FK-targetable User so `assessorId`/
# `assignedAssessorId`/… get a real `.references()` and classify as people-pickers
# instead of shipping as bare, target-less uuids.
_ACTOR_FK_COLUMN_RE = re.compile(
    r"(assessor|assignee|assigned|reviewer|recruiter|manager|interviewer|"
    r"evaluator|grader|scorer|examiner|approver|supervisor)",
    re.I,
)


def _actor_fk_columns(models: list) -> list[tuple[str, str]]:
    """(entityName, columnName) for every FK-shaped column (name ends in `Id`, not
    the PK `id`) whose name matches the actor/person pattern."""
    out: list[tuple[str, str]] = []
    for m in models:
        if not isinstance(m, dict) or not m.get("name"):
            continue
        for f in m.get("fields") or []:
            if not isinstance(f, dict):
                continue
            name = str(f.get("name") or "")
            low = name.lower()
            if not name or low == "id" or not low.endswith("id"):
                continue
            if _ACTOR_FK_COLUMN_RE.search(name):
                out.append((m["name"], name))
    return out


def _find_field(fields: list, name: str) -> dict | None:
    low = str(name).lower()
    for f in fields:
        if isinstance(f, dict) and str(f.get("name") or "").lower() == low:
            return f
    return None


def _ensure_field(fields: list, spec: dict) -> None:
    if _find_field(fields, spec["name"]) is None:
        fields.append(dict(spec))


def _find_user_model(models: list) -> dict | None:
    from services.name_normalizer import to_singular
    for m in models:
        if not isinstance(m, dict):
            continue
        table = str(m.get("table") or "").lower()
        name = str(m.get("name") or "")
        if table == "users" or (name and to_singular(name).lower() == "user"):
            return m
    return None


def _ensure_actor_user_model(plan: dict) -> dict:
    """Deterministic post-planner normalizer (Theme C / RBAC).

    When the app has an access model with roles OR any data_model carries an
    actor/person FK column (``assessorId``/``assignedAssessorId``/``assigneeId``/…),
    guarantee:
      (a) a ``User`` data_model mapped to the reserved ``users`` table, carrying a
          ``role`` enum column whose values are ``access_control.roles`` (plus core
          profile columns id/name/email); and
      (b) a ``relations`` entry linking each UNLINKED actor FK column → ``User`` so
          the schema builder emits a real ``.references(() => users.id)`` and the FK
          classifier can resolve it to the users table.

    Idempotent, mutates and returns plan. A no-op for an app with neither roles nor
    actor FK columns, and it never overrides an actor FK column that already has a
    relation to a domain entity (e.g. ``Employee.managerId → Employee``).
    """
    if not isinstance(plan, dict):
        return plan
    models = plan.get("data_models")
    if not isinstance(models, list):
        return plan

    # Prefer `actors[].role` when present — that's the slice-B contract.
    # Fall back to `access_control.roles` (legacy plans) so pre-slice-B
    # fixtures still generate the User.role enum they used to.
    ac = plan.get("access_control") or {}
    ac_roles = [str(r).strip() for r in (ac.get("roles") or [])
                if isinstance(r, str) and str(r).strip()]
    actor_roles: list[str] = []
    _actors = plan.get("actors")
    if isinstance(_actors, list):
        for a in _actors:
            if not isinstance(a, dict):
                continue
            r = a.get("role")
            if isinstance(r, str) and r.strip() and r not in actor_roles:
                actor_roles.append(r.strip())
    # Actor-side wins on order; ac fills in any it didn't cover (usually none).
    roles = actor_roles or ac_roles
    if actor_roles and ac_roles:
        for r in ac_roles:
            if r not in roles:
                roles.append(r)
    actor_cols = _actor_fk_columns(models)
    if not roles and not actor_cols:
        return plan

    # (a) ensure a User data_model mapped to the reserved users table.
    user_model = _find_user_model(models)
    if user_model is None:
        user_model = {"name": "User", "table": "users", "fields": []}
        models.append(user_model)
        plan["data_models"] = models
    if not user_model.get("table"):
        user_model["table"] = "users"
    fields = user_model.setdefault("fields", [])
    if not isinstance(fields, list):
        fields = []
        user_model["fields"] = fields
    _ensure_field(fields, {"name": "id", "type": "uuid", "primaryKey": True})
    _ensure_field(fields, {"name": "name", "type": "varchar"})
    _ensure_field(fields, {"name": "email", "type": "varchar", "nullable": False})
    if roles:
        role_field = _find_field(fields, "role")
        if role_field is None:
            fields.append({"name": "role", "type": "varchar",
                           "enum_values": list(roles)})
        else:
            existing = role_field.get("enum_values") or role_field.get("enum") or []
            role_field["enum_values"] = list(dict.fromkeys([*existing, *roles]))
            role_field.setdefault("type", "varchar")

    # (b) relations linking each UNLINKED actor FK column → User.
    user_name = user_model.get("name") or "User"
    relations = plan.get("relations")
    if not isinstance(relations, list):
        relations = []
        plan["relations"] = relations
    linked = {
        (str(r.get("from") or r.get("fromEntity") or r.get("source") or ""),
         str(r.get("foreignKey") or r.get("fk") or r.get("foreign_key")
             or r.get("field") or r.get("column") or ""))
        for r in relations if isinstance(r, dict)
    }
    for ent_name, col in actor_cols:
        if ent_name == user_name:
            continue
        if (str(ent_name), str(col)) in linked:
            continue
        relations.append({"from": ent_name, "to": user_name,
                          "type": "many-to-one", "foreignKey": col})
        linked.add((str(ent_name), str(col)))
    return plan


# ── Spec D W2 — column/entity semantic normalizer ───────────────────────
# The four fields below are read by Wave 2 classifier modules to short-
# circuit their name-regex/word-list fallbacks. The planner authors them
# in the prompt; this normalizer runs on the emitted plan to drop values
# outside the closed sets (a misspelling must not leak into the
# consuming classifier and produce garbage).
#
# Fields (all optional per column / entity):
#   entity.schedulable_by       — "resource" | "person" | "none" | False
#   column.user_fk_role         — "actor" | "assignment" | "tenancy" | "audit"
#   column.role                 — "actor" | "assignment" | "tenancy" | "domain"
#   column.semantic.control     — one of _FIELD_TYPES (Input, Textarea, …)
#
# The consuming classifiers already have "invalid → fall through to legacy"
# behavior, so silent-drop here just tightens the contract at the source.

_VALID_SCHEDULABLE_BY: frozenset[str] = frozenset({"resource", "person", "none"})
_VALID_USER_FK_ROLES: frozenset[str] = frozenset({"actor", "assignment", "tenancy", "audit"})
_VALID_COLUMN_FK_ROLES: frozenset[str] = frozenset({"actor", "assignment", "tenancy", "domain"})
# Kept in lock-step with services.semantic_field_types._FIELD_TYPES — the
# closed set the consuming classifier honours. Anything else is dropped so
# the classifier's `sc in _FIELD_TYPES` gate never sees a garbage control.
_VALID_SEMANTIC_CONTROLS: frozenset[str] = frozenset({
    "Input", "Textarea", "Select", "NumberInput", "DatePicker", "Switch",
    "Combobox", "FileUpload",
})


def _iter_plan_entities(plan: dict):
    """Yield (name, entity_dict) across both plan flavours (dict and list-of-dicts).

    Same shape rules as services.plan_field_lookup._iter_entities — keeps the
    normalizer's iteration in lock-step with the reader so a field the reader
    can see is a field the normalizer can prune.
    """
    if not isinstance(plan, dict):
        return
    ents = plan.get("entities")
    if isinstance(ents, dict):
        for name, ent in ents.items():
            if isinstance(name, str) and isinstance(ent, dict):
                yield name, ent
    dm = plan.get("data_models") or plan.get("dataModels")
    if isinstance(dm, list):
        for ent in dm:
            if isinstance(ent, dict):
                nm = ent.get("name")
                if isinstance(nm, str):
                    yield nm, ent


def _iter_entity_fields(entity: dict):
    """Yield (name, field_dict) for every field on an entity.

    Handles both list-of-dicts (`fields: [{name, ...}]`) and dict
    (`fields: {name: {...}}`) shapes so the normalizer works whether the
    planner emitted the one-shot or the full-mode plan.
    """
    fields = entity.get("fields")
    if isinstance(fields, list):
        for f in fields:
            if isinstance(f, dict):
                nm = f.get("name") or f.get("column")
                if isinstance(nm, str) and nm.strip():
                    yield nm, f
    elif isinstance(fields, dict):
        for nm, f in fields.items():
            if isinstance(nm, str) and isinstance(f, dict):
                yield nm, f


def _sanitize_column_semantics(plan: dict) -> dict:
    """Drop out-of-set values for the four Spec D W2 emission fields.

    Silent-drop policy: an invalid value is REMOVED from the field/entity
    so the downstream classifier sees "plan is silent" and runs its legacy
    heuristic — never a garbage-in / garbage-out path. Idempotent; mutates
    and returns plan.
    """
    if not isinstance(plan, dict):
        return plan

    for _ent_name, ent in _iter_plan_entities(plan):
        # entity.schedulable_by — string OR literal False allowed; other
        # falsy/other-type values dropped. Normalize to lowercase for the
        # scheduler_pass comparison.
        if "schedulable_by" in ent:
            sb = ent["schedulable_by"]
            if sb is False:
                pass  # explicit opt-out — kept verbatim
            elif isinstance(sb, str):
                v = sb.strip().lower()
                if v in _VALID_SCHEDULABLE_BY or v in ("false", "no"):
                    ent["schedulable_by"] = v
                else:
                    ent.pop("schedulable_by", None)
            else:
                ent.pop("schedulable_by", None)

        for _col_name, f in _iter_entity_fields(ent):
            # column.user_fk_role — closed set, string only.
            if "user_fk_role" in f:
                r = f.get("user_fk_role")
                if isinstance(r, str) and r.strip().lower() in _VALID_USER_FK_ROLES:
                    f["user_fk_role"] = r.strip().lower()
                else:
                    f.pop("user_fk_role", None)

            # column.role — closed set, string only.
            if "role" in f:
                r = f.get("role")
                if isinstance(r, str) and r.strip().lower() in _VALID_COLUMN_FK_ROLES:
                    f["role"] = r.strip().lower()
                else:
                    f.pop("role", None)

            # column.semantic.control — dict wrapper; drop `control` key if
            # the value is not in _VALID_SEMANTIC_CONTROLS. Leave `enum_values`
            # / `format` etc. inside the blob untouched — those are validated
            # by their own downstream readers.
            sem = f.get("semantic")
            if isinstance(sem, dict) and "control" in sem:
                sc = sem.get("control")
                if not (isinstance(sc, str) and sc.strip() in _VALID_SEMANTIC_CONTROLS):
                    sem.pop("control", None)
                # A now-empty semantic blob is harmless — plan_column_semantics
                # collapses it to None. No need to remove the wrapper.

    return plan


def _annotate_page_types(plan: dict) -> dict:
    """Add `type` and infer `entity` / `entity_summary` for every page.

    Steps performed (all idempotent):
    1. Classify page type from route/name/description when `type` is missing.
    2. For pages where `entity` is "N/A" / missing, infer it from the route
       using the plan's entity list.  Dashboard pages get `entity_summary`
       (the full entity list) instead of a single `entity`.
    3. Pages that already have a valid entity or entity_summary are untouched.

    The classifier is deterministic; running on the same plan twice
    produces byte-identical output.
    """
    if not isinstance(plan, dict):
        return plan
    pages = plan.get("pages")
    if not isinstance(pages, list):
        return plan

    # Step -2 — AI-intent completeness guard: the PLANNER designs chatbots (see
    # the planner prompt). This only backfills an essential the planner dropped
    # (message entity / AI workflow / chat page) and records it, so the gap is
    # visible. No-op when there's no chat intent or the planner did its job.
    # Runs first so any backfill flows through auth-gating + route hygiene.
    from services.ai_intent import ensure_assistant_app
    _ai_report = ensure_assistant_app(plan)
    if _ai_report.get("backfilled"):
        plan["_ai_intent_backfilled"] = _ai_report["backfilled"]
    pages = plan.get("pages")

    # Step -1 — auth gating: decide once, then guarantee login/signup exist as
    # real pages (gated) or are stripped (public). Must run before route
    # hygiene so the auth routes get normalised/deduped too.
    _gated = _decide_auth_gating(plan)
    plan["authGated"] = _gated
    plan = _ensure_auth_pages(plan, _gated)
    pages = plan.get("pages")  # _ensure_auth_pages may have replaced the list

    # Step 0 — route hygiene: unique, normalised routes before anything else
    # classifies or files pages by route.
    plan = _sanitize_page_routes(plan)

    # Collect all known entity names from the plan for inference.
    entities_raw = plan.get("entities") or {}
    if isinstance(entities_raw, dict):
        entity_names = list(entities_raw.keys())
    elif isinstance(entities_raw, list):
        entity_names = [e.get("name", "") for e in entities_raw if isinstance(e, dict)]
    else:
        entity_names = []

    for p in pages:
        if not isinstance(p, dict):
            continue
        # Step 1 — page type annotation. Planner-authored `page.type` wins
        # (this branch runs only when the LLM omitted it); otherwise fall
        # back to the deterministic route/description taxonomy.
        if not p.get("type"):
            p["type"] = _classify_page_from_route(
                route=p.get("route", ""),
                name=p.get("name", "") or "",
                description=p.get("description", "") or "",
                entity=p.get("entity"),
            )
        # Step 2 — entity / entity_summary inference
        # Only run if entity is absent or "N/A"-style placeholder.
        raw_entity = (p.get("entity") or "").strip()
        _NA = {"n/a", "none", "null", "unknown", "-", ""}
        if not raw_entity or raw_entity.lower() in _NA:
            inferred = _infer_entity_for_page(p, entity_names)
            if inferred:
                p["entity"] = inferred
            else:
                # Clear the N/A placeholder so downstream code gets None
                p["entity"] = None
                # Dashboard pages get entity_summary so the LLM knows what to aggregate
                if not p.get("entity_summary"):
                    summary = _entity_summary_for_dashboard(p, entity_names)
                    if summary:
                        p["entity_summary"] = summary

    plan = _sanitize_page_actions(plan)
    plan = _sanitize_page_fields(plan)
    # Field-interaction auto-derivation — fill in obvious computed/cascade
    # interactions the LLM missed (invoice `total = qty * price`, `hra =
    # basic * 0.4`, State-depends-on-Country, etc). Never overwrites a
    # hand-authored `interaction` block. See interaction_auto_derive.py
    # rules + the Field-Interaction Authoring program plan.
    try:
        from services.interaction_auto_derive import apply_auto_derivations
        report = apply_auto_derivations(plan)
        if report["applied"]:
            import logging as _lg
            _lg.getLogger(__name__).info(
                "[interaction_auto_derive] applied %d, skipped %d — %s",
                len(report["applied"]), len(report["skipped"]),
                ", ".join(report["applied"][:5]) + ("…" if len(report["applied"]) > 5 else "")
            )
    except Exception:  # noqa: BLE001 — never block planning on auto-derive
        import logging as _lg
        _lg.getLogger(__name__).exception("[interaction_auto_derive] crashed; continuing")
    plan = _sanitize_page_widgets(plan)
    plan = _sanitize_page_purpose(plan)
    plan = _sanitize_page_interactions(plan)
    # Spec E Wave 3 — page.wizard / list.editable_columns / list.filter_fields /
    # layout=master_detail / journey.onboarding. Deterministic post-gen
    # passes render these into concrete schema when FORGE_E_PATTERNS is on.
    plan = _sanitize_page_wave3_ux(plan)
    plan = _sanitize_page_design(plan)
    plan = _sanitize_workflow_connectivity(plan)
    # RBAC (Theme C): model a persisted, FK-targetable User entity + role enum and
    # link actor FK columns to it, so assessor/assignee/… FKs resolve to users.
    plan = _ensure_actor_user_model(plan)
    # Slice B+: materialize the onboarding UI implied by actors[]. For each
    # non-self-signup actor, add the invite/link page + workflow the inviter
    # needs — so the actor's onboarding source is observable in the app,
    # not just described in the plan metadata. Idempotent + additive.
    from services.actor_onboarding_expand import derive_actor_onboarding
    plan = derive_actor_onboarding(plan)
    # Commerce detection: if the brief says "sell / cart / storefront / etc."
    # AND the plan has a product-shaped entity, mark that entity with
    # commerce:true. Downstream deterministic page builders read this flag to
    # auto-place AddToCart / CartBadge / CartPage — the cart runtime primitive
    # (forge_cart table + /api/cart routes) does the rest. Idempotent.
    # FK-target completeness: every FK column must point at a declared
    # entity — the LLM sometimes emits `Plant.nurseryLocationId` without
    # declaring `NurseryLocation`, which leaves the FK dropdown empty and
    # blocks form submission. Synthesize a minimal stub for any missing
    # target so schema builder + seed synth + Select all have something
    # concrete to work with. Structural, additive, idempotent.
    from services.fk_target_completeness import ensure_fk_targets
    plan = ensure_fk_targets(plan)
    from services.commerce_flag import flag_commerce_entity
    plan = flag_commerce_entity(plan)
    # Media-completeness: entities that plainly need a photo (Plant, Product,
    # Recipe, Property, Vehicle, ...) get a `photoUrl` field appended when the
    # LLM forgot. Also triggers on commerce entities and briefs that mention
    # photos/images. Additive + idempotent — never overwrites existing fields.
    from services.entity_completeness import ensure_media_fields
    plan = ensure_media_fields(plan)
    # Spec D W2 — drop out-of-set values on the four planner-emission fields
    # the Wave 2 classifiers read (entity.schedulable_by, column.user_fk_role,
    # column.role, column.semantic.control). Runs last so any earlier pass
    # that copies fields between shapes still gets normalised.
    plan = _sanitize_column_semantics(plan)
    return plan


def classify_register(brief: str, domain: str = "") -> str:
    """Pick a stylistic register from the brief + domain.
    Delegates to services.register_selector for the canonical heuristics."""
    return _classify(brief, domain)


async def classify_register_llm(
    brief: str,
    domain: str = "",
    plan: dict | None = None,
) -> str:
    """LLM-driven register pick — Sonnet reads the brief/domain/plan and
    chooses one of the six valid registers, falling back to the rule-based
    classifier on any failure (no API key, parse error, timeout). Same
    proxy contract as the sync `classify_register` so callers in
    `routers/generate.py` import from one place."""
    return await _classify_llm(brief, domain, plan)


PLANNER_SYSTEM_PROMPT = r"""You are an application architect planning the structure of a new application or module.
You have a multi-turn conversation with the user to clarify requirements, then produce a detailed structured plan.

═══════════════════════════════════════════════════════════════════════════
## HARD-STOP: COMPUTATIONAL TOOL DETECTION (READ FIRST)
═══════════════════════════════════════════════════════════════════════════

Before applying any other rule below, check whether the user's ask is a
STANDALONE COMPUTATIONAL TOOL — a calculator, converter, estimator,
quiz-scorer, tip calculator, EMI/loan/BMI calculator, unit/currency
converter, or similar input→formula→output tool with:

  * no accounts or user management
  * no data to store or list
  * no records anyone else needs to see
  * no workflows/approvals/notifications
  * a single page whose whole purpose is compute-a-result

If YES, IGNORE every "MANDATORY" section further down that requires:
  * a User entity (there are no accounts)
  * an actors[] block with anything other than one anonymous visitor
  * auth/login/signup pages
  * workflow_tasks / approvals / assignment strategies
  * api_routes or entity persistence

Emit a plan with `archetype: "computational"` on a single page, empty
entities/relations/api_routes, one `visitor` actor with `access: "anon"`.
See the COMPUTATIONAL section below for the exact shape.

WORKFLOWS ARE ALLOWED (and expected) when the tool needs a SIDE-EFFECT —
"email me the BMI value", "send the estimate to a webhook", "notify me
when the score is calculated", "book a consultation". In that case:
  * entities STILL = [] (the workflow is the persistence layer, not the tool)
  * workflows[] = [{name, trigger:"button", actions:[{type:"send_email"/
    "http_request"/etc, args mapped from the page's computed fields}]}]
  * add a single "Send" / "Email me" / "Notify" button on the page with
    onClick:{kind:"workflow", workflow:"<workflow_id>", args:{fieldName:
    "{{fieldName}}"}} — the runtime dispatcher passes the computed value.
  * still NO user_task nodes, NO approvals, NO login/signup, NO User entity.
  * the workflow is a black-box side-effect, not a persistence layer.

The "coherent-but-wrong CRUD-shell" bug (calculator app that ships as a
`CalculationSession` log with `/login` and `/visitors` CRUD) comes from
following the MANDATORY sections literally on tools that don't need them —
this hard-stop exists specifically to prevent that.

═══════════════════════════════════════════════════════════════════════════

IMPORTANT: You have access to the organization's structure (departments, teams, roles, people,
reporting lines). Use this to automatically infer access control, workflow assignments, and
role-based permissions. Do NOT ask the user "what roles do you need?" — infer them from the org.

## Your Process

1. UNDERSTAND: Read the user's request. If building onto an existing app, read the AppModel
   index (app-model.json) to understand what already exists.

2. CLARIFY (only if truly needed): Ask 2-4 focused questions ONLY if the request is
   genuinely ambiguous or missing critical information. If the user's request already
   specifies what the app does (e.g., "Leave Management System", "Task Tracker",
   "Inventory Management"), SKIP clarification and go straight to step 3 (PLAN).
   Make reasonable assumptions for anything not explicitly stated.

   Topics to clarify ONLY if unclear:
   - Core entities and their relationships
   - Key user workflows (what does the user DO in this app?)
   - Authentication/authorization needs
   - Any integrations (email, payments, file upload, external APIs)
   Do NOT ask more than 4 questions. Prefer making smart assumptions over asking.

   IMPORTANT: If the user says "answer with your best knowledge", "use defaults",
   "you decide", or similar — skip ALL questions and produce the plan immediately.

   IMPORTANT: If the user's description implies AI capabilities, model them as
   WORKFLOWS whose step names map to the engine's AI nodes (the workflow engine
   runs these against an LLM):
     - generate/reply/summarize/draft  → ai_generate  (write text)
     - classify/categorize/sentiment    → ai_classify  (pick a label)
     - extract/parse fields             → ai_extract   (pull structured data)
     - decide/route/recommend           → ai_decide    (choose an option)
     - OCR / scan / digitize document   → ocr_document (PaddleOCR sidecar —
       on-prem OCR with bounding boxes; use INSTEAD of ai_extract when the
       doc has plain typed/handwritten text, no complex reasoning needed)
   For a CHATBOT / assistant / conversational app, YOU (the planner) design it:
   at minimum a message-like entity (Conversation + Message) plus a chat page (a
   message list with a text input) and an "Assistant Reply" workflow triggered on
   message_created with steps ["generate_reply", "insert_reply"]. TAILOR it to the
   assistant's job — e.g. a KnowledgeBase/Document entity for a research assistant,
   a Ticket link for a support bot, a CodeSnippet for a coding helper. The two
   entities above are the floor, not the whole design. Name AI steps with the
   verbs above so they compile to the right node.

   IMPORTANT: If conversation history shows the user already answered questions or
   said to proceed, produce the plan immediately — do NOT ask more questions.

3. PLAN: Once requirements are clear, produce a COMPLETE structured plan as JSON.
   The plan is the AUTHORITY for every downstream step — schema, forms, workflows,
   navigation, sidebar. Nothing downstream may infer what the plan should have
   declared. Descriptions stay concise (one-line phrases), but the STRUCTURAL
   fields below are non-negotiable.

   ═══════════════════════════════════════════════════════════════════════════
   COMPLETENESS CONTRACT — the plan is INCOMPLETE (and will be rejected) if:
   ═══════════════════════════════════════════════════════════════════════════

   • Any entity has fields without `not_null` declared for every non-nullable
     column, or without `type` set for every field.
   • Any field the domain restricts to a fixed value set is missing its
     `enum_values` (e.g. `status`, `priority`, `type`, `stage`). If a
     workflow ever sets this column to a literal value, ALL such values
     must be in `enum_values`.
   • Any uuid field that references another table is missing its
     `fk: {table, column}` block. Every FK column must declare its target.
   • Any workflow triggered by a user is missing `inputs[]` covering every
     column the workflow writes that is not derivable from session/URL/defaults.
     If ScheduleInterview writes 5 columns to `interviews`, and only session
     and defaults cover 1 of them, `inputs[]` must have 4 entries.
   • The `actors[]` block is missing, empty, or omits an actor referenced by
     any page's `visibleTo` or any workflow's `roles`.
   • The `nav.initialFor` map is missing an entry for any role in `actors[]`.
   • Any route named in `nav.sidebar[].items` is not present in `pages[]`.

   Fill these fields. Downstream agents READ them — they do not GUESS.

```json
{
  "module_name": "string",
  "description": "string",
  "data_models": [
    {
      "name": "TableName",
      "table": "table_names",
      "purpose": "One-line: what this entity is for in the domain.",
      "primary": true,
      "fields": [
        {"name": "id", "type": "uuid", "primaryKey": true, "not_null": true},

        // A plain scalar field. `not_null` is REQUIRED on every non-nullable
        // column. `label` overrides the humanized name in forms.
        {"name": "name", "type": "varchar", "not_null": true, "label": "Full name"},

        // FIELD-KIND HINTS — declare these so the downstream form/table builders
        // don't have to infer. Anything you DECLARE HERE becomes authoritative:
        //   • `enum_values`: the ONLY values a Select for this column may offer.
        //     Never let a status/priority/type field ship without this if the
        //     column is restricted to a fixed set.
        //     PREFERRED SHAPE for user-facing dropdowns (Spec B1): emit
        //     `[{"key": "ach", "label": "ACH Transfer"}, ...]` so the Select
        //     shows the human-friendly label. The plain `["ach", "cash"]`
        //     shape still works and auto-Title-Cases (`ach` → `Ach`), but
        //     when a term is an acronym, a domain word, or otherwise doesn't
        //     Title-Case cleanly, emit the object shape with the label you
        //     want the user to see.
        //   • `fk: {table, column}`: this column is a foreign key. Forms render
        //     a Select bound to the target entity. Never emit a uuid field
        //     without an `fk` block unless it's genuinely opaque.
        //   • `semantic_type`: a hint for the control chooser when the SQL type
        //     is ambiguous. Values: "multiline" (Textarea/RichText), "email",
        //     "phone", "url", "currency", "percent", "color", "file",
        //     "cv-file", "avatar", "city", "country". If the column IS a city
        //     or airport, declare `semantic_type: "city"` — do NOT leave the
        //     field-name heuristic to guess.
        //   • `default`: default value written by the DB (`now()`, `false`,
        //     `'open'`). Fields with defaults may be omitted from create forms.
        //   • `lifecycle`: mark timestamps/audit columns so forms hide them.
        //     Values: "created_at", "updated_at", "deleted_at", "audit".
        //   • Spec C1 — DASHBOARD COMPOSITION: on any dashboard-shaped
        //     page, emit a top-level `dashboard_composition` block:
        //       "dashboard_composition": {
        //         "tiles": [
        //           {"kind":"stat", "label":"Total Units",
        //            "calc":"count", "entity":"Unit"},
        //           {"kind":"stat", "label":"Rent Collected MTD",
        //            "calc":"sum", "entity":"RentPayment", "field":"amount",
        //            "filter":"paidDate>=month_start"},
        //           {"kind":"stat", "label":"Occupancy %",
        //            "calc":"ratio", "numerator":"Unit.status=occupied",
        //            "denominator":"Unit"}
        //         ],
        //         "widgets": [
        //           {"component":"Kanban", "title":"Maintenance",
        //            "bindsTo":"MaintenanceTicket", "groupBy":"status"},
        //           {"component":"Table", "title":"Recent Payments",
        //            "bindsTo":"RentPayment", "sort":"paidDate desc", "limit":5}
        //         ],
        //         "layout": "kpi_row_over_two_column_widgets"
        //       }
        //     RULES:
        //       - calc: one of count | sum | ratio | avg | min | max | distinct
        //       - entity/bindsTo: MUST be a real entity from the plan
        //       - field: MUST be a real column on that entity
        //       - component: MUST be a real library component
        //       - layout: kpi_row_over_two_column_widgets | kpi_row_over_single_column |
        //         kpi_grid_only | widgets_only
        //     Compose the dashboard by reasoning FROM the domain — pick the
        //     tiles that answer the most-important question a user of THIS
        //     app opens the dashboard to see. Not a template.
        //   • Spec B4 — `_primary: true` on a FIELD marks it as the form's
        //     primary FK context — the parent record the form fundamentally
        //     "belongs to" (rent payment → lease, appointment → patient,
        //     invoice → customer). When the flag is set, the deterministic
        //     post-generate pass wraps the form in a 2-column layout with
        //     a context Card on the right showing the parent record's key
        //     fields. If a form has exactly ONE FK, the flag is optional
        //     (that FK auto-wins). Set it explicitly when a form has
        //     multiple FKs and one is meaningfully the "context anchor".
        //   • Spec B5 — FK AUTO-FILL: on a field whose value should default
        //     from a sibling FK's target record, emit
        //     `"interaction": {"onChange": {"fetch": {"resource": "leases",
        //     "by": "id", "from": "leaseId"}, "set": {"amount": "{{result.currentBalance}}"}}}`.
        //     When the user picks a Lease, the app fetches that lease and
        //     writes its `currentBalance` into the `amount` field. Use for
        //     any parent-record default (Customer → Address, Product → Price).
        //   • Spec B6 — CONDITIONAL SECTIONS: within a form's `fields`, you
        //     MAY emit `{"kind": "section", "name": "...", "label": "...",
        //     "visibleIf": "form.method == 'ach'", "fields": [...]}` to
        //     reveal/hide a group of fields under one predicate. Use when an
        //     enum's values imply different downstream data (payment method
        //     = ACH reveals routing #, method = cash reveals receipt #, …).
        //     Predicate is a feel-lite expression over sibling fields.
        //   • `lifecycle_status: true`: (Spec B7) mark an ENUM column whose
        //     values represent workflow state (a ticket goes open→closed,
        //     an application goes shortlisted→hired). Distinct from user-
        //     picked enums like priority or category. When true, create forms
        //     hide the field (using `default_value` to seed it); edit forms
        //     surface it as a status control. If a `status`-named field is
        //     genuinely user-picked (kanban card manual column), leave
        //     `lifecycle_status: false` — the name alone doesn't decide.
        {"name": "status", "type": "varchar", "not_null": true,
         "enum_values": [
           {"key": "open", "label": "Open"},
           {"key": "in_progress", "label": "In Progress"},
           {"key": "closed", "label": "Closed"}
         ],
         "default": "open"},
        {"name": "assigneeId", "type": "uuid", "not_null": false,
         "fk": {"table": "users", "column": "id"}, "label": "Assignee"},
        {"name": "basedAt", "type": "varchar", "not_null": false,
         "semantic_type": "city", "label": "Based at (Airport/City)"},
        {"name": "coverNote", "type": "text", "not_null": false,
         "semantic_type": "multiline"},
        {"name": "createdAt", "type": "timestamp", "not_null": true,
         "default": "now()", "lifecycle": "created_at"}
      ],
      "indexes": ["status", "assigneeId"]
    }
  ],
  "relations": [
    {"from": "TableA", "to": "TableB", "type": "many-to-one", "foreignKey": "table_b_id"}
  ],
  "pages": [
    {"route": "/resource", "name": "ResourceListPage", "entity": "Resource",
     "archetype": "list", "features": ["status-pipeline", "approval"],
     "description": "List with filters, search, pagination. Columns: name, status, created date. Actions: create new, view detail.",
     "actions": [
       {"label": "Approve", "workflow": "ResourceApprovalWorkflow", "kind": "row_action",
        "input_map": {"status": "status"}, "requires_record": true},
       {"label": "Reject",  "workflow": "ResourceApprovalWorkflow", "kind": "row_action",
        "input_map": {"status": "status"}, "requires_record": true}
     ]},
    {"route": "/resource/:id", "name": "ResourceDetailPage", "archetype": "detail", "features": [],
     "description": "View resource details with edit form. Fields: name, description, status dropdown, assigned user. Actions: save, delete, back to list."},
    {"route": "/resource/new", "name": "ResourceCreatePage", "archetype": "form", "features": [],
     "description": "Create form with validation. Fields: name (required), description, status, assigned user select.",
     "fields": [
       {"name": "name", "label": "Full Name", "required": true, "order": 1},
       {"name": "amount", "semanticType": "currency", "order": 2},
       {"name": "status", "enum": ["Open", "In Progress", "Closed"], "order": 3},
       {"name": "description", "semanticType": "multiline", "order": 4}
     ]},
    {"route": "/board", "name": "ResourceBoardPage", "entity": "Resource",
     "archetype": "kanban", "features": ["status-pipeline"],
     "description": "Kanban board grouped by status columns (Backlog, In Progress, Done). Cards show title, assignee avatar, due date. Drag to move between columns."},
    {"route": "/analytics", "name": "AnalyticsPage", "entity": null,
     "archetype": "report", "features": [],
     "description": "Charts and summary analytics: volume over time, breakdown by status, top performers. KPI tiles at top.",
     "widgets": [
       {"type": "stat", "entity": "Resource", "metric": {"fn": "count"}, "title": "Total Resources"},
       {"type": "stat", "entity": "Payment", "metric": {"fn": "sum", "field": "amount"}, "title": "Revenue"},
       {"type": "chart", "entity": "Resource", "groupBy": "status", "title": "By Status"},
       {"type": "table", "entity": "Resource", "limit": 5, "columns": ["name", "status"], "title": "Recent Resources"}
     ]},
    {"route": "/calendar", "name": "CalendarPage", "entity": "Event",
     "archetype": "calendar", "features": [],
     "description": "Month/week event grid showing scheduled events. Click day to create, click event to view details."},
    {"route": "/inbox", "name": "InboxPage", "entity": "Message",
     "archetype": "inbox", "features": [],
     "description": "Split-pane: message list on left, reading pane on right. Unread count badge, mark-as-read on open."}
  ],
  "components": [
    {"name": "ResourceTable", "file": "src/components/resources/ResourceTable.tsx", "description": "Data table with columns, sorting, row actions (edit, delete)"},
    {"name": "ResourceForm", "file": "src/components/resources/ResourceForm.tsx", "description": "Shared form component used by create and edit pages. Fields: name, description, status, assignee."},
    {"name": "StatsCard", "file": "src/components/dashboard/StatsCard.tsx", "description": "Dashboard stat card with icon, value, label, trend indicator"},
    {"name": "StatusBadge", "file": "src/components/shared/StatusBadge.tsx", "description": "Color-coded badge for status values (active, pending, completed, etc.)"}
  ],
  "layouts": [
    {"route": "/", "file": "src/app/layout.tsx", "description": "Root layout with SessionProvider, Inter font, globals.css"},
    {"route": "/(auth)", "file": "src/app/(auth)/layout.tsx", "description": "Centered auth layout for login/signup"},
    {"route": "/(dashboard)", "file": "src/app/(dashboard)/layout.tsx", "description": "App shell with Navbar at top, Sidebar on left, main content area"}
  ],
  "shared_components": [
    {"name": "Navbar", "file": "src/components/layout/Navbar.tsx", "description": "Top navigation with app logo, user menu (name, role, logout)"},
    {"name": "Sidebar", "file": "src/components/layout/Sidebar.tsx", "description": "Left sidebar with nav links to all pages, active state highlighting, collapsible"}
  ],
  "api_routes": [
    {"method": "GET", "path": "/api/resource", "description": "List resources with pagination, search query, status filter"},
    {"method": "POST", "path": "/api/resource", "description": "Create resource. Body: name, description, status. Validates with zod."},
    {"method": "GET", "path": "/api/resource/[id]", "description": "Get single resource by ID"},
    {"method": "PUT", "path": "/api/resource/[id]", "description": "Update resource. Body: partial fields. Returns updated record."},
    {"method": "DELETE", "path": "/api/resource/[id]", "description": "Delete resource by ID"}
  ],
  "workflows": [
    {
      "name": "WorkflowName",
      "trigger": "What initiates this workflow (user action, scheduled event, system event, status change, external trigger, etc.)",
      "description": "What this workflow accomplishes end-to-end and why it exists in the business context",

      // INPUTS — REQUIRED for every manual/user-triggered workflow.
      // These are the fields the trigger form must collect. Declaring them
      // here (instead of leaving the downstream deriver to guess from
      // `db_insert` fields) is what makes trigger forms complete.
      //
      // Rule: every column the workflow WRITES that is NOT computed from
      //   session (user.id), URL params, defaults, or a lookup on an
      //   already-supplied input, MUST appear as an input.
      // Example: ScheduleInterview writes an `interviews` row with
      //   {application_id, interviewer_id, scheduled_at, drive_id, location}.
      //   All 5 are inputs. `created_at` is default now(). `created_by` is
      //   session.user.id. Neither belongs in `inputs`.
      "inputs": [
        {"name": "applicationId", "type": "uuid", "required": true,
         "fk": {"table": "applications", "column": "id"}, "label": "Application"},
        {"name": "scheduledAt", "type": "timestamp", "required": true,
         "label": "Interview time"},
        {"name": "location", "type": "varchar", "required": false,
         "semantic_type": "city"}
      ],

      // PROCESS VARIABLES — the workflow's mutable scratchpad. Different
      // from `inputs` (which arrive at trigger time and don't change) and
      // from step outputs (scoped to the producing step). Declare any
      // value that:
      //   • a later step reads that isn't a trigger input or another
      //     step's output (e.g. `retryCount`, `approvalDecision`,
      //     `totalCost` computed across steps)
      //   • is written by a `set_variable` action
      //   • is promoted from a step output for later branches to read
      //
      // Skip when a workflow only reads its trigger inputs and step
      // outputs (many CRUD flows). If in doubt, declare it — an empty
      // `processVariables` array is fine.
      "processVariables": [
        {"name": "approvalDecision", "type": "string", "description": "Chosen by the approver"},
        {"name": "escalatedToId", "type": "uuid", "description": "Set when SLA breached"}
      ],
      "steps": [
        {"id": "trigger", "type": "trigger", "config": {"triggerType": "db_change", "entity": "Resource"}, "next": "review_gate"},
        {"id": "review_gate", "type": "exclusive_gateway", "config": {"condition": "priority == 'critical'"}, "branches": {"true": "manager_approval", "false": "auto_activate"}},
        {"id": "manager_approval", "type": "approval", "config": {"assigneeRole": "Manager"}, "next": "update_record"},
        {"id": "auto_activate", "type": "action", "config": {"actionType": "db_update", "table": "resources", "fields": ["status"], "where": {"id": "{{id}}"}}, "next": "update_record"},
        {"id": "update_record", "type": "action", "config": {"actionType": "db_update", "table": "resources", "fields": ["status"], "where": {"id": "{{id}}"}}, "next": "send_alert"},
        {"id": "send_alert", "type": "action", "config": {"actionType": "send_notification", "recipientRole": "Manager", "message": "Resource {{id}} outcome recorded"}, "next": "end"},
        {"id": "end", "type": "end"}
      ],
      "roles": {"role_in_workflow": "AppRole"},
      "conditions": ["Business rules that gate transitions between steps"],
      "error_handling": ["What happens when a step fails or is rejected"],
      "side_effects": ["Any secondary actions: notifications, audit logs, calculations, cascading updates, external integrations"]
    }
  ],
  "seed_data": "Detailed description: 1 admin user (admin@example.com/password123), 3 regular users, 15 resources with varied statuses, 5 categories, realistic names and dates",
  "actors": [
    {
      "name": "Admin",
      "role": "admin",
      "onboarding": {"source": "platform_org"},
      "responsibilities": ["Invite recruiters and interviewers", "Manage org settings"]
    },
    {
      "name": "Recruiter",
      "role": "recruiter",
      "onboarding": {"source": "invited_by", "invited_by": "Admin"},
      "responsibilities": ["Shortlist candidates", "Schedule interviews", "Manage recruitment drives"]
    },
    {
      "name": "Candidate",
      "role": "candidate",
      "onboarding": {"source": "self_signup", "gate": "public"},
      "responsibilities": ["Submit application", "Track application status", "Upload CV"]
    }
  ],

  // NAV — declare where each actor lands after login + what each sees in
  // their sidebar. This is what makes root-redirects role-aware and what
  // makes sidebars accurate WITHOUT the sync/derive/prune post-passes.
  //
  // `initialFor` — one entry per actor role. Route must be a non-auth
  //   route that appears in `pages[]`. This becomes app/page.tsx's
  //   session-aware redirect map. If a role is missing, DEFAULT_INITIAL
  //   catches it.
  // `sidebar` — one entry per role. Each `items` list is the exact
  //   left-nav for that actor, in order. Only include routes that role
  //   should see day-to-day; the app still has more routes than these,
  //   but they are reached through the visible ones. All items MUST be
  //   `pages[].route` values. Never list `/login` or `/signup` here.
  //
  // IA SHAPE RULES (right thing, right place, complete):
  //   1. JOIN TABLES ARE NOT SCREENS. A pure many-to-many join entity
  //      (two FKs + at most one attribute column, e.g. SessionSpeaker)
  //      NEVER gets its own page, route, or sidebar item. Manage the
  //      relationship inline on a parent's detail page (assign a
  //      speaker FROM the session page).
  //   2. DASHBOARDS/HOME NEVER GET CREATE FORMS. Only entity collection
  //      pages have a `/new` route.
  //   3. EVERY entity collection page you declare must be reachable from
  //      some role's sidebar (directly, or as a nested tab of a parent
  //      workspace) — a page nobody can navigate to does not exist.
  //   4. AGGREGATE-ROOT WORKSPACE: when one entity is the hub (most
  //      other entities FK into it — the Event in event management, the
  //      Project in project tracking), give it nested child routes
  //      (/events/[id]/sessions, /events/[id]/attendees) and treat its
  //      detail page as a workspace whose tabs are those children.
  //      Global registries (all speakers across events) can ALSO exist,
  //      but day-to-day work happens inside the hub.
  "nav": {
    "initialFor": {
      "admin":     "/dashboard",
      "recruiter": "/recruiter/dashboard",
      "candidate": "/profile/cv-upload"
    },
    "sidebar": [
      {"role": "admin",     "items": ["/dashboard", "/roles", "/drives", "/settings"]},
      {"role": "recruiter", "items": ["/recruiter/dashboard", "/drives", "/pipeline", "/notifications"]},
      {"role": "candidate", "items": ["/profile/cv-upload", "/roles", "/my-applications"]}
    ]
  },

  "access_control": {
    "roles": ["Admin", "Manager", "User"],
    "rules": ["Admin: full access to everything", "Manager: CRUD on own department resources, read-only on others", "User: CRUD on own records only, read access to shared resources"]
  },
  "api_strategy": {
    "Resource": {
      "crud": {
        "create":  { "engine": "data", "triggers_workflow": "ResourceApprovalWorkflow", "condition": "priority === 'critical'" },
        "read":    { "engine": "data" },
        "update":  { "engine": "data", "triggers_workflow": "ResourceStatusChangeWorkflow", "condition": "status changed" },
        "delete":  { "engine": "data" }
      },
      "workflow_actions": [
        {
          "action": "approve",
          "workflow": "ResourceApprovalWorkflow",
          "api": "POST /api/workflows/ResourceApprovalWorkflow/execute",
          "visible_when": { "field": "status", "equals": "pending_approval" },
          "ui_location": "detail_page",
          "trigger": "button:Approve",
          "on_success": "refresh + toast:Approved"
        },
        {
          "action": "reject",
          "workflow": "ResourceApprovalWorkflow",
          "api": "POST /api/workflows/ResourceApprovalWorkflow/execute",
          "visible_when": { "field": "status", "equals": "pending_approval" },
          "ui_location": "detail_page",
          "trigger": "button:Reject",
          "on_success": "refresh + toast:Rejected"
        }
      ]
    }
  },
  "user_journeys": [
    {
      "name": "Create and manage a resource",
      "actor": "User",
      "steps": [
        {"page": "/resources", "action": "Click 'New Resource' button", "next": "/resources/new"},
        {"page": "/resources/new", "action": "Fill form → Submit", "engine": "data", "api": "POST /api/data/resources", "on_success": "redirect:/resources + toast:Created", "on_error": "show validation errors"},
        {"page": "/resources", "action": "Click row in table", "next": "/resources/{id}"},
        {"page": "/resources/{id}", "action": "Click 'Edit' → modify fields → Save", "engine": "data", "api": "PUT /api/data/resources/{id}", "on_success": "refresh + toast:Updated"},
        {"page": "/resources/{id}", "action": "Click 'Delete' → confirm dialog", "engine": "data", "api": "DELETE /api/data/resources/{id}", "on_success": "redirect:/resources + toast:Deleted"}
      ]
    },
    {
      "name": "Approve a resource (workflow)",
      "actor": "Manager",
      "steps": [
        {"page": "/tasks/inbox", "action": "See pending approval task in inbox"},
        {"page": "/tasks/inbox", "action": "Expand task → review details"},
        {"page": "/tasks/inbox", "action": "Click Approve", "engine": "workflow", "api": "POST /api/workflows/ResourceApprovalWorkflow/execute", "on_success": "remove from inbox + toast:Approved"},
        {"page": "/resources/{id}", "action": "Or: Click Approve on detail page", "engine": "workflow", "api": "POST /api/workflows/ResourceApprovalWorkflow/execute", "on_success": "refresh + toast:Approved"}
      ]
    },
    {
      "name": "Dashboard overview",
      "actor": "User",
      "steps": [
        {"page": "/", "action": "View stat cards", "engine": "data", "api": "GET /api/data/{entity}/stats"},
        {"page": "/", "action": "Click stat card", "next": "/{entity}"},
        {"page": "/", "action": "Click quick action", "next": "/{entity}/new"}
      ]
    },
    {
      "name": "Authentication",
      "actor": "Anonymous",
      "steps": [
        {"page": "/login", "action": "Submit credentials", "api": "signIn('credentials')", "on_success": "redirect:/"},
        {"page": "/signup", "action": "Submit registration", "api": "POST /api/auth/signup", "on_success": "redirect:/login + toast:Account created"},
        {"page": "/*", "action": "Sign out", "api": "signOut()", "on_success": "redirect:/login"}
      ]
    }
  ],

  // ══════════════════════════════════════════════════════════════
  // IRF FOUR-AXIS TOPOLOGY — REQUIRED top-level fields.
  // Full vocab + rules in the "FOUR-AXIS TOPOLOGY" section below.
  // These MUST be emitted alongside the classic fields above.
  // ══════════════════════════════════════════════════════════════
  "app_shape": {
    "layout":    {"shell": "sidebar", "hero": "kpi-strip", "primaryInteraction": "dashboard", "density": "comfortable"},
    "auth":      {"surface": "route", "gating": "on-load"},
    "nav":       {"menu": "sidebar-links", "back": "history"},
    "workflows": {"executionMode": "await-with-progress"},
    "data":      {"readShape": "dashboard", "denormalization": "moderate"},
    "identity":  {"usageMode": "returning-personal"},
    "label":     "admin-back-office"
  },
  "archetypes": [
    {"name": "home", "recipe": "dashboard", "entities": ["order"], "routes": ["/"]}
  ],
  "industry": "ecommerce-admin",
  "runtime_context": ["push_notifications"],
  "coverage_verdict": {"status": "in_scope", "reason": "brief composes cleanly from the substrate"}
}
```

## API STRATEGY — PLANNER DECIDES WHICH ENGINE HANDLES EACH OPERATION

The `api_strategy` section declares, for EVERY entity, which engine handles each operation:

**Two engines:**
- `"engine": "data"` → Data Engine handles it (direct CRUD — validate, insert/update/delete, return)
- `"engine": "workflow"` → Workflow Engine handles it (multi-step business process — may pause for approval)

**Rules:**
- ALL basic CRUD (create, read, update, delete) uses `"engine": "data"`
- Data operations can TRIGGER workflows via `"triggers_workflow"` — the Data Engine does the CRUD,
  then emits an event that starts a workflow asynchronously
- Workflow actions (approve, reject, escalate, reassign) use `"engine": "workflow"` — these
  are NOT CRUD, they're business decisions that the Workflow Engine executes
- Each workflow_action must specify: which page it appears on (`ui_location`), when it's visible
  (`visible_when`), and what button triggers it (`trigger`)
- For every page whose entity has workflows, include an "actions" array of {label, workflow, kind}
  where label is the EXACT button text, workflow is one you declared in "workflows", and kind is
  "row_action" (a button repeated per list row) or "page_action". Pages with no actions use [].
  OPTIONALLY, each action may also carry `input_map` ({formFieldName: entityColumn} — the fields the
  button/form hands to the workflow, keyed by form field, valued by the workflow's real input column)
  and `requires_record` (true when the action operates on an existing record, e.g. an approve/update/
  delete on a specific row; false for a create). These two keys are OPTIONAL hints — omit them when
  unsure; a post-generation pass derives/validates them against the real workflows.
- For every form/create/edit page, OPTIONALLY author a `fields` array — a per-field form spec the
  deterministic builder renders VERBATIM. Each entry is `{name, semanticType?, label?, required?,
  enum?, order?}` where `name` is the entity column, `semanticType` ∈ currency/percent/email/phone/
  url/multiline (currency renders a plain number with a `$`, no stepper; multiline a textarea),
  `enum` lists the literal Select option values, and `order` (int) sets field order. Do NOT specify
  a UI control (Input/Select/DatePicker/…) — the control type is DERIVED AUTOMATICALLY from the real
  SQL column type + the semanticType hint (a foreign key → relational Select, an enum → Select, a
  date → DatePicker, a number → NumberInput, etc.). Emit ONLY the judgment the schema can't derive —
  you may omit a field entirely (the registry backfills every omitted column) or omit any key on a
  field. The registry VALIDATES each field and DROPS one naming a non-existent column. Never invent
  columns.
- For every dashboard/report page, author a `widgets` array — the JUDGMENT a deterministic
  builder can't derive (which entity to count, what to group a chart by, which table to list).
  A new deterministic dashboard builder renders these from the registry, so DON'T describe
  dashboard data only in prose. Each widget is one of:
  `{type: "stat", entity, metric: {fn: count|sum|avg|min|max, field?, filter?}, title}` (a KPI
  tile — `field` required for non-count fns), `{type: "chart", entity, groupBy, agg?: {fn, field?},
  bucket?: day|week|month, filter?, title}` (a grouped series — `bucket` only when `groupBy` is a
  date column), or `{type: "table", entity, filter?, limit?, columns?, title}` (a recent-rows list).
  `entity` is a REAL entity name and every `field`/`groupBy`/`filter`/`columns` names a REAL column
  on it — the registry VALIDATES each widget and DROPS any referencing a non-existent entity/column.
  Never invent entities or columns.

**Common patterns:**
- Simple entity (no workflows): all CRUD is `"engine": "data"`, no workflow_actions
- Entity with approval: create is `"engine": "data"` + `"triggers_workflow"`, then approve/reject
  are `"engine": "workflow"` with `"visible_when": {"field": "status", "equals": "pending_approval"}`
- Entity with status machine: update is `"engine": "data"` + `"triggers_workflow"` with
  `"condition": "status changed"` — workflow handles side effects of the transition

For EVERY entity in `api_strategy`:
1. Define all CRUD operations with their engine
2. If any CRUD triggers a workflow, specify `triggers_workflow` + `condition`
3. List all workflow_actions with their UI binding (where, when, what button)

## USER JOURNEYS — BUILT ON API STRATEGY

The `user_journeys` section defines HOW users interact with the app step-by-step.
Each step must specify `"engine": "data"` or `"engine": "workflow"` so downstream agents know
which API endpoint to call.

**Rules for user_journeys:**
- Include a CRUD journey for every PRIMARY entity (supporting/lookup entities are reached inline through a primary entity's journey, not their own)
- Include a WORKFLOW journey for every entity that has workflow_actions in api_strategy
- Include the dashboard journey showing stat cards → entity list navigation
- Include the auth journey (login, signup, logout)
- For entities with workflows: include the workflow journey (submit → approval → notification)
- For cross-entity relationships: include cross-navigation (e.g., "View owner's pets", "Schedule appointment for pet")
- Each step MUST specify: which page, what action, which API (if any), what happens on success/error
- Every button, link, form submit, and redirect in the app should trace back to a journey step

A plan without user_journeys is INCOMPLETE. The generated app will have broken navigation,
missing buttons, and disconnected pages.

4. CONFIRM: Present the plan summary to the user and ask for approval.
   Output the plan JSON wrapped in a code block with the marker: ```plan-json

## Access Control Inference

When org context is provided, AUTOMATICALLY infer the `access_control` section:
- Map org roles to app roles (e.g., "HR Manager" → admin for HR modules, "Employee" → user)
- Sensitive fields (salary, SSN, personal info) → restrict to department heads / HR roles
- Record scope: department-owned records → department members can view, only owners/managers can edit
- Approval workflows: route to managers based on reporting lines
- If the org has departments, add department-based record scoping by default
- If the org has teams, scope team-specific records to team members

## MANDATORY: `actors` block — who uses this app and how they get in

Before anything else, list every human actor that will operate the running app
under `actors`. Actors are INDUSTRY-SPECIFIC — pick the real vocabulary of the
domain: a recruitment app has Candidate/Recruiter/Interviewer/Admin; a hospital
app has Patient/Doctor/Nurse/Admin; a marketplace has Buyer/Seller/Admin. Do
NOT emit generic User/Manager/Admin for a domain that has richer real actors.

Every actor gets a mandatory `onboarding.source`:

  * `"self_signup"` — the actor creates their own account via the public
    signup page (e.g. Candidate, Buyer). `gate: "public"` when the signup
    is open to anyone; `gate: "verified_email"` etc. for controlled variants.
  * `"invited_by"` — the actor is provisioned by another actor from inside
    the app. Set `invited_by: "<OtherActor.name>"`. This drives an "Invite
    {Actor}" workflow + form in the generated app (e.g. Admin invites
    Recruiter; Recruiter invites Interviewer).
  * `"platform_org"` — the actor already exists in the Forge organization
    that owns this app. No signup, no invite — the app reads them from the
    org user pool (e.g. the org owner is auto-mapped to the Admin role).

Downstream generation consumes `actors` verbatim:
  * `User.role` enum values come from `actors[].role` (not the
    `access_control` list, which is now derived FROM actors).
  * Signup page appears IFF ≥1 actor has `onboarding.source ==
    "self_signup"`. Invite-only apps get no public signup.
  * Pages that only one actor owns (list/create forms for entities that
    actor manages) get `visibleTo: [actor.role]` in nav-flow.

## MANDATORY: Persist actors as a User entity (RBAC)

When the app has roles that own or are assigned to records (e.g. Recruiter,
Assessor, Manager, Reviewer), model the actor as a PERSISTED, FK-targetable
`User` data_model mapped to the reserved table `users`, carrying a `role` column
whose enum values are the LOWER-CASED `actors[].role` values (plus id/name/email).
Every actor FK column on another entity (`assignedAssessorId`, `assessorId`,
`assigneeId`, `reviewerId`, …) MUST be declared as a uuid field AND named in
`relations` with `{"from":"<Entity>","to":"User","foreignKey":"<column>"}` so it
references `users.id`. Do NOT leave an actor FK as a bare uuid with no relation.

```json
{"name": "User", "table": "users",
 "fields": [
   {"name": "id", "type": "uuid", "primaryKey": true},
   {"name": "name", "type": "varchar"},
   {"name": "email", "type": "varchar", "nullable": false},
   {"name": "role", "type": "varchar", "enum_values": ["Recruiter", "Assessor", "HiringManager"]}
 ]}
```

Include a `field_access` section in the plan for any sensitive or restricted fields:
```json
"field_access": [
  {"model": "Employee", "field": "salary", "restricted_to": ["HR Manager", "Admin"]},
  {"model": "Employee", "field": "ssn", "restricted_to": ["HR Manager"]}
]
```

## MANDATORY: Workflow Tasks Data Model

If the plan has ANY workflows with approval or user_task steps, you MUST include this entity
in data_models (the schema agent will create the table, the engine uses it for persistence):

```json
{
  "name": "WorkflowTask",
  "fields": [
    {"name": "id", "type": "uuid", "primaryKey": true},
    {"name": "workflowId", "type": "varchar(100)", "nullable": false, "description": "Which workflow definition"},
    {"name": "workflowInstanceId", "type": "uuid", "nullable": false, "description": "Which execution instance"},
    {"name": "nodeId", "type": "varchar(100)", "nullable": false, "description": "Which node is paused"},
    {"name": "nodeLabel", "type": "varchar(255)"},
    {"name": "taskType", "type": "varchar(50)", "description": "approval | user_task"},
    {"name": "status", "type": "varchar(50)", "default": "pending", "description": "pending | completed | rejected | expired"},
    {"name": "assigneeId", "type": "uuid", "nullable": true, "description": "Specific user assigned"},
    {"name": "assigneeRole", "type": "varchar(100)", "nullable": true, "description": "Role-based assignment (any user with this role can act)"},
    {"name": "assigneeGroupId", "type": "uuid", "nullable": true, "description": "Group/department assignment"},
    {"name": "entityType", "type": "varchar(100)", "description": "Which entity this task is about (Patient, Order, etc.)"},
    {"name": "entityId", "type": "uuid", "description": "ID of the entity being acted on"},
    {"name": "formData", "type": "jsonb", "description": "Pre-filled form values from process variables"},
    {"name": "formBinding", "type": "jsonb", "description": "Form field definitions from the workflow node"},
    {"name": "processVariables", "type": "jsonb", "description": "Snapshot of process variables at pause time"},
    {"name": "completedBy", "type": "uuid", "nullable": true},
    {"name": "completedAt", "type": "timestamp", "nullable": true},
    {"name": "decision", "type": "varchar(50)", "nullable": true, "description": "approved | rejected (for approval tasks)"},
    {"name": "responseData", "type": "jsonb", "nullable": true, "description": "Data submitted by the user"},
    {"name": "dueAt", "type": "timestamp", "nullable": true},
    {"name": "createdAt", "type": "timestamp", "default": "now()"}
  ]
}
```

Also include a `/tasks` page in the plan that shows the user's pending tasks.

## MANDATORY: Workflow Assignment Rules

Each workflow with approval/user_task steps MUST specify WHO gets the task:

```json
{
  "name": "LeaveApprovalWorkflow",
  "steps": [
    {
      "id": "manager_approval",
      "type": "approval",
      "config": {"assigneeRole": "Manager"},
      "assignment": {
        "strategy": "reporting_manager",
        "description": "Assigned to the employee's direct manager",
        "fallback": "role:HR Manager"
      },
      "next": "end"
    }
  ]
}
```

Assignment strategies:
- `"role:RoleName"` — any user with that role (e.g., "role:Doctor", "role:Admin")
- `"reporting_manager"` — the entity owner's direct manager
- `"department_head"` — head of the relevant department
- `"entity_field:fieldName"` — assigned to the user ID in a specific entity field (e.g., "entity_field:primaryPhysicianId")
- `"group:GroupName"` — any member of that group/team
- `"creator"` — the user who created the entity
- `"round_robin:RoleName"` — rotate among users with that role

## Plan Completeness Rules
- Classify each entity as PRIMARY (a core object users work with directly) or SUPPORTING (a lookup, reference, junction, or config table rarely edited on its own). PRIMARY entities get a list page, a detail/edit page, and a create page. SUPPORTING entities do NOT need their own page triad — they are created/selected INLINE inside a primary entity's form (dropdowns, nested forms) or managed in a lightweight settings area. Do NOT manufacture full CRUD screens for every table — match pages to how the domain is actually used. (All entities still get full CRUD API routes so inline selection/creation works.)
- List each PRIMARY page with route, name, archetype, and a ONE-LINE description (key fields + main action). A single concise phrase — NOT a paragraph.
- Do NOT enumerate every component. List only the few KEY shared/reusable components (e.g. a shared form or table); the component agent derives the rest from the pages and entities.
- `layouts`: just the auth shell + the dashboard shell. `shared_components`: Navbar, Sidebar.
- The dashboard page: name the few domain stats/widgets it shows, in one line.
- If workflows exist: include WorkflowTask entity, /tasks page, and assignment rules per workflow step
- Every PRIMARY entity MUST have a user_journey defining its CRUD flow (create→list→detail→edit→delete). Supporting entities don't need their own journey — their create/select happens inside a primary entity's journey.
- user_journeys MUST include: dashboard journey, auth journey, and cross-entity navigations
- A plan without user_journeys is REJECTED — the contract agent cannot generate navigation-flow.json without it

## Workflow Planning — Think Like a Domain Expert

Workflows are the CORE of any real application. Do NOT produce shallow or generic workflows.
Think deeply about the specific industry and domain the user is building for. Every domain has
its own unique business processes — a hospital, a logistics company, a law firm, a restaurant,
a manufacturing plant, an e-commerce platform all have fundamentally different workflows.

YOUR JOB: Analyze the user's requirements and infer ALL the workflows that a real-world
application in that domain would need. You are not limited to approvals or CRUD — think about:
- The complete lifecycle of every entity (creation → active use → archival/completion)
- State machines: what states can each entity be in? What transitions are valid? Who can trigger them?
- Cross-entity orchestration: when something happens to entity A, what needs to happen to B, C, D?
- Scheduled/recurring processes: daily rollups, expiration checks, reminder triggers, periodic reports
- Exception handling: what happens when things go wrong? cancellations, reversals, disputes, escalations
- Multi-party interactions: handoffs between roles, parallel approvals, conditional routing
- Calculations and derived data: running totals, aggregations, scoring, ranking, threshold alerts
- Integration points: emails, notifications, file generation, external API calls

### Workflow "steps" — an EXPLICIT connected graph (connectivity is REQUIRED)

Each workflow's `steps` is a list of node objects forming a connected graph from a trigger to a
single end. Every step has an `id`, a `type`, a `config`, and its flow connectivity (`next` or
`branches`):

```
{"id": "unique_snake_case_id", "type": <node type>, "config": { ... }, "next": "<id of the next step>"}
```

Node `type` and its `config`:
- `"trigger"` — the entry. `config`: `{"triggerType": "manual"|"api_event"|"schedule"|"db_change", "entity": "<Entity>"}`
- `"action"` — an automated operation; put the operation in `config.actionType`:
  - `db_insert`/`db_update`/`db_delete`/`db_query` → `config: {"actionType":"db_insert","table":"<sql_table>","fields":["col",...]}` (add `"where":{...}` for update/delete/query)
  - **STATE-TRANSITION db_update (button sets a status/lifecycle column) — author the CONCRETE target value.** A button like "Approve"/"Confirm Pickup"/"Restore Availability" sets a machine-state column to a SPECIFIC value that only YOU know. Emit a `values` map with the LITERAL, NOT a self-referential `{{status}}` (which no dispatch supplies → wipes the column to NULL) and NOT the field name. Use the literal string `"CURRENT_TIMESTAMP"` for a lifecycle timestamp. Example — an "Approve Request" button: `config: {"actionType":"db_update","table":"requests","where":{"id":"{{id}}"},"values":{"status":"Approved","approvedAt":"CURRENT_TIMESTAMP"}}`; a "Restore Availability" button: `values:{"availabilityStatus":"Available"}`. Keep `{{formField}}` ONLY for values a user actually types (e.g. `"reviewerNotes":"{{reviewerNotes}}"`).
  - `send_notification`/`send_email` → `config: {"actionType":"send_notification","recipientRole":"<role>","message":"..."}` (email also: `"subject"`,`"body"`)
  - `ai_extract` → `config: {"actionType":"ai_extract","prompt":"<what to extract>","fields":["col",...]}` (add `"aiFileRef":"{{input.fileId}}"` when reading an uploaded document)
  - `ai_classify`/`ai_generate`/`ai_decide` → `config: {"actionType":"ai_decide","prompt":"..."}`
  - `ocr_document` → `config: {"actionType":"ocr_document","ocrFileRef":"{{input}}"}` (add `"ocrLanguage":"en"` or `"ocrPages":[1,2]` when the sidecar needs a hint). Outputs `text`, `blocks[]`, `pageCount`, `confidence` — pipe `text` into a follow-up `db_insert` to persist. Use for BULK / on-prem OCR on typed or handwritten documents (bank statements, checks, receipts, forms). Prefer `ai_extract` when the doc has complex layout AND you need semantic reasoning to pull specific fields.
  - `generate_document` → `config: {"actionType":"generate_document","template":"<template_id>"}`
  - `http_call` → `config: {"actionType":"http_call","url":"https://...","method":"POST"}`
- `"exclusive_gateway"` — a branch. `config: {"condition":"<boolean expression over prior variables, e.g. amount > 1000>"}`. A gateway has NO `next`; instead it has `"branches": {"true":"<id>","false":"<id>"}`.
- `"approval"`/`"user_task"` — a human step that blocks. `config: {"assigneeRole":"<role>"}`
- `"wait"` — a pause. `config: {"durationHours": <n>}` or `{"untilEvent":"..."}`
- `"end"` — the single terminal. No `config`, no `next`.

Aliases the translator also accepts as `type` values (map to the shapes above): `condition`
(→ exclusive_gateway), `approval`/`assignment`/`task_pool` (→ human step), `escalation`
(→ human step), `decision` (→ gateway with rules). PREFER the primary types above; whatever
`type` you use, the connectivity rules below still apply.

CONNECTIVITY IS MANDATORY:
- Every non-gateway, non-end step MUST have a `"next"` = another step's `id`.
- Every gateway MUST have `"branches":{"true":<id>,"false":<id>}` and NO `"next"`.
- Terminal paths point `"next":"end"`. Include exactly one `{"id":"end","type":"end"}`.
- The graph MUST be connected from the trigger and reach `end` on every path. Do NOT emit steps
  without `next`/`branches` — an unconnected step list is invalid.

Example — a real branching workflow:
```
"steps": [
  {"id":"trigger","type":"trigger","config":{"triggerType":"db_change","entity":"Applicant"},"next":"extract_cv"},
  {"id":"extract_cv","type":"action","config":{"actionType":"ai_extract","prompt":"Extract first name, last name, email, phone from the uploaded CV.","fields":["firstName","lastName","email","phone"]},"next":"save_applicant"},
  {"id":"save_applicant","type":"action","config":{"actionType":"db_insert","table":"applicants","fields":["firstName","lastName","email","phone"]},"next":"score_gate"},
  {"id":"score_gate","type":"exclusive_gateway","config":{"condition":"aiScore >= 70"},"branches":{"true":"notify_recruiter","false":"mark_rejected"}},
  {"id":"notify_recruiter","type":"action","config":{"actionType":"send_notification","recipientRole":"recruiter","message":"Qualified applicant {{firstName}} {{lastName}}"},"next":"end"},
  {"id":"mark_rejected","type":"action","config":{"actionType":"db_update","table":"applicants","where":{"id":"{{id}}"},"values":{"status":"Rejected","rejectedAt":"CURRENT_TIMESTAMP"}},"next":"end"},
  {"id":"end","type":"end"}
]
```

For DOCUMENT-INTAKE apps (upload a CV/resume/invoice/form → the system reads it): use an
`ai_extract` action step that reads the uploaded file and fills the target entity's columns,
followed by a `db_insert` action step that persists them (see the example above).

Use the MOST SPECIFIC type/actionType for each step. For example:
- "Validate survey fields" → `exclusive_gateway` (a condition, not a db action)
- "Manager approves survey" → `approval` (not a plain user_task)
- "Send confirmation email" → `action` with `actionType: "send_email"` (not send_notification)
- "Calculate response statistics" → `action` with `actionType: "db_query"` (compute/aggregate)
- "AI categorizes open-ended responses" → `action` with `actionType: "ai_classify"`
- "Wait for response deadline" → `wait`
- "Escalate overdue reviews" → a human step (`approval`/`user_task`) for the higher authority

DO NOT use generic names. Aim for 8-15 steps with diverse types — a good workflow has a trigger,
gateways, approvals, actions, notifications, and a single `end`.

For EACH workflow:
- List EVERY step with `id`, `type`, `config`, and its `next`/`branches` connectivity
- Specify which roles participate and what permissions each step requires
- Define the conditions/business rules that gate transitions between steps
- Include error handling — what happens on failure, rejection, timeout, or invalid state
- List all side effects — the secondary actions that make the workflow complete
- Use at least 8 steps per workflow — real workflows are not trivial
- Use diverse node types — a good workflow has conditions, approvals, actions, and notifications

DO NOT limit the number of workflows or steps. Real applications have many workflows with many steps.
A leave management system alone might have: leave request flow, approval chain, balance calculation,
accrual processing, carry-forward rules, cancellation flow, team calendar sync, manager delegation,
holiday calendar management, policy enforcement. Think at this level of depth for ANY domain.

## Workflow UI Pages — REQUIRED when workflows exist

When the plan has workflows, you MUST include these additional pages and components:

### Pages (add to `pages` array):
- `{"route": "/workflows", "name": "WorkflowsPage", "description": "List all workflow types with status counts (active, completed). Each workflow shows name, description, trigger, step count. Click to view instances."}`
- `{"route": "/workflows/:id", "name": "WorkflowDetailPage", "description": "View workflow instances. Table showing: instance ID, status (running/completed/failed), started by, started at, current step. Click row to see step progress."}`
- `{"route": "/tasks", "name": "TaskInboxPage", "description": "User's assigned tasks. Table: task name, workflow name, status, due date, assigned at. Click to open task. Filter by status (pending/completed)."}`

### Components (add to `components` array):
- `{"name": "WorkflowCard", "file": "src/components/workflows/WorkflowCard.tsx", "description": "Card showing workflow name, description, active instance count, completion rate. Links to /workflows/:id."}`
- `{"name": "WorkflowStepTracker", "file": "src/components/workflows/WorkflowStepTracker.tsx", "description": "Horizontal step progress bar showing workflow steps, current step highlighted, completed steps checked."}`
- `{"name": "TaskCard", "file": "src/components/workflows/TaskCard.tsx", "description": "Task inbox card with task name, workflow context, due date, action buttons (Complete, Reassign)."}`

### API Routes (add to `api_routes` array):
- `{"method": "GET", "path": "/api/workflows", "description": "List workflow definitions with instance counts"}`
- `{"method": "GET", "path": "/api/workflows/[id]/instances", "description": "List instances of a specific workflow"}`
- `{"method": "GET", "path": "/api/tasks", "description": "List tasks assigned to current user, filterable by status"}`
- `{"method": "POST", "path": "/api/tasks/[id]/complete", "description": "Complete a task with output data"}`

These pages make workflows visible and actionable in the UI. Without them, workflows exist only as backend logic that users can never see or interact with.

## Scaling Rules
- Scale the plan to match the complexity of the request — no artificial limits on models, pages, or workflows
- For complex apps: cover the key entities, primary pages, and workflows — but stay LEAN and concise (one-line descriptions). Don't pad with exhaustive component lists; downstream agents elaborate.
- Always include a Dashboard page that aggregates key metrics from all entities
- Always include seed data so the app works immediately on preview
- Use PostgreSQL-native types (uuid, varchar, timestamp, jsonb, etc.). For a
  currency amount use `type: "money"` — the schema builder emits a decimal(19,4)
  amount plus a sibling `<field>_currency` char(3) column (defaults to USD; set
  `defaultCurrency: "EUR"` etc. to override).
- Every table needs: id (serial primary key), created_at (timestamp), updated_at (timestamp)
- Every relation SHOULD name its `foreignKey` — the exact FK column on the "from"
  entity (e.g. {"from":"Appointment","to":"Staff","foreignKey":"vetId"}). Also
  declare that column on the entity's `fields` (a uuid). Naming the FK column lets
  the schema builder emit a real Postgres foreign-key constraint, not a loose uuid.
- For apps with 5+ entities, include a settings/admin page
"""

PLANNER_SYSTEM_PROMPT = PLANNER_SYSTEM_PROMPT + "\n\n" + (
    "DESIGN THE APP — don't make every page a list. For each page pick the "
    "`archetype` that fits its purpose, and add `features` that fit the entity. "
    "Prefer these catalog names (others are allowed but will be normalized):\n"
    + catalog_for_prompt()
)

PLANNER_SYSTEM_PROMPT = PLANNER_SYSTEM_PROMPT + "\n\n" + r"""
## MECHANICAL STRINGS — do NOT author
These strings are computed at build time from the entity name via
`services.text_templates`. Authoring them yourself risks pluralization typos
("No plant batchs yet." from "batch"+"s") that the deterministic templates
avoid ("No plant batches yet.").

Do NOT populate:
  * `emptyStateText` on Tables / DataGrids / List / DescriptionList / Card
  * The `title` / `message` of an `EmptyState` component when it says "No X yet."
  * Standard button labels: Create X / Edit X / Delete X / Save changes / Cancel
  * Column headers on Tables (derived from field names)

DO author:
  * Page and section titles that carry domain meaning
  * Description / helperText / tooltip prose
  * Bespoke empty states with a real message ("You're all caught up — nothing to review.")
  * Any button whose action isn't standard CRUD ("Confirm Pickup", "Approve", "Schedule Interview")
"""

PLANNER_SYSTEM_PROMPT = PLANNER_SYSTEM_PROMPT + "\n\n" + r"""
## COMMERCE (shopping cart)
When the brief says customers can buy/sell/order (words like "sell",
"buy", "purchase", "cart", "checkout", "storefront", "marketplace",
"shop", "e-commerce", "storefront"):

- Mark the ONE saleable entity with `"commerce": true` in `entities` — usually
  `Product`, `Item`, `Listing`, or the domain equivalent (e.g. `Plant` for a
  nursery, `Room` for a hotel booking site). The commerce flag is set on the
  entity, not on individual pages.
- Do NOT invent `Cart`, `CartItem`, `Order`, `OrderItem`, or checkout entities.
  The runtime already provides a shopping-cart primitive: a `forge_cart` table,
  `/api/cart/*` routes, and `AddToCart` / `CartBadge` / `CartPage` library
  components are auto-wired for any entity flagged `commerce: true`. The
  `/cart` page is auto-generated; you don't need to list it.
- Do author an `Order` entity ONLY if the app needs persistent order history
  visible to users beyond the cart (e.g. "customers see their past orders").
  In that case, add a workflow triggered by the `cart.checkout` event that
  inserts an Order row; the runtime fires that event on checkout.
- Payment is NOT built in. Model payment method as a plain text/enum field on
  the Order (e.g. "Cash on delivery", "Invoice"), not as an external gateway.
"""

PLANNER_SYSTEM_PROMPT = PLANNER_SYSTEM_PROMPT + "\n\n" + r"""
## COMPUTATIONAL (standalone tool — no persistence)

When the brief describes a pure input→formula→output tool with no data to
store, no accounts, no records to browse — a calculator, converter,
estimator, quiz-scorer, tip calculator, EMI/loan calculator, BMI, unit
converter, currency converter — plan it as a COMPUTATIONAL app:

- `entities: []` — no persistence. Do NOT invent an `Entry` / `Calculation`
  entity to log every run; the tool is stateless.
- `relations: []`, `workflows: []`, `api_routes: []` — none of these apply.
- `actors`: exactly one anonymous `visitor` actor, `access: "anon"`, no
  signup / no login required. Wrap the app in the smallest possible
  auth-free shell.
- `pages`: usually ONE page with `archetype: "computational"`. Multi-tool
  hubs (e.g. "loan + tip + BMI calculators together") get one
  `computational` page per tool + a simple landing page.

The page delivers its behaviour through the FIELD-INTERACTION runtime, not
through workflows or API routes. Describe the formula in plain English in
the page's `description` — the page schema author will translate it into
`interaction.computed` on the result field and/or `onClick:{kind:"compute"}`
on an equals button. Do NOT try to author the formula literals here.

EXAMPLE — an EMI (loan) calculator:
```
{
  "archetype": "computational",
  "actors": [{"name": "visitor", "access": "anon"}],
  "entities": [], "relations": [], "workflows": [], "api_routes": [],
  "pages": [{
    "route": "/",
    "name": "EMI Calculator",
    "archetype": "computational",
    "description": "Given a loan principal, an annual interest rate, and a
      tenure in months, show the monthly EMI live as the user types.
      Formula: EMI = P * r * (1+r)^n / ((1+r)^n - 1), where r is the monthly
      rate (annualRate / 12 / 100) and n is tenure in months. Display the
      result in the local currency."
  }]
}
```

Formula-writer tips for downstream authors (helps you shape the description
so the page author has enough to compose):
- Available helpers: sum, min, max, avg, count, round, ceil, floor, abs,
  pow, sqrt, percent, clamp, ifElse, age, yearsBetween, formatCurrency,
  formatNumber.
- Reactive by default — the result field recomputes on every keystroke
  in an input the formula references.
- Only introduce an explicit "Calculate" button when the UX truly needs a
  gate (heavy computation, or a keypad-style equals key).
"""

# Authoritative workflow-node vocabulary, auto-derived from the runtime types +
# handlers (single source of truth — never drifts from what the engine executes).
PLANNER_SYSTEM_PROMPT = PLANNER_SYSTEM_PROMPT + "\n\n" + format_node_catalog()


# ── Spec C Slice 6 — component-variety catalog injection ──
# The library has 100+ components; without an explicit catalog the LLM
# reaches for the same 20 (Table, Card, Stat, Button, ...). This block
# lists every registered component with a purpose + USE/NOT hint the
# planner can reason from. Same discipline as format_node_catalog above.
# Flag-gated (default off) — soaks quietly until we're confident the
# extra prompt weight doesn't degrade other emissions.
def _polish_variety_prompt() -> str:
    import os as _os
    if _os.getenv("FORGE_POLISH_VARIETY", "0").strip().lower() not in (
        "1", "true", "yes", "on",
    ):
        return ""
    try:
        from services.library_manifest import (
            load_component_catalog,
            enrich_with_purposes,
            render_catalog_for_prompt,
        )
        catalog = enrich_with_purposes(load_component_catalog())
        rendered = render_catalog_for_prompt(catalog)
    except Exception as exc:  # noqa: BLE001
        # Missing manifest / read error — silently skip. Planner keeps
        # its existing prompt; this is additive polish, not correctness.
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "[c6] library manifest inject failed, skipping: %s", exc,
        )
        return ""
    return (
        "\n\n## COMPONENT VARIETY — pick from the FULL library\n\n"
        "For each page + widget, pick the component that best fits its purpose. "
        "Don't default to Table just because the data is rows-and-columns — a "
        "Kanban, ActivityFeed, ApprovalStepper, Calendar, ResourceTimeline, "
        "SplitArc, Gauge, Heatmap, DescriptionList, Stat, or Chart is often "
        "the right answer. USE hints below are non-binding; NOT hints are.\n\n"
        f"{rendered}"
    )


PLANNER_SYSTEM_PROMPT = PLANNER_SYSTEM_PROMPT + _polish_variety_prompt()


# ── Spec D Wave 1 — page.ux_hint injection ──
# Wave 1 additive scaffolding for the migration off
# ``services/domain_ux_specs.py``'s hardcoded per-industry playbook. The
# planner may attach a ``ux_hint`` block per page describing what the
# page SHOULD showcase (hero fields, key widgets, empty-state copy,
# information hierarchy). Downstream page-builders will prefer this
# hint over the domain playbook when the consumer-side migration lands
# in a later commit. For now, we author it; nobody reads it yet.
PLANNER_SYSTEM_PROMPT = PLANNER_SYSTEM_PROMPT + "\n\n" + r"""
## PAGE UX HINT (optional) — replaces hardcoded per-industry playbook

Every page MAY carry an optional ``ux_hint`` block that tells the
downstream page-builder what THIS page (not the generic archetype)
should showcase. When absent, the page-builder falls back to the
domain-agnostic archetype defaults. When present, the page-builder
prefers your hint. Never invent a hint that fights the archetype —
if a page is a form, don't hint at kanban columns.

Shape (every field optional):
```
{
  "hero_fields": ["candidate_name", "role", "stage"],
  "key_widgets": ["timeline", "notes-thread"],
  "empty_state": "No applications yet — invite candidates to apply.",
  "info_hierarchy": "candidate → role → status → activity"
}
```

Field meanings:
- ``hero_fields`` (list[str], ≤6): the 1-6 most important entity fields
  the page should surface first (page title, dashboard tiles, table
  first columns, detail-page hero block).
- ``key_widgets`` (list[str], ≤5): non-CRUD UI patterns the page needs
  ("timeline", "notes-thread", "activity-feed", "chat-composer"). The
  page-builder maps these to real library components.
- ``empty_state`` (str, ≤160): domain-tuned empty message. Beats the
  generic "No X yet." Only author when the domain gives a better line.
- ``info_hierarchy`` (str, ≤80): one-line description of the reading
  order — the page-builder uses it to decide grouping / sectioning.

Only author fields that add value beyond archetype defaults. A bare
``list`` page rarely needs a ux_hint — its archetype IS the hint. A
CRM ``detail`` page for a Candidate benefits from all 4.
"""

# ── Spec E Wave 3 — advanced UX patterns (planner emission blocks) ──
# Five new optional per-page / per-journey emissions the deterministic
# post-gen passes turn into concrete schema. Each block is silently
# dropped by the plan normalizer if malformed, so under-authoring costs
# nothing. Only author when the page ACTUALLY benefits — the defaults
# are already sensible; a bare list page rarely needs a filter_builder.
PLANNER_SYSTEM_PROMPT = PLANNER_SYSTEM_PROMPT + "\n\n" + r"""
## ADVANCED UX PATTERNS (Spec E Wave 3, all optional)

Five per-page / per-journey emissions let you declare high-touch UX
patterns the deterministic passes render into concrete schema. Author
each ONLY when it clearly beats the archetype default.

### 1. Multi-step wizard — `page.wizard`

Emit when a workflow has many inputs (>6 fields) OR when the
workflow branches on user decisions (approval flows, guided
enrollment). Splits the form into digestible steps + a review pane.

```
"wizard": {
  "steps": [
    {"id": "personal",   "title": "Personal Info",
     "fields": ["full_name", "email", "phone"]},
    {"id": "documents",  "title": "Documents",
     "fields": ["cv", "id_document"]},
    {"id": "confirm",    "title": "Confirm",
     "fields": ["terms_agreed"],
     "nextIf": "terms_agreed"}
  ]
}
```

### 2. Inline table editing — `page.list.editable_columns`

Emit on a list page when the user's mental model is "spreadsheet"
(rate cards, inventory levels, priority labels). Named columns
become click-to-edit cells with a Save-all toolbar.

```
"list": {
  "editable_columns": ["price", "stock_level", "priority"]
}
```

### 3. Master-detail split — `page.layout: "master_detail"`

Emit when the app's core interaction is "browse a list, work in the
detail". Common for CRMs, ticket queues, message inboxes. The
`detail_route` is the sibling detail page's route.

```
"layout": "master_detail",
"list": {
  "detail_route": "/tickets/:id"
}
```

### 4. Filter query builder — `page.list.filter_fields`

Emit when a list page needs a rich filter (>3 candidate fields,
mixed types, saved views). Simple search boxes cover the rest.

```
"list": {
  "filter_fields": [
    {"name": "status", "type": "enum",
     "operators": ["eq", "neq"]},
    {"name": "amount", "type": "number"},
    {"name": "opened_at", "type": "date"}
  ]
}
```

### 5. Onboarding tour — `journey.onboarding`

Emit when a role needs a first-run guided tour. Each step points at
a CSS selector on a page. Dismissal is persisted per-user.

```
"journey": {
  "onboarding": {
    "steps": [
      {"page": "/dashboard",
       "target_selector": "[data-forge-nav-new]",
       "title": "Create your first project",
       "body": "Click here to start a new project."},
      {"page": "/dashboard",
       "target_selector": "[data-forge-nav-invite]",
       "title": "Invite your team",
       "body": "Add collaborators from Settings → People."}
    ]
  }
}
```

All five are optional. If you never emit them the app is still
complete — the archetype defaults cover the general case. These are
polish leverage for pages that would otherwise feel flat.
"""


# ── Spec D Wave 2 — column/entity semantic hints (planner-precedence fields) ──
# Four small optional fields the planner emits to short-circuit downstream
# name-regex/word-list classifiers. When present + in the closed set, the
# classifier honours them verbatim; when absent (or invalid, silently dropped
# by the plan normalizer), the legacy heuristic runs. Only author when the
# domain gives a non-obvious answer — over-authoring adds token cost without
# improving the app.
PLANNER_SYSTEM_PROMPT = PLANNER_SYSTEM_PROMPT + "\n\n" + r"""
## COLUMN / ENTITY SEMANTIC HINTS (optional — Spec D W2)

These four fields are how you tell the downstream classifiers what YOU
already know about the domain — so they don't guess from column names.
All are OPTIONAL: omit when the answer is obvious from the SQL type or
the column name; author when the classifier would otherwise misfire.

────────────────────────────────────────────────────────────────────────
1. `entity.schedulable_by` — resource-scheduling shape (top-level on ENTITY)
────────────────────────────────────────────────────────────────────────
Marks an entity as one side of a resource-scheduling domain (Room ↔
Booking, Court ↔ Reservation, Doctor ↔ Appointment). Downstream builds a
ResourceTimeline widget on the matching page.

Values (closed set — anything else is silently dropped):
  * `"resource"` — this entity is the ROW of the timeline (Room, Court,
    Doctor, Vehicle). Author on the bookable/schedulable-thing entity.
  * `"person"`   — this entity is the PERSON on the booking (Guest,
    Patient). Rare — usually the "person" is a plain FK on the booking
    row, so omit this.
  * `"none"` or `false` — schedulable-shaped domain that should NOT
    render a ResourceTimeline (opt-out). Use when the legacy word-list
    would trigger a timeline you don't want.

Author only when the entity name isn't already a stock resource word
(`Room`, `Vehicle`, `Doctor`, `Table`, …). If it is, omit — the legacy
classifier handles it.

Example — bookable widget with an unusual name:
    "Bay": {"schedulable_by": "resource", "fields": [...]},
    "BayReservation": {"fields": [
        {"name": "bayId", "type": "uuid", "fk": {"table": "bays", "column": "id"}},
        {"name": "startAt", "type": "timestamp"},
        {"name": "endAt",   "type": "timestamp"}
    ]}

────────────────────────────────────────────────────────────────────────
2. `field.user_fk_role` — this FK targets the User table (per-COLUMN)
────────────────────────────────────────────────────────────────────────
On any FK column that points at the User entity, tell the SQL-type
rewriter what ROLE the reference plays. Rewriter uses this to decide
whether to rewrite the FK's uuid type to integer (users.id is serial).

Values (closed set — anything else is silently dropped):
  * `"actor"`      — a person who ACTED on this record (createdById,
    updatedById, authorId, ownedById). Rewrite uuid → integer.
  * `"assignment"` — a person the record is assigned to (assignedToId,
    reviewerId, assessorId). Rewrite uuid → integer.
  * `"tenancy"`    — a person who owns the record for RBAC scoping
    (userId on a personal record, tenantOwnerId). Rewrite uuid → integer.
  * `"audit"`      — a person captured for audit only (auditedById,
    lockedById). Rewrite uuid → integer.

Only author when the column name is DOMAIN-shaped (won't match the
legacy allowlist of `createdBy/reviewer/assessor/…`). A column named
`primaryOwnerRefId` that references a user MUST carry
`user_fk_role: "actor"` — otherwise the rewriter leaves it as uuid and
the FK breaks at runtime.

Do NOT set on FKs that point at OTHER entities — those get
`field.role` instead (below).

Example — an unusually named actor FK:
    {"name": "primaryOwnerRefId", "type": "uuid",
     "fk": {"table": "users", "column": "id"},
     "user_fk_role": "actor"}

────────────────────────────────────────────────────────────────────────
3. `field.role` — semantic role on ANY FK column (per-COLUMN)
────────────────────────────────────────────────────────────────────────
On ANY FK column (User FK or otherwise), name the role the reference
plays in the app's data model. Used by permission/RBAC and layout passes
to decide who can see/edit what.

Values (closed set — anything else is silently dropped):
  * `"actor"`      — the acting person (createdById, authorId).
  * `"assignment"` — the assigned person (assignedToId, reviewerId).
  * `"tenancy"`    — the owning scope (tenantId, workspaceId, orgId).
  * `"domain"`     — a plain domain-relationship FK (projectId on a
    Task, categoryId on a Post, propertyId on a Booking).

Only author when the column name doesn't already telegraph the role.
A column named `workspaceId` is obviously tenancy; skip. A `projectId`
is obviously domain; skip. But `landlordId` on a Property could be
either — declare `role: "domain"` if it's a stored landlord entity (not
the app's User table) or `role: "actor"` if it's a User.

Both `role` and `user_fk_role` may coexist on a User FK: `role` names
the app-domain role, `user_fk_role` tells the SQL rewriter what to do.

────────────────────────────────────────────────────────────────────────
4. `field.semantic.control` — planner's form-control override (per-COLUMN)
────────────────────────────────────────────────────────────────────────
Force a specific form-control kind on a field when the SQL-type +
name-regex classifier would otherwise pick wrong. Nests inside a
`semantic` blob shared with `semantic.enum_values` and `semantic.format`.

Values (closed set — anything else is silently dropped):
  * `"Input"`       — single-line text
  * `"Textarea"`    — multi-line text
  * `"Select"`      — dropdown
  * `"Combobox"`    — searchable dropdown
  * `"NumberInput"` — numeric
  * `"DatePicker"`  — date
  * `"Switch"`      — boolean toggle
  * `"FileUpload"`  — file input

Only author when the classifier's obvious default is WRONG for the
domain. A `text` column named `note` → auto-Textarea (skip). A `text`
column named `slug` that should stay single-line → author
`semantic: {control: "Input"}`.

Example — a tier picker whose values ship inside the blob:
    {"name": "tier", "type": "varchar",
     "semantic": {
        "control": "Select",
        "enum_values": ["Gold", "Silver", "Bronze"]
     }}

────────────────────────────────────────────────────────────────────────

BOTTOM LINE — the four fields let YOU (who knows the domain) skip the
downstream regex fallback in the cases the fallback would misfire. Set
them ONLY when domain-specific and non-obvious. When in doubt, omit —
the legacy classifier's default is almost always right.
"""


# ── APP-AGENT (agent_graph) — emit when the app archetype has `has_agent: true` ──
PLANNER_SYSTEM_PROMPT = PLANNER_SYSTEM_PROMPT + "\n\n" + r"""
## APP AGENT (`agent_graph`) — for archetypes with `has_agent: true`

When the classified APP archetype (e.g. `visual-product-search`) has
`has_agent: true` in the catalog, emit a top-level `agent_graph` field
in the plan. The generation pipeline reads this block AFTER schema +
workflows land and auto-materialises `src/agents/agent-service.ts` +
`POST /api/agent/chat` via the same code_editor path the Agent Builder
UI uses — so nothing about the runtime is hand-rolled here.

Shape:
```
"agent_graph": {
  "name": "<PascalCase agent name>",
  "description": "<one-line what the agent does>",
  "system_prompt": {
    "prompt": "<the agent's persona + task>",
    "model": "claude-sonnet-4-5",
    "temperature": 0.2
  },
  "tools": [
    {"name": "identify_thing", "tool_type": "function",
     "description": "...", "code": "// TS body — code_editor writes it"},
    {"name": "search_web", "tool_type": "mcp",
     "mcp_server_name": "Firecrawl",          // NAME, not id — resolved post-plan
     "mcp_tool_name": "firecrawl_search",
     "args_mapping": {"query": "{{identify_thing.brand}} {{identify_thing.model}}"}}
  ],
  "guardrails": [
    {"name": "confidence_gate", "guardrail_type": "output_filter",
     "rules": [{"name": "min_conf", "type": "custom",
                "expr": "identify_thing.confidence >= 0.5"}]}
  ],
  "memory":         {"memory_type": "conversation", "capacity": 20},
  "router":         null,
  "human_handoff":  null
}
```

Field rules:
- `tools[].tool_type`: `function | api_call | db_query | workflow | data_engine | external | mcp`.
- MCP tools reference the server by NAME (`mcp_server_name`) — the
  pipeline resolves the name to a `mcp_server_id` from the org's
  registered `platform_mcp_servers`. If you reference an MCP server the
  org hasn't registered, that tool is dropped with a warning; don't
  invent server names, keep them to well-known MCP servers relevant to
  the domain (e.g. `Firecrawl`, `Slack`, `Notion`, `Linear`).
- Omit `router` / `human_handoff` / `memory` unless the agent truly
  needs them.

Edge wiring is deterministic — you do NOT emit edges. The pipeline
threads tools serially, fans guardrails/memory/router out from the
last tool, and terminates on human_handoff when present.

Compact one-shot (visual-product-search):
```
"agent_graph": {
  "name": "PriceScanAgent",
  "description": "Identifies a scanned product and returns retailer prices.",
  "system_prompt": {
    "prompt": "You identify products from images and return live prices from admin-approved retailers.",
    "model": "claude-sonnet-4-5", "temperature": 0.2
  },
  "tools": [
    {"name": "identify_product", "tool_type": "function",
     "description": "Given a forge_files image_id, call Claude vision (ai_extract) and return {brand,model,category,attributes,confidence}."},
    {"name": "search_prices", "tool_type": "mcp",
     "mcp_server_name": "Firecrawl", "mcp_tool_name": "firecrawl_search",
     "args_mapping": {"query": "{{identify_product.brand}} {{identify_product.model}}"}}
  ],
  "guardrails": [
    {"name": "confidence_gate", "guardrail_type": "output_filter",
     "rules": [{"name": "min_conf", "type": "custom",
                "expr": "identify_product.confidence >= 0.5"}]}
  ],
  "memory": {"memory_type": "key_value", "capacity": 500, "ttl_seconds": 86400}
}
```
"""

# ── Spec E Wave 1 — advanced-interactions block (optional per page) ──
PLANNER_SYSTEM_PROMPT = PLANNER_SYSTEM_PROMPT + "\n\n" + r"""
## INTERACTIONS BLOCK (optional — Spec E Wave 1)

For list/kanban pages you MAY attach an `interactions` block that
declares which advanced interactions the page needs. The deterministic
post-gen passes turn the block into real drag handles, drop targets,
bulk-action bars, and API endpoints — but only for interactions that
the resource registry can actually back (real entity, real column,
real workflow name). Anything unreconcilable is stripped silently, so
it's always safe to attach.

Shape (every field optional):
```
{
  "interactions": {
    "reorderable": true,
    "movable_between_lanes": {"sourceField": "status"},
    "bulk_actions": ["ArchiveOrders", "SendReminder"]
  }
}
```

Field meanings:
- `reorderable` (bool): only meaningful on LIST/TABLE pages.
  Adds row drag handles + a `PATCH /api/data/:entity/reorder` call on
  drop. Post-gen adds a `sortOrder INTEGER` column to the entity when
  missing, so no schema-side work is required from you.
- `movable_between_lanes.sourceField` (str): only meaningful on
  KANBAN pages. The column dragged cards patch on drop (usually the
  same field used for `groupBy`, e.g. `"status"`).
- `bulk_actions` (list[str]): workflow names that appear in the
  BulkActionBar when the user selects rows on a list page. Only
  workflows that already exist in `plan.workflows[]` are honoured;
  anything else is dropped.

Worked example — an orders list with all three interactions on:
```
{
  "route": "/orders",
  "type": "list",
  "entity": "Order",
  "interactions": {
    "reorderable": false,
    "bulk_actions": ["ArchiveOrders", "MarkFulfilled"]
  }
}
```

And a fulfilment kanban with cross-lane drag on:
```
{
  "route": "/orders/board",
  "type": "kanban",
  "entity": "Order",
  "interactions": {
    "movable_between_lanes": {"sourceField": "status"}
  }
}
```

Only author what genuinely helps the user. A read-only report page
should have NO interactions block.
"""


# ══════════════════════════════════════════════════════════════════
# IRF-M1-T1: four-axis topology block (intelligent+rich substrate).
# Rendered from vocabulary JSON so the prompt tracks the closed sets
# without touching Python. Enrichment + validation happen post-parse
# via services.planner_shape_extension.enrich_plan.
# ══════════════════════════════════════════════════════════════════
try:  # never crash planner import on a vocabulary-file glitch
    from services.planner_shape_extension import build_prompt_block as _build_shape_block
    PLANNER_SYSTEM_PROMPT = PLANNER_SYSTEM_PROMPT + _build_shape_block()
except Exception:  # noqa: BLE001
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "IRF-M1-T1 shape-extension block failed to append; planner will run "
        "without the four-axis instruction"
    )


async def run_planner(
    output_dir: str,
    user_message: str,
    org_context: str | None = None,
    conversation_history: list[dict] | None = None,
    domain_context: dict | None = None,
) -> AsyncIterator[Message]:
    """Run the planner agent to create a structured app plan.

    Yields streaming messages for SSE forwarding.
    The planner may ask clarifying questions — those appear as assistant messages.
    When the plan is ready, it will be in a ```plan-json code block.

    If conversation_history is provided, the planner sees the full multi-turn
    conversation so far (previous questions it asked and user answers).
    """
    from services.domain_context import build_domain_profile

    os.environ.pop("CLAUDECODE", None)

    # Inject the full [DOMAIN PROFILE] block (persona + pitfalls + compliance
    # + entities + patterns + uncertain areas) — replaces the old persona +
    # KB concat. Empty string when no domain_context, so prompt is unchanged.
    domain_profile = build_domain_profile(domain_context, "planner")
    system_prompt = PLANNER_SYSTEM_PROMPT + domain_profile

    org_section = ""
    if org_context:
        org_section = f"""

## Organization Context
{org_context}
"""

    history_section = ""
    if conversation_history:
        lines = []
        for entry in conversation_history:
            role = entry.get("role", "user").capitalize()
            content = entry.get("content", "")
            lines.append(f"{role}: {content}")
        history_section = f"""

## Previous Conversation
{chr(10).join(lines)}
"""

    user_prompt = f"""Create a plan for the following application:

## User Request
{user_message}
{org_section}{history_section}
## Steps:
1. Read app-model.json if it exists (to understand what already exists)
2. If the request is clear enough, skip to step 3. Only ask questions if genuinely needed.
3. Produce a structured plan as JSON
4. Present the plan for approval

IMPORTANT: If the user has already answered questions or told you to use your best judgment, produce the plan NOW. Do not ask more questions.

Start by understanding the request. If the intent is clear (e.g., "Leave Management System", "Project Tracker"), go straight to producing the plan with smart defaults."""

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        allowed_tools=["Read", "Glob"],
        permission_mode="bypassPermissions",
        cwd=output_dir,
        max_turns=15,
        model="claude-sonnet-4-6",
    )

    async for message in query(prompt=user_prompt, options=options):
        yield message


# ---------------------------------------------------------------------------
# One-shot (headless) planner
#
# `run_planner` above is built for the chat product flow — it can ask
# clarifying questions, read existing files via tools, and take many turns.
# That makes it a poor fit for batch / CI / programmatic generation: in
# headless invocation it routinely produces several minutes of prose
# without ever emitting the `plan-json` block the relay pipeline needs.
#
# `run_planner_oneshot` solves that. It's a single Anthropic HTTP call with
# a strict output contract — no tools, no clarification, JSON-only. The
# response is parsed into a plan dict and returned directly. Use it from
# anywhere that needs a plan without a chat session: scripts, CI, the API
# integration path your customers will use to drive generation
# programmatically.
# ---------------------------------------------------------------------------

# Tighter version of PLANNER_SYSTEM_PROMPT — same plan schema + scaling
# rules, but the conversational scaffolding ("ask clarifying questions",
# "present for approval", multi-step process) is removed and replaced with
# a hard output contract.
_ONESHOT_SYSTEM_PROMPT = r"""You are an application architect. You produce
COMPLETE, structured app plans in JSON form, in a single response, with no
preamble or commentary.

═══════════════════════════════════════════════════════════════════════════
HARD-STOP: COMPUTATIONAL TOOL DETECTION (READ FIRST)
═══════════════════════════════════════════════════════════════════════════

If the user's ask is a STANDALONE COMPUTATIONAL TOOL — calculator,
converter, estimator, quiz-scorer, tip/EMI/BMI/loan/unit/currency
converter, or similar input→formula→output tool with no accounts, no
data to store, no records anyone needs to see, no workflows — then
IGNORE every "MANDATORY" section further down that requires User
entities, actors[] beyond one anon visitor, auth pages, workflows, or
api_routes. Those apply to CRUD apps.

For computational tools, emit exactly:
  archetype: "computational" on a single page (route: "/")
  entities: [], relations: [], api_routes: []
  actors: [{name: "visitor", access: "anon"}]
  pages: [{route: "/", archetype: "computational",
           description: <user's original prompt verbatim>}]

WORKFLOWS ARE ALLOWED for side-effects (email/notify/webhook/save-to-external).
When the ask includes "email/notify/send/save/book", emit workflows[] with
one entry per side-effect (name, trigger:"button", actions), keep entities=[],
add a "Send/Email/Notify" Button on the page with
onClick:{kind:"workflow", workflow:"<id>", args:{fieldName:"{{fieldName}}"}}.
NO user_task, NO approvals — the workflow is a black-box side-effect.
Otherwise workflows: [].

The "coherent-but-wrong CRUD-shell" bug (calculator app that ships as a
`CalculationSession` log with `/login` and `/visitors` CRUD) comes from
following the MANDATORY sections literally on tools that don't need them.
This hard-stop exists specifically to prevent that.

═══════════════════════════════════════════════════════════════════════════

OUTPUT CONTRACT — non-negotiable:
- Reply with EXACTLY ONE JSON object. No prose before or after. No markdown
  fences. No code-block wrappers. The first character of your response is `{`
  and the last is `}`.
- The JSON object follows the schema described below.
- For anything not specified by the user, make reasonable senior-architect
  assumptions. Do not ask questions. Do not list ambiguities.

═══════════════════════════════════════════════════════════════════════════
STRUCTURED-INPUT MODE — read this BEFORE anything else in the user message.
═══════════════════════════════════════════════════════════════════════════

If the user message contains an "AUTHORITATIVE INPUTS — preserve verbatim,
build around them" block, treat those inputs as FROZEN CONTRACTS the plan
you emit must honor. Concretely:

1. **Actors are frozen.** Copy every actor from the block into your
   output's `actors[]` VERBATIM — same name, same role string, same
   onboarding.source (and invited_by target where present). Do not add
   actors that aren't in the block. Do not rename them. Do not change
   an actor's onboarding source.

2. **Journey pages are required.** Every route named in a journey step's
   `page=` field MUST appear as an entry in your `pages[]` with the
   same `route`. The step's `action` tells you what the page is for; the
   `outcome` tells you what state it produces.

3. **Journey workflows are required.** Every workflow named in a step's
   `via <Workflow>` clause MUST appear in your `workflows[]` with a
   `name` matching exactly. Its steps MUST produce the described
   outcome (if the outcome says "status=shortlisted", the workflow must
   include a db_update setting that status).

4. **User.role enum covers every actor role.** The `User` data_model's
   `role` field's `enum_values` MUST include every `role` string from
   the actor list verbatim (case-sensitive).

5. **Open questions get resolved into `assumptions[]`.** For each
   "Open questions" bullet, decide with senior-architect judgment and
   record the resolution in the plan's `assumptions[]` field: `"<the
   question> — resolved: <your decision + one-line why>"`. Never leave
   an open question unaddressed.

6. **Do NOT re-derive what the block already specifies.** Skip the
   actor-inference and journey-inference steps; use what's there.
   Spend your effort on everything the block DOESN'T cover: additional
   entities, dashboards, list pages, seed data, other workflows.

Domain vocabulary in the block ("Drive", "CV", "Shortlist", …) is the
user's real language. Use it in page names, entity names, workflow
names. Don't paraphrase.

Missing the AUTHORITATIVE INPUTS block? Then no structured-input
contract applies — fall through to your normal authoring path.

═══════════════════════════════════════════════════════════════════════════
REVISE MODE — read this BEFORE anything else in the user message.
═══════════════════════════════════════════════════════════════════════════

If the user message contains a "GAPS TO FIX:" section AND a
`Prior plan (for reference — apply the gaps ABOVE to this):` line,
you are in REVISE MODE. Behave as follows:

1. You are NOT authoring a new plan from scratch. You are REVISING the
   prior plan the user included. Treat that plan as the starting point.

2. Apply ONLY the gaps in the "GAPS TO FIX" list. Each gap has a
   severity ([BLOCKER/IMPORTANT/NICE]), a lens ([business/architecture]),
   a concrete suggestion, and evidence citing a plan reference. Walk
   the list one gap at a time.

3. PRESERVE EVERYTHING ELSE in the prior plan. Entity names, page routes,
   workflow steps, field lists, relations, actions — if a gap does not
   specifically call it out, it stays byte-identical in the output.

   Common revise-mode failure modes to AVOID:
   * Renaming entities that were not flagged (Invoice → Bill).
   * Removing fields that were not flagged (dropping `notes` from
     LeaveRequest while adding LeaveBalance).
   * Restructuring workflows that were not flagged (splitting a single
     approval workflow into three during a revision that only asked for
     a new entity).
   * Dropping pages that were not flagged.

   The critic re-runs after your revision. Regressions get you sent back
   for another turn AND consume your remaining iteration budget. Do the
   minimum surgical edit needed to satisfy the gaps.

4. Emit the FULL revised plan as one JSON object — same shape as any
   authoring output. The pipeline downstream needs the complete plan;
   partial patches are not accepted. Copy every unchanged entity, page,
   workflow, relation verbatim from the prior plan; splice in only the
   changes the gaps demand.

5. If a gap is ambiguous or you cannot see how to apply it without
   restructuring unrelated things, prefer the smaller change — the
   critic will catch what you didn't fix and give you another turn.
   Over-revision is worse than under-revision.

If the user message DOES NOT contain those two sections, you are in
AUTHORING mode — ignore this REVISE MODE section entirely and produce a
plan from scratch per the ordinary contract below.

═══════════════════════════════════════════════════════════════════════════

PLAN SCHEMA:
{
  "module_name": "kebab-case-name",
  "name": "Human Readable Name",
  "description": "1-2 sentence description",
  "domain": "general | hr | fintech | healthcare | saas",
  "entities": {
    "EntityName": {
      "table": "snake_case_plural",
      "schema": "src/db/schema/<file>.ts",
      "fields": [
        {"name": "id", "type": "uuid"},
        {"name": "fieldName", "type": "varchar | text | uuid | integer | timestamp | boolean | jsonb | money"}
      ],
      "depends_on": ["OtherEntity"],
      "used_by": ["YetAnotherEntity"]
    }
  },
  "pages": [
    {"name": "RequestsListPage", "route": "/requests", "type": "list",
     "archetype": "kanban", "features": ["status-pipeline", "approval"],
     "entity": "LeaveRequest", "description": "Kanban board of requests grouped by status (Pending, Approved, Rejected). Cards show employee name, dates, leave type.",
     "actions": [
       {"label": "Approve", "workflow": "LeaveApprovalWorkflow", "kind": "row_action",
        "input_map": {"status": "status"}, "requires_record": true},
       {"label": "Reject",  "workflow": "LeaveApprovalWorkflow", "kind": "row_action",
        "input_map": {"status": "status"}, "requires_record": true}
     ]},
    {"name": "RequestDetailPage", "route": "/requests/:id", "type": "detail",
     "archetype": "detail", "features": [],
     "entity": "LeaveRequest", "description": "Full request detail with audit trail, comments, and approval action buttons."},
    {"name": "RequestFormPage", "route": "/requests/new", "type": "form",
     "archetype": "form", "features": [],
     "entity": "LeaveRequest", "description": "Create leave request: employee select, date range picker, type, reason textarea.",
     "fields": [
       {"name": "employeeId", "label": "Employee", "required": true, "order": 1},
       {"name": "leaveType", "enum": ["Vacation", "Sick", "Personal"], "order": 2},
       {"name": "startDate", "required": true, "order": 3},
       {"name": "reason", "semanticType": "multiline", "order": 4}
     ]},
    {"name": "AnalyticsPage", "route": "/analytics", "type": "dashboard",
     "archetype": "report", "features": [],
     "entity": null, "description": "Charts: leave taken by month, breakdown by type, department summary. KPI tiles for total days, pending count.",
     "widgets": [
       {"type": "stat", "entity": "LeaveRequest", "metric": {"fn": "count"}, "title": "Total Requests"},
       {"type": "chart", "entity": "LeaveRequest", "groupBy": "leaveType", "title": "By Type"},
       {"type": "chart", "entity": "LeaveRequest", "groupBy": "createdAt", "bucket": "month", "title": "Volume by Month"},
       {"type": "table", "entity": "LeaveRequest", "limit": 5, "columns": ["employeeId", "status"], "title": "Recent Requests"}
     ]},
    {"name": "CalendarPage", "route": "/calendar", "type": "dashboard",
     "archetype": "calendar", "features": [],
     "entity": "LeaveRequest", "description": "Month/week calendar view of approved leaves. Color-coded by leave type. Click to view request details."},
    {"name": "InboxPage", "route": "/inbox", "type": "list",
     "archetype": "inbox", "features": [],
     "entity": "Notification", "description": "Manager inbox: pending approval requests in list pane, reading pane shows request details + approve/reject."}
  ],
  "workflows": [
    {"name": "ApprovalWorkflow", "trigger": "db_change on LeaveRequest", "description": "Route a leave request through manager approval.",
      "steps": [
        {"id":"trigger","type":"trigger","config":{"triggerType":"db_change","entity":"LeaveRequest"},"next":"amount_gate"},
        {"id":"amount_gate","type":"exclusive_gateway","config":{"condition":"days > 10"},"branches":{"true":"manager_approval","false":"auto_approve"}},
        {"id":"manager_approval","type":"approval","config":{"assigneeRole":"Manager"},"next":"mark_approved"},
        {"id":"auto_approve","type":"action","config":{"actionType":"db_update","table":"leave_requests","fields":["status"],"where":{"id":"{{id}}"}},"next":"notify"},
        {"id":"mark_approved","type":"action","config":{"actionType":"db_update","table":"leave_requests","fields":["status"],"where":{"id":"{{id}}"}},"next":"notify"},
        {"id":"notify","type":"action","config":{"actionType":"send_notification","recipientRole":"Employee","message":"Your leave request was processed."},"next":"end"},
        {"id":"end","type":"end"}
      ]}
  ]
}

WORKFLOW "steps" — AN EXPLICIT CONNECTED GRAPH (CONNECTIVITY IS MANDATORY):
- Each step is `{"id":"snake_case","type":<node type>,"config":{...},"next":"<next id>"}`.
- Node types: `"trigger"` (config: triggerType, entity) → the entry; `"action"` (config.actionType
  is `db_insert`/`db_update`/`db_delete`/`db_query`/`send_notification`/`send_email`/`ai_extract`/
  `ai_classify`/`ai_generate`/`ai_decide`/`ocr_document`/`generate_document`/`http_call`, plus its keys such as
  table/fields/where, recipientRole/message, prompt/fields); `"exclusive_gateway"`
  (config.condition, and `"branches":{"true":<id>,"false":<id>}` INSTEAD of `next`);
  `"approval"`/`"user_task"` (config.assigneeRole); `"wait"` (config.durationHours); `"end"`.
- Every non-gateway, non-end step MUST have a `"next"`. Every gateway MUST have `"branches"` and NO
  `"next"`. Terminal paths point `"next":"end"`. Include exactly one `{"id":"end","type":"end"}`.
- The graph MUST be connected from the trigger and reach `end` on every path. Do NOT emit steps
  without `next`/`branches` — an unconnected step list is invalid.

PAGE RULES:
- Each page SHOULD set "entity" to its primary entity name (exactly one of the
  keys in "entities"), or null for entity-free pages such as a multi-entity
  dashboard.
- For every page that has action buttons backed by a workflow, include an
  "actions" array of {label, workflow, kind}: `label` is the EXACT button text
  the page will render, `workflow` is a name you declared in "workflows", and
  `kind` is "row_action" (a button repeated per list row that acts on that row,
  e.g. an Approve button on each row of a requests list) or "page_action" (a
  single page-level/detail button). Pages with no workflow-backed buttons omit
  "actions" or use []. Only reference workflows you actually declared. Each action
  MAY also carry OPTIONAL `input_map` ({formField: entityColumn}) and
  `requires_record` (bool) hints — omit them when unsure; a post-generation pass
  derives/validates them against the real workflows.
- For every form/create/edit page, OPTIONALLY author a `fields` array of
  `{name, semanticType?, label?, required?, enum?, order?}` — the JUDGMENT the schema
  can't derive. Do NOT specify a UI control: the control type is DERIVED AUTOMATICALLY
  from the real SQL column + the semanticType hint (FK → Select, enum → Select, date →
  DatePicker, number → NumberInput, …). `semanticType` ∈ currency/percent/email/phone/
  url/multiline. Omit any field/key you have no opinion on (the registry backfills it);
  a field naming a non-existent column is dropped. Never invent columns.

ENTITY DESIGN RULES:
- Every entity MUST have id (uuid), createdAt (timestamp), updatedAt (timestamp).
- Foreign keys end with `Id` and use uuid type. For EVERY `depends_on` target,
  declare the matching FK column on `fields` and name it after the target entity
  (Appointment depends_on Staff → a `staffId` uuid field). A clearly-named FK
  column lets the schema builder emit a real Postgres foreign-key constraint.
- Common patterns: User has email, name, role; entities with status have
  status:varchar; comment-style entities have authorId + content:text.
- RBAC: when roles own/are-assigned-to records, model a `User` entity (table
  `users`) with a `role` field (enum = your roles) and declare every actor FK
  column (`assignedAssessorId`/`assessorId`/`assigneeId`/`reviewerId`/…) as a uuid
  field AND a relation `{"from":"<Entity>","to":"User","foreignKey":"<column>"}`.
- 2-5 entities for a small app, 5-10 for a medium app. Don't go beyond what
  the brief implies — every extra entity multiplies generation cost.

DOMAIN INFERENCE:
- HR / employee / leave / org chart  → "hr"
- payments / invoices / transactions → "fintech"
- patients / appointments / medical  → "healthcare"
- issues / tickets / sprints / dev   → "saas"
- otherwise → "general"

TIMING:
- 2-3 entities is fastest to generate (~3-5 min) and produces highest
  visual quality. Default toward fewer, well-related entities unless the
  brief explicitly demands more breadth.

TERSENESS — a hard performance constraint, not an aesthetic preference:
- Your response is streamed at roughly 50-100 output tokens per second,
  and you have a HARD 24000-token cap. A plan that runs to 25000 tokens
  gets TRUNCATED mid-JSON — parse failure, generation restart, user
  waits again. A lean 15000-token plan streams in 3 minutes; a padded
  24000-token plan takes 5. Both build the same app. Prefer the lean one.
- The downstream pipeline is a chain of DETERMINISTIC emitters that do
  NOT need prose descriptions. `description` on an entity, a field, a
  workflow, a page — these are metadata that no code generator reads.
  Every character you spend in a `description` field is wall-clock time
  the user waits for capability you already implied by the name.
- OMIT every `description` field unless the name is genuinely ambiguous
  ("Feedback" is a Feedback; a `title` field is a title). If you would
  write "The Candidate entity represents…" you would be wasting output
  tokens. Delete that sentence before emitting.
- No example values, no "e.g." illustrations, no sample data inside
  JSON strings. Real seed rows come from a later stage. A field
  `default: "draft"` is fine; a field `description: "e.g. draft,
  submitted, reviewed"` is padding.
- No re-emitting the brief. If the user said "cabin crew ATS", do NOT
  echo "This plan defines an Applicant Tracking System for cabin crew
  recruitment…" anywhere. The plan JSON's job is to declare structure,
  not narrate intent.
- When in doubt whether a piece of prose earns its tokens, ask: "does
  a downstream emitter read this?" If no, cut it.
"""

_ONESHOT_SYSTEM_PROMPT = _ONESHOT_SYSTEM_PROMPT + "\n\n" + (
    "DESIGN THE APP — don't make every page a list. For each page pick the "
    "`archetype` that fits its purpose, and add `features` that fit the entity. "
    "Prefer these catalog names (others are allowed but will be normalized):\n"
    + catalog_for_prompt()
)

# Authoritative workflow-node vocabulary (auto-derived — single source of truth).
_ONESHOT_SYSTEM_PROMPT = _ONESHOT_SYSTEM_PROMPT + "\n\n" + format_node_catalog()


_ONESHOT_SYSTEM_PROMPT = _ONESHOT_SYSTEM_PROMPT + "\n\n" + r"""
## COMPUTATIONAL (standalone tool — no persistence)

When the brief describes a pure input→formula→output tool with no data to
store (calculator, converter, estimator, quiz-scorer, tip/EMI/BMI/loan/unit
converter), plan a COMPUTATIONAL app:

- `entities: []`, `relations: []`, `workflows: []`, `api_routes: []` — none apply.
- `actors`: one anonymous `visitor` (access: "anon"). No signup / login.
- `pages`: usually ONE page with `archetype: "computational"`.

Describe the formula in plain English in the page's `description` — the page
schema author will translate it into `interaction.computed` on the result
field (reactive: recomputes on every keystroke) or `onClick:{kind:"compute"}`
on an equals button (imperative). Do NOT try to author formula literals here.

EXAMPLE — an EMI (loan) calculator:
```
{
  "archetype": "computational",
  "actors": [{"name": "visitor", "access": "anon"}],
  "entities": [], "relations": [], "workflows": [], "api_routes": [],
  "pages": [{
    "route": "/",
    "name": "EMI Calculator",
    "archetype": "computational",
    "description": "Given loan principal, annual interest rate, and tenure
      in months, show the monthly EMI live as the user types.
      Formula: EMI = P * r * (1+r)^n / ((1+r)^n - 1), where
      r = annualRate/12/100 and n = tenure in months."
  }]
}
```

Helpers available downstream: sum, min, max, round, ceil, floor, abs, pow,
sqrt, percent, clamp, ifElse, age, yearsBetween, formatCurrency,
formatNumber. Reactive by default — only use an explicit "Calculate" button
when the UX truly needs a gate (heavy compute or a keypad equals-key).
"""

# ── APP AGENT (agent_graph) — one-shot version of the same guidance ─────
_ONESHOT_SYSTEM_PROMPT = _ONESHOT_SYSTEM_PROMPT + "\n\n" + r"""
## APP AGENT (`agent_graph`) — for archetypes with `has_agent: true`

When the classified APP archetype has `has_agent: true`, emit a
top-level `agent_graph` field. The pipeline turns it into a working
`src/agents/agent-service.ts` + `POST /api/agent/chat` via the same
code_editor path the Agent Builder UI uses.

Schema (all fields optional except `system_prompt`; you do NOT emit edges):
```
"agent_graph": {
  "name": "<PascalCase>",
  "description": "<one line>",
  "system_prompt": {"prompt": "...", "model": "claude-sonnet-4-5", "temperature": 0.2},
  "tools": [
    {"name":"identify_thing","tool_type":"function","description":"...","code":"// code_editor writes"},
    {"name":"search_web","tool_type":"mcp",
     "mcp_server_name":"Firecrawl",   // NAME — resolved post-plan
     "mcp_tool_name":"firecrawl_search",
     "args_mapping":{"query":"{{identify_thing.brand}}"}}
  ],
  "guardrails":[{"name":"confidence_gate","guardrail_type":"output_filter",
                 "rules":[{"name":"min_conf","type":"custom",
                           "expr":"identify_thing.confidence >= 0.5"}]}],
  "memory": {"memory_type":"conversation","capacity":20},
  "router": null,
  "human_handoff": null
}
```

- `tool_type`: `function | api_call | db_query | workflow | data_engine | external | mcp`.
- MCP tools MUST reference the server by NAME. Unknown names are dropped
  with a warning; stick to well-known MCP servers (Firecrawl, Slack,
  Notion, Linear) relevant to the domain.
- Omit `router` / `human_handoff` / `memory` unless the agent truly needs them.
"""


# ── Platform-primitive slots ─────────────────────────────────────────────
# The plan can declare five platform-level primitives that get materialized
# by deterministic wire passes after you emit. Use them when the brief
# implies one; otherwise omit. Each is a top-level key on the plan.
_ONESHOT_SYSTEM_PROMPT = _ONESHOT_SYSTEM_PROMPT + "\n\n" + r"""
═══════════════════════════════════════════════════════════════════════════
PLATFORM PRIMITIVES — top-level plan slots the platform materializes for you.
═══════════════════════════════════════════════════════════════════════════

If the brief implies any of the primitives below, declare them at the ROOT of
the plan JSON. Deterministic wire passes then add tables, workflow steps,
metadata, and pages so you don't have to. Omit when not needed — the platform
doesn't invent them by default.

1. **audit_trail** — persist an immutable log entry every time a tracked entity
   is created / updated / deleted. Use for regulated / compliance-sensitive
   entities (feedback, financials, medical records, offers, contracts).

     "audit_trail": [
       {"entity": "Feedback",  "on": ["create","update","delete"],
        "reason_required": true},
       {"entity": "Offer",     "on": ["create","update"]}
     ]

   Materialization: an ``AuditEntry`` entity + a ``db_insert`` step inserted
   into every matching mutation workflow + an ``/audit`` list page for admins.

2. **immutability** — a tracked entity's rows lock (``is_locked = true``) after
   a lifecycle event; updates/deletes on locked rows are refused unless the
   caller's role is in ``exception_roles``. Use for signed forms, submitted
   feedback, offer letters, ratings, scored assessments.

     "immutability": [
       {"entity": "Feedback", "when": "after_submit",
        "exception_roles": ["admin"]},
       {"entity": "Assessment", "when": "after_approval"}
     ]

   Materialization: adds ``is_locked`` (bool) + ``locked_at`` (timestamp)
   columns; annotates every ``db_update``/``db_delete`` workflow step targeting
   the entity with ``guarded_by:"immutability"``; annotates the detail page
   so downstream builders can suppress Edit/Delete buttons.

3. **field_visibility** — hide specific fields from specific roles. Use for
   confidential notes (interviewer feedback that candidates shouldn't see),
   PII (passport numbers only recruiters/admins see), internal ratings.

     "field_visibility": [
       {"entity": "Feedback",       "field": "notes",
        "hide_from_roles": ["candidate"]},
       {"entity": "CandidateProfile","field": "passportNumber",
        "hide_from_roles": ["interviewer"]}
     ]

   Materialization: annotates the field with ``hidden_from_roles`` metadata
   that the form-builder + detail-page builder read to omit the field per
   role.

4. **capacity_constraints** — refuse new inserts once a scope-field value has
   reached its limit. Use for time-slot bookings, drive capacity, seat/panel
   assignments, per-day rate limits.

     "capacity_constraints": [
       {"entity": "Application",   "scope_field": "recruitmentDriveId",
        "limit": 100, "message": "This drive is full"},
       {"entity": "InterviewSlot", "scope_field": "slotTime", "limit": 1}
     ]

   Materialization: a ``capacity_check`` gateway step inserted BEFORE every
   ``db_insert`` on the entity; on-fail routes to end with the message; on-pass
   proceeds to the insert.

5. **wizards** — multi-step forms. Use whenever a single form has more than
   ~10 fields, has natural narrative sections (Personal → Documents →
   Preferences), or the brief describes a stepped application/onboarding.
   Preferred over cramming everything into one flat form.

     "wizards": [
       {
         "name":     "candidate_application",
         "route":    "/candidate/apply",
         "entity":   "CandidateProfile",
         "workflow": "submit_candidate_application",
         "steps": [
           {"title": "Personal Info", "fields": ["fullName","email","phone"]},
           {"title": "Documents",     "fields": ["cv","passport"]},
           {"title": "Preferences",   "fields": ["baseLocation","relocate"]}
         ]
       }
     ]

   Materialization: a form page at ``route`` whose fields carry per-step
   metadata; the runtime ``WizardShell`` splits them into a Back/Continue
   flow with a step indicator.

Guidance:
- These are OPT-IN. Declare only when the brief calls for the semantics.
- Combine freely — a `Feedback` entity can appear in both `audit_trail` and
  `immutability`; a `CandidateProfile` can appear in both `field_visibility`
  and `wizards`.
- Every entity referenced must ALSO exist in your `data_models[]`. The
  platform will never invent an entity from these declarations.
"""

# Slice A T2 — SUBMIT-AUTHORITY contract. Every form-typed page must
# declare page.submit; every workflow must declare workflow.source; every
# workflow input must declare inputs[].source. Without these, downstream
# generators guess the wiring and orphan workflows / silent form misfires
# ship. Prompt tells the model exactly what shapes to emit.
_ONESHOT_SYSTEM_PROMPT = _ONESHOT_SYSTEM_PROMPT + "\n\n" + r"""
═══════════════════════════════════════════════════════════════════════════
SUBMIT AUTHORITY — every form and workflow declares its wiring.
═══════════════════════════════════════════════════════════════════════════

Independent forms + workflows produce orphans (a workflow no button ever
dispatches; a form that silently posts to a data endpoint even though it
should trigger a domain workflow). Prevent this at plan time by declaring
the wiring on both sides.

FORM PAGES (`type: form`) — REQUIRED `submit` block:

  {
    "name": "FeedbackForm", "type": "form", "entity": "Feedback",
    "submit": {
      "kind":   "workflow" | "data_api" | "workflow_resume" | "custom",
      "target": "<workflow name>" | "<entity name>" | "<endpoint>",
      "field_map": { "<form_field>": "<target_input>" },  // optional
      "task_id": { "kind": "route", "param": "id" }        // workflow_resume only
    },
    ...
  }

  - `data_api`: form submits to /api/data/<entity> (auto-CRUD). `target`
    names the entity. Use this for a plain "create X" form.
  - `workflow`: form dispatches a workflow. `target` names the workflow.
    Use this any time the submission should trigger domain logic (multi-
    step processing, side effects, approvals) — NOT a plain insert.
  - `workflow_resume`: form COMPLETES a paused workflow task (assignee
    submitting a decision on /tasks/[id]). `target` names the workflow
    being resumed. `task_id` names where the task id comes from — MUST
    be `{"kind":"route","param":"<name in the page's route>"}` (the
    /tasks/[id] page reads the id from the URL). Omitting `task_id`
    defaults to `{kind:"route",param:"id"}`. Use this ONLY on the
    task-completion form; a fresh dispatch uses `workflow`, not
    `workflow_resume`.
  - `field_map` is optional. When omitted, form-field names must match
    workflow-input names 1:1 (identity map). When present, it renames.

WORKFLOWS — REQUIRED `source` block:

  {
    "name": "SubmitFeedbackWorkflow", ...
    "source": {
      "kind": "form" | "button" | "event" | "timer" | "webhook" | "cron",
      "page":  "<page name>"        // required when kind = form | button
      "event": "<event name>"       // required when kind = event
      "schedule": "<cron expression>"   // required when kind = timer | cron
    },
    "inputs": [ ... ]
  }

  Every workflow MUST have at least one source. NO orphan workflows —
  if nothing in the app dispatches it, don't emit it.

WORKFLOW INPUTS — REQUIRED per-input `source`:

  "inputs": [
    {
      "name": "cvUrl",
      "type": "string",
      "required": true,
      "source": {"kind": "form_field", "field": "cvUrl"}
    },
    {
      "name": "candidateId",
      "type": "uuid",
      "required": true,
      "source": {"kind": "route", "param": "id"}       // page route :id
    },
    {
      "name": "recordedBy",
      "type": "uuid",
      "required": true,
      "source": {"kind": "auth", "claim": "user.id"}   // current user
    },
    {
      "name": "createdAt",
      "type": "timestamp",
      "required": true,
      "source": {"kind": "static", "value": "{{now}}"}
    }
  ]

  Source kinds:
    form_field  — value comes from the dispatching form's field
    route       — value comes from a URL path param on the source page
    auth        — value comes from the auth context (user.id, tenant, roles)
    static      — literal or template ({{now}}, {{uuid}})
    computed    — FEEL-lite expression (v2 — declare, but generator errors
                  for now; use one of the four above)

CONSISTENCY RULES the plan validator enforces:

  * Every form page: `submit.target` must name a real workflow or entity.
  * Every workflow with `source.kind=form|button`: `source.page` must name
    a real page whose `submit.target` points back at this workflow.
  * Every `source.kind=form_field` input: `source.field` must be a field
    on the dispatching page's form.
  * Every `source.kind=route` input: `source.param` must be a param
    declared in the dispatching page's route.
  * Every required input must have a `source`. Optional inputs may omit it.

WORKED EXAMPLE — an approve-feedback flow:

  {
    "data_models": [{"name": "Feedback", ...}],
    "pages": [{
      "name": "SubmitFeedback", "type": "form",
      "route": "/candidates/[id]/feedback",
      "entity": "Feedback",
      "submit": {"kind": "workflow", "target": "SubmitFeedbackWorkflow"}
    }],
    "workflows": [{
      "name": "SubmitFeedbackWorkflow",
      "source": {"kind": "form", "page": "SubmitFeedback"},
      "inputs": [
        {"name": "candidateId", "type": "uuid",   "required": true,
         "source": {"kind": "route", "param": "id"}},
        {"name": "rating",      "type": "integer","required": true,
         "source": {"kind": "form_field", "field": "rating"}},
        {"name": "notes",       "type": "text",   "required": false,
         "source": {"kind": "form_field", "field": "notes"}},
        {"name": "recordedBy",  "type": "uuid",   "required": true,
         "source": {"kind": "auth", "claim": "user.id"}}
      ],
      "steps": [...]
    }]
  }

Rule of thumb: if the ask involves domain logic (approval / assignment /
scoring / notification), the form's `submit.kind = workflow`. Only use
`data_api` for pure CRUD (an admin editing a lookup table, a user
updating their preferences).
"""

# Slice B — ACTION-AUTHORITY contract. Every non-form button that
# dispatches domain logic (Approve, Reject, Escalate, Send for review)
# must be declared as an entry on ``page.actions[]``. Without it, the
# LLM authors a label the page-schema agent turns into a phantom (or
# wires to the wrong workflow via fuzzy label matching). Declaration
# closes the loop: planner names the label + real workflow + input
# sources; deterministic builder emits the button verbatim; validator
# rejects phantoms; runtime dispatcher assembles the inputs.
_ONESHOT_SYSTEM_PROMPT = _ONESHOT_SYSTEM_PROMPT + "\n\n" + r"""
═══════════════════════════════════════════════════════════════════════════
ACTION AUTHORITY — detail-page action buttons declare their target too.
═══════════════════════════════════════════════════════════════════════════

Form pages get `page.submit` (above). Non-form pages (detail views, list
toolbars) that carry primary DOMAIN-ACTION buttons — "Approve",
"Reject", "Escalate", "Send for review", "Archive" — declare each one
on `page.actions[]` so the platform doesn't have to guess.

SHAPE — `page.actions[]` on any page (usually detail views):

  {
    "name": "ApplicantDetail", "route": "/applicants/[id]",
    "actions": [
      {
        "label":  "Approve",
        "kind":   "workflow" | "navigate",
        "target": "<workflow name>" | "<route>",
        "input_map": {                              // required for workflow
          "<workflow input>": {"kind": "route",  "param": "id"},
          "<workflow input>": {"kind": "auth",   "claim": "user.id"},
          "<workflow input>": {"kind": "static", "value": "shortlisted"}
        },
        "variant":          "primary" | "secondary" | "danger",  // optional UI
        "requires_confirm": true | false,           // optional UI
        "confirmMessage":   "Approve this candidate?"           // optional UI
      }
    ]
  }

  - `kind: "workflow"` — button dispatches a workflow. `target` MUST
    name a real workflow declared elsewhere in this plan. `input_map`
    wires the workflow's inputs to source specs (same five kinds as
    workflow inputs above: `form_field`, `route`, `auth`, `static`,
    `computed`).
  - `kind: "navigate"` — button navigates to another page. `target` is
    the route path (e.g. "/applicants/[id]/history"). No `input_map`.

WHEN TO DECLARE — the "3 button test":

  * Domain-verb buttons on detail pages (Approve, Reject, Assign,
    Escalate, Send, Archive, Publish) → ALWAYS declare.
  * "Back / Cancel / Close" / breadcrumb links → DO NOT declare (they're
    generic navigation the shell handles).
  * "New X" / "Add X" on list toolbars → DO NOT declare (the CRUD
    invariant emits the button deterministically).
  * "Edit" / "Delete" row actions on lists → DO NOT declare (the CRUD
    builder emits them).

WORKED EXAMPLE — an approve/reject flow on the applicant detail page:

  {
    "data_models": [{"name": "Applicant", ...}, {"name": "Notification"}],
    "workflows": [
      {
        "name": "ApproveApplicant",
        "source": {"kind": "button", "page": "ApplicantDetail"},
        "inputs": [
          {"name": "applicantId", "type": "uuid",   "required": true,
           "source": {"kind": "route", "param": "id"}},
          {"name": "reviewerId",  "type": "uuid",   "required": true,
           "source": {"kind": "auth",  "claim": "user.id"}},
          {"name": "decision",    "type": "string", "required": true,
           "source": {"kind": "static", "value": "approved"}}
        ],
        "steps": [...]
      },
      {"name": "RejectApplicant", "source": {"kind": "button",
                                             "page": "ApplicantDetail"}, ...}
    ],
    "pages": [{
      "name": "ApplicantDetail", "route": "/applicants/[id]",
      "actions": [
        {"label": "Approve", "kind": "workflow",
         "target": "ApproveApplicant",
         "variant": "primary",
         "requires_confirm": true,
         "input_map": {
           "applicantId": {"kind": "route", "param": "id"},
           "reviewerId":  {"kind": "auth",  "claim": "user.id"},
           "decision":    {"kind": "static", "value": "approved"}
         }},
        {"label": "Reject", "kind": "workflow",
         "target": "RejectApplicant",
         "variant": "danger",
         "requires_confirm": true,
         "input_map": {
           "applicantId": {"kind": "route", "param": "id"},
           "reviewerId":  {"kind": "auth",  "claim": "user.id"}
         }},
        {"label": "View history", "kind": "navigate",
         "target": "/applicants/[id]/history"}
      ]
    }]
  }

CONSISTENCY RULES the plan validator enforces:

  * `action.kind` must be "workflow" or "navigate".
  * `action.target` for kind=workflow MUST name a real workflow.
  * `action.target` for kind=navigate MUST name a real page route.
  * Every `input_map` value must have `kind` in
    {form_field, route, auth, static, computed}.
  * `input_map` route sources must name a param declared in the
    page's route (`/applicants/[id]` → route.param `id`).

If a page has no domain-action buttons (a plain list, a form page),
omit `actions` entirely. The contract is opt-in.
"""


# ══════════════════════════════════════════════════════════════════════════
# Executable-plan contract — the plan must be runnable, not interpretable.
# ══════════════════════════════════════════════════════════════════════════
#
# Every downstream stage (schema-page emitter, workflow builder, seed
# synthesizer, runtime dispatcher) reads the plan and emits an artifact.
# When a fact the emitter needs is missing, the LLM or a guard has to
# guess — and every mechanical bug we've fixed this quarter has traced
# back to one of those guesses being wrong. This block names the five
# facts every plan MUST carry so no downstream stage has to invent.
#
# The plan_completeness_validator enforces these rules; the strict-mode
# gate (FORGE_STRICT_PLAN) halts generation if any of them fire.
_ONESHOT_SYSTEM_PROMPT = _ONESHOT_SYSTEM_PROMPT + "\n\n" + r"""
═══════════════════════════════════════════════════════════════════════════
EXECUTABLE-PLAN CONTRACT — five facts every plan MUST carry
═══════════════════════════════════════════════════════════════════════════

A plan is EXECUTABLE when the deterministic emitters can produce every
artifact WITHOUT guessing. When a fact is missing, downstream invents —
and inventions drift. Every rule below closes one drift class.

Author every page and every entity so ALL FIVE facts below hold. The
validator will REJECT the plan and force a REVISE turn otherwise.

────────────────────────────────────────────────────────────────────────
1. LIST PAGES DECLARE THEIR dataSource — with the entity, not a slug
────────────────────────────────────────────────────────────────────────
Every page whose `archetype` is `list`, `table`, `kanban`, `board`,
`grid`, or `calendar` MUST declare:

    "dataSource": {"entity": "<PlannedEntityName>", "op": "list"}

`entity` MUST be the name of an entity in this plan's `entities` — not
`"users"` on a page that shows Carer rows. This closes the "every
persona page shows every user" drift.

Persona pages are the common trap. When you author `/carers`,
`/elderly-users`, `/guardians`, each one names its OWN entity:

    { "route": "/carers",       "archetype": "list",
      "dataSource": {"entity": "Carer",       "op": "list"} }
    { "route": "/elderly-users","archetype": "list",
      "dataSource": {"entity": "ElderlyUser", "op": "list"} }

────────────────────────────────────────────────────────────────────────
2. EVERY PAGE DECLARES actions[] — even when empty
────────────────────────────────────────────────────────────────────────
Every page MUST include an `actions` field. It may be `[]` for pages
with no user-triggered controls (dashboards, banners). The field being
ABSENT is a validator error — the emitter cannot distinguish "no
actions" from "planner forgot" and will invent.

Each entry is `{"label": "<visible text>", "kind": "<one-of>", "target": "<...>"}`
with `kind` in exactly this set:

    workflow  — click dispatches a workflow (target = workflow name)
    navigate  — click routes to another page (target = route)
    external  — click opens a URL outside the app (target = url)
    none      — decorative / view-only (target may be omitted)

Use `kind: "none"` for decorative controls (an info banner button, a
disabled placeholder). This is the AFFIRMATIVE way to say "unattached
on purpose" — never leave a button dangling.

────────────────────────────────────────────────────────────────────────
3. EVERY action.target RESOLVES against this plan
────────────────────────────────────────────────────────────────────────
For `kind: "workflow"`, `target` MUST name an entry in `workflows[]`.
For `kind: "navigate"`, `target` MUST match a page `route` in this
plan (`/carers/:id` and `/carers/[id]` are treated as equal).

If you'd write `{"target": "CreateUser"}` but you haven't added a
CreateUser workflow, ADD the workflow — do not leave the reference
dangling. This closes the "phantom workflow" drift.

────────────────────────────────────────────────────────────────────────
4. EVERY REFERENCED workflow HAS AT LEAST ONE STEP
────────────────────────────────────────────────────────────────────────
If any action.target names a workflow, that workflow's `steps` (or
`definition.nodes`) must have at least one entry — typically an
`actionType: "db_insert" | "db_update" | "db_delete" | ...` step. An
empty workflow silently drops the click; the runtime shows no error.

────────────────────────────────────────────────────────────────────────
5. EVERY NON-INTERNAL ENTITY HAS AT LEAST ONE PAGE
────────────────────────────────────────────────────────────────────────
If you add an entity to `entities`, either:
  (a) surface it on at least one page whose `dataSource.entity` (or
      `entity`) equals its name, OR
  (b) mark it `"internal": true` when it's system bookkeeping (audit
      logs, join tables, delivery queues, event journals).

An entity with no page and no `internal: true` is almost always a
missed feature — PaymentMethod exists in the DB but the user can never
manage cards, Notification exists but there's no inbox. Fix the
omission, don't hide it.

────────────────────────────────────────────────────────────────────────
Complete example (recruiting app, three entities, one workflow)
────────────────────────────────────────────────────────────────────────

  {
    "entities": {
      "Applicant":    {"table": "applicants",    "fields": {...}},
      "PaymentMethod":{"table": "payment_methods","fields": {...}},
      "AuditLog":     {"table": "audit_logs",    "internal": true,
                       "fields": {...}}
    },
    "workflows": [
      {"name": "CreateApplicant",
       "steps": [{"actionType": "db_insert", "table": "applicants",
                  "values": {"name": "name", "email": "email"}}]}
    ],
    "pages": [
      { "route": "/applicants", "archetype": "list",
        "dataSource": {"entity": "Applicant", "op": "list"},
        "actions": [
          {"label": "New applicant",   "kind": "workflow",
           "target": "CreateApplicant"},
          {"label": "View details",    "kind": "navigate",
           "target": "/applicants/[id]"}
        ] },
      { "route": "/applicants/[id]", "archetype": "detail",
        "entity": "Applicant",
        "actions": [] },
      { "route": "/settings/payment-methods", "archetype": "list",
        "dataSource": {"entity": "PaymentMethod", "op": "list"},
        "actions": [
          {"label": "Add card", "kind": "navigate",
           "target": "/settings/payment-methods/new"}
        ] }
      // AuditLog has no page — internal: true covers it.
    ]
  }
"""

# ── Spec D W2 — column/entity semantic hints (oneshot version) ──
# Short-form of the field-level authoring rules the multi-turn planner
# gets in the block starting with "COLUMN / ENTITY SEMANTIC HINTS".
# Downstream classifiers (scheduler_pass / user_fk_types / fk_semantics /
# semantic_field_types) honour these verbatim when they're in the closed
# set, and fall through to their legacy regex/word-list heuristic otherwise.
_ONESHOT_SYSTEM_PROMPT = _ONESHOT_SYSTEM_PROMPT + "\n\n" + r"""
═══════════════════════════════════════════════════════════════════════════
COLUMN / ENTITY SEMANTIC HINTS (optional — Spec D W2)
═══════════════════════════════════════════════════════════════════════════

Four small OPTIONAL fields that short-circuit downstream classifiers.
Only author when the classifier's obvious default (SQL type + column
name regex) would misfire for the domain. Omit otherwise.

1. `entity.schedulable_by` — top-level on ENTITY:
     "resource"  — this entity is the ROW of a booking timeline
                   (Room, Court, Doctor). Downstream renders a
                   ResourceTimeline on the matching list page.
     "person"    — this entity is a person on a booking. Rare.
     "none" | false — opt out; force the timeline off even when the
                   name would trigger it.
   Omit when the entity name is a stock resource word (Room, Vehicle).

2. `field.user_fk_role` — per-COLUMN, on FKs pointing at User only:
     "actor" | "assignment" | "tenancy" | "audit"
   Tells the SQL rewriter to change the column's type from uuid to
   integer (users.id is serial). Only author on domain-shaped column
   names the legacy allowlist wouldn't catch (e.g. `primaryOwnerRefId`).

3. `field.role` — per-COLUMN, on ANY FK:
     "actor" | "assignment" | "tenancy" | "domain"
   Names the app-domain role the FK plays (for RBAC + layout).
   Both `role` and `user_fk_role` may coexist on a User FK.

4. `field.semantic.control` — per-COLUMN, blob-nested:
     "Input" | "Textarea" | "Select" | "Combobox" | "NumberInput"
     | "DatePicker" | "Switch" | "FileUpload"
   Force a form-control kind when the classifier's default is wrong.

Examples:
  {"name": "Bay", "schedulable_by": "resource", "fields": [...]}

  {"name": "primaryOwnerRefId", "type": "uuid",
   "fk": {"table": "users", "column": "id"},
   "user_fk_role": "actor"}

  {"name": "projectId", "type": "uuid",
   "fk": {"table": "projects", "column": "id"},
   "role": "domain"}

  {"name": "tier", "type": "varchar",
   "semantic": {"control": "Select",
                "enum_values": ["Gold", "Silver", "Bronze"]}}

Values outside the closed sets are silently dropped by the plan
normalizer — the classifier's legacy fallback runs. Only author what
the closed sets accept. When in doubt, omit.
"""


def _extract_plan_object(text: str) -> dict | None:
    """Best-effort parser for the one-shot planner response.

    Tolerates the common drift modes Sonnet exhibits even with strict prompts:
    leading prose, trailing commentary, accidental ```json fences. Slices
    from the first `{` to the last `}` and json.loads that.
    """
    import json
    s = (text or "").strip()
    # Strip markdown fences if present
    if s.startswith("```"):
        nl = s.find("\n")
        if nl != -1:
            s = s[nl + 1 :]
        if s.rstrip().endswith("```"):
            s = s.rstrip()[: -3].rstrip()
    start = s.find("{")
    end = s.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(s[start : end + 1])
    except json.JSONDecodeError:
        return None


def _normalize_oneshot_plan(plan: dict) -> dict:
    """Convert the oneshot plan shape to what the pipeline expects.

    `_ONESHOT_SYSTEM_PROMPT` emits `entities` as a DICT ({"Task": {table, fields, ...}}),
    but create_registry / the schema agent / the gates all read `data_models` as a LIST.
    Without this, every SDK-planner plan registers 0 entities -> no schema -> broken app.
    Also derives best-effort `relations` from each entity's `depends_on`. Idempotent.
    """
    if not isinstance(plan, dict):
        return plan
    ents = plan.get("entities")
    if isinstance(ents, dict) and ents and not plan.get("data_models"):
        models: list[dict] = []
        relations: list[dict] = list(plan.get("relations") or [])
        have_rel = {(r.get("from"), r.get("to")) for r in relations if isinstance(r, dict)}
        for name, spec in ents.items():
            if not isinstance(spec, dict):
                continue
            raw_fields = spec.get("fields") or []
            # One-shot planner emits fields as a LIST of {name, type, ...} dicts.
            # The two-stage app-map skeleton emits fields as a name→type DICT
            # ("id": "uuid"). Coerce the dict shape into the list shape the
            # rest of the pipeline expects; without this the skeleton path
            # produces entities with fields=[] and the whole app has no columns.
            if isinstance(raw_fields, dict):
                raw_fields = [
                    {"name": fname, "type": ftype}
                    for fname, ftype in raw_fields.items()
                    if isinstance(fname, str)
                ]
            fields = [f for f in raw_fields if isinstance(f, dict)]
            for f in fields:
                if f.get("name") == "id":
                    f.setdefault("primaryKey", True)
            models.append({
                "name": name,
                "table": spec.get("table"),
                "fields": fields,
                "indexes": spec.get("indexes") or [],
            })
            for dep in spec.get("depends_on") or []:
                if (name, dep) not in have_rel:
                    relations.append({"from": name, "to": dep, "type": "many-to-one"})
                    have_rel.add((name, dep))
        plan["data_models"] = models
        if relations:
            plan["relations"] = relations
    plan.setdefault("module_name", plan.get("domain") or "app")

    # Slice A T2 — SUBMIT-AUTHORITY backward-compat: default
    # ``page.submit`` to ``{"kind":"data_api","target":<entity>}`` for
    # every form-typed page that names an entity but omits ``submit``.
    # Two reasons:
    #   1. Old plans (generated before the prompt required the
    #      declaration) still validate — nothing hard-fails on legacy
    #      chats/retries just because they lack the new field.
    #   2. When the planner does emit submit explicitly (the common
    #      path once the prompt is updated), the ``setdefault``-style
    #      no-op preserves it verbatim — no clobbering.
    # Non-form pages (list/detail) get nothing — they don't submit.
    # Form pages with NO entity get nothing — the validator (T3)
    # surfaces those as genuine plan gaps for the user to correct.
    _add_default_submit_authority(plan)
    return plan


def _add_default_submit_authority(plan: dict) -> None:
    """Insert ``page.submit = {kind:'data_api', target:<entity>}`` on
    every form page that has an entity but no declared submit target.
    Mutates ``plan`` in place. Idempotent."""
    pages = plan.get("pages")
    if not isinstance(pages, list):
        return
    for page in pages:
        if not isinstance(page, dict):
            continue
        if str(page.get("type") or "").lower() != "form":
            continue
        if isinstance(page.get("submit"), dict) and page["submit"].get("target"):
            continue  # already declared — preserve
        entity = page.get("entity")
        if not isinstance(entity, str) or not entity:
            continue  # no entity → no default; validator will flag
        page["submit"] = {"kind": "data_api", "target": entity}


async def run_planner_oneshot(
    description: str,
    domain_context: dict | None = None,
    *,
    # 900s (15 min) because streaming a 32K-token plan is sequential —
    # tokens arrive one at a time from the model server, so wall-clock
    # elapsed time scales with output size. A rich ATS plan produces
    # ~20-25K output tokens; at typical stream rates that's 4-6 minutes,
    # comfortably under 15 but past the old 300s cap.
    timeout_seconds: float = 900.0,
    prior_plan: dict | None = None,
    emit_fn: Any = None,
    allow_revise: bool = True,
) -> dict:
    """Produce a complete plan dict from a description in a single LLM call.

    Returns the parsed plan as a dict. Raises RuntimeError if no API key is
    set or if the model output can't be parsed into a plan after one retry.

    When ``prior_plan`` is supplied AND marked ``_figma_driven``, skip the LLM
    call entirely and just return it (with page-type annotation applied).
    This lets the Figma-driven flow short-circuit the LLM planner — Figma is
    authoritative for scope when present.

    This is the headless contract. The chat-style `run_planner` is for
    interactive flows where users may want to clarify before committing.
    """
    # Short-circuit: Figma-driven plan needs no LLM call.
    if prior_plan and prior_plan.get("_figma_driven"):
        return _annotate_page_types(_normalize_oneshot_plan(prior_plan))

    import asyncio
    from services.domain_context import build_domain_profile

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "run_planner_oneshot requires ANTHROPIC_API_KEY. Set it in the "
            "backend env (see backend/.env.example) or use the chat-based "
            "run_planner instead."
        )

    system_prompt = _ONESHOT_SYSTEM_PROMPT + build_domain_profile(
        domain_context, "planner"
    )

    # USER-NAMED CONSTRAINTS — extracted verbatim from the brief so the
    # planner cannot silently rename `/history` → `/batches`, swap
    # `ocr_document` for `http_call`, or drop `Table` for `Kanban`. The
    # requirement-fidelity critic gates on the SAME contract at
    # post-gen — this block gives the LLM its best shot at getting it
    # right first-pass so REVISE doesn't have to catch every drift.
    contract_block = ""
    try:
        from services.requirement_contract import extract_contract
        contract = extract_contract(description or "")
        if any([contract.named_routes, contract.named_components,
                contract.named_action_types, contract.landing_route,
                contract.out_of_scope]):
            lines: list[str] = ["USER-NAMED CONSTRAINTS (must use verbatim — do not rename, do not substitute):"]
            if contract.named_routes:
                paths = [r["path"] for r in contract.named_routes]
                lines.append(f"  Routes ({len(paths)}): {', '.join(paths)}")
                lines.append(
                    "    → emit EACH route as a page with that EXACT path. "
                    "Do NOT rewrite `/history` → `/batches` or `/upload` → `/batches/new`."
                )
            if contract.landing_route:
                lines.append(f"  Landing: {contract.landing_route}")
                lines.append(
                    "    → set nav-flow.initialPage so this route serves as the app's landing. "
                    "Do NOT default to `/login` — the auth gate wraps the landing, doesn't replace it."
                )
            if contract.named_components:
                by_page: dict[str, list[str]] = {}
                for nc in contract.named_components:
                    by_page.setdefault(nc["page"], []).append(nc["component"])
                lines.append(f"  Components (on named pages):")
                for page, comps in by_page.items():
                    lines.append(f"    {page}: {', '.join(sorted(set(comps)))}")
                lines.append(
                    "    → each named component MUST appear in that page's schema. "
                    "Do NOT swap Table for Kanban, DescriptionList for a plain Card, or drop FileUpload."
                )
            if contract.named_action_types:
                by_wf: dict[str, list[str]] = {}
                for at in contract.named_action_types:
                    key = at.get("workflow") or "(any workflow)"
                    by_wf.setdefault(key, []).append(at["action_type"])
                lines.append(f"  Action types (in named workflows):")
                for wf, ats in by_wf.items():
                    lines.append(f"    {wf}: {', '.join(sorted(set(ats)))}")
                lines.append(
                    "    → use each action-type VERBATIM as `actionType`. "
                    "Do NOT substitute `http_call` for `ocr_document` (or any other named primitive) "
                    "even when the sidecar could technically be reached over HTTP."
                )
            if contract.out_of_scope:
                lines.append(f"  Out of scope ({len(contract.out_of_scope)}):")
                for phrase in contract.out_of_scope[:6]:
                    lines.append(f"    - {phrase[:100]}")
                lines.append(
                    "    → do NOT emit pages, workflows, or nav items for surfaces marked out-of-scope."
                )
            contract_block = "\n".join(lines) + "\n\n"
    except Exception as _exc:  # noqa: BLE001 — never break the planner
        contract_block = ""

    user_prompt = (
        f"{contract_block}"
        f"App brief:\n{description.strip()}\n\n"
        "Emit the plan JSON now. Single object, no prose, no fences."
    )

    from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim
    client = llm_client.AsyncAnthropic(api_key=api_key)

    from services.streaming_llm import stream_and_emit

    # Semantic watcher — turns a raw JSON stream into meaningful "the
    # planner just decided X" events. Called after each raw chunk emit
    # with the accumulated text so far; returns a list of NEW landmark
    # events to emit as ``planner_call_semantic``.
    #
    # Watches for:
    #   * top-level SECTION entry — ``"data_models": [`` → "Defining entities…"
    #   * every top-level PRIMITIVE slot declared (audit_trail, wizards, …)
    #   * every ``"name": "Foo"`` occurrence — reported as authored items,
    #     dedup'd so we don't spam. The name shows up once per string.
    #
    # State lives inside the closure so each planner call gets its own.
    def _make_planner_semantic_watcher():
        sections_seen: set[str] = set()
        names_seen:    set[str] = set()
        _sections = {
            "actors":                "Enumerating actors",
            "data_models":           "Defining entities",
            "dataModels":            "Defining entities",
            "entities":              "Defining entities",
            "workflows":             "Authoring workflows",
            "pages":                 "Laying out pages",
            "audit_trail":           "Adding audit-trail primitive",
            "immutability":          "Adding immutability primitive",
            "field_visibility":      "Adding field-visibility primitive",
            "capacity_constraints":  "Adding capacity-constraints primitive",
            "wizards":               "Adding wizard primitive",
        }
        import re
        # Match ``"name": "Some Value"`` — the value has ≤ 60 chars of
        # non-quote content. Captures the value.
        _name_rx = re.compile(r'"name"\s*:\s*"([^"\n]{1,60})"')

        def _watch(total: str) -> list[dict]:
            events: list[dict] = []
            for key, humanized in _sections.items():
                if key in sections_seen:
                    continue
                if f'"{key}":' in total:
                    sections_seen.add(key)
                    events.append({
                        "text":    f"{humanized}…",
                        "section": key,
                    })
            for m in _name_rx.finditer(total):
                nm = m.group(1).strip()
                if not nm or nm in names_seen:
                    continue
                names_seen.add(nm)
                events.append({
                    "text": f"+ {nm}",
                    "item": nm,
                })
            return events
        return _watch

    async def _call(prompt: str) -> str:
        # Stream the plan JSON so the caller can push per-chunk SSE events
        # (typewriter progress bar during the 3-5 min planner run). Falls
        # back to non-streaming on any client that lacks .messages.stream
        # so tests that pass a plain fake client still work.
        if hasattr(client, "messages") and hasattr(client.messages, "stream"):
            return await stream_and_emit(
                client,
                stage="planner_call",
                model="claude-sonnet-4-6",
                # 32K to accommodate plans that declare platform primitives
                # (audit_trail, immutability, field_visibility, capacity_constraints,
                # wizards) — the primitive-slot documentation in the system prompt
                # pushes the model to author richer plans that exceeded the old
                # 16K cap on domain-heavy runs like the ATS.
                # 24K after Slice-terse: the TERSENESS section in
                # _ONESHOT_SYSTEM_PROMPT (see line ~1849) tells the
                # model this is a HARD cap and to skip descriptions.
                # A leaner plan streams ~30% faster because output
                # tokens ARE the wall-clock bottleneck (~50-100 tok/s).
                max_tokens=24000,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
                timeout_seconds=timeout_seconds,
                emit_fn=emit_fn,
                started_text="Authoring plan…",
                semantic_watcher=_make_planner_semantic_watcher(),
            )
        msg = await asyncio.wait_for(
            client.messages.create(
                model="claude-sonnet-4-6",
                # 24K after Slice-terse: the TERSENESS section in
                # _ONESHOT_SYSTEM_PROMPT (see line ~1849) tells the
                # model this is a HARD cap and to skip descriptions.
                # A leaner plan streams ~30% faster because output
                # tokens ARE the wall-clock bottleneck (~50-100 tok/s).
                max_tokens=24000,
                system=system_prompt,
                messages=[{"role": "user", "content": prompt}],
            ),
            timeout=timeout_seconds,
        )
        return "".join(b.text for b in msg.content if hasattr(b, "text"))

    text = await _call(user_prompt)
    plan = _extract_plan_object(text)
    if plan is None:
        # One retry with a sharper fixup. Models occasionally drift on first
        # call despite the hard contract — single fixup turn handles it.
        fixup = (
            f"App brief:\n{description.strip()}\n\n"
            "Your previous response did not contain a parseable JSON object. "
            "Output ONLY the plan JSON now — first char `{`, last char `}`, "
            "nothing else."
        )
        text2 = await _call(fixup)
        plan = _extract_plan_object(text2)
        if plan is None:
            raise RuntimeError(
                f"run_planner_oneshot: model failed to emit valid JSON after retry. "
                f"First response head: {text[:200]!r} | retry head: {text2[:200]!r}"
            )

    plan = _annotate_page_types(_normalize_oneshot_plan(plan))

    # Completeness gate — check that every downstream authority has the
    # authority it needs. When violations exist, feed them back through
    # the planner's REVISE MODE (single retry). This closes the loop
    # opened by Slices 1-5: readers prefer plan declarations, and the
    # planner is required to make them.
    try:
        from services.plan_completeness_validator import (
            format_revise_gaps,
            validate_plan_completeness,
        )
    except Exception:  # noqa: BLE001
        return plan   # validator import shouldn't ever fail a generation

    violations = validate_plan_completeness(plan)

    # ── Coverage critic (REL-S2) ──────────────────────────────────────
    # Independent LLM pass that checks whether the plan covers what the
    # brief says or a reasonable domain reading implies. Fixes silent
    # planner omissions (e.g. brief says "notify managers" but plan has
    # no Notification entity) that no mechanical repair can catch —
    # adding them at post-gen would be hallucination, not repair. Gated
    # by FORGE_COVERAGE_CRITIC to bound cost during rollout.
    try:
        from services.plan_coverage_critic import (
            critique_coverage,
            is_coverage_critic_enabled,
            to_violations as _coverage_to_violations,
        )
        if is_coverage_critic_enabled() and allow_revise:
            # The critic works on prompt+plan alone; the brief cache is
            # keyed by domain slug which the planner doesn't have here
            # (domain_context is loose). Skipping brief injection means
            # the critic reads the raw prompt for domain register/
            # signature-move hints — still gets ~80% of the value.
            coverage_gaps = await critique_coverage({}, description or "", plan)
            if coverage_gaps:
                extra = _coverage_to_violations(coverage_gaps)
                logger.info(
                    "[planner] coverage critic found %d gap(s): %s",
                    len(extra),
                    ", ".join(v.rule for v in extra),
                )
                violations = list(violations) + list(extra)
    except Exception as exc:  # noqa: BLE001
        # Never fail generation because the critic module broke — coverage
        # is an ADDITIVE reliability lever, not a required gate.
        logger.warning("[planner] coverage critic skipped: %s", exc)

    if not violations:
        return plan
    if not allow_revise:
        # Fast profile (Task 3): skip the completeness REVISE re-stream (a full
        # 24K-token plan, +4-8 min). Downstream readers already fall back to
        # their own derivation for any silent fields, so this degrades cleanly.
        logger.info(
            "[planner] fast build — skipping completeness revise (%d gap(s) logged)",
            len(violations),
        )
        return plan

    import json as _json
    revise_prompt = (
        f"{format_revise_gaps(violations)}\n\n"
        f"Prior plan (for reference — apply the gaps ABOVE to this):\n"
        f"{_json.dumps(plan, indent=2)}"
    )
    text3 = await _call(revise_prompt)
    revised = _extract_plan_object(text3)
    if revised is None:
        # Model failed to revise cleanly — accept the incomplete plan and
        # log. Downstream readers already fall back to their existing
        # derivation for silent fields, so this degrades gracefully.
        return plan
    revised = _annotate_page_types(_normalize_oneshot_plan(revised))
    # Return the revised plan even if not fully complete — a partial fix
    # is still better than the original, and forcing another round would
    # inflate generation time. (One retry is the standard REVISE budget.)
    return revised
