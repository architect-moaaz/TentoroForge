"""The navigation is a Blueprint section, and Smith can change it.

The menu — entries, order, labels, groups, landing route — is projected from
`navigation.tree`; nothing in the verb set touched it. A revision is a small
structured call held to a contract, committed through the Blueprint, and the
shell is re-projected. No page is composed."""

import json
from types import SimpleNamespace

import pytest

from services.blueprint.ids import page_key
from services.blueprint.service import BlueprintService
from services.smith import navigation_change as nc


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Med Registration", domain="health")
    s.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Nurse", "table": "nurses",
                                   "fields": [{"name": "id", "type": "uuid"}, {"name": "fullName", "type": "string"}]}]}
    form = s.upsert("pages", {"name": "Nurse Registration", "route": "/nurse-registration", "pattern": "form",
                              "purpose": "Register.", "actions": ["submit"], "data": {"primaryEntity": "ENTITY-001"}},
                    natural_key=page_key("/nurse-registration"))
    lst = s.upsert("pages", {"name": "Master Data", "route": "/master-data", "pattern": "entity_list",
                             "purpose": "All nurses.", "actions": ["view_record"], "data": {"primaryEntity": "ENTITY-001"}},
                   natural_key=page_key("/master-data"))
    edit = s.upsert("pages", {"name": "Edit Nurse", "route": "/nurse-registration/[id]", "pattern": "form",
                              "purpose": "Edit.", "actions": ["save_edit"], "data": {"primaryEntity": "ENTITY-001"}},
                    natural_key=page_key("/nurse-registration/[id]"))
    s.doc["navigation"] = {"style": "sidebar", "initialRoute": {"default": "/nurse-registration"},
                           "tree": [{"label": "Nurse Registration", "page": form["id"], "icon": "user-plus"},
                                    {"label": "Master Data", "page": lst["id"], "icon": "table"}]}
    s.save()
    (tmp_path / "app" / "src" / "schemas").mkdir(parents=True)
    (tmp_path / "app" / "src" / "app" / "(dashboard)").mkdir(parents=True)
    s._t = SimpleNamespace(form=form, lst=lst, edit=edit)
    return s


def _client(replies):
    """A stub for the structured call: each reply is returned in turn."""
    seen = []
    def call(*, system, user, schema):
        seen.append((system, user, schema))
        return json.dumps(replies[min(len(seen) - 1, len(replies) - 1)])
    call.seen = seen
    return call


def test_the_menu_is_reordered_and_relabelled_and_the_shell_re_projected(svc, tmp_path):
    client = _client([{"tree": [{"label": "Nurse Directory", "page": svc._t.lst["id"], "icon": "table"},
                                {"label": "Nurse Registration", "page": svc._t.form["id"], "icon": "user-plus"}],
                       "initialRoute": "/master-data", "note": ""}])
    out = nc.change_navigation(svc, "put Master Data first, call it Nurse Directory, and open on it",
                               app_root=str(tmp_path / "app"), client=client)
    system, user, schema = client.seen[0]
    assert schema is nc.NAV_SCHEMA and "Change ONLY what the request asks" in system
    assert '"canBeInMenu": false' in user and "/nurse-registration/[id]" in user       # the record route is shown as not a destination
    fresh = BlueprintService.load(output_dir=str(tmp_path))
    nav = fresh.doc["navigation"]
    assert [n["label"] for n in nav["tree"]] == ["Nurse Directory", "Nurse Registration"]
    assert nav["initialRoute"] == {"default": "/master-data"} and nav["style"] == "sidebar"
    assert out["before"] == ["Nurse Registration", "Master Data"] and out["after"] == ["Nurse Directory", "Nurse Registration"]
    shell = json.loads((tmp_path / "app" / "src" / "schemas" / "shell.json").read_text())
    groups = shell["children"][0]["props"]["groups"]
    assert [g["label"] for g in groups] == ["Nurse Directory", "Nurse Registration"] and shell["initialRoute"] == "/master-data"
    assert "src/schemas/shell.json" in out["edited_paths"] and "src/contracts/nav-flow.json" in out["edited_paths"]
    assert fresh.doc.get("pageLayouts", []) == []                                          # nothing composed
    text = nc.summary_of(out, "put Master Data first")
    assert "now Nurse Directory · Nurse Registration" in text and "opens on /master-data" in text


def test_a_menu_that_invents_a_page_or_names_a_record_route_is_refused_then_retried(svc, tmp_path):
    client = _client([
        {"tree": [{"label": "Nurse Registration", "page": svc._t.form["id"]},
                  {"label": "Master Data", "page": svc._t.lst["id"]},
                  {"label": "Reports", "page": "PAGE-099"},
                  {"label": "Edit", "page": svc._t.edit["id"]}]},
        {"tree": [{"label": "Admin", "children": [{"label": "Master Data", "page": svc._t.lst["id"]}]},
                  {"label": "Nurse Registration", "page": svc._t.form["id"]}]},
    ])
    out = nc.change_navigation(svc, "group master data under Admin", app_root=None, client=client)
    assert len(client.seen) == 2
    refused = client.seen[1][1]
    assert "PAGE-099" in refused and "not a page of this application" in refused
    assert "record route that cannot be a menu destination" in refused
    assert out["after"] == ["Admin [Master Data]", "Nurse Registration"]


def test_the_contract_in_full(svc):
    doc = svc.doc
    ok = {"tree": [{"label": "A", "page": svc._t.form["id"]}]}
    assert nc.validate(doc, ok) == []
    assert "empty" in nc.validate(doc, {"tree": []})[0]
    assert any("twice" in p for p in nc.validate(doc, {"tree": [{"label": "A", "page": svc._t.form["id"]},
                                                                {"label": "B", "page": svc._t.form["id"]}]}))
    assert any("opens nothing and holds nothing" in p for p in nc.validate(doc, {"tree": [{"label": "Hollow"}]}))
    assert any("landing route" in p for p in nc.validate(doc, {"tree": ok["tree"], "initialRoute": {"default": "/nowhere"}}))
    assert any("no label" in p for p in nc.validate(doc, {"tree": [{"label": " ", "page": svc._t.form["id"]}]}))


def test_a_menu_returned_unchanged_is_not_a_change(svc):
    same = {"tree": [{"label": "Nurse Registration", "page": svc._t.form["id"], "icon": "user-plus"},
                     {"label": "Master Data", "page": svc._t.lst["id"], "icon": "table"}],
            "initialRoute": "", "note": "it is already first"}
    with pytest.raises(nc.NavigationChangeError, match="exactly as it is — it is already first"):
        nc.change_navigation(svc, "put registration first", app_root=None, client=_client([same]))


def test_the_verb_and_the_tool_share_the_seam(monkeypatch, tmp_path):
    import services.smith_tools as smith_tools
    from services.smith.tools import render as _catalogue
    from services.smith.verbs import REQUIRED_BY_VERB
    assert REQUIRED_BY_VERB["edit_navigation"] == {"change"} and "`edit_navigation`" in _catalogue() and "`edit_navigation` (" in _catalogue()
    calls = []
    monkeypatch.setattr("services.smith.navigation_change.run",
                        lambda output_dir, change, **kw: calls.append(change) or {"applied": True, "edited_paths": ["src/schemas/shell.json"], "diff_summary": "ok"})
    assert smith_tools.READONLY_HANDLERS["edit_navigation"](str(tmp_path), {})["applied"] is False
    assert smith_tools.READONLY_HANDLERS["edit_navigation"](str(tmp_path), {"change": "put it first"})["applied"]
    from tests.services._front_door import SmithSession
    session = SmithSession(project_id="p1", output_dir=str(tmp_path), guards_fn=lambda _d: [],
                           understand_ask_fn=lambda m, c, history=None: {"verb": "edit_navigation", "change": "open on master data"},
                           iteration_move_fn=lambda *a, **k: None)
    result = session.run_iteration(user_message="open on master data")
    assert result.status == "resolved" and result.touched_paths == ["src/schemas/shell.json"]
    assert calls == ["put it first", "open on master data"]
