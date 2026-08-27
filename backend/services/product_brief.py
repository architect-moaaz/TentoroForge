"""Product brief — the missing input for beautiful-app generation.

The plan already answers "what does the app DO?" (entities, workflows,
routes, actors). It does NOT answer "who is this app FOR and what do
they DO with it?" — the input every UX specialist starts from.

This module fills that gap. It composes a ``ProductBrief`` from three
sources:

- ``plan.actors`` (from ACTORS-B) → personas + their roles + onboarding
- ``plan.journeys`` (from JT-T1) → each actor's top jobs and moments
- ``design_brief`` (from PHASE-1-A) → voice notes + brand palette
- Small LLM enrichment → brand name/tagline/glyph, extra moment copy

Every downstream authoring step (shell frame picker, nav flow, page
schema agents, empty-state emitter, dashboard composer) reads this
brief to make persona-driven, job-oriented choices rather than
entity-driven CRUD choices.

Behind ``FORGE_PRODUCT_BRIEF=1`` for controlled rollout. When off, the
generator behaves exactly as before — this module is purely additive.

Persisted to ``contracts/product-brief.json`` for downstream reads and
Smith inspection.

Task: #662 (PB-1).
Design commitment: Path B — Forge = beautiful AND working app generator.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from services.archetype_keywords import plan_token_table

logger = logging.getLogger(__name__)


# ── env gate ─────────────────────────────────────────────────────────


_FLAG = "FORGE_PRODUCT_BRIEF"


def is_product_brief_enabled() -> bool:
    """Return True when the product-brief pipeline branch is on.

    Off by default so the change ships risk-free. Every downstream
    consumer must fall back gracefully to the pre-brief behaviour when
    this returns False.
    """
    raw = os.environ.get(_FLAG, "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


# ── schema ───────────────────────────────────────────────────────────


class Brand(BaseModel):
    """The invented product identity. LLM-authored from plan+domain.

    ``glyph`` is either a single emoji or a short symbolic name a
    downstream logo emitter can render as an SVG. Kept simple — a
    logo generator can grow later (see MOBILE-E for the pattern).
    """
    name: str = Field("", max_length=48)
    tagline: str = Field("", max_length=80)
    glyph: str = Field("", max_length=16)


class Job(BaseModel):
    """One thing a persona wants to do in the app.

    ``id`` is a stable slug callers key off. ``label`` is human-shown
    (nav item label, tab label). ``primary_entities`` are the plan
    entities this job reads/writes — the composer uses them to pick a
    default route + surface. ``moments`` is a curated subset of the
    named moments this job passes through, so per-page authoring can
    reach the right moment fast.
    """
    id: str = Field("", max_length=48)
    label: str = Field("", max_length=32)
    primary_entities: list[str] = Field(default_factory=list, max_length=6)
    moments: list[str] = Field(default_factory=list, max_length=8)


class Persona(BaseModel):
    """One kind of user of the app.

    A persona is a RE-INTERPRETATION of a plan actor as a product
    persona: same underlying identity (role in RBAC) plus product-
    thinking additions (a sample name for realistic seeding, a one-
    line context, and their top jobs). ``id`` matches the actor's
    role slug so RBAC and IA stay aligned.
    """
    id: str = Field("", max_length=48)
    name: str = Field("", max_length=32)          # display label
    role: str = Field("", max_length=32)          # RBAC role slug
    one_liner: str = Field("", max_length=140)
    sample_name: str | None = Field(None, max_length=48)  # for seed data
    jobs: list[Job] = Field(default_factory=list, max_length=8)


class Moment(BaseModel):
    """A specific point in a user's journey the app must handle well.

    Moments are the raw material the empty-state / copy / composer
    layers curate against. ``context`` describes when the user sees
    it (in plain prose). ``screen`` names the route it lives on.
    ``empty_copy`` is domain-voiced empty-state prose the empty-state
    guard can reach for instead of the mechanical TXT-1 template.
    """
    id: str = Field("", max_length=48)
    context: str = Field("", max_length=180)
    screen: str = Field("", max_length=80)        # route (leading slash)
    empty_copy: str | None = Field(None, max_length=200)


class VoiceNotes(BaseModel):
    """Editorial voice guidance for content-authoring agents.

    Distinct from design_brief.voice which covers TYPOGRAPHIC voice
    (font-pairings, tone-intensity). This covers COPYWRITING voice —
    the adjectives to write toward, sample CTAs, and words to avoid.
    """
    adjectives: list[str] = Field(default_factory=list, max_length=6)
    sample_ctas: list[str] = Field(default_factory=list, max_length=6)
    avoid: list[str] = Field(default_factory=list, max_length=8)


class ProductBrief(BaseModel):
    """The complete product brief — persisted as contracts/product-brief.json."""
    brand: Brand = Field(default_factory=Brand)
    personas: list[Persona] = Field(default_factory=list, max_length=8)
    archetype: str = Field("", max_length=48)      # booking-platform, crm, ...
    moments: list[Moment] = Field(default_factory=list, max_length=20)
    voice_notes: VoiceNotes = Field(default_factory=VoiceNotes)


# ── derivation from plan ─────────────────────────────────────────────


# Plan actor names → user-facing persona labels. Kept short + friendly.
# Downstream nav/tab rendering reads persona.name for the visible pill,
# so the label needs to feel like a natural product noun ("Member",
# "Instructor"), not the RBAC role slug ("member_role", "instr_admin").
def _humanize_role(role: str) -> str:
    if not isinstance(role, str) or not role.strip():
        return "User"
    s = role.strip().replace("_", " ").replace("-", " ")
    # split camelCase → space-separated
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", s)
    parts = [p for p in s.split() if p]
    # Common role synonyms → product labels.
    synonyms = {
        "admin":     "Admin",
        "staff":     "Staff",
        "manager":   "Manager",
        "customer":  "Customer",
        "member":    "Member",
        "student":   "Student",
        "instructor": "Instructor",
        "teacher":   "Teacher",
        "user":      "User",
        "employee":  "Employee",
        "owner":     "Owner",
        "operator":  "Operator",
        "buyer":     "Buyer",
        "seller":    "Seller",
        "vendor":    "Vendor",
        "client":    "Client",
        "guest":     "Guest",
        "provider":  "Provider",
        "reviewer":  "Reviewer",
        "requester": "Requester",
        "approver":  "Approver",
    }
    out = [synonyms.get(p.lower(), p.capitalize()) for p in parts]
    return " ".join(out) or "User"


def _slug(s: str) -> str:
    """kebab-case a label for use as an id."""
    if not isinstance(s, str):
        return ""
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "x"


def _actor_role(actor: Any) -> str:
    """Extract the RBAC role from an actor dict/model."""
    if isinstance(actor, dict):
        return str(actor.get("role") or actor.get("name") or "").strip()
    return str(getattr(actor, "role", None) or getattr(actor, "name", "") or "").strip()


def _actor_name(actor: Any) -> str:
    if isinstance(actor, dict):
        return str(actor.get("name") or actor.get("role") or "").strip()
    return str(getattr(actor, "name", None) or getattr(actor, "role", "") or "").strip()


def _actor_responsibilities(actor: Any) -> list[str]:
    if isinstance(actor, dict):
        r = actor.get("responsibilities")
    else:
        r = getattr(actor, "responsibilities", None)
    if isinstance(r, list):
        return [str(x).strip() for x in r if x]
    return []


# Verbs that hint at what job a responsibility describes. Ordered by
# specificity — a responsibility like "browse the class schedule" hits
# "browse" before it hits any generic verb. First match wins per
# responsibility. Kept short so a new domain adds one row rather than
# authoring a full ML classifier.
_JOB_VERB_HINTS: tuple[tuple[str, str, str], ...] = (
    # (verb-substring, job-label, job-id)
    ("book",       "Book",         "book"),
    ("browse",     "Browse",       "browse"),
    ("schedule",   "Schedule",     "schedule"),
    ("review",     "Reviews",      "reviews"),
    ("rate",       "Reviews",      "reviews"),
    ("cancel",     "Cancel",       "cancel"),
    ("manage",     "Manage",       "manage"),
    ("configure",  "Settings",     "settings"),
    ("approve",    "Approvals",    "approvals"),
    ("assign",     "Assign",       "assign"),
    ("track",      "Track",        "track"),
    ("monitor",    "Monitor",      "monitor"),
    ("report",     "Reports",      "reports"),
    ("analyze",    "Analytics",    "analytics"),
    ("view",       "View",         "view"),
    ("upload",     "Upload",       "upload"),
    ("invite",     "Invite",       "invite"),
)


def _jobs_from_responsibilities(responsibilities: list[str],
                                 journeys_for_actor: list[dict]) -> list[Job]:
    """Turn responsibility prose + journey names into a de-duped Job list.

    Each responsibility becomes a Job when a verb hint matches; each
    journey name becomes a Job (using the journey's ``primary_entities``
    where declarable). De-dupes by job id.

    The list is capped at ~5 jobs — a persona nav with 8 tabs starts
    to feel like a schema, not a product.
    """
    jobs: dict[str, Job] = {}
    # From responsibilities
    for resp in responsibilities:
        r_lower = resp.lower()
        for verb, label, jid in _JOB_VERB_HINTS:
            if verb in r_lower:
                if jid not in jobs:
                    jobs[jid] = Job(id=jid, label=label)
                break
    # From journeys — each journey the actor primary-drives becomes a
    # job. We take the journey NAME as the label since planners tend
    # to phrase journeys as user-facing tasks ("Book a class", not
    # "sessions.create").
    for jr in journeys_for_actor:
        name = str(jr.get("name") or "").strip()
        if not name:
            continue
        jid = _slug(name)
        if jid in jobs:
            # Merge — prefer the journey label if it's more descriptive
            if len(name) > len(jobs[jid].label):
                jobs[jid].label = name[:32]
            continue
        # Collect primary entities from journey step pages (rough: page → entity slug)
        primary_entities: list[str] = []
        for step in (jr.get("steps") or []):
            page = str((step or {}).get("page") or "")
            # Extract entity slug from route like "/bookings" or "/bookings/new"
            m = re.match(r"^/([a-zA-Z0-9_-]+)", page)
            if m:
                slug = m.group(1)
                if slug not in primary_entities:
                    primary_entities.append(slug)
        jobs[jid] = Job(id=jid, label=name[:32], primary_entities=primary_entities[:6])

    # Cap at 5 jobs per persona so nav-tabs stays legible.
    out = list(jobs.values())[:5]
    return out


def _jobs_from_pages(role: str, pages: list) -> list[Job]:
    """Fallback: derive jobs from ``plan.pages`` route prefixes.

    Fires when the planner emitted actors without responsibilities OR
    journeys. Real planners often skip these — the persona then has
    zero jobs and PB-4's dead-link protection drops the entire persona
    from nav-flow.

    Rule set:
      * ``admin`` role → pages matching ``/admin/*``
      * ``instructor`` / ``teacher`` / ``coach`` role → pages
        matching ``/instructor/*`` (case-insensitive)
      * ``manager`` role → ``/admin/*`` too (staff-side)
      * any other role (member, customer, user, patient, …) →
        pages that DON'T start with a role-scoped prefix (the
        "shared/member-facing" set — /classes, /dashboard, /my-*)

    Each surviving route becomes a Job whose label is a humanised
    leaf slug and whose ``primary_entities`` is the leaf slug — so
    the nav-flow's dead-link check resolves it via the entity→page
    map that already indexes every page by its route slug.
    Capped at 5 jobs per persona so pill nav stays readable.
    """
    if not isinstance(pages, list):
        return []

    role_slug = role.strip().lower()

    # Which first path segments in THIS app name a role? Derived from the
    # routes themselves, not a fixed list. The old code hardcoded the
    # yoga-studio vocabulary (admin / manager / studio_admin / instructor /
    # teacher / coach / trainer); every role outside it — `member`,
    # `committee_chair`, `secretary_general`, `public` on the Legislative
    # Council build — fell to the "everything" branch, so all four personas
    # got the SAME nav and the role switcher changed nothing.
    role_segments = _role_scoped_segments(pages, role_slug)

    # A role owns a route when the route's first segment matches the role
    # (`/organiser/events` for `organiser`). Matching is loose because the
    # planner writes `committee_chair` while routes use `committee-chairs`.
    own_prefixes = tuple(f"/{seg}/" for seg in role_segments
                         if _roles_match(seg, role_slug))
    other_prefixes = tuple(f"/{seg}/" for seg in role_segments
                           if not _roles_match(seg, role_slug))

    matched: list[tuple[str, str]] = []  # (route, section_slug)
    for pg in pages:
        if not isinstance(pg, dict):
            continue
        route = str(pg.get("route") or "").strip()
        if not route or "[" in route:
            # Skip dynamic-segment routes (detail views) — not top-level nav.
            continue
        route_l = route.lower()
        if own_prefixes:
            # This role has its own scoped area — that IS its nav.
            if not route_l.startswith(own_prefixes):
                continue
        elif other_prefixes:
            # Unscoped role in a scoped app: everything that isn't
            # somebody else's area.
            if route_l.startswith(other_prefixes):
                continue
        # else: nothing in this app is role-scoped — every role sees the
        # same set, and _personas_from_plan decides whether that is worth
        # rendering as a persona switcher at all.

        section = _section_slug(route, own_prefixes)
        if not section:
            continue
        matched.append((route, section))

    # De-dupe by section so /sessions and /sessions/new collapse to one job.
    seen: set[str] = set()
    jobs: list[Job] = []
    for _, section in matched:
        if section in seen:
            continue
        seen.add(section)
        label = _humanize_role(section).title()
        jobs.append(Job(id=section, label=label[:32],
                        primary_entities=[section]))
        if len(jobs) >= 5:
            break
    return jobs


# Trailing path segments that name an ACTION, not a section of the app.
# `/bills/new` is the bill create form; taking the leaf slug produced a nav
# item literally labelled "New" bound to a non-existent `new` entity.
_VERB_LEAVES = frozenset({
    "new", "edit", "create", "add", "update", "delete", "remove",
    "confirm", "review", "link",
})

_AUTH_LEAVES = frozenset({
    "login", "signup", "logout", "register", "signout", "signin",
})


def _normalise_role_token(s: str) -> str:
    """`committee_chair`, `committee-chairs`, `CommitteeChair` → `committeechair`.

    Planner roles and route slugs disagree on separator and plurality, so
    comparison happens on a stripped token rather than the raw string.
    """
    t = re.sub(r"[^a-z0-9]", "", str(s or "").lower())
    return t[:-1] if t.endswith("s") and len(t) > 3 else t


def _roles_match(a: str, b: str) -> bool:
    return bool(a) and _normalise_role_token(a) == _normalise_role_token(b)


def _role_scoped_segments(pages: list, role_slug: str) -> set[str]:
    """First path segments that look like a role name in this app.

    A segment counts when it matches the role we're resolving for AND has no
    list page of its own. That second half is what separates a role SCOPE
    from an entity SECTION whose name happens to match a role:

        /organiser/events   + no /organiser page  → `organiser` is a scope
        /members/new        + a  /members page    → `members` is an entity

    Without it, the Legislative Council's `member` role claimed `/members/*`
    as its private area, every other route was excluded, and the persona
    came back with zero jobs — the same silent-drop that removed `admin`.

    We deliberately do NOT try to infer "is this segment a role?" in
    general: a false positive hides real pages from a persona, which is
    worse than the flat nav we fall back to.
    """
    all_routes = {
        str(pg.get("route") or "").strip().lower().rstrip("/")
        for pg in (pages or []) if isinstance(pg, dict)
    }
    segs: set[str] = set()
    for pg in pages or []:
        if not isinstance(pg, dict):
            continue
        route = str(pg.get("route") or "").strip().lower()
        parts = [p for p in route.strip("/").split("/") if p]
        if len(parts) < 2:
            continue                 # `/members` is a section, not a scope
        head = parts[0]
        if not _roles_match(head, role_slug):
            continue
        if f"/{head}" in all_routes:
            continue                 # it has its own list page — an entity
        segs.add(head)
    return segs


def _section_slug(route: str, own_prefixes: tuple[str, ...]) -> str | None:
    """The section a route belongs to — its first meaningful segment.

    `/bills/new` → `bills` (NOT `new`). Inside a role-scoped area the role
    segment is stripped first: `/organiser/events/new` → `events`.
    """
    parts = [p for p in route.strip("/").split("/") if p]
    if not parts:
        return None
    if own_prefixes and f"/{parts[0].lower()}/" in own_prefixes:
        parts = parts[1:]            # drop the role scope
    if not parts:
        return None
    head = parts[0].lower()
    if head in _AUTH_LEAVES or head in _VERB_LEAVES:
        return None
    return head


def _personas_from_plan(plan: dict) -> list[Persona]:
    """Derive personas from ``plan.actors`` + ``plan.journeys``.

    Every actor becomes a persona (RBAC role kept as ``id``). Their
    jobs are derived from their responsibilities and the journeys they
    primary-drive. When BOTH are empty (planners often skip both),
    fall back to route-prefix matching against ``plan.pages`` — a
    yoga app's Instructor persona then gets Sessions/Availability
    jobs from /instructor/* routes rather than being dropped from the
    nav entirely. ``sample_name`` stays None here — an optional LLM
    enrichment pass can fill it.
    """
    actors_raw = plan.get("actors") if isinstance(plan, dict) else None
    if not isinstance(actors_raw, list):
        return []
    journeys = plan.get("journeys") if isinstance(plan, dict) else []
    journeys = journeys if isinstance(journeys, list) else []
    pages = plan.get("pages") if isinstance(plan, dict) else []
    pages = pages if isinstance(pages, list) else []

    personas: list[Persona] = []
    for actor in actors_raw:
        role = _actor_role(actor)
        if not role:
            continue
        label = _humanize_role(role)
        resp = _actor_responsibilities(actor)
        my_journeys = [
            jr for jr in journeys
            if isinstance(jr, dict) and str(jr.get("primary_actor") or "").strip() == role
        ]
        one_liner = ""
        if resp:
            # First responsibility, capped for the ≤140 char field.
            one_liner = resp[0][:140]
        jobs = _jobs_from_responsibilities(resp, my_journeys)
        if not jobs:
            # No responsibilities and no journeys — planner didn't
            # emit them. Salvage the persona with route-prefix jobs
            # so PB-4 doesn't drop it for having zero nav entries.
            jobs = _jobs_from_pages(role, pages)
        personas.append(Persona(
            id=_slug(role),
            name=label,
            role=role,
            one_liner=one_liner,
            jobs=jobs,
        ))
    return personas


# The keyword table moved to services.archetype_keywords so the prompt
# matcher and this haystack matcher can never again disagree about which
# archetypes exist. Kept under the original name: this module's public
# surface is unchanged and vocab_ranker imports it from here.
_ARCHETYPE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = plan_token_table()


def _archetype_from_plan(plan: dict) -> str:
    """Best-effort archetype label from the plan.

    Reads (in order): ``plan.archetype`` (explicit), ``plan.app_shape.
    identity.archetype``, then a keyword-based fallback from
    ``plan.entities`` + ``plan.description``. Kept simple — we just need
    a lowercase slug the domain-vocabulary layer can key off later.

    The keyword fallback fires because planners rarely emit either
    explicit field today; a booking app's SIGNAL comes from its
    entities (Booking, ClassSession, Instructor, MembershipPlan). A
    match requires TWO distinct keyword hits so a lone "instructor"
    entity in an unrelated app doesn't accidentally trigger the
    booking-platform vocab.
    """
    if isinstance(plan, dict):
        a = plan.get("archetype")
        if isinstance(a, str) and a.strip():
            return a.strip().lower()
        shape = plan.get("app_shape")
        if isinstance(shape, dict):
            ident = shape.get("identity")
            if isinstance(ident, dict):
                a = ident.get("archetype")
                if isinstance(a, str) and a.strip():
                    return a.strip().lower()

        # Keyword fallback — collect entity slugs + description words.
        haystack: list[str] = []
        ents = plan.get("entities")
        if isinstance(ents, dict):
            for k in ents.keys():
                if isinstance(k, str):
                    # Split CamelCase and snake_case so `ClassSession`
                    # matches both `class` and `session` tokens.
                    parts = re.sub(r"([a-z])([A-Z])", r"\1_\2", k).lower()
                    haystack.append(parts)
        for field in ("description", "name", "domain", "industry"):
            v = plan.get(field)
            if isinstance(v, str):
                haystack.append(v.lower())
        text = " ".join(haystack)
        for slug, keywords in _ARCHETYPE_KEYWORDS:
            hits = sum(1 for kw in keywords if kw in text)
            if hits >= 2:
                return slug
    return ""


def _voice_from_design_brief(brief: Any) -> VoiceNotes:
    """Pull editorial voice hints from the design_brief if present.

    The design_brief already knows the domain's tone (``identity.
    register``, ``identity.voice``). We mine those into copy-voice
    adjectives here so the product brief carries the voice forward
    without a second LLM call.
    """
    voice = VoiceNotes()
    if brief is None:
        return voice

    def _read(node: Any, key: str) -> Any:
        if isinstance(node, dict):
            return node.get(key)
        return getattr(node, key, None)

    ident = _read(brief, "identity")
    if ident is None:
        return voice
    register = _read(ident, "register") or []
    voice_val = _read(ident, "voice")
    voice_free = _read(ident, "voice_free")
    words: list[str] = []
    if isinstance(register, (list, tuple)):
        for r in register:
            if isinstance(r, str):
                # snake_case → separate words; keep the friendly ones
                for w in r.lower().replace("_", " ").replace("-", " ").split():
                    if w and w not in words:
                        words.append(w)
    if isinstance(voice_val, str) and voice_val.strip():
        for w in voice_val.lower().replace("_", " ").split():
            if w and w not in words:
                words.append(w)
    if isinstance(voice_free, str) and voice_free.strip():
        # voice_free is prose like "grounded warmth, quietly intentional"
        # — take the adjectives (short lowercase words).
        for w in re.findall(r"[a-z]+", voice_free.lower()):
            if len(w) >= 4 and w not in words:
                words.append(w)
    voice.adjectives = words[:6]
    return voice


def derive_from_plan(plan: dict, design_brief: Any = None) -> ProductBrief:
    """Compose a ProductBrief deterministically from plan + design brief.

    No LLM call. Fast, deterministic, safe to run on every generation.
    The result may have an empty ``brand`` (LLM enrichment can fill
    later); every other field is derived from real plan data.

    Callers that want a fully-enriched brief should call
    :func:`enrich_with_llm` on the result. That step is optional and
    best-effort.
    """
    if not isinstance(plan, dict):
        plan = {}
    return ProductBrief(
        brand=Brand(),  # empty by design; enrichment step fills it
        personas=_personas_from_plan(plan),
        archetype=_archetype_from_plan(plan),
        moments=[],
        voice_notes=_voice_from_design_brief(design_brief),
    )


# ── disk I/O ────────────────────────────────────────────────────────


_BRIEF_FILE = "product-brief.json"


def _brief_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / "contracts" / _BRIEF_FILE


def save_product_brief(output_dir: str | Path, brief: ProductBrief) -> Path:
    """Persist to ``contracts/product-brief.json``. Creates the dir.

    Returns the written path. Never raises — a persistence failure is
    logged and swallowed so it can't take generation down.
    """
    p = _brief_path(output_dir)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        # model_dump(mode="json") emits primitives suitable for json.dumps.
        p.write_text(json.dumps(brief.model_dump(mode="json"), indent=2) + "\n",
                     encoding="utf-8")
    except OSError as exc:
        logger.warning("product_brief: save failed for %s: %s", p, exc)
    return p


def load_product_brief_from_disk(output_dir: str | Path) -> ProductBrief | None:
    """Read the brief back from disk. Returns None on any failure.

    Downstream consumers use this to fetch the brief without threading
    it through 6 layers of call args.
    """
    p = _brief_path(output_dir)
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("product_brief: load failed for %s: %s", p, exc)
        return None
    try:
        return ProductBrief.model_validate(raw)
    except Exception as exc:  # noqa: BLE001 — pydantic ValidationError etc.
        logger.warning("product_brief: schema-invalid on disk at %s: %s", p, exc)
        return None


__all__ = [
    "Brand",
    "Job",
    "Moment",
    "Persona",
    "ProductBrief",
    "VoiceNotes",
    "derive_from_plan",
    "is_product_brief_enabled",
    "load_product_brief_from_disk",
    "save_product_brief",
]
