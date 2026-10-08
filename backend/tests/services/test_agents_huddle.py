"""The agents that own the parts a question touches settle it together (2026-10-08).

The observer sent each finding back to the node that wrote it, and only to
it: 220 findings across 258 local runs were still wrong after both rounds,
many because the fix lay in another agent's part. A request for a change to
another agent's part was collected and dropped. The decisions everything is
built on were judged by one critic, never by the agents building on them.

A huddle: the owners each say what they see, side by side; the observer,
chairing, decides; the decision is written down, binding, and each owner that
must act is briefed through the seam Smith re-decides a section with. Who
takes part is read from the build — who owns what, who reads what — never
listed.
"""
from __future__ import annotations

import json
import re
import types

import pytest

from services.huddle import deadlocks, room
from services.huddle.room import Huddle, Room


# --------------------------------------------------------------------------- #
# Who takes part — read from the build
# --------------------------------------------------------------------------- #

def test_a_big_decision_is_one_many_agents_build_on():
    big = room.big_decisions()
    assert set(big) == {"data_model", "page_contracts", "workflows", "security"}, big
    from services.blueprint.orchestrator import DAG
    assert all(not DAG[k].fanout for k in big), "a decision made a page or a record at a time is not one"
    assert "requirements" not in big, "the person's own requirements are reviewed by the person"


def test_a_big_decision_is_reviewed_by_those_most_of_the_build_stands_on():
    assert room.builders_of("data_model") == ["page_design", "workflow", "security"]
    assert "security" in room.builders_of("workflows"), "who may run a process is the permissions' call"
    for node in room.big_decisions():
        people = room.builders_of(node, {"designSources": []})
        assert 0 < len(people) <= room.MAX_PARTICIPANTS
        from services.blueprint.orchestrator import DAG
        assert DAG[node].agent not in people, "an agent does not review itself"
        assert "figma_intelligence" not in people, "no design is connected: that agent has no work here"


def test_the_owners_of_what_a_finding_names_are_called():
    text = "PAGE-004 declares edit, but FLOW-007 is refused for the role by PERM-012"
    assert room.owners_named(text, also="page_design") == ["page_design", "workflow", "security"]
    assert room.owners_named("no data.constraints range for age", also="data_model") == ["data_model"]
    assert room.owners_named("", also="analytics") == ["analytics"]


def test_a_decision_is_carried_out_by_the_node_that_decides_that_part_once():
    assert room.node_for("page_design") == "page_contracts"
    assert room.node_for("workflow") == "workflows", "not the per-process step writer"
    assert room.node_for("page_design", hint="app_flows") == "app_flows", "the node that raised it, when it is theirs"
    assert room.node_for("workflow", hint="app_flows") == "workflows"


# --------------------------------------------------------------------------- #
# The room
# --------------------------------------------------------------------------- #

class _Reply:
    def __init__(self, data):
        self.text = json.dumps(data)
        self.usage = None


class FakeModel:
    """Positions by who is asked; the chair's reply as given."""

    def __init__(self, chair: dict, fail: set[str] = frozenset()):
        self.chair, self.fail, self.calls = chair, set(fail), []

    def __call__(self, *, system, user, schema):
        self.calls.append(system)
        if schema is room.CHAIR_SCHEMA:
            return _Reply(self.chair)
        agent = re.search(r"Forge's (\w+) agent", system).group(1)
        if agent in self.fail:
            raise RuntimeError("no answer")
        return _Reply({"view": f"{agent} sees it", "change": f"{agent} would change its part",
                       "needs": [{"agent": "security", "what": "grant it"}]})


DOC = {"requirements": [{"id": "REQ-001", "description": "Admins manage products."}],
       "roles": [], "data": {"entities": []}, "pages": []}


def _room(tmp_path, model, events):
    return Room(tmp_path, model, emit=lambda kind, data: events.append((kind, data)))


def test_the_owners_speak_side_by_side_and_the_chair_decides(tmp_path):
    events = []
    chair = {"settled": True, "decision": "Admins may run Update Product.", "reason": "REQ-001",
             "briefs": [{"agent": "security", "changes": True, "brief": "Confirm PERM-012 for Admin."},
                        {"agent": "page_design", "changes": False, "brief": "No change to PAGE-004."},
                        {"agent": "stranger", "changes": True, "brief": "not in the room"}], "question": ""}
    h = _room(tmp_path, FakeModel(chair), events).convene(
        DOC, kind="deadlock", topic="Admin is refused Update Product", participants=["page_design", "workflow",
                                                                                     "security", "analytics"],
        evidence="403 on FLOW-007")
    assert h.participants == ["page_design", "workflow", "security"], "at most three"
    assert [p["agent"] for p in h.positions] == h.participants
    assert h.status == "decided" and h.decision["decision"] == "Admins may run Update Product."
    assert h.briefs == {"security": "Confirm PERM-012 for Admin."}, \
        "only agents in the room whose part changes are briefed"
    phases = [d["phase"] for k, d in events if k == "huddle"]
    assert phases == ["start", "position", "position", "position", "decided"]
    kept = room.load(tmp_path, h.id)
    assert kept is not None and kept.decision == h.decision, "the record is kept"
    assert h.id == "HUD-001" and room._next_id(tmp_path) == "HUD-002"


def test_a_conflict_the_requirements_do_not_settle_is_a_question_not_a_brief(tmp_path):
    chair = {"settled": False, "decision": "", "reason": "", "question": "May a shopper cancel a shipped order?",
             "briefs": [{"agent": "workflow", "brief": "x"}]}
    h = _room(tmp_path, FakeModel(chair), []).convene(DOC, kind="deadlock", topic="t",
                                                       participants=["workflow"], evidence="e")
    assert h.status == "deadlock" and h.briefs == {}
    assert h.decision["question"] == "May a shopper cancel a shipped order?"


def test_an_agent_that_cannot_answer_is_recorded_not_invented(tmp_path):
    chair = {"settled": True, "decision": "d", "reason": "r", "question": "", "briefs": []}
    model = FakeModel(chair, fail={"workflow"})
    h = _room(tmp_path, model, []).convene(DOC, kind="deadlock", topic="t",
                                           participants=["workflow", "security"], evidence="e")
    silent = next(p for p in h.positions if p["agent"] == "workflow")
    assert silent["unavailable"] and not silent["view"]
    assert h.status == "decided"
    nobody = _room(tmp_path, FakeModel(chair, fail={"workflow"}), []).convene(
        DOC, kind="deadlock", topic="t", participants=["workflow"], evidence="e")
    assert nobody.status == "deadlock", "no voice in the room, no decision"


def test_the_room_speaks_the_language_of_no_one_application():
    for text in (room.POSITION_SYSTEM, room.CHAIR_SYSTEM):
        for word in ("shop", "cart", "product", "order", "patient", "invoice", "booking"):
            assert not re.search(rf"\b{word}s?\b", text.lower()), word


# --------------------------------------------------------------------------- #
# The decision, carried out
# --------------------------------------------------------------------------- #

@pytest.fixture()
def svc(tmp_path):
    from services.blueprint.service import BlueprintService
    return BlueprintService.create(output_dir=tmp_path, app_id="app_1", name="Shop", domain="Commerce")


def test_a_decision_binds_and_each_owner_is_briefed_through_its_node(svc, monkeypatch):
    asked = []

    def fake_rerun(svc_, node, *, brief, request, interpretation, **kw):
        asked.append((node, brief))
        return [types.SimpleNamespace(natural_key="PERM:admin:update")], None

    monkeypatch.setattr("services.smith.section_change.rerun", fake_rerun)
    h = Huddle(id="HUD-001", kind="deadlock", topic="Admin is refused", trigger={}, participants=["security"],
               status="decided", decision={"decision": "Admins may update products.", "reason": "REQ-001",
                                           "question": ""},
               briefs={"security": "Confirm PERM-012 for Admin."})
    room.carry_out(svc, h)
    rows = [d for d in svc.doc.get("decisions") or [] if d.get("source") == "huddle"]
    assert rows and rows[0]["decision"] == "Admins may update products." and rows[0]["binding"]
    assert asked == [("security", asked[0][1])] and "Confirm PERM-012 for Admin." in asked[0][1]
    assert "HUD-001" in asked[0][1], "the owner is told which huddle decided"
    assert any("security (security) changed PERM:admin:update" in o for o in h.outcome)


def test_a_question_is_not_carried_out(svc, monkeypatch):
    monkeypatch.setattr("services.smith.section_change.rerun",
                        lambda *a, **k: pytest.fail("a deadlock briefs nobody"))
    h = Huddle(id="HUD-002", kind="deadlock", topic="t", trigger={}, participants=["workflow"],
               status="deadlock", decision={"decision": "", "reason": "", "question": "May they?"})
    room.carry_out(svc, h)
    assert not [d for d in svc.doc.get("decisions") or [] if d.get("source") == "huddle"]


def test_an_owner_that_refuses_leaves_its_part_and_says_so(svc, monkeypatch):
    from services.smith.section_change import SectionChangeError

    def refuse(*a, **k):
        raise SectionChangeError("refused twice")
    monkeypatch.setattr("services.smith.section_change.rerun", refuse)
    h = Huddle(id="HUD-003", kind="deadlock", topic="t", trigger={}, participants=["workflow"],
               status="decided", decision={"decision": "d", "reason": "r", "question": ""},
               briefs={"workflow": "b"})
    room.carry_out(svc, h)
    assert any("was not changed: refused twice" in o for o in h.outcome)


# --------------------------------------------------------------------------- #
# After a build
# --------------------------------------------------------------------------- #

def test_what_a_build_leaves_undecided_becomes_huddles_most_owners_first():
    report = types.SimpleNamespace(
        unrepaired={"page_contracts": "PAGE-004 declares edit, but FLOW-007 is refused by PERM-012",
                    "data_model": "age has no range"},
        blocked_because={"business_rules": "confidence 0.2 — needs RULE-003 settled"},
        change_requests=[{"section": "permissions", "reason": "Admin needs FLOW-007",
                          "raisedBy": "observer:workflows"},
                         {"section": "permissions", "reason": "Admin needs FLOW-007",
                          "raisedBy": "observer:workflows"}])
    got = deadlocks.candidates(report)
    assert got[0]["participants"] == ["page_design", "workflow", "security"], "the most owners first"
    kinds = [c["kind"] for c in got]
    assert kinds.count("change_request") == 1, "the same request twice is one huddle"
    cr = next(c for c in got if c["kind"] == "change_request")
    assert cr["participants"] == ["security", "workflow"], "the owner asked, and who asked"
    assert {c["kind"] for c in got} == {"unrepaired", "blocked", "change_request"}


def test_an_application_can_be_built_without_huddles(svc, monkeypatch):
    svc.doc["application"]["huddles"] = False
    monkeypatch.setattr(deadlocks, "client", lambda: pytest.fail("no huddle is convened"))
    report = types.SimpleNamespace(unrepaired={"data_model": "x"}, blocked_because={}, change_requests=[])
    assert deadlocks.settle_deadlocks(svc, str(svc.output_dir), report) == []


# --------------------------------------------------------------------------- #
# A big decision, reviewed by those who build on it
# --------------------------------------------------------------------------- #

class FakeRoom:
    def __init__(self, briefs):
        self.briefs, self.calls = briefs, []

    def convene(self, doc, *, kind, participants, owner, topic, evidence, trigger):
        self.calls.append({"kind": kind, "participants": participants, "owner": owner, "node": trigger["node"]})
        return Huddle(id=f"HUD-00{len(self.calls)}", kind=kind, topic=topic, trigger=trigger,
                      participants=participants, status="decided",
                      decision={"decision": "d", "reason": "r", "question": ""}, briefs=dict(self.briefs))


def _observe(observer, node, agent, doc=None):
    return observer.observe(node, agent=agent, subjects=[""], doc=doc or {"application": {}}, mode="all")


def test_the_builders_review_a_big_decision_once_and_its_author_is_sent_the_brief():
    from services.blueprint.observer import HUDDLE_EDGE, Observer
    fake = FakeRoom({"data_model": "Add a status field to Order.", "security": "Guard Order by owner."})
    watcher = Observer(huddle=fake)
    obs = _observe(watcher, "data_model", "data_model")
    assert fake.calls == [{"kind": "review", "participants": ["page_design", "workflow", "security"],
                           "owner": "data_model", "node": "data_model"}]
    mine = [f for f in obs.findings.get("", []) if f.edge == HUDDLE_EDGE]
    assert [f.detail for f in mine] == ["HUD-001: Add a status field to Order."], \
        "the decision's author gets the brief, through the repair loop"
    theirs = [f for f in obs.deferred if f.edge == HUDDLE_EDGE]
    assert theirs and theirs[0].section in ("permissions", "roles", "security"), \
        "another agent's brief travels on as a change request"
    _observe(watcher, "data_model", "data_model")
    assert len(fake.calls) == 1, "its repair is judged by the critic, not reviewed again"


def test_only_a_big_decision_is_reviewed_and_never_when_huddles_are_off():
    from services.blueprint.observer import Observer
    fake = FakeRoom({})
    watcher = Observer(huddle=fake)
    _observe(watcher, "business_rules", "business_rules")
    assert fake.calls == [], "a decision few agents build on is the critic's alone"
    _observe(watcher, "security", "security", {"application": {"huddles": False}})
    assert fake.calls == []


def test_the_person_overrules_and_their_words_become_the_decision(svc, tmp_path):
    h = Huddle(id="HUD-004", kind="deadlock", topic="Who may cancel a shipped order", trigger={},
               participants=["workflow"], status="decided",
               decision={"decision": "Nobody may.", "reason": "RULE-006", "question": ""})
    room.save(svc.output_dir, h)
    room.record_decision(svc, h)
    got = room.overrule(svc, "HUD-004", "  Admins may, within a day.  ")
    assert got.status == "overruled" and got.decision["decision"] == "Admins may, within a day."
    theirs = [d for d in svc.doc["decisions"] if d.get("decision") == "Admins may, within a day."]
    agents = [d for d in svc.doc["decisions"] if d.get("decision") == "Nobody may."]
    assert theirs and theirs[0]["approvedBy"] == "user" and theirs[0]["source"] == "user"
    assert agents and agents[0]["status"] == "DEPRECATED" and theirs[0]["supersedes"] == agents[0]["id"], \
        "the person's decision supersedes the agents' — a change of mind, kept as one"
    said = room.ask(got)
    assert "HUD-004" in said and "Nobody may." in said and "Admins may, within a day." in said
    with pytest.raises(ValueError):
        room.overrule(svc, "HUD-004", "   ")
    with pytest.raises(KeyError):
        room.overrule(svc, "HUD-999", "x")
