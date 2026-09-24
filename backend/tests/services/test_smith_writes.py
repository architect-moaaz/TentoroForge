"""Smith writes code through the build's seam — §0 of `2026-09-24-smith-as-a-loop`.

`write_page_code` is a primitive of the loop, not a verb: the first
interpretation call never picks it, the loop does, after reading. Every oracle
on the path — the compiler, the contract, the "did the code draw it" check —
comes back as a finding the loop can act on.
"""
from __future__ import annotations

import pytest

from services.smith import tools, writes
from services.smith.verbs import REQUIRED_BY_VERB
from tests.services.test_smith_loop import _Chooser, _Writes, _repo, _session, _understanding


def test_write_page_code_is_a_tool_and_not_a_verb():
    assert tools.is_tool("write_page_code") and tools.is_write("write_page_code")
    assert "write_page_code" not in REQUIRED_BY_VERB
    assert "Changing code" in tools.render()


def test_a_page_that_does_not_compile_is_a_finding_not_a_dead_end(tmp_path, monkeypatch):
    """Three compile rounds failed. That is the build's most trusted oracle
    speaking, so the loop hears it — and here tries a sharper brief."""
    import services.smith.compose as compose_mod
    from services.smith.compose import ComposeError

    _repo(tmp_path)
    (tmp_path / "app").mkdir()
    briefs: list[str] = []

    def fake_recode(svc, route, *, app_root, request, wanted=(), **kw):
        briefs.append(request)
        if len(briefs) == 1:
            raise ComposeError("the new /rentals did not compile, so nothing was changed: "
                               "view.tsx(16,7): TS2322 Type '\"accepted\"' is not assignable")
        return {"applied": True, "committed": ["PAGE-004"], "version": 9, "reason": "", "missing": []}

    monkeypatch.setattr(compose_mod, "recode_page", fake_recode)
    # Only /rentals is a coded page here; step one (a rename of src/a.json)
    # must stay a rename, not be rerouted to the composer.
    monkeypatch.setattr(compose_mod, "_page_for_route",
                        lambda doc, r: {"id": "PAGE-004", "route": r} if r == "/rentals" else None)
    monkeypatch.setattr(compose_mod, "code_row",
                        lambda doc, pid: {"page": pid, "view": "x"} if pid == "PAGE-004" else None)
    monkeypatch.setattr("services.blueprint.service.BlueprintService.load",
                        classmethod(lambda cls, output_dir: type("S", (), {"doc": {"pages": []}})()))

    chooser = _Chooser({"tool": "write_page_code",
                        "args": {"route": "/rentals", "brief": "add accepted to ATTENTION_STATUSES"}, "why": ""},
                       {"tool": "write_page_code",
                        "args": {"route": "/rentals", "brief": "widen the Rental status union, then add accepted"}, "why": ""})
    session = _session(tmp_path,
                       understanding=_understanding(target_file="src/a.json", element_label="A", new_value="A"),
                       move=_Writes(tmp_path), chooser=chooser)

    result = session.run_iteration("accepted rentals should need attention too")

    heard = chooser.seen[1][-1]
    assert heard.status == "finding" and "TS2322" in heard.said
    assert len(briefs) == 2
    assert result.status == "resolved"
    assert "Rewrote **/rentals** (version 9)" in result.answer


def test_a_route_with_no_page_says_so_and_names_compose_route(tmp_path, monkeypatch):
    monkeypatch.setattr("services.blueprint.service.BlueprintService.load",
                        classmethod(lambda cls, output_dir: type("S", (), {"doc": {"pages": [{"route": "/tools"}]}})()))
    out = writes.write_page_code(str(tmp_path), "/nowhere", "anything")
    assert not out["applied"]
    assert "no page at `/nowhere`" in out["finding"] and "compose_route" in out["finding"]


def test_code_that_does_not_draw_what_the_brief_asked_is_a_finding(tmp_path, monkeypatch):
    import services.smith.compose as compose_mod
    monkeypatch.setattr(compose_mod, "recode_page", lambda *a, **k: {
        "applied": True, "committed": ["PAGE-004"], "version": 3, "reason": "", "missing": ["phone"]})
    monkeypatch.setattr(compose_mod, "_page_for_route", lambda doc, r: {"id": "PAGE-004", "route": r})
    monkeypatch.setattr(compose_mod, "code_row", lambda doc, pid: {"page": pid, "view": "x"})
    monkeypatch.setattr("services.blueprint.service.BlueprintService.load",
                        classmethod(lambda cls, output_dir: type("S", (), {"doc": {"pages": []}})()))
    out = writes.write_page_code(str(tmp_path), "/profile", "show the phone")
    assert out["applied"] and "does not draw: phone" in out["finding"]


def test_a_missing_brief_is_refused_before_anything_runs(tmp_path):
    out = writes.write_page_code(str(tmp_path), "/x", "")
    assert not out["applied"] and "needs both" in out["finding"]


def test_a_verb_whose_composer_refused_is_a_finding_the_loop_hears(tmp_path, monkeypatch):
    """`compose_route` on a coded page that did not compile used to end the
    turn as `needs_user` with the error in a bubble. Same oracle, same rule."""
    import services.smith.compose as compose_mod
    from services.smith.compose import ComposeError

    _repo(tmp_path)
    (tmp_path / "app").mkdir()
    calls: list[str] = []

    def fake_recode(svc, route, *, app_root, request, wanted=(), **kw):
        calls.append(request)
        if len(calls) == 1:
            raise ComposeError("the new /rentals did not compile: TS2322")
        return {"applied": True, "committed": ["PAGE-004"], "version": 2, "reason": "", "missing": []}

    monkeypatch.setattr(compose_mod, "recode_page", fake_recode)
    monkeypatch.setattr(compose_mod, "_page_for_route", lambda doc, r: {"id": "PAGE-004", "route": r})
    monkeypatch.setattr(compose_mod, "code_row", lambda doc, pid: {"page": pid, "view": "x"})
    monkeypatch.setattr("services.blueprint.service.BlueprintService.load",
                        classmethod(lambda cls, output_dir: type("S", (), {"doc": {"pages": []}})()))
    monkeypatch.setattr(compose_mod, "prepare_capabilities",
                        lambda *a, **k: {"declared": [], "created": []})

    chooser = _Chooser({"tool": "write_page_code",
                        "args": {"route": "/rentals", "brief": "sharper"}, "why": ""})
    session = _session(tmp_path,
                       understanding=_understanding(verb="compose_route", route="/rentals",
                                                    target_file="/rentals"),
                       move=_Writes(tmp_path), chooser=chooser)

    result = session.run_iteration("lay out /rentals again")

    assert chooser.seen, "the compile failure ended the turn instead of being heard"
    assert chooser.seen[0][0].status == "finding" and "TS2322" in chooser.seen[0][0].said
    assert len(calls) == 2 and result.status == "resolved"
