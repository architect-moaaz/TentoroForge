"""``add_field`` composite seam — extend an EXISTING entity's data model.

The missing sibling of :mod:`services.add_entity_seam`. Adding a column to an
existing entity used to have no incremental path: ``add_entity`` refuses a name
that already exists, and ``edit_page`` only touches a page schema, never the
data model. So a plain ask like *"add a discount field to offers"* fell through
to a whole-app definition update + rebuild — the DEFECT-FIELD-ADD-NOT-INCREMENTAL
failure in the QA sheet (F-01). Adding one nullable column is a non-destructive
``drizzle-kit push`` (the column is created, existing rows keep their data); it
must never cost a reset + reseed + full rebuild.

This seam writes exactly the two files a new column touches, surgically:

    * ``contracts/resource-registry.json`` — the field appended to the entity's
      ``fields`` list (the naming authority every guard/validator reads).
    * ``src/db/schema/<slug>.ts``           — one Drizzle column line inserted
      into the existing ``pgTable`` body, and its builder added to the import.

It does NOT re-render the whole Drizzle module (that would risk byte-changing
columns that already work — the same reason ``add_entity`` only writes what is
new). It does NOT surface the field on any page; that is a follow-up
``edit_page`` (surfacing a column on a screen is a page-schema change, not a
data-model one). Keeping the two concerns separate is what lets the data-model
half land as a migration instead of a rebuild.

Files this seam writes (atomically via :mod:`services.atomic_apply`):
    * ``contracts/resource-registry.json`` — field appended to the entity
    * ``src/db/schema/<slug>.ts``          — column inserted + import widened
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from services.atomic_apply import BundleOp

logger = logging.getLogger(__name__)


class AddFieldError(ValueError):
    """Raised when the seam can't build a bundle."""


# A nullable column is the only non-destructive add: an existing row has no
# value for a brand-new NOT NULL column, so ``drizzle-kit push`` would fail (or
# demand a default + backfill). The incremental promise only holds for a
# nullable column, so the seam forces the column nullable regardless of what the
# caller passed — a NOT NULL constraint on a new field is a rebuild concern.
_FORCE_NULLABLE = True


def build_add_field_bundle(
    output_dir: str,
    *,
    entity: str,
    field: dict,
) -> list[BundleOp]:
    """Compose the atomic-apply bundle that adds one column to ``entity``.

    Args:
        output_dir: The generated app's root.
        entity: The EXISTING entity's name (case-insensitive match against the
            registry).
        field: ``{name, type, length?, precision?, scale?, default?}`` — the
            same field shape ``schema_builder`` / ``add_entity`` consume. Any
            ``notNull`` is ignored: the new column is always nullable so the
            push is non-destructive (see ``_FORCE_NULLABLE``).

    Raises:
        AddFieldError: entity not found, field name missing/invalid, the field
            already exists, the Drizzle module is absent, or the registry /
            module can't be parsed.
    """
    out = Path(output_dir)
    if not out.is_dir():
        raise AddFieldError(f"output_dir missing: {output_dir}")
    if not isinstance(entity, str) or not entity.strip():
        raise AddFieldError("entity must be a non-empty name")
    if not isinstance(field, dict):
        raise AddFieldError("field must be a dict")
    field_name = str(field.get("name") or "").strip()
    if not field_name or not field_name[0].isalpha():
        raise AddFieldError(f"field name must be an identifier, got {field.get('name')!r}")

    reg_path = out / "contracts" / "resource-registry.json"
    if not reg_path.is_file():
        raise AddFieldError("registry not found: contracts/resource-registry.json")
    try:
        registry = json.loads(reg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise AddFieldError(f"registry unreadable: {e}") from e
    if not isinstance(registry, dict):
        raise AddFieldError("registry is not a JSON object")

    entities = registry.get("entities")
    if not isinstance(entities, list):
        raise AddFieldError("registry.entities must be a list")

    # Locate the entity — case-insensitive, same as add_entity's collision check.
    target = None
    for e in entities:
        if isinstance(e, dict) and str(e.get("name") or "").lower() == entity.strip().lower():
            target = e
            break
    if target is None:
        known = ", ".join(str(e.get("name")) for e in entities if isinstance(e, dict)) or "(none)"
        raise AddFieldError(
            f"entity {entity!r} not found in the registry — known entities: {known}. "
            "Use add_entity to create a new entity."
        )

    fields = target.setdefault("fields", [])
    if not isinstance(fields, list):
        raise AddFieldError(f"registry entity {entity!r} has a non-list `fields`")

    # Idempotence guard — a field of this name already on the entity is a no-op
    # the caller should know about, not a silent duplicate column.
    if any(isinstance(f, dict) and str(f.get("name") or "").lower() == field_name.lower()
           for f in fields):
        raise AddFieldError(
            f"field {field_name!r} already exists on {target.get('name')!r}"
        )

    slug = str(target.get("slug") or "").strip() or _to_kebab(str(target.get("name") or entity))
    drizzle_path = out / "src" / "db" / "schema" / f"{slug}.ts"
    if not drizzle_path.is_file():
        raise AddFieldError(
            f"drizzle module not found: src/db/schema/{slug}.ts — this app predates "
            "the per-entity schema module; a data-model change here needs a rebuild."
        )
    drizzle_src = drizzle_path.read_text(encoding="utf-8")

    # The field the registry records: name + type + shape keys, never notNull
    # (the column is nullable by construction so the push is non-destructive).
    reg_field: dict = {"name": field_name, "type": field.get("type") or "varchar"}
    for k in ("length", "precision", "scale", "default"):
        if field.get(k) is not None:
            reg_field[k] = field[k]
    fields.append(reg_field)

    new_drizzle = _insert_column(drizzle_src, field, drizzle_path.name)

    return [
        BundleOp(
            path="contracts/resource-registry.json",
            content=json.dumps(registry, indent=2) + "\n",
            kind="registry",
        ),
        BundleOp(
            path=f"src/db/schema/{slug}.ts",
            content=new_drizzle,
            kind="drizzle",
        ),
    ]


# --------------------------------------------------------------------------- #
# Drizzle surgery
# --------------------------------------------------------------------------- #

def _insert_column(src: str, field: dict, filename: str) -> str:
    """Insert one column line into an existing pgTable body and widen the
    ``drizzle-orm/pg-core`` import to cover its builder.

    Surgical on purpose: only the import line and the pgTable body are touched,
    so every existing column stays byte-for-byte identical.
    """
    from services.schema_builder import _builder_for, _render_default

    f = dict(field)
    f["notNull"] = False  # never emit .notNull() — the column must be nullable
    builder, args = _builder_for(f)
    var_name = _camel_var(str(field.get("name") or ""))

    line = f"  {var_name}: {builder}({args})"
    default_call = _render_default(field.get("default"))
    if default_call:
        line += default_call
    line += ","

    # 1. Widen the import so the builder resolves. The module opens with
    #    `import { pgTable, <b1>, <b2>, ... } from "drizzle-orm/pg-core";`.
    import_re = re.compile(
        r'import\s*\{([^}]*)\}\s*from\s*"drizzle-orm/pg-core";'
    )
    m = import_re.search(src)
    if not m:
        raise AddFieldError(
            f"{filename}: no `drizzle-orm/pg-core` import to widen"
        )
    tokens = [t.strip() for t in m.group(1).split(",") if t.strip()]
    if builder not in tokens:
        # pgTable stays first; the rest sorted, matching add_entity's emission.
        rest = sorted({t for t in tokens if t != "pgTable"} | {builder})
        new_tokens = (["pgTable"] if "pgTable" in tokens else []) + rest
        new_import = 'import { ' + ", ".join(new_tokens) + ' } from "drizzle-orm/pg-core";'
        src = src[:m.start()] + new_import + src[m.end():]

    # 2. Insert the column before the pgTable body's closing `});`. The table is
    #    the single pgTable in the module, so its close is the last `});`.
    close_idx = src.rfind("});")
    if close_idx == -1:
        raise AddFieldError(f"{filename}: no pgTable close `}});` found")
    # Walk back over whitespace to sit right after the previous line's newline.
    insert_at = close_idx
    while insert_at > 0 and src[insert_at - 1] in " \t":
        insert_at -= 1
    return src[:insert_at] + line + "\n" + src[insert_at:]


# --------------------------------------------------------------------------- #
# Helpers (mirrors of add_entity_seam's, kept local so the seams stay decoupled)
# --------------------------------------------------------------------------- #

def _camel_var(name: str) -> str:
    parts = re.split(r"[_\-\s]+", name)
    if not parts:
        return name
    first = parts[0][:1].lower() + parts[0][1:]
    rest = "".join(p[:1].upper() + p[1:] for p in parts[1:])
    return first + rest


def _to_kebab(name: str) -> str:
    s = re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()
    return re.sub(r"[^a-z0-9-]+", "-", s).strip("-")
