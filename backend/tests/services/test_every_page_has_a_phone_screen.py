"""The phone's safety nets: every page has a screen, and a screen that could not be written is said and recoverable.

A native app has one screen per page. When the writer cannot produce one (it fails its rounds, needs a workflow
that does not exist, or the run stops) the page used to be missing from the phone: a tab or a menu entry leading to
"This screen does not exist", and a hand-over message that said nothing. Now:
  * `screen_gaps` names the pages with no screen (the check);
  * each gets a route that says what happened and links to the web page (`MissingScreen`);
  * the hand-over message says which ones, and what happens on the phone;
  * `write_phone_screens` writes just those, in one version."""
from __future__ import annotations

import types
from pathlib import Path

import pytest

from services.blueprint.native_projection import MISSING_SCREEN, native_root, project_native, screen_gaps
from services.smith import compose, writes

SCREEN = "export default function Screen() { return null; }"


def doc(rows=("PAGE-001",), native=True, mobile="tabs"):
    pages = [
        {"id": "PAGE-001", "name": "Plants", "route": "/plants", "pattern": "entity_list", "access": "authenticated"},
        {"id": "PAGE-002", "name": "Add Plant", "route": "/add-plant", "pattern": "form", "access": "authenticated"},
        {"id": "PAGE-003", "name": "Sign in", "route": "/login", "pattern": "auth", "access": "public"},
    ]
    return {"application": {"name": "Leafy"}, "mobile": {"native": {"enabled": native}}, "designSystem": {}, "security": {},
            "roles": [], "data": {"entities": []}, "workflows": [], "pages": pages,
            "navigation": {"tree": [{"label": "Plants", "page": "PAGE-001"}], "mobile": mobile},
            "nativeCode": [{"page": p, "screen": SCREEN} for p in rows]}


# --- the check ---------------------------------------------------------------------------------------------


def test_a_page_with_no_screen_is_a_gap_and_the_fixed_sign_in_is_not():
    gaps = screen_gaps(doc(rows=("PAGE-001",)))
    assert [p["id"] for p in gaps] == ["PAGE-002"], "the sign-in page has the fixed screen standing in"
    assert screen_gaps(doc(rows=("PAGE-001", "PAGE-002"))) == []


def test_an_app_that_is_not_native_has_no_gaps():
    assert screen_gaps(doc(rows=(), native=False)) == []


def test_a_row_with_no_screen_in_it_does_not_count_as_a_screen():
    d = doc(rows=("PAGE-001",))
    d["nativeCode"].append({"page": "PAGE-002", "screen": ""})
    assert [p["id"] for p in screen_gaps(d)] == ["PAGE-002"]


# --- the fallback screen -----------------------------------------------------------------------------------


def test_a_page_with_no_screen_still_has_a_route_that_says_so(tmp_path):
    project_native(doc(rows=("PAGE-001",)), tmp_path)
    root = native_root(tmp_path)
    fallback = (root / "app/add-plant.tsx").read_text("utf-8")
    assert fallback == MISSING_SCREEN.format(title='"Add Plant"', route='"/add-plant"')
    assert "<MissingScreen" in fallback and '"/add-plant"' in fallback
    real = [f for f in (root / "app/plants.tsx", root / "app/(tabs)/plants.tsx") if f.exists()]
    assert real and "@/screens/PAGE-001" in real[0].read_text("utf-8"), "the page that has a screen is untouched"


def test_a_tab_whose_screen_is_missing_is_missing_inside_the_tabs(tmp_path):
    d = doc(rows=())
    d["navigation"]["tree"] = [{"label": "Plants", "page": "PAGE-001"}, {"label": "Add", "page": "PAGE-002"}]
    project_native(d, tmp_path)
    assert "MissingScreen" in (native_root(tmp_path) / "app/(tabs)/plants.tsx").read_text("utf-8")


def test_the_real_screen_replaces_the_notice_when_it_is_written_later(tmp_path):
    project_native(doc(rows=("PAGE-001",)), tmp_path)
    root = native_root(tmp_path)
    assert "MissingScreen" in (root / "app/add-plant.tsx").read_text("utf-8")
    project_native(doc(rows=("PAGE-001", "PAGE-002")), tmp_path)
    assert (root / "app/add-plant.tsx").read_text("utf-8") == 'export { default } from "@/screens/PAGE-002";\n'


def test_the_notice_goes_with_the_page_when_the_page_goes(tmp_path):
    project_native(doc(rows=("PAGE-001",)), tmp_path)
    gone = doc(rows=("PAGE-001",))
    gone["pages"] = [p for p in gone["pages"] if p["id"] != "PAGE-002"]
    project_native(gone, tmp_path)
    assert not (native_root(tmp_path) / "app/add-plant.tsx").exists()


def test_the_kit_has_the_part_the_notice_uses():
    kit = Path(__file__).resolve().parents[2] / "templates" / "native" / "src" / "ui"
    assert "export function MissingScreen" in (kit / "Missing.tsx").read_text("utf-8")
    assert "MissingScreen" in (kit / "index.ts").read_text("utf-8")


# --- the hand-over message ---------------------------------------------------------------------------------


def test_the_handover_message_names_the_screens_the_phone_is_missing():
    from routers.blueprint_generate import _phone_line
    line = _phone_line(doc(rows=("PAGE-001",)))
    assert "1 screen could not be written (Add Plant)" in line and "web app is complete" in line
    assert "write the phone screens" in line
    many = doc(rows=())
    assert "2 screens could not be written (Plants, Add Plant)" in _phone_line(many) and "those pages show" in _phone_line(many)
    assert _phone_line(doc(rows=("PAGE-001", "PAGE-002"))) == "" and _phone_line(doc(native=False, rows=())) == ""
    assert _phone_line(None) == ""


def test_the_line_is_part_of_the_handover_message():
    import inspect
    from routers import blueprint_generate
    assert "_phone_line(full)" in inspect.getsource(blueprint_generate._build_complete_message)


# --- the retry ---------------------------------------------------------------------------------------------


class Svc:
    output_dir = "/tmp/nowhere"

    def __init__(self, d):
        self.doc = {**d, "version": 1}
        self.proposals = []

    def snapshot(self):
        return dict(self.doc)

    def save(self):
        pass

    def commit(self, **kw):
        self.committed = kw
        return {"version": 2}


@pytest.fixture
def stubbed(monkeypatch):
    import services.blueprint.agent_contract as ac
    import services.blueprint.executors as ex
    import services.blueprint.native_projection as np_
    state = {"projected": 0, "refuse": set()}

    def apply(svc, result, commit=True):
        for p in result.proposals:
            svc.proposals.append(p.natural_key)
        bad = any(p.natural_key in state["refuse"] for p in result.proposals)
        return types.SimpleNamespace(applied=not bad, reason="contract said no" if bad else "",
                                     artifacts=[] if bad else [f"nativeCode:{p.natural_key}" for p in result.proposals])

    monkeypatch.setattr(ac, "apply_agent_result", apply)
    monkeypatch.setattr(ex.RunUsage, "for_app", classmethod(lambda cls, svc, phase="build": cls()))
    monkeypatch.setattr(np_, "project_native", lambda *a, **k: state.__setitem__("projected", state["projected"] + 1))
    return state, monkeypatch


def test_the_retry_writes_only_the_pages_that_have_no_screen(stubbed):
    state, mp = stubbed
    asked = []
    mp.setattr(compose, "native_follow", lambda svc, d, page, **k: (asked.append(page["id"]) or {"page": page["id"], "screen": SCREEN}, ""))
    svc = Svc(doc(rows=("PAGE-001",)))
    out = compose.native_pass(svc)
    assert out["applied"] and out["written"] == ["/add-plant"] and asked == ["PAGE-002"]
    assert svc.proposals == ["PAGE-002"] and state["projected"] == 1 and svc.committed["affected"] == ["nativeCode:PAGE-002"]


def test_the_retry_can_name_pages_and_says_why_one_could_not_be_written(stubbed):
    state, mp = stubbed
    mp.setattr(compose, "native_follow", lambda svc, d, page, **k: (None, "the phone screen of /plants did not compile, so it was left as it was")
               if page["id"] == "PAGE-001" else ({"page": page["id"], "screen": SCREEN}, ""))
    out = compose.native_pass(Svc(doc(rows=())), ["/plants", "/add-plant", "/nowhere"], only_missing=False)
    assert out["written"] == ["/add-plant"]
    assert "did not compile" in out["failed"]["/plants"] and "no phone screen to write" in out["failed"]["/nowhere"]


def test_the_retry_changes_nothing_when_every_screen_was_refused_or_none_is_missing(stubbed):
    state, mp = stubbed
    mp.setattr(compose, "native_follow", lambda svc, d, page, **k: ({"page": page["id"], "screen": SCREEN}, ""))
    state["refuse"] = {"PAGE-002"}
    refused = compose.native_pass(Svc(doc(rows=("PAGE-001",))))
    assert not refused["applied"] and "refused" in refused["failed"]["/add-plant"] and state["projected"] == 0
    assert compose.native_pass(Svc(doc(rows=("PAGE-001", "PAGE-002"))))["reason"] == "every page already has a phone screen"
    assert "not a native app" in compose.native_pass(Svc(doc(native=False, rows=())))["reason"]


def test_smith_has_the_tool_and_says_what_it_did(monkeypatch):
    assert "write_phone_screens" in writes.WRITE_NAMES
    monkeypatch.setattr("services.blueprint.service.BlueprintService.load", classmethod(lambda cls, **k: object()))
    monkeypatch.setattr("services.smith.compose.native_pass", lambda svc, routes, **k: {
        "applied": True, "written": ["/add-plant"], "failed": {"/plants": "did not compile"}, "version": 4, "reason": ""})
    out = writes.write_phone_screens("/tmp/x")
    assert out["applied"] and "Wrote 1 phone screen(s) (version 4): `/add-plant`" in out["said"]
    assert "still without a phone screen" in out["finding"] and "/plants: did not compile" in out["finding"]
    monkeypatch.setattr("services.smith.compose.native_pass", lambda svc, routes, **k: {
        "applied": False, "written": [], "failed": {}, "version": 4, "reason": "every page already has a phone screen"})
    assert writes.write_phone_screens("/tmp/x")["said"] == "every page already has a phone screen"
