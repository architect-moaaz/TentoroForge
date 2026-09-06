"""A city Select narrows to its state because the data model says so.

The dependency is a relationship in the data model — City carries a foreign
key to State — not something an author invents. In a Form with two Selects
whose sources are those entities, the child's options are scoped by the
parent's current value through `optionsFrom.dependsOn`, wired at projection.
The composer refuses a dependency whose parent is not on the form, or whose
column the entity lacks.
"""
from services.blueprint.dependent_options import wire_dependent_options
from services.blueprint.functional_completeness import functional_findings

ENTITIES = [
    {"id": "ENTITY-010", "name": "State", "fields": [{"name": "id"}, {"name": "name"}]},
    {"id": "ENTITY-011", "name": "City", "fields": [{"name": "id"}, {"name": "name"}, {"name": "stateId"}]},
]
RELS = [{"from": "ENTITY-011", "to": "ENTITY-010", "kind": "one_to_many", "fromField": "stateId", "toField": "id"}]
SOURCES = [{"name": "states", "op": "list", "entity": "State"}, {"name": "cities", "op": "list", "entity": "City"}]


def _select(name, source, **extra):
    return {"type": "Select", "props": {"name": name, "label": name.title(), "options": [{"value": "x", "label": "x"}],
                                        "optionsFrom": {"source": source, "value": "id", "label": "name", **extra}}, "children": []}


def _form(*kids):
    return {"type": "Form", "props": {}, "children": list(kids)}


def _doc(root, rels=RELS):
    page = {"id": "PAGE-1", "route": "/addresses/new", "name": "p", "requirements": [], "users": [], "data": {}}
    return {"data": {"entities": ENTITIES, "relationships": rels}, "workflows": [], "requirements": [], "roles": [],
            "widgets": [], "pages": [page], "pageLayouts": [{"page": "PAGE-1", "root": root, "dataSources": SOURCES}]}


def test_the_child_is_wired_to_its_parent_from_the_relationship():
    root = _form(_select("state", "states"), _select("city", "cities"))
    layout = {"root": root, "dataSources": SOURCES}
    assert wire_dependent_options(_doc(root), layout) == 1
    assert root["children"][1]["props"]["optionsFrom"]["dependsOn"] == {"field": "state", "column": "stateId"}
    assert "dependsOn" not in root["children"][0]["props"]["optionsFrom"]


def test_without_a_relationship_nothing_is_invented():
    root = _form(_select("state", "states"), _select("city", "cities"))
    assert wire_dependent_options(_doc(root, rels=[]), {"root": root, "dataSources": SOURCES}) == 0


def test_an_authored_dependency_is_kept():
    root = _form(_select("state", "states"), _select("city", "cities", dependsOn={"field": "state", "column": "stateId"}))
    assert wire_dependent_options(_doc(root), {"root": root, "dataSources": SOURCES}) == 0


def test_a_wired_form_passes_the_composer():
    root = _form(_select("state", "states"), _select("city", "cities", dependsOn={"field": "state", "column": "stateId"}))
    assert not [f for f in functional_findings(_doc(root)) if f["rule"] == "dependent-options-unsatisfied"]


def test_a_parent_that_is_not_on_the_form_is_refused():
    root = _form(_select("city", "cities", dependsOn={"field": "state", "column": "stateId"}))
    rules = [f["detail"] for f in functional_findings(_doc(root)) if f["rule"] == "dependent-options-unsatisfied"]
    assert any("depends on 'state', which is not a field of its Form" in d for d in rules), rules


def test_a_column_the_entity_lacks_is_refused():
    root = _form(_select("state", "states"), _select("city", "cities", dependsOn={"field": "state", "column": "regionId"}))
    rules = [f["detail"] for f in functional_findings(_doc(root)) if f["rule"] == "dependent-options-unsatisfied"]
    assert any("'regionId', which City does not have" in d for d in rules), rules


def test_projection_wires_it_where_the_record_is_carried():
    import inspect
    from services.blueprint import page_planner
    assert "wire_dependent_options(doc" in inspect.getsource(page_planner.plan_page)
