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
from tests.services._loop_fixtures import _Chooser, _Writes, _repo, _session, _understanding


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


# --------------------------------------------------------------------------- #
# write_section — the seam every change verb uses, with the loop choosing
# --------------------------------------------------------------------------- #

def test_write_section_is_a_tool_and_its_map_holds_against_the_dag():
    from services.blueprint.agent_contract import AGENT_REGISTRY
    from services.blueprint.orchestrator import DAG
    assert tools.is_write("write_section") and "write_section" not in REQUIRED_BY_VERB
    for section, node in writes.SECTION_NODE.items():
        assert node in DAG, (section, node)
        assert section in AGENT_REGISTRY[DAG[node].agent].writes, (section, node)


def test_a_section_the_owning_agent_refuses_is_a_finding(tmp_path, monkeypatch):
    import services.smith.section_change as sc
    from services.smith.section_change import SectionChangeError
    monkeypatch.setattr("services.blueprint.service.BlueprintService.load",
                        classmethod(lambda cls, output_dir: type("S", (), {"doc": {"version": 3}})()))
    monkeypatch.setattr(sc, "record_requirement", lambda svc, text, owner: {"id": "REQ-9"})
    def refuse(*a, **k):
        raise SectionChangeError("refused 2 times and nothing has been changed. The last reason was: ContractViolation")
    monkeypatch.setattr(sc, "rerun", refuse)
    out = writes.write_section(str(tmp_path), "apis", "make GET /x take a range")
    assert not out["applied"] and "apis was not changed" in out["finding"] and "ContractViolation" in out["finding"]


def test_a_section_change_is_committed_and_reprojected(tmp_path, monkeypatch):
    import services.smith.section_change as sc
    from services.blueprint.agent_contract import ArtifactProposal
    svc = type("S", (), {"doc": {"version": 7}})()
    monkeypatch.setattr("services.blueprint.service.BlueprintService.load", classmethod(lambda cls, output_dir: svc))
    monkeypatch.setattr(sc, "record_requirement", lambda s, text, owner: {"id": "REQ-9"})
    briefs: list[str] = []
    def rerun(s, node, *, brief, request, subject, interpretation, reasoning, app_root, say):
        briefs.append((node, brief)); s.doc["version"] = 8
        return [ArtifactProposal("data.entities", "nurse", {"name": "Colleague"})], None
    monkeypatch.setattr(sc, "rerun", rerun)
    monkeypatch.setattr("services.smith.entity_change._project_data", lambda s, root: ["app/src/db/schema/nurses.ts"])
    out = writes.write_section(str(tmp_path), "data.entities", "rename Nurse to Colleague")
    assert out["applied"] and out["version"] == 8 and "nurse" in out["said"]
    assert out["touched"] == ["app/src/db/schema/nurses.ts"]
    assert briefs[0][0] == "entity_fields" and "THIS IS A CHANGE" in briefs[0][1]


def test_an_unknown_section_names_the_ones_there_are(tmp_path):
    out = writes.write_section(str(tmp_path), "nowhere", "x")
    assert not out["applied"] and "data.entities" in out["finding"] and "apis" in out["finding"]


def test_the_three_refusals_now_go_through_write_section(tmp_path, monkeypatch):
    from services.smith4 import verbs as v4
    from services.smith4.verbs import Ctx, section_write
    assert all(v4.PERFORM[v] is section_write for v in ("rename_entity", "change_field_type", "edit_api"))
    calls: list[tuple] = []
    monkeypatch.setattr(writes, "write_section", lambda out, section, brief, **k:
                        calls.append((section, brief)) or {"applied": True, "said": "Changed.", "finding": "", "touched": []})
    monkeypatch.setattr("services.smith.entity_change.consequences", lambda doc, ref: {"pages": ["Nurse List"], "workflows": []})
    ctx = Ctx(output_dir=str(tmp_path), project_id="p", message="", ask="")
    out = section_write(ctx, {"verb": "rename_entity", "entity": "Nurse", "new_value": "Colleague"})
    assert out.status == "resolved" and calls[0][0] == "data.entities" and "Colleague" in calls[0][1]
    assert "Nurse List" in out.said                     # what still says the old name
    section_write(ctx, {"verb": "edit_api", "api": "GET /api/x", "change": "take a range"})
    assert calls[1][0] == "apis" and "GET /api/x" in calls[1][1]
