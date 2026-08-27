"""S5-T4 — `add_workflow` composite seam.

Mirrors :mod:`services.add_page_seam` for workflow files. Smith proposes
op + entity; the applier synthesizes the workflow via the pipeline's own
:func:`services.crud_workflow_generator.build_crud_workflow` and lands
it atomically via :mod:`services.atomic_apply`.

Files this seam writes:
    * ``workflows/<Op><Entity>.json`` — e.g. ``CreateCandidate.json``

Op set for slice T4 is deliberately limited to what
``build_crud_workflow`` already covers (Create / Update / Delete). Richer
workflows (approvals, multi-step business processes) fall back to the
LLM refiner or a future seam.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from services.atomic_apply import BundleOp
from services.entity_names import derive_names

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Public: supported ops
# --------------------------------------------------------------------------- #

DETERMINISTIC_OPS: tuple[str, ...] = ("create", "update", "delete")
"""What ``services.crud_workflow_generator.build_crud_workflow`` handles."""


class AddWorkflowError(ValueError):
    """Raised when the seam can't build a bundle. Caller renders the
    message directly."""


# --------------------------------------------------------------------------- #
# Public builder
# --------------------------------------------------------------------------- #

def build_add_workflow_bundle(
    output_dir: str,
    *,
    op: str,
    entity: str,
    name: Optional[str] = None,
) -> list[BundleOp]:
    """Compose the atomic-apply bundle for a new CRUD workflow.

    Args:
        output_dir: The generated app's root.
        op: One of :data:`DETERMINISTIC_OPS`.
        entity: Registry entity name (canonical or lowercased).
        name: Optional workflow file basename (defaults to
            ``<Op><Entity>``, e.g. ``CreateCandidate``).

    Returns:
        A list of :class:`BundleOp` ready for
        :func:`services.atomic_apply.apply_bundle`.

    Raises:
        AddWorkflowError: On unsupported op, unknown entity, or when
            the generator refuses.
    """
    out = Path(output_dir)
    if not out.is_dir():
        raise AddWorkflowError(f"output_dir missing: {output_dir}")

    op_norm = (op or "").strip().lower()
    if op_norm not in DETERMINISTIC_OPS:
        raise AddWorkflowError(
            f"op {op!r} is not deterministic. "
            f"Supported: {sorted(DETERMINISTIC_OPS)}. "
            "Hand off to the LLM refiner for bespoke workflows."
        )

    entities = _load_entities(out)
    entity_meta = entities.get((entity or "").strip().lower())
    if entity_meta is None:
        raise AddWorkflowError(
            f"entity {entity!r} not found in registry. "
            f"Available: {sorted(entities.keys())}"
        )
    entity_name = entity_meta["_name"]
    fields = entity_meta["fields_list"]
    table = entity_meta.get("_table") or _derive_table(entity_name)

    # 1. Build the workflow via the pipeline's own builder.
    #
    # `pk` matters: Update/Delete emit `where {<pk>: …}`. This seam used to
    # call the generator with no `pk`, taking the `id` default, while fresh
    # generation read the real key off the parsed Drizzle schema (register
    # S21-3). On a table keyed on `uuid` / `code` the seam's WHERE named a
    # column that does not exist, `_buildWhere` dropped it, and the runtime
    # refused with "WHERE resolved to zero conditions" — the button did
    # nothing, silently. Both paths now ask the same authority.
    from services.crud_workflow_generator import (
        build_crud_workflow,
        primary_key_of,
        schema_columns_for,
    )
    real_cols = schema_columns_for(str(out), table)
    pk = primary_key_of(real_cols, table=table)
    if pk is None and real_cols and op_norm in ("update", "delete"):
        # The schema DOES describe this table and it has neither a primary key
        # nor an `id` column — so any WHERE we emit is knowably dead. Refuse
        # rather than ship a button that does nothing. When `real_cols` is None
        # the schema simply doesn't say; the generator's `id` default stands.
        raise AddWorkflowError(
            f"cannot build a {op_norm} workflow for {entity_name!r}: table "
            f"{table!r} declares no primary key and has no 'id' column "
            f"(columns: {sorted(c.get('name') for c in real_cols if c.get('name'))}). "
            f"Any WHERE would reference a column that does not exist and the "
            f"workflow would silently do nothing at runtime. Add a primary key "
            f"to the table, then retry."
        )
    workflow = build_crud_workflow(entity_name, table, fields, op_norm, pk=pk)
    if not isinstance(workflow, dict):
        raise AddWorkflowError(
            f"crud generator returned no workflow for op={op_norm!r} entity={entity_name!r}"
        )

    # 2. Compose the file path (matches the pipeline's <Op><Entity>.json
    #    convention — CreateCandidate.json, etc.).
    file_basename = (name or f"{op_norm.capitalize()}{entity_name}").strip()
    if not file_basename.endswith(".json"):
        file_basename = f"{file_basename}.json"

    # Refuse if a workflow that any RESOLVER would confuse with this one
    # already exists (register S20-2).
    #
    # This was an exact-basename `is_file()` check, but every resolver in the
    # system compares case- and separator-insensitively. So `create_candidate`
    # could be created beside an existing `CreateCandidate`, and from that
    # moment `_resolve_workflow_path` could not tell the two apart — a later
    # Smith edit would land in whichever the filesystem listed first. The guard
    # now uses the SAME key the resolvers use, so "can this collide?" has one
    # answer rather than two.
    from services.edit_workflow_seam import normalize_workflow_key
    wf_dir = out / "workflows"
    new_key = normalize_workflow_key(file_basename[:-5])
    if wf_dir.is_dir():
        clashes = sorted(
            f.name for f in wf_dir.glob("*.json")
            if normalize_workflow_key(f.stem) == new_key
        )
        if clashes:
            raise AddWorkflowError(
                f"workflow already exists: {', '.join(clashes)} — a name that "
                f"differs only in case, '-' or '_' resolves to the SAME "
                f"workflow, so creating workflows/{file_basename} would make "
                f"both unaddressable. Delete it first or pick a different `name`."
            )

    return [BundleOp(
        path=f"workflows/{file_basename}",
        content=json.dumps(workflow, indent=2) + "\n",
        kind="workflow",
    )]


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #

def _load_entities(out: Path) -> dict[str, dict]:
    """``{lower_name: {_name, _table, fields_list}}`` — matches
    add_page_seam._load_entities but preserves the fields list (not dict)
    because build_crud_workflow expects the list-of-{name,type,notNull}
    shape."""
    reg_path = out / "contracts" / "resource-registry.json"
    if not reg_path.is_file():
        return {}
    try:
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(reg, dict):
        return {}

    out_map: dict[str, dict] = {}
    for e in reg.get("entities") or []:
        if not isinstance(e, dict):
            continue
        name = e.get("name") or e.get("slug")
        if not isinstance(name, str) or not name:
            continue
        fields = e.get("fields") or e.get("columns") or []
        if isinstance(fields, dict):
            # normalise dict-shape to list, matching what registry_extractor
            # writes in most cases.
            fields = [{"name": k, **v} for k, v in fields.items() if isinstance(v, dict)]
        if not isinstance(fields, list):
            fields = []
        out_map[name.lower()] = {
            "_name": name,
            "_table": e.get("table") or e.get("sql_table"),
            "fields_list": fields,
        }
    return out_map


def _derive_table(entity_name: str) -> str:
    """Fallback table-name derivation when the registry doesn't carry one.

    Delegates to :func:`services.entity_names.derive_names` — the single
    naming authority — which is what fresh generation uses via
    ``crud_workflow_generator._derive_table``. This helper used to append
    a bare ``'s'``, so ``Category`` produced ``categorys``: a workflow
    added through this seam wrote to a table that does not exist and
    failed at runtime with `unknown table`. Same defect as register
    finding CRUD-1, in the Smith add-workflow seam rather than fresh
    generation; the Tier-1 sweep did not reach this one."""
    return derive_names(entity_name).tableSnake
