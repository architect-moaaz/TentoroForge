"""set_field_interaction — pure resolver + writer for the field-level
``interaction`` block. Called by:

  - Smith tool ``set_field_interaction`` (chat authoring)
  - Editor "Interactions" panel (visual authoring, via the same schema
    edit endpoint)

Contract:
  - Validates via :func:`services.interaction_spec.validate_interaction`
  - Applies merge/replace/remove semantics
  - Writes atomically via a single JSON-object rewrite (same pattern the
    other Smith seams use — no need to reach for the multi-file patcher)
  - Mirrors the interaction to plan.json when the plan tracks fields
    (best-effort; a plan-mirror failure never blocks the schema write)

Returns a dict shaped like the other Smith seams (``applied``,
``edited_paths``, ``diff_summary``, ``reason`` on failure).
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any, Iterable

from services.interaction_spec import (
    ValidationResult,
    validate_interaction,
)

logger = logging.getLogger(__name__)


_VALID_MODES = ("merge", "replace", "remove")


def set_field_interaction(
    output_dir: str,
    *,
    page: str,
    field: str,
    interaction: dict[str, Any] | None = None,
    mode: str = "merge",
) -> dict[str, Any]:
    """Apply an ``interaction`` block onto ``field`` in the schema for
    ``page``.

    Args:
        output_dir: generated-app root.
        page:       page identifier — accepts ``"home"``, ``"employees/new"``,
                    ``"src/schemas/employees/new.json"``, or a leading ``/``
                    form (``"/employees/new"``). Falls back to grep across
                    ``src/schemas/**`` if the direct path doesn't resolve.
        field:      name of the target field (case-sensitive first, then
                    case-insensitive fallback).
        interaction: proposed interaction dict (ignored when mode="remove").
        mode:       "merge" (default) — union new keys onto existing;
                    "replace" — drop old block entirely, write new;
                    "remove" — delete the interaction block on this field.

    Returns:
        dict with keys ``applied``, ``edited_paths``, ``diff_summary``, and
        on failure ``reason``. Never raises for user errors.
    """
    if mode not in _VALID_MODES:
        return _err(f"unknown mode '{mode}' — expected one of {_VALID_MODES}")

    root = Path(output_dir).resolve()
    if not root.exists():
        return _err(f"output_dir does not exist: {output_dir}")

    schema_path = _resolve_schema_path(root, page)
    if schema_path is None:
        return _err(
            f"could not locate a schema file for page '{page}' under {root}/src/schemas"
        )

    try:
        schema = json.loads(schema_path.read_text())
    except json.JSONDecodeError as exc:
        return _err(f"schema at {schema_path} is not valid JSON: {exc}")
    except OSError as exc:
        return _err(f"cannot read {schema_path}: {exc}")

    field_node, siblings, field_pointer = _locate_field(schema, field)
    if field_node is None:
        available = sorted(_all_field_names(schema))
        hint = ", ".join(available[:8]) + ("…" if len(available) > 8 else "")
        return _err(
            f"field '{field}' not found in {schema_path.name}. "
            f"Available fields: {hint or '(none)'}"
        )

    # For remove mode, no validation needed — we just strip the block.
    if mode == "remove":
        if "interaction" not in field_node:
            return {
                "applied": True,
                "edited_paths": [],
                "diff_summary": f"field '{field}' had no interaction — nothing to remove",
                "changed": False,
            }
        new_node = copy.deepcopy(field_node)
        new_node.pop("interaction", None)
        return _write_and_summarize(
            schema, schema_path, field_pointer, field_node, new_node,
            root=root, page=page, mode=mode,
        )

    # merge / replace need a proposed block
    if not isinstance(interaction, dict):
        return _err(
            f"interaction must be a JSON object for mode='{mode}', "
            f"got {type(interaction).__name__}"
        )

    # Load registry — validator degrades resource checks gracefully when
    # it's not available, so a missing registry doesn't block authoring.
    registry = _try_load_registry(root)

    # For merge, start from the existing block and layer new keys on top,
    # then re-validate the combined shape so cross-checks (unknown
    # sibling, cycle) see the whole picture.
    proposed = _combine(field_node.get("interaction"), interaction, mode)

    result: ValidationResult = validate_interaction(
        proposed, field_node, siblings, registry=registry
    )
    if not result.ok:
        return _err(
            "interaction validation failed",
            errors=result.errors,
            warnings=result.warnings,
        )

    new_node = copy.deepcopy(field_node)
    if result.canonical:
        new_node["interaction"] = result.canonical
    else:
        new_node.pop("interaction", None)

    return _write_and_summarize(
        schema, schema_path, field_pointer, field_node, new_node,
        root=root, page=page, mode=mode,
        warnings=result.warnings,
    )


# ── Helpers ───────────────────────────────────────────────────────────────


def _err(message: str, *, errors: list[str] | None = None, warnings: list[str] | None = None) -> dict[str, Any]:
    return {
        "applied": False,
        "edited_paths": [],
        "reason": message,
        "errors": errors or [],
        "warnings": warnings or [],
    }


def _combine(existing: Any, proposed: dict[str, Any], mode: str) -> dict[str, Any]:
    """Return the interaction dict to validate. In merge mode we union
    top-level keys (proposed wins on collision); in replace mode we
    drop existing entirely."""
    if mode == "replace" or not isinstance(existing, dict):
        return copy.deepcopy(proposed)
    merged: dict[str, Any] = copy.deepcopy(existing)
    for k, v in proposed.items():
        # None / null on a top-level key = "remove that sub-key"
        if v is None:
            merged.pop(k, None)
        else:
            merged[k] = copy.deepcopy(v)
    return merged


def _write_and_summarize(
    schema: dict,
    schema_path: Path,
    field_pointer: list[Any],
    old_node: dict,
    new_node: dict,
    *,
    root: Path,
    page: str,
    mode: str,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Apply new_node at field_pointer in schema, write atomically, mirror
    to plan.json, return a summary."""
    if old_node == new_node:
        return {
            "applied": True,
            "edited_paths": [],
            "diff_summary": "no change (proposed interaction equals current)",
            "changed": False,
            "warnings": warnings or [],
        }

    _apply_at_pointer(schema, field_pointer, new_node)

    try:
        tmp = schema_path.with_suffix(schema_path.suffix + ".tmp")
        tmp.write_text(json.dumps(schema, indent=2) + "\n")
        tmp.replace(schema_path)
    except OSError as exc:
        return _err(f"failed to write schema at {schema_path}: {exc}")

    edited = [str(schema_path.relative_to(root))]

    # Best-effort plan.json mirror — mirror keeps plan authoritative for
    # downstream re-generations, but a failure here does NOT roll back the
    # schema write (schema is source-of-truth for the runtime).
    plan_mirror = _mirror_to_plan(root, page, new_node)
    if plan_mirror:
        edited.append(plan_mirror)

    field_name = new_node.get("name") or old_node.get("name")
    diff_lines = _diff_summary(old_node.get("interaction"), new_node.get("interaction"))
    return {
        "applied": True,
        "edited_paths": edited,
        "diff_summary": f"{mode} interaction on field '{field_name}' in {schema_path.name}:\n  {diff_lines}",
        "changed": True,
        "field": field_name,
        "warnings": warnings or [],
    }


def _diff_summary(before: Any, after: Any) -> str:
    if before is None and after is not None:
        return f"+ {json.dumps(after, sort_keys=True)[:200]}"
    if before is not None and after is None:
        return f"- {json.dumps(before, sort_keys=True)[:200]}"
    return (
        f"~ before={json.dumps(before, sort_keys=True)[:120]}\n"
        f"   after={json.dumps(after, sort_keys=True)[:120]}"
    )


# ── Schema-path resolution ────────────────────────────────────────────────


def _resolve_schema_path(root: Path, page: str) -> Path | None:
    """Accept any of:
        home                              → src/schemas/home.json
        employees/new                     → src/schemas/employees/new.json
        /employees/new                    → src/schemas/employees/new.json
        src/schemas/employees/new.json    → src/schemas/employees/new.json (verbatim)
    """
    schemas_root = root / "src" / "schemas"
    if not schemas_root.exists():
        return None

    p = (page or "").strip().lstrip("/")
    if not p:
        return None

    # Verbatim path (relative or absolute)
    for candidate in [
        Path(p),
        root / p,
        schemas_root / p,
        schemas_root / (p + ".json"),
    ]:
        if candidate.is_absolute() and candidate.exists() and candidate.is_file():
            return candidate.resolve()
        rel = root / candidate
        if rel.exists() and rel.is_file():
            return rel.resolve()

    # Fall back to a single grep — look for a file whose relative path
    # matches the page under src/schemas
    matches = list(schemas_root.rglob("*.json"))
    p_norm = p.rstrip(".json")
    for m in matches:
        rel = str(m.relative_to(schemas_root))
        if rel == p_norm + ".json" or rel.rstrip(".json") == p_norm:
            return m.resolve()

    return None


# ── Field walker ──────────────────────────────────────────────────────────


def _locate_field(
    schema: dict, target: str
) -> tuple[dict | None, list[dict], list[Any]]:
    """Find a form-field node named ``target`` anywhere in the schema
    tree. Returns (field_node, siblings, pointer). The pointer is a list
    of keys/indices to walk from the root to the found node."""
    target_lower = target.lower()

    # First pass: exact match
    found = _walk_for_field(schema, target, case_insensitive=False, pointer=[])
    if found is not None:
        node, pointer = found
        siblings = _siblings_at_pointer(schema, pointer)
        return node, siblings, pointer

    # Second pass: case-insensitive fallback
    found = _walk_for_field(schema, target_lower, case_insensitive=True, pointer=[])
    if found is not None:
        node, pointer = found
        siblings = _siblings_at_pointer(schema, pointer)
        return node, siblings, pointer

    return None, [], []


def _walk_for_field(
    node: Any, target: str, *, case_insensitive: bool, pointer: list[Any]
) -> tuple[dict, list[Any]] | None:
    """DFS through the tree looking for a form-field node whose ``name``
    equals target. A form field is any dict inside a ``fields`` list."""
    if isinstance(node, dict):
        # If this dict has a "fields" list, scan its entries first
        fields = node.get("fields")
        if isinstance(fields, list):
            for i, f in enumerate(fields):
                if not isinstance(f, dict):
                    continue
                name = f.get("name")
                if not isinstance(name, str):
                    continue
                match = (
                    name == target
                    if not case_insensitive
                    else name.lower() == target
                )
                if match:
                    return f, pointer + ["fields", i]
        # Recurse into children
        for k, v in node.items():
            result = _walk_for_field(
                v, target, case_insensitive=case_insensitive, pointer=pointer + [k]
            )
            if result is not None:
                return result
    elif isinstance(node, list):
        for i, item in enumerate(node):
            result = _walk_for_field(
                item, target, case_insensitive=case_insensitive, pointer=pointer + [i]
            )
            if result is not None:
                return result
    return None


def _siblings_at_pointer(schema: dict, pointer: list[Any]) -> list[dict]:
    """Return the list-of-fields containing the target."""
    if not pointer or pointer[-2] != "fields":
        return []
    parent_pointer = pointer[:-1]  # points at "fields"
    parent = _get_at_pointer(schema, parent_pointer)
    return [f for f in (parent or []) if isinstance(f, dict)]


def _apply_at_pointer(schema: dict, pointer: list[Any], new_value: Any) -> None:
    if not pointer:
        return
    cur = schema
    for k in pointer[:-1]:
        cur = cur[k]
    cur[pointer[-1]] = new_value


def _get_at_pointer(schema: Any, pointer: list[Any]) -> Any:
    cur = schema
    for k in pointer:
        try:
            cur = cur[k]
        except (KeyError, IndexError, TypeError):
            return None
    return cur


def _all_field_names(schema: Any) -> Iterable[str]:
    """Enumerate every field ``name`` in the schema. Used for typo hints."""
    if isinstance(schema, dict):
        fields = schema.get("fields")
        if isinstance(fields, list):
            for f in fields:
                if isinstance(f, dict) and isinstance(f.get("name"), str):
                    yield f["name"]
        for v in schema.values():
            yield from _all_field_names(v)
    elif isinstance(schema, list):
        for item in schema:
            yield from _all_field_names(item)


# ── Registry loader (fail-open) ───────────────────────────────────────────


def _try_load_registry(root: Path) -> dict | None:
    """Best-effort registry load — returns None on any failure so
    validator degrades resource checks to warnings instead of blocking.
    """
    try:
        from services.registry import load_registry
        return load_registry(str(root)) or None
    except Exception as exc:  # noqa: BLE001
        logger.debug("set_field_interaction: registry unavailable (%s)", exc)
        return None


# ── plan.json mirror ──────────────────────────────────────────────────────


def _mirror_to_plan(root: Path, page: str, new_field_node: dict) -> str | None:
    """Best-effort: if plan.json exists and has a page whose route matches
    ``page`` with a fields[] entry matching the field name (case-insensitive),
    mirror the interaction there so the plan stays authoritative for
    future re-generations. Returns the relative path written, or None."""
    plan_path = root / "plan.json"
    if not plan_path.exists():
        return None
    try:
        plan = json.loads(plan_path.read_text())
    except Exception:  # noqa: BLE001
        return None

    field_name = new_field_node.get("name")
    if not isinstance(field_name, str) or not field_name:
        return None
    interaction = new_field_node.get("interaction")

    page_norm = (page or "").strip().lstrip("/").rstrip(".json").lower()
    # Try matching the page against route/id/slug forms the plan uses
    pages = plan.get("pages") if isinstance(plan.get("pages"), list) else []
    for p in pages:
        if not isinstance(p, dict):
            continue
        candidates = {
            str(p.get(k, "")).strip("/").lower()
            for k in ("route", "id", "slug", "path")
            if p.get(k)
        }
        if page_norm not in candidates:
            continue
        fields = p.get("fields")
        if not isinstance(fields, list):
            continue
        for f in fields:
            if not isinstance(f, dict):
                continue
            fname = f.get("name")
            if isinstance(fname, str) and fname.lower() == field_name.lower():
                if interaction is None:
                    f.pop("interaction", None)
                else:
                    f["interaction"] = copy.deepcopy(interaction)
                try:
                    plan_path.write_text(json.dumps(plan, indent=2) + "\n")
                    return str(plan_path.relative_to(root))
                except OSError:
                    return None
    return None
