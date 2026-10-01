"""Smith changes the app's structure — the frame, the look, the screens — at any size.

SnapIT (2026-09-29): "convert the layout to the Myntra apps layout" was
planned as a new palette and "rebuild the layout of every screen"; the palette
landed, one screen got its dock moved, and the frame was never touched — no
tool could reach it, `restyle` kept typography, density and navigation by
design, and every page change was an edit inside the layout it had. And a
small ask about the frame ("centre the menu", "a search box in the top bar")
had nothing to go to at all.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.blueprint.service import BlueprintService
from services.smith import frame_change, sync_app, tools, writes
from services.smith.frame_change import FrameChangeError, change_frame

LAYOUT = "src/app/(dashboard)/layout.tsx"


def _svc(tmp_path: Path) -> BlueprintService:
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="SnapIT", domain="shopping")
    svc.save()
    return svc


class _Reply:
    def __init__(self, data):
        self.text = json.dumps(data)


class _Client:
    """The frame writer, answering with scripted edits."""
    def __init__(self, *answers):
        self.answers, self.users = list(answers), []

    def __call__(self, *, system, user, schema):
        self.users.append(user)
        return _Reply(self.answers.pop(0))


# --------------------------------------------------------------------------- #
# The frame is the app's to change, at any size
# --------------------------------------------------------------------------- #

def test_a_small_frame_change_is_made_compiled_and_kept(tmp_path):
    svc = _svc(tmp_path)
    app = tmp_path / "app"
    (app / "src/app/(dashboard)").mkdir(parents=True)
    (app / LAYOUT).write_text('<nav className="flex justify-start">menu</nav>\n')
    client = _Client({"edits": [{"find": "justify-start", "replace": "justify-center"}],
                      "rationale": "The menu is centred."})
    compiled = []
    out = change_frame(svc, "app/" + LAYOUT, "centre the menu", app_root=str(app), client=client,
                       check=lambda code: compiled.append(code) or [])
    assert out["applied"] and out["file"] == LAYOUT
    assert "justify-center" in (app / LAYOUT).read_text() and compiled
    rows = svc.doc["frameCode"]
    assert rows == [{"file": LAYOUT, "rationale": "centre the menu",
                     "code": '<nav className="flex justify-center">menu</nav>\n'}]
    assert svc.doc["changeHistory"][-1]["userRequest"] == "centre the menu"


def test_edits_that_do_not_apply_or_compile_are_sent_back(tmp_path):
    svc = _svc(tmp_path)
    app = tmp_path / "app"
    (app / "src/app/(dashboard)").mkdir(parents=True)
    (app / LAYOUT).write_text("<header>bell</header>\n")
    client = _Client({"edits": [{"find": "not there", "replace": "x"}], "rationale": ""},
                     {"edits": [{"find": "bell", "replace": "bell <Search/>"}], "rationale": ""},
                     {"edits": [{"find": "bell", "replace": "bell <form method=\"get\"/>"}], "rationale": "ok"})
    results = iter([["layout.tsx(1,20): error TS2304: Cannot find name 'Search'."], []])
    out = change_frame(svc, LAYOUT, "a search box in the top bar", app_root=str(app), client=client,
                       check=lambda code: next(results))
    assert out["applied"]
    assert "occurs 0 times" in client.users[1] and "Cannot find name 'Search'" in client.users[2]


def test_only_the_frame_is_changed_this_way(tmp_path):
    svc = _svc(tmp_path)
    with pytest.raises(FrameChangeError, match="not part of the frame"):
        change_frame(svc, "src/app/admin/page.tsx", "x", app_root=str(tmp_path / "app"), client=_Client())


def test_an_owned_frame_file_is_never_replaced_by_the_platforms(tmp_path):
    app = tmp_path / "app"
    doc = {"application": {"name": "SnapIT"},
           "frameCode": [{"file": LAYOUT, "rationale": "centre", "code": "OWN LAYOUT"}]}
    sync_app.refresh_frame(app, doc)
    assert (app / LAYOUT).read_text() == "OWN LAYOUT"
    public = (app / "src/components/PublicPageFrame.tsx").read_text()
    assert "LanguageSwitch" in public                     # the platform's, current
    assert sync_app.refresh_frame(app, doc) == []         # in step: nothing written


def test_the_platform_frame_is_filled_with_the_apps_name(tmp_path):
    sync_app.refresh_frame(tmp_path, {"application": {"name": "SnapIT"}})
    assert "__APP_NAME__" not in (tmp_path / LAYOUT).read_text()


# --------------------------------------------------------------------------- #
# The look is more than colours; the screens can be laid out again
# --------------------------------------------------------------------------- #

def test_a_design_change_reaches_the_shell_not_only_the_tokens(tmp_path, monkeypatch):
    import services.blueprint.projection as proj
    called = []
    for name in ("project_design_tokens", "project_navigation", "project_shell_identity"):
        monkeypatch.setattr(proj, name, lambda doc, root, n=name: called.append(n) or {"files": [n]})
    monkeypatch.setattr(sync_app, "refresh_frame", lambda root, doc: called.append("frame") or ["frame"])
    svc = _svc(tmp_path)
    files = writes._reproject(svc, str(tmp_path / "app"), "designSystem")
    assert called == ["project_design_tokens", "project_navigation", "project_shell_identity", "frame"]
    assert files == ["project_design_tokens", "project_navigation", "project_shell_identity", "frame"]


def test_several_screens_are_laid_out_again_as_one_change(tmp_path, monkeypatch):
    import services.blueprint.ui_engineer as ue
    from services.blueprint import app_sdk
    from services.smith import compose
    svc = _svc(tmp_path)
    svc.doc["pages"] = [{"id": f"PAGE-00{i}", "name": n, "route": r, "purpose": "x"}
                        for i, (n, r) in enumerate([("Home", "/"), ("Search", "/search"), ("Saved", "/saved")], 1)]
    svc.doc["pageCode"] = [{"page": f"PAGE-00{i}", "rationale": "first", "load": "export {}", "view": f"old {i}"}
                           for i in (1, 2, 3)]
    svc.save()
    before = svc.doc["version"]
    monkeypatch.setattr(ue, "ensure_sdk", lambda doc, root: None)
    monkeypatch.setattr(app_sdk, "project_code_pages", lambda doc, root: [])
    seen = []

    def fake_compose(doc, page, root, client, *, brief, relayout_of, **kw):
        seen.append((page["route"], relayout_of["view"], brief))
        if page["route"] == "/saved":
            raise ue.CompileError("TS2322")
        return {"page": page["id"], "rationale": "myntra", "load": "export {}", "view": f"new {page['route']}"}, []
    monkeypatch.setattr(ue, "compose_page", fake_compose)
    out = compose.relayout_pages(svc, ["/", "/search", "/saved"], app_root=str(tmp_path / "app"),
                                 request="like Myntra", client_for=lambda: object())
    assert sorted(r for r, _v, _b in seen) == ["/", "/saved", "/search"]
    assert all(b == "like Myntra" for _r, _v, b in seen)
    assert out["done"] == ["/", "/search"] and "did not compile" in out["failed"]["/saved"]
    assert svc.doc["version"] == before + 1               # one change, one undo
    views = {r["page"]: r["view"] for r in svc.doc["pageCode"]}
    assert views == {"PAGE-001": "new /", "PAGE-002": "new /search", "PAGE-003": "old 3"}


def test_a_whole_relayout_is_asked_as_a_fresh_layout_holding_what_the_page_does():
    from services.blueprint.ui_engineer import plan_prompt, user_prompt
    doc = {"application": {"name": "SnapIT"}, "pages": []}
    page = {"id": "PAGE-001", "route": "/", "name": "Home", "purpose": "x"}
    text = user_prompt(doc, page, brief="like Myntra", relayout_of={"load": "L", "view": "<Btn/>"})
    assert "LAID OUT AGAIN FROM THE START" in text and "<Btn/>" in text and "WITH EDITS" not in text
    assert "like Myntra" in plan_prompt(doc, page, "like Myntra")


# --------------------------------------------------------------------------- #
# The loop is told which size of tool fits which size of ask
# --------------------------------------------------------------------------- #

def test_the_catalogue_offers_every_size_of_structural_change():
    for name in ("write_frame", "rewrite_pages", "write_page_code", "write_section"):
        assert tools.is_tool(name) and tools.is_write(name), name
    shown = tools.render()
    assert "`write_frame` (file: string, brief: string)" in shown
    assert "`write_page_code` (route: string, brief: string, whole: boolean)" in shown
    assert "src/app/(dashboard)/MobileTabBar.tsx" in shown


def test_the_prompt_sizes_the_change_to_the_ask():
    from services.smith import loop
    from services.smith.verbs import VERB_HELP
    assert "A STRUCTURAL ASK IS THE WHOLE STRUCTURE" in loop._PROMPT
    assert "A SMALL CHANGE TO THE FRAME IS STILL A CHANGE YOU CAN MAKE" in loop._PROMPT
    assert "Colours ONLY" in VERB_HELP["restyle"]
    loop._PROMPT.format(ask="a", history="", ctx="", observations="", catalogue="")
