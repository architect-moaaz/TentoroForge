"""Remove or edit a column on an existing entity — the destructive / renaming
siblings of :mod:`services.add_field_seam`.

Surgical, exactly like the add: touches only the two files a column lives in —
``contracts/resource-registry.json`` and ``src/db/schema/<slug>.ts`` — leaving
every other column byte-for-byte identical, so the change lands as a
``drizzle-kit push`` migration rather than a rebuild.

Unlike an add, removing or renaming a column is **data-affecting and
reference-breaking**: existing rows lose the column's data, and every workflow
step, form field and binding that named it now names something that is gone. So
the callers gate these behind confirmation, and the field-dependency ripple
checks (``workflow-column-unknown``, ``form-field-unknown``) surface whatever
still references the old name for repair. This seam does the source surgery; it
does not chase the references — the invariant already does.

The primary key and the engine-managed timestamps are never removed or renamed
here: they are contract, not a domain field, and dropping one breaks the Data
Engine. The seam refuses them.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from services.atomic_apply import BundleOp
from services.add_field_seam import _camel_var, _to_kebab


class EditFieldError(ValueError):
    """Raised when the seam cannot build a bundle. Caller renders the message."""


#: Columns the engine owns; a domain edit never touches them.
_MANAGED = {"id", "createdat", "updatedat", "deletedat",
            "created_at", "updated_at", "deleted_at"}

#: `  varName: builder("col_name"[, {...}])<chain>,` — args carry no `)` of
#: their own (drizzle options are `{...}`), so the first `)` closes the builder.
_COLUMN_LINE = re.compile(
    r'^(?P<indent>\s*)(?P<var>[A-Za-z_]\w*)\s*:\s*'
    r'(?P<builder>[A-Za-z_]\w*)\((?P<args>[^)]*)\)(?P<chain>.*?),?\s*$'
)


def _snake(name: str) -> str:
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", str(name)).lower()
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def _load_target(output_dir: str, entity: str):
    """(registry, target_entity, fields, slug, drizzle_path, drizzle_src). Same
    locate logic as add_field_seam so the seams agree on what an entity is."""
    out = Path(output_dir)
    reg_path = out / "contracts" / "resource-registry.json"
    if not reg_path.is_file():
        raise EditFieldError("registry not found: contracts/resource-registry.json")
    try:
        registry = json.loads(reg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise EditFieldError(f"registry unreadable: {e}") from e
    if not isinstance(registry, dict) or not isinstance(registry.get("entities"), list):
        raise EditFieldError("registry.entities must be a list")

    target = next(
        (e for e in registry["entities"]
         if isinstance(e, dict) and str(e.get("name") or "").lower() == entity.strip().lower()),
        None)
    if target is None:
        known = ", ".join(str(e.get("name")) for e in registry["entities"]
                          if isinstance(e, dict)) or "(none)"
        raise EditFieldError(f"entity {entity!r} not found in the registry — known: {known}")

    fields = target.setdefault("fields", [])
    if not isinstance(fields, list):
        raise EditFieldError(f"registry entity {entity!r} has a non-list `fields`")

    slug = str(target.get("slug") or "").strip() or _to_kebab(str(target.get("name") or entity))
    drizzle_path = out / "src" / "db" / "schema" / f"{slug}.ts"
    if not drizzle_path.is_file():
        raise EditFieldError(
            f"drizzle module not found: src/db/schema/{slug}.ts — this app predates "
            "the per-entity schema module; a data-model change here needs a rebuild.")
    return registry, target, fields, slug, drizzle_path, drizzle_path.read_text(encoding="utf-8")


def _find_field(fields: list, field_name: str) -> dict | None:
    return next((f for f in fields
                 if isinstance(f, dict) and str(f.get("name") or "").lower() == field_name.lower()),
                None)


def _refuse_managed(field_name: str, verb: str) -> None:
    if _snake(field_name).replace("_", "") in {m.replace("_", "") for m in _MANAGED} \
            or field_name.lower() in _MANAGED:
        raise EditFieldError(
            f"{field_name!r} is an engine-managed column (primary key / timestamp) — "
            f"it cannot be {verb}. Only domain fields may be.")


def _column_var(field_name: str) -> str:
    return _camel_var(field_name)


def _remove_column_line(src: str, var: str, filename: str) -> str:
    """Drop the one column line whose variable is `var`; every other line stays
    identical."""
    kept, removed = [], False
    for line in src.splitlines(keepends=True):
        m = _COLUMN_LINE.match(line.rstrip("\n"))
        if m and m.group("var") == var:
            removed = True
            continue
        kept.append(line)
    if not removed:
        raise EditFieldError(f"{filename}: no column line for {var!r} to remove")
    return "".join(kept)


def build_remove_field_bundle(output_dir: str, *, entity: str, field_name: str) -> list[BundleOp]:
    """Compose the atomic-apply bundle that drops one column from ``entity``."""
    field_name = str(field_name or "").strip()
    if not field_name:
        raise EditFieldError("field_name is required")
    _refuse_managed(field_name, "removed")

    registry, target, fields, slug, dpath, dsrc = _load_target(output_dir, entity)
    existing = _find_field(fields, field_name)
    if existing is None:
        known = ", ".join(str(f.get("name")) for f in fields if isinstance(f, dict)) or "(none)"
        raise EditFieldError(
            f"field {field_name!r} not found on {target.get('name')!r} — fields: {known}")
    if existing.get("primaryKey") or existing.get("references"):
        raise EditFieldError(
            f"{field_name!r} is a key or foreign-key column — removing it would orphan "
            f"a relationship; drop the relationship first.")

    target["fields"] = [f for f in fields if f is not existing]
    new_drizzle = _remove_column_line(dsrc, _column_var(str(existing.get("name"))), dpath.name)
    return [
        BundleOp(path="contracts/resource-registry.json",
                 content=json.dumps(registry, indent=2) + "\n", kind="registry"),
        BundleOp(path=f"src/db/schema/{slug}.ts", content=new_drizzle, kind="drizzle"),
    ]


def build_edit_field_bundle(output_dir: str, *, entity: str, field_name: str,
                            new_name: str | None = None,
                            new_type: str | None = None) -> list[BundleOp]:
    """Compose the bundle that renames and/or retypes one column.

    ``new_name`` renames the field (registry) and its column (Drizzle var + the
    column-name string); ``new_type`` rebuilds the column's Drizzle builder and
    updates the registry type. At least one must be given.
    """
    field_name = str(field_name or "").strip()
    new_name = str(new_name or "").strip() or None
    new_type = str(new_type or "").strip() or None
    if not field_name:
        raise EditFieldError("field_name is required")
    if not new_name and not new_type:
        raise EditFieldError("nothing to change — pass new_name and/or new_type")
    _refuse_managed(field_name, "edited")

    registry, target, fields, slug, dpath, dsrc = _load_target(output_dir, entity)
    existing = _find_field(fields, field_name)
    if existing is None:
        known = ", ".join(str(f.get("name")) for f in fields if isinstance(f, dict)) or "(none)"
        raise EditFieldError(
            f"field {field_name!r} not found on {target.get('name')!r} — fields: {known}")
    if new_name and _find_field(fields, new_name) and new_name.lower() != field_name.lower():
        raise EditFieldError(
            f"{target.get('name')!r} already has a field named {new_name!r}")

    old_var = _column_var(str(existing.get("name")))
    final_name = new_name or str(existing.get("name"))
    final_type = new_type or existing.get("type") or "varchar"

    # Registry: rename and/or retype in place, keeping the field's other shape keys.
    if new_name:
        existing["name"] = new_name
    if new_type:
        existing["type"] = new_type
        # a length only makes sense for string types; drop it on a retype away.
        if new_type not in ("varchar", "text", "char") and "length" in existing:
            existing.pop("length", None)

    new_drizzle = _rewrite_column_line(
        dsrc, old_var, dpath.name,
        new_var=_column_var(final_name),
        new_col=_snake(final_name),
        retype_field={"name": final_name, "type": final_type,
                      **{k: existing[k] for k in ("length", "precision", "scale")
                         if k in existing}} if new_type else None,
    )
    return [
        BundleOp(path="contracts/resource-registry.json",
                 content=json.dumps(registry, indent=2) + "\n", kind="registry"),
        BundleOp(path=f"src/db/schema/{slug}.ts", content=new_drizzle, kind="drizzle"),
    ]


def _rewrite_column_line(src: str, old_var: str, filename: str, *,
                         new_var: str, new_col: str,
                         retype_field: dict | None) -> str:
    """Rewrite the one column line for `old_var`: new variable name, new column
    string, and — when `retype_field` is given — a rebuilt builder from the new
    type. Chained modifiers (`.notNull()`, `.default(...)`) are preserved."""
    from services.schema_builder import _builder_for

    out_lines, done = [], False
    for line in src.splitlines(keepends=True):
        m = _COLUMN_LINE.match(line.rstrip("\n"))
        if not (m and m.group("var") == old_var):
            out_lines.append(line)
            continue
        indent, chain = m.group("indent"), m.group("chain")
        if retype_field is not None:
            f = dict(retype_field)
            f["notNull"] = False
            builder, _args = _builder_for(f)
            args = f'"{new_col}"'
            # carry a length option for string builders that take one.
            if f.get("length") and builder in ("varchar", "char"):
                args += f', {{ length: {int(f["length"])} }}'
        else:
            builder = m.group("builder")
            # keep the original options, only swap the column-name string (1st arg).
            args = re.sub(r'"[^"]*"', f'"{new_col}"', m.group("args"), count=1)
        out_lines.append(f'{indent}{new_var}: {builder}({args}){chain},\n')
        done = True
    if not done:
        raise EditFieldError(f"{filename}: no column line for {old_var!r} to edit")
    return "".join(out_lines)
