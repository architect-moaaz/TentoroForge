"""Part A: CRUD workflow generation dedups singular/plural duplicate entities.

The planner/extractor sometimes emits both 'Customer' and 'Customers' (same table),
which doubled every CRUD workflow (CreateCustomer + CreateCustomers). The generator
now collapses them to one canonical (singular) workflow set.
"""
import json

from services.crud_workflow_generator import (
    _dedup_entities, _norm_entity, generate_crud_workflows,
)


def test_norm_entity_aligns_singular_and_plural():
    assert _norm_entity("Customer") == _norm_entity("Customers")
    assert _norm_entity("ServiceZone") == _norm_entity("ServiceZones")
    # distinct entities are NOT collapsed
    assert _norm_entity("Invoice") != _norm_entity("Customer")


def test_dedup_prefers_singular_when_same_table():
    entities = {
        "Customer": {"table": "customers", "fields": []},
        "Customers": {"table": "customers", "fields": []},
        "Invoice": {"table": "invoices", "fields": []},
    }
    canonical = dict(_dedup_entities(entities, real_tables={}))
    assert "Customer" in canonical          # singular kept
    assert "Customers" not in canonical     # plural dropped
    assert "Invoice" in canonical           # unique entity untouched
    assert len(canonical) == 2


def test_different_tables_are_not_merged():
    # same normalized base but genuinely different tables -> keep both
    entities = {
        "Status": {"table": "statuses", "fields": []},
        "Statu": {"table": "statu", "fields": []},
    }
    canonical = dict(_dedup_entities(entities, real_tables={}))
    assert len(canonical) == 2


def test_generate_crud_emits_no_duplicate_files(tmp_path):
    plan = {"entities": {
        "Customer": {"table": "customers", "fields": [{"name": "name", "type": "string"}]},
        "Customers": {"table": "customers", "fields": [{"name": "name", "type": "string"}]},
    }}
    written = generate_crud_workflows(plan, str(tmp_path))
    # one set of CRUD ops for the single canonical entity, no plural variants
    assert set(written) == {"CreateCustomer", "UpdateCustomer", "DeleteCustomer"}
    files = {p.name for p in (tmp_path / "workflows").glob("*.json")}
    assert "CreateCustomers.json" not in files
    assert json.loads((tmp_path / "workflows" / "CreateCustomer.json").read_text())["name"] == "CreateCustomer"
