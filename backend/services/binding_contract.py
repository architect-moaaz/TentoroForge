"""Derive the data-binding contract from REALITY and feed it forward to the UI.

The mismatches happen because the page agent binds against *intent* (the early,
LLM-declared contract said "Plan") while the runtime only has *reality*
("MembershipPlan"). This module closes the gap at the source: after the schema +
workflows are generated and extracted into the registry, it computes — purely
deterministically — the exact binding for every entity (FK dropdowns → real target
entity + slug + label field, form → real Create/Update workflow, status field →
real status workflow), persists it as `contracts/binding-contract.json`, and
injects it into the page agent's prompt.

So the page agent is handed the real references instead of guessing them. The
`resolve_schema_references` pass then only has to catch the rare residual.
"""
from __future__ import annotations

import json
import logging
import os

logger = logging.getLogger(__name__)

from services.form_scaffold import (
    _ent_key, _label_field, _plural, _fk_target, _load_registry,
)
from services.semantic_field_types import _norm
from services.workflow_action_mapper import index_status_workflows

from services.fk_semantics import hidden_fk_columns, default_hidden_fk_norms


def _workflow_names(output_dir: str) -> set[str]:
    """Every string the RUNTIME will resolve to a workflow.

    The contract tells the page agent which workflow to bind to, so a name that
    is not runtime-resolvable is an instruction to build a dead button — the
    agent obeys, the button renders, and clicking it does nothing (register
    BA-3). `resolvable_workflow_names` is the single authority for this: it
    keys the way `loadWorkflows` does, by declared id AND name.

    A failure here must not silently produce an EMPTY set: that would strip
    every createWorkflow/updateWorkflow from the contract and look identical to
    an app with no workflows at all.
    """
    from services.crud_actions import resolvable_workflow_names
    try:
        return resolvable_workflow_names(output_dir)
    except Exception as e:  # noqa: BLE001
        logger.error(
            "binding_contract: could not index workflows under %s (%s) — the "
            "contract will omit every form workflow, so the page agent gets no "
            "binding guidance at all.", output_dir, e,
        )
        return set()


def derive_binding_contract(output_dir: str) -> dict:
    """Compute the per-entity binding contract from the extracted registry."""
    reg = _load_registry(output_dir)
    entities = reg.get("entities") or {}
    relations = reg.get("relations") or []
    exact_wf = _workflow_names(output_dir)
    status_idx = index_status_workflows(output_dir)

    out: dict[str, dict] = {}
    for ename, edef in entities.items():
        fields = (edef or {}).get("fields") or {}
        cols = list(fields.keys()) if isinstance(fields, dict) else []
        # Hide only server-filled (actor/tenancy) FKs; a domain FK still binds.
        try:
            hidden = hidden_fk_columns(ename, reg, output_dir)
        except Exception:
            hidden = default_hidden_fk_norms()
        fk_bindings = []
        for col in cols:
            nk = _norm(col)
            if not (nk.endswith("id") and nk != "id") or nk in hidden:
                continue
            target = _fk_target(_ent_key(ename), nk, relations, entities)
            if not target:
                continue
            fk_bindings.append({
                "field": col,
                "targetEntity": target,
                "source": _plural(target),          # the resolvable /api/data slug
                "valueField": "id",
                "labelField": _label_field(target, entities),
            })
        st = status_idx.get(_ent_key(ename))
        out[ename] = {
            "labelField": _label_field(ename, entities),
            "listSource": _plural(ename),
            "fkBindings": fk_bindings,
            "createWorkflow": f"Create{ename}" if f"Create{ename}" in exact_wf else None,
            "updateWorkflow": f"Update{ename}" if f"Update{ename}" in exact_wf else None,
            "statusWorkflow": ({
                "name": st["name"], "statusVar": st["status_var"],
                "idVar": st["id_var"], "statuses": st["statuses"],
            } if st else None),
        }
    return out


def save_binding_contract(output_dir: str, contract: dict | None = None) -> dict:
    contract = contract if contract is not None else derive_binding_contract(output_dir)
    try:
        cdir = os.path.join(output_dir, "contracts")
        os.makedirs(cdir, exist_ok=True)
        with open(os.path.join(cdir, "binding-contract.json"), "w", encoding="utf-8") as fh:
            json.dump(contract, fh, indent=2)
    except Exception:
        pass
    return contract


def _load_binding_contract(output_dir: str) -> dict:
    try:
        with open(os.path.join(output_dir, "contracts", "binding-contract.json"), encoding="utf-8") as fh:
            return json.load(fh) or {}
    except Exception:
        return derive_binding_contract(output_dir)


def binding_contract_block(output_dir: str, entity: str | None) -> str:
    """Prompt block handing the page agent the EXACT bindings for `entity`, so it
    references reality instead of guessing. Returns "" when nothing to say."""
    if not entity:
        return ""
    contract = _load_binding_contract(output_dir)
    b = contract.get(entity) or contract.get(_ent_key(entity)) or \
        next((v for k, v in contract.items() if _ent_key(k) == _ent_key(entity)), None)
    if not b:
        return ""

    lines = [f"## Data bindings for `{entity}` — use these EXACT references (never invent shorter names)"]
    for fk in b.get("fkBindings") or []:
        lines.append(
            f"- The `{fk['field']}` field is a foreign key to `{fk['targetEntity']}`. Render it as a "
            f"`Select` (or Combobox) whose page dataSource is "
            f'{{ "name": "{fk["source"]}", "entity": "{fk["targetEntity"]}", "op": "list" }} and whose '
            f'`optionsFrom` is {{ "source": "{fk["source"]}", "value": "id", "label": "{fk["labelField"]}" }}. '
            f"Do NOT abbreviate the entity name."
        )
    cw, uw = b.get("createWorkflow"), b.get("updateWorkflow")
    if cw or uw:
        parts = []
        if cw:
            parts.append(f'create → workflow `{cw}`')
        if uw:
            parts.append(f'edit → workflow `{uw}`')
        lines.append(f"- The form's submit uses: {', '.join(parts)}. Do not invent other workflow names.")
    sw = b.get("statusWorkflow")
    if sw:
        # Emit the instruction whenever a status workflow EXISTS.
        #
        # The guard used to be `if sw and sw.get("statuses")`, and the status
        # set was empty on the ordinary path (register STATUS-1, fixed in
        # Batch 13) — so the status-binding instruction was silently omitted
        # from the prompt in the common case and the agent invented its own
        # status wiring. If the legal values are still unknown, say that
        # explicitly rather than saying nothing (register BA-4).
        if sw.get("statuses"):
            lines.append(
                f"- Status transitions dispatch workflow `{sw['name']}` with args "
                f'{{ "{sw["idVar"]}": "{{{{item.id}}}}", "{sw["statusVar"]}": <one of {sw["statuses"]}> }}.'
            )
        else:
            lines.append(
                f"- Status transitions dispatch workflow `{sw['name']}` with args "
                f'{{ "{sw["idVar"]}": "{{{{item.id}}}}", "{sw["statusVar"]}": <the target status> }}. '
                f"This workflow declares no explicit status values, so use the value the "
                f"button's own label implies and do NOT invent a different variable name."
            )

    if len(lines) > 1:
        return "\n".join(lines) + "\n"

    # Say that there is nothing, rather than returning silence (register BA-11).
    #
    # An empty string is indistinguishable from "this block was never built",
    # so the agent had no signal at all and guessed bindings freely. Naming the
    # absence is strictly more information than omitting it.
    return (
        f"## Data bindings for `{entity}`\n"
        f"- No FK bindings, form workflows or status workflows were derived for this "
        f"entity. Bind ONLY to things you can see in the registry; do not invent "
        f"workflow names or dataSource slugs for it.\n"
    )
