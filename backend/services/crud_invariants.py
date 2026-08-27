"""CRUD-invariant guard for list pages — "Create New X" button is not optional.

Root-cause fix, not a bandaid: for every LIST page bound to an entity,
the header MUST contain an action button navigating to that entity's
`/entity/new` route. Today's platform guarantees this only inside
:func:`services.deterministic_pages.build_list_page`; LLM-authored list
pages can drop the button entirely, and `button_audit` only heals
*existing* buttons — it can't invent one.

This module closes that hole with a single deterministic pass:

  1. Discover every schema page in ``src/schemas/``.
  2. Identify list pages by structure (Table/Repeat/List over an
     ``op:"list"`` dataSource) — no reliance on `kind=list` metadata,
     which the LLM sometimes omits.
  3. For each list page, resolve the primary entity + slug (from the
     dataSource + registered slugs).
  4. Assert a header/toolbar contains a Button whose ``navigate`` OR
     ``href`` points at ``/<slug>/new``. If missing, INSERT one at the
     top of the page's first header/toolbar row (or synthesize a header
     row when none exists).

Generalizes: applies to any entity in the registry. No per-domain
hardcodes. Idempotent — a re-run on a fixed page is a no-op.

Runs late in :mod:`services.post_generate_fixes` (after
``list_data_source_guard`` has settled the slug set, before the final
button audit).
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional


logger = logging.getLogger(__name__)


# Same regex the list-data-source guard uses — the const name IS the
# data-engine's registered slug.
_EXPORT_TABLE_RE = re.compile(r"export\s+const\s+([A-Za-z_$][\w$]*)\s*=\s*pgTable\(")


# ------------------------------------------------------------------ #
# Types                                                              #
# ------------------------------------------------------------------ #

@dataclass
class InsertRecord:
    """One "New X" button we inserted, for the pipeline log."""
    file: str
    entity: str
    slug: str
    label: str


@dataclass
class CrudInvariantResult:
    inserted: list[InsertRecord] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)

    @property
    def files_changed(self) -> int:
        return len({r.file for r in self.inserted})


# ------------------------------------------------------------------ #
# Discovery                                                          #
# ------------------------------------------------------------------ #

def _iter_schemas(output_dir: str) -> Iterable[tuple[str, dict]]:
    root = os.path.join(output_dir, "src", "schemas")
    if not os.path.isdir(root):
        return
    for f in sorted(glob.glob(os.path.join(root, "**", "*.json"), recursive=True)):
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            yield f, data


def _registered_slugs(output_dir: str) -> set[str]:
    sdir = os.path.join(output_dir, "src", "db", "schema")
    slugs: set[str] = set()
    if not os.path.isdir(sdir):
        return slugs
    for fp in sorted(glob.glob(os.path.join(sdir, "*.ts"))):
        try:
            with open(fp, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        slugs.update(_EXPORT_TABLE_RE.findall(text))
    return slugs


# ------------------------------------------------------------------ #
# Structural list-page detection                                     #
# ------------------------------------------------------------------ #

# Node types that show a collection of rows/records. Structural — the
# LLM can label a page anything, but if it renders a list-shaped
# component it needs the invariant.
_LIST_NODES = {"Table", "Repeat", "List", "Kanban", "Calendar", "CardGrid"}


def _walk(node: Any) -> Iterable[Any]:
    """Depth-first walk of every dict node in the schema tree."""
    if isinstance(node, dict):
        yield node
        for child in node.get("children") or []:
            yield from _walk(child)
        # Some schema nodes stash children under alternate keys — the
        # only nested-schema keys we've ever seen are `columns` (Table),
        # `sections` (Form), `items` (List). We walk the ones that can
        # legitimately contain other components.
        for key in ("sections",):
            for child in node.get(key) or []:
                yield from _walk(child)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _find_primary_entity(schema: dict) -> Optional[tuple[str, str]]:
    """Return ``(entity_name, ds_name)`` for the page's primary list
    dataSource, or ``None`` when the page isn't clearly list-shaped.

    A "primary list dataSource" is the one used by the first list-shaped
    node in the tree. Fallback: the first ``op="list"`` dataSource
    declared on the page."""
    sources = schema.get("dataSources") or []
    if not isinstance(sources, list):
        return None
    list_sources: dict[str, dict] = {}
    for ds in sources:
        if not isinstance(ds, dict):
            continue
        name = str(ds.get("name") or "").strip()
        op = str(ds.get("op") or "").strip()
        if name and op in ("list", "table", "grid", "index", ""):
            list_sources[name] = ds

    if not list_sources:
        return None

    # Walk for the first list-shaped component and inspect its
    # binding — that's the "primary" source of the page.
    for node in _walk(schema.get("children")):
        if not isinstance(node, dict):
            continue
        if node.get("type") not in _LIST_NODES:
            continue
        props = node.get("props") or {}
        for key in ("rows", "items", "bind", "source"):
            val = props.get(key)
            if not isinstance(val, str):
                continue
            m = re.match(r"^\{\{\s*([A-Za-z_][\w]*)\s*\}\}$", val)
            if not m:
                continue
            ref = m.group(1)
            src = list_sources.get(ref)
            if src and src.get("entity"):
                return str(src["entity"]).strip(), ref

    # No list-shaped component in the tree — nothing to guard. A page
    # with an ``op=list`` dataSource but no Table/Repeat/... isn't a
    # user-facing list; skip.
    return None


# ------------------------------------------------------------------ #
# Slug resolution                                                    #
# ------------------------------------------------------------------ #

def _canon(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _slug_for_entity(
    entity: str,
    registered: set[str],
    schema_route: str,
) -> Optional[str]:
    """Pick the registered slug for this entity. Preference:

      1. exact match against the entity name
      2. canonical match (case + separator insensitive)
      3. the page's own route's first segment IF it matches a
         registered slug (a page at ``/bookings`` whose entity is
         ``ClassBooking`` reasonably uses the /bookings/new route)
    """
    if entity in registered:
        return entity
    canon_entity = _canon(entity)
    for slug in registered:
        if _canon(slug) == canon_entity:
            return slug

    route_seg = ""
    if isinstance(schema_route, str):
        parts = [p for p in schema_route.strip("/").split("/") if p]
        if parts:
            route_seg = parts[0]
    if route_seg:
        for slug in registered:
            if _canon(slug) == _canon(route_seg):
                return slug
    return None


# ------------------------------------------------------------------ #
# Invariant check + insertion                                        #
# ------------------------------------------------------------------ #

def _humanize(name: str) -> str:
    """'ClassBooking' → 'Class Booking'; 'user_role' → 'User role'."""
    s = re.sub(r"[_-]+", " ", name).strip()
    s = re.sub(r"(?<!^)(?=[A-Z])", " ", s).strip()
    if not s:
        return name
    return s[0].upper() + s[1:]


def _button_targets(node: dict) -> list[str]:
    """Every navigate/href/route this button (or its onClick) resolves
    to. Returns a list of URL strings; the caller matches structurally."""
    out: list[str] = []
    props = node.get("props") or {}
    for key in ("navigate", "href", "route", "to"):
        val = props.get(key)
        if isinstance(val, str) and val.strip():
            out.append(val.strip())
    on_click = props.get("onClick")
    if isinstance(on_click, dict):
        for key in ("navigate", "href", "route", "to"):
            val = on_click.get(key)
            if isinstance(val, str) and val.strip():
                out.append(val.strip())
    return out


def _has_create_button(schema: dict, slug: str) -> bool:
    """True when the page already has SOME button whose navigate
    resolves to ``/slug/new`` (with or without a trailing slash)."""
    target = f"/{slug}/new"
    target_alt = f"/{slug}/new/"
    for node in _walk(schema.get("children")):
        if not isinstance(node, dict):
            continue
        if node.get("type") != "Button":
            continue
        for url in _button_targets(node):
            if url in (target, target_alt):
                return True
    return False


def _find_header_row(children: list) -> Optional[dict]:
    """Find a Row/Toolbar node at the top of the page tree suitable for
    placing header actions in. Uses the same heuristic
    ``deterministic_pages.build_list_page`` uses: a top-level Row where
    the first child is a Heading. Returns None if none found."""
    if not isinstance(children, list):
        return None
    for node in children:
        if not isinstance(node, dict):
            continue
        if node.get("type") not in ("Row", "Toolbar", "Stack"):
            continue
        inner = node.get("children") or []
        if not isinstance(inner, list) or not inner:
            continue
        head = inner[0]
        if isinstance(head, dict) and head.get("type") == "Heading":
            return node
    return None


def _make_button(label: str, url: str) -> dict:
    """Emit the same button shape ``build_list_page`` uses so the fix
    reads like the original emitter's output — clicking through a
    diff won't look "patched"."""
    return {
        "type": "Button",
        "props": {
            "label": label,
            "variant": "primary",
            "navigate": url,
        },
    }


def _insert_button(schema: dict, entity: str, slug: str) -> tuple[str, dict]:
    """Insert a "New <entity>" button into the page's header row.
    Returns ``(label, button_node)`` so the caller can log what
    landed."""
    label = f"New {_humanize(entity)}"
    button = _make_button(label, f"/{slug}/new")

    children = schema.setdefault("children", [])
    if not isinstance(children, list):
        # A malformed schema — refuse to touch it.
        raise ValueError(
            f"schema children is not a list ({type(children).__name__})"
        )

    header_row = _find_header_row(children)
    if header_row is not None:
        row_children = header_row.setdefault("children", [])
        # The Deterministic emitter puts headings first and actions
        # second under a nested Row. Match that so the layout is
        # consistent.
        # Look for an existing action Row (Row whose children are all
        # Buttons) inside the header_row.
        for c in row_children:
            if (
                isinstance(c, dict)
                and c.get("type") == "Row"
                and all(
                    isinstance(x, dict) and x.get("type") == "Button"
                    for x in (c.get("children") or [])
                )
            ):
                c.setdefault("children", []).append(button)
                return label, button
        # No action row — append one alongside the heading.
        row_children.append({
            "type": "Row",
            "props": {"gap": "tokens.spacing.2"},
            "children": [button],
        })
        return label, button

    # No header row at all — synthesize one at the top.
    heading_text = str(schema.get("title") or _humanize(entity) + "s")
    new_row = {
        "type": "Row",
        "props": {"justify": "between", "align": "center"},
        "children": [
            {"type": "Heading", "props": {"content": heading_text, "level": 1}},
            {"type": "Row", "props": {"gap": "tokens.spacing.2"},
             "children": [button]},
        ],
    }
    children.insert(0, new_row)
    return label, button


# ------------------------------------------------------------------ #
# Public entry                                                       #
# ------------------------------------------------------------------ #

def ensure_list_pages_have_create_action(
    output_dir: str,
) -> CrudInvariantResult:
    """Sweep every schema page and enforce the invariant. Idempotent.

    Never raises: a per-page failure is captured in ``result.skipped``
    with a reason, so the pipeline keeps moving.
    """
    result = CrudInvariantResult()
    registered = _registered_slugs(output_dir)
    if not registered:
        # No entities registered → data engine hasn't emitted schemas
        # yet. Skip cleanly.
        return result

    for path, schema in _iter_schemas(output_dir):
        # Skip route templates for the create/edit forms themselves —
        # they don't want a "New X" button.
        route = str(schema.get("route") or "")
        if any(seg in route for seg in ("/new", "/edit", "[", ":")):
            continue
        try:
            primary = _find_primary_entity(schema)
        except Exception as exc:  # noqa: BLE001
            result.skipped.append({
                "file": path, "reason": f"walk failed: {exc.__class__.__name__}",
            })
            continue
        if not primary:
            continue
        entity, _ds_name = primary
        slug = _slug_for_entity(entity, registered, route)
        if not slug:
            result.skipped.append({
                "file": path, "entity": entity,
                "reason": "no registered slug matches entity",
            })
            continue

        if _has_create_button(schema, slug):
            result.already_present.append(path)
            continue

        try:
            label, _btn = _insert_button(schema, entity, slug)
        except (ValueError, TypeError) as exc:
            result.skipped.append({
                "file": path, "entity": entity,
                "reason": f"insert failed: {exc}",
            })
            continue

        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(schema, fh, indent=2)
                fh.write("\n")
        except OSError as exc:
            result.skipped.append({
                "file": path, "entity": entity,
                "reason": f"write failed: {exc.__class__.__name__}",
            })
            continue

        result.inserted.append(InsertRecord(
            file=path, entity=entity, slug=slug, label=label,
        ))

    if result.inserted:
        logger.info(
            "crud_invariants: inserted %d 'New X' button(s) across %d file(s) in %s",
            len(result.inserted), result.files_changed, output_dir,
        )
    if result.skipped:
        logger.warning(
            "crud_invariants: skipped %d page(s) in %s (first: %r)",
            len(result.skipped), output_dir, result.skipped[0],
        )
    return result
