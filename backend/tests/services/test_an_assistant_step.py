"""A workflow can hand one step to an assistant (the "agent step").

The step type is `agent_step`: for a judgement that needs LOOKUPS across records, which the cheap `ai_*` steps cannot do.
The assistant is one of the app's own, or is drawn from a short brief by the build's `workflow_agents` stage; it hands
back a structured result and the workflow carries on. This file pins the build side of it, on a VET-clinic Blueprint
(`fixtures/vet_clinic_blueprint.json`: the clinic's entities from its generated schema, its workflows by contract):

* the step type is registered once and every copy agrees;
* Smith is told when to choose it (and only the workflow-steps author is told);
* the apply gate takes the vet triage step and refuses each broken variant with a sentence the author can answer;
* the `workflow_agents` stage makes the workflow-only assistant: reads for what the brief names, exactly the workflows it
  names as changes, a focused prompt, no memory, no hand-over; saves it where the install finds it; writes its id back;
  and a rebuild neither duplicates it nor resets one a builder has edited;
* the compile step carries `workflowOnly`.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from services.agent_runtime_config import compile_agent
from services.agent_suggest import BriefError, agent_for_brief, resolve_brief_tools
from services.blueprint import agent_steps
from services.blueprint.agent_contract import (
    AgentResult, ArtifactProposal, InvalidWorkflowStep, apply_agent_result, check_workflow_steps,
)
from services.blueprint.orchestrator import DAG, SERVICE_HANDLERS, levels
from services.blueprint.service import BlueprintService
from services.catalog import workflow_nodes

REPO = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "vet_clinic_blueprint.json"
HOST = "Handle Appointment Request"


# ---------------------------------------------------------------------------
# the VET clinic and its triage step
# ---------------------------------------------------------------------------

def vet_doc() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def triage(**config) -> dict:
    """The model case: look up the pet's history, return urgency and a suggested slot, propose the booking."""
    cfg = {
        "agentBrief": {
            "purpose": "Judge how urgent a pet's problem is and suggest an appointment type, vet and slots.",
            "reads": ["Pet", "MedicalRecord", "Prescription", "VaccinationRecord", "Appointment", "Veterinarian"],
            "mayChange": [{"tool": "Book Appointment", "why": "to propose the slot it suggests"}],
        },
        "task": "A request came in for {{pet.name}}: {{reason}}. Judge the urgency and suggest a slot.",
        "input": {"pet": "{{pet.id}}"},
        "outputFields": [
            {"name": "urgency", "type": "enum", "values": ["emergency", "urgent", "routine"],
             "description": "How soon the pet must be seen"},
            {"name": "appointmentType", "type": "string", "description": "Kind of visit"},
            {"name": "suggestedVet", "type": "string", "description": "The veterinarian to book"},
            {"name": "suggestedSlots", "type": "array", "description": "Up to three free slots"},
            {"name": "redFlags", "type": "array", "description": "Signs that need a person"},
        ],
        "autonomy": "suggest", "onFailure": "human",
    }
    cfg.update(config)
    for k in [k for k, v in cfg.items() if v is None]:      # None removes a key
        del cfg[k]
    return {"key": "triage", "name": "Triage", "type": "agent_step", "next": ["check"], "config": cfg}


def host_steps(step: dict | None = None, check: str = 'triage.result.urgency = "emergency" or triage.needsHuman = true',
               **extra_config) -> list[dict]:
    return [
        {"key": "start", "name": "Start", "type": "trigger", "config": {"type": "manual"}, "next": ["triage"]},
        step or triage(**extra_config),
        {"key": "check", "name": "Emergency?", "type": "condition", "config": {"expression": check},
         "next": ["review", "done"]},
        {"key": "review", "name": "Vet reviews", "type": "approval",
         "config": {"assignType": "role", "assignTarget": "Veterinarian", "description": "{{triage.summary}}"},
         "next": ["done"]},
        {"key": "done", "name": "Done", "type": "end", "config": {"refused": False}, "next": []},
    ]


def host_body(doc: dict, steps: list[dict]) -> dict:
    row = next(w for w in doc["workflows"] if w["name"] == HOST)
    return {**copy.deepcopy(row), "steps": steps}


def proposal(body: dict) -> AgentResult:
    return AgentResult(task_id="T", agent="workflow", confidence=0.9,
                       proposals=[ArtifactProposal("workflows", body["name"], body)])


def gate(steps: list[dict], *, doc: dict | None = None, assistants=None) -> str | None:
    """The refusal the apply gate gives this workflow, or None when it takes it."""
    doc = doc or vet_doc()
    try:
        check_workflow_steps(proposal(host_body(doc, steps)), doc, None, None,
                             {} if assistants is None else assistants)
    except InvalidWorkflowStep as exc:
        return str(exc)
    return None


@pytest.fixture()
def svc(tmp_path):
    """A VET Blueprint a build can write to: the fixture's entities and workflows, the host workflow still without steps."""
    doc = vet_doc()
    s = BlueprintService.create(output_dir=tmp_path, app_id="vet", name="VET Clinic", domain="veterinary")
    s.doc["application"]["description"] = doc["application"]["description"]
    s.doc["data"] = doc["data"]
    s.doc["businessRules"] = doc["businessRules"]
    s.doc["security"] = {**s.doc.get("security", {}), **copy.deepcopy(doc["security"])}
    for w in doc["workflows"]:
        s.upsert("workflows", copy.deepcopy(w), natural_key=w["name"])
    s.save()
    return s


def apply_triage(svc, steps=None):
    body = host_body(svc.doc, steps or host_steps())
    return apply_agent_result(svc, proposal(body), commit=False)


def host_of(svc) -> dict:
    return next(w for w in svc.doc["workflows"] if w["name"] == HOST)


def triage_of(svc) -> dict:
    return next(s for s in host_of(svc)["steps"] if s["key"] == "triage")


# ---------------------------------------------------------------------------
# registered once; every copy agrees
# ---------------------------------------------------------------------------

def test_the_assistant_step_is_one_catalog_node_and_every_copy_agrees():
    cat = workflow_nodes()
    node = cat.node("agent_step")
    assert node["category"] == "ai"
    assert node["handles"] == {"in": True, "out": True, "else": False}
    # one of agentId / agentBrief, and the task, and what it hands back
    assert cat.required_groups("agent_step") == [["agentId", "agentBrief"], ["task"], ["outputFields"]]
    assert cat.missing("agent_step", {"task": "x"}) == ["agentId|agentBrief", "outputFields"]
    assert cat.missing("agent_step", {"agentId": "a", "task": "x", "outputFields": [{"name": "n"}]}) == []

    source = (REPO / "packages" / "catalog" / "workflow-nodes.json").read_bytes()
    assert (REPO / "backend" / "contracts" / "workflow-node-catalog.json").read_bytes() == source
    assert (REPO / "frontend" / "src" / "catalog" / "workflow-nodes.json").read_bytes() == source

    zod = (REPO / "packages" / "schema" / "src" / "blueprint" / "blueprint.ts").read_text("utf-8")
    block = re.search(r"WORKFLOW_NODE_TYPES = \[(.*?)\] as const", zod, re.S).group(1)
    assert '"agent_step"' in block
    contract = json.loads((REPO / "backend" / "contracts" / "blueprint.schema.json").read_text("utf-8"))
    enum = contract["properties"]["workflows"]["items"]["properties"]["steps"]["items"]["properties"]["type"]["enum"]
    assert "agent_step" in enum and enum == cat.node_types


def test_the_other_places_that_know_the_ai_steps_know_this_one():
    from agents.planner import PLANNER_SYSTEM_PROMPT
    from services.node_config_specs import providers_for_action
    from services.workflow_executability import _REQUIRED
    from services.workflow_step_translator import _resolve_node_type

    assert _REQUIRED["agent_step"] == tuple(tuple(g) for g in workflow_nodes().required_groups("agent_step"))
    assert providers_for_action("agent_step") == ["anthropic"]            # it needs the model key like the other AI steps
    assert _resolve_node_type({"type": "agent_step"}) == ("agent_step", None)
    assert '"agent_step"' in PLANNER_SYSTEM_PROMPT and "LOOKING UP" in PLANNER_SYSTEM_PROMPT
    assert "workflow_agents" in __import__("services.office_events", fromlist=["NODE_LABEL"]).NODE_LABEL


def test_a_valid_step_passes_the_catalog_and_a_bare_one_says_what_is_missing():
    cat = workflow_nodes()
    assert cat.step_errors(triage()) == []
    bare = {"key": "t", "type": "agent_step", "config": {}}
    assert cat.step_errors(bare) == ["config needs one of: agentId|agentBrief", "config needs one of: task",
                                     "config needs one of: outputFields"]


# ---------------------------------------------------------------------------
# when Smith chooses it: said where the AI-step guidance is, and nowhere else
# ---------------------------------------------------------------------------

def test_the_workflow_step_author_is_told_when_to_choose_an_assistant_step():
    from services.blueprint.executors import AGENT_STEP_GUIDANCE, NODE_TASKS

    task = NODE_TASKS["workflow_steps"]
    assert AGENT_STEP_GUIDANCE in task
    g = AGENT_STEP_GUIDANCE
    # cheap steps for one judgement on what is in hand; an assistant only for lookups; it costs several times as much
    assert all(word in g for word in ("ai_classify", "ai_decide", "ai_generate", "ai_extract", "looking things up", "three to ten times"))
    # the brief: reads limited to what the step needs, typed output used by later steps
    assert "only those this step needs" in g and "LATER STEP" in g and "outputFields" in g
    # the dial: suggest by default, limited only for routine reversible changes, and what is never allowed
    assert "`suggest`" in g and "routine and reversible" in g and "Never allow deleting records, moving money" in g
    # a person for anything risky, a decision on the result, an approval fed from needsHuman and the proposals
    assert "`onFailure` is `human`" in g and "condition on its result" in g and "{{<key>.needsHuman}}" in g and "approval" in g
    assert "{{<key>.result.<field>}}" in g and "{{<key>.proposals}}" in g
    # the model case
    assert "vet clinic" in g and "MedicalRecord" in g and "urgency (enum emergency, urgent, routine)" in g


def test_no_other_call_is_told_and_the_one_that_is_does_not_grow_much():
    from services.blueprint.executors import AGENT_STEP_GUIDANCE, NODE_TASKS

    for node, text in NODE_TASKS.items():
        if node != "workflow_steps":
            assert "agent_step" not in text, f"{node} was given the assistant-step guidance"
    # proportionate: one paragraph, in the cached system prompt of one task
    assert len(AGENT_STEP_GUIDANCE) < 3200
    # the user part of the call gains nothing: sibling workflows stay out of it (a wrong tool name is refused with the names)
    from services.blueprint.executors import _workflow_steps_prompt

    _, user = _workflow_steps_prompt(vet_doc(), "SYSTEM", "FLOW-006", "", output_dir=None)
    assert "workflowNames" not in user and "Refund Invoice" not in user
    # the catalog line the author reads for the node stays one short entry
    assert len(workflow_nodes().digest(types=["agent_step"])) < 500


# ---------------------------------------------------------------------------
# the gate: the triage step is taken; each broken variant is refused in words
# ---------------------------------------------------------------------------

def test_the_vet_triage_step_is_accepted():
    assert gate(host_steps()) is None


def test_a_step_with_no_assistant_and_no_brief_is_refused():
    msg = gate(host_steps(triage(agentBrief=None)))
    assert "needs an assistant" in msg and "agentId" in msg and "agentBrief" in msg


def test_an_assistant_the_app_does_not_have_is_refused_and_one_it_has_is_taken(tmp_path):
    steps = host_steps(triage(agentBrief=None, agentId="wf_nobody"))
    msg = gate(steps)
    assert "wf_nobody" in msg and "does not have" in msg and "agentBrief" in msg

    made = agent_for_brief(vet_doc(), triage()["config"]["agentBrief"], None, None, agent_id="wf_triage_helper")
    agent_steps.save_assistant(tmp_path, made["agent"])
    steps = host_steps(triage(agentBrief=None, agentId="wf_triage_helper", allowedWriteTools=["book_appointment"]))
    assert gate(steps, assistants=agent_steps.load_assistants(tmp_path)) is None


@pytest.mark.parametrize("brief, says", [
    ({"purpose": "", "reads": ["Pet"]}, "`agentBrief.purpose`"),
    ({"purpose": "x" * 601, "reads": ["Pet"]}, "601 characters; keep it to 600"),
    ({"purpose": "Judge it.", "reads": []}, "`agentBrief.reads` lists the records"),
    ({"purpose": "Judge it.", "reads": ["Pet"], "mayChange": [{"tool": "Book Appointment"}]}, "`agentBrief.mayChange`"),
    ({"purpose": "Judge it.", "reads": ["Pet"], "instructions": "y" * 1501}, "`agentBrief.instructions`"),
])
def test_a_brief_that_is_not_usable_says_what_to_fix(brief, says):
    assert says in gate(host_steps(triage(agentBrief=brief)))


def test_a_brief_that_asks_for_what_the_app_does_not_have_names_what_it_has():
    reads = {"purpose": "Judge it.", "reads": ["Pet", "Medical history"]}
    msg = gate(host_steps(triage(agentBrief=reads)))
    assert "'Medical history', which is not one of this app's records" in msg and "MedicalRecord" in msg

    signin = {"purpose": "Judge it.", "reads": ["User"]}
    assert "holds sign-in details" in gate(host_steps(triage(agentBrief=signin)))

    writes = {"purpose": "Judge it.", "reads": ["Pet"], "mayChange": [{"tool": "Send Invoice", "why": "x"}]}
    msg = gate(host_steps(triage(agentBrief=writes)))
    assert "'Send Invoice', which is not a workflow an assistant can run" in msg and "book_appointment" in msg
    assert "nightly_reminder" not in msg, "a scheduled process is not something an assistant starts"


def test_an_assistant_may_not_be_given_the_workflow_its_step_belongs_to():
    brief = triage()["config"]["agentBrief"]
    brief["mayChange"] = [{"tool": "Handle Appointment Request", "why": "to book"}]
    msg = gate(host_steps(triage(agentBrief=brief)))
    assert "the workflow this very step belongs to" in msg


def test_two_workflows_whose_assistants_start_each_other_are_refused():
    doc = vet_doc()
    other = {"id": "FLOW-007", "name": "Review Cancellation", "purpose": "Decide whether a cancellation stands.",
             "trigger": {"kind": "manual"}, "status": "PROPOSED", "launchedFrom": [], "inputs": [],
             "steps": [{"key": "ask", "type": "agent_step", "name": "Ask", "next": [], "config": triage(
                 agentBrief={"purpose": "Decide it.", "reads": ["Appointment"],
                             "mayChange": [{"tool": HOST, "why": "to rebook"}]})["config"]}]}
    doc["workflows"].append(other)
    brief = triage()["config"]["agentBrief"]
    brief["mayChange"] = [{"tool": "Review Cancellation", "why": "to send it for review"}]
    msg = gate(host_steps(triage(agentBrief=brief)), doc=doc)
    assert "could end up starting this workflow again" in msg
    assert f"{HOST} -> Review Cancellation -> {HOST}" in msg


@pytest.mark.parametrize("fields, says", [
    (None, "`outputFields` lists what the assistant hands back"),
    ([], "`outputFields` lists what the assistant hands back"),
    ([{"name": "Urgency", "type": "string", "description": "x"}], "starts with a lower-case letter"),
    ([{"name": "confidence", "type": "number", "description": "x"}], "returned by every assistant step already"),
    ([{"name": "urgency", "type": "color", "description": "x"}], "is one of string, number, boolean, array, object, enum"),
    ([{"name": "urgency", "type": "enum", "description": "x"}], "is an enum, so it lists its `values`"),
    ([{"name": "urgency", "type": "string", "values": ["a"], "description": "x"}], "`values` belongs to a field of type enum"),
    ([{"name": "urgency", "type": "string"}], "needs a `description`"),
    ([{"name": "urgency", "type": "string", "description": "a"}, {"name": "urgency", "type": "string", "description": "b"}],
     "'urgency' is listed twice"),
])
def test_output_fields_are_typed_and_named_so_later_steps_can_use_them(fields, says):
    steps = host_steps(triage(outputFields=fields), check="triage.needsHuman = true")
    assert says in gate(steps)


@pytest.mark.parametrize("check, says", [
    ('triage.result.urgncy = "emergency"', "returns only urgency, appointmentType, suggestedVet, suggestedSlots, redFlags"),
    ("triage.urgency = \"emergency\"", "under `result`: {{triage.result.urgency}}"),
    ("triage.verdict = \"x\"", "does not return"),
    ('triage.result.urgency = "critical"', "compares triage.result.urgency with \"critical\", which is not one of its values (emergency, urgent, routine)"),
    ('triage.result.urgency in ["emergency", "severe"]', "\"severe\""),
    ('triage.result.urgency > "a"', "use = or !="),
    ('triage.confidence = "high"', "is not a number"),
    ('triage.needsHuman = "yes"', "compare it with true or false"),
    ('triage.result.suggestedSlots = "monday"', "a list or record"),
    ('triage.summary > "a"', "text can only be compared with = or !="),
])
def test_what_a_later_step_reads_must_be_something_the_step_returns(check, says):
    msg = gate(host_steps(check=check))
    assert msg and says in msg, msg


def test_a_template_read_of_a_field_it_does_not_return_is_refused_too():
    steps = host_steps()
    steps[3]["config"]["description"] = "{{triage.result.reason}} — {{triage.summary}}"
    msg = gate(steps)
    assert "{{triage.result.reason}}" in msg and "add 'reason' to its outputFields" in msg
    # the standard envelope is always there to read
    steps[3]["config"]["description"] = "{{triage.summary}} {{triage.proposals}} {{triage.confidence}} {{triage.result.urgency}}"
    assert gate(steps) is None


@pytest.mark.parametrize("config, says", [
    ({"autonomy": "reckless"}, "`autonomy` is one of suggest, limited, full"),
    ({"autonomy": "limited"}, "`allowedWriteTools` names the only tools it may run"),
    ({"autonomy": "full"}, "`allowedWriteTools` names the only tools it may run"),
    ({"autonomy": "limited", "allowedWriteTools": []}, "`allowedWriteTools` names the only tools it may run"),
    ({"allowedWriteTools": ["cancel_appointment"]}, "assistant has no tool of that name that changes data"),
    ({"allowedWriteTools": "book_appointment"}, "`allowedWriteTools` is a list of tool names"),
    ({"minConfidence": 1.5}, "`minConfidence` is a number from 0 to 1"),
    ({"minConfidence": "high"}, "`minConfidence` is a number from 0 to 1"),
    ({"maxActions": 11}, "`maxActions` is a whole number from 1 to 10"),
    ({"maxActions": 0}, "`maxActions` is a whole number from 1 to 10"),
    ({"maxTurns": 13}, "`maxTurns` is a whole number from 1 to 12"),
    ({"timeoutSec": 4}, "`timeoutSec` is a whole number from 5 to 300"),
    ({"timeoutSec": 301}, "`timeoutSec` is a whole number from 5 to 300"),
    ({"maxTokens": 999}, "`maxTokens` is a whole number from 1000 to 100000"),
    ({"maxTokens": 100001}, "`maxTokens` is a whole number from 1000 to 100000"),
    ({"onFailure": None}, "`onFailure` says what happens when the assistant cannot answer"),
    ({"onFailure": "shrug"}, "`onFailure` says what happens when the assistant cannot answer"),
    ({"task": ""}, "`task` says what to do this time"),
    ({"input": {"pet": "plain text"}}, "`input` maps a name to a value from the workflow"),
])
def test_the_dial_the_limits_and_what_to_do_on_failure_are_held_to_their_ranges(config, says):
    msg = gate(host_steps(**config))
    assert msg and says in msg, msg


def test_the_edges_of_every_range_are_accepted():
    ok = {"autonomy": "limited", "allowedWriteTools": ["book_appointment"], "minConfidence": 0, "maxActions": 10,
          "maxTurns": 12, "timeoutSec": 300, "maxTokens": 100000, "onFailure": "skip"}
    assert gate(host_steps(**ok)) is None
    low = {"minConfidence": 1, "maxActions": 1, "maxTurns": 1, "timeoutSec": 5, "maxTokens": 1000, "onFailure": "fail"}
    assert gate(host_steps(**low)) is None


def test_an_assistant_is_never_allowed_to_delete_or_move_money_on_its_own_but_may_propose_it():
    brief = triage()["config"]["agentBrief"]
    brief["mayChange"] = [{"tool": "Delete Prescription", "why": "to remove a wrong one"},
                          {"tool": "Refund Invoice", "why": "to refund"}]
    # proposing is fine: a person approves it
    assert gate(host_steps(triage(agentBrief=brief))) is None
    deleting = gate(host_steps(triage(agentBrief=brief, autonomy="limited", allowedWriteTools=["delete_prescription"])))
    assert "'delete_prescription' deletes records, and an assistant is never allowed to do that on its own" in deleting
    paying = gate(host_steps(triage(agentBrief=brief, autonomy="full", allowedWriteTools=["refund_invoice"])))
    assert "'refund_invoice' moves money" in paying


def test_an_assistant_the_build_made_may_change_only_what_the_step_names(tmp_path):
    """Built for a step (workflow-only, `wf_`): read-only plus exactly what its brief and the step name. One a builder has
    since added a tool to is refused until the step names it."""
    doc = vet_doc()
    big = agent_for_brief(doc, {"purpose": "Anything.", "reads": ["Pet"], "mayChange": [
        {"tool": "Book Appointment", "why": "a"}, {"tool": "Cancel Appointment", "why": "b"}]}, None, None,
        agent_id="wf_wide")
    agent_steps.save_assistant(tmp_path, big["agent"])
    assistants = agent_steps.load_assistants(tmp_path)

    # acting alone with one of its two changes allowed: the other is a change the step never named
    limited = host_steps(triage(agentBrief=None, agentId="wf_wide", autonomy="limited",
                                allowedWriteTools=["book_appointment"]))
    msg = gate(limited, assistants=assistants)
    assert "made for this step can change data with cancel_appointment, which the step does not name" in msg
    # naming both in the allowed list (or the brief) makes it the step's own decision
    both = host_steps(triage(agentBrief=None, agentId="wf_wide", autonomy="limited",
                             allowedWriteTools=["book_appointment", "cancel_appointment"]))
    assert gate(both, assistants=assistants) is None
    # a step that names none of them (proposing only) still cannot carry an assistant made with changes it does not name
    msg = gate(host_steps(triage(agentBrief=None, agentId="wf_wide")), assistants=assistants)
    assert "can change data with book_appointment, cancel_appointment" in msg


# ---------------------------------------------------------------------------
# an application through the real apply path (the gate runs inside it)
# ---------------------------------------------------------------------------

def test_a_workflow_steps_application_takes_the_triage_step_and_names_the_tool_as_the_app_does(svc):
    steps = host_steps(allowedWriteTools=["Book Appointment"])
    steps[1]["config"]["agentBrief"]["mayChange"][0]["tool"] = "Book Appointment"       # written the way a person says it
    assert apply_triage(svc, steps).applied
    cfg = triage_of(svc)["config"]
    assert cfg["allowedWriteTools"] == ["book_appointment"], "the runtime compares tool names exactly"
    assert cfg["agentBrief"]["mayChange"][0]["tool"] == "book_appointment"


def test_a_workflow_steps_application_refuses_a_broken_step_and_leaves_the_blueprint_alone(svc):
    before = copy.deepcopy(svc.doc["workflows"])
    with pytest.raises(InvalidWorkflowStep) as e:
        apply_triage(svc, host_steps(check='triage.result.urgency = "critical"'))
    assert f"{HOST}/" in str(e.value) and "not one of its values" in str(e.value)
    assert svc.doc["workflows"] == before


def test_the_verification_report_reads_the_same_checks_over_the_whole_document():
    from services.blueprint.functional_completeness import functional_findings

    doc = vet_doc()
    row = next(w for w in doc["workflows"] if w["name"] == HOST)
    row["steps"] = host_steps(check='triage.result.urgency = "critical"')
    found = [f for f in functional_findings(doc) if f["rule"] == "agent-step"]
    assert len(found) == 1 and found[0]["page"] == "FLOW-006" and "not one of its values" in found[0]["detail"]
    row["steps"] = host_steps()
    assert [f for f in functional_findings(doc) if f["rule"] == "agent-step"] == []


# ---------------------------------------------------------------------------
# the assistant made from a brief
# ---------------------------------------------------------------------------

def test_a_brief_becomes_a_read_only_assistant_plus_exactly_the_workflows_it_names():
    doc = vet_doc()
    host = next(w for w in doc["workflows"] if w["name"] == HOST)
    made = agent_for_brief(doc, triage()["config"]["agentBrief"], host, triage())
    agent = made["agent"]

    assert made["id"] == agent["id"] == "wf_handle-appointment-request_triage"
    assert agent["name"] == "Triage assistant"
    tools = {n["data"]["config"]["tool_name"]: n["data"]["config"] for n in agent["nodes"] if n["type"] == "tool"}
    reads = {name for name, c in tools.items() if c["tool_type"] == "data_engine"}
    assert reads == {f"{op}_{name}" for op, name in [
        ("list", "pets"), ("get", "pet"), ("list", "medical_records"), ("get", "medical_record"),
        ("list", "prescriptions"), ("get", "prescription"), ("list", "vaccination_records"), ("get", "vaccination_record"),
        ("list", "appointments"), ("get", "appointment"), ("list", "veterinarians"), ("get", "veterinarian")]}
    assert all(tools[r]["operation"] in ("list", "get") for r in reads), "a read tool never creates or changes"
    writes = {name for name, c in tools.items() if c["tool_type"] != "data_engine"}
    assert writes == {"book_appointment"} == set(made["writeTools"])
    assert tools["book_appointment"]["tool_type"] == "workflow" and tools["book_appointment"]["workflow_id"] == "book-appointment"
    # records it was not given are not there: not the invoices, not the owners, never the sign-in table
    assert not any(c.get("entity") in ("invoices", "pet_owners", "users") for c in tools.values())
    # what a person may not see is not what the assistant sees
    assert "phone" not in json.dumps(tools["list_pets"]["response_filter"]) and "passwordHash" not in json.dumps(tools)

    # focused prompt
    prompt = next(n for n in agent["nodes"] if n["type"] == "system_prompt")["data"]["config"]["prompt"]
    assert "Judge how urgent a pet's problem is" in prompt
    assert "You cannot change data" in prompt and "recorded" in prompt or "records the call as a proposal" in prompt
    assert "urgency (one of emergency, urgent, routine)" in prompt and "needsHuman" in prompt
    assert "A veterinarian cannot have two scheduled appointments" in prompt, "the app's own rule that governs its tools"

    # the boxes: two guardrails, memory that keeps nothing, no hand-over to a person, no router
    kinds = [n["type"] for n in agent["nodes"]]
    assert kinds.count("guardrail") == 2 and kinds.count("memory") == 1
    assert "human_handoff" not in kinds and "router" not in kinds
    memory = next(n for n in agent["nodes"] if n["type"] == "memory")["data"]["config"]
    assert memory["stateless"] is True and memory["capacity"] == 2
    assert agent["config"]["workflow_only"] is True


def test_an_assistant_with_nothing_to_change_says_it_has_no_tool_that_changes_data():
    brief = {"purpose": "Summarise a pet's history.", "reads": ["Pet", "MedicalRecord"]}
    made = agent_for_brief(vet_doc(), brief, None, {"key": "summary", "name": "Summary"})
    assert made["writeTools"] == [] and made["id"].startswith("wf_")
    prompt = made["agent"]["nodes"][0]["data"]["config"]["prompt"]
    assert "no tool that changes data" in prompt


def test_a_brief_the_app_cannot_honour_raises_in_plain_sentences():
    with pytest.raises(BriefError) as e:
        agent_for_brief(vet_doc(), {"purpose": "x", "reads": ["Pets", "Ghosts"]}, None, None)
    assert "'Ghosts', which is not one of this app's records" in str(e.value) and e.value.problems
    with pytest.raises(BriefError, match="the brief is not usable"):
        agent_for_brief(vet_doc(), {"purpose": "", "reads": []}, None, None)


def test_a_read_is_found_by_the_way_people_spell_it():
    doc = vet_doc()
    for ref, expect in [("pets", "pets"), ("Pet", "pets"), ("medical records", "medical_records"),
                        ("vaccinations", "vaccination_records"), ("list_prescriptions", "prescriptions"),
                        ("Vaccination Record", "vaccination_records")]:
        r = resolve_brief_tools(doc, {"purpose": "x", "reads": [ref]})
        assert not r.problems and r.reads[0]["cfg"]["entity"] == expect, ref


def test_the_id_is_wf_workflow_step_and_stays_inside_the_runtimes_alphabet():
    from services.agent_suggest import assistant_id_for
    from services.agent_runtime_config import safe_id

    wf = {"id": "FLOW-001", "name": "Handle Appointment Request"}
    assert assistant_id_for(wf, "triage") == "wf_handle-appointment-request_triage"
    long_name = {"id": "FLOW-002", "name": "x" * 120}
    aid = assistant_id_for(long_name, "triage")
    assert len(aid) <= 80 and safe_id(aid) == aid
    assert assistant_id_for(long_name, "triage") == aid, "the same step always gets the same id"
    assert assistant_id_for({"id": "F", "name": "x" * 120}, "other") != aid


# ---------------------------------------------------------------------------
# the stage
# ---------------------------------------------------------------------------

def test_the_stage_sits_after_the_steps_are_written_and_before_they_are_projected():
    node = DAG["workflow_agents"]
    assert node.kind == "service" and "workflow_steps" in node.depends_on
    assert "workflow_agents" in DAG["integration"].depends_on
    assert node.optional, "an app ships without it: the step answers its own onFailure"
    assert "workflow_agents" in SERVICE_HANDLERS
    order = [k for lvl in levels() for k in lvl]
    assert order.index("workflow_steps") < order.index("workflow_agents") < order.index("integration")
    assert order.index("workflow_agents") < order.index("assemble")


def test_the_stage_makes_the_assistant_saves_it_and_writes_its_id_into_the_step(svc, tmp_path):
    apply_triage(svc)
    assert "agentId" not in triage_of(svc)["config"]

    report = agent_steps.build_workflow_assistants(svc, commit=False)
    aid = "wf_handle-appointment-request_triage"
    assert report.built == [aid] and report.kept == [] and report.problems == []

    saved = tmp_path / "agent-definitions" / f"{aid}.json"
    assert saved.is_file(), "where the install picks it up with the app"
    graph = json.loads(saved.read_text("utf-8"))
    assert graph["config"]["workflow_only"] is True
    assert graph["config"]["made_for"]["workflowId"] == "FLOW-006" and graph["config"]["made_for"]["stepKey"] == "triage"
    assert triage_of(svc)["config"]["agentId"] == aid
    assert triage_of(svc)["config"]["agentBrief"]["purpose"], "the brief stays: it is what a lost assistant is made again from"
    assert [p.name for p in (tmp_path / "agent-definitions").glob("*.json")] == [f"{aid}.json"]

    from services.agent_runtime_install import has_agents
    assert has_agents(tmp_path), "the install sees it"
    # the Blueprint still stands: the gate takes the step now that it names an assistant that exists
    svc.validate()
    again = host_body(svc.doc, host_of(svc)["steps"])
    check_workflow_steps(proposal(again), svc.doc, None, None, agent_steps.load_assistants(tmp_path))


def test_the_compiled_assistant_is_workflow_only_with_reads_and_one_proposal_tool(svc, tmp_path):
    apply_triage(svc)
    agent_steps.build_workflow_assistants(svc, commit=False)
    graph = json.loads((tmp_path / "agent-definitions" / "wf_handle-appointment-request_triage.json").read_text("utf-8"))
    compiled = compile_agent(graph)
    assert compiled.config["workflowOnly"] is True
    by_name = {t["name"]: t for t in compiled.config["tools"]}
    assert by_name["book_appointment"]["kind"] == "workflow" and by_name["book_appointment"].get("confirm") is True
    assert all(t["operation"] in ("list", "get") for t in by_name.values() if t["kind"] == "data")
    assert "handoff" not in compiled.config and "request_human" not in by_name
    assert compiled.config["memory"]["type"] == "conversation"
    assert not [w for w in compiled.warnings if "dropped" in w]


def test_a_rebuild_does_not_duplicate_or_reset_the_assistant(svc, tmp_path):
    apply_triage(svc)
    agent_steps.build_workflow_assistants(svc, commit=False)
    saved = tmp_path / "agent-definitions" / "wf_handle-appointment-request_triage.json"
    first = saved.read_bytes()

    report = agent_steps.build_workflow_assistants(svc, commit=False)
    assert report.built == [] and report.kept == ["wf_handle-appointment-request_triage"]
    assert saved.read_bytes() == first
    assert len(list((tmp_path / "agent-definitions").glob("*.json"))) == 1
    assert triage_of(svc)["config"]["agentId"] == "wf_handle-appointment-request_triage"


def test_an_assistant_a_builder_has_edited_is_kept_whatever_happens_to_the_brief(svc, tmp_path):
    apply_triage(svc)
    agent_steps.build_workflow_assistants(svc, commit=False)
    saved = tmp_path / "agent-definitions" / "wf_handle-appointment-request_triage.json"
    graph = json.loads(saved.read_text("utf-8"))
    prompt = next(n for n in graph["nodes"] if n["type"] == "system_prompt")
    prompt["data"]["config"]["prompt"] += "\nAlways ask about vaccinations first."          # the builder's own edit
    saved.write_text(json.dumps(graph, indent=2), "utf-8")
    edited = saved.read_bytes()
    assert not agent_steps.untouched(json.loads(edited))

    assert agent_steps.build_workflow_assistants(svc, commit=False).built == []
    assert saved.read_bytes() == edited

    # and when Smith has since changed the brief: still the builder's
    row = host_of(svc)
    row["steps"][1]["config"]["agentBrief"]["purpose"] = "Judge urgency only."
    svc.save()
    report = agent_steps.build_workflow_assistants(svc, commit=False)
    assert report.built == [] and report.kept and saved.read_bytes() == edited


def test_an_untouched_assistant_is_made_again_when_the_brief_has_changed(svc, tmp_path):
    apply_triage(svc)
    agent_steps.build_workflow_assistants(svc, commit=False)
    saved = tmp_path / "agent-definitions" / "wf_handle-appointment-request_triage.json"
    assert agent_steps.untouched(json.loads(saved.read_text("utf-8")))

    triage_of(svc)["config"]["agentBrief"]["reads"] = ["Pet", "Appointment"]
    svc.save()
    report = agent_steps.build_workflow_assistants(svc, commit=False)
    assert report.built == ["wf_handle-appointment-request_triage"]
    tools = [n["data"]["config"]["tool_name"] for n in json.loads(saved.read_text("utf-8"))["nodes"] if n["type"] == "tool"]
    assert "list_medical_records" not in tools and "list_appointments" in tools
    assert len(list((tmp_path / "agent-definitions").glob("*.json"))) == 1


def test_an_assistant_whose_file_is_gone_is_made_again_from_the_brief(svc, tmp_path):
    apply_triage(svc)
    agent_steps.build_workflow_assistants(svc, commit=False)
    saved = tmp_path / "agent-definitions" / "wf_handle-appointment-request_triage.json"
    saved.unlink()
    report = agent_steps.build_workflow_assistants(svc, commit=False)
    assert report.built == ["wf_handle-appointment-request_triage"] and saved.is_file()
    assert triage_of(svc)["config"]["agentId"] == "wf_handle-appointment-request_triage"


def test_a_step_that_names_one_of_the_apps_own_assistants_gets_no_new_one(svc, tmp_path):
    own = agent_for_brief(vet_doc(), {"purpose": "Own.", "reads": ["Pet"]}, None, None, agent_id="app_assistant")
    agent_steps.save_assistant(tmp_path, own["agent"])
    before = (tmp_path / "agent-definitions" / "app_assistant.json").read_bytes()
    step = triage(agentBrief=None, agentId="app_assistant", allowedWriteTools=None)
    apply_agent_result(svc, proposal(host_body(svc.doc, host_steps(step))), commit=False)
    report = agent_steps.build_workflow_assistants(svc, commit=False)
    assert report.built == [] and report.updated_workflows == []
    assert (tmp_path / "agent-definitions" / "app_assistant.json").read_bytes() == before
    assert [p.name for p in (tmp_path / "agent-definitions").glob("*.json")] == ["app_assistant.json"]


def test_the_stage_reports_a_brief_it_cannot_build_and_saves_nothing(svc, tmp_path):
    apply_triage(svc)
    triage_of(svc)["config"]["agentBrief"]["reads"] = ["Ghosts"]       # slipped in after the gate, e.g. by an edit
    svc.save()
    report = agent_steps.build_workflow_assistants(svc, commit=False)
    assert report.built == [] and "Ghosts" in report.problems[0]
    assert not (tmp_path / "agent-definitions").exists() or not list((tmp_path / "agent-definitions").glob("*.json"))
    with pytest.raises(RuntimeError, match="an assistant could not be made for"):
        SERVICE_HANDLERS["workflow_agents"](svc)


def test_the_stage_handler_is_what_the_build_runs(svc, tmp_path):
    apply_triage(svc)
    SERVICE_HANDLERS["workflow_agents"](svc)
    assert triage_of(svc)["config"]["agentId"] == "wf_handle-appointment-request_triage"


# ---------------------------------------------------------------------------
# the compile step
# ---------------------------------------------------------------------------

def test_workflow_only_is_compiled_into_the_runtime_config_and_nothing_else_changes():
    base = {"id": "a", "name": "A", "nodes": [], "edges": []}
    assert compile_agent({**base, "config": {"workflow_only": True}}).config["workflowOnly"] is True
    for off in ({}, {"workflow_only": False}, {"workflow_only": "yes"}, {"workflow_only": None}):
        assert "workflowOnly" not in compile_agent({**base, "config": off}).config, off
    assert "workflowOnly" not in compile_agent(base).config


def test_the_apps_own_chat_assistant_is_not_workflow_only():
    from services.agent_suggest import suggest_agent

    compiled = compile_agent(suggest_agent(vet_doc()))
    assert "workflowOnly" not in compiled.config


# ---------------------------------------------------------------------------
# the used-by lookup the editor and the delete warning read
# ---------------------------------------------------------------------------

def test_used_by_reads_the_apps_workflow_definitions_then_the_blueprint(svc, tmp_path):
    apply_triage(svc)
    agent_steps.build_workflow_assistants(svc, commit=False)
    aid = "wf_handle-appointment-request_triage"
    assert agent_steps.used_by(tmp_path, svc.doc, aid) == [
        {"workflowId": "FLOW-006", "workflowName": HOST, "stepId": "triage"}]
    assert agent_steps.used_by(tmp_path, svc.doc, "nobody") == []

    # once the app has its definitions (what the editor changes), they are the truth
    from services.blueprint.projection import project_workflows
    app = tmp_path / "app"
    app.mkdir()
    project_workflows(svc.doc, app)
    assert agent_steps.used_by(tmp_path, svc.doc, aid) == [
        {"workflowId": "handle-appointment-request", "workflowName": HOST, "stepId": "triage"}]
    node = next(n for n in json.loads((app / "src/lib/workflows/definitions/handle-appointment-request.json")
                                      .read_text("utf-8"))["definition"]["nodes"] if n["id"] == "triage")
    assert node["type"] == "agent_step" and node["data"]["config"]["agentId"] == aid
    assert node["data"]["config"]["autonomy"] == "suggest" and node["data"]["config"]["onFailure"] == "human"


# ---------------------------------------------------------------------------
# a dry generation: a scripted model writes the workflow, the build makes its assistant
# ---------------------------------------------------------------------------

def test_a_scripted_build_writes_the_step_is_refused_once_then_gets_its_assistant(svc, tmp_path):
    """workflow_steps (a fake model that first writes a branch that could never be taken) -> the gate sends it back
    with the sentence -> the second reply is taken -> workflow_agents makes the assistant. No real model."""
    from services.blueprint.orchestrator import run

    calls: list[dict] = []

    def model(spec):
        calls.append({"node": spec.node, "subject": spec.subject, "attempt": spec.attempt, "feedback": spec.feedback})
        broken = spec.attempt == 1
        steps = host_steps(check='triage.result.urgency = "critical"' if broken else
                           'triage.result.urgency = "emergency" or triage.needsHuman = true')
        return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.9,
                           proposals=[ArtifactProposal("workflows", HOST, host_body(svc.doc, steps))])

    report = run(svc, model, plan=["workflow_steps", "workflow_agents"], commit=False)

    assert [c["node"] for c in calls] == ["workflow_steps", "workflow_steps"]
    assert "not one of its values (emergency, urgent, routine)" in calls[1]["feedback"], "the refusal is what it is re-asked with"
    assert "workflow_steps" in report.completed and "workflow_agents" in report.completed and not report.failed
    assert triage_of(svc)["config"]["agentId"] == "wf_handle-appointment-request_triage"
    assert (tmp_path / "agent-definitions" / "wf_handle-appointment-request_triage.json").is_file()


def test_one_of_the_apps_chat_assistants_with_other_changes_is_only_a_warning(tmp_path):
    """An existing assistant a step points at: a change tool the step does not allow can only ever become a proposal at run
    time, so it is said (a warning, logged by the gate) and never refused."""
    from services.agent_suggest import suggest_agent

    doc = vet_doc()
    # the app's chat assistant as it was drawn before this workflow existed (else it could start the workflow itself)
    before = {**doc, "workflows": [w for w in doc["workflows"] if w["name"] != HOST]}
    chat = suggest_agent(before)
    chat["id"] = "app_assistant"
    agent_steps.save_assistant(tmp_path, chat)
    assistants = agent_steps.load_assistants(tmp_path)
    assert not assistants["app_assistant"].workflow_only and len(assistants["app_assistant"].write_tools) > 3

    for autonomy in ({}, {"autonomy": "limited", "allowedWriteTools": ["book_appointment"]}):
        steps = host_steps(triage(agentBrief=None, agentId="app_assistant", **autonomy))
        assert gate(steps, assistants=assistants) is None, autonomy

    warnings: list[str] = []
    body = host_body(doc, host_steps(triage(agentBrief=None, agentId="app_assistant", autonomy="limited",
                                            allowedWriteTools=["book_appointment"])))
    assert agent_steps.agent_step_problems([body], doc, assistants, warnings) == []
    assert len(warnings) == 1 and f"{HOST}/triage" in warnings[0]
    assert "'app_assistant' can also change data with" in warnings[0] and "cancel_appointment" in warnings[0]
    assert "can only become proposals" in warnings[0] and "book_appointment" not in warnings[0].split("with", 1)[1].split(";")[0]

    # an assistant that merely LOOKS like the build's (a wf_ id) but is a chat assistant is still only a warning
    chat["id"] = "wf_looks_built"
    agent_steps.save_assistant(tmp_path, chat)
    assert gate(host_steps(triage(agentBrief=None, agentId="wf_looks_built")),
                assistants=agent_steps.load_assistants(tmp_path)) is None


# ---------------------------------------------------------------------------
# what the assistant reads is readable by the role it runs as (`workflow`), and nothing else is widened
# ---------------------------------------------------------------------------

def rules_of(svc) -> dict:
    return {r["entity"]: r for r in svc.doc["security"]["ownershipRules"]}


def test_the_stage_follows_security_because_it_records_read_access_in_its_rules():
    assert "security" in DAG["workflow_agents"].depends_on


def test_the_vet_schedules_are_readable_by_the_step_and_nothing_else_is_widened(svc):
    before = copy.deepcopy(rules_of(svc))
    apply_triage(svc)
    report = agent_steps.build_workflow_assistants(svc, commit=False)
    rules = rules_of(svc)
    assert len(report.grants) == 2 and report.problems == []

    # the vets' schedules and the prescriptions (both in the brief's `reads`, both scoped to a person) are readable
    assert rules["Veterinarian"]["readRoles"] == ["workflow"] and rules["Prescription"]["readRoles"] == ["workflow"]
    # ... and only for reading: who may WRITE (unscopedRoles) is exactly what it was
    for name in ("Veterinarian", "Prescription"):
        assert rules[name]["unscopedRoles"] == before[name]["unscopedRoles"] and "workflow" not in rules[name]["unscopedRoles"]
    # a scoped record the brief does not read is not widened; an attribution rule filters nothing and is left alone
    assert "readRoles" not in rules["Invoice"] and "readRoles" not in rules["Appointment"]
    # everything else in every rule is unchanged
    strip = lambda r: {k: v for k, v in r.items() if k != "readRoles"}
    assert {k: strip(v) for k, v in rules.items()} == {k: strip(v) for k, v in before.items()}
    svc.validate()


def test_the_projection_carries_the_grant_as_a_read_only_exemption(svc):
    from services.blueprint.projection import ownership_rules, render_ownership_rules_module

    apply_triage(svc)
    agent_steps.build_workflow_assistants(svc, commit=False)
    manifest = ownership_rules(svc.doc)
    vet = manifest["veterinarians"][0]
    assert vet["readRoles"] == ["workflow"] and vet["unscopedRoles"] == ["Admin", "Receptionist"]
    assert "readRoles" not in manifest["invoices"][0] and "readRoles" not in manifest["appointments"][0]
    assert "readRoles?: string[]" in render_ownership_rules_module(manifest)
    # an app with no assistant step projects exactly what it did before: no readRoles anywhere
    plain = ownership_rules({**svc.doc, "security": {**svc.doc["security"], "ownershipRules": [
        {k: v for k, v in r.items() if k != "readRoles"} for r in svc.doc["security"]["ownershipRules"]]}})
    assert not any("readRoles" in r for rules in plain.values() for r in rules)


def test_the_grant_is_idempotent_and_follows_the_brief(svc):
    apply_triage(svc)
    agent_steps.build_workflow_assistants(svc, commit=False)
    first = copy.deepcopy(svc.doc["security"])
    assert agent_steps.build_workflow_assistants(svc, commit=False).grants == []
    assert svc.doc["security"] == first

    # the brief reads fewer records: the grant on the one it no longer reads is taken back, the other stays
    triage_of(svc)["config"]["agentBrief"]["reads"] = ["Pet", "Veterinarian"]
    svc.save()
    report = agent_steps.build_workflow_assistants(svc, commit=False)
    rules = rules_of(svc)
    assert rules["Veterinarian"]["readRoles"] == ["workflow"] and "readRoles" not in rules["Prescription"]
    assert any("Prescription: the `workflow` role no longer reads it" in g for g in report.grants)


def test_when_the_step_is_gone_its_grant_goes_with_it(svc):
    apply_triage(svc)
    agent_steps.build_workflow_assistants(svc, commit=False)
    assert "readRoles" in rules_of(svc)["Veterinarian"]
    host_of(svc)["steps"] = [s for s in host_of(svc)["steps"] if s["type"] != "agent_step"]
    svc.save()
    report = agent_steps.build_workflow_assistants(svc, commit=False)
    assert len(report.grants) == 2 and not any("readRoles" in r for r in rules_of(svc).values())


def test_a_step_that_names_an_assistant_reads_what_that_assistants_tools_read(svc, tmp_path):
    own = agent_for_brief(vet_doc(), {"purpose": "Own.", "reads": ["Veterinarian"]}, None, None, agent_id="app_assistant")
    agent_steps.save_assistant(tmp_path, own["agent"])
    apply_agent_result(svc, proposal(host_body(svc.doc, host_steps(triage(agentBrief=None, agentId="app_assistant",
                                                                         allowedWriteTools=None)))), commit=False)
    agent_steps.build_workflow_assistants(svc, commit=False)
    rules = rules_of(svc)
    assert rules["Veterinarian"]["readRoles"] == ["workflow"] and "readRoles" not in rules["Prescription"]


def test_a_rule_that_already_lets_the_role_do_everything_is_left_as_it_is(svc):
    rules_of(svc)["Veterinarian"]["unscopedRoles"].append("workflow")     # a builder's own decision
    svc.save()
    apply_triage(svc)
    agent_steps.build_workflow_assistants(svc, commit=False)
    assert "readRoles" not in rules_of(svc)["Veterinarian"]


# ---------------------------------------------------------------------------
# names the runtime would refuse at run time, refused at build time
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["confidence", "needsHuman", "summary"])
def test_an_output_field_may_not_take_one_of_the_names_every_answer_has(name):
    fields = [{"name": name, "type": "string", "description": "x"}]
    msg = gate(host_steps(triage(outputFields=fields), check="triage.needsHuman = true"))
    assert f"{name!r} is returned by every assistant step already (confidence, needsHuman, summary)" in msg


def test_two_output_fields_may_not_share_a_name():
    fields = [{"name": "urgency", "type": "string", "description": "a"}, {"name": "urgency", "type": "number", "description": "b"}]
    assert "'urgency' is listed twice" in gate(host_steps(triage(outputFields=fields), check="triage.needsHuman = true"))


def test_an_assistant_may_not_have_a_tool_called_return_result(tmp_path):
    graph = agent_for_brief(vet_doc(), {"purpose": "Own.", "reads": ["Pet"]}, None, None, agent_id="app_assistant")["agent"]
    graph["nodes"].append({"id": "tool_rr", "type": "tool", "position": {"x": 0, "y": 0}, "data": {
        "label": "Return result", "nodeType": "tool", "config": {"tool_name": "return_result", "tool_type": "function"}}})
    agent_steps.save_assistant(tmp_path, graph)
    msg = gate(host_steps(triage(agentBrief=None, agentId="app_assistant")), assistants=agent_steps.load_assistants(tmp_path))
    assert "has a tool called 'return_result'" in msg and "the name the step gives its answer back through" in msg


def test_a_workflow_whose_tool_name_would_be_return_result_cannot_be_given_to_an_assistant():
    doc = vet_doc()
    doc["workflows"].append({"id": "FLOW-009", "name": "Return Result", "purpose": "x", "trigger": {"kind": "manual"},
                             "status": "PROPOSED", "launchedFrom": [], "inputs": [], "steps": []})
    brief = triage()["config"]["agentBrief"]
    brief["mayChange"] = [{"tool": "Return Result", "why": "x"}]
    assert "`return_result` is the name the step gives its answer back through" in gate(host_steps(triage(agentBrief=brief)), doc=doc)
    with pytest.raises(BriefError, match="return_result"):
        agent_for_brief(doc, brief, None, None)
