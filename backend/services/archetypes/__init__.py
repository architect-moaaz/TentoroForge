"""Archetype library — curated recipes for common app patterns.

Each archetype declares:
  - NAME:           the canonical id used across the pipeline
  - KEYWORDS:       phrases the classifier scores against a prompt
  - DEFAULT_ACTORS: seeded actor list the extractor unions with
  - DEFAULT_ENTITIES: entity records the extractor unions with. The
                    archetype's `kind` classification WINS over the
                    heuristic classifier so "Scan" is guaranteed to
                    be treated as an event even if a user prompt
                    accidentally hints otherwise.
  - DEFAULT_FEATURES: feature records the extractor unions with.
  - DEFAULT_WORKFLOWS: workflow names planner should emit.
  - DEFAULT_COMPONENTS: component types typical for this archetype
                    (used by future component-suggestion passes).
  - ANTI_ENTITIES: entities to REJECT even if the prompt suggests
                    them — kills the "product mentions → forge_cart"
                    class of false positives.
  - EXTERNALS:      external services the archetype implies.

Adding a new archetype: create backend/services/archetypes/<name>.py,
export the seven fields above, add its module to _ALL_ARCHETYPES below,
add a KEYWORDS-based detector test in test_archetype_detector.py, and
that's it — the detector + locked_spec pick it up automatically.
"""
from __future__ import annotations

from . import visual_product_search

_ALL_ARCHETYPES = [visual_product_search]


def all_archetypes():
    """Return every archetype module registered in the library."""
    return list(_ALL_ARCHETYPES)


def get_archetype(name: str):
    """Return the archetype module with the given NAME, or None."""
    for mod in _ALL_ARCHETYPES:
        if getattr(mod, "NAME", None) == name:
            return mod
    return None


def ensure_required_pages(plan: dict) -> int:
    """Union the archetype's `REQUIRED_PAGES` into `plan['pages']`.

    Idempotent — if a page with the same `route` already exists, keep the
    planner's version (it may have specialized the shape). Only inject
    routes the plan is genuinely missing.

    Returns the number of pages actually injected. Never raises; a missing
    archetype module or a plan without pages is a silent no-op.
    """
    if not isinstance(plan, dict):
        return 0
    archetype = plan.get("archetype") or plan.get("app_archetype")
    if not archetype:
        return 0
    mod = get_archetype(archetype)
    if mod is None:
        return 0
    required = getattr(mod, "REQUIRED_PAGES", None) or []
    if not required:
        return 0

    pages = plan.get("pages")
    if not isinstance(pages, list):
        pages = []
        plan["pages"] = pages

    existing_routes = {p.get("route") for p in pages if isinstance(p, dict)}
    injected = 0
    for spec in required:
        if not isinstance(spec, dict):
            continue
        route = spec.get("route")
        if not route or route in existing_routes:
            continue
        pages.append(dict(spec))
        existing_routes.add(route)
        injected += 1
    return injected


def _canon_name(s) -> str:
    import re
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def ensure_required_workflows(plan: dict) -> int:
    """Union the archetype's `REQUIRED_WORKFLOWS` into `plan['workflows']`.

    Fuzzy-matched by normalized name (contains either way) so a
    planner-authored "Scan Barcode Workflow" satisfies the requirement for
    "BarcodeSearchWorkflow". Injected entries carry empty steps — the
    archetype-owned deterministic emitter authors the node graph, keyed on
    the name. Idempotent; never raises."""
    if not isinstance(plan, dict):
        return 0
    mod = get_archetype(plan.get("archetype") or plan.get("app_archetype") or "")
    if mod is None:
        return 0
    required = getattr(mod, "REQUIRED_WORKFLOWS", None) or []
    if not required:
        return 0
    wfs = plan.get("workflows")
    if not isinstance(wfs, list):
        wfs = []
        plan["workflows"] = wfs
    existing = [_canon_name(w.get("name")) for w in wfs if isinstance(w, dict)]

    # The archetype_workflows alias registry is the single source of truth
    # for "which names mean the same workflow" — if an existing plan
    # workflow resolves to the same emitter as the required name, the
    # requirement is satisfied (e.g. "Scan Barcode Workflow" satisfies
    # "BarcodeSearchWorkflow").
    archetype = plan.get("archetype") or plan.get("app_archetype")
    try:
        from services.archetype_workflows import find_emitter as _find_emitter
    except Exception:  # pragma: no cover
        _find_emitter = None  # type: ignore[assignment]

    injected = 0
    for spec in required:
        if not isinstance(spec, dict):
            continue
        want = _canon_name(spec.get("name"))
        if not want:
            continue
        if any(want in have or have in want for have in existing if have):
            continue
        if _find_emitter is not None:
            target = _find_emitter(archetype, spec.get("name"))
            if target is not None and any(
                _find_emitter(archetype, w.get("name")) is target
                for w in wfs if isinstance(w, dict)
            ):
                continue
        wfs.append(dict(spec))
        existing.append(want)
        injected += 1
    return injected


def ensure_required_columns(plan: dict) -> int:
    """Union the archetype's `REQUIRED_ENTITY_COLUMNS` into plan.data_models.

    For each spec, find the data_models entry whose name fuzzy-matches an
    entity candidate and append any fields it is missing (matched by
    normalized name, so `image_url` satisfies `imageUrl`). Entities the
    plan doesn't have at all are skipped — pages/workflows for them would
    be missing too, and inventing whole entities is the planner's job.
    Idempotent; never raises."""
    if not isinstance(plan, dict):
        return 0
    mod = get_archetype(plan.get("archetype") or plan.get("app_archetype") or "")
    if mod is None:
        return 0
    required = getattr(mod, "REQUIRED_ENTITY_COLUMNS", None) or []
    dms = plan.get("data_models")
    if not required or not isinstance(dms, list):
        return 0
    injected = 0
    for spec in required:
        if not isinstance(spec, dict):
            continue
        cands = [_canon_name(c) for c in (spec.get("entity_candidates") or [])]
        target = None
        for dm in dms:
            if not isinstance(dm, dict):
                continue
            nm = _canon_name(dm.get("name"))
            if nm and any(c == nm or c in nm or nm in c for c in cands if c):
                target = dm
                break
        if target is None:
            continue
        fields = target.get("fields")
        if not isinstance(fields, list):
            fields = []
            target["fields"] = fields
        have = {_canon_name(f.get("name")) for f in fields if isinstance(f, dict)}
        for f in spec.get("fields") or []:
            if isinstance(f, dict) and _canon_name(f.get("name")) not in have:
                fields.append(dict(f))
                have.add(_canon_name(f.get("name")))
                injected += 1
    return injected
