"""The frame of an application drawn from a design is Smith's to change (2026-10-31).

DITANS drew its own frame: a shell per portal, with its own menu. Every
frame fault there — the account menu cut off by the bar, menu entries that
led nowhere (42 of 67), the arrow over the shell's controls — was fixed by
hand in the drawing's rows, because `write_frame` knew only the platform's
files and nothing bound a drawn menu entry to a screen. Now the drawn shells
and shared drawn components are frame parts, `bind_menu` binds an entry, and
re-projection writes the drawn frame like every other part of the app.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.blueprint.service import BlueprintService
from services.smith import frame_change, reproject, writes
from services.smith.drawn_menu import bind_menu

SHELL = ('"use client";\nexport default function RecruiterShell(props: any) {\n'
         '  return <div><div className="h-[72px] overflow-hidden" data-layer="Top bar">{props.controls}</div>'
         '<main>{props.children}</main></div>;\n}\n')


@pytest.fixture(autouse=True)
def _their_words_ask_for_it(monkeypatch):
    monkeypatch.setattr("services.smith4.turn.asked_for", lambda words, change: True)


def _svc(tmp_path: Path) -> BlueprintService:
    svc = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Jobs", domain="hiring")
    svc.doc["pages"] = [{"id": "PAGE-001", "name": "Find talent", "route": "/find-talent", "purpose": "x"},
                        {"id": "PAGE-002", "name": "Talent pools", "route": "/find-talent/pools", "purpose": "x"}]
    svc.doc["drawnViews"] = [{"key": "shell:D3", "kind": "shell", "name": "RecruiterShell", "portal": "Recruiter",
                              "code": SHELL, "contract": {"data": [], "actions": []},
                              "sample": {"nav": [{"id": "1", "label": "Find talent"},
                                                 {"id": "2", "label": "Pools"}]}}]
    svc.save()
    (tmp_path / "app").mkdir()
    return svc


def test_a_drawn_menu_says_what_each_entry_opens(tmp_path):
    _svc(tmp_path)
    out = bind_menu(str(tmp_path), "recruiter", [])
    assert not out["applied"] and "1 leading nowhere" in out["said"]
    assert '"Find talent" → Find talent (/find-talent)' in out["said"] and '"Pools" → nowhere ✗' in out["said"]


def test_an_entry_is_bound_to_a_screen_as_one_version_and_projected(tmp_path):
    svc = _svc(tmp_path)
    before = svc.doc["version"]
    out = writes.run("bind_menu", {"shell": "Recruiter", "entries": [{"label": "pools", "route": "/find-talent/pools"},
                                                                    {"label": "Saved", "route": "/x"}]},
                     output_dir=str(tmp_path))
    assert out["applied"] and "Bound 1 entry" in out["said"] and "not an entry of this menu" in out["finding"]
    doc = BlueprintService.load(output_dir=str(tmp_path)).doc
    assert doc["version"] == before + 1
    assert doc["drawnViews"][0]["sample"]["nav"][1]["href"] == "/find-talent/pools"
    wrapper = (tmp_path / "app/src/components/DrawnShell.tsx").read_text()
    assert "/find-talent/pools" in wrapper
    assert (tmp_path / "app/src/components/drawn/RecruiterShell.tsx").read_text() == SHELL


def test_a_screen_that_does_not_exist_is_not_bound(tmp_path):
    _svc(tmp_path)
    out = bind_menu(str(tmp_path), "Recruiter", [{"label": "Pools", "route": "/nowhere"}])
    assert not out["applied"] and "is not a screen of this application" in out["finding"]


def test_a_drawn_shell_is_a_frame_part_changed_in_the_drawing(tmp_path):
    svc = _svc(tmp_path)

    class Reply:
        text = json.dumps({"edits": [{"find": 'className="h-[72px] overflow-hidden"',
                                      "replace": 'className="h-[72px]"'}], "rationale": "the menu shows whole"})
    seen = []

    def client(*, system, user, schema):
        seen.append(user)
        return Reply()
    out = frame_change.change_frame(svc, "app/src/components/drawn/RecruiterShell.tsx", "do not cut the account menu off",
                                    app_root=str(tmp_path / "app"), client=client, check=lambda code: [])
    assert out["applied"]
    assert frame_change.DRAWN_NOTE in seen[0]                 # the drawing's classes are kept, hex and all
    doc = BlueprintService.load(output_dir=str(tmp_path)).doc
    assert 'className="h-[72px]"' in doc["drawnViews"][0]["code"] and not doc.get("frameCode")
    with pytest.raises(frame_change.FrameChangeError, match="drawn from the design: `src/components/drawn/RecruiterShell.tsx`"):
        frame_change.change_frame(svc, "src/components/Nope.tsx", "x", app_root=str(tmp_path / "app"),
                                  client=client, check=lambda code: [])


def test_reprojection_writes_the_drawn_frame(tmp_path):
    svc = _svc(tmp_path)
    svc.doc["drawnViews"][0]["code"] = SHELL.replace("overflow-hidden", "")
    reproject._drawn(svc, str(tmp_path / "app"))
    assert "overflow-hidden" not in (tmp_path / "app/src/components/drawn/RecruiterShell.tsx").read_text()


def test_the_catalogue_offers_the_drawn_frame():
    said = next(d for n, d, _a in writes.WRITES if n == "write_frame")
    assert "drawn shell" in said and "src/components/drawn/" in said
    assert any(n == "bind_menu" for n, _d, _a in writes.WRITES)
