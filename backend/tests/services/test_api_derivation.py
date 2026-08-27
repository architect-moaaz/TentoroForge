"""Endpoints follow from the Blueprint; nobody designs them.

The `apis` agent produced ~40 endpoints for $0.40 and failed contract
validation, when every one of them was recoverable from artifacts that already
existed. These tests pin the derivation and the two §75 edges it makes true by
construction.
"""
import pytest

from services.blueprint.api_derivation import apply_derived_apis, derive_apis
from services.blueprint.service import BlueprintService
from services.blueprint.verification import verify


def doc(**over):
    base = {
        "schemaVersion": "1", "version": 1, "state": "IMPLEMENTATION",
        "application": {"id": "a", "name": "R", "domain": "ATS"},
        "data": {"entities": [
            {"id": "ENTITY-001", "name": "Candidate", "table": "candidates",
             "fields": [{"name": "id", "type": "uuid"}]},
            {"id": "ENTITY-002", "name": "JobRole", "table": "job_roles"},
        ]},
    }
    base.update(over)
    return base


def paths(apis):
    return {(a["method"], a["path"]) for a in apis}


# --- reads come from the data engine ---------------------------------------

def test_every_entity_gets_a_list_and_a_fetch():
    got = paths(derive_apis(doc()))
    assert ("GET", "/api/candidates") in got
    assert ("GET", "/api/candidates/{id}") in got
    assert ("GET", "/api/job-roles") in got, "camelCase pluralises to a slug"


def test_pluralisation_is_deterministic():
    a = derive_apis(doc())
    b = derive_apis(doc())
    assert [x["path"] for x in a] == [x["path"] for x in b]


# --- mutations come from workflows -----------------------------------------

def test_a_workflow_step_that_writes_an_entity_implies_its_endpoints():
    d = doc(workflows=[{"id": "FLOW-001", "name": "Advance candidate",
                        "trigger": {"kind": "event"},
                        "steps": [{"key": "s", "name": "save", "type": "action",
                                   "entity": "ENTITY-001"}]}])
    got = paths(derive_apis(d))
    assert ("POST", "/api/candidates") in got
    assert ("PUT", "/api/candidates/{id}") in got


def test_a_manual_workflow_gets_a_launch_endpoint():
    d = doc(workflows=[{"id": "FLOW-001", "name": "Advance candidate",
                        "trigger": {"kind": "manual"}}])
    assert any(a["path"].startswith("/api/workflows/") for a in derive_apis(d))


def test_a_non_mutating_step_implies_nothing():
    d = doc(workflows=[{"id": "FLOW-001", "name": "notify",
                        "trigger": {"kind": "event"},
                        "steps": [{"key": "s", "name": "email",
                                   "type": "notification", "entity": "ENTITY-001"}]}])
    assert ("POST", "/api/candidates") not in paths(derive_apis(d))


# --- analytics come from widgets -------------------------------------------

def test_an_aggregate_widget_implies_a_metrics_endpoint():
    d = doc(widgets=[{"id": "WIDGET-001", "page": "PAGE-001", "kind": "metric",
                      "label": "Open", "dataSource": {
                          "op": "aggregate", "entity": "ENTITY-001",
                          "aggregation": "count"}}])
    assert ("GET", "/api/candidates/metrics") in paths(derive_apis(d))


def test_a_list_widget_needs_no_extra_endpoint():
    d = doc(widgets=[{"id": "WIDGET-001", "page": "PAGE-001", "kind": "list",
                      "label": "Recent", "dataSource": {
                          "op": "list", "entity": "ENTITY-001"}}])
    assert ("GET", "/api/candidates/metrics") not in paths(derive_apis(d))


# --- the edges become true by construction ---------------------------------

def test_page_actions_get_backing_endpoints(tmp_path):
    d = doc(pages=[{"id": "PAGE-001", "name": "Candidates", "route": "/candidates",
                    "purpose": "x", "actions": ["create", "delete"],
                    "data": {"primaryEntity": "ENTITY-001"}}])
    d["apis"] = derive_apis(d)
    assert verify(d, edges=("Page↔API",)).passed, "the edge the derivation closes"


def test_derived_endpoints_never_reference_a_missing_entity():
    d = doc(pages=[{"id": "PAGE-001", "name": "P", "route": "/p", "purpose": "x",
                    "actions": ["create"],
                    "data": {"primaryEntity": "ENTITY-404"}}])
    d["apis"] = derive_apis(d)
    assert verify(d, edges=("API↔Database",)).passed


# --- policy is read, never invented ----------------------------------------

def test_a_declared_permission_is_attached():
    d = doc(permissions=[{"id": "PERM-001", "name": "create candidates",
                          "action": "create", "subject": "ENTITY-001"}],
            pages=[{"id": "PAGE-001", "name": "P", "route": "/p", "purpose": "x",
                    "actions": ["create"],
                    "data": {"primaryEntity": "ENTITY-001"}}])
    post = next(a for a in derive_apis(d)
                if (a["method"], a["path"]) == ("POST", "/api/candidates"))
    assert post["permission"] == "PERM-001"


def test_an_undeclared_permission_is_not_invented():
    """Leaving it unguarded lets the §75 API↔Permission edge report it, which
    is the honest outcome — inventing one would hide a real gap."""
    d = doc(pages=[{"id": "PAGE-001", "name": "P", "route": "/p", "purpose": "x",
                    "actions": ["create"],
                    "data": {"primaryEntity": "ENTITY-001"}}])
    post = next(a for a in derive_apis(d)
                if (a["method"], a["path"]) == ("POST", "/api/candidates"))
    assert "permission" not in post
    d["apis"] = derive_apis(d)
    assert not verify(d, edges=("API↔Permission",)).passed


# --- idempotence ------------------------------------------------------------

def test_deriving_twice_does_not_duplicate(tmp_path):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="a", name="n",
                                  domain="d")
    svc.doc["data"] = doc()["data"]
    first = apply_derived_apis(svc)
    second = apply_derived_apis(svc)
    assert first["derived"] == second["derived"]
    assert len(svc.doc["apis"]) == first["derived"]
    svc.validate()


def test_the_same_endpoint_implied_twice_merges_provenance():
    d = doc(
        workflows=[{"id": "FLOW-001", "name": "w", "trigger": {"kind": "event"},
                    "requirements": ["REQ-001"],
                    "steps": [{"key": "s", "name": "save", "type": "action",
                               "entity": "ENTITY-001"}]}],
        pages=[{"id": "PAGE-001", "name": "P", "route": "/p", "purpose": "x",
                "actions": ["create"], "requirements": ["REQ-002"],
                "data": {"primaryEntity": "ENTITY-001"}}])
    post = [a for a in derive_apis(d)
            if (a["method"], a["path"]) == ("POST", "/api/candidates")]
    assert len(post) == 1, "one endpoint, not two"
    assert set(post[0]["requirements"]) == {"REQ-001", "REQ-002"}
