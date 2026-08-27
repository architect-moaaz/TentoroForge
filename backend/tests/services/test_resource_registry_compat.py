"""Phase 5 compat tests — resource_registry re-exports produce the same
output as the legacy modules for representative inputs.

Extract-then-adapt: legacy import paths stay alive AND resource_registry
becomes the canonical import surface. This suite guards both invariants.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import resource_registry as rr


# ---------------------------------------------------------------------------
# Legacy imports still resolve (back-compat is not broken)
# ---------------------------------------------------------------------------

def test_legacy_registry_module_imports():
    from services import registry  # noqa: F401
    from services.registry import (  # noqa: F401
        create_registry, load_registry, save_registry,
        merge_section, reconcile_entities, registry_summary_for_agent,
    )


def test_legacy_registry_validator_imports():
    from services import registry_validator  # noqa: F401
    from services.registry_validator import (  # noqa: F401
        RegistryError, fuzzy_match, validate_registry, format_validation_report,
    )


def test_legacy_registry_extractor_imports():
    from services import registry_extractor  # noqa: F401
    from services.registry_extractor import (  # noqa: F401
        extract_entities_from_schema, extract_routes_from_files,
        extract_components_from_files, extract_pages_from_files,
        extract_schema_pages_from_json,
    )


def test_legacy_registry_repair_imports():
    from services import registry_repair  # noqa: F401
    from services.registry_repair import auto_fix_mismatches  # noqa: F401


def test_legacy_plan_field_lookup_imports():
    from services import plan_field_lookup  # noqa: F401
    from services.plan_field_lookup import (  # noqa: F401
        load_plan, get_entity, get_field, get_enum_values, get_enum_options,
        get_fk, get_semantic_type, get_lifecycle_status, get_default_value,
        get_not_null, title_case_key,
    )


def test_legacy_entity_completeness_imports():
    from services import entity_completeness  # noqa: F401
    from services.entity_completeness import (  # noqa: F401
        ensure_media_fields, entity_needs_media,
    )


# ---------------------------------------------------------------------------
# Re-exports are the SAME OBJECT (not a shadow copy)
# ---------------------------------------------------------------------------

def test_contract_registry_reexports_are_identical():
    from services import registry as legacy
    assert rr.create_registry is legacy.create_registry
    assert rr.load_registry is legacy.load_registry
    assert rr.save_registry is legacy.save_registry
    assert rr.merge_section is legacy.merge_section
    assert rr.reconcile_entities is legacy.reconcile_entities
    assert rr.registry_summary_for_agent is legacy.registry_summary_for_agent


def test_validator_reexports_are_identical():
    from services import registry_validator as legacy
    assert rr.RegistryError is legacy.RegistryError
    assert rr.fuzzy_match is legacy.fuzzy_match
    assert rr.validate_contract_registry is legacy.validate_registry
    assert rr.format_validation_report is legacy.format_validation_report


def test_extractor_reexports_are_identical():
    from services import registry_extractor as legacy
    assert rr.extract_entities_from_schema is legacy.extract_entities_from_schema
    assert rr.extract_routes_from_files is legacy.extract_routes_from_files
    assert rr.extract_components_from_files is legacy.extract_components_from_files
    assert rr.extract_pages_from_files is legacy.extract_pages_from_files
    assert rr.extract_schema_pages_from_json is legacy.extract_schema_pages_from_json


def test_repair_reexports_are_identical():
    from services import registry_repair as legacy
    assert rr.auto_fix_mismatches is legacy.auto_fix_mismatches


def test_plan_field_lookup_reexports_are_identical():
    from services import plan_field_lookup as legacy
    assert rr.load_plan is legacy.load_plan
    assert rr.get_entity is legacy.get_entity
    assert rr.get_field is legacy.get_field
    assert rr.get_enum_values is legacy.get_enum_values
    assert rr.get_enum_options is legacy.get_enum_options
    assert rr.get_fk is legacy.get_fk
    assert rr.get_semantic_type is legacy.get_semantic_type
    assert rr.get_not_null is legacy.get_not_null
    assert rr.get_default_value is legacy.get_default_value
    assert rr.get_lifecycle_status is legacy.get_lifecycle_status
    assert rr.title_case_key is legacy.title_case_key


def test_entity_completeness_reexports_are_identical():
    from services import entity_completeness as legacy
    assert rr.ensure_media_fields is legacy.ensure_media_fields
    assert rr.entity_needs_media is legacy.entity_needs_media


# ---------------------------------------------------------------------------
# Behavioral parity — resource_registry.<fn>(x) == legacy.<fn>(x)
# ---------------------------------------------------------------------------

SIMPLE_PLAN = {
    "data_models": [
        {
            "name": "Project",
            "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True, "nullable": False},
                {"name": "title", "type": "varchar", "nullable": False},
                {"name": "status", "type": "varchar",
                 "enum_values": ["open", "in_progress", "closed"]},
                {"name": "ownerId", "type": "uuid", "nullable": False},
            ],
            "indexes": ["title"],
        },
        {
            "name": "Task",
            "fields": [
                {"name": "id", "type": "uuid", "primaryKey": True, "nullable": False},
                {"name": "title", "type": "varchar", "nullable": False},
                {"name": "projectId", "type": "uuid", "nullable": False,
                 "fk": {"table": "projects", "column": "id"}},
                {"name": "priority", "type": "integer"},
            ],
        },
    ],
    "relations": [
        {"from": "Task", "to": "Project", "type": "many-to-one",
         "foreignKey": "projectId"},
    ],
    "api_routes": [
        {"method": "GET", "path": "/api/projects", "entity": "Project"},
    ],
    "components": [],
    "pages": [
        {"route": "/projects", "file": "src/app/projects/page.tsx",
         "components": ["ProjectList"], "api_calls": ["/api/projects"]},
    ],
    "workflows": [
        {"steps": [{"name": "review", "page": "/projects", "variables": {}}]},
    ],
}


def test_create_registry_parity():
    from services import registry as legacy
    a = rr.create_registry(SIMPLE_PLAN)
    b = legacy.create_registry(SIMPLE_PLAN)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_build_canonical_registry_deterministic():
    a = rr.build_canonical_registry(SIMPLE_PLAN)
    b = rr.build_canonical_registry(SIMPLE_PLAN)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    # Sanity: both entities present with a stable id key.
    assert set(a["entities"].keys()) == {"Project", "Task"}


def test_validate_contract_registry_parity():
    from services import registry_validator as legacy
    reg = rr.create_registry(SIMPLE_PLAN)
    # Introduce a dangling ref so validator has something to say.
    reg["relations"].append({
        "from_entity": "Task", "to_entity": "NoSuchEntity",
        "type": "many-to-one", "foreignKey": "x",
    })
    a = rr.validate_contract_registry(reg)
    b = legacy.validate_registry(reg)
    assert [(e.section, e.name, e.error) for e in a] == \
           [(e.section, e.name, e.error) for e in b]
    assert any(e.section == "relations" and "NoSuchEntity" in e.error for e in a)


def test_format_validation_report_parity():
    from services import registry_validator as legacy
    reg = rr.create_registry(SIMPLE_PLAN)
    reg["relations"].append({
        "from_entity": "Task", "to_entity": "NoSuchEntity",
        "type": "many-to-one", "foreignKey": "x",
    })
    errs = rr.validate_contract_registry(reg)
    assert rr.format_validation_report(errs) == legacy.format_validation_report(errs)


def test_registry_summary_for_agent_parity():
    from services import registry as legacy
    reg = rr.create_registry(SIMPLE_PLAN)
    a = rr.registry_summary_for_agent(reg, ["entities", "relations", "pages"])
    b = legacy.registry_summary_for_agent(reg, ["entities", "relations", "pages"])
    assert a == b
    assert "Project" in a
    assert "Task" in a


def test_fuzzy_match_parity():
    from services import registry_validator as legacy
    cands = ["Project", "Task", "Reservation"]
    for query in ["Projeect", "Reservayion", "totally-unrelated"]:
        assert rr.fuzzy_match(query, cands) == legacy.fuzzy_match(query, cands)


def test_load_and_save_registry_roundtrip(tmp_path: Path):
    from services import registry as legacy
    reg = rr.create_registry(SIMPLE_PLAN)
    rr.save_registry(str(tmp_path), reg)
    loaded_via_rr = rr.load_registry(str(tmp_path))
    loaded_via_legacy = legacy.load_registry(str(tmp_path))
    assert loaded_via_rr == loaded_via_legacy
    # Content survives roundtrip.
    assert set(loaded_via_rr["entities"].keys()) == {"Project", "Task"}


def test_merge_section_parity():
    from services import registry as legacy
    reg = rr.create_registry(SIMPLE_PLAN)
    entries = {"Widget": {"file": "src/components/Widget.tsx",
                          "props": {}, "api_calls": [], "field_refs": []}}
    a = rr.merge_section(reg, "components", entries)
    b = legacy.merge_section(reg, "components", entries)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    assert "Widget" in a["components"]


def test_reconcile_entities_parity():
    from services import registry as legacy
    reg = rr.create_registry(SIMPLE_PLAN)
    # Extractor keys entities by Pascalized TABLE name (plural).
    extracted = {
        "Projects": {
            "fields": {
                "id": {"type": "uuid", "primaryKey": True, "nullable": False},
                "title": {"type": "varchar", "nullable": False,
                          "hasDefault": False, "unique": True},
            },
            "indexes": ["title"],
        },
    }
    a = rr.reconcile_entities(reg, extracted)
    b = legacy.reconcile_entities(reg, extracted)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    # The extracted metadata folded onto the plan key "Project" (singular).
    assert a["entities"]["Project"]["fields"]["title"].get("unique") is True


# ---------------------------------------------------------------------------
# Plan-field lookup parity
# ---------------------------------------------------------------------------

def test_plan_field_lookup_parity(tmp_path: Path):
    from services import plan_field_lookup as legacy

    plan = {
        "data_models": [
            {
                "name": "Ticket",
                "fields": [
                    {"name": "status", "type": "varchar",
                     "enum_values": ["open", {"key": "in_progress",
                                              "label": "In Progress"}, "closed"],
                     "lifecycle_status": True, "default_value": "open"},
                    {"name": "assigneeId", "type": "uuid",
                     "fk": {"table": "users", "column": "id"}, "nullable": False},
                    {"name": "notes", "type": "text", "semantic_type": "richtext"},
                ],
            }
        ]
    }

    # Persist a plan.json so load_plan() has something to read.
    (tmp_path / "src" / "contracts").mkdir(parents=True)
    (tmp_path / "src" / "contracts" / "plan.json").write_text(json.dumps(plan))

    # Bust plan_field_lookup's mtime cache to avoid cross-test pollution.
    legacy._CACHE.clear()

    p1 = rr.load_plan(str(tmp_path))
    legacy._CACHE.clear()
    p2 = legacy.load_plan(str(tmp_path))
    assert p1 == p2 == plan

    # get_enum_values keys-only
    assert rr.get_enum_values(plan, "Ticket", "status") == \
           legacy.get_enum_values(plan, "Ticket", "status") == \
           ["open", "in_progress", "closed"]

    # get_enum_options uses authored label when present, else title-cases.
    opts = rr.get_enum_options(plan, "Ticket", "status")
    assert opts == legacy.get_enum_options(plan, "Ticket", "status")
    assert {"value": "in_progress", "label": "In Progress"} in opts
    assert {"value": "open", "label": "Open"} in opts

    # get_fk resolves the FK target.
    assert rr.get_fk(plan, "Ticket", "assigneeId") == \
           legacy.get_fk(plan, "Ticket", "assigneeId") == \
           {"table": "users", "column": "id"}

    # get_semantic_type, get_lifecycle_status, get_default_value, get_not_null.
    assert rr.get_semantic_type(plan, "Ticket", "notes") == "richtext"
    assert rr.get_lifecycle_status(plan, "Ticket", "status") is True
    assert rr.get_default_value(plan, "Ticket", "status") == "open"
    assert rr.get_not_null(plan, "Ticket", "assigneeId") is True

    # title_case_key snake / kebab / camel.
    assert rr.title_case_key("in_progress") == legacy.title_case_key("in_progress") == "In Progress"
    assert rr.title_case_key("credit-card") == "Credit Card"


# ---------------------------------------------------------------------------
# Media completeness parity
# ---------------------------------------------------------------------------

def test_ensure_media_fields_parity():
    from services import entity_completeness as legacy
    plan_a = {
        "entities": {
            "Plant": {"fields": [{"name": "name", "type": "varchar"}]},
            "Invoice": {"fields": [{"name": "amount", "type": "numeric"}]},
        }
    }
    import copy
    plan_b = copy.deepcopy(plan_a)
    a = rr.ensure_media_fields(plan_a)
    b = legacy.ensure_media_fields(plan_b)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    # Plant gets a photoUrl injected; Invoice does not.
    plant_fields = [f["name"] for f in a["entities"]["Plant"]["fields"]]
    invoice_fields = [f["name"] for f in a["entities"]["Invoice"]["fields"]]
    assert "photoUrl" in plant_fields
    assert "photoUrl" not in invoice_fields


def test_entity_needs_media_parity():
    from services import entity_completeness as legacy
    spec = {"fields": [{"name": "title", "type": "varchar"}]}
    assert rr.entity_needs_media("Plant", spec) is True
    assert rr.entity_needs_media("Plant", spec) == \
           legacy.entity_needs_media("Plant", spec)
    assert rr.entity_needs_media("Invoice", spec) is False


# ---------------------------------------------------------------------------
# Registry-from-code extractors — run against a synthesized project tree
# ---------------------------------------------------------------------------

def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def test_extract_entities_from_schema_parity(tmp_path: Path):
    from services import registry_extractor as legacy
    _write(tmp_path / "src" / "db" / "schema" / "projects.ts", '''
import { pgTable, uuid, varchar, timestamp } from "drizzle-orm/pg-core";

export const projects = pgTable("projects", {
  id: uuid("id").primaryKey().defaultRandom(),
  title: varchar("title", { length: 255 }).notNull(),
  createdAt: timestamp("created_at").notNull().defaultNow(),
});
''')
    a = rr.extract_entities_from_schema(str(tmp_path))
    b = legacy.extract_entities_from_schema(str(tmp_path))
    assert a == b
    assert "Projects" in a
    assert a["Projects"]["fields"]["title"]["nullable"] is False
    assert a["Projects"]["fields"]["createdAt"].get("hasDefault") is True


def test_extract_routes_from_files_parity(tmp_path: Path):
    from services import registry_extractor as legacy
    _write(tmp_path / "src" / "app" / "api" / "projects" / "route.ts",
           "export async function GET() {}\nexport async function POST() {}\n")
    a = rr.extract_routes_from_files(str(tmp_path))
    b = legacy.extract_routes_from_files(str(tmp_path))
    assert a == b
    assert "GET /api/projects" in a
    assert "POST /api/projects" in a


def test_extract_pages_from_files_parity(tmp_path: Path):
    from services import registry_extractor as legacy
    _write(tmp_path / "src" / "app" / "projects" / "page.tsx", '''
import { ProjectList } from "@/components/ProjectList";
export default function Page() { return <ProjectList/>; }
''')
    a = rr.extract_pages_from_files(str(tmp_path))
    b = legacy.extract_pages_from_files(str(tmp_path))
    assert a == b
    assert "/projects" in a
    assert "ProjectList" in a["/projects"]["components"]
