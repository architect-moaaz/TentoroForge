# backend/tests/services/test_schema_binding.py
from services.schema_binding import normalize_label, node_text, iter_nodes


def test_normalize_label_lowercases_strips_punct():
    assert normalize_label("  Approve Entry! ") == "approve entry"
    assert normalize_label("Re-Scan") == "re scan"
    assert normalize_label(None) == ""


def test_node_text_reads_common_keys():
    assert node_text({"type": "Text", "props": {"content": "Hi"}}) == "Hi"
    assert node_text({"type": "Button", "props": {"label": "Go"}}) == "Go"
    assert node_text({"type": "Text", "props": {"children": "Kid"}}) == "Kid"
    assert node_text({"type": "Box", "props": {}}) == ""


def test_iter_nodes_yields_every_node_depth_first():
    tree = {"id": "a", "type": "Stack", "children": [
        {"id": "b", "type": "Text", "props": {"content": "x"}},
        {"id": "c", "type": "Row", "children": [{"id": "d", "type": "Button", "props": {"label": "Y"}}]},
    ]}
    ids = [n["id"] for n in iter_nodes(tree)]
    assert ids == ["a", "b", "c", "d"]


from services.schema_binding import structural_signature


def test_signature_identical_for_same_shape():
    a = {"type": "Card", "children": [{"type": "Text"}, {"type": "Button"}]}
    b = {"type": "Card", "children": [{"type": "Text"}, {"type": "Button"}]}
    assert structural_signature(a) == structural_signature(b)


def test_signature_differs_for_different_shape():
    a = {"type": "Card", "children": [{"type": "Text"}]}
    b = {"type": "Card", "children": [{"type": "Button"}]}
    assert structural_signature(a) != structural_signature(b)


def test_signature_depth_bounded():
    # Beyond max_depth, deep structure is ignored — two cards equal at depth 1.
    a = {"type": "Card", "children": [{"type": "Row", "children": [{"type": "Text"}]}]}
    b = {"type": "Card", "children": [{"type": "Row", "children": [{"type": "Button"}]}]}
    assert structural_signature(a, max_depth=1) == structural_signature(b, max_depth=1)
    assert structural_signature(a, max_depth=3) != structural_signature(b, max_depth=3)


from services.schema_binding import find_repeater


def _row(i):
    return {"id": f"r{i}", "type": "Card", "children": [
        {"id": f"t{i}", "type": "Text", "props": {"content": f"Row {i}"}},
        {"id": f"b{i}", "type": "Button", "props": {"label": "View"}},
    ]}


def test_find_repeater_picks_largest_identical_sibling_group():
    schema = {"children": [{"id": "list", "type": "Stack", "children": [_row(1), _row(2), _row(3)]}]}
    match = find_repeater(schema)
    assert match is not None
    assert match["parent"]["id"] == "list"
    assert [m["id"] for m in match["members"]] == ["r1", "r2", "r3"]


def test_find_repeater_returns_none_for_single_row():
    schema = {"children": [{"id": "list", "type": "Stack", "children": [_row(1)]}]}
    assert find_repeater(schema) is None


def test_find_repeater_ignores_heterogeneous_siblings():
    schema = {"children": [{"id": "hdr", "type": "Stack", "children": [
        {"id": "title", "type": "Text", "props": {"content": "T"}},
        {"id": "sub", "type": "Image", "props": {}},
    ]}]}
    assert find_repeater(schema) is None


def test_find_repeater_ignores_leaf_only_groups():
    # Three bare sibling leaf nodes (no children) are not a real list row —
    # a list row must be a container with at least one child cell.
    schema = {"children": [{"id": "stack", "type": "Stack", "children": [
        {"id": "sp1", "type": "Spacer"},
        {"id": "sp2", "type": "Spacer"},
        {"id": "sp3", "type": "Spacer"},
    ]}]}
    assert find_repeater(schema) is None


from services.schema_binding import map_cells_to_fields


def test_map_cells_by_name_substring():
    row = {"type": "Card", "children": [
        {"id": "c1", "type": "Text", "props": {"content": "Driver Name"}},
        {"id": "c2", "type": "Text", "props": {"content": "Status"}},
    ]}
    fields = [{"name": "name"}, {"name": "status"}, {"name": "id"}]
    assert map_cells_to_fields(row, fields) == {"c1": "name", "c2": "status"}


def test_map_cells_positional_when_no_name_match():
    row = {"type": "Card", "children": [
        {"id": "c1", "type": "Text", "props": {"content": "ABC-123"}},
        {"id": "c2", "type": "Text", "props": {"content": "Pending"}},
    ]}
    fields = [{"name": "licensePlate"}, {"name": "status"}]
    assert map_cells_to_fields(row, fields) == {"c1": "licensePlate", "c2": "status"}


def test_map_cells_skips_when_no_fields():
    row = {"type": "Card", "children": [{"id": "c1", "type": "Text", "props": {"content": "X"}}]}
    assert map_cells_to_fields(row, []) == {}


def test_map_cells_excludes_interactive_buttons():
    row = {"type": "Card", "children": [
        {"id": "c1", "type": "Text", "props": {"content": "Name"}},
        {"id": "btn", "type": "Button", "props": {"label": "Approve"}},
    ]}
    fields = [{"name": "name"}, {"name": "status"}]
    result = map_cells_to_fields(row, fields)
    assert "btn" not in result          # button never treated as a display cell
    assert result == {"c1": "name"}


import copy
from services.schema_binding import apply_list_binding


def _list_schema():
    def row(i):
        return {"id": f"r{i}", "type": "Card", "children": [
            {"id": f"t{i}", "type": "Text", "props": {"content": "Driver Name"}},
            {"id": f"s{i}", "type": "Text", "props": {"content": "Status"}},
        ]}
    return {"schemaVersion": "2.0", "id": "p", "dataSources": [],
            "children": [{"id": "list", "type": "Stack", "children": [row(1), row(2), row(3)]}]}


def test_apply_list_binding_adds_datasource_and_repeat():
    schema = _list_schema()
    entity = {"name": "Driver", "fields": [{"name": "name"}, {"name": "status"}]}
    out, info = apply_list_binding(copy.deepcopy(schema), {"entity": "Driver"}, entity)
    assert out["dataSources"] == [{"name": "driver", "entity": "Driver", "op": "list"}]
    # The 3 rows collapse to one Repeat bound to the source.
    stack = out["children"][0]
    assert len(stack["children"]) == 1
    rep = stack["children"][0]
    assert rep["type"] == "Repeat"
    assert rep["bind"] == "driver"
    assert info["bound"] is True


def test_apply_list_binding_rewrites_cells_to_item_fields():
    schema = _list_schema()
    entity = {"name": "Driver", "fields": [{"name": "name"}, {"name": "status"}]}
    out, _ = apply_list_binding(copy.deepcopy(schema), {"entity": "Driver"}, entity)
    rep = out["children"][0]["children"][0]
    texts = [n["props"].get("content") for n in iter_nodes(rep) if n.get("type") == "Text"]
    assert "{{item.name}}" in texts
    assert "{{item.status}}" in texts


def test_apply_list_binding_rewrites_title_cells():
    def row(i):
        return {"id": f"r{i}", "type": "Card", "children": [
            {"id": f"t{i}", "type": "Heading", "props": {"title": "Driver Name"}},
            {"id": f"s{i}", "type": "Heading", "props": {"title": "Status"}},
        ]}
    schema = {"schemaVersion": "2.0", "id": "p", "dataSources": [],
              "children": [{"id": "list", "type": "Stack", "children": [row(1), row(2), row(3)]}]}
    entity = {"name": "Driver", "fields": [{"name": "name"}, {"name": "status"}]}
    out, info = apply_list_binding(copy.deepcopy(schema), {"entity": "Driver"}, entity)
    rep = out["children"][0]["children"][0]
    titles = [n["props"].get("title") for n in iter_nodes(rep) if n.get("type") == "Heading"]
    assert "{{item.name}}" in titles
    assert "{{item.status}}" in titles


def test_apply_list_binding_unbound_when_no_repeater():
    schema = {"schemaVersion": "2.0", "id": "p", "dataSources": [],
              "children": [{"id": "x", "type": "Text", "props": {"content": "solo"}}]}
    entity = {"name": "Driver", "fields": [{"name": "name"}]}
    out, info = apply_list_binding(copy.deepcopy(schema), {"entity": "Driver"}, entity)
    assert info["bound"] is False
    assert out["dataSources"] == []


from services.schema_binding import apply_button_bindings


def test_row_action_button_gets_workflow_and_item_id():
    schema = {"children": [
        {"id": "rep", "type": "Repeat", "bind": "trucks", "children": [
            {"id": "row", "type": "Card", "children": [
                {"id": "btn", "type": "Button", "props": {"label": "Approve"}},
            ]},
        ]},
    ]}
    intent = {"actions": [{"label": "Approve", "workflow": "ApproveEntry", "kind": "row_action"}]}
    out, info = apply_button_bindings(copy.deepcopy(schema), intent)
    btn = next(n for n in iter_nodes(out) if n.get("id") == "btn")
    assert btn["props"]["workflow"] == "ApproveEntry"
    assert btn["props"]["args"]["id"] == "{{item.id}}"
    assert "btn" in info["bound"]


def test_page_action_button_gets_workflow_no_item_args():
    schema = {"children": [{"id": "btn", "type": "Button", "props": {"label": "New Truck"}}]}
    intent = {"actions": [{"label": "New Truck", "workflow": "CreateTruck", "kind": "page_action"}]}
    out, _ = apply_button_bindings(copy.deepcopy(schema), intent)
    btn = next(n for n in iter_nodes(out) if n.get("id") == "btn")
    assert btn["props"]["workflow"] == "CreateTruck"
    assert "args" not in btn["props"]


def test_unmatched_button_left_inert():
    schema = {"children": [{"id": "btn", "type": "Button", "props": {"label": "Cancel"}}]}
    intent = {"actions": [{"label": "Approve", "workflow": "W", "kind": "row_action"}]}
    out, info = apply_button_bindings(copy.deepcopy(schema), intent)
    btn = next(n for n in iter_nodes(out) if n.get("id") == "btn")
    assert "workflow" not in btn["props"]
    assert "btn" in info["unbound"]


from services.schema_binding import apply_bindings


def _plan():
    return {
        "data_models": [{"name": "Driver", "fields": [{"name": "name"}, {"name": "status"}]}],
        "workflows": [{"name": "ApproveDriver", "description": "approve"}],
    }


def _page_intent():
    return {"file": "src/schemas/drivers.json", "entity": "Driver",
            "actions": [{"label": "Approve", "workflow": "ApproveDriver", "kind": "row_action"}]}


def _drivers_schema():
    def row(i):
        return {"id": f"r{i}", "type": "Card", "children": [
            {"id": f"n{i}", "type": "Text", "props": {"content": "Driver Name"}},
            {"id": f"a{i}", "type": "Button", "props": {"label": "Approve"}},
        ]}
    return {"schemaVersion": "2.0", "id": "drivers", "dataSources": [],
            "children": [{"id": "list", "type": "Stack", "children": [row(1), row(2)]}]}


def test_apply_bindings_end_to_end():
    out, report = apply_bindings(_drivers_schema(), _page_intent(), _plan())
    assert out["dataSources"] == [{"name": "driver", "entity": "Driver", "op": "list"}]
    rep = out["children"][0]["children"][0]
    assert rep["type"] == "Repeat" and rep["bind"] == "driver"
    btn = next(n for n in iter_nodes(out) if n.get("type") == "Button")
    assert btn["props"]["workflow"] == "ApproveDriver"
    assert btn["props"]["args"]["id"] == "{{item.id}}"
    assert report["list_bound"] is True
    assert report["buttons_bound"] == 1


def test_apply_bindings_idempotent():
    once, _ = apply_bindings(_drivers_schema(), _page_intent(), _plan())
    twice, report = apply_bindings(copy.deepcopy(once), _page_intent(), _plan())
    assert twice == once                 # nothing changes on re-run
    assert report["list_skipped"] is True
    assert report["buttons_bound"] == 0


def test_apply_bindings_wires_buttons_when_list_already_bound():
    # LLM-shaped: page already has a dataSource + a Repeat (data bound by the
    # page agent), but the row button has no workflow yet.
    schema = {
        "schemaVersion": "2", "id": "drivers",
        "dataSources": [{"name": "driver", "entity": "Driver", "op": "list"}],
        "root": {"id": "r", "type": "Stack", "children": [
            {"id": "rep", "type": "Repeat", "bind": "driver", "children": [
                {"id": "row", "type": "Card", "children": [
                    {"id": "nm", "type": "Text", "props": {"content": "{{item.name}}"}},
                    {"id": "btn", "type": "Button", "props": {"label": "Approve"}},
                ]},
            ]},
        ]},
    }
    out, report = apply_bindings(schema, _page_intent(), _plan())
    btn = next(n for n in iter_nodes(out) if n.get("id") == "btn")
    assert btn["props"]["workflow"] == "ApproveDriver"
    assert btn["props"]["args"]["id"] == "{{item.id}}"
    assert report["list_skipped"] is True       # data binding left intact
    assert report["buttons_bound"] == 1
    # existing dataSource untouched
    assert out["dataSources"] == [{"name": "driver", "entity": "Driver", "op": "list"}]


def test_apply_bindings_reverts_on_invalid_result(monkeypatch):
    import services.schema_binding as sb
    # Force the applier to produce a structurally-broken schema.
    monkeypatch.setattr(sb, "apply_list_binding",
                        lambda s, pi, ed: ({"children": [{"type": ""}]}, {"bound": True, "source": "x"}))
    original = _drivers_schema()
    out, report = apply_bindings(copy.deepcopy(original), _page_intent(), _plan())
    assert out == original  # reverted
    assert report["reverted"] is True


def test_cemex_like_page_binds_list_and_row_button():
    # A list of trucks, each row showing plate + status with an Approve button.
    def row(i):
        return {"id": f"row{i}", "type": "Card", "children": [
            {"id": f"plate{i}", "type": "Text", "props": {"content": "License Plate"}},
            {"id": f"status{i}", "type": "Text", "props": {"content": "Status"}},
            {"id": f"app{i}", "type": "Button", "props": {"label": "Approve"}},
        ]}
    schema = {"schemaVersion": "2.0", "id": "trucks", "dataSources": [],
              "children": [{"id": "wrap", "type": "Stack", "children": [
                  {"id": "title", "type": "Text", "props": {"content": "Trucks"}},
                  {"id": "list", "type": "Stack", "children": [row(1), row(2), row(3), row(4)]},
              ]}]}
    plan = {"data_models": [{"name": "Truck", "fields": [
                {"name": "licensePlate"}, {"name": "status"}, {"name": "id"}]}],
            "workflows": [{"name": "ApproveTruck", "description": "approve"}]}
    intent = {"file": "src/schemas/trucks.json", "entity": "Truck",
              "actions": [{"label": "Approve", "workflow": "ApproveTruck", "kind": "row_action"}]}

    out, report = apply_bindings(schema, intent, plan)

    assert {"name": "truck", "entity": "Truck", "op": "list"} in out["dataSources"]
    repeats = [n for n in iter_nodes(out) if n.get("type") == "Repeat"]
    assert len(repeats) == 1 and repeats[0]["bind"] == "truck"
    # exactly one template row remains under the repeat
    assert len(repeats[0]["children"]) == 1
    btn = next(n for n in iter_nodes(out) if n.get("type") == "Button")
    assert btn["props"]["workflow"] == "ApproveTruck"
    assert btn["props"]["args"]["id"] == "{{item.id}}"
    assert report["list_bound"] and report["buttons_bound"] == 1


def test_navigate_action_sets_navigate_prop():
    import copy
    from services.schema_binding import apply_button_bindings, iter_nodes
    schema = {"children": [{"id": "b", "type": "Button", "props": {"label": "New"}}]}
    intent = {"actions": [{"label": "New", "kind": "navigate", "to": "/tasks/new"}]}
    out, info = apply_button_bindings(copy.deepcopy(schema), intent)
    btn = next(n for n in iter_nodes(out) if n.get("id") == "b")
    assert btn["props"].get("navigate") == "/tasks/new"
    assert "workflow" not in btn["props"]
    assert "b" in info["bound"]


def test_form_on_new_page_wires_create_workflow():
    import copy
    from services.schema_binding import apply_form_bindings, iter_nodes
    schema = {"root": {"id": "r", "type": "Stack", "children": [
        {"id": "f", "type": "Form", "props": {"fields": [{"name": "title"}]}}]}}
    out, info = apply_form_bindings(copy.deepcopy(schema), entity="Task",
                                    page_type="form", route="/tasks/new",
                                    existing_workflows={"CreateTask", "UpdateTask"})
    form = next(n for n in iter_nodes(out) if n.get("type") == "Form")
    assert form["props"]["workflow"] == "CreateTask"
    assert info["forms_bound"] == 1


def test_form_on_new_page_overrides_phantom_workflow():
    # The page agent wired the Form to a phantom workflow that does not exist in
    # the real workflow set. apply_form_bindings must override it to Create<Entity>.
    import copy
    from services.schema_binding import apply_form_bindings, iter_nodes
    schema = {"root": {"id": "r", "type": "Stack", "children": [
        {"id": "f", "type": "Form", "props": {"workflow": "submitLeaveRequest"}}]}}
    out, info = apply_form_bindings(copy.deepcopy(schema), entity="LeaveRequest",
                                    page_type="form", route="/leave-requests/new",
                                    existing_workflows={"CreateLeaveRequest"})
    form = next(n for n in iter_nodes(out) if n.get("type") == "Form")
    assert form["props"]["workflow"] == "CreateLeaveRequest"   # phantom overridden
    assert info["forms_bound"] == 1


def test_form_on_edit_page_overrides_phantom_but_keeps_real_workflow():
    # New semantics: a Form whose current workflow is NOT in existing_workflows
    # (phantom) gets overridden to Update<Entity>; a Form whose workflow IS real
    # is left untouched.
    import copy
    from services.schema_binding import apply_form_bindings, iter_nodes

    # Phantom workflow -> overridden to UpdateTask.
    phantom = {"root": {"type": "Stack", "children": [
        {"id": "f", "type": "Form", "props": {"workflow": "Custom"}}]}}
    out, info = apply_form_bindings(copy.deepcopy(phantom), entity="Task",
                                    page_type="form", route="/tasks/123/edit",
                                    existing_workflows={"UpdateTask"})
    form = next(n for n in iter_nodes(out) if n.get("type") == "Form")
    assert form["props"]["workflow"] == "UpdateTask"   # phantom overridden
    assert info["forms_bound"] == 1

    # Real workflow already present -> left untouched.
    real = {"root": {"type": "Stack", "children": [
        {"id": "f", "type": "Form", "props": {"workflow": "UpdateTask"}}]}}
    out2, info2 = apply_form_bindings(copy.deepcopy(real), entity="Task",
                                      page_type="form", route="/tasks/123/edit",
                                      existing_workflows={"UpdateTask"})
    form2 = next(n for n in iter_nodes(out2) if n.get("type") == "Form")
    assert form2["props"]["workflow"] == "UpdateTask"   # real workflow untouched
    assert info2["forms_bound"] == 0


def test_form_page_buttons_get_submit_and_cancel_navigate():
    """On a create form, the primary/save buttons must become native submit triggers
    (so the Form collects field values + dispatches), and Cancel must navigate back to
    the entity list — otherwise the submit button does nothing (the original bug)."""
    from services.schema_binding import apply_form_bindings
    schema = {"root": {"type": "Form", "props": {}, "children": [
        {"type": "Input", "props": {"name": "firstName"}},
        {"type": "Button", "props": {"label": "Cancel", "variant": "ghost"}},
        {"type": "Button", "props": {"label": "Register Owner", "variant": "primary", "navigate": "/owners/new"}},  # stray nav
    ]}}
    out, rep = apply_form_bindings(schema, entity="Owner", page_type="form",
                                  route="/owners/new", existing_workflows={"CreateOwner"})
    btns = [n for n in _iter(out) if isinstance(n, dict) and n.get("type") == "Button"]
    reg = next(b for b in btns if "Register" in b["props"]["label"])
    cancel = next(b for b in btns if b["props"]["label"] == "Cancel")
    form = next(n for n in _iter(out) if isinstance(n, dict) and n.get("type") == "Form")
    assert form["props"]["workflow"] == "CreateOwner"
    assert reg["props"]["submit"] is True
    assert "navigate" not in reg["props"]  # stray navigate stripped (would reload + abort submit)
    assert cancel["props"]["navigate"] == "/owners"


def _iter(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _iter(v)
    elif isinstance(node, list):
        for v in node:
            yield from _iter(v)
