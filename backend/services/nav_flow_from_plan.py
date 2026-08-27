"""Build a nav-flow.json structure from a planner's plan.pages list.

Auto-classifies routes as auth (shell:false) vs shell (shell:true) based
on page.type, then derives post_login_redirect / post_logout_redirect.

Mirrors the auto-classification in figma_mcp_pipeline._upsert_nav_flow
so LLM and Figma pipelines produce equivalent nav-flow shapes.

Routes are normalised through `:param` → `[param]` (Next.js convention) and
schema filenames replace dynamic segments with 'detail' to match how the
schema agent writes files (e.g. `/users/[id]` → `src/schemas/users/detail.json`).
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# Auth-route prefixes — pages whose route matches these are treated as
# auth pages regardless of the planner's `type` annotation. This mirrors
# the check in services/nav_flow_from_schemas.py (SP1.5-F1) — the plan-
# driven emitter used to only check ``type == "auth"``, so a signup page
# the planner mislabeled as ``type: "form"`` would end up in the app
# shell (visible in the sidebar). Now: route wins.
_AUTH_ROUTE_PREFIXES = (
    "/login", "/signin", "/sign-in", "/signup", "/sign-up", "/register",
)


def nav_flow_from_plan(plan: dict[str, Any],
                       product_brief: Any = None) -> dict[str, Any]:
    """Emit nav-flow.json from plan.pages.

    plan.pages entries are expected to have:
      - id: str (page identifier — used as a hint, but always normalised
              for filesystem safety; planner ids like 'users-:id' become
              'users-detail')
      - route: str (URL route — `:param` and `[param]` both accepted)
      - name: str (display title)
      - type: str (page type from classify_page — auth/dashboard/form/list/detail)

    PB-4: when ``product_brief`` is supplied (from PB-2's persistence),
    the returned nav-flow gains a ``personas`` field describing the
    top-level persona pills + per-persona job groupings that
    persona-tab shell frames read. The pages array is unchanged so
    every existing consumer keeps working — ``personas`` is purely
    additive metadata a persona-aware shell frame can opt into.
    """
    pages_in = plan.get("pages", []) or []
    pages_out: list[dict[str, Any]] = []
    auth_routes: list[str] = []

    for p in pages_in:
        if not isinstance(p, dict):
            continue
        route = _normalise_route(p.get("route") or "")
        # Page id: prefer planner's id but always sanitise for filesystem
        page_id = _sanitise_id(p.get("id") or "") or _slug_from_route(route) or "page"
        page_type = (p.get("type") or "").lower()
        # Route wins: /login, /signup, /register etc. are ALWAYS auth
        # pages even if the planner labeled them ``type: "form"``. This
        # keeps auth routes out of the shell (SP1.5-F1 parity for the
        # plan-driven path).
        is_auth = (
            page_type == "auth"
            or any(route.startswith(pfx) for pfx in _AUTH_ROUTE_PREFIXES)
        )
        entry = {
            "id": page_id,
            "route": route,
            "title": p.get("name") or _humanize(page_id),
            "schemaFile": _schema_file_from_route(route),
            "shell": not is_auth,
        }
        # Optional role gate (slice B): pages the planner marks as owned by
        # a specific actor get a ``visibleTo`` array so the runtime shell +
        # renderer can hide the route from other roles. Accepts either
        # ``page.visibleTo: [...]`` (canonical) or ``page.roles: [...]`` /
        # ``page.role: "..."`` (aliases). ``visibleTo=null`` = public.
        vt = _read_visible_to(p)
        if vt is not None:
            entry["visibleTo"] = vt
        pages_out.append(entry)
        if is_auth:
            auth_routes.append(route)

    nav_flow: dict[str, Any] = {
        "version": "1.0",
        "pages": pages_out,
        "auth_routes": auth_routes,
        "transitions": [],
        "guards": {},
    }
    if pages_out:
        nav_flow["initialPage"] = pages_out[0]["id"]
    non_auth = [p["route"] for p in pages_out if p["shell"]]
    if non_auth:
        nav_flow["post_login_redirect"] = non_auth[0]
    if auth_routes:
        nav_flow["post_logout_redirect"] = auth_routes[0]

    # Per-actor landing map — for each role the plan mentions (via any
    # page.visibleTo), pick the FIRST shell page in nav-flow order that
    # role can see. The app_emitter reads this to write a session-aware
    # root-redirect (admin → /dashboard, candidate → /profile/cv-upload,
    # …) instead of a single hardcoded target that pushes every session
    # to the same page. A public shell page (visibleTo=None) counts as
    # visible to everyone, so a role missing an explicit page still
    # lands somewhere real.
    initial_for: dict[str, str] = {}
    roles_seen: set[str] = set()
    for p in pages_out:
        for r in (p.get("visibleTo") or []):
            if isinstance(r, str) and r.strip():
                roles_seen.add(r.strip())
    for role in roles_seen:
        for p in pages_out:
            if not p.get("shell"):
                continue
            vt = p.get("visibleTo")
            if vt is None or role in vt:
                initial_for[role] = p["route"]
                break
    if initial_for:
        nav_flow["initialFor"] = initial_for

    # PB-4: attach persona metadata when a product brief is supplied.
    # This is READ-ONLY hinting for shell-frame builders — the pages
    # array is authoritative for routing/menus. A persona-aware frame
    # reads this to build top-level persona pills + per-persona job
    # tab groupings; a legacy frame ignores it entirely.
    _persona_meta = _persona_metadata_from_brief(product_brief, pages_out)
    if _persona_meta:
        nav_flow["personas"] = _persona_meta

    return nav_flow


def _persona_metadata_from_brief(product_brief: Any,
                                  pages_out: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """Turn a ProductBrief into nav-flow persona metadata.

    Returns a list of ``{id, name, role, jobs: [{id, label, route}]}``
    entries when the brief carries personas AND at least one page in
    ``pages_out`` can serve as a target for their jobs. Returns None
    when either input is empty (a persona-aware shell should then
    fall back to the pages-only nav).

    Job → route resolution:

      1. If the job declares ``primary_entities``, we look for a page
         whose route starts with ``/<entity>`` (first hit wins).
      2. Otherwise we look for a page whose title matches the job
         label (case-insensitive, punctuation-loose).
      3. Otherwise the job is dropped from the persona's nav — it
         would render as a dead link.

    Non-shell (auth) pages are excluded from resolution: nav pills
    should never point at ``/login``.
    """
    if product_brief is None:
        return None
    personas = getattr(product_brief, "personas", None)
    if not isinstance(personas, list) or not personas:
        return None

    # Build lookup: entity-slug → first shell page starting at that slug.
    shell_pages = [p for p in pages_out if p.get("shell")]
    if not shell_pages:
        return None

    entity_to_page: dict[str, dict[str, Any]] = {}
    for p in shell_pages:
        route = str(p.get("route") or "")
        m = None
        if route.startswith("/"):
            first = route.split("/", 2)[1] if "/" in route[1:] else route[1:]
            first = first.strip()
            if first:
                m = first.lower()
        if m and m not in entity_to_page:
            entity_to_page[m] = p

    title_to_page = {
        str(p.get("title") or "").strip().lower(): p
        for p in shell_pages
        if p.get("title")
    }

    out: list[dict[str, Any]] = []
    for persona in personas:
        p_id = getattr(persona, "id", None) or ""
        p_name = getattr(persona, "name", None) or ""
        p_role = getattr(persona, "role", None) or ""
        p_jobs = getattr(persona, "jobs", None) or []
        if not p_id or not p_name:
            continue
        job_entries: list[dict[str, Any]] = []
        for job in p_jobs:
            j_id = getattr(job, "id", None) or ""
            j_label = getattr(job, "label", None) or ""
            if not j_id or not j_label:
                continue
            j_entities = getattr(job, "primary_entities", None) or []
            target_page = None
            for ent in j_entities:
                ent_l = str(ent).strip().lower()
                if ent_l in entity_to_page:
                    target_page = entity_to_page[ent_l]
                    break
            if target_page is None:
                # Fallback: title match.
                target_page = title_to_page.get(j_label.strip().lower())
            if target_page is None:
                # Dead job — dropping it beats rendering a dead link.
                continue
            job_entries.append({
                "id": j_id,
                "label": j_label,
                "route": target_page["route"],
                "pageId": target_page["id"],
            })
        # Slice B (2026-08-13) — resolve `screens` from the archetype
        # vocabulary's per-persona primary screen list. Consumed by the
        # layout's second-tier sub-nav pill row. Best-effort — a missing
        # vocabulary or unresolvable slug leaves the list empty.
        _screens: list[dict[str, Any]] = []
        try:
            _screens = _resolve_persona_screens(product_brief, p_role, shell_pages) or []
        except Exception:  # noqa: BLE001 — persona metadata is best-effort
            _screens = []

        # Drop the persona only when BOTH jobs and screens resolve to
        # nothing — a persona with vocabulary-provided screens can still
        # render a useful sub-nav row even without brief-provided jobs
        # (which is the common case for booking-platform Instructor,
        # where the LLM-derived jobs use narrow entity slugs that don't
        # match the plan's nested routes).
        if not job_entries and not _screens:
            continue
        persona_entry: dict[str, Any] = {
            "id": p_id,
            "name": p_name,
            "role": p_role,
            "jobs": job_entries,
        }
        if _screens:
            # The vocabulary CURATES order; it must never TRUNCATE reach.
            # Only the screens it names that resolve to real pages survive
            # _resolve_persona_screens, so on the inventory build admin's
            # 5 named screens resolved to 1 — and because the layout
            # prefers `screens` over `jobs` wholesale, that persona shipped
            # a one-item sub-nav while its 4 real jobs sat unreachable
            # (live on 5u9du8jt). Vocabulary picks come first; every
            # remaining job is appended so coverage is never lost.
            _seen = {s.get("route") for s in _screens if isinstance(s, dict)}
            persona_entry["screens"] = _screens + [
                {"label": j["label"], "route": j["route"]}
                for j in job_entries if j.get("route") not in _seen
            ]
        out.append(persona_entry)

    return _drop_undifferentiated_personas(out)


def _persona_nav_signature(persona: dict) -> tuple:
    """What this persona's nav actually SHOWS, order-insensitive.

    `screens` wins when present (the layout prefers it wholesale), so the
    signature must read the same field the renderer does — comparing jobs
    while the layout renders screens would compare the wrong thing.
    """
    rows = persona.get("screens") or persona.get("jobs") or []
    return tuple(sorted(
        str(r.get("route") or "") for r in rows if isinstance(r, dict)))


def _drop_undifferentiated_personas(personas: list[dict] | None) -> list[dict] | None:
    """Return the personas, or None when the switcher would be a no-op.

    Live failure (49w6y3nd): member / committee_chair / secretary_general /
    public all resolved to the SAME four routes, so the persona pills
    rendered and clicking between them changed nothing — reported as "Roles
    shows same pages for all the roles".

    Identical personas are not a cosmetic problem. They advertise a per-role
    view the app does not have, and they hide the real gap: the plan named
    actors but never said which pages each may see. Returning None makes the
    shell fall back to one honest menu and leaves the gap visible.

    A single persona is always kept — there is nothing for it to duplicate.
    """
    if not personas:
        return None
    if len(personas) == 1:
        return personas
    sigs = [_persona_nav_signature(p) for p in personas]
    if len(set(sigs)) == 1:
        logger.warning(
            "nav-flow: %d personas (%s) all resolve to the same %d route(s) — "
            "dropping persona nav rather than rendering a switcher that "
            "changes nothing. The plan's actors carry no per-role page access.",
            len(personas), ", ".join(str(p.get("id")) for p in personas),
            len(sigs[0]),
        )
        return None
    return personas


def _resolve_persona_screens(product_brief: Any,
                              persona_role: str,
                              shell_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return ``[{label, route, icon}]`` for a persona's primary screens.

    Slice B (2026-08-13). Reads the archetype vocabulary's
    ``primary_screens_per_persona`` list (e.g. ``["schedule",
    "my-bookings", "membership", "reviews"]`` for a booking-platform
    member), then walks the plan's shell pages to resolve each screen
    slug to a real route.

    Match rules:
      1. Last path segment equals the slug (exact match, case-insensitive
         and hyphen/underscore-fluid).
      2. Slug appears anywhere in the route (fallback).
      3. Slug is a prefix of an entity-plural inflection (e.g.
         ``"booking"`` matches ``/bookings``).

    Unresolvable screens are dropped — a dead pill is worse than a
    missing one. Icon comes from :func:`services.nav_icon_map.icon_for`
    which returns a Lucide slug (falls back to ``"folder"``).
    """
    if not persona_role:
        return []
    archetype = getattr(product_brief, "archetype", None) if product_brief else None
    if not archetype:
        return []
    # Persona sub-nav resolution uses the BASE vocabulary's
    # primary_screens_per_persona directly. The composer's LLM-added personas
    # /section-recipes don't need to influence nav-flow — the base vocab's
    # per-persona screen list is authoritative for the sub-nav pill row.
    # (Earlier revision tried to call load_compose_and_modify_vocab_sync
    # here but referenced an undefined `plan` — the NameError was swallowed
    # by the outer try/except, leaving every persona with 0 screens.)
    try:
        from services.archetype_vocabulary import load_vocabulary
    except Exception:  # noqa: BLE001
        return []
    vocab = load_vocabulary(archetype)
    if vocab is None:
        return []
    screen_slugs = list(vocab.primary_screens_per_persona.get(persona_role, []))
    if not screen_slugs:
        return []

    # Icon helper — safe to import lazily; nav_icon_map is pure.
    try:
        from services.nav_icon_map import icon_for as _icon_for
    except Exception:  # noqa: BLE001
        def _icon_for(_):
            return "folder"

    # 2026-08-13 — prefer pages whose route STARTS with the persona role
    # prefix (e.g. Admin gets ``/admin/*`` before falling back to any
    # matching page). Without this, the "dashboard" slug for admin used to
    # land on ``/member/dashboard`` on multi-persona plans that share slugs
    # across role prefixes (yoga app: /member/dashboard, /instructor/dashboard,
    # /admin/dashboard). Ordered candidate list = role-prefixed first, then
    # everything else, so _match_screen_to_page's first-hit-wins logic
    # picks the persona's own page whenever one exists.
    role_prefixes = _role_route_prefixes(persona_role)
    ordered_pages: list[dict[str, Any]] = []
    if role_prefixes:
        prefixed = [p for p in shell_pages
                    if any(str(p.get("route") or "").startswith(pref)
                           for pref in role_prefixes)]
        rest = [p for p in shell_pages if p not in prefixed]
        ordered_pages = prefixed + rest
    else:
        ordered_pages = list(shell_pages)

    out: list[dict[str, Any]] = []
    seen_routes: set[str] = set()
    for slug in screen_slugs:
        page = _match_screen_to_page(slug, ordered_pages)
        if page is None:
            continue
        route = str(page.get("route") or "")
        if not route or route in seen_routes:
            continue
        seen_routes.add(route)
        label = _label_for_persona_screen(page, slug)
        out.append({
            "label": label,
            "route": route,
            "icon":  _icon_for(label),
        })
    return out


def _role_route_prefixes(persona_role: str) -> list[str]:
    """Return the plausible route-prefix forms a plan may use for a persona role.

    ``"studio_admin"`` → ``["/studio-admin/", "/studio_admin/", "/admin/"]``.
    Plain roles like ``"member"`` → ``["/member/"]``.
    Used to bias screen-slug resolution toward routes the persona actually
    owns before falling back to any matching page.
    """
    r = (persona_role or "").strip().lower()
    if not r:
        return []
    forms = {r, r.replace("_", "-"), r.replace("-", "_")}
    # Common alias collapse: any "*_admin" persona also owns "/admin/*".
    if r.endswith("_admin") or r.endswith("-admin"):
        forms.add("admin")
    out: list[str] = []
    for f in forms:
        pref = f"/{f}/"
        if pref not in out:
            out.append(pref)
    return out


def _norm_slug(s: str) -> str:
    """Lowercase + hyphen/underscore-collapse for fuzzy matching."""
    if not isinstance(s, str):
        return ""
    return re.sub(r"[^a-z0-9]+", "-", s.strip().lower()).strip("-")


def _match_screen_to_page(slug: str, shell_pages: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Best-effort match a vocabulary screen slug to a shell page.

    Tries in order:
      1. Exact match on the route's last path segment.
      2. Compound slug (``my-bookings``) matched by its trailing noun
         (``bookings``). Handles the "my-X" convention in vocabularies
         where the plan just exposes ``/X``.
      3. Slug is a token inside the route path.
    Returns None when nothing lands — the caller drops the pill.
    """
    target = _norm_slug(slug)
    if not target:
        return None
    target_plural = target if target.endswith("s") else f"{target}s"
    # Compound slugs like "my-bookings" or "upcoming-classes" — derive
    # a plain-noun alias from the last token so the vocabulary's
    # persona-scoped label ("my-bookings") still resolves to the
    # entity route the plan actually exposes ("/bookings"). Drops
    # persona-scope prefixes ("my", "upcoming") without hardcoding them.
    tail = target.rsplit("-", 1)[-1] if "-" in target else ""
    tail_plural = (tail + "s") if tail and not tail.endswith("s") else tail

    for p in shell_pages:
        route = str(p.get("route") or "")
        if not route:
            continue
        # Last segment: /schedule → schedule; /admin/users → users
        last = route.rstrip("/").rsplit("/", 1)[-1]
        last_n = _norm_slug(last)
        if last_n in (target, target_plural):
            return p
        if tail and last_n in (tail, tail_plural):
            return p
    # Fuzzy pass — slug appears anywhere in the route.
    for p in shell_pages:
        route = str(p.get("route") or "")
        route_n = _norm_slug(route)
        if not route_n:
            continue
        if target in route_n or target_plural in route_n:
            return p
        if tail and (tail in route_n or tail_plural in route_n):
            return p
    return None


def write_nav_flow(output_dir: str | "Path", nav_flow: dict) -> None:
    """Write nav-flow.json to <output_dir>/src/contracts/nav-flow.json."""
    import json
    from pathlib import Path
    p = Path(output_dir) / "src" / "contracts"
    p.mkdir(parents=True, exist_ok=True)
    (p / "nav-flow.json").write_text(json.dumps(nav_flow, indent=2))


# ────────────────────────────────────────────────────────────────────────
# Route + filename normalisation

_COLON_PARAM_RE = re.compile(r":(\w+)")
_BRACKET_PARAM_RE = re.compile(r"\[\w+\]")


def _normalise_route(route: str) -> str:
    """Convert Express-style `:param` to Next.js-style `[param]`."""
    if not route:
        return ""
    return _COLON_PARAM_RE.sub(lambda m: f"[{m.group(1)}]", route)


def _slug_from_route(route: str) -> str:
    """`/` → 'home', `/users/[id]` → 'users-detail', `/notes` → 'notes'."""
    if route in ("/", ""):
        return "home"
    cleaned = route.strip("/")
    if "[" in cleaned:
        # Replace any [param] with 'detail' for kebab id
        cleaned = _BRACKET_PARAM_RE.sub("detail", cleaned)
    return cleaned.replace("/", "-")


def _schema_file_from_route(route: str) -> str:
    """Map a normalised route to the schema file's relative path.

    Delegates to services.route_slug.slugify_route so this matches EXACTLY
    where page_schema_agent writes its files (out_path = src/schemas/<slug>.json).
    If the two disagree, the editor's read path can't find the file the
    agent wrote.

    Examples:
      /              → src/schemas/home.json
      /requests      → src/schemas/requests.json
      /requests/new  → src/schemas/requests/new.json
      /users/[id]    → src/schemas/users/[id].json  (Next.js bracket convention)
      /users/:id     → src/schemas/users/[id].json  (Express → Next.js normalised)
    """
    from services.route_slug import slugify_route
    slug = slugify_route(route)
    return f"src/schemas/{slug}.json"


def _sanitise_id(page_id: str) -> str:
    """Strip filesystem-hostile characters from a planner-supplied id.

    Planner often emits ids like 'workflows-:id'; we want a safe slug like
    'workflows-detail'. Conservative: replace any `:param` token with the
    literal 'detail' (matches the route-side convention).
    """
    if not page_id:
        return ""
    cleaned = _COLON_PARAM_RE.sub("detail", page_id)
    cleaned = _BRACKET_PARAM_RE.sub("detail", cleaned)
    # Drop anything that isn't safe for a filename
    cleaned = re.sub(r"[^A-Za-z0-9._-]", "-", cleaned)
    return cleaned.strip("-")


def _humanize(slug: str) -> str:
    return " ".join(w.capitalize() for w in slug.replace("-", " ").replace("_", " ").split())


# Raw page class-name IDs that leak through as "titles" when the plan
# author didn't supply a human-friendly ``name`` (or gave the same
# camelCase id). Rendered verbatim in the persona sub-nav they read as
# generator-output ("MemberSchedulePage", "AdminDashboardPage") instead
# of the intended user-facing label ("Schedule", "Dashboard").
_RAW_CLASSNAME_RE = re.compile(r"^[A-Z][a-zA-Z0-9]*Page$")

# Multi-word PascalCase with NO spaces (e.g. ``StudioSchedule``, ``MyBookings``,
# ``InstructorReviews``). Legitimately concise single-word titles like
# ``Home`` / ``Dashboard`` / ``Bookings`` are safe — this regex requires TWO
# capitalized runs. When a plan page title matches this, it's a raw class-name
# leak (the LLM planner echoed the page-id back into the ``title`` field), and
# we prefer the route-derived humanized label instead.
_MULTI_WORD_PASCAL_RE = re.compile(r"^[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]*)+$")

# Route segments that are DYNAMIC params, not meaningful nouns: Next.js
# ``[id]`` / ``[slug]`` catch-all, and the FastAPI / Express ``:param``
# style. Skipped when picking the last meaningful token from a route.
_PARAM_SEGMENT_RE = re.compile(r"^(\[.*\]|:.+|\.{3}.*)$")

# Common all-lowercase acronyms that should be uppercased in labels.
# Kept small — a false-positive uppercase (turning "id" mid-word) is
# more jarring than a missing acronym.
_ACRONYMS = {"id", "url", "api", "kpi", "sla", "faq", "ip", "ui", "ux",
             "pdf", "csv", "sql", "http", "https", "ssn", "vip"}


def _humanize_route(route: str) -> str:
    """Turn a URL route into a human-readable label using its last
    MEANINGFUL path segment.

    Rules:
      1. Drop the query string / fragment (defensive; routes shouldn't
         carry these but LLM output sometimes does).
      2. Walk segments from the end; skip any that are dynamic params
         (``[id]``, ``:slug``, ``...rest``) or empty.
      3. Replace ``-`` / ``_`` with spaces, title-case each word,
         uppercase common acronyms.
      4. Fall back to ``"Home"`` for ``/`` and empty routes.

    Examples::

        _humanize_route("/schedule")                 == "Schedule"
        _humanize_route("/member/bookings")          == "Bookings"
        _humanize_route("/instructor/sessions/[id]/roster") == "Roster"
        _humanize_route("/admin/dashboard")          == "Dashboard"
        _humanize_route("/kpis/api-usage")           == "API Usage"
    """
    if not route:
        return "Home"
    r = route.split("?", 1)[0].split("#", 1)[0]
    segments = [s for s in r.split("/") if s]
    if not segments:
        return "Home"
    # Pick the last non-dynamic segment.
    for seg in reversed(segments):
        if not _PARAM_SEGMENT_RE.match(seg):
            token = seg
            break
    else:
        return "Home"
    words = re.split(r"[-_]+", token)
    out_words: list[str] = []
    for w in words:
        if not w:
            continue
        if w.lower() in _ACRONYMS:
            out_words.append(w.upper())
        else:
            out_words.append(w[:1].upper() + w[1:].lower())
    return " ".join(out_words) or "Home"


def _label_for_persona_screen(page: dict, slug: str) -> str:
    """Pick the best label for a persona sub-nav pill.

    Precedence (first hit wins):
      1. ``page.title`` when it's a human-authored string — i.e. NOT a
         raw class-name like ``MemberSchedulePage`` (matches
         ``_RAW_CLASSNAME_RE``). This preserves genuinely authored
         labels like "My Schedule".
      2. A humanized version of the route's last meaningful segment.
      3. The archetype-vocabulary slug, humanized (last-resort).

    Returns a non-empty string in every case.
    """
    title = str(page.get("title") or "").strip()
    if title and not _RAW_CLASSNAME_RE.match(title) and not _MULTI_WORD_PASCAL_RE.match(title):
        return title
    route = str(page.get("route") or "")
    routed = _humanize_route(route)
    if routed and routed != "Home":
        return routed
    return _humanize(slug) or "Home"


def _read_visible_to(page: dict) -> list[str] | None:
    """Return the sanitized ``visibleTo`` role list from a plan page entry,
    or None when the page is public. Accepts either ``visibleTo``,
    ``roles`` (list), or ``role`` (scalar string) as input aliases —
    LLM plans routinely use whichever alias fits their sentence. Roles
    are stripped + de-duplicated; an empty list after cleanup is
    treated as public (returns None)."""
    raw = page.get("visibleTo")
    if raw is None:
        raw = page.get("roles")
    if raw is None:
        r = page.get("role")
        if isinstance(r, str) and r.strip():
            raw = [r]
    if not isinstance(raw, list):
        return None
    cleaned: list[str] = []
    for r in raw:
        if isinstance(r, str) and r.strip() and r.strip() not in cleaned:
            cleaned.append(r.strip())
    return cleaned or None
