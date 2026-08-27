"""Archetype vocabulary libraries — Slice 2 of the Path B commitment.

The plan tells Forge WHAT the app is (entities, workflows, actors).  It
does NOT tell Forge what a "booking platform" IS as a product — its
conventional screens, its expected sections per screen, its component
preferences, its signature empty states, its status badges. Every
booking app on the market gets those right by convention; Forge got
them by re-guessing every time.

This module carries those conventions as per-archetype vocabulary
files. Composers CONSULT the vocabulary when authoring pages, so a
booking platform gets Schedule/Upcoming-Past/Reviews as it should,
without every composer re-inventing the pattern.

Design contract:

  - One vocabulary file per archetype slug (booking-platform.py,
    crm.py, ecommerce.py, …). Files stay small + pure — no runtime
    imports of composers, no LLM calls, no I/O.

  - :class:`ArchetypeVocabulary` is a frozen-ish dataclass. Every
    field defaults to empty so a half-populated vocabulary is safe to
    ship. Callers that miss a field just fall back to their existing
    behaviour — the vocabulary is *purely additive*.

  - :func:`load_vocabulary` looks up by canonical slug (lowercase,
    hyphenated). Returns None on misses so callers can branch cleanly
    on "vocabulary exists" vs "fall back to legacy".

  - Registry is lazy — the archetype module isn't imported until the
    first call. Avoids paying import cost on generation runs that
    don't use vocabularies at all.

Vocabularies grow incrementally: this slice ships
``booking_platform`` as the reference implementation, matched to the
patterns visible in the Claude yoga demo. CRM, ecommerce, and other
domains land in follow-up slices as we regen those app types.

Task: #668 (SL2-1). Follows the Path B direction (beautiful + working
generator) — Forge finally knows what a booking app is.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ── Shape vocabulary ────────────────────────────────────────────────


# Preferred shape for a screen listing entities. The collection composer
# reads this to choose between the existing Table default and the
# consumer-product shapes.
#
#   - ``table``:          the current default; a dense sortable grid.
#                         Right for admin/comparison work.
#   - ``card-list``:      one pill-card per row (icon + title + meta +
#                         action). Right for "your things" views —
#                         bookings, reviews, messages, transactions.
#   - ``card-grid``:      2-3 col responsive card grid. Right for
#                         browsing directories — instructors, teams,
#                         products, spaces.
#   - ``schedule-grid``:  time-of-day columns; sessions per column.
#                         Right for booking apps' Schedule screens.
#   - ``ledger-list``:    dense row-per-transaction table with a right-
#                         aligned amount column (MoneyDisplay), status
#                         badge, and timestamp — the banking-industry
#                         signature for transaction history. Slice-3.
#   - ``kanban``:         column-per-status pipeline. Right for
#                         application/opportunity/lead pipelines
#                         (loan applications, CRM deals). Slice-3.
#
# Composers unknown-shape-safe: an unrecognised shape falls back to
# ``table`` and logs a warning.
KNOWN_SHAPES = frozenset({"table", "card-list", "card-grid", "schedule-grid",
                          "ledger-list", "kanban"})


# ── Data classes ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ComponentPreference:
    """How this archetype wants a given entity presented.

    ``shape`` picks the top-level layout (see :data:`KNOWN_SHAPES`).
    ``primary_field`` is the single most-important field to use as the
    card's title (composer falls back to entity name when absent).
    ``context`` (optional) narrows the preference to a role: "admin"
    means "this shape is for admin views; other personas may see the
    entity differently." Empty context = applies to every persona.
    ``primary_component`` (optional, CREATIVE-5b) is a HINT to downstream
    composers: "for this entity, prefer this specific library component
    over the default one for its shape." Must match a name in the library
    manifest — the vocab composer validates and drops unknown names.
    Empty string = fall back to the shape's default component.
    """
    shape: str = "table"
    primary_field: str = ""
    context: str = ""
    primary_component: str = ""


@dataclass(frozen=True)
class ArchetypeVocabulary:
    """The full vocabulary for one archetype.

    ``id`` matches the canonical archetype slug used in
    ``plan.archetype`` and ``product_brief.archetype``.

    Every field defaults to empty so a partial vocabulary is safe —
    every composer consuming this branches on presence, never crashes
    on absence.
    """
    id: str

    # Which screens does each persona primarily need? Keys are persona
    # role slugs (matching plan.actors[*].role); values are screen slugs
    # in order of importance. Used by the persona-tabs sub-nav layer to
    # know which tabs to render.
    primary_screens_per_persona: dict[str, list[str]] = field(default_factory=dict)

    # Which sections does each screen split into? Keys are screen slugs
    # (matching the persona screen list); values are ordered section
    # names. When a screen has multiple sections, the collection
    # composer emits one Card-wrapped block per section with a filter
    # predicate matching the section name.
    section_recipes: dict[str, list[str]] = field(default_factory=dict)

    # Preferred shape per entity. Keys are entity slugs
    # (matching plan.entities keys). Missing entity → composer keeps
    # its current default shape (Table).
    component_preferences: dict[str, ComponentPreference] = field(default_factory=dict)

    # Domain-voiced empty-state copy. Keys are semantic state ids
    # (``empty_schedule``, ``empty_bookings``, ``no_results``, …);
    # values are the exact copy string. Read by the empty_state_library.
    signature_states: dict[str, str] = field(default_factory=dict)

    # Suggested badge variants per status enum. Keys are lowercase
    # status values (matching harvested enum values); values are a
    # dict with ``variant`` (success | danger | neutral | accent |
    # warning) and optional ``label`` override.
    status_badges: dict[str, dict[str, str]] = field(default_factory=dict)

    # Per-section filter recipes — one entry per section named in
    # :attr:`section_recipes` values. Keys are section names ("upcoming",
    # "past", "today", …); values are ``{column: value}`` dicts the
    # composer folds into the section's dataSource ``filter``. Empty
    # value dict = no filter (show the whole entity list under that
    # heading). Runtime enforces filters via equality (drizzle ``eq``);
    # multi-value or range filters are represented by the composer
    # picking the single canonical value for that section (e.g. upcoming
    # → status="confirmed"). More sophisticated matching lands in a
    # follow-on runtime slice.
    section_filters: dict[str, dict[str, str]] = field(default_factory=dict)

    # What belongs on THIS domain's dashboard.
    #
    # Everything above shapes interior list screens; the dashboard — the
    # landing page, the first thing anyone sees — had no vocabulary input
    # at all, so every app opened on the same generic KPI-and-chart
    # skeleton regardless of industry ("dashboards are lame"). This is the
    # domain's answer to "what does a person in this business need to see
    # first?", consumed by the dashboard authority.
    #
    #   kpis:     ordered metric specs. Each is
    #             ``{label, entity, op, field?, filter?}`` — op ∈
    #             count | sum | avg. ``filter`` is a
    #             ``{column: [candidate, ...]}`` dict scoping the metric
    #             (e.g. low-stock count); candidates are resolved against
    #             the entity's real enum by
    #             :func:`services.section_split.resolve_filter_values`,
    #             exactly as section filters are.
    #   sections: ordered ``{title, entity, shape?, filter?, limit?}``
    #             blocks for the body — the working lists a person acts
    #             on, in priority order.
    #
    # Entities are named by their vocabulary slug; the composer resolves
    # them against the app's real registry and silently drops any the app
    # doesn't have, so a partial match still yields a domain-shaped page.
    dashboard_recipe: dict[str, list[dict]] = field(default_factory=dict)

    # What belongs on THIS domain's interior pages, per entity.
    #
    # ``component_preferences`` says how an entity is SHAPED (table vs
    # card-grid); nothing said what it should SHOW. So which columns
    # reach a list, and how a record page groups its fields, were free
    # LLM choices in every app — which is why one warehouse app leads
    # its item table with `createdAt` and the next with `id`. A domain
    # has strong opinions here: a picker scanning stock wants SKU, name,
    # on-hand and reorder point, in that order, and does not want
    # timestamps.
    #
    # Keys are entity slugs (same vocabulary spelling as
    # ``component_preferences``). Values:
    #
    #   list_columns:    ordered column names for the collection view —
    #                    the domain's reading order, most identifying
    #                    first. Aim for 4-6; more is a spreadsheet.
    #   detail_sections: ordered ``{label, fields}`` groups for the
    #                    record page, so a detail view reads as sections
    #                    a person recognises ("Stock", "Supplier")
    #                    rather than one flat column dump.
    #   filter_chips:    columns worth a filter chip above the list.
    #   list_order:      ``{field, dir}`` — which row the domain wants at
    #                    the top. Sort order is the same kind of decision
    #                    as ``list_columns`` and was free in the same way:
    #                    a stock screen sorted by "recently updated" is a
    #                    changelog, while the picker wanted whatever is
    #                    running out. Recency is a legitimate answer where
    #                    the screen really is about what just happened
    #                    (see ``stock_movements``) — it is only wrong as a
    #                    default nobody chose.
    #
    # Every name is resolved against the app's real columns and silently
    # dropped when absent, so a vocabulary may name a column the app
    # didn't build without breaking the page.
    page_recipes: dict[str, dict] = field(default_factory=dict)


# ── Name matching ──────────────────────────────────────────────────


def _norm_name(name: str) -> str:
    """purchase_orders / purchaseOrders / purchase-orders → purchaseorders."""
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def match_entity_name(wanted: str, available: Any) -> str | None:
    """Map a vocabulary's entity name onto the app's own spelling.

    Vocabularies are authored in the domain's words while apps are named
    by the planner, so ``purchase_orders``, ``purchaseOrders`` and
    ``PurchaseOrder`` all mean the same table. Returns the APP's
    spelling — downstream bindings must use the name the app really has
    — or None when the app has no such entity, so callers drop rather
    than invent.
    """
    want = _norm_name(wanted)
    if not want:
        return None
    by_norm = {_norm_name(a): a for a in (available or []) if a}
    if want in by_norm:
        return by_norm[want]
    # Tolerate plural drift in either direction.
    singular = want[:-1] if want.endswith("s") and not want.endswith("ss") else want
    for cand in (singular, want + "s"):
        if cand in by_norm:
            return by_norm[cand]
    return None


# ── Registry + loader ──────────────────────────────────────────────


def _canonical_slug(archetype: str | None) -> str:
    """Normalise an archetype string to a lookup key.

    ``Booking Platform`` / ``booking_platform`` / ``booking-platform``
    all collapse to ``booking-platform``. Empty / None → ``""``.
    """
    if not isinstance(archetype, str):
        return ""
    s = archetype.strip().lower()
    if not s:
        return ""
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


# Lazily populated on first load — keeps import cost off runs that
# never touch vocabularies.
_REGISTRY: dict[str, ArchetypeVocabulary] | None = None


def _build_registry() -> dict[str, ArchetypeVocabulary]:
    """Import every known vocabulary module and index by canonical slug.

    New vocabularies register by adding an import here + declaring an
    ``ARCHETYPE`` module-level constant of type
    :class:`ArchetypeVocabulary`. Kept as one obvious list rather than
    scanning the directory — deleting a vocabulary should not silently
    drop coverage.
    """
    from services.archetype_vocabulary.booking_platform import BOOKING_PLATFORM
    from services.archetype_vocabulary.banking_platform import BANKING_PLATFORM
    from services.archetype_vocabulary.crm_platform import CRM_PLATFORM
    from services.archetype_vocabulary.inventory_platform import INVENTORY_PLATFORM
    from services.archetype_vocabulary.content_platform import CONTENT_PLATFORM
    from services.archetype_vocabulary.learning_platform import LEARNING_PLATFORM
    from services.archetype_vocabulary.healthcare_platform import HEALTHCARE_PLATFORM
    from services.archetype_vocabulary.field_service_platform import FIELD_SERVICE_PLATFORM
    from services.archetype_vocabulary.marketplace_platform import MARKETPLACE_PLATFORM
    from services.archetype_vocabulary.project_platform import PROJECT_PLATFORM
    from services.archetype_vocabulary.payment_processing_platform import (
        PAYMENT_PROCESSING_PLATFORM,
    )
    from services.archetype_vocabulary.subscription_billing_platform import (
        SUBSCRIPTION_BILLING_PLATFORM,
    )
    from services.archetype_vocabulary.analytics_dashboard_platform import (
        ANALYTICS_DASHBOARD_PLATFORM,
    )
    from services.archetype_vocabulary.messaging_platform import MESSAGING_PLATFORM
    from services.archetype_vocabulary.dev_tools_platform import DEV_TOOLS_PLATFORM
    from services.archetype_vocabulary.document_intelligence_platform import (
        DOCUMENT_INTELLIGENCE_PLATFORM,
    )
    from services.archetype_vocabulary.legislative_platform import (
        LEGISLATIVE_PLATFORM,
    )

    registry: dict[str, ArchetypeVocabulary] = {}
    for vocab in (
        BOOKING_PLATFORM,
        BANKING_PLATFORM,
        CRM_PLATFORM,
        INVENTORY_PLATFORM,
        CONTENT_PLATFORM,
        LEARNING_PLATFORM,
        HEALTHCARE_PLATFORM,
        FIELD_SERVICE_PLATFORM,
        MARKETPLACE_PLATFORM,
        PROJECT_PLATFORM,
        PAYMENT_PROCESSING_PLATFORM,
        SUBSCRIPTION_BILLING_PLATFORM,
        ANALYTICS_DASHBOARD_PLATFORM,
        MESSAGING_PLATFORM,
        DEV_TOOLS_PLATFORM,
        DOCUMENT_INTELLIGENCE_PLATFORM,
        LEGISLATIVE_PLATFORM,
    ):
        slug = _canonical_slug(vocab.id)
        if slug:
            registry[slug] = vocab
    return registry


def _get_registry() -> dict[str, ArchetypeVocabulary]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY


def clear_cache() -> None:
    """Test hook — force the next :func:`load_vocabulary` call to rebuild."""
    global _REGISTRY
    _REGISTRY = None


def load_vocabulary(archetype: str | None) -> ArchetypeVocabulary | None:
    """Return the vocabulary for ``archetype``, or None if unregistered.

    Callers branch on the result:

        vocab = load_vocabulary(brief.archetype)
        if vocab is not None:
            # archetype-aware path
            pref = vocab.component_preferences.get(entity_slug)
            ...
        else:
            # legacy path — no vocabulary for this archetype yet
    """
    slug = _canonical_slug(archetype)
    if not slug:
        return None
    registry = _get_registry()
    hit = registry.get(slug)
    if hit is not None:
        return hit
    # Callers arrive with the short domain word rather than the module's
    # full id: plan.archetype is "inventory" and the keyword detector in
    # plan_directive_parser emits "legislative", while the registry is
    # keyed "inventory-platform" / "legislative-platform". Without this
    # every short slug resolved to None and silently took the legacy
    # no-vocabulary path — the archetype layer looked wired and wasn't.
    return registry.get(f"{slug}-platform")


def known_archetypes() -> tuple[str, ...]:
    """Return the sorted tuple of registered archetype slugs.

    Used by tests + telemetry to detect coverage gaps ("we regen 12
    apps but only ship vocabularies for 1 archetype").
    """
    return tuple(sorted(_get_registry().keys()))


def _entity_lookup_variants(entity_slug: str) -> list[str]:
    """Return name variants to probe against ``component_preferences``.

    Planners emit entity names in whatever casing/inflection the source
    prompt used (``Booking``, ``ClassSession``, ``instructor``). The
    vocabulary keys are the canonical lowercase plural (``bookings``,
    ``class_sessions``, ``instructors``). We probe in this order:

        1. verbatim (backward compatibility — vocabularies MAY carry the
           exact spelling for rare cases)
        2. lowercase (``Booking`` → ``booking``)
        3. lowercase + trailing 's' (``booking`` → ``bookings``)
        4. camelCase → snake_case (``ClassSession`` → ``class_session``)
        5. camelCase → snake_case + 's' (``class_sessions``)

    Duplicates collapse. Empty input → empty list (caller returns None).
    """
    if not isinstance(entity_slug, str) or not entity_slug.strip():
        return []
    variants: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        if name and name not in seen:
            seen.add(name)
            variants.append(name)

    raw = entity_slug.strip()
    _add(raw)
    lo = raw.lower()
    _add(lo)
    if not lo.endswith("s"):
        _add(lo + "s")
    # camelCase → snake_case: insert underscore before caps (after first char)
    snake_parts: list[str] = []
    for i, ch in enumerate(raw):
        if ch.isupper() and i > 0 and not raw[i - 1].isupper():
            snake_parts.append("_")
        snake_parts.append(ch.lower())
    snake = "".join(snake_parts)
    _add(snake)
    if not snake.endswith("s"):
        _add(snake + "s")
    return variants


def component_preference(vocab: ArchetypeVocabulary | None,
                         entity_slug: str,
                         persona_role: str = "") -> ComponentPreference | None:
    """Best-fit component preference for an entity + persona.

    Prefers a ``context``-specific entry (e.g. ``members`` +
    context=``admin``) over a context-less one when the caller
    supplies ``persona_role``. Kept as a helper here rather than
    inlined in every composer so the "prefer specific context" rule
    stays in ONE place.

    Entity name matching tolerates the casing/inflection variants the
    planner emits: ``Booking`` / ``booking`` / ``bookings`` all resolve
    to the same key ``bookings`` in the vocabulary. See
    :func:`_entity_lookup_variants` for the full probe order.
    """
    if vocab is None:
        return None
    pref = None
    for variant in _entity_lookup_variants(entity_slug):
        pref = vocab.component_preferences.get(variant)
        if pref is not None:
            break
    if pref is None:
        return None
    # Context-specific preference: honour when it matches the calling
    # persona; otherwise treat as if the entity had no preference (a
    # role-scoped preference should not leak into unrelated personas).
    if pref.context and pref.context.strip().lower() != persona_role.strip().lower():
        return None
    return pref


__all__ = [
    "ArchetypeVocabulary",
    "ComponentPreference",
    "KNOWN_SHAPES",
    "_entity_lookup_variants",
    "clear_cache",
    "component_preference",
    "known_archetypes",
    "load_vocabulary",
    "match_entity_name",
]
