"""Rename an entity (and/or its table) — the last managed structural change.

An entity has no "type", so an entity edit is a **rename**: the registry name,
the slug, the table, the Drizzle module (its file name, its exported const, and
its ``pgTable("…")`` string) and the barrel export line all move together. It is
the highest-cascade edit — every workflow, page, relationship and foreign key
that named the old entity now names something gone — so the caller confirms with
the full blast radius first, and the completeness checks surface each reference
to repair. This seam does the source surgery only.

``new_table`` alone renames just the table (the entity keeps its name and
module); ``new_name`` renames the entity and everything derived from it. The
auth/users entity is refused — next-auth owns it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from services.atomic_apply import BundleOp
from services.add_entity_seam import _camel_var
from services.remove_entity_seam import _is_auth_entity, _to_kebab, dependents, _AUTH_NAMES  # noqa: F401


class EditEntityError(ValueError):
    """Raised when the seam cannot build a bundle. Caller renders the message."""


def _derive_table(name: str) -> str:
    from services.entity_names import derive_names
    return derive_names(name).tableSnake


def build_edit_entity_bundle(output_dir: str, *, entity: str,
                             new_name: str | None = None,
                             new_table: str | None = None) -> list[BundleOp]:
    """Compose the atomic bundle that renames an entity and/or its table."""
    entity = str(entity or "").strip()
    new_name = str(new_name or "").strip() or None
    new_table = str(new_table or "").strip() or None
    if not entity:
        raise EditEntityError("entity is required")
    if not new_name and not new_table:
        raise EditEntityError("nothing to change — pass new_name and/or new_table")

    out = Path(output_dir)
    reg_path = out / "contracts" / "resource-registry.json"
    if not reg_path.is_file():
        raise EditEntityError("registry not found: contracts/resource-registry.json")
    try:
        registry = json.loads(reg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise EditEntityError(f"registry unreadable: {e}") from e
    entities = registry.get("entities")
    if not isinstance(entities, list):
        raise EditEntityError("registry.entities must be a list")

    target = next((e for e in entities
                   if isinstance(e, dict) and str(e.get("name") or "").lower() == entity.lower()),
                  None)
    if target is None:
        known = ", ".join(str(e.get("name")) for e in entities if isinstance(e, dict)) or "(none)"
        raise EditEntityError(f"entity {entity!r} not found in the registry — known: {known}")
    if _is_auth_entity(target):
        raise EditEntityError(
            f"{target.get('name')!r} is an auth-managed entity — next-auth owns it and "
            f"renaming it breaks sign-in.")
    if new_name and any(
            isinstance(e, dict) and e is not target
            and str(e.get("name") or "").lower() == new_name.lower() for e in entities):
        raise EditEntityError(f"an entity named {new_name!r} already exists")

    old_slug = str(target.get("slug") or "").strip() or _to_kebab(str(target.get("name") or entity))
    old_var = _camel_var(str(target.get("name") or entity))
    final_name = new_name or str(target.get("name"))
    final_slug = _to_kebab(final_name) if new_name else old_slug
    final_var = _camel_var(final_name)
    final_table = new_table or (_derive_table(new_name) if new_name else str(target.get("table") or ""))

    # Never rename INTO the auth namespace — a `users`/`accounts` table would
    # collide with next-auth's own at push time.
    if final_name.lower() in _AUTH_NAMES or final_table.lower() in _AUTH_NAMES \
            or final_slug in _AUTH_NAMES:
        raise EditEntityError(
            f"renaming to {final_name!r} (table {final_table!r}) collides with the "
            f"auth namespace next-auth owns — pick another name.")

    # Registry, in place.
    if new_name:
        target["name"] = new_name
        target["slug"] = final_slug
    if final_table:
        target["table"] = final_table

    old_module = out / "src" / "db" / "schema" / f"{old_slug}.ts"
    if not old_module.is_file():
        raise EditEntityError(
            f"drizzle module not found: src/db/schema/{old_slug}.ts — this app predates "
            "the per-entity schema module; a rename here needs a rebuild.")
    src = old_module.read_text(encoding="utf-8")
    # Swap the exported const name and the pgTable("…") string, whatever they are.
    new_src = re.sub(
        r'export\s+const\s+\w+\s*=\s*pgTable\(\s*"[^"]*"',
        f'export const {final_var} = pgTable("{final_table}"',
        src, count=1)
    if new_src == src and (new_name or new_table):
        raise EditEntityError(
            f"src/db/schema/{old_slug}.ts: no `export const … = pgTable(\"…\"` to rename")

    ops: list[BundleOp] = [
        BundleOp(path="contracts/resource-registry.json",
                 content=json.dumps(registry, indent=2) + "\n", kind="registry"),
    ]
    if final_slug != old_slug:
        # Module file moves: write the new, delete the old.
        ops.append(BundleOp(path=f"src/db/schema/{final_slug}.ts", content=new_src, kind="drizzle"))
        ops.append(BundleOp(path=f"src/db/schema/{old_slug}.ts", content="", kind="delete"))
    else:
        ops.append(BundleOp(path=f"src/db/schema/{final_slug}.ts", content=new_src, kind="drizzle"))

    # Barrel: rewrite the one export line for this module.
    barrel_path = out / "src" / "db" / "schema" / "index.ts"
    if barrel_path.is_file():
        barrel = barrel_path.read_text(encoding="utf-8")
        new_line = f'export {{ {final_var} }} from "./{final_slug}";'
        rewritten = []
        changed = False
        for ln in barrel.splitlines(keepends=True):
            if f'"./{old_slug}"' in ln or f"'./{old_slug}'" in ln:
                rewritten.append(new_line + ("\n" if ln.endswith("\n") else ""))
                changed = True
            else:
                rewritten.append(ln)
        if changed:
            ops.append(BundleOp(path="src/db/schema/index.ts",
                                content="".join(rewritten), kind="barrel"))

    return ops
