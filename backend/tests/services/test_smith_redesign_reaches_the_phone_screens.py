"""Smith's multi-page redesign lays out the phone's screens with the web's pages.

`relayout_pages` rewrote every web page in parallel and left the phone as it was, so after "redo every screen like
Myntra" the two apps no longer matched. Each phone screen is now written in the same worker, saved in the same
version, and a screen that cannot be written is said, per page, without undoing the redesign."""
from __future__ import annotations

import types

import pytest

from services.smith import compose, writes

PAGES = [
    {"id": "PAGE-001", "name": "Plants", "route": "/plants", "pattern": "entity_list"},
    {"id": "PAGE-002", "name": "Add Plant", "route": "/add-plant", "pattern": "form"},
]


class Svc:
    output_dir = "/tmp/nowhere"

    def __init__(self):
        self.doc = {"application": {"id": "x"}, "pages": PAGES, "version": 1,
                    "pageCode": [{"page": p["id"], "view": "old", "load": "old"} for p in PAGES]}
        self.proposals: list[tuple[str, str, str]] = []

    def snapshot(self):
        return dict(self.doc)

    def save(self):
        pass

    def commit(self, **kw):
        self.committed = kw
        return {"version": 2}


@pytest.fixture
def world(monkeypatch):
    """The model, the compiler and the Blueprint commit replaced; what is under test is who writes what."""
    svc = Svc()
    calls = {"projected": 0, "refuse": None}

    import services.blueprint.agent_contract as ac
    import services.blueprint.app_sdk as sdk
    import services.blueprint.executors as ex
    import services.blueprint.ui_engineer as ui

    monkeypatch.setattr(ui, "ensure_sdk", lambda *a, **k: None)
    monkeypatch.setattr(ui, "compose_page", lambda doc, page, root, llm, **k: ({"view": "new", "load": "new", "parts": {}}, []))
    monkeypatch.setattr(sdk, "project_code_pages", lambda *a, **k: None)
    monkeypatch.setattr(ex, "tiered_router", lambda reasoning=None: types.SimpleNamespace(
        for_task=lambda node, agent: types.SimpleNamespace(accepts_images=False)))
    monkeypatch.setattr(ex.RunUsage, "for_app", classmethod(lambda cls, svc, phase="build": cls()))

    def apply(svc_, result, commit=True):
        for p in result.proposals:
            svc.proposals.append((p.section, p.natural_key, result.agent))
        refuse = calls["refuse"]
        if refuse and any(p.section == refuse for p in result.proposals):
            return types.SimpleNamespace(applied=False, reason="contract said no", artifacts=[])
        return types.SimpleNamespace(applied=True, reason="", artifacts=[f"{p.section}:{p.natural_key}" for p in result.proposals])

    monkeypatch.setattr(ac, "apply_agent_result", apply)

    import services.blueprint.native_projection as np_
    monkeypatch.setattr(np_, "project_native", lambda *a, **k: calls.__setitem__("projected", calls["projected"] + 1))
    return svc, calls, monkeypatch


def run(svc, monkeypatch, phone):
    """`phone(page)` -> (body | None, note): what the phone's writer answers for each page."""
    monkeypatch.setattr(compose, "native_follow", lambda svc_, doc, page, **k: phone(page, k))
    return compose.relayout_pages(svc, ["/plants", "/add-plant"], app_root="/tmp/nowhere/app", request="follow the Myntra pattern")


def test_every_phone_screen_is_laid_out_again_in_the_same_version(world):
    svc, calls, mp = world
    seen = []
    out = run(svc, mp, lambda page, k: (seen.append(k["brief"]) or {"page": page["id"], "screen": "new screen"}, ""))
    assert out["applied"] and out["done"] == ["/add-plant", "/plants"]
    assert out["native"] == {"/add-plant": "updated", "/plants": "updated"}
    sections = sorted((s, k) for s, k, _ in svc.proposals)
    assert sections == [("nativeCode", "PAGE-001"), ("nativeCode", "PAGE-002"), ("pageCode", "PAGE-001"), ("pageCode", "PAGE-002")]
    assert all("follow the Myntra pattern" in b and "Keep every control" in b for b in seen)
    assert svc.committed["affected"] and calls["projected"] == 1, "one commit, then the phone project refreshed once"


def test_a_screen_that_cannot_be_written_is_said_and_the_redesign_stands(world):
    svc, calls, mp = world
    out = run(svc, mp, lambda page, k: (None, "the phone screen of /plants did not compile, so it was left as it was")
              if page["id"] == "PAGE-001" else ({"page": page["id"], "screen": "s"}, ""))
    assert out["applied"] and out["done"] == ["/add-plant", "/plants"]
    assert out["native"]["/add-plant"] == "updated" and "did not compile" in out["native"]["/plants"]


def test_a_phone_screen_the_contract_refuses_is_said_and_the_web_page_stands(world):
    svc, calls, mp = world
    calls["refuse"] = "nativeCode"
    out = run(svc, mp, lambda page, k: ({"page": page["id"], "screen": "s"}, ""))
    assert out["applied"] and len(out["done"]) == 2
    assert all("refused" in v and "contract said no" in v for v in out["native"].values())
    assert calls["projected"] == 0, "nothing of the phone changed, so its project is not rewritten"


def test_a_web_only_app_is_laid_out_as_before(world):
    svc, calls, mp = world
    out = run(svc, mp, lambda page, k: (None, ""))
    assert out["applied"] and out["native"] == {}
    assert {s for s, _, _ in svc.proposals} == {"pageCode"} and calls["projected"] == 0


def test_the_person_is_told_what_happened_to_the_phone(monkeypatch):
    def said(native):
        monkeypatch.setattr("services.smith.compose.relayout_pages", lambda *a, **k: {
            "applied": True, "done": ["/a", "/b"], "failed": {}, "version": 5, "committed": [], "native": native})
        monkeypatch.setattr("services.blueprint.service.BlueprintService.load", classmethod(lambda cls, **k: types.SimpleNamespace(
            doc={"pages": [{"id": "P", "route": "/a"}]})))
        monkeypatch.setattr("services.smith.compose.code_row", lambda doc, pid: {"x": 1})
        return writes.rewrite_pages("/tmp/x", ["/a", "/b"], "redo them")

    allok = said({"/a": "updated", "/b": "updated"})
    assert "The phone screens were laid out again to match." in allok["said"] and allok["finding"] == ""
    part = said({"/a": "updated", "/b": "the phone screen of /b did not compile, so it was left as it was"})
    assert "phone screens of `/a`" in part["said"] and "phone screens left as they were" in part["finding"] and "/b:" in part["finding"]
    assert "phone" not in said({})["said"].lower()
