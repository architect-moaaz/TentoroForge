"""Post-gen: rebuild collection page schemas from persisted maquettes.

Runs AFTER page authoring. Reads
``<output>/src/contracts/collection-maquettes.json`` (a list of
:class:`services.collection_maquette.CollectionMaquette` dicts written
by the maquette LLM step in the pipeline) and rewrites each targeted
collection page schema deterministically.

Authority pattern is the same as
:mod:`services.apply_dashboard_maquette`: the maquette IS the content
contract; the assembler is mechanical; no LLM in the assembly.

Layout branch (from ``maquette.layout``):
  * ``table`` — `Table` bound to entity `op:"list"` with the maquette's
    columns.
  * ``kanban`` — `Kanban` grouped by the first status-shaped column
    (falls back to `Table` when no status column exists — the composer
    logs the fallback rather than emit a broken kanban).
  * ``calendar`` — `Calendar` keyed to the first date-shaped column
    (falls back to `Table` when no date column exists).
  * ``cards`` — grid of `Card` items with the primary column as title
    and up to 3 secondary columns beneath.
  * ``timeline`` — vertical `TimelineList` keyed to the first date
    column (falls back to `Table` when no date column exists).

Slot honoring (from maquette moments layer):
  * ``hero`` → optional top-band header (Row of title + subtitle + badge)
  * ``filter_presets`` → chip row above the collection
  * ``empty_state`` → `IllustratedEmpty` on the collection primitive
    (emptyText / emptyDescription / emptyAction slots the Table already
    supports; other layouts get an above-the-collection empty state).
  * ``footer`` → optional band beneath collection (total / insight / …)
  * ``signature_moves`` → `data-signature-move` attr on root Stack
  * ``row_treatment`` → `data-row-treatment` attr on the collection node

Idempotent: rewriting an already-composed collection is a no-op.
Fails closed: any exception logs and leaves the existing schema alone.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _prefetch_page_compositions(root, entries, kind: str) -> None:
    """Warm the LLM page-composer cache for this whole batch at once.

    Best-effort by construction — a failure here costs nothing but
    speed, because every page still composes on demand inside
    ``_apply_one``. So it swallows rather than propagates.
    """
    try:
        from services.page_composer_pipeline import prefetch_maquette_pages
        stats = prefetch_maquette_pages(root, entries, kind)
        if stats.get("composed") or stats.get("cached"):
            logger.info(
                "[%s] page-composer prefetch: composed=%s cached=%s failed=%s",
                kind, stats.get("composed"), stats.get("cached"), stats.get("failed"),
            )
    except Exception as exc:  # noqa: BLE001
        logger.debug("[%s] page-composer prefetch skipped: %s", kind, exc)



# Marker so we don't reapply on an already-composed collection.
_MARKER_META_KEY = "collection_maquette_composed"

# Persistence path (relative to output_dir). The LLM-authoring seam
# writes a JSON list of maquette dicts here; one entry per collection
# page. See services/collection_maquette.py for the dict shape.
_MAQUETTES_REL_PATH = ("src", "contracts", "collection-maquettes.json")


def apply_maquettes_to_collections(output_dir: str) -> dict[str, Any]:
    """Rebuild each targeted collection page from its persisted maquette.

    Returns a diagnostic dict::

        {"applied": int, "skipped": int, "reasons": [str, ...]}

    Never raises. Multi-page: iterates every maquette entry and applies
    each independently; a per-page failure doesn't stop the batch.

    Phase 6a (Collection Authority) — the composer is the SOLE writer
    for collection pages when
    :func:`services.artifact_authority.is_authority_enabled` is on for
    ``"collection"``. Two extensions activate under that flag:

    1. **Bootstrap the schema when it doesn't exist.** The LLM
       ``page_schema_agent`` skips collection pages under the flag, so
       the target file isn't on disk yet. Derive its path from the
       plan + maquette route and treat missing as "empty existing schema".

    2. **Recipe fallback when a maquette entry is unusable.** When a
       maquette entry can't be applied (bad route, missing entity, etc)
       and the flag is on, invoke
       :func:`services.deterministic_pages.build_list_page` (or the
       appropriate kanban/calendar builder) so the collection page
       still ends up on disk with sensible defaults.
    """
    root = Path(output_dir)
    _authority_on = _is_collection_authority_enabled()
    maq_path = root.joinpath(*_MAQUETTES_REL_PATH)

    # Phase 6a: when the flag is on AND no maquettes file exists, we
    # still need collection pages on disk (the LLM was told to skip
    # them). Fall back to deterministic builders for every collection
    # page in the plan.
    if not maq_path.is_file():
        if _authority_on:
            return _fallback_all_collections_via_recipe(
                root, reason="no maquettes on disk",
            )
        return {"applied": 0, "skipped": 0, "reasons": ["no maquettes on disk"]}

    try:
        raw = json.loads(maq_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[collection-maquette] unreadable: %s", exc)
        if _authority_on:
            return _fallback_all_collections_via_recipe(
                root, reason=f"maquettes unreadable: {exc}",
            )
        return {"applied": 0, "skipped": 0, "reasons": [f"maquettes unreadable: {exc}"]}

    entries = raw if isinstance(raw, list) else (raw.get("maquettes") if isinstance(raw, dict) else None)
    if not isinstance(entries, list):
        return {"applied": 0, "skipped": 0, "reasons": ["maquettes not a list"]}

    # Read entity registry once — the composer uses it to type-map
    # columns without re-inferring per-page.
    registry = _load_registry(root)

    # SL2-2: Load the product brief + archetype vocabulary once. Both
    # optional — when either is missing, _apply_one falls back to the
    # legacy layout resolution (maquette.layout or "table"). Kept
    # best-effort so a missing brief / unregistered archetype never
    # blocks composition.
    _vocab = None
    try:
        from services.product_brief import load_product_brief_from_disk
        from services.page_vocabulary import _load_brief
        from services.vocab_composer_pipeline import load_compose_and_modify_vocab_sync
        _pb = load_product_brief_from_disk(root)
        if _pb is not None and _pb.archetype:
            # Load plan.json so the LLM has per-app context for modifier/composer.
            # (json is already imported at module top — no local import here or it
            # would shadow it via Python's function-scope rule and break other
            # json.load() calls in this function with UnboundLocalError.)
            _plan: dict = {}
            try:
                _plan_path = Path(root) / "src" / "contracts" / "plan.json"
                if _plan_path.exists():
                    _plan = json.loads(_plan_path.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                _plan = {}
            # Composer (FORGE_VOCAB_COMPOSER) supersedes modifier
            # (FORGE_VOCAB_MODIFIER). Both flags off → base vocab verbatim.
            _vocab, _preset, _ = load_compose_and_modify_vocab_sync(
                plan=_plan,
                brief=_load_brief(root),   # was None — dropped the identity signal
                output_dir=root,
            )
            if _vocab is not None:
                logger.info(
                    "[collection-maquette] archetype vocabulary loaded: %s",
                    _vocab.id,
                )
    except Exception as _vocab_exc:  # noqa: BLE001
        logger.debug("[collection-maquette] vocab load skipped: %s", _vocab_exc)

    # CREATIVE-6c — warm the page-composer cache for the whole batch in
    # parallel before the per-page loop starts. Each _apply_one still
    # calls the single-page composer exactly as before; it just finds a
    # cache hit instead of paying a fresh ~1min LLM round-trip in series.
    # Purely additive: if this returns nothing (flag off, inputs missing,
    # API down) every page composes on demand, which is the old path.
    _prefetch_page_compositions(root, entries, kind="list")

    applied = 0
    skipped = 0
    reasons: list[str] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            skipped += 1
            reasons.append(f"entry[{i}]: not a dict")
            continue
        result = _apply_one(root, entry, registry, allow_bootstrap=_authority_on,
                             vocabulary=_vocab)
        if result.get("applied"):
            applied += 1
        else:
            skipped += 1
            reason = result.get("reason") or "unknown"
            entity = entry.get("entity") or "?"
            reasons.append(f"{entity}: {reason}")

    # Under authority, sweep the plan for collection pages we haven't
    # written yet and recipe-fill them. The maquette author caps the
    # number of pages it LLM-authors, so multi-collection apps normally
    # have a tail of pages with no maquette entry.
    if _authority_on:
        _tail = _fallback_missing_collections_via_recipe(root, applied_routes={
            entry.get("route") for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("route"), str)
        })
        applied += _tail.get("applied", 0)
        reasons.extend(_tail.get("reasons", []))

    return {"applied": applied, "skipped": skipped, "reasons": reasons}


# The layout a maquette carries when its author expressed no shape opinion.
# Anything else is a deliberate call about this app's data.
_DEFAULT_LAYOUT = "table"


def _resolve_layout(authored: Optional[str],
                    pref_shape: Optional[str]) -> tuple[str, str]:
    """``(layout, why)`` — the author or the vocabulary, and the reason.

    The archetype vocabulary already briefs the maquette author (its reading
    order goes into the authoring prompt), so letting it also override the
    result gave one authority two votes: it shaped the judgment, then
    overwrote it. Everything the author added on top — a montage-informed
    shape, a call made from the real column list — was flattened back to a
    convention that had already been heard.

    So the vocabulary decides only where the author said nothing. A maquette
    that carries ``"table"`` expressed no shape (it is the fallthrough in the
    author's own decision rule), which keeps every existing convention
    intact. A deliberate kanban/calendar/cards/timeline stands.

    Data fitness is a separate, later veto and outranks both — a kanban with
    no status column still degrades to a table downstream.
    """
    pref = (pref_shape or "").strip()
    layout = (authored or "").strip() or _DEFAULT_LAYOUT

    if not pref or pref == layout:
        return layout, "authored"
    if layout == _DEFAULT_LAYOUT:
        return pref, f"vocabulary preference {pref!r} (author expressed none)"
    return layout, (f"authored {layout!r} kept; vocabulary preference "
                    f"{pref!r} declined (author was already briefed with it)")


def _apply_one(root: Path, maquette: dict, registry: dict,
                *, allow_bootstrap: bool = False,
                vocabulary: Any = None) -> dict[str, Any]:
    """Apply a single collection maquette. Returns ``{"applied": bool,
    "reason": str}``. Never raises.

    ``allow_bootstrap`` (Phase 6a) — when True, a missing schema file
    doesn't skip the maquette; instead the composer derives a target
    path from the maquette's route and writes fresh.

    ``vocabulary`` (SL2-2) — the loaded ArchetypeVocabulary for this
    app's archetype, or None. Its ``component_preferences[entity].shape``
    fills in where the maquette author expressed no shape (a booking
    entity's default table becomes a card-list; instructors a card-grid;
    sessions a schedule-grid), but no longer overrides a deliberate
    author pick — see :func:`_resolve_layout` for why. Backward
    compatible — None means "use the maquette's layout exactly as
    before."
    """
    entity = maquette.get("entity")
    route = maquette.get("route")
    if not (isinstance(entity, str) and entity and
            isinstance(route, str) and route.startswith("/")):
        return {"applied": False, "reason": "missing/bad entity or route"}

    # CREATIVE-6b — LLM page composer early-exit. When FORGE_PAGE_COMPOSER
    # is on, ask the LLM composer for a full page schema first. On success,
    # write it and skip the deterministic path entirely. On any failure
    # (flag off / LLM error / validation reject) the composer returns None
    # and we fall through to the existing deterministic assembly below.
    try:
        from services.page_composer_pipeline import (
            compose_page_via_pipeline_sync as _llm_compose,
            is_flag_on as _llm_flag_on,
            page_from_maquette as _page_from_maquette,
            _write_page_schema as _llm_write,
        )
        from services.page_vocabulary import _load_brief
        if _llm_flag_on():
            _plan = json.loads((root / "src" / "contracts" / "plan.json").read_text(encoding="utf-8")) \
                if (root / "src" / "contracts" / "plan.json").is_file() else {}
            _page = _page_from_maquette(maquette, _plan, "list")
            _llm_schema, _llm_prov = _llm_compose(
                _page, _plan, root, brief=_load_brief(root))
            if _llm_schema is not None:
                _wrote = _llm_write(_page, _llm_schema, root)
                if _wrote is not None:
                    return {"applied": True, "reason": "ok (llm-composed)"}
    except Exception as _llm_exc:  # noqa: BLE001
        logger.debug("[collection-maquette] llm composer skipped: %s", _llm_exc)

    schema_path = _find_collection_schema(root, route)
    _bootstrapped = False
    if schema_path is None:
        if allow_bootstrap:
            # Derive target path from the maquette's route — same slug
            # convention _find_collection_schema uses.
            slug = _route_to_slug(route)
            schema_path = root / "src" / "schemas" / f"{slug}.json"
            _bootstrapped = True
        else:
            return {"applied": False, "reason": f"no schema for route {route}"}

    if _bootstrapped:
        existing: dict = {}
    else:
        try:
            existing = json.loads(schema_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return {"applied": False, "reason": f"schema unreadable: {exc}"}

    # Idempotency: skip if already composed.
    if isinstance(existing, dict) and isinstance(existing.get("meta"), dict):
        if existing["meta"].get(_MARKER_META_KEY) is True:
            return {"applied": False, "reason": "already composed"}

    # BOOTSTRAP ONLY. The maquette now reaches the page AUTHOR as a design
    # brief before the page is written (services.maquette_brief), so the
    # author already built this page from this maquette. Rewriting it here
    # would discard that work and re-impose one deterministic shape on
    # every app — the reason interior pages all looked alike. Compose only
    # when nothing exists at this route.
    if not _bootstrapped and isinstance(existing, dict) and existing.get("root"):
        return {"applied": False, "reason": "page already authored — not overwriting"}


    entity_meta = _entity_meta(registry, entity)
    columns = _column_type_map(entity_meta)

    _authored_layout = maquette.get("layout") if isinstance(maquette.get("layout"), str) else None
    layout = (_authored_layout or "").strip() or _DEFAULT_LAYOUT
    row_treatment = maquette.get("row_treatment") if isinstance(maquette.get("row_treatment"), str) else "cozy"

    # SL2-2: vocabulary-driven shape override. When the archetype
    # vocabulary declares a preferred shape for this entity, it wins
    # over the maquette's layout. A booking-platform's ``bookings``
    # entity becomes ``card-list``, ``instructors`` becomes ``card-
    # grid``, ``sessions`` becomes ``schedule-grid`` — even if the
    # maquette author (LLM-authored earlier in the pipeline) requested
    # a plain table. Vocabulary encodes conventions the composer
    # otherwise re-guesses per generation.
    #
    # The maquette's declared layout wins ONLY when the vocabulary
    # has no preference for this entity, or when the preference is
    # context-scoped to a different persona than the current view's
    # (studio_admin-scoped tables never leak into member views).
    #
    # Persona context for the preference lookup: the maquette carries
    # the intended persona in ``maquette.persona`` (planner-emitted);
    # falls back to empty string, which the helper treats as "any
    # context-free preference wins".
    if vocabulary is not None:
        try:
            from services.archetype_vocabulary import (
                component_preference as _pref_for,
            )
            persona_role = str(maquette.get("persona") or "").strip()
            pref = _pref_for(vocabulary, entity, persona_role=persona_role)
            resolved, why = _resolve_layout(
                _authored_layout, getattr(pref, "shape", None) if pref else None)
            if resolved != layout or "declined" in why:
                logger.info("[collection-maquette] %s layout=%s — %s",
                            entity, resolved, why)
            layout = resolved
        except Exception as _pref_exc:  # noqa: BLE001
            # Vocabulary is best-effort — a lookup error must not
            # block composition. Log at debug so real failures still
            # surface via wider logging.
            logger.debug("[collection-maquette] pref lookup failed: %s", _pref_exc)

    root_id = existing.get("id") or f"{_route_to_slug(route)}-list"

    # Build the collection primitive first — some layouts need the
    # column list, some need a date-anchor, kanban needs a status column.
    collection_node, ds_name, data_sources, layout_used = _build_collection_node(
        entity=entity,
        route=route,
        layout=layout,
        maquette=maquette,
        columns=columns,
        row_treatment=row_treatment,
        vocabulary=vocabulary,
    )
    if collection_node is None:
        return {"applied": False, "reason": "could not build a collection primitive"}

    # SL2-4: split into vocabulary-declared sections (Upcoming/Past,
    # Today/This-Week, …). When the archetype vocabulary declares a
    # multi-section recipe for this route, wrap the base collection in
    # per-section Cards with distinct dataSources — each carrying the
    # section's filter dict. Non-matching routes fall through unchanged.
    if vocabulary is not None:
        try:
            from services.section_split import (
                resolve_sections,
                split_collection_into_sections,
            )
            _sections = resolve_sections(vocabulary, route)
            if len(_sections) >= 2:
                # Pull declared enum_values from the entity meta so the
                # section-filter resolver can pick a value that will
                # actually appear in seed data (or drop the filter if
                # nothing matches, keeping the visual split honest).
                _enum_lookup: dict[str, list[str]] = {}
                _fields = entity_meta.get("fields") or entity_meta.get("columns") or []
                if isinstance(_fields, list):
                    for _f in _fields:
                        if isinstance(_f, dict):
                            _name = _f.get("name") or _f.get("column")
                            _enum = _f.get("enum_values") or _f.get("enum")
                            if isinstance(_name, str) and isinstance(_enum, list):
                                _enum_lookup[_name] = [str(v) for v in _enum if isinstance(v, str)]
                elif isinstance(_fields, dict):
                    for _name, _meta in _fields.items():
                        if isinstance(_meta, dict):
                            _enum = _meta.get("enum_values") or _meta.get("enum")
                            if isinstance(_name, str) and isinstance(_enum, list):
                                _enum_lookup[_name] = [str(v) for v in _enum if isinstance(v, str)]
                collection_node, data_sources = split_collection_into_sections(
                    base_node=collection_node,
                    base_ds_name=ds_name,
                    base_data_sources=data_sources,
                    sections=_sections,
                    vocabulary=vocabulary,
                    entity_columns=columns,
                    entity_enum_values=_enum_lookup,
                )
                layout_used = f"{layout_used}+sections({len(_sections)})"
                logger.info(
                    "[collection-maquette] section-split applied: route=%s "
                    "sections=%s", route, _sections,
                )
        except Exception as _ss_exc:  # noqa: BLE001
            logger.debug("[collection-maquette] section-split skipped: %s", _ss_exc)

    # Assemble the section list (hero → filter_presets → collection → footer).
    sections: list[dict] = []

    hero_node = _build_hero_node(maquette.get("hero"))
    if hero_node is not None:
        sections.append(hero_node)

    filters_node = _build_filter_chip_row(maquette.get("filter_presets") or [])
    if filters_node is not None:
        sections.append(filters_node)

    sections.append(collection_node)

    footer_node = _build_footer_node(maquette.get("footer"))
    if footer_node is not None:
        sections.append(footer_node)

    # ── root Stack props: signature-moves attr ──
    root_props: dict[str, Any] = {"gap": "tokens.spacing.6"}
    sig_moves = maquette.get("signature_moves") or []
    sig_moves = [s for s in sig_moves if isinstance(s, str) and s.strip()]
    if sig_moves:
        # Match dashboard composer's convention.
        root_props["data-signature-move"] = " ".join(sig_moves[:8])
    root_props["data-layout"] = layout_used

    new_schema: dict = {
        "schemaVersion": existing.get("schemaVersion", "2"),
        "id": root_id,
        "route": route,
        "layout": existing.get("layout", "main"),
        "dataSources": data_sources,
        "root": {"type": "Stack", "props": root_props, "children": sections},
    }
    prev_meta = existing.get("meta") if isinstance(existing.get("meta"), dict) else {}
    new_schema["meta"] = {**prev_meta, _MARKER_META_KEY: True}

    try:
        # Bootstrap path may need to create the schemas directory.
        schema_path.parent.mkdir(parents=True, exist_ok=True)
        # Sanitize Phase 2 metadata out of props before write.
        from services.composer_prop_hygiene import sanitize_schema as _sanitize
        _sanitize(new_schema)
        schema_path.write_text(json.dumps(new_schema, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return {"applied": False, "reason": f"write failed: {exc}"}

    logger.info(
        "[collection-maquette] composed %s (%s layout, %d sections)%s",
        schema_path.name, layout_used, len(sections),
        " (bootstrap)" if _bootstrapped else "",
    )
    return {"applied": True,
            "reason": "ok (bootstrap)" if _bootstrapped else "ok"}


# ─────────────────────────── schema lookup ─────────────────────────────


def _find_collection_schema(root: Path, route: str) -> Optional[Path]:
    """Find the schema file for a collection route.

    Tries in order:
      1. Well-known slug: ``<route-slug>.json`` in each schema dir.
      2. Leaf slug: last path segment of the route.
      3. Content match: any schema whose ``route`` field matches.
    """
    schema_dirs = [
        root / "src" / "schemas",
        root / "src" / "contracts" / "pages",
        root / "schemas" / "pages",
    ]
    slug = _route_to_slug(route)
    leaf = slug.split("/")[-1]

    for base in schema_dirs:
        if not base.is_dir():
            continue
        p = base / f"{slug}.json"
        if p.is_file():
            return p
        p2 = base / f"{leaf}.json"
        if p2.is_file():
            return p2

    # Content-based fallback.
    _target = route.rstrip("/")
    for base in schema_dirs:
        if not base.is_dir():
            continue
        for p in base.glob("**/*.json"):
            try:
                doc = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            r = str(doc.get("route") or "").rstrip("/")
            if r == _target:
                return p
    return None


def _route_to_slug(route: str) -> str:
    return route.strip("/") or "index"


# ─────────────────────────── registry helpers ──────────────────────────


def _load_registry(root: Path) -> dict:
    """Load the entity registry. Returns ``{}`` if missing.

    The composer only needs the ``entities`` map with per-entity fields
    (name + sqlType/type) — enough to resolve column type classes.
    """
    for candidate in (
        root / "src" / "contracts" / "registry.json",
        root / "src" / "contracts" / "plan.json",
    ):
        if candidate.is_file():
            try:
                _reg = json.loads(candidate.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            # Clean at the boundary: a composer that never receives
            # ``passwordHash`` cannot emit it, so the output sweep does
            # not need a second pass to strip it back out.
            from services.sensitive_column_guard import (
                strip_sensitive_from_registry,
            )
            _reg, _n = strip_sensitive_from_registry(_reg)
            if _n:
                logger.info(
                    "collection_maquette: %d sensitive column(s) withheld "
                    "from the composer", _n,
                )
            return _reg
    return {}


def _entity_meta(registry: dict, entity_name: str) -> dict:
    """Return the entity's meta dict from the registry or ``{}``."""
    entities = registry.get("entities") if isinstance(registry, dict) else None
    if isinstance(entities, dict):
        meta = entities.get(entity_name)
        if isinstance(meta, dict):
            return meta
    return {}


def _column_type_map(entity_meta: dict) -> dict[str, str]:
    """Return ``{column_name: sql_type_lowercase}``. Missing meta ⇒ ``{}``."""
    out: dict[str, str] = {}
    fields = entity_meta.get("fields") or entity_meta.get("columns") or []
    if isinstance(fields, list):
        for f in fields:
            if isinstance(f, dict):
                name = f.get("name") or f.get("column")
                t = f.get("type") or f.get("sqlType") or ""
                if isinstance(name, str) and name:
                    out[name] = str(t).lower()
    elif isinstance(fields, dict):
        for name, meta in fields.items():
            t = ""
            if isinstance(meta, dict):
                t = meta.get("type") or meta.get("sqlType") or ""
            if isinstance(name, str):
                out[name] = str(t).lower()
    return out


# ─────────────────────────── layout builders ───────────────────────────


_STATUS_HINTS = ("status", "state", "stage", "phase")
_DATE_TYPE_MARKERS = ("date", "time", "timestamp")


def _pick_status_column(columns: dict[str, str]) -> Optional[str]:
    for name in columns:
        lo = name.lower()
        if any(h == lo or h in lo for h in _STATUS_HINTS):
            return name
    return None


def _pick_date_column(columns: dict[str, str]) -> Optional[str]:
    # Prefer explicit event-anchors (startAt/startTime/date/on…) over
    # created/updated.
    priority = ("startat", "starttime", "startdate", "date", "eventat",
                "scheduledat", "dueat", "occursat")
    for pref in priority:
        for name in columns:
            if name.lower() == pref:
                return name
    for name, t in columns.items():
        if t in _DATE_TYPE_MARKERS or any(m in t for m in _DATE_TYPE_MARKERS):
            if name.lower() not in ("createdat", "updatedat", "deletedat"):
                return name
    # Last resort: createdAt.
    for name in columns:
        if name.lower() == "createdat":
            return name
    return None


def _build_collection_node(
    *,
    entity: str,
    route: str,
    layout: str,
    maquette: dict,
    columns: dict[str, str],
    row_treatment: str,
    vocabulary: Any = None,
) -> tuple[Optional[dict], str, list[dict], str]:
    """Return (collection_node, dataSource_name, dataSources_list, layout_used).

    Returns (None, "", [], "") when we can't build anything (unlikely —
    the "table" fallback always produces a node if there's any column at
    all; only fires when the maquette has zero columns AND the registry
    has zero columns for the entity).

    ``layout_used`` may differ from ``layout`` when a requested layout
    falls back (e.g. kanban without a status column → table).
    """
    ds_name = _route_to_slug(route).replace("/", "_") or entity
    # Sanitize to identifier — the runtime binding syntax is stricter.
    ds_name = re.sub(r"[^A-Za-z0-9_]", "_", ds_name).strip("_") or entity
    data_sources: list[dict] = [{"name": ds_name, "entity": entity, "op": "list"}]

    mq_cols = _maquette_columns(maquette, columns,
                                vocabulary=vocabulary, entity=entity)

    layout_used = layout
    if layout == "kanban":
        status_col = _pick_status_column(columns) or _pick_status_column(dict.fromkeys(mq_cols, ""))
        if status_col:
            node = {
                "type": "Kanban",
                "props": {
                    "data": f"{{{{{ds_name}}}}}",
                    "groupBy": status_col,
                    "cardTitle": _primary_column(mq_cols),
                    "cardHref": f"{route.rstrip('/')}/{{id}}",
                    "data-row-treatment": row_treatment,
                },
            }
            _apply_empty_slot(node, maquette, vocabulary=vocabulary, entity=entity, route=route)
            return node, ds_name, data_sources, "kanban"
        # fallback
        layout_used = "table"

    if layout == "calendar":
        date_col = _pick_date_column(columns)
        if date_col:
            node = {
                "type": "Calendar",
                "props": {
                    "data": f"{{{{{ds_name}}}}}",
                    "dateField": date_col,
                    "cardTitle": _primary_column(mq_cols),
                    "cardHref": f"{route.rstrip('/')}/{{id}}",
                    "data-row-treatment": row_treatment,
                },
            }
            _apply_empty_slot(node, maquette, vocabulary=vocabulary, entity=entity, route=route)
            return node, ds_name, data_sources, "calendar"
        layout_used = "table"

    if layout == "timeline":
        date_col = _pick_date_column(columns)
        if date_col:
            node = {
                "type": "TimelineList",
                "props": {
                    "data": f"{{{{{ds_name}}}}}",
                    "dateField": date_col,
                    "title": _primary_column(mq_cols),
                    "rowHref": f"{route.rstrip('/')}/{{id}}",
                    "data-row-treatment": row_treatment,
                },
            }
            _apply_empty_slot(node, maquette, vocabulary=vocabulary, entity=entity, route=route)
            return node, ds_name, data_sources, "timeline"
        layout_used = "table"

    # SL2-2: vocabulary shape aliases. ``card-grid`` maps to the
    # existing "cards" branch; ``schedule-grid`` maps to "calendar"
    # when a date column exists (falls back to table otherwise). The
    # aliases live at THIS layer, not upstream, so tests + the maquette
    # LLM can still request "cards" / "calendar" directly.
    if layout == "card-grid":
        layout = "cards"
    if layout == "schedule-grid":
        # A schedule-grid needs a date anchor; without one it can't
        # visually differentiate rows by time. Fall through to
        # calendar (which does the same fallback to table).
        layout = "calendar"

    # Slice-3 (banking): ledger-list layout — the transaction-history
    # signature for banking apps. A dense row-per-transaction Table with
    # a right-aligned amount (formatted as currency), a status badge, a
    # relative-timestamp column, and a trailing running-balance column
    # bound to a companion op:"series" agg:"running_sum" dataSource.
    # Row style: subtle top border between rows (data-row-treatment
    # "compact"), no per-row card wrapper — a real ledger is one
    # continuous register, not stacked cards.
    if layout == "ledger-list":
        primary = _primary_column(mq_cols)
        # Money columns get MoneyDisplay with a per-row currency binding
        # to the sibling column the schema builder emits (Slice-2). Every
        # other column renders as a Text so the row layout is uniform.
        money_cols = [c for c in mq_cols if columns.get(c, "") in ("money", "currency")]
        status_col = _pick_status_column(columns)
        date_col = _pick_date_column(columns) or "createdAt"
        # Table with typed columns; format:"currency" right-aligns the
        # money cell + Intl-formats the amount. Per-row currency (from the
        # sibling _currency column) is a Table-level limitation we leave
        # to a follow-up (needs a `currencyKey` column-def extension).
        table_columns: list[dict] = [
            {"key": primary, "label": _humanize(primary)},
        ]
        for m in money_cols:
            table_columns.append({
                "key": m, "label": _humanize(m),
                "format": "currency", "align": "right",
            })
        if status_col and status_col not in (primary, *money_cols):
            table_columns.append({
                "key": status_col, "label": _humanize(status_col),
                "format": "badge",
            })
        if date_col not in (primary, status_col, *money_cols):
            table_columns.append({
                "key": date_col, "label": "When",
                "format": "datetime", "align": "right",
            })
        # Order newest-first: matches how humans read a ledger (most
        # recent at the top). Encoded via orderBy on the list dataSource.
        list_ds_name = ds_name
        data_sources = [{
            "name": list_ds_name, "entity": entity, "op": "list",
            "orderBy": [{"field": date_col, "dir": "desc"}],
        }]
        # Companion running-balance dataSource — every money column gets
        # its own running total keyed by createdAt. The client uses it to
        # render a trailing balance column; when the client hasn't wired
        # that yet, the dataSource still resolves and the source is a
        # zero-cost query (cached until page nav).
        for m in money_cols:
            data_sources.append({
                "name": f"{list_ds_name}Running{_cap(m)}",
                "entity": entity, "op": "series",
                "agg": {"fn": "running_sum", "field": m},
                "orderByCol": date_col,
            })
        node = {
            "type": "Table",
            "props": {
                "columns": table_columns,
                "rows": f"{{{{{list_ds_name}}}}}",
                "rowHref": f"{route.rstrip('/')}/{{id}}",
                "data-row-treatment": "compact",
                "data-shape": "ledger-list",
            },
        }
        _apply_empty_slot(node, maquette, vocabulary=vocabulary, entity=entity, route=route)
        return node, list_ds_name, data_sources, "ledger-list"

    # SL2-2: card-list layout — the Claude-yoga-demo booking-card
    # pattern. One padded pill per row with title + inline metadata
    # (dot-separated) + right-side action anchor. Used for "your
    # things" screens (bookings, reviews, appointments) — reader
    # wants a scannable card, not a sortable data grid.
    if layout == "card-list":
        primary = _primary_column(mq_cols)
        # Up to 3 secondary fields shown as inline meta (icon+text
        # pairs would be nicer but require per-field icon inference —
        # deferred to a follow-on slice).
        meta_fields = [c for c in mq_cols if c != primary][:3]
        detail_href = f"{route.rstrip('/')}/{{{{item.id}}}}"
        # Build the meta row: `{{item.field1}} · {{item.field2}} · …`.
        # Each field is a Text node so the runtime can format it
        # per-type; the dot separator is a plain Text between them.
        meta_children: list[dict] = []
        for i, f in enumerate(meta_fields):
            if i > 0:
                meta_children.append({
                    "type": "Text",
                    "props": {"content": "·", "tone": "muted",
                              "className": "opacity-40"},
                })
            meta_children.append({
                "type": "Text",
                "props": {"content": "{{item." + f + "}}", "tone": "muted"},
            })
        card_children: list[dict] = [
            {
                "type": "Row",
                "props": {"justify": "between", "align": "center",
                          "gap": "tokens.spacing.3"},
                "children": [
                    {
                        "type": "Stack",
                        "props": {"gap": "tokens.spacing.1"},
                        "children": [
                            {"type": "Heading",
                             "props": {"content": "{{item." + primary + "}}",
                                       "level": 4}},
                            *([{"type": "Row",
                                "props": {"gap": "tokens.spacing.2",
                                          "align": "center"},
                                "children": meta_children}] if meta_children else []),
                        ],
                    },
                    # Right-side chevron affordance — signals row is
                    # actionable without demanding a specific action verb.
                    {"type": "Text",
                     "props": {"content": "›", "tone": "muted",
                               "className": "text-xl opacity-40"}},
                ],
            },
        ]
        node = {
            "type": "Stack",
            "props": {"gap": "tokens.spacing.3"},
            "children": [{
                "type": "Repeat",
                # Node-level `bind` with a BARE name. props.bind was read by
                # nothing, and the `{{ }}` wrapper made it an expression rather
                # than the source name the renderer looks up.
                "bind": ds_name,
                "props": {"as": "item"},
                "children": [{
                    "type": "Card",
                    "props": {
                        "elevation": "sm",
                        "href": detail_href,
                        "data-row-treatment": row_treatment,
                    },
                    "children": card_children,
                }],
            }],
        }
        _apply_empty_slot(node, maquette, vocabulary=vocabulary, entity=entity, route=route)
        return node, ds_name, data_sources, "card-list"

    if layout == "cards":
        primary = _primary_column(mq_cols)
        secondary = [c for c in mq_cols if c != primary][:3]
        # `CardGrid` is not a real component (was rendering as a solid
        # error-tinted bar because the renderer's discriminated union
        # doesn't accept it). Substitute with the real primitives that
        # ARE in the registry: a responsive Grid, a Repeat data
        # iterator, and Card children with the primary heading + up to
        # three secondary text lines.
        card_children: list[dict] = [
            {"type": "Heading",
             "props": {"content": "{{item." + primary + "}}", "level": 3}},
        ]
        for f in secondary:
            card_children.append({
                "type": "Text",
                "props": {"content": "{{item." + f + "}}", "tone": "muted"},
            })
        detail_href = f"{route.rstrip('/')}/{{{{item.id}}}}"
        node = _card_grid_node(ds_name, detail_href, card_children)
        _apply_empty_slot(node, maquette, vocabulary=vocabulary, entity=entity, route=route)
        return node, ds_name, data_sources, "cards"

    # Default: table
    table_columns: list[dict] = []
    for col_name in mq_cols:
        table_columns.append({"key": col_name, "label": _humanize(col_name)})
    if not table_columns:
        # Nothing to render — the composer refuses.
        return None, "", [], ""
    node = {
        "type": "Table",
        "props": {
            "columns": table_columns,
            "rows": f"{{{{{ds_name}}}}}",
            "rowHref": f"{route.rstrip('/')}/{{id}}",
            "data-row-treatment": row_treatment,
        },
    }
    _apply_empty_slot(node, maquette, vocabulary=vocabulary, entity=entity, route=route)
    return node, ds_name, data_sources, "table"


def _maquette_columns(maquette: dict, real_columns: dict[str, str],
                      *, vocabulary: Any = None, entity: str = "") -> list[str]:
    """Ordered column names for the collection, filtered to real columns.

    Three tiers, most-specific first: the maquette's own choice, then the
    archetype's page recipe, then raw registry order. That middle tier
    exists because registry order is insertion order — so the old
    fallback led warehouse tables with `id` and `createdAt` while SKU and
    on-hand quantity sat off the right edge. A domain has a reading
    order; when the author didn't supply one, use the domain's rather
    than the database's.
    """
    out: list[str] = []
    for c in maquette.get("columns") or []:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        if isinstance(name, str) and name and (not real_columns or name in real_columns):
            out.append(name)
    if out:
        return out

    if vocabulary is not None and entity:
        try:
            from services.page_vocabulary import resolve_page_recipe
            recipe = resolve_page_recipe(
                vocabulary, entity, {"fields": list(real_columns.keys())})
        except Exception:  # noqa: BLE001
            recipe = {}
        if recipe.get("list_columns"):
            logger.info("[collection] %s columns from archetype recipe: %s",
                        entity, recipe["list_columns"])
            return recipe["list_columns"]

    # Last resort: registry order, minus the keys nobody reads.
    return [n for n in real_columns.keys() if n.lower() not in ("id", "uuid")][:6]


# The card grid the collection composer emits when the maquette asks for cards.
# Extracted so there is one statement of the shape, and so it can be tested
# without composing a whole page.
_CARD_GRID_COLUMNS = 3


def _card_grid_node(ds_name: str, detail_href: str,
                    card_children: list[dict]) -> dict:
    """A Repeat of Cards laid out as a grid.

    This emitted ``cols: {"base": 1, "sm": 2, "lg": 3}``. Grid takes a NUMBER
    and owns that exact responsive ladder itself (columns=3 ->
    `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3`), so the object described the
    behaviour the renderer already had while reading as nothing at all — Grid
    fell back to one column. The page rendered a single stacked strip.

    The column count has to be STATED here: the only child is a Repeat that
    fans out when the data arrives, so nothing downstream can count the cards.

    Density comes from services.section_layout — the same rule the
    post-generate pass applies, imported rather than restated, so a card is the
    same width whichever got there first.
    """
    from services.section_layout import density_for_columns

    card_props: dict = {"elevation": "sm", "href": detail_href}
    density = density_for_columns(_CARD_GRID_COLUMNS)
    if density:
        card_props["density"] = density
    return {
        "type": "Grid",
        "props": {
            "columns": _CARD_GRID_COLUMNS,
            "gap": "tokens.spacing.4",
            "equalRows": True,
            "equalCols": True,
        },
        "children": [{
            "type": "Repeat",
            # Node-level `bind` with a BARE name. props.bind was read by
            # nothing, and the `{{ }}` wrapper made it an expression rather
            # than the source name the renderer looks up.
            "bind": ds_name,
            "props": {"as": "item"},
            "children": [{
                "type": "Card",
                "props": card_props,
                "children": card_children,
            }],
        }],
    }


def _primary_column(cols: list[str]) -> str:
    return cols[0] if cols else "id"


# ─────────────────────────── slot builders ─────────────────────────────


def _build_hero_node(hero: Any) -> Optional[dict]:
    """Compact hero band above the collection.

    Different from a dashboard hero — a collection hero is just a small
    header row with title + subtitle + optional badge, wrapped in a
    Row so it sits inline with the collection frame.
    """
    if not isinstance(hero, dict):
        return None
    title = hero.get("title")
    if not (isinstance(title, str) and title.strip()):
        return None
    subtitle = hero.get("subtitle") if isinstance(hero.get("subtitle"), str) else None
    badge = hero.get("badge") if isinstance(hero.get("badge"), str) else None

    left_children: list[dict] = [
        {"type": "Heading", "props": {"content": title.strip(), "level": 1}},
    ]
    if subtitle:
        left_children.append({"type": "Text", "props": {"content": subtitle,
                                                          "variant": "caption"}})
    row_children: list[dict] = [{
        "type": "Stack",
        "props": {"gap": "tokens.spacing.1"},
        "children": left_children,
    }]
    if badge:
        row_children.append({"type": "Badge", "props": {"content": badge, "tone": "neutral"}})

    return {
        "type": "Row",
        "props": {"justify": "between", "align": "center", "data-slot": "collection-hero"},
        "children": row_children,
    }


def _build_filter_chip_row(presets: list) -> Optional[dict]:
    """Chip row of filter presets. Returns None if there are none.

    Each chip is a Tag conforming to the renderer's schema
    (packages/schema/nodes/display.ts TagNode):
    props are strict — only ``label`` (required), ``variant``, and
    ``removable``. The filter expression is stashed on the node itself
    (outside ``props``) as ``data-filter-expr`` so a later runtime
    slice can pick it up without the strict-props check rejecting it.
    """
    chips: list[dict] = []
    for i, p in enumerate(presets):
        if not isinstance(p, dict):
            continue
        label = p.get("label")
        expr = p.get("expr")
        if not (isinstance(label, str) and label and isinstance(expr, str) and expr):
            continue
        # First chip = active preset (accent variant, respects
        # --accent design token). Remaining chips = neutral default
        # so the active one visually leads. Matches the Claude yoga
        # demo's "one chip highlighted, others muted" pattern.
        variant = "accent" if i == 0 else "default"
        chip: dict = {
            "type": "Tag",
            "props": {"label": label, "variant": variant},
        }
        # Stash the filter expression on the node, NOT in props — props
        # is .strict() and would reject an unknown key. Nothing in the
        # renderer consumes this today; it's a hook for a later slice.
        chip["data-filter-expr"] = expr
        chips.append(chip)
    if not chips:
        return None
    # Cluster (not Row) — chips need flex-wrap on mobile so they don't
    # overflow the viewport. Cluster is exactly this: flex + wrap +
    # gap + configurable align/justify. Row is single-axis, no wrap.
    return {
        "type": "Cluster",
        "props": {"gap": "tokens.spacing.2", "align": "center",
                  "justify": "start"},
        "data-slot": "collection-filters",
        "children": chips,
    }


def _apply_empty_slot(collection_node: dict, maquette: dict,
                       *, vocabulary: Any = None,
                       entity: str = "", route: str = "") -> None:
    """Set the collection primitive's empty-state props from the maquette.

    Applies to Table today; other primitives get the same props for
    the future to grow into (renderer decides what to do with unknown
    props). The maquette wins where it declares empty-state fields;
    the archetype vocabulary (SL2-3) fills BLANK fields with domain-
    voiced copy — never overwrites a maquette-authored value.

    Precedence, per field:
      1. maquette.empty_state.<field> (LLM-authored intent)
      2. vocabulary lookup (archetype-conventional copy)
      3. leave the field unset (renderer's built-in default)
    """
    empty = maquette.get("empty_state") if isinstance(maquette.get("empty_state"), dict) else {}
    illustration = empty.get("illustration") if isinstance(empty.get("illustration"), str) else None
    headline = empty.get("headline") if isinstance(empty.get("headline"), str) else None
    subhead = empty.get("subhead") if isinstance(empty.get("subhead"), str) else None
    cta_label = empty.get("cta_label") if isinstance(empty.get("cta_label"), str) else None
    cta_action = empty.get("cta_action") if isinstance(empty.get("cta_action"), str) else None

    # SL2-3: fall back to archetype vocabulary when the maquette left
    # a field blank. `resolve_empty_state` returns {} when there's no
    # vocabulary match — we merge conservatively.
    if vocabulary is not None:
        try:
            from services.empty_state_library import resolve_empty_state
            vocab_copy = resolve_empty_state(vocabulary, entity, route=route)
            if headline is None:
                headline = vocab_copy.get("headline")
            if subhead is None:
                subhead = vocab_copy.get("subhead")
            if cta_label is None:
                cta_label = vocab_copy.get("cta_label")
            if cta_action is None:
                cta_action = vocab_copy.get("cta_action")
        except Exception as _es_exc:  # noqa: BLE001
            logger.debug("[collection-maquette] empty-state lookup failed: %s", _es_exc)

    props = collection_node.setdefault("props", {})
    if headline:
        props["emptyText"] = headline
    if subhead:
        props["emptyDescription"] = subhead
    if illustration:
        props["emptyIllustration"] = illustration
    if cta_label and cta_action:
        props["emptyAction"] = {"label": cta_label, "navigate": cta_action}


def _build_footer_node(footer: Any) -> Optional[dict]:
    if not isinstance(footer, dict):
        return None
    kind = footer.get("kind")
    if not (isinstance(kind, str) and kind in ("total-row", "batch-actions",
                                                "insight", "add-affordance")):
        return None
    content = footer.get("content") if isinstance(footer.get("content"), str) else None

    if kind == "total-row":
        return {
            "type": "Row",
            "props": {"justify": "end", "align": "center",
                      "data-slot": "collection-footer", "data-footer-kind": "total-row"},
            "children": [
                {"type": "Text",
                 "props": {"content": content or "Total", "variant": "caption"}},
            ],
        }
    if kind == "insight":
        return {
            "type": "Card",
            "props": {"padding": "tokens.spacing.4",
                      "data-slot": "collection-footer", "data-footer-kind": "insight"},
            "children": [
                {"type": "Text", "props": {"content": content or ""}},
            ],
        }
    if kind == "batch-actions":
        return {
            "type": "Row",
            "props": {"justify": "between", "align": "center",
                      "data-slot": "collection-footer", "data-footer-kind": "batch-actions"},
            "children": [
                {"type": "Text",
                 "props": {"content": content or "Bulk actions", "variant": "caption"}},
            ],
        }
    # add-affordance
    return {
        "type": "Row",
        "props": {"justify": "end", "align": "center",
                  "data-slot": "collection-footer", "data-footer-kind": "add-affordance"},
        "children": [
            {"type": "Text",
             "props": {"content": content or "Add another", "variant": "caption"}},
        ],
    }


# ─────────────────────────── humanize ──────────────────────────────────


def _humanize(name: str) -> str:
    """Column name → human label."""
    # Split camelCase and snake_case.
    s = re.sub(r"(?<!^)(?=[A-Z])", " ", name).replace("_", " ").strip()
    return " ".join(w.capitalize() for w in s.split())


def _cap(name: str) -> str:
    """Cap first letter of an identifier (for building dataSource names)."""
    return name[:1].upper() + name[1:] if name else name


# ─────────────────────────── authority helpers (Phase 6a) ──────────────


def _is_collection_authority_enabled() -> bool:
    """Import-safe check for FORGE_COLLECTION_AUTHORITY.

    Any import failure defaults False — safety: legacy behaviour is the
    fall-through path.
    """
    try:
        from services.artifact_authority import is_authority_enabled
        return is_authority_enabled("collection")
    except Exception:  # noqa: BLE001
        return False


def _plan_collection_pages(root: Path) -> list[dict]:
    """Return the list of collection-typed pages from ``plan.json``.

    Used by the recipe-fallback path to know which pages need a bootstrap
    when no maquette exists. Returns [] on any read failure.
    """
    plan_path = root / "src" / "contracts" / "plan.json"
    if not plan_path.is_file():
        return []
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    try:
        from services.artifact_authority import is_page_of_kind
    except Exception:  # noqa: BLE001
        return []
    out: list[dict] = []
    for p in plan.get("pages") or []:
        if isinstance(p, dict) and is_page_of_kind(p, "collection"):
            out.append(p)
    return out


def _fallback_all_collections_via_recipe(root: Path, *, reason: str) -> dict[str, Any]:
    """Recipe-fill every collection page when NO maquettes file exists.

    Used when the LLM maquette-authoring step failed entirely (no file
    at all) and the authority flag is on. Writes a deterministic schema
    per collection page in the plan.
    """
    pages = _plan_collection_pages(root)
    if not pages:
        return {"applied": 0, "skipped": 0,
                "reasons": [f"{reason}; no collection pages in plan"]}
    return _recipe_fill_pages(root, pages, reason_prefix=reason)


def _fallback_missing_collections_via_recipe(
    root: Path, *, applied_routes: set[str | None],
) -> dict[str, Any]:
    """After maquette entries run, recipe-fill any collection page in
    the plan that we haven't written yet.

    ``applied_routes`` is the set of routes we did have a maquette entry
    for — used to skip pages the maquette-driven path already handled.
    """
    pages = [p for p in _plan_collection_pages(root)
             if p.get("route") not in applied_routes]
    if not pages:
        return {"applied": 0, "reasons": []}
    return _recipe_fill_pages(root, pages, reason_prefix="tail-fill (no maquette entry)")


def _recipe_fill_pages(root: Path, pages: list[dict], *, reason_prefix: str) -> dict[str, Any]:
    """Deterministic-build each page via services.deterministic_pages.

    Idempotent: if the file already exists AND carries the composer
    marker, skip it (something else already wrote it deterministically).
    """
    registry = _load_registry(root)
    entities = registry.get("entities") if isinstance(registry, dict) else {}
    if not isinstance(entities, dict):
        entities = {}
    from services.deterministic_pages import (
        build_list_page, build_kanban_page, build_calendar_page,
    )
    applied = 0
    reasons: list[str] = []
    for page in pages:
        route = page.get("route")
        entity = page.get("entity") or page.get("primary_entity")
        if not (isinstance(route, str) and route.startswith("/")):
            continue
        if not (isinstance(entity, str) and entity):
            reasons.append(f"{route}: no entity")
            continue
        entity_meta = entities.get(entity) or {}
        columns = _column_type_map(entity_meta)
        if not columns:
            reasons.append(f"{route}: no entity columns")
            continue

        slug = _route_to_slug(route)
        target = root / "src" / "schemas" / f"{slug}.json"
        # Skip pages the maquette composer already wrote.
        if target.is_file():
            try:
                existing = json.loads(target.read_text(encoding="utf-8"))
                if isinstance(existing, dict) and isinstance(existing.get("meta"), dict):
                    if existing["meta"].get(_MARKER_META_KEY) is True:
                        continue
            except Exception:  # noqa: BLE001
                pass

        # Dispatch to the right deterministic builder based on page type.
        ptype = str(page.get("type") or page.get("archetype") or "list").lower()
        try:
            if ptype == "kanban":
                schema = build_kanban_page(entity, columns, route,
                                            design_spec=None, page_hint=page)
            elif ptype == "calendar":
                # build_calendar_page has no page_hint param today.
                schema = build_calendar_page(entity, columns, route,
                                              design_spec=None)
            else:
                schema = build_list_page(entity, columns, route,
                                          design_spec=None, page_hint=page)
            target.parent.mkdir(parents=True, exist_ok=True)
            # Recipe-fallback path also needs prop hygiene.
            from services.composer_prop_hygiene import sanitize_schema as _sanitize
            _sanitize(schema)
            target.write_text(json.dumps(schema, indent=2), encoding="utf-8")
            applied += 1
            reasons.append(f"{route}: recipe-filled ({reason_prefix})")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[collection-maquette] recipe-fill failed for %s: %s",
                           route, exc)
            reasons.append(f"{route}: recipe-fill failed: {exc}")
    return {"applied": applied, "skipped": 0, "reasons": reasons}
