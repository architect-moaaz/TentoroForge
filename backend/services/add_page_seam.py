"""S5-T2 — `add_page` composite seam.

Smith's tool for adding a whole new page to an existing app: not a patch,
not a piecemeal edit, but the incremental analogue of what the pipeline
does for a fresh app. Same builders, same file layout, same guards. The
difference is *when* — one page at a time, on top of a real tree.

Design principle (recap):
    Smith reuses the pipeline's own primitives. `add_page` never
    hand-writes JSON — it synthesizes a planner-shaped "page" dict
    from Smith's params and dispatches through
    :func:`services.deterministic_pages.build_crud_page`, the same
    builder the pipeline calls at generation time.

Files this seam writes (all atomically via services.atomic_apply):
    * ``src/schemas/<slug>.json``       — the new page schema
    * ``src/contracts/nav-flow.json``   — new page entry + transition
    * (future) ``src/schemas/shell.json`` — sidebar menu item

The public entry point is :func:`build_add_page_bundle`, which returns
a list of ``BundleOp`` the applier ships through
:func:`services.atomic_apply.apply_bundle`. Callers (Smith's router
branch, tests, a future editor "add page" command) do not need to know
which files the seam touches.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from services.atomic_apply import BundleOp

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Public: the deterministic archetype set
# --------------------------------------------------------------------------- #

DETERMINISTIC_ARCHETYPES: tuple[str, ...] = (
    "list", "form", "create", "edit", "detail", "kanban", "calendar",
)
"""What ``services.deterministic_pages.build_crud_page`` can handle
without an LLM. Any other archetype falls to the LLM path (see
:mod:`agents.page_schema_agent`), which this seam does NOT yet invoke
— that's a follow-up. For slice T2 we ONLY handle deterministic
archetypes and refuse the rest with an actionable error."""


# --------------------------------------------------------------------------- #
# Result shape
# --------------------------------------------------------------------------- #

class AddPageError(ValueError):
    """Raised when the seam can't build a bundle — caller renders the
    message directly. Preferred over bare ValueError so callers can
    branch on this class."""


# --------------------------------------------------------------------------- #
# Public builder
# --------------------------------------------------------------------------- #

def build_add_page_bundle(
    output_dir: str,
    *,
    archetype: str,
    entity: str,
    route: str,
    title: Optional[str] = None,
    fields: Optional[list[dict]] = None,
    features: Optional[list[str]] = None,
) -> list[BundleOp]:
    """Compose the atomic-apply bundle for a new page.

    Args:
        output_dir: The generated app's root.
        archetype: One of :data:`DETERMINISTIC_ARCHETYPES`. Values outside
            this set raise :class:`AddPageError` — Smith should fall
            back to ``handoff_to_pipeline("refine", ...)`` for those.
        entity: The primary bound entity name (matches the registry's
            ``entities[].name``). Used by the builder for FK resolution,
            column derivation, and dataSource wiring.
        route: URL route (``/pipeline``). Leading slash required.
        title: Optional display title. Defaults to a humanized route.
        fields: Optional per-field spec (planner shape). When present,
            the builder merges these over registry-derived defaults
            — same behaviour the pipeline gives the planner.
        features: Optional list of archetype-specific hints, e.g.
            ``["groupBy:stage"]`` for kanban. Parsed and threaded to
            the builder through the synthetic page dict.

    Returns:
        A list of :class:`BundleOp` ready for
        :func:`services.atomic_apply.apply_bundle`.

    Raises:
        AddPageError: On unsupported archetype, unknown entity, invalid
            route, or when the deterministic builder refuses to emit
            (returns None).
    """
    out = Path(output_dir)
    if not out.is_dir():
        raise AddPageError(f"output_dir missing: {output_dir}")

    archetype = (archetype or "").strip().lower()
    if archetype not in DETERMINISTIC_ARCHETYPES:
        raise AddPageError(
            f"archetype {archetype!r} is not deterministic. "
            f"Supported: {sorted(DETERMINISTIC_ARCHETYPES)}. "
            "Hand off to the LLM refiner for bespoke pages."
        )

    if not isinstance(route, str) or not route.startswith("/"):
        raise AddPageError(f"route must start with '/', got {route!r}")

    entities = _load_entities(out)
    entity_meta = _find_entity(entities, entity)
    if entity_meta is None:
        raise AddPageError(
            f"entity {entity!r} not found in registry. "
            f"Available: {sorted(entities.keys())}"
        )
    entity_name = entity_meta["_name"]  # canonical casing
    columns = entity_meta.get("fields") or {}

    # 1. Build the page schema via the pipeline's deterministic builder.
    page_dict = _build_page_via_pipeline(
        output_dir=str(out),
        archetype=archetype,
        entity=entity_name,
        columns=columns,
        route=route,
        fields=fields,
        entities=entities,
    )
    if not isinstance(page_dict, dict):
        raise AddPageError(
            f"deterministic builder returned no schema for "
            f"archetype={archetype!r} entity={entity_name!r}"
        )

    # Assign id + title (mirrors the pipeline's post-processing).
    slug = _slug_from_route(route)              # id: flat, hyphen-joined
    rel_path = _path_from_route(route)          # file: nested, mirrors URL
    page_dict["id"] = slug
    if title:
        page_dict.setdefault("title", title)

    # Apply archetype-specific feature hints (e.g. kanban groupBy).
    if features:
        _apply_features(page_dict, archetype, features)

    schema_path = f"src/schemas/{rel_path}.json"
    schema_content = json.dumps(page_dict, indent=2) + "\n"

    # 2. Update nav-flow.json (append page entry + a default transition
    #    from the app's initial page).
    nav_flow_path = "src/contracts/nav-flow.json"
    nav_flow_content = _update_nav_flow(
        out=out,
        page_id=slug,
        route=route,
        title=title or _humanize_slug(slug),
    )

    ops = [
        BundleOp(path=schema_path, content=schema_content, kind="page-schema"),
        BundleOp(path=nav_flow_path, content=nav_flow_content, kind="nav-flow"),
    ]
    return ops


# --------------------------------------------------------------------------- #
# Internals — pipeline builder invocation
# --------------------------------------------------------------------------- #

def _build_page_via_pipeline(
    output_dir: str,
    archetype: str,
    entity: str,
    columns: dict,
    route: str,
    fields: Optional[list[dict]],
    entities: dict,
) -> Optional[dict]:
    """Thin wrapper around the pipeline's build_crud_page. Kept as a
    single call-site so the seam can evolve independently of the
    builder signature."""
    from services.deterministic_pages import build_crud_page

    design_spec: dict = {}
    try:
        from services.schema_prompt import _load_design_spec
        design_spec = _load_design_spec(output_dir) or {}
    except Exception:  # noqa: BLE001 — best-effort; empty spec is fine
        pass

    # Load the full registry so build_crud_page's FK-role authority sees
    # relationships (a domain FK stays as an editable Select; actor/
    # tenancy FKs are hidden — same behaviour as fresh generation).
    full_registry: dict = {}
    try:
        reg_path = Path(output_dir) / "contracts" / "resource-registry.json"
        if reg_path.is_file():
            full_registry = json.loads(reg_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        pass

    return build_crud_page(
        archetype, entity, columns, route, design_spec,
        entities=entities,
        field_specs=fields,
        registry=full_registry,
        output_dir=output_dir,
    )


# --------------------------------------------------------------------------- #
# Internals — nav-flow updater
# --------------------------------------------------------------------------- #

_NAV_FLOW_REL = "src/contracts/nav-flow.json"


def _update_nav_flow(*, out: Path, page_id: str, route: str, title: str) -> str:
    """Read the current nav-flow.json, append the new page entry (if not
    already present), and return the serialized JSON. Preserves shape;
    if the file is missing or unreadable, synthesize a minimal one."""
    nav_path = out / _NAV_FLOW_REL
    if nav_path.is_file():
        try:
            data = json.loads(nav_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = _empty_nav_flow()
        except (OSError, ValueError):
            data = _empty_nav_flow()
    else:
        data = _empty_nav_flow()

    pages = data.setdefault("pages", [])
    if isinstance(pages, list):
        already = any(
            isinstance(p, dict) and p.get("id") == page_id
            for p in pages
        )
        if not already:
            pages.append({
                "id":         page_id,
                "route":      route,
                "title":      title,
                "schemaFile": f"src/schemas/{page_id}.json",
                "shell":      True,
            })

    # Ensure the ancillary sections the guards expect.
    data.setdefault("version", "1.0")
    data.setdefault("auth_routes", [])
    data.setdefault("transitions", [])
    data.setdefault("guards", {})

    return json.dumps(data, indent=2) + "\n"


def _empty_nav_flow() -> dict[str, Any]:
    return {
        "version": "1.0",
        "pages": [],
        "auth_routes": [],
        "transitions": [],
        "guards": {},
    }


# --------------------------------------------------------------------------- #
# Internals — registry / entity lookup
# --------------------------------------------------------------------------- #

def _load_entities(out: Path) -> dict[str, dict]:
    """Return ``{lower_name: {_name, fields}}`` for every entity in the
    registry. Case-insensitive lookup — Smith's LLM sometimes emits
    ``"application"`` when the registry stores ``"Application"``. The
    canonical name is preserved under ``_name`` for downstream use."""
    reg_path = out / "contracts" / "resource-registry.json"
    if not reg_path.is_file():
        return {}
    try:
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(reg, dict):
        return {}
    # resource-registry.json stores entities in either shape:
    #   * dict: {"User": {...}, "Candidate": {...}}   ← current bpxr6hsv
    #   * list: [{"name": "User", ...}, ...]          ← older projects
    # Normalize to an iterable of (name, meta) pairs and handle both.
    raw = reg.get("entities") or {}
    if isinstance(raw, dict):
        pairs = list(raw.items())
    elif isinstance(raw, list):
        pairs = [
            (e.get("name") or e.get("slug"), e) for e in raw
            if isinstance(e, dict)
        ]
    else:
        return {}

    out_map: dict[str, dict] = {}
    for name, e in pairs:
        if not isinstance(name, str) or not name or not isinstance(e, dict):
            continue
        # Normalize `fields` — registry uses a list of {name, ...}; the
        # deterministic builders expect a dict name → meta.
        fields = e.get("fields") or e.get("columns") or []
        if isinstance(fields, list):
            fields_map: dict[str, dict] = {}
            for f in fields:
                if isinstance(f, dict) and isinstance(f.get("name"), str):
                    fields_map[f["name"]] = f
            fields = fields_map
        out_map[name.lower()] = {"_name": name, "fields": fields}
    return out_map


def _find_entity(entities: dict[str, dict], name: str) -> Optional[dict]:
    if not isinstance(name, str):
        return None
    return entities.get(name.strip().lower())


# --------------------------------------------------------------------------- #
# Internals — feature parsing
# --------------------------------------------------------------------------- #

def _apply_features(page_dict: dict, archetype: str, features: list[str]) -> None:
    """Thread archetype-specific hints through the emitted page dict.

    For slice T2 we handle:
      * kanban: ``groupBy:<column>`` sets the Kanban node's props.groupBy
    Other archetypes: no-op (features are informational).
    """
    for feat in features:
        if not isinstance(feat, str) or ":" not in feat:
            continue
        k, v = feat.split(":", 1)
        k, v = k.strip(), v.strip()
        if archetype == "kanban" and k == "groupBy" and v:
            _set_kanban_group_by(page_dict, v)


def _set_kanban_group_by(page_dict: dict, group_by: str) -> None:
    """Walk the page tree and set the first Kanban node's groupBy prop."""
    def walk(node: Any) -> bool:
        if isinstance(node, dict):
            if node.get("type") == "Kanban":
                props = node.setdefault("props", {})
                props["groupBy"] = group_by
                return True
            for k in ("children", "content", "items", "columns"):
                children = node.get(k)
                if isinstance(children, list):
                    for c in children:
                        if walk(c):
                            return True
        return False
    walk(page_dict.get("root"))


# --------------------------------------------------------------------------- #
# Internals — slug / humanize helpers
# --------------------------------------------------------------------------- #

_SLUG_STRIP = re.compile(r"[^a-z0-9-]+")


def _slug_from_route(route: str) -> str:
    """Flat hyphen-joined slug for the page's INTERNAL id (``recruiters-new``).
    Static segments only; dynamic ``[id]`` / ``:id`` segments are dropped."""
    parts = [p for p in route.strip("/").split("/") if p and not p.startswith(("[", ":"))]
    slug = "-".join(parts) if parts else "home"
    slug = _SLUG_STRIP.sub("-", slug.lower()).strip("-")
    return slug or "home"


def _path_from_route(route: str) -> str:
    """Filesystem-relative path (WITHOUT the ``.json`` suffix) mirroring the
    URL structure, e.g. ``/recruiters/new`` → ``recruiters/new``,
    ``/candidates/[id]/edit`` → ``candidates/[id]/edit``. This is the
    convention ``_regenerate_route_registry`` uses when it scans schemas
    and derives routes via ``route_from_slug`` — flat hyphen-joined paths
    would produce a bad route (``/recruiters-new`` instead of
    ``/recruiters/new``) and be invisible to Next's compiled dispatch."""
    parts = [p for p in route.strip("/").split("/") if p]
    if not parts:
        return "home"
    return "/".join(parts)


def _humanize_slug(slug: str) -> str:
    words = slug.replace("-", " ").replace("_", " ").split()
    return " ".join(w.capitalize() for w in words) or "Home"
