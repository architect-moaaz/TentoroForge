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




def _with_roles(svc):
    """Three kinds of user, each with a door of its own."""
    svc.doc["roles"] = [{"id": "ROLE-001", "name": "Admin"}, {"id": "ROLE-002", "name": "Nurse"}]
    svc.doc["navigation"]["initialRoute"] = {"default": "/nurse-registration", "admin": "/master-data",
                                             "Nurse": "/nurse-registration"}
    svc.save()
    return svc


def test_changing_the_default_landing_keeps_every_role_its_own(svc, tmp_path):
    """The reply used to carry one string and the verb wrote {"default": it}:
    "open on Master Data" took away the administrator's and the nurse's own
    landings, and the 403 page's per-role map emptied with them."""
    _with_roles(svc)
    app = tmp_path / "app"
    from services.blueprint import assembly
    assembly.copy_scaffold(app, project_short_id="t")
    same_tree = [{"label": "Nurse Registration", "page": svc._t.form["id"], "icon": "user-plus"},
                 {"label": "Master Data", "page": svc._t.lst["id"], "icon": "table"}]
    out = nc.change_navigation(svc, "open on Master Data", app_root=str(app),
                               client=_client([{"tree": same_tree, "initialRoute": "/master-data", "note": ""}]))
    nav = BlueprintService.load(output_dir=str(tmp_path)).doc["navigation"]
    assert nav["initialRoute"] == {"default": "/master-data", "admin": "/master-data", "Nurse": "/nurse-registration"}
    assert out["landing"] == "/master-data" and out["landings"] == {}
    nav_flow = json.loads((app / "src/contracts/nav-flow.json").read_text())
    assert nav_flow["initialFor"] == {"Admin": "/master-data", "Nurse": "/nurse-registration"}
    import re
    page = (app / "src/app/forbidden.tsx").read_text()
    inlined = re.search(r"const LANDING_FOR: Record<string, string> = (\{.*?\});", page, re.S)
    assert inlined and json.loads(inlined.group(1)) == {"Admin": "/master-data", "Nurse": "/nurse-registration"}
    assert 'const LANDING = "/master-data";' in page


def test_one_role_s_landing_is_changed_alone_and_spelled_as_the_map_spells_it(svc, tmp_path):
    _with_roles(svc)
    same_tree = [{"label": "Nurse Registration", "page": svc._t.form["id"], "icon": "user-plus"},
                 {"label": "Master Data", "page": svc._t.lst["id"], "icon": "table"}]
    out = nc.change_navigation(svc, "nurses should open on Master Data", app_root=None,
                               client=_client([{"tree": same_tree, "note": "",
                                                "initialRoute": [{"for": "nurse", "route": "/master-data"}]}]))
    nav = BlueprintService.load(output_dir=str(tmp_path)).doc["navigation"]
    assert nav["initialRoute"] == {"default": "/nurse-registration", "admin": "/master-data", "Nurse": "/master-data"}
    assert out["landings"] == {"Nurse": "/master-data"}
    assert "Nurse opens on /master-data" in nc.summary_of(out, "nurses should open on Master Data")


def test_a_landing_for_nobody_or_on_a_record_route_is_refused(svc):
    _with_roles(svc)
    ok = [{"label": "A", "page": svc._t.form["id"]}]
    assert any("not a kind of user" in p for p in
               nc.validate(svc.doc, {"tree": ok, "initialRoute": {"default": "/master-data", "guest": "/master-data"}}))
    assert any("for admin" in p for p in
               nc.validate(svc.doc, {"tree": ok, "initialRoute": {"admin": "/nurse-registration/[id]"}}))
    assert nc.validate(svc.doc, {"tree": ok, "initialRoute": {"default": "/master-data", "ADMIN": "/master-data",
                                                              "ROLE-002": "/master-data"}}) == []
    assert nc._landings(svc.doc, svc.doc["navigation"], [{"for": "ADMIN", "route": "/nurse-registration"}]) == {
        "default": "/nurse-registration", "admin": "/nurse-registration", "Nurse": "/nurse-registration"}
    assert nc._landings(svc.doc, svc.doc["navigation"], "") == svc.doc["navigation"]["initialRoute"]


def test_the_model_is_told_the_kinds_of_user(svc):
    _with_roles(svc)
    system, user = nc._prompt(svc.doc, "open on Master Data")
    assert "per kind of user" in system and "The kinds of user (roles): Admin, Nurse" in user
