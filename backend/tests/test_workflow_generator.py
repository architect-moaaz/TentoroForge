"""Cross-generator table-name AGREEMENT: the workflow generator and the schema
builder must name the SAME table for the SAME entity, both via the canonical
resource registry.

The live bug this closes: a plan hints entity ``Equipment`` → table ``equipment``.
The schema builder honors the hint and emits ``pgTable("equipment", ...)``, but the
workflow generator independently pluralized ``Equipment`` → ``equipments`` (via
``_to_table``) for its ``db_insert`` config, so the runtime threw
``[workflow:CreateEquipment] unknown table``. The registry is now the single
naming authority both generators read.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from services.resource_registry import build_canonical_registry
from services.schema_builder import build_schema_files
from services.workflow_generator import _resolve_table, generate_workflow_definitions


def _equipment_plan() -> dict:
    """Entity WITH a table hint (`equipment`, an uncountable noun) + a workflow
    whose create step targets it."""
    return {
        "data_models": [
            {
                "name": "Equipment",
                "table": "equipment",
                "fields": [
                    {"name": "name", "type": "varchar"},
                    {"name": "status", "type": "varchar"},
                ],
            },
        ],
        "workflows": [
            {
                "name": "CreateEquipment",
                "description": "Create a new Equipment record",
                "steps": ["Create Equipment"],
            },
        ],
    }


def _schema_pgtable_name(schema_out: Path, slug: str) -> str:
    """The pgTable(...) name the schema builder emitted for `slug`.ts."""
    text = (schema_out / "src" / "db" / "schema" / f"{slug}.ts").read_text(encoding="utf-8")
    m = re.search(r'pgTable\(\s*["\']([A-Za-z0-9_]+)["\']', text)
    assert m, f"no pgTable(...) found in {slug}.ts"
    return m.group(1)


def _workflow_insert_table(wf_out: Path) -> str:
    """The db_insert config.table the workflow generator emitted."""
    for jf in (wf_out / "workflows").glob("*.json"):
        defn = json.loads(jf.read_text(encoding="utf-8"))
        for node in defn.get("definition", {}).get("nodes", []):
            cfg = (node.get("data") or {}).get("config") or {}
            if cfg.get("actionType") == "db_insert":
                return cfg.get("table", "")
    raise AssertionError("no db_insert node with a table found in generated workflows")


def test_schema_and_workflow_agree_on_hinted_table(tmp_path):
    """THE agreement test: schema and workflow name the SAME hinted table.

    Fails before the registry-first fix (workflow resolves ``equipments`` via
    ``_to_table`` while the schema emits ``equipment``); passes after.
    """
    plan = _equipment_plan()

    schema_out = tmp_path / "schema_app"
    schema_out.mkdir()
    build_schema_files(plan, str(schema_out))
    schema_table = _schema_pgtable_name(schema_out, "equipment")

    # Generate workflows in a SEPARATE dir so no schema files are present — this
    # forces resolution through the registry (not the schema-file scan fallback),
    # exactly the seam the live bug lives in.
    wf_out = tmp_path / "wf_app"
    wf_out.mkdir()
    generate_workflow_definitions(str(wf_out), plan)
    workflow_table = _workflow_insert_table(wf_out)

    assert schema_table == workflow_table == "equipment"


def test_unhinted_entity_still_pluralizes(tmp_path):
    """No hint → registry == old behavior: RecruitmentDrive → recruitmentDrives,
    and schema + workflow still agree (no regression on the common case)."""
    plan = {
        "data_models": [
            {
                "name": "RecruitmentDrive",
                "fields": [
                    {"name": "title", "type": "varchar"},
                    {"name": "status", "type": "varchar"},
                ],
            },
        ],
        "workflows": [
            {
                "name": "CreateRecruitmentDrive",
                "description": "Create a new RecruitmentDrive",
                "steps": ["Create RecruitmentDrive"],
            },
        ],
    }

    schema_out = tmp_path / "schema_app"
    schema_out.mkdir()
    build_schema_files(plan, str(schema_out))
    schema_table = _schema_pgtable_name(schema_out, "recruitment-drives")

    wf_out = tmp_path / "wf_app"
    wf_out.mkdir()
    generate_workflow_definitions(str(wf_out), plan)
    workflow_table = _workflow_insert_table(wf_out)

    assert schema_table == workflow_table == "recruitmentDrives"


def test_registry_is_primary_authority_over_schema_scan():
    """Given a registry, _resolve_table returns the registry table even when the
    schema-file scan would have matched a different (pluralized) name."""
    registry = build_canonical_registry(_equipment_plan())
    # table_names deliberately WRONG (the drifted plural) — registry must win.
    assert _resolve_table("Equipment", ["equipments"], registry=registry) == "equipment"


def test_registry_absent_entity_falls_back_cleanly():
    """A token not in the registry falls back to the old behavior without crashing:
    schema-scan match first, then camelCase _to_table."""
    registry = build_canonical_registry(_equipment_plan())  # only knows Equipment
    # Present in the schema scan → returned verbatim.
    assert _resolve_table("Ghost", ["ghosts"], registry=registry) == "ghosts"
    # Nothing to match → camelCase fallback, no crash.
    assert _resolve_table("Ghost", [], registry=registry) == "ghosts"
    # No registry at all → unchanged legacy behavior.
    assert _resolve_table("Ghost", [], registry=None) == "ghosts"
