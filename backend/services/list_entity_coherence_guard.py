"""Bind persona/entity list pages to the entity that matches their filename.

The symptom class this closes
----------------------------
On `inhdm3ta`, `carers.json`, `elderly-users.json`, and `guardians.json` all
declared `dataSources: [{name:"users", entity:"User", op:"list"}]` with the
Table bound to `{{users}}`. The generated app therefore rendered every user
on every persona page. The reason is a naming choice by the LLM: it authored
each persona page but reused the "users" dataSource that appeared on other
pages, ignoring the persona entity that lives under its own table
(`carers` / `elderly_users` / `guardians`).

What this pass does
-------------------
For every schema file whose basename maps to a registered entity, if the
page's FIRST list dataSource binds a different entity, rebind it:

  * `dataSource.entity` → the matching entity
  * `dataSource.name`   → the plural-lowercase of the entity name (matches the
    convention used by the deterministic list-page emitter and by the
    Data Engine's slug resolver)
  * Every `Table.rows` / `Repeat.items` / `List.items` binding on the page
    that referenced the OLD name is repointed to the new one.

Deterministic. Idempotent. Silent on error. Runs BEFORE
`list_data_source_guard` so the slug reconciler works against the
corrected shape.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from services.artifact_authority import should_assert_only_any
from typing import Any

from services.entity_names import derive_names

logger = logging.getLogger(__name__)


# Files that never carry an entity list. Skipped even if their filename by
# accident matches a registered entity.
_SKIP_STEMS = {"shell", "login", "signup", "forgot-password", "dashboard", "home"}

_LIST_BINDING_KEYS = ("rows", "items", "list", "data")
_SINGLE_TOKEN_RE = re.compile(r"^\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}$")

# List-shape ops recognized by the data engine. `list_data_source_guard` uses
# the same set — kept aligned.
_LIST_OPS = {"list", "read", "select", "query"}


def reconcile_list_entities(output_dir: str) -> dict:
    """Rebind persona list pages to the entity that matches their filename.

    Returns::

        {"pages_scanned": int, "pages_rebound": int,
         "rebound_files": [(file, old_entity, new_entity), ...]}

    Never raises.
    """
    root = Path(output_dir)
    schemas_dir = root / "src" / "schemas"
    summary: dict[str, Any] = {
        "pages_scanned": 0,
        "pages_rebound": 0,
        "asserts_logged": 0,
        "rebound_files": [],
    }
    if not schemas_dir.exists():
        return summary

    entity_by_key = _load_entity_by_key(root)
    if not entity_by_key:
        return summary

    for schema_path in sorted(schemas_dir.rglob("*.json")):
        rel = schema_path.relative_to(schemas_dir)
        rel_str = str(rel).replace("\\", "/")

        # Only touch top-level `<name>.json` files. `<name>/[id].json`,
        # `<name>/new.json`, and `<name>/[id]/edit.json` are detail / edit
        # / create pages — not list pages.
        if len(rel.parts) != 1:
            continue
        stem = rel.stem
        if stem.lower() in _SKIP_STEMS:
            continue

        entity_name = entity_by_key.get(_canon(stem))
        if not entity_name:
            # No matching entity — the LLM authored a page whose name doesn't
            # correspond to a registered entity. Leave it alone.
            continue

        summary["pages_scanned"] += 1

        try:
            page = json.loads(schema_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            logger.exception("[list-entity-coherence] read failed: %s", rel_str)
            continue

        # Composer-authored pages are ASSERT-only: the composer's decision is the
        # authority, so log drift instead of rewriting it.
        if should_assert_only_any(page):
            summary["asserts_logged"] += 1
            continue

        changed = _rebind_page(page, entity_name)
        if not changed:
            continue

        try:
            schema_path.write_text(json.dumps(page, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            logger.exception("[list-entity-coherence] write failed: %s", rel_str)
            continue

        summary["pages_rebound"] += 1
        summary["rebound_files"].append(
            (rel_str, changed[0], changed[1])
        )
        logger.info(
            "[list-entity-coherence] %s : dataSource entity %r -> %r",
            rel_str, changed[0], changed[1],
        )

    return summary


# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────


def _load_entity_by_key(root: Path) -> dict[str, str]:
    """Return {canonicalized_slug: canonical entity name}. Reads registry
    (preferred, has table + fields) and plan as fallback."""
    for candidate in ("registry.json", "plan.json"):
        p = root / candidate
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        entities = data.get("entities")
        if not isinstance(entities, dict):
            continue
        out: dict[str, str] = {}
        for name in entities:
            if not isinstance(name, str) or not name:
                continue
            for key in _entity_lookup_keys(name):
                out.setdefault(key, name)
        if out:
            return out
    return {}


def _entity_lookup_keys(name: str) -> list[str]:
    """Return the canonical keys under which an entity can be looked up from
    a page filename. Covers singular/plural + camel/kebab/snake variants.

    `Carer` → carer, carers
    `ElderlyUser` → elderlyuser, elderlyusers
    `User` → user, users
    """
    canon = _canon(name)
    keys = {canon}
    if not canon.endswith("s"):
        keys.add(canon + "s")
    else:
        keys.add(canon[:-1])
    return list(keys)


def _canon(s: str) -> str:
    """Lowercase, strip non-alphanumerics. `elderly-users` → `elderlyusers`;
    `ElderlyUser` → `elderlyuser`."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _plural_slug(entity_name: str) -> str:
    """Plural lowercase dataSource slug: `ElderlyUser` → `elderlyusers`.

    Delegates to :func:`services.entity_names.derive_names` — the single
    naming authority. The local version appended a bare `'s'` and
    disagreed with the authority on 17 of every 20 names, the highest
    mismatch rate measured anywhere in the pipeline. Since this slug is
    what `_rebind_page` rebinds a list's dataSource to, a wrong slug
    pointed the list at a source that does not exist — producing the
    exact empty-table symptom this guard was written to remove.

    Raises :class:`services.entity_names.EntityNameError` rather than
    rebinding a page to a slug derived from a nameless entity."""
    return derive_names(entity_name).pluralSlug


def _rebind_page(page: dict, entity_name: str) -> tuple[str, str] | None:
    """Rebind the first list dataSource on `page` to `entity_name`. Returns
    (old_entity, new_entity) if a change was made, else None."""
    data_sources = page.get("dataSources")
    if not isinstance(data_sources, list) or not data_sources:
        return None

    target_slug = _plural_slug(entity_name)

    for ds in data_sources:
        if not isinstance(ds, dict):
            continue
        op = str(ds.get("op", "")).strip().lower()
        if op not in _LIST_OPS:
            continue
        current_entity = ds.get("entity")
        if current_entity == entity_name:
            return None  # already correct
        # Rebind THIS dataSource.
        old_entity = str(current_entity) if current_entity else ""
        old_name = str(ds.get("name") or "")
        ds["entity"] = entity_name
        ds["name"] = target_slug
        # Repoint every {{old_name}} single-token binding on the page.
        if old_name and old_name != target_slug:
            _rebind_bindings(page.get("root"), old_name, target_slug)
        return old_entity, entity_name
    return None


def _rebind_bindings(node: Any, old_name: str, new_name: str) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _LIST_BINDING_KEYS and isinstance(v, str):
                m = _SINGLE_TOKEN_RE.match(v)
                if m and m.group(1) == old_name:
                    node[k] = "{{" + new_name + "}}"
                    continue
            _rebind_bindings(v, old_name, new_name)
    elif isinstance(node, list):
        for v in node:
            _rebind_bindings(v, old_name, new_name)
