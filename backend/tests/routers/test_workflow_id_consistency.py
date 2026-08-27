"""Regression: a workflow's client-facing id must equal its filename stem.

Bug: `list_workflows` returned the JSON's internal `id` field (a slug), but
`get_workflow`/`delete_workflow` and the runtime engine (`_load_definition`)
resolve a workflow by `{output_dir}/workflows/{id}.json` (the filename). When a
generated workflow file is named `<hash>.json` but contains a divergent
`"id": "<slug>"`, the listed slug could not be opened/simulated/deleted → 404.

Fix: clients always see the filename stem as the id.
"""
from routers.workflows import workflow_list_item, canonical_workflow


def test_list_item_id_is_filename_stem_not_internal_id():
    data = {
        "id": "leave-request-approval",  # divergent internal slug
        "name": "Leave Request",
        "description": "d",
        "definition": {"trigger": {"type": "manual"}, "steps": [1, 2]},
    }
    item = workflow_list_item(data, stem="46d9a27c")
    assert item.id == "46d9a27c"  # canonical id == filename so get-one resolves
    assert item.name == "Leave Request"
    assert item.trigger_type == "manual"
    assert item.step_count == 2


def test_list_item_falls_back_to_stem_for_missing_fields():
    item = workflow_list_item({}, stem="abc123")
    assert item.id == "abc123"
    assert item.name == "abc123"
    assert item.description is None
    assert item.trigger_type is None
    assert item.step_count == 0


def test_canonical_workflow_overrides_id_to_stem():
    data = {"id": "leave-request-approval", "name": "Leave"}
    out = canonical_workflow(data, stem="46d9a27c")
    assert out["id"] == "46d9a27c"  # body id == filename so simulate/start use the right id
    assert out["name"] == "Leave"


def test_canonical_workflow_noop_when_already_matching():
    assert canonical_workflow({"id": "abc", "name": "X"}, "abc")["id"] == "abc"
