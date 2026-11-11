"""A card about one record is drawn while there is one.

A new DITANS candidate's home (QA 2026-11-06) showed a next step, an
invitation and an unfinished application as cards of empty words and
wordless buttons: the drawing shows one of each, the view drew them always,
and the page could only give an object of empty strings when there was none.
"""
from __future__ import annotations

import re

from services.drawn import params as P
from services.drawn.contract import props_type

HOME = """export default function HomeView() {
  return (
    <div className="flex flex-col bg-[#ffffff]">
      <div className="flex flex-col" data-layer="Head">
        <p className="text-[30px]">Good morning, Sara</p>
      </div>
      <div className="flex flex-col" data-layer="Main col">
        <div className="flex flex-col bg-[#e6fbf6]" data-layer="Next step">
          <p className="text-[12px]">YOUR NEXT BEST STEP</p>
          <div className="flex flex-col">
            <p className="text-[22px]">Pay for DataFlow verification</p>
            <div className="w-[200px] h-[48px] bg-[#0443fa]" data-layer="Pay">
              <p className="text-[14px] text-[#ffffff]">Pay AED 450</p>
            </div>
            <div className="w-[200px] h-[48px]" data-layer="Not now">
              <p className="text-[14px]">Not now</p>
            </div>
          </div>
        </div>
        <div className="flex flex-col bg-[#ffffff] border-[1px] border-[#e1e8eb]" data-layer="Invitation">
          <p className="text-[16px]">Invitations to apply</p>
          <p className="text-[14px]">Saudi German Hospital · Charge Nurse</p>
        </div>
      </div>
    </div>
  );
}
"""


def _home():
    answer = {"contract": {"data": [
                  {"name": "nurse", "kind": "record", "label": "Nurse", "fields": [
                      {"name": "greeting", "label": "Greeting", "type": "string"}]},
                  {"name": "nextStep", "kind": "record", "label": "Next step", "fields": [
                      {"name": "title", "label": "Title", "type": "string"},
                      {"name": "payLabel", "label": "Pay label", "type": "string"}]},
                  {"name": "invitation", "kind": "record", "label": "Invitation", "fields": [
                      {"name": "summary", "label": "Summary", "type": "string"}]}],
                  "actions": [{"name": "onPay", "label": "Pay", "kind": "run", "nodes": ["9"]},
                              {"name": "onNotNow", "label": "Not now", "kind": "run", "nodes": ["11"]}]},
              "lists": [], "inputs": [], "shows": [],
              "values": [{"node": "3", "expr": "props.nurse.greeting"},
                         {"node": "8", "expr": "props.nextStep.title"},
                         {"node": "10", "expr": "props.nextStep.payLabel"},
                         {"node": "15", "expr": "props.invitation.summary"}]}
    out, problems = P.apply(HOME, answer, "HomeView")
    assert problems == [], problems
    return out


def _guarded(code: str, record: str) -> str:
    """The markup drawn only while `record` is there."""
    start = code.index("{present(props." + record + ") && (")
    return code[start:re.compile(r"\n\s*\)\}").search(code, start).start()]


def test_each_records_card_is_drawn_only_while_there_is_one():
    code = _home()["code"]
    step = _guarded(code, "nextStep")
    # the whole card: its heading and its unbound "Not now" go with it
    assert 'data-layer="Next step"' in step and "YOUR NEXT BEST STEP" in step and "props.onNotNow()" in step
    assert "Invitations to apply" not in step, "and nothing about another record"
    invitation = _guarded(code, "invitation")
    assert 'data-layer="Invitation"' in invitation and "Invitations to apply" in invitation
    assert "present(props.nurse)" not in code, "a page's head is not a card: it has no box of its own"
    assert code.count("function present(") == 1, "the view carries what it asks"


def test_a_record_is_there_when_anything_in_it_is():
    """A new job has no id yet, only its title and "Draft": its header stays."""
    import subprocess
    probe = P.PRESENT.replace("record: unknown", "record").replace("): boolean", ")").replace(
        " as Record<string, unknown>", "") + """
console.log(JSON.stringify([present(null), present({id: "", title: "", done: false, tags: []}),
                            present({id: "", title: "Charge Nurse"}), present({id: "j-1", title: ""})]));"""
    out = subprocess.run(["node", "-e", probe], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[false,false,true,true]"


def test_the_page_may_give_none_and_is_told_so():
    out = _home()
    typed = props_type("HomeView", out["contract"], code=out["code"])
    assert "nextStep: { id: string; title: string; payLabel: string } | null;" in typed
    assert "invitation: { id: string; summary: string } | null;" in typed
    assert "nurse: { id: string; greeting: string };" in typed
    # read from the stored code, the page writer's type says the same
    assert "| null" not in props_type("HomeView", out["contract"])


def test_a_record_spread_over_the_whole_screen_stays_required():
    answer = {"contract": {"data": [{"name": "job", "kind": "record", "label": "Job", "fields": [
                  {"name": "title", "label": "Title", "type": "string"},
                  {"name": "summary", "label": "Summary", "type": "string"}]}], "actions": []},
              "lists": [], "inputs": [], "shows": [],
              "values": [{"node": "3", "expr": "props.job.title"}, {"node": "15", "expr": "props.job.summary"}]}
    out, problems = P.apply(HOME, answer, "JobView")
    assert problems == [], problems
    assert "present(props.job)" not in out["code"], "the screen itself is never hidden"
    assert "| null" not in out["code"]


def test_a_line_in_the_screens_header_does_not_take_the_header_with_it():
    """A 90-day check-in with no placement lost "Is the job what you were promised?"
    with the placement's line above it (DITANS 2026-11-06)."""
    answer = {"contract": {"data": [{"name": "nextStep", "kind": "record", "label": "Next step", "fields": [
                  {"name": "title", "label": "Title", "type": "string"}]},
                  {"name": "invitation", "kind": "record", "label": "Invitation", "fields": [
                      {"name": "summary", "label": "Summary", "type": "string"}]},
                  {"name": "placement", "kind": "record", "label": "Placement", "fields": [
                      {"name": "line", "label": "Line", "type": "string"}]}], "actions": []},
              "lists": [], "inputs": [], "shows": [],
              "values": [{"node": "3", "expr": "props.placement.line"},
                         {"node": "8", "expr": "props.nextStep.title"},
                         {"node": "15", "expr": "props.invitation.summary"}]}
    out, problems = P.apply(HOME, answer, "CheckInView")
    assert problems == [], problems
    assert "present(props.placement)" not in out["code"]
    assert "{present(props.nextStep) && (" in out["code"] and "{present(props.invitation) && (" in out["code"]
