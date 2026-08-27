"""Per-agent context assembler — injects the platform's hard contracts into the
page/form prompt so the model can't invent components, props, or field names.

Sources of truth (no drift — both are what the renderer/validators already use):
  - component prop contracts:  packages/registry/dist/component-contracts.json
        (extracted from the library's zod propsSchemas — see registry/scripts/extract-contracts.ts)
  - entity columns:            the Contract Registry passed in (registry.json), read with
        the same helper form_field_align uses.

This is the first slice of a context engine: it turns the registry from a post-hoc
validator into an up-front constraint. Most of the schema-authoring bugs (TableSortable,
`text` vs `content`, dropped `rows`, propertyName≠name, phantom fields, missing required
columns, owner-FK) come from the model not being handed these contracts.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from services.fk_semantics import _norm as _fk_norm
from services.fk_semantics import hidden_fk_columns

_CONTRACTS_JSON = (
    Path(__file__).resolve().parents[2] / "packages" / "registry" / "dist" / "component-contracts.json"
)

_SYSTEM = {"id", "createdat", "updatedat", "deletedat", "created_at", "updated_at", "deleted_at"}


@lru_cache(maxsize=1)
def _component_contracts() -> dict:
    """{ 'Table': {'caption': {'type':'string','optional':True}, 'columns': {'type':'array'}, ...}, ... }
    — each prop carries {type, enum?, optional?} (from the live zod schemas). Empty on a fresh
    clone before the registry is built — the assembler then simply omits the block. Tolerates the
    older flat {Name: [props]} shape too."""
    try:
        return json.loads(_CONTRACTS_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _fmt_prop(name: str, desc) -> str:
    """`level(1|2|3|4|5|6)?`, `caption(string)?`, `rows`, etc."""
    if not isinstance(desc, dict):
        return name  # older flat shape (just a prop name)
    seg = name
    enum = desc.get("enum")
    typ = desc.get("type")
    if enum:
        vals = "|".join(str(v) for v in enum[:10])
        seg += f"({vals})"
    elif typ and typ not in ("any", "unknown", "union", "object"):
        seg += f"({typ})"
    if desc.get("optional"):
        seg += "?"
    return seg


def component_catalog_block() -> str:
    """Authoritative allowlist: every usable component + its EXACT props, with types and the
    allowed enum values for constrained props."""
    contracts = _component_contracts()
    if not contracts:
        return ""
    lines = [
        "## ALLOWED COMPONENTS — the `type` of every node MUST be one of these, and for each "
        "component you may ONLY use the prop names listed. Any other component type, or any prop "
        "not listed for that component, is silently DROPPED by the renderer (so the UI breaks). "
        "Notation: `prop(string)` shows the prop type; `prop(a|b|c)` means the value MUST be exactly "
        "one of a/b/c; a trailing `?` marks an optional prop. Do not invent component names, prop "
        "names, or enum values.",
        "",
    ]
    for name in sorted(contracts):
        props = contracts[name]
        if isinstance(props, dict):
            parts = [_fmt_prop(p, props[p]) for p in sorted(props)]
        elif isinstance(props, list):
            parts = list(props)
        else:
            parts = []
        lines.append(f"- {name}: {', '.join(parts) if parts else '(no props)'}")
    return "\n".join(lines)


def _entity_columns(registry: dict, entity: str) -> dict:
    try:
        from services.form_field_align import _entity_columns as _read
        return _read(registry or {}, entity)
    except Exception:
        return {}


def entity_columns_block(entity_name: str, registry: dict) -> str:
    """The real columns for this page's entity — the ONLY valid field names, with
    required/role flags so the model can't rename, invent, or omit required columns."""
    cols = _entity_columns(registry or {}, entity_name)
    if not cols:
        return ""
    # Actor/tenancy FKs (server-filled) — hidden from forms; a domain FK is NOT in this set
    # and stays an editable field. Role-based via fk_semantics, name-based fallback if no
    # registry FK info is available.
    hidden = hidden_fk_columns(entity_name, registry or {})
    out = [
        f"## ENTITY `{entity_name}` — these are the ONLY valid field names. A form input's "
        f"`props.name`, and any data binding like `{{{{{entity_name[:1].lower()}{entity_name[1:]}.<field>}}}}`, "
        f"MUST use exactly one of these names. Do NOT rename (e.g. no `propertyName` for `name`) "
        f"or invent fields.",
        "",
    ]
    for name, meta in cols.items():
        meta = meta if isinstance(meta, dict) else {}
        nn = name.lower()
        typ = meta.get("type", "?")
        required = meta.get("nullable") is False or meta.get("notNull") is True
        if meta.get("primaryKey"):
            role = "primary-key — never put in a form"
        elif _fk_norm(name) in hidden:
            role = ("auto-filled FK — set automatically from the session (logged-in user / "
                    "tenant); do NOT add a form field for it")
        elif nn in _SYSTEM:
            role = "system — managed automatically; never put in a form"
        else:
            role = "editable"
        flag = "REQUIRED" if required else "optional"
        out.append(f"- {name} ({typ}, {flag}, {role})")
    out.append(
        "\nEvery REQUIRED editable column MUST have a form input. Skip primary-key, auto-filled "
        "FK, and system columns."
    )
    return "\n".join(out)


def workflow_catalog_block(output_dir: str | Path) -> str:
    """Authoritative list of the domain workflows already generated for this app,
    so the page agent references REAL workflow names instead of inventing them
    (e.g. `confirmAppointment`, which is a dead dispatch). Reads `workflows/*.json`.

    Lists domain workflows in full (name + description + required inputs) — these
    are the ones the model tends to invent — and notes that Create/Update/Delete
    <Entity> CRUD workflows also exist for every entity, without enumerating them.
    Returns "" when there are no workflows or the dir is missing.
    """
    import glob
    import os

    wdir = os.path.join(str(output_dir), "workflows")
    if not os.path.isdir(wdir):
        return ""

    domain: list[str] = []
    crud = 0
    for fp in sorted(glob.glob(os.path.join(wdir, "*.json"))):
        try:
            with open(fp, encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:  # noqa: BLE001
            continue
        name = d.get("name") or d.get("id")
        if not name:
            continue
        if re.match(r"^(Create|Update|Delete)[A-Z]", str(name)):
            crud += 1
            continue
        desc = (d.get("description") or "").strip().split("\n")[0][:120]
        req = [
            v.get("name")
            for v in (d.get("processVariables") or [])
            if isinstance(v, dict) and v.get("required") and v.get("name")
        ]
        req_s = f" — inputs: {', '.join(req)}" if req else ""
        domain.append(f'- `{name}`{(" — " + desc) if desc else ""}{req_s}')

    if not domain and not crud:
        return ""

    lines = [
        "## Existing workflows — reference ONLY these exact names",
        "The platform already generated these workflows and wires action buttons "
        "automatically, so you normally do NOT set a workflow on a button. But if "
        "you ever emit an action that names a workflow, it MUST be one of these "
        "EXACT names — NEVER invent one (an invented name like `confirmAppointment` "
        "is a dead button that does nothing).",
    ]
    if domain:
        lines.append("\nDomain workflows:")
        lines.extend(domain)
    if crud:
        lines.append(
            f"\nPlus standard CRUD workflows `Create<Entity>` / `Update<Entity>` / "
            f"`Delete<Entity>` for the app's entities ({crud} total) — the platform "
            f"wires form submits and row actions to these; you never name them."
        )
    return "\n".join(lines)


def assemble_page_context(entity_name: str | None, registry: dict | None) -> str:
    """The full injected context block for a page/form prompt."""
    blocks = [component_catalog_block()]
    if entity_name:
        blocks.append(entity_columns_block(entity_name, registry or {}))
    return "\n\n".join(b for b in blocks if b)
