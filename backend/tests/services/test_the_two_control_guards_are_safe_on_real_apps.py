"""Defects the tester found in control_inputs_guard and link_target_guard
(D1-D10): wrong repairs, speed, ambiguity about WHO a user input is, reference
forms, assets, route groups, wiring, atomic/minimal writes, quiet failures."""
import json
import logging
import time

from services.control_inputs_guard import ensure_controls_supply_inputs
from services.link_target_guard import ensure_links_resolve


def _w(tmp_path, rel, doc, raw=None):
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(raw if raw is not None else json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return p


def _page(tmp_path, rel, root, route="/x", **extra):
    return _w(tmp_path, f"src/schemas/{rel}", {"route": route, "root": root, **extra})


def _link(label, **p):
    return {"type": "Button", "props": {"label": label, **p}}


def _read(p):
    return json.loads(p.read_text(encoding="utf-8"))


# --- D1: a repoint is to a page of the same kind, never a [param] or a different kind ----------

def test_back_link_to_a_list_that_does_not_exist_is_removed_not_pointed_at_itself(tmp_path, caplog):
    _page(tmp_path, "incidents/[id].json", {"type": "Stack", "children": [_link("Back", navigate="/incidents")]},
          route="/incidents/[id]")
    with caplog.at_level(logging.WARNING, logger="services.link_target_guard"):
        r = ensure_links_resolve(str(tmp_path))
    blob = (tmp_path / "src/schemas/incidents/[id].json").read_text()
    assert "[id]\"" not in blob.replace('"route": "/incidents/[id]"', "") and '"navigate"' not in blob
    assert r["removed"] and r["repointed"] == []
    assert any("Back" in f.get("control", "") for f in r["findings"])              # D1c: named


def test_list_and_form_links_never_collapse_onto_a_detail_page(tmp_path):
    _page(tmp_path, "products/detail.json", {"type": "Stack"}, route="/products/detail")
    _page(tmp_path, "home.json", {"type": "Stack", "children": [
        _link("All", navigate="/products"), _link("New", navigate="/products/new"),
        _link("Edit", navigate="/products/[id]/edit")]}, route="/")
    r = ensure_links_resolve(str(tmp_path))
    assert r["repointed"] == []
    assert "/products/detail" not in (tmp_path / "src/schemas/home.json").read_text()


def test_a_close_page_of_the_same_kind_is_still_an_honest_repoint(tmp_path):
    _page(tmp_path, "rate-changes.json", {"type": "Stack"}, route="/rate-changes")
    _page(tmp_path, "home.json", {"type": "Stack", "children": [_link("Rates", navigate="/rate-change")]}, route="/")
    r = ensure_links_resolve(str(tmp_path))
    assert r["repointed"] == [{"page": "home.json", "link": "navigate", "target": "/rate-change", "to": "/rate-changes"}]


# --- D2: speed ----------------------------------------------------------------------------------

def test_a_big_app_is_checked_quickly(tmp_path):
    for i in range(100):
        links = [_link(f"l{j}", navigate=f"/p{(i + j) % 100}") for j in range(20)]
        _page(tmp_path, f"p{i}.json", {"type": "Stack", "children": links}, route=f"/p{i}")
    t = time.time()
    ensure_links_resolve(str(tmp_path))
    assert time.time() - t < 6          # was 28s; ~0.3s now - the bound is generous for slow machines


# --- D3 / D4: who is `userId`, and every way a step can read it --------------------------------

def _assign_app(tmp_path, wf_name="Assign Ticket", value="{{userId}}", control=None):
    wf = {"id": "flow-1", "name": wf_name, "requiredInputs": ["userId"],
          "definition": {"nodes": [{"id": "n", "data": {"config": {"actionType": "db_update", "table": "tickets",
                                                                      "values": {"assignee": value}}}}]}}
    _w(tmp_path, "src/lib/workflows/definitions/assign.json", wf)
    row = {"type": "Table", "props": {"rowActions": [{"label": "Assign to", "workflow": "flow-1"}]}}
    _page(tmp_path, "tickets.json", control or row, route="/tickets")
    return tmp_path / "src/lib/workflows/definitions/assign.json"


def test_an_assign_action_is_never_rewritten_to_assign_to_the_admin(tmp_path):
    wf = _assign_app(tmp_path)
    r = ensure_controls_supply_inputs(str(tmp_path))
    assert r["repaired"] == [] and [f["input"] for f in r["findings"]] == ["userId"]
    assert "person acted on" in r["findings"][0]["detail"]
    assert _read(wf)["requiredInputs"] == ["userId"] and "{{user.id}}" not in wf.read_text()


def test_a_bare_userid_on_a_plain_button_is_still_the_acting_user(tmp_path):
    wf = _assign_app(tmp_path, wf_name="Mark Notifications Read",
                     control={"type": "Button", "props": {"label": "Mark all read", "workflow": "flow-1"}})
    r = ensure_controls_supply_inputs(str(tmp_path))
    assert [x["input"] for x in r["repaired"]] == ["userId"] and r["findings"] == []
    assert "{{user.id}}" in wf.read_text()


def test_an_unambiguous_actor_name_is_bound_even_on_a_row(tmp_path):
    wf = _assign_app(tmp_path)
    d = _read(wf)
    d["requiredInputs"] = ["requesterId"]
    d["definition"]["nodes"][0]["data"]["config"]["values"] = {"by": "{{requesterId}}"}
    wf.write_text(json.dumps(d))
    r = ensure_controls_supply_inputs(str(tmp_path))
    assert [x["input"] for x in r["repaired"]] == ["requesterId"]


def test_other_reference_forms_are_not_half_rewritten(tmp_path):
    for value in ("{{ userId | upper }}", "{{userId.name}}", "$userId"):
        wf = _assign_app(tmp_path, wf_name="Mark Read", value=value,
                         control={"type": "Button", "props": {"label": "Mark all read", "workflow": "flow-1"}})
        r = ensure_controls_supply_inputs(str(tmp_path))
        assert r["repaired"] == [], value
        assert _read(wf)["requiredInputs"] == ["userId"] and [f["input"] for f in r["findings"]] == ["userId"]


# --- D5: assets and data are not links ---------------------------------------------------------

def test_files_uploads_and_data_rows_are_not_dead_links(tmp_path):
    p = _page(tmp_path, "home.json", {"type": "Stack", "children": [
        {"type": "Image", "props": {"src": "/logo.png", "href": "/logo.png"}},
        _link("Doc", href="/uploads/x.pdf"),
        {"type": "Table", "props": {"data": [{"href": "/zzz", "to": "/yyy"}]}}]}, route="/")
    before = p.read_text()
    assert ensure_links_resolve(str(tmp_path)) == {"created": [], "repointed": [], "removed": [], "findings": []}
    assert p.read_text() == before


# --- D6: name matching is the runtime's (exact), and the message says so -----------------------

def test_a_field_that_differs_only_by_case_is_named_as_such(tmp_path):
    _w(tmp_path, "src/lib/workflows/definitions/t.json",
       {"id": "f", "name": "Add", "requiredInputs": ["Title"], "definition": {"x": "{{Title}}"}})
    _page(tmp_path, "a.json", {"type": "Form", "props": {"workflow": "f", "fields": [{"name": "title"}]}})
    (f,) = ensure_controls_supply_inputs(str(tmp_path))["findings"]
    assert "differs from 'Title' by case" in f["detail"]


# --- D7: route groups, and a wildcard never answers new/edit -------------------------------------

def test_a_page_in_a_route_group_is_reached_without_the_group_in_the_url(tmp_path):
    _page(tmp_path, "(dashboard)/cats.json", {"type": "Stack"}, route="/cats")
    _page(tmp_path, "home.json", {"type": "Stack", "children": [_link("Cats", navigate="/cats")]}, route="/")
    assert ensure_links_resolve(str(tmp_path))["removed"] == []


def test_a_dynamic_page_does_not_answer_a_link_to_new(tmp_path):
    _page(tmp_path, "cats.json", {"type": "Stack"}, route="/cats")
    _page(tmp_path, "cats/[id].json", {"type": "Stack"}, route="/cats/[id]")
    _page(tmp_path, "home.json", {"type": "Stack", "children": [_link("Add", navigate="/cats/new")]}, route="/")
    r = ensure_links_resolve(str(tmp_path))
    assert [x["target"] for x in r["removed"]] == ["/cats/new"]


# --- D8: the guards run in the suite, and what they find reaches the verdict --------------------

def test_the_guard_suite_runs_both_guards_and_reports_what_they_find(tmp_path):
    from services.post_generate_fixes import apply_post_generate_fixes_with_result
    _w(tmp_path, "src/lib/workflows/definitions/c.json",
       {"id": "flow-c", "name": "Cancel Order", "requiredInputs": ["order"], "definition": {"w": {"id": "{{order}}"}}})
    _page(tmp_path, "orders.json", {"type": "Stack", "children": [
        {"type": "Button", "props": {"label": "Cancel", "workflow": "flow-c"}},
        _link("Back", navigate="/nowhere")]}, route="/orders")
    result = apply_post_generate_fixes_with_result(str(tmp_path), force=True)
    guards = {f.guard for f in result.failures}
    msgs = " ".join(f.message for f in result.failures)
    assert "control_inputs_guard" in " ".join(guards) or "control_inputs_guard" in msgs
    assert "link_target_guard" in " ".join(guards) or "link_target_guard" in msgs
    assert '"navigate"' not in (tmp_path / "src/schemas/orders.json").read_text()      # and the repair happened


# --- D9: atomic, minimal writes ---------------------------------------------------------------

def test_a_rewrite_keeps_the_files_own_formatting(tmp_path):
    raw = '{"id":"f","name":"Mark Read","requiredInputs":["userId"],"note":"café","definition":{"v":"{{userId}}"}}'
    wf = _w(tmp_path, "src/lib/workflows/definitions/m.json", None, raw=raw)
    _page(tmp_path, "a.json", {"type": "Button", "props": {"label": "Mark all read", "workflow": "f"}})
    ensure_controls_supply_inputs(str(tmp_path))
    out = wf.read_text(encoding="utf-8")
    assert "\n" not in out.strip() and "café" in out and not out.endswith("\n")   # compact, unescaped, no newline
    assert "{{user.id}}" in out
    assert not list(wf.parent.glob("*.tmp*"))


def test_a_page_is_rewritten_with_its_own_indent_and_newline(tmp_path):
    raw = json.dumps({"route": "/", "root": {"type": "Stack", "children": [_link("Gone", navigate="/nowhere"),
                                                                           {"type": "Text", "props": {"content": "café"}}]}},
                     indent=4, ensure_ascii=False)
    p = _w(tmp_path, "src/schemas/home.json", None, raw=raw)
    ensure_links_resolve(str(tmp_path))
    out = p.read_text(encoding="utf-8")
    assert '\n    "route"' in out and "café" in out and not out.endswith("\n") and "nowhere" not in out


def test_a_clean_app_is_not_rewritten_at_all(tmp_path):
    p = _page(tmp_path, "home.json", {"type": "Stack", "children": [_link("Home", navigate="/")]}, route="/")
    m = p.stat().st_mtime_ns
    ensure_links_resolve(str(tmp_path))
    assert p.stat().st_mtime_ns == m


# --- D10: an unreadable file is named, not silently skipped -----------------------------------

def test_a_malformed_page_is_warned_about_by_name(tmp_path, caplog):
    (tmp_path / "src/schemas").mkdir(parents=True)
    (tmp_path / "src/schemas/broken.json").write_text("{not json")
    with caplog.at_level(logging.WARNING):
        ensure_links_resolve(str(tmp_path))
    assert any("broken.json" in m for m in caplog.messages)
