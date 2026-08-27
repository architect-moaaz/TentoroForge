"""Canonical Resource Registry — one deterministic record per entity.

Built once from the plan after planning. Owns every entity's name family
(via the single ``name_normalizer``) plus its relationships and interactions,
so no downstream generator derives names independently.

``build_canonical_registry(plan)`` returns a deterministic dict:

    {
      "version": 1,
      "entities": {
         "<PascalName>": { **name_family, "columns": [...], "fks": [...] }
      },
      "relationships": [{"from","to","type","fkColumn"}],
      "interactions": [{"id","sourcePage","trigger","label","workflowId",
                        "targetEntityId","inputMap"}],
      "roles": []
    }
"""

import json
import logging
import os
from typing import Any

import re

from services.name_normalizer import name_family, to_singular

logger = logging.getLogger(__name__)

# Tables the auth foundation owns — a plan entity mapping here keeps table
# "users" (auth owns the schema) but MUST still appear in the registry.
RESERVED_TABLES = {"users"}


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _normalize_models(data_models: Any) -> list[dict]:
    """Accept ``data_models`` as a LIST of ``{"name", ...}`` dicts OR a legacy
    DICT keyed by name; return a list of dicts each carrying ``name`` (folding
    the key in for the dict form). Mirrors the readers in
    ``contract_generator`` / ``schema_builder`` so both plan shapes work."""
    if isinstance(data_models, dict):
        out: list[dict] = []
        for nm, spec in data_models.items():
            if isinstance(spec, dict):
                model = dict(spec)
                model.setdefault("name", nm)
            else:
                model = {"name": nm, "fields": spec or []}
            out.append(model)
        return out
    if isinstance(data_models, list):
        return [m for m in data_models if isinstance(m, dict) and m.get("name")]
    return []


def _plan_models(plan: dict) -> list[dict]:
    """Canonical entity/model source with legacy fallback."""
    return _normalize_models(plan.get("data_models") or plan.get("entities") or [])


def _rel_get(rel: dict, *keys: str):
    for k in keys:
        v = rel.get(k)
        if v:
            return v
    return None


def _column_enum(field: dict):
    ev = field.get("enum_values") or field.get("enum")
    if isinstance(ev, list) and ev:
        return list(ev)
    return None


def build_canonical_registry(plan: dict) -> dict:
    """Compute the canonical registry from a plan. Deterministic; never raises
    on a malformed entity (skips and continues)."""
    plan = plan or {}
    models = _plan_models(plan)

    # entity display-name → stable id (kebab-singular). Reserved User keeps
    # table "users" but still gets a normal id.
    name_to_id: dict[str, str] = {}
    fam_by_name: dict[str, dict] = {}
    for model in models:
        try:
            nm = model.get("name")
            if not nm:
                continue
            hint = model.get("table")
            # Reserved: a User entity keeps table "users" (auth owns it).
            if not hint and to_singular(nm) == "user":
                hint = "users"
            fam = name_family(nm, table_hint=hint)
            name_to_id[nm] = fam["id"]
            fam_by_name[nm] = fam
        except Exception as e:  # never raise on a malformed entity
            logger.warning("resource_registry: skipping entity %r: %s", model, e)
            continue

    # relations: {from,to,type,foreignKey} — map PascalCase names → entity ids.
    relations: list[dict] = []
    for rel in (plan.get("relations") or []):
        if not isinstance(rel, dict):
            continue
        frm = _rel_get(rel, "from", "fromEntity", "source", "parent")
        to = _rel_get(rel, "to", "toEntity", "target", "child")
        fk = _rel_get(rel, "foreignKey", "fk", "foreign_key", "field", "column")
        rtype = _rel_get(rel, "type", "relation", "kind") or "many-to-one"
        if not frm or not to:
            continue
        relations.append({
            "from_name": str(frm),
            "to_name": str(to),
            "type": str(rtype),
            "fkColumn": str(fk) if fk else None,
        })

    # per-entity fk lookup: (entityName, column) → targetEntityId
    fk_target: dict[tuple, str] = {}
    for rel in relations:
        tgt_id = name_to_id.get(rel["to_name"])
        if rel["fkColumn"] and tgt_id:
            fk_target[(rel["from_name"], rel["fkColumn"])] = tgt_id

    entities: dict[str, dict] = {}
    for nm, fam in fam_by_name.items():
        model = next((m for m in models if m.get("name") == nm), {})
        columns: list[dict] = []
        fks: list[dict] = []
        for field in (model.get("fields") or []):
            if not isinstance(field, dict) or not field.get("name"):
                continue
            col_name = field["name"]
            nullable = field.get("nullable")
            not_null = bool(nullable is False or field.get("notNull") or field.get("required"))
            fk_tgt = fk_target.get((nm, col_name))
            columns.append({
                "name": col_name,
                "type": field.get("type", "varchar"),
                "notNull": not_null,
                "fk": fk_tgt,
                "enum": _column_enum(field),
            })
            if fk_tgt:
                fks.append({"column": col_name, "targetEntityId": fk_tgt})
        entity_rec = {**fam, "columns": columns, "fks": fks}
        # Slice-3 ledger contract: propagate ``lifecycle`` into the registry
        # so downstream readers (form_scaffold, ensure_edit_routes, record
        # composer, api guards) don't have to re-parse the plan. Only
        # ``append_only`` is stored (crud/unset is the historical default);
        # keeping it explicit at the registry level means the plan is the
        # single source of truth for this flag.
        lifecycle = model.get("lifecycle")
        if isinstance(lifecycle, str) and lifecycle.strip():
            entity_rec["lifecycle"] = lifecycle.strip()
        entities[nm] = entity_rec

    # relationships (ids), sorted by (from, to, fkColumn)
    relationships: list[dict] = []
    for rel in relations:
        frm_id = name_to_id.get(rel["from_name"])
        to_id = name_to_id.get(rel["to_name"])
        if not frm_id or not to_id:
            continue
        relationships.append({
            "from": frm_id,
            "to": to_id,
            "type": rel["type"],
            "fkColumn": rel["fkColumn"],
        })
    relationships.sort(key=lambda r: (r["from"], r["to"], r["fkColumn"] or ""))

    # ── RBAC (Theme C): roles + a persisted, FK-targetable User entity ──
    access = plan.get("access_control") or {}
    roles = [str(r).strip() for r in (access.get("roles") or [])
             if isinstance(r, str) and str(r).strip()]
    rules = [str(x).strip() for x in (access.get("rules") or [])
             if isinstance(x, (str,)) and str(x).strip()]

    # Does the registry already carry a User entity (a plan model mapped to the
    # reserved users table, e.g. from the C-1 planner normalizer)?
    def _is_user_entity(rec: dict) -> bool:
        return _norm(rec.get("table")) == "users" or _norm(rec.get("id")) == "user"

    user_id: str | None = next(
        (rec.get("id") for rec in entities.values() if _is_user_entity(rec)), None)

    # An actor FK targets the User entity when a relation points at it.
    targets_user = any(
        _norm(rel.get("to_name")) == "user" or
        (name_to_id.get(rel["to_name"]) and
         _norm(name_to_id.get(rel["to_name"])) == "user")
        for rel in relations)

    # Ensure a User entity exists whenever the app has an access model or an FK
    # targeting a user — auth owns the physical `users` table, but FK targets must
    # resolve here. Non-RBAC apps (no roles, no user-targeted FK) are untouched.
    if user_id is None and (roles or targets_user):
        fam = name_family("User", table_hint="users")
        columns = [
            {"name": "id", "type": "uuid", "notNull": True, "fk": None, "enum": None},
            {"name": "name", "type": "varchar", "notNull": False, "fk": None, "enum": None},
            {"name": "email", "type": "varchar", "notNull": True, "fk": None, "enum": None},
            {"name": "role", "type": "varchar", "notNull": False, "fk": None,
             "enum": list(roles) or None},
        ]
        entities["User"] = {**fam, "columns": columns, "fks": []}
        user_id = fam["id"]

    access_model = {
        "roles": roles,
        "rules": rules,
        "userEntityId": user_id,
        "ownership": "role-based",
    }

    entity_ids = set(name_to_id.values())
    # route → entity id (route may be a slug/kebab; match against id or slug)
    route_to_entity: dict[str, str] = {}
    for fam in fam_by_name.values():
        route_to_entity[fam["id"]] = fam["id"]
        route_to_entity[fam["slug"]] = fam["id"]

    def _infer_target(page_entity: str | None, workflow: str | None) -> str | None:
        if page_entity:
            return page_entity
        if workflow:
            wl = str(workflow).lower()
            # longest id match wins (avoid "log" matching before "maintenance-log")
            for eid in sorted(entity_ids, key=len, reverse=True):
                compact = eid.replace("-", "")
                if compact and compact in wl:
                    return eid
        return None

    interactions: list[dict] = []
    for page in (plan.get("pages") or []):
        if not isinstance(page, dict):
            continue
        route = page.get("route") or page.get("path") or ""
        page_entity = route_to_entity.get(str(route).strip("/"))
        for action in (page.get("actions") or []):
            if not isinstance(action, dict):
                continue
            label = action.get("label") or ""
            workflow = action.get("workflow")
            interactions.append({
                "id": to_singular(str(label).replace(" ", "")) if label else "",
                "sourcePage": str(route),
                "trigger": action.get("kind"),
                "label": label,
                "workflowId": workflow,
                "targetEntityId": _infer_target(page_entity, workflow),
                "inputMap": action.get("input_map") or {},
            })
    interactions.sort(key=lambda i: i["id"])

    return {
        "version": 1,
        "entities": dict(sorted(entities.items())),
        "relationships": relationships,
        "interactions": interactions,
        "roles": roles,
        "accessModel": access_model,
    }


def write_registry(registry: dict, output_dir: str) -> str:
    """Persist ``registry`` to ``<output_dir>/contracts/resource-registry.json``.

    Serialized with ``indent=2, sort_keys=True`` so identical registries produce
    byte-identical files (deterministic). Creates ``contracts/`` if missing and
    returns the written path.
    """
    contracts_dir = os.path.join(output_dir, "contracts")
    os.makedirs(contracts_dir, exist_ok=True)
    path = os.path.join(contracts_dir, "resource-registry.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(registry, indent=2, sort_keys=True))
    return path


# ---------------------------------------------------------------------------
# Canonical aggregation surface (Phase 5 — naming authority collapse)
# ---------------------------------------------------------------------------
#
# Historically the registry subsystem grew as 7 sibling modules — each with its
# own callers, each importing from the others. This surface re-exports every
# public API through one canonical name so the whole pipeline can migrate to
# ``from services.resource_registry import X`` and the legacy modules can be
# folded away once their caller counts hit zero (extract-then-adapt).
#
# The legacy modules remain the implementation for now — moving code carries
# more risk than value in a single pass, and every legacy import path stays
# alive so existing callers are undisturbed. New callers should import from
# here.
#
# See ``docs/superpowers/plans/2026-08-12-pipeline-cleanup.md`` (Phase 5).

# — Contract Registry (services.registry) ————————————————————————————
from services.registry import (  # noqa: E402,F401
    ContractRegistry,
    EntityInfo,
    FieldInfo,
    PageInfo,
    Relation,
    RouteInfo,
    ComponentInfo,
    WorkflowBinding,
    RuleInfo,
    create_registry,
    load_registry,
    save_registry,
    merge_section,
    reconcile_entities,
    registry_summary_for_agent,
    enrich_entity_names,
)

# — Cross-reference validation (services.registry_validator) ————————————
from services.registry_validator import (  # noqa: E402,F401
    RegistryError,
    fuzzy_match,
    validate_registry as validate_contract_registry,
    format_validation_report,
)

# — Post-hoc code extraction (services.registry_extractor) ————————————
from services.registry_extractor import (  # noqa: E402,F401
    extract_entities_from_schema,
    extract_routes_from_files,
    extract_components_from_files,
    extract_pages_from_files,
    extract_schema_pages_from_json,
)

# — Auto-repair helpers (services.registry_repair) ————————————————————
from services.registry_repair import (  # noqa: E402,F401
    auto_fix_mismatches,
)

# — Plan-authored field lookups (services.plan_field_lookup) ————————————
from services.plan_field_lookup import (  # noqa: E402,F401
    load_plan,
    get_entity,
    get_field,
    get_enum_values,
    get_enum_options,
    get_fk,
    get_semantic_type,
    get_lifecycle_status,
    get_default_value,
    get_not_null,
    title_case_key,
)

# — Media-completeness (services.entity_completeness — registry-overlap only) —
# ensure_media_fields walks plan entities and adds a photoUrl field where the
# name/brief demands one. The media-heuristic core stays in entity_completeness
# (its vocabulary + planner hooks are not registry logic); this is the one
# entry-point the pipeline calls, so it's the only piece re-exported here.
from services.entity_completeness import (  # noqa: E402,F401
    ensure_media_fields,
    entity_needs_media,
)


__all__ = [
    # Canonical registry (this module)
    "build_canonical_registry",
    "write_registry",
    "RESERVED_TABLES",
    # Contract registry
    "ContractRegistry",
    "EntityInfo",
    "FieldInfo",
    "PageInfo",
    "Relation",
    "RouteInfo",
    "ComponentInfo",
    "WorkflowBinding",
    "RuleInfo",
    "create_registry",
    "load_registry",
    "save_registry",
    "merge_section",
    "reconcile_entities",
    "registry_summary_for_agent",
    "enrich_entity_names",
    # Validation
    "RegistryError",
    "fuzzy_match",
    "validate_contract_registry",
    "format_validation_report",
    # Extractors
    "extract_entities_from_schema",
    "extract_routes_from_files",
    "extract_components_from_files",
    "extract_pages_from_files",
    "extract_schema_pages_from_json",
    # Repair
    "auto_fix_mismatches",
    # Plan-field lookup
    "load_plan",
    "get_entity",
    "get_field",
    "get_enum_values",
    "get_enum_options",
    "get_fk",
    "get_semantic_type",
    "get_lifecycle_status",
    "get_default_value",
    "get_not_null",
    "title_case_key",
    # Media completeness
    "ensure_media_fields",
    "entity_needs_media",
]
