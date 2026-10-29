"""A design of several products is built as one application.

The DITANS file (2026-10-29) draws six products side by side, one top-level
Figma section each: a candidate app (phone), the candidate's web, a recruiter
portal, an agency workspace, an enterprise console and the DITANS back office.
Each has its own sidebar and its own people, and the candidate's screens are
drawn twice, for a phone and for a desktop. Built as one product, every page
wore the admin's frame and every candidate screen became two pages.
"""
from __future__ import annotations

import json

from tests.services.drawn.test_a_drawing_becomes_the_app_as_drawn import _screen


def _source(frames):
    return {"id": "FIGMA-001", "treatAs": "specification", "fileKey": "K", "frames": frames}


# -- the product a frame is drawn in -----------------------------------------

def test_a_frame_knows_the_top_level_section_it_is_drawn_in():
    from services.figma.reference import _screen_nodes

    def frame(nid, name):
        return {"id": nid, "type": "FRAME", "name": name, "absoluteBoundingBox": {"x": 0, "y": 100, "width": 393, "height": 852}}

    page = {"type": "CANVAS", "name": "Page 1", "children": [
        {"type": "SECTION", "name": "D1 · Candidate app", "children": [
            {"type": "TEXT", "characters": "1 · Get started", "absoluteBoundingBox": {"x": 0, "y": 0, "width": 200, "height": 40}},
            frame("1:1", "M-J1 · Jobs"),
            {"type": "SECTION", "name": "D1 · Profile v2.0", "children": [frame("1:2", "M-PR1v3 · Profile")]}]},
        {"type": "SECTION", "name": "D6 · DITANS Admin", "children": [frame("2:1", "A-11 · Promo codes")]},
        frame("3:1", "Loose screen")]}
    got = {node["name"]: (section, portal) for _c, section, node, portal in _screen_nodes({"document": page})
           if node.get("type") == "FRAME"}
    assert got["M-J1 · Jobs"] == ("D1 · Candidate app / 1 · Get started", "D1 · Candidate app")
    assert got["M-PR1v3 · Profile"][1] == "D1 · Candidate app", "a section inside a product is still that product"
    assert got["A-11 · Promo codes"][1] == "D6 · DITANS Admin"
    assert got["Loose screen"][1] == ""


def test_the_frame_record_carries_its_product_and_width():
    from services.figma.reference import DesignReference, FigmaTarget, ScreenRef
    from services.figma.store import source_record

    ref = DesignReference(target=FigmaTarget(file_key="K", node_id="", source_url="u"), source_id="FIGMA-001")
    ref.screens = [ScreenRef(node_id="1:1", name="M-J1", section="D1 / Jobs", portal="D1 · Candidate app", width=393)]
    frame = source_record(ref, name="Ditans", treat_as="specification")["frames"][0]
    assert frame["portal"] == "D1 · Candidate app" and frame["width"] == 393


# -- a frame for each product -------------------------------------------------

def _two_products(monkeypatch, tmp_path):
    from services.figma import store
    from services.figma.reference import ScreenRef

    frames = [{"nodeId": f"{i}:1", "name": f"A-0{i} · Tenants", "portal": "D6 · DITANS Admin"} for i in (1, 2, 3)] \
        + [{"nodeId": f"{i}:1", "name": f"R-0{i} · Jobs", "portal": "D3 · Employer / Recruiter"} for i in (4, 5, 6)]
    doc = {"designSources": [_source(frames)]}
    monkeypatch.setattr(store, "load_screen", lambda sid, nid, out: ScreenRef(
        node_id=nid, name="s", width=1440, height=1024,
        structure={"source": "rest_node_document", "document": _screen(int(nid.split(":")[0]))}))
    return doc


def test_each_product_is_drawn_in_its_own_frame(monkeypatch, tmp_path):
    from services.drawn import convert
    from services.blueprint.orchestrator import _drawn_subjects

    doc = _two_products(monkeypatch, tmp_path)
    assert convert.portals(doc) == ["D6 · DITANS Admin", "D3 · Employer / Recruiter"]
    shells = ["shell:D6 · DITANS Admin", "shell:D3 · Employer / Recruiter"]
    assert convert.shell_subjects(doc) == shells
    assert _drawn_subjects(doc)[-3:] == [*shells, convert.COMPONENTS_KEY]
    prepared = convert._prepare(doc, tmp_path)
    assert set(prepared.shells) == set(shells)
    admin = prepared.shells["shell:D6 · DITANS Admin"]
    assert admin["name"] == "DITANSAdminShell" and admin["portal"] == "D6 · DITANS Admin"
    assert admin["frame"] in {"1:1", "2:1", "3:1"}, "a product's frame is found among its own screens"
    assert prepared.shells["shell:D3 · Employer / Recruiter"]["frame"] in {"4:1", "5:1", "6:1"}
    assert "export default function DITANSAdminShell" in admin["markup"]


def test_a_design_of_one_product_keeps_its_one_frame(monkeypatch, tmp_path):
    from services.drawn import convert

    doc = _two_products(monkeypatch, tmp_path)
    for f in doc["designSources"][0]["frames"]:
        f.pop("portal")
    assert convert.shell_subjects(doc) == [convert.SHELL_KEY]
    prepared = convert._prepare(doc, tmp_path)
    assert list(prepared.shells) == [convert.SHELL_KEY] and prepared.shell_markup


def _shell_row(key, name, portal, labels):
    return {"key": key, "kind": "shell", "name": name, "frame": "1:1", "portal": portal,
            "code": f"export default function {name}() {{}}",
            "contract": {"data": [{"name": "nav", "kind": "list", "fields": []}],
                         "actions": [{"name": "onNav", "label": "", "kind": "navigate", "on": "nav"}]},
            "sample": {"nav": [{"id": str(i), "label": l} for i, l in enumerate(labels)]}}


def _portals_doc():
    frames = [{"nodeId": "1:1", "name": "A-11 · Promo codes", "portal": "Admin", "width": 1440},
              {"nodeId": "2:1", "name": "R-01 · Command centre", "portal": "Recruiter", "width": 1440},
              {"nodeId": "3:1", "name": "CW-02 · Jobs", "portal": "Candidate web", "width": 1440},
              {"nodeId": "4:1", "name": "M-J1 · Jobs", "portal": "Candidate app", "width": 393}]
    return {"application": {"name": "DITANS"}, "designSources": [_source(frames)],
            "roles": [{"id": "ROLE-001", "name": "Platform staff"}, {"id": "ROLE-002", "name": "Recruiter"},
                      {"id": "ROLE-003", "name": "Candidate"}],
            "pages": [{"id": "PAGE-001", "name": "Promo codes", "route": "/promo-codes", "figmaFrame": "1:1",
                       "users": ["ROLE-001"]},
                      {"id": "PAGE-002", "name": "Command centre", "route": "/command-centre", "figmaFrame": "2:1",
                       "users": ["ROLE-002"]},
                      {"id": "PAGE-003", "name": "Jobs", "route": "/jobs/[id]", "figmaFrame": "3:1",
                       "users": ["ROLE-003"]},
                      {"id": "PAGE-004", "name": "Sign in", "route": "/login", "pattern": "auth"}],
            "drawnPairs": [{"phone": "4:1", "wide": "3:1", "because": "the job search"}],
            "drawnViews": [_shell_row("shell:Admin", "AdminShell", "Admin", ["Promo codes"]),
                           _shell_row("shell:Recruiter", "RecruiterShell", "Recruiter", ["Command centre"]),
                           _shell_row("shell:Candidate web", "CandidateWebShell", "Candidate web", ["Jobs"])]}


def test_the_app_wears_the_frame_of_the_product_the_page_was_drawn_in(tmp_path):
    from services.drawn.project import phone_routes, portal_routes, project_drawn, role_portals

    doc = _portals_doc()
    routes = portal_routes(doc, doc["drawnViews"])
    assert routes == [["/promo-codes", "shell:Admin"], ["/command-centre", "shell:Recruiter"],
                      ["/jobs/[id]", "shell:Candidate web"]]
    assert role_portals(doc, routes) == {"Platform staff": "shell:Admin", "Recruiter": "shell:Recruiter",
                                         "Candidate": "shell:Candidate web"}
    assert phone_routes(doc) == ["/jobs/[id]"]
    doc["pages"].append({"id": "PAGE-005", "name": "Push", "route": "/push", "figmaFrame": "4:1"})
    assert phone_routes(doc) == ["/jobs/[id]", "/push"], "a screen drawn only for the phone is bare on one"
    doc["pages"].pop()
    out = project_drawn(doc, tmp_path, tmp_path / "app")
    assert out["shells"] == 3 and out["phone"] == 1
    for name in ("AdminShell", "RecruiterShell", "CandidateWebShell"):
        assert (tmp_path / f"app/src/components/drawn/{name}.tsx").is_file()
    wrapper = (tmp_path / "app/src/components/DrawnShell.tsx").read_text()
    assert 'import ShellView1 from "./drawn/RecruiterShell";' in wrapper
    assert '"shell:Recruiter": Frame1,' in wrapper and 'const FIRST = "shell:Admin";' in wrapper
    assert '"Recruiter": "shell:Recruiter"' in wrapper, "a page no product drew is framed by the role's product"
    assert "if (phone && PHONE.some((r) => matches(r, path))) return <>{props.children}</>;" in wrapper
    assert "role?: string" in wrapper


def test_the_frame_is_chosen_by_page_then_role(tmp_path):
    """The wrapper's route matcher, run as the app runs it."""
    import shutil
    import subprocess

    from services.drawn.project import project_drawn

    if not shutil.which("node"):
        return
    project_drawn(_portals_doc(), tmp_path, tmp_path / "app")
    wrapper = (tmp_path / "app/src/components/DrawnShell.tsx").read_text()
    start = wrapper.index("function matches")
    body = wrapper[start:wrapper.index("\n}\n", start) + 3].replace("route: string, path: string): boolean", "route, path)")
    script = body + "\nconsole.log(JSON.stringify([matches('/jobs/[id]', '/jobs/42'), matches('/jobs/[id]', '/jobs'), " \
                    "matches('/promo-codes', '/promo-codes/'), matches('/a/[...rest]', '/a/b/c')]));"
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout
    assert json.loads(out) == [True, False, True, True]


# -- one screen drawn twice ---------------------------------------------------

def _paired_doc():
    doc = _portals_doc()
    doc["drawnViews"] += [
        {"key": "3:1", "kind": "screen", "name": "JobsView", "frame": "3:1", "code": "x", "portal": "Candidate web",
         "contract": {"data": [{"name": "jobs", "kind": "list", "label": "Jobs", "fields": []}],
                      "actions": [{"name": "onApply", "label": "Apply", "kind": "navigate", "target": "2:1"}]}},
        {"key": "4:1", "kind": "screen", "name": "MJobsView", "frame": "4:1", "code": "y", "portal": "Candidate app",
         "contract": {"data": [{"name": "results", "kind": "list", "label": "Results", "fields": []}],
                      "actions": [{"name": "onOpen", "label": "Open job", "kind": "navigate", "target": "3:1"}]}}]
    return doc


def test_the_phone_and_desktop_drawings_are_asked_about_once_and_can_only_name_real_drawings():
    from services.drawn import pairs

    doc = _paired_doc()
    doc.pop("drawnPairs")
    phones, wides = pairs.candidates(doc)
    assert [f["ref"] for f in phones] == ["4:1"] and [f["ref"] for f in wides] == ["1:1", "2:1", "3:1"]
    schema = pairs.schema(phones, wides)["properties"]["pairs"]["items"]["properties"]
    assert schema["phone"]["enum"] == ["4:1"] and schema["wide"]["enum"] == ["1:1", "2:1", "3:1"]
    asked = {}

    class Reply:
        text = json.dumps({"pairs": [{"phone": "4:1", "wide": "3:1", "because": "job search"},
                                     {"phone": "4:1", "wide": "2:1", "because": "again"}]})
        usage = None

    def client(*, system, user, schema):
        asked["user"] = user
        return Reply()

    found, left = pairs.pair(client, doc)
    assert found == [{"phone": "4:1", "wide": "3:1", "because": "job search"}]
    assert left and "already paired" in left[0]
    assert "`4:1` M-J1 · Jobs" in asked["user"] and "data: Results" in asked["user"]


def test_a_design_of_one_size_asks_nothing():
    from services.drawn import pairs

    doc = _paired_doc()
    for f in doc["designSources"][0]["frames"]:
        f["width"] = 1440
    assert pairs.candidates(doc) == ([], [])
    assert pairs.pair(lambda **_k: (_ for _ in ()).throw(AssertionError("asked")), doc) == ([], [])


def test_a_phone_drawing_of_a_desktop_screen_is_that_screens_page():
    from services.blueprint.page_planner import specification_frames
    from services.drawn import binder

    doc = _paired_doc()
    assert "4:1" not in {f["nodeId"] for f in specification_frames(doc)}, "no page of its own"
    page = doc["pages"][2]
    assert [(a, l) for a, l, _r in binder.views_of(doc, page)] == [("main", "Jobs"), ("phone", "JobsView")]
    assert set(binder.parts_of(doc, page)) == {"JobsView", "MJobsView"}
    prompt = binder.user_prompt(doc, page)
    assert "the phone drawing of `JobsView`, shown instead of it on a phone" in prompt
    assert "useIsPhone()" in prompt
    assert binder._targets(doc)["4:1"]["route"] == "/jobs/[id]", "a link to the phone drawing leads to its page"
    problems = binder.check('import JobsView from "./parts/JobsView";', page, doc)
    assert any("MJobsView" in p for p in problems), "the phone drawing must be shown too"


def test_the_journey_and_the_contracts_say_each_product_and_each_screen_once(monkeypatch, tmp_path):
    from services.drawn import contract, flow

    doc = _paired_doc()
    digest = contract.digest(doc)
    assert "# Candidate web — a product of its own" in digest
    assert "MJobsView" not in digest, "the phone drawing shows what its desktop twin shows"
    monkeypatch.setattr(flow, "_statements", lambda *_a: [])
    text = flow.document(doc, tmp_path)
    assert "The design draws 4 products side by side" in text and "- Candidate app" in text
    assert "## The frame Recruiter's screens are drawn in" in text
    assert "Also drawn for the phone, as M-J1 · Jobs." in text
    assert "### M-J1 · Jobs" not in text


def test_the_planner_hears_who_a_screen_is_for():
    from services.blueprint.page_planner import frame_slots, specification_frames

    doc = _paired_doc()
    slots = {s["figmaFrame"]: s for s in frame_slots(specification_frames(doc), doc=doc)}
    assert slots["2:1"]["portal"] == "Recruiter"
    assert "one of the 3 products the design draws side by side" in slots["2:1"]["prompt"]
