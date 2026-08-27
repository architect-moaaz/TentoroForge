"""S5-T5 — `add_entity` composite seam.

Third of Smith's "new-thing" seams. Adds an entity to the app end-to-end:

    * Insert entity into ``contracts/resource-registry.json`` — the
      canonical naming authority every guard/validator reads.
    * Emit a Drizzle schema file at ``src/db/schema/<slug>.ts`` using the
      column-type dispatch from :mod:`services.schema_builder`
      (``_builder_for``, ``_to_snake``, ``_render_default``) — same
      output shape the pipeline produces for a fresh app.
    * Append the export to the schema barrel
      ``src/db/schema/index.ts`` so downstream code sees the new entity.

Deliberately surgical: does NOT re-run ``build_schema_files`` over every
entity (that would risk byte-changing existing schema files that already
work). Only writes what's new.

Files this seam writes (atomically via services.atomic_apply):
    * ``contracts/resource-registry.json`` — entity appended
    * ``src/db/schema/<slug>.ts``          — new Drizzle schema
    * ``src/db/schema/index.ts``           — new export line

Follow-up (not in T5): a default create/edit page + a default
``Create<Entity>`` workflow via ``add_page`` + ``add_workflow`` composed
into one bundle. Kept out for now to keep the T5 blast radius small.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from services.atomic_apply import BundleOp
from services.entity_names import derive_names

logger = logging.getLogger(__name__)


class AddEntityError(ValueError):
    """Raised when the seam can't build a bundle."""


# --------------------------------------------------------------------------- #
# Public builder
# --------------------------------------------------------------------------- #

def build_add_entity_bundle(
    output_dir: str,
    *,
    name: str,
    fields: list[dict],
    table: Optional[str] = None,
) -> list[BundleOp]:
    """Compose the atomic-apply bundle for a new entity.

    Args:
        output_dir: The generated app's root.
        name: Entity name in canonical casing (e.g. ``Assessor``).
        fields: List of ``{name, type, notNull?, length?, precision?,
                scale?, default?}`` dicts — same shape ``schema_builder``
                consumes for existing entities.
        table: Optional explicit SQL table name; defaults to
               ``pluralized snake_case`` derived from ``name``.

    Raises:
        AddEntityError: On name collision, empty fields, invalid name,
            or missing output_dir.
    """
    out = Path(output_dir)
    if not out.is_dir():
        raise AddEntityError(f"output_dir missing: {output_dir}")
    if not isinstance(name, str) or not name.strip() or not name[0].isalpha():
        raise AddEntityError(
            f"entity name must be a non-empty identifier, got {name!r}"
        )
    if not isinstance(fields, list) or not fields:
        raise AddEntityError("fields must be a non-empty list")

    entity_name = name.strip()
    slug = _to_kebab(entity_name)
    table_name = table or _pluralize_snake(entity_name)

    reg_path = out / "contracts" / "resource-registry.json"
    if not reg_path.is_file():
        raise AddEntityError("registry not found: contracts/resource-registry.json")
    try:
        registry = json.loads(reg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise AddEntityError(f"registry unreadable: {e}") from e
    if not isinstance(registry, dict):
        raise AddEntityError("registry is not a JSON object")

    entities = registry.setdefault("entities", [])
    if not isinstance(entities, list):
        raise AddEntityError("registry.entities must be a list")

    # Collision check — case-insensitive.
    if any(
        isinstance(e, dict) and str(e.get("name") or "").lower() == entity_name.lower()
        for e in entities
    ):
        raise AddEntityError(f"entity {entity_name!r} already exists in the registry")

    # 1. Add to registry — the shape mirrors what registry_extractor emits.
    new_entity = {
        "name": entity_name,
        "table": table_name,
        "slug": slug,
        "fields": _normalize_fields_for_registry(fields),
    }
    entities.append(new_entity)

    # 2. Emit the Drizzle schema for this one entity.
    drizzle_content = _render_drizzle_module(entity_name, table_name, fields)

    # 3. Compose the barrel export line — READ current barrel, append if
    #    not already present. If the barrel doesn't exist we create it.
    barrel_path = out / "src" / "db" / "schema" / "index.ts"
    if barrel_path.is_file():
        barrel_content = barrel_path.read_text(encoding="utf-8")
    else:
        barrel_content = ""
    export_line = f'export {{ {_camel_var(entity_name)} }} from "./{slug}";\n'
    if export_line.strip() not in barrel_content:
        # Append with a leading newline if the file didn't already end with one.
        if barrel_content and not barrel_content.endswith("\n"):
            barrel_content += "\n"
        barrel_content += export_line

    return [
        BundleOp(
            path="contracts/resource-registry.json",
            content=json.dumps(registry, indent=2) + "\n",
            kind="registry",
        ),
        BundleOp(
            path=f"src/db/schema/{slug}.ts",
            content=drizzle_content,
            kind="drizzle",
        ),
        BundleOp(
            path="src/db/schema/index.ts",
            content=barrel_content,
            kind="barrel",
        ),
    ]


# --------------------------------------------------------------------------- #
# Drizzle renderer
# --------------------------------------------------------------------------- #

def _render_drizzle_module(entity_name: str, table_name: str, fields: list[dict]) -> str:
    """Render a Drizzle pgTable module for one entity.

    Uses the same _builder_for / _to_snake / _render_default helpers
    schema_builder uses for the pipeline's own emission — so the file
    shape matches byte-for-byte what fresh generation produces.
    """
    from services.schema_builder import _builder_for, _to_snake, _render_default

    # Ensure identity columns present. schema_builder adds these to the
    # registry entity, but a Smith-authored `add_entity` may omit them —
    # inject if missing to keep the row shape sane.
    field_map = {(f.get("name") or ""): f for f in fields if isinstance(f, dict)}
    seen_names = {n.lower() for n in field_map}
    ordered: list[dict] = list(fields)
    if "id" not in seen_names:
        ordered.insert(0, {"name": "id", "type": "uuid", "notNull": True, "default": "uuidv4"})
    if "createdat" not in seen_names and "created_at" not in seen_names:
        ordered.append({"name": "createdAt", "type": "timestamp", "default": "now"})
    if "updatedat" not in seen_names and "updated_at" not in seen_names:
        ordered.append({"name": "updatedAt", "type": "timestamp", "default": "now"})

    # Collect the set of Drizzle builder names so we import exactly what we use.
    used_builders: set[str] = set()
    body_lines: list[str] = []
    for f in ordered:
        col_name = f.get("name") or ""
        var_name = _camel_var(col_name)
        builder, args = _builder_for(f)
        used_builders.add(builder)
        line = f"  {var_name}: {builder}({args})"
        # Primary-key id short-circuits — .primaryKey() implies .notNull(),
        # and .defaultRandom() gives us the uuid default. Nothing else to add.
        if col_name.lower() == "id" and builder == "uuid":
            line += ".primaryKey().defaultRandom()"
        else:
            if f.get("notNull") is True:
                line += ".notNull()"
            default_call = _render_default(f.get("default"))
            if default_call:
                line += default_call
        body_lines.append(line + ",")

    imports = ", ".join(sorted(used_builders))
    body = "\n".join(body_lines)
    return (
        f'import {{ pgTable, {imports} }} from "drizzle-orm/pg-core";\n'
        f"\n"
        f'export const {_camel_var(entity_name)} = pgTable("{table_name}", {{\n'
        f"{body}\n"
        f"}});\n"
    )


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _normalize_fields_for_registry(fields: list[dict]) -> list[dict]:
    """Return each field's registry-shape dict — name+type at minimum,
    dropping any extra Smith-authored keys."""
    out: list[dict] = []
    for f in fields:
        if not isinstance(f, dict):
            continue
        row: dict = {"name": f.get("name"), "type": f.get("type") or "varchar"}
        for k in ("notNull", "length", "precision", "scale", "default"):
            if f.get(k) is not None:
                row[k] = f[k]
        out.append(row)
    return out


def _camel_var(name: str) -> str:
    """Convert `Assessor` / `assessor_name` / `assessor-name` → camelCase."""
    parts = re.split(r"[_\-\s]+", name)
    if not parts:
        return name
    first = parts[0][:1].lower() + parts[0][1:]
    rest = "".join(p[:1].upper() + p[1:] for p in parts[1:])
    return first + rest


def _to_kebab(name: str) -> str:
    """`Assessor` → `assessor`, `InterviewFeedback` → `interview-feedback`."""
    s = re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()
    return re.sub(r"[^a-z0-9-]+", "-", s).strip("-")


def _pluralize_snake(name: str) -> str:
    """The snake_case table name for an entity added through this seam.

    Delegates to :func:`services.entity_names.derive_names` — the single
    naming authority — which is also what fresh generation now uses via
    ``crud_workflow_generator._derive_table``. The docstring here used to
    say it was *deliberately* mirroring the pipeline's naive convention;
    that convention was register finding CRUD-1, and both sides moved to
    the authority together. Keeping a private copy in step by hand is the
    coupling that produced the bug — there is nothing left to keep in
    step now."""
    return derive_names(name).tableSnake
