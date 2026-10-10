"""Two reviews before a build: the requirements, then the product model.

A person agrees first to what the application must do, then to what it is
made of — module by module — and can build all of it or only the modules they
pick. These pin the shape of that: which nodes each review runs, what each
review shows and remembers, how a change is made and reported, and that a
module left for later is declared but never written, laid out or served.
"""
from __future__ import annotations

import json

import pytest

from services.blueprint import approval, orchestrator, scope
from services.blueprint.agent_contract import AgentResult, ArtifactProposal
from services.blueprint.orchestrator import DAG, FANOUT, completed_nodes, page_features
from services.blueprint.service import BlueprintService
from services.smith import gates
from services.smith.smith import domain_nodes, model_nodes


# --------------------------------------------------------------------------- #
# A clinic, defined as far as the product model
# --------------------------------------------------------------------------- #

def _page(pid, name, route, module, entity="", **extra):
    body = {"id": pid, "name": name, "route": route, "purpose": f"{name} purpose",
            "module": module, "requirements": extra.pop("requirements", [])}
    if entity:
        body["data"] = {"primaryEntity": entity}
    body.update(extra)
    return body


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="kids", name="KidsCare", domain="health")
    s.doc["requirements"] = [
        {"id": "REQ-001", "description": "A parent books a visit for a child.", "area": "Booking",
         "acceptanceCriteria": ["a free slot is chosen"], "confidence": 0.9},
        {"id": "REQ-002", "description": "A parent cancels up to 24 hours before.", "area": "Booking",
         "assumption": "24 hours", "confidence": 0.8},
        {"id": "REQ-003", "description": "An admin manages doctors.", "area": "Clinic admin",
         "confidence": 0.9},
    ]
    s.doc["modules"] = [
        {"id": "MODULE-001", "name": "Appointments", "description": "Booking visits."},
        {"id": "MODULE-002", "name": "Clinic admin", "description": "Doctors and hours."},
    ]
    s.doc["data"] = {"entities": [
        {"id": "ENTITY-001", "name": "Appointment", "table": "appointments",
         "fields": [{"name": "slot", "type": "timestamp"}]},
        {"id": "ENTITY-002", "name": "Doctor", "table": "doctors",
         "fields": [{"name": "name", "type": "string"}]},
        {"id": "ENTITY-003", "name": "Clinic", "table": "clinics"},
    ]}
    s.doc["pages"] = [
        _page("PAGE-001", "Book a visit", "/book", "MODULE-001", "ENTITY-001", requirements=["REQ-001"]),
        _page("PAGE-002", "My visits", "/visits", "MODULE-001", "ENTITY-001", requirements=["REQ-002"]),
        _page("PAGE-003", "Doctors", "/admin/doctors", "MODULE-002", "ENTITY-002", requirements=["REQ-003"]),
        _page("PAGE-004", "Weekly hours", "/admin/hours", "MODULE-002", "ENTITY-002"),
        {"id": "PAGE-005", "name": "Sign in", "route": "/login", "purpose": "Sign in",
         "pattern": "auth", "auth": "login"},
        _page("PAGE-006", "Help", "/help", ""),
    ]
    s.doc["pages"][5].pop("module")
    s.doc["navigation"] = {"style": "sidebar", "tree": [
        {"label": "Visits", "children": [{"label": "Book", "page": "PAGE-001"},
                                         {"label": "Mine", "page": "PAGE-002"}]},
        {"label": "Admin", "children": [{"label": "Doctors", "page": "PAGE-003"},
                                        {"label": "Hours", "page": "PAGE-004"}]},
        {"label": "Help", "page": "PAGE-006"},
    ], "initialRoute": {"Admin": "/admin/doctors", "Parent": "/visits"}}
    s.doc["integrations"] = [{"id": "INT-001", "name": "Email", "kind": "email", "serves": "send_email"}]
    s.doc["roles"] = [{"id": "ROLE-001", "name": "Parent"}, {"id": "ROLE-002", "name": "Admin"}]
    s.doc["state"] = "PLAN_REVIEW"
    s.validate()
    s.save()
    return s


# --------------------------------------------------------------------------- #
# Which nodes each review runs
# --------------------------------------------------------------------------- #

def test_the_first_review_is_the_requirements_alone():
    assert domain_nodes() == ["requirements"]


def test_the_product_model_names_the_parts_and_writes_none_of_them_in_detail():
    model = set(model_nodes())
    assert {"application_model", "ux_architecture", "data_model", "entity_fields",
            "page_contracts"} <= model
    # Nothing that writes a screen, a process's steps or code runs before the
    # person has seen the model.
    assert not model & {"page_details", "workflows", "workflow_steps", "page_layouts",
                        "page_code", "frontend", "backend", "assemble"}


def test_every_model_node_can_run_on_what_came_before_it():
    earlier = set(domain_nodes()) | set(model_nodes()) | {"figma_intelligence"}
    for key in model_nodes():
        assert DAG[key].depends_on <= earlier, (key, DAG[key].depends_on - earlier)


# --------------------------------------------------------------------------- #
# Which review is open
# --------------------------------------------------------------------------- #

def test_the_state_says_which_review_is_open(svc, tmp_path):
    svc.doc["state"] = "BLUEPRINT_REVIEW"
    assert gates.current(svc.doc, tmp_path) == gates.REQUIREMENTS
    svc.doc["state"] = "PLANNING"
    assert gates.current(svc.doc, tmp_path) == gates.PRODUCT_MODEL
    svc.doc["state"] = "PLAN_REVIEW"
    assert gates.current(svc.doc, tmp_path) == gates.PRODUCT_MODEL
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "package.json").write_text("{}")
    assert gates.current(svc.doc, tmp_path) is None


# --------------------------------------------------------------------------- #
# Consent is taken against what was shown
# --------------------------------------------------------------------------- #

def test_the_requirements_approval_goes_stale_when_their_wording_changes(svc):
    approval.record(svc, "understanding")
    assert approval.state_of(svc.doc, "understanding") == "approved"
    svc.doc["requirements"][1]["description"] = "A parent cancels up to 12 hours before."
    assert approval.state_of(svc.doc, "understanding") == "stale"


def test_rewording_a_requirement_does_not_unsettle_the_product_model(svc):
    approval.record(svc, "blueprint")
    svc.doc["requirements"][1]["description"] = "A parent cancels up to 12 hours before."
    assert approval.state_of(svc.doc, "blueprint") == "approved"


# --------------------------------------------------------------------------- #
# The product model, module by module
# --------------------------------------------------------------------------- #

def test_the_model_groups_every_part_under_the_module_it_belongs_to(svc):
    view = gates.model_view(svc.doc)
    by = {m["id"]: m for m in view["modules"]}
    assert [p["route"] for p in by["MODULE-001"]["pages"]] == ["/book", "/visits"]
    assert [e["name"] for e in by["MODULE-001"]["entities"]] == ["Appointment"]
    assert [e["name"] for e in by["MODULE-002"]["entities"]] == ["Doctor"]
    assert by["MODULE-001"]["requirements"] == ["REQ-001", "REQ-002"]
    # Sign-in, a screen with no module and a record no screen is about are
    # the foundation every module sits on.
    assert [p["route"] for p in view["foundation"]["auth"]] == ["/login"]
    assert [p["route"] for p in view["foundation"]["pages"]] == ["/help"]
    assert [e["name"] for e in view["foundation"]["entities"]] == ["Clinic"]
    assert [r["name"] for r in view["foundation"]["roles"]] == ["Parent", "Admin"]
    assert view["integrations"][0]["connected"] is True
    assert view["counts"]["modules"] == 2 and view["counts"]["pages"] == 6


def test_a_requirement_no_screen_cites_is_named_as_not_covered(svc):
    svc.doc["requirements"].append({"id": "REQ-004", "description": "Reminders by SMS.",
                                    "confidence": 0.9})
    assert gates.model_view(svc.doc)["uncovered"] == ["REQ-004"]


# --------------------------------------------------------------------------- #
# Versions: what each round showed, and what moved
# --------------------------------------------------------------------------- #

def test_a_round_that_changed_nothing_is_not_a_new_version(svc, tmp_path):
    assert gates.record_version(tmp_path, gates.REQUIREMENTS, svc.doc)["version"] == 1
    assert gates.record_version(tmp_path, gates.REQUIREMENTS, svc.doc)["version"] == 1
    svc.doc["requirements"][0]["description"] = "A parent books a visit for one of their children."
    assert gates.record_version(tmp_path, gates.REQUIREMENTS, svc.doc)["version"] == 2


def test_the_diff_names_what_was_added_removed_and_reworded(svc, tmp_path):
    before = gates.requirement_items(svc.doc)
    svc.doc["requirements"][1]["description"] = "A parent cancels up to 12 hours before."
    svc.doc["requirements"][2]["status"] = "DEPRECATED"
    svc.doc["requirements"].append({"id": "REQ-004", "description": "Reminders by SMS.",
                                    "confidence": 0.9})
    change = gates.requirements_diff(before, gates.requirement_items(svc.doc))
    assert change["added"] == ["REQ-004"]
    assert [r["id"] for r in change["removed"]] == ["REQ-003"]
    assert change["changed"] == [{"id": "REQ-002", "was": "A parent cancels up to 24 hours before."}]


def test_the_panel_sees_the_diff_of_the_last_round_only(svc, tmp_path):
    gates.record_version(tmp_path, gates.REQUIREMENTS, svc.doc)
    svc.doc["requirements"][0]["description"] = "Booking, reworded."
    gates.record_version(tmp_path, gates.REQUIREMENTS, svc.doc)
    out = gates.payload(svc.doc, tmp_path)
    assert out["gate"] == gates.PRODUCT_MODEL
    assert out[gates.REQUIREMENTS]["version"] == 2
    assert out[gates.REQUIREMENTS]["diff"]["changed"][0]["id"] == "REQ-001"
    assert out[gates.PRODUCT_MODEL]["items"]["counts"]["modules"] == 2


# --------------------------------------------------------------------------- #
# Making a change
# --------------------------------------------------------------------------- #

def _executor(replies):
    """An owning agent that answers each node with the proposals given."""
    asked = []

    def author(spec):
        asked.append(spec)
        return AgentResult(task_id=spec.task_id, agent=spec.agent,
                           proposals=[ArtifactProposal(section, key, dict(body))
                                      for section, key, body in replies.get(spec.node, [])],
                           confidence=0.95)
    author.asked = asked
    return author


def test_a_requirements_change_is_redrafted_by_its_owner_and_reported(svc, tmp_path):
    svc.doc["state"] = "BLUEPRINT_REVIEW"
    run = _executor({"requirements": [
        ("requirements", "REQ-002", {"id": "REQ-002", "area": "Booking", "confidence": 0.95,
                                     "description": "A parent cancels up to 12 hours before."}),
        ("requirements", "sms", {"description": "A parent gets an SMS the day before.",
                                 "area": "Notifications", "confidence": 0.95}),
        ("product", "product", {"objectives": ["should be dropped"]}),
    ]})
    out = gates.revise_requirements(svc, "cutoff is 12 hours; add an SMS reminder",
                                    remove=["REQ-003"], executor=run)
    assert "cutoff is 12 hours" in run.asked[0].brief
    assert out["version"] == 2
    assert [r["id"] for r in out["diff"]["removed"]] == ["REQ-003"]
    assert out["diff"]["changed"][0]["id"] == "REQ-002"
    assert len(out["diff"]["added"]) == 1
    assert "should be dropped" not in json.dumps(svc.doc.get("product") or {})
    said = gates.say_requirements_change(out["diff"], out["version"])
    assert "v2 added 1, removed 1, changed 1" in said and "lock these in" in said


def test_a_model_change_retires_moves_renames_and_records_new_behaviour(svc, tmp_path):
    approval.record(svc, "understanding")
    turn = {"kind": "change", "brief": "", "parts": [], "remove": ["PAGE-004"],
            "move": [{"page": "PAGE-003", "module": "MODULE-001"}],
            "rename": [{"id": "MODULE-001", "name": "Visits"}],
            "newRequirements": [{"description": "Doctors are listed beside visits.", "area": "Booking"}]}
    out = gates.revise_model(svc, turn, request="put doctors with visits, drop hours",
                             executor=_executor({}))
    view = gates.model_view(svc.doc)
    first = view["modules"][0]
    assert first["name"] == "Visits"
    assert [p["route"] for p in first["pages"]] == ["/book", "/visits", "/admin/doctors"]
    assert all(p["route"] != "/admin/hours" for m in view["modules"] for p in m["pages"])
    assert out["requirements"] and out["requirements"][0].startswith("REQ-")
    # The person asked for it in this sentence: it joins the approved list.
    assert approval.state_of(svc.doc, "understanding") == "approved"
    said = gates.say_model_change(out)
    assert "added" in said and out["requirements"][0] in said


def test_a_model_change_is_briefed_only_to_the_owners_of_what_it_touches(svc):
    run = _executor({"page_contracts": [
        ("pages", "/waitlist", {"name": "Waitlist", "route": "/waitlist", "purpose": "Join a waitlist",
                                "module": "MODULE-001"})]})
    out = gates.revise_model(svc, {"kind": "change", "brief": "add a waitlist to appointments",
                                   "parts": ["screens"], "remove": [], "move": [], "rename": [],
                                   "newRequirements": []}, executor=run)
    assert [s.node for s in run.asked] == ["page_contracts"]
    assert "add a waitlist" in run.asked[0].brief
    changed = {m["id"]: m for m in out["diff"]["changed"]}
    assert len(changed["MODULE-001"]["added"]) == 1


def test_an_owner_with_nothing_to_add_is_not_a_failed_change(svc):
    out = gates.revise_model(svc, {"kind": "change", "brief": "rename nothing", "parts": ["records"],
                                   "remove": [], "move": [], "rename": [], "newRequirements": []},
                             executor=_executor({}))
    assert out["wrote"] == 0


def test_the_message_is_interpreted_against_what_is_on_screen(svc):
    seen = {}

    def client(*, system, user, schema):
        seen.update(system=system, user=user, schema=schema)
        return json.dumps({"kind": "question", "answer": "Twelve hours.", "brief": "", "parts": [],
                           "remove": [], "move": [], "rename": [], "newRequirements": []})
    out = gates.interpret(svc.doc, gates.PRODUCT_MODEL, "what is the cutoff?", client=client)
    assert out["kind"] == "question" and out["answer"] == "Twelve hours."
    assert "Appointments" in seen["user"] and "approvedRequirements" in seen["user"]


def test_no_turn_schema_carries_a_keyword_the_api_refuses():
    refused = {"maxItems", "minItems", "maxLength", "minLength", "pattern", "maximum", "minimum",
               "uniqueItems", "multipleOf"}
    text = json.dumps(gates.TURN_SCHEMA)
    assert not [k for k in refused if f'"{k}"' in text]


# --------------------------------------------------------------------------- #
# A module left for later: declared, never written, laid out or served
# --------------------------------------------------------------------------- #

def test_choosing_modules_defers_the_rest_and_none_means_everything(svc):
    said = scope.choose(svc, ["MODULE-001"])
    assert said == {"built": ["Appointments"], "waiting": ["Clinic admin"]}
    assert scope.deferred_page_ids(svc.doc) == {"PAGE-003", "PAGE-004"}
    scope.choose(svc, None)
    assert scope.deferred_page_ids(svc.doc) == set()
    assert not any(m.get("deferred") for m in svc.doc["modules"])


def test_a_deferred_modules_screens_are_not_fanned_out(svc):
    scope.choose(svc, ["MODULE-001"])
    assert set(FANOUT["pages"](svc.doc)) == {"PAGE-001", "PAGE-002", "PAGE-005", "PAGE-006"}
    written = {p["id"] for subject in page_features(svc.doc)
               for p in orchestrator.feature_pages(svc.doc, subject)}
    assert not written & {"PAGE-003", "PAGE-004"}


def test_a_scoped_build_is_complete_when_the_chosen_screens_are(svc):
    scope.choose(svc, ["MODULE-001"])
    svc.doc["pageCode"] = [{"page": pid, "view": "x"} for pid in ("PAGE-001", "PAGE-002", "PAGE-005", "PAGE-006")]
    assert "page_code" in completed_nodes(svc.doc)
    # Building the waiting module later is the same run with its screens pending.
    scope.choose(svc, None)
    assert "page_code" not in completed_nodes(svc.doc)


def test_the_running_app_never_sees_a_deferred_screen(svc):
    scope.choose(svc, ["MODULE-001"])
    view = scope.built_view(svc.doc)
    assert {p["id"] for p in view["pages"]} == {"PAGE-001", "PAGE-002", "PAGE-005", "PAGE-006"}
    labels = [n["label"] for n in view["navigation"]["tree"]]
    assert labels == ["Visits", "Help"]          # the Admin heading had nothing left under it
    assert view["navigation"]["initialRoute"] == {"Parent": "/visits"}
    assert [m["id"] for m in view["modules"]] == ["MODULE-001"]
    # The Blueprint keeps them: they are still the product the person agreed to.
    assert len(svc.doc["pages"]) == 6


def test_nothing_deferred_is_the_document_itself(svc):
    assert scope.built_view(svc.doc) is svc.doc


def test_a_sign_in_page_is_never_deferred(svc):
    svc.doc["pages"][4]["module"] = "MODULE-002"
    scope.choose(svc, ["MODULE-001"])
    assert "PAGE-005" not in scope.deferred_page_ids(svc.doc)


def test_a_waiting_screen_is_not_reported_as_missing(svc):
    from services.blueprint.functional_completeness import functional_findings
    scope.choose(svc, ["MODULE-001"])
    missing = {f["page"] for f in functional_findings(svc.doc) if f.get("rule") == "page-not-composed"}
    assert not missing & {"PAGE-003", "PAGE-004"}
    assert {"PAGE-001", "PAGE-002"} <= missing


def test_the_layout_service_skips_a_waiting_screen(svc, monkeypatch):
    laid = []
    monkeypatch.setattr("services.blueprint.template_page.template_layout",
                        lambda doc, page: laid.append(page["id"]) or {"page": page["id"], "root": {}})
    monkeypatch.setattr("services.blueprint.orchestrator.apply_agent_result", lambda *a, **k: None)
    scope.choose(svc, ["MODULE-001"])
    orchestrator._compose_page_layouts(svc)
    assert set(laid) == {"PAGE-001", "PAGE-002", "PAGE-006"}


def test_a_change_refused_part_way_leaves_the_document_as_it_was(svc):
    def refuses(spec):
        return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.95, proposals=[
            ArtifactProposal("pages", "/x", {"route": "/x", "purpose": "a page with no name"})])
    before = json.dumps(svc.doc, sort_keys=True)
    with pytest.raises(gates.GateChangeError):
        gates.revise_model(svc, {"kind": "change", "brief": "add x", "parts": ["screens"],
                                 "remove": ["PAGE-004"], "move": [], "rename": [],
                                 "newRequirements": [{"description": "X exists.", "area": "X"}]},
                           executor=refuses)
    assert json.dumps(svc.doc, sort_keys=True) == before
    assert gates.versions(svc.output_dir, gates.REQUIREMENTS) == []


# --------------------------------------------------------------------------- #
# Through the router
# --------------------------------------------------------------------------- #

class _Report:
    def __init__(self, completed=()):
        self.completed = list(completed)
        self.skipped, self.blocked, self.failed = [], [], []


@pytest.fixture()
def dag(monkeypatch):
    """The DAG's run, recorded rather than spent."""
    ran: dict = {}
    monkeypatch.setattr("services.blueprint.executors.RunUsage.for_app",
                        classmethod(lambda cls, s, **k: type("U", (), {"summary": lambda self: {}})()))
    monkeypatch.setattr("services.blueprint.executors.tiered_router", lambda **k: object())
    monkeypatch.setattr("services.blueprint.executors.make_executor", lambda *a, **k: object())
    monkeypatch.setattr("services.blueprint.observer.anthropic_observer", lambda *a, **k: None)

    def run(svc, executor, *, plan, **k):
        ran["plan"] = list(plan)
        ran["modules"] = [(m["id"], bool(m.get("deferred"))) for m in svc.doc.get("modules") or []]
        return _Report(completed=plan)
    monkeypatch.setattr("services.blueprint.orchestrator.run", run)
    return ran


def test_approving_the_requirements_works_out_the_model_and_stops_at_its_review(svc, dag, tmp_path):
    from routers import blueprint_generate as router
    svc.doc["state"] = "BLUEPRINT_REVIEW"
    svc.doc["pageCode"] = []
    svc.save()
    said: list[tuple[str, dict]] = []
    out = router._approve_requirements(str(tmp_path), str(tmp_path / "app"),
                                       emit=lambda kind, data: said.append((kind, data)),
                                       message="Approve requirements")
    after = BlueprintService.load(output_dir=str(tmp_path)).doc
    assert set(dag["plan"]) <= set(model_nodes())
    assert out["awaitingApproval"] is True and out["phase"] == "model"
    assert after["state"] == "PLAN_REVIEW"
    assert approval.state_of(after, "understanding") == "approved"
    assert approval.state_of(after, "plan") == "open", "nothing is authorised to build yet"
    texts = [d.get("text", "") for k, d in said if k == "message"]
    assert any("are locked" in t for t in texts)
    assert any("Here is the whole app in **2 modules**" in t for t in texts)
    assert gates.versions(str(tmp_path), gates.PRODUCT_MODEL)[-1]["version"] == 1


def test_building_picked_modules_records_the_choice_and_both_approvals(svc, dag, tmp_path):
    from routers import blueprint_generate as router
    said: list = []
    router._run_dag(str(tmp_path), str(tmp_path / "app"), "", approved=True,
                    emit=lambda kind, data: said.append((kind, data)), modules=["MODULE-001"])
    assert dag["modules"] == [("MODULE-001", False), ("MODULE-002", True)]
    after = BlueprintService.load(output_dir=str(tmp_path)).doc
    assert approval.latest(after, "blueprint") and approval.latest(after, "plan")


def test_building_the_whole_app_builds_every_module(svc, dag, tmp_path):
    from routers import blueprint_generate as router
    scope.choose(svc, ["MODULE-001"])
    router._run_dag(str(tmp_path), str(tmp_path / "app"), "", approved=True,
                    emit=lambda kind, data: None, modules=None)
    assert dag["modules"] == [("MODULE-001", False), ("MODULE-002", False)]


def test_the_build_announcement_names_the_modules_that_wait(svc):
    from routers import blueprint_generate as router
    scope.choose(svc, ["MODULE-001"])
    svc.doc["pageCode"] = [{"page": p, "view": "x"} for p in ("PAGE-001", "PAGE-002", "PAGE-006")]
    svc.doc["runtime"] = {"pages": {"planned": 4, "served": 4}}
    text = router._build_complete_message(svc.doc)
    assert "4 pages ready" in text and "Not built yet, as you chose: Clinic admin" in text


def _req(message, history=()):
    from routers.blueprint_generate import SmithChatRequest, SmithChatTurn
    return SmithChatRequest(message=message, history=[SmithChatTurn(role=r, text=t) for r, t in history])


def _turn(kind, **extra):
    return {"kind": kind, "answer": "", "brief": "", "parts": [], "remove": [], "move": [],
            "rename": [], "newRequirements": [], **extra}


def test_a_question_at_a_review_is_answered_and_changes_nothing(svc, tmp_path, monkeypatch):
    from routers import blueprint_generate as router
    monkeypatch.setattr(gates, "interpret", lambda *a, **k: _turn("question", answer="Two modules."))
    said: list = []
    out = router._gate_turn(svc, gates.PRODUCT_MODEL, str(tmp_path), "", _req("how many modules?"),
                            emit=lambda kind, data: said.append((kind, data)))
    assert out == {"status": "reported"} and said[0][1]["text"] == "Two modules."


def test_something_else_at_a_review_goes_to_the_ordinary_turn(svc, tmp_path, monkeypatch):
    from routers import blueprint_generate as router
    monkeypatch.setattr(gates, "interpret", lambda *a, **k: _turn("other"))
    assert router._gate_turn(svc, gates.REQUIREMENTS, str(tmp_path), "", _req("connect my figma"),
                             emit=lambda *a: None) is None


def test_yes_to_the_model_asks_whether_to_build_all_or_some(svc, tmp_path, monkeypatch):
    from routers import blueprint_generate as router
    monkeypatch.setattr(gates, "interpret", lambda *a, **k: _turn("approve"))
    said: list = []
    out = router._gate_turn(svc, gates.PRODUCT_MODEL, str(tmp_path), "", _req("looks right"),
                            emit=lambda kind, data: said.append((kind, data)))
    assert out["status"] == "asked" and said[0][1]["options"] == ["Build the whole app"]
    assert router._is_build_consent("Build the whole app")


def test_a_change_at_the_requirements_review_is_made_and_reported(svc, tmp_path, monkeypatch):
    from routers import blueprint_generate as router
    monkeypatch.setattr(gates, "interpret",
                        lambda *a, **k: _turn("change", brief="cutoff is 12 hours", remove=["REQ-003"]))
    asked = {}
    monkeypatch.setattr(gates, "revise_requirements", lambda svc, brief, **k: asked.update(brief=brief, **k) or {
        "version": 2, "diff": {"added": [], "removed": [{"id": "REQ-003"}], "changed": [{"id": "REQ-002"}]}})
    said: list = []
    out = router._gate_turn(svc, gates.REQUIREMENTS, str(tmp_path), "", _req("12 hours, and no admin"),
                            emit=lambda kind, data: said.append((kind, data)))
    assert asked["brief"] == "cutoff is 12 hours" and asked["remove"] == ["REQ-003"]
    assert out["status"] == "resolved" and "v2 removed 1, changed 1" in said[0][1]["text"]


def test_typed_yes_at_the_requirements_review_is_not_a_build():
    from routers import blueprint_generate as router
    for said in ("Approve requirements", "looks good", "lgtm"):
        assert router._is_gate_consent(said)
    assert not router._is_gate_consent("approve the refund flow")


def test_a_model_that_did_not_finish_says_so(svc, monkeypatch, tmp_path):
    from routers import blueprint_generate as router
    svc.doc["state"] = "BLUEPRINT_REVIEW"
    svc.save()
    monkeypatch.setattr(router, "_run_dag", lambda *a, **k: {
        "awaitingApproval": True, "report": {"failed": [{"node": "page_contracts", "why": "x"}]}})
    said: list = []
    router._approve_requirements(str(tmp_path), "", emit=lambda kind, data: said.append(data))
    assert "couldn't finish" in said[-1]["text"] and "page_contracts" in said[-1]["text"]


def test_rewording_an_approved_requirement_at_the_model_keeps_it_approved(svc):
    approval.record(svc, "understanding")
    run = _executor({"requirements": [
        ("requirements", "REQ-002", {"id": "REQ-002", "area": "Booking", "confidence": 0.95,
                                     "description": "A parent cancels up to 6 hours before."})]})
    out = gates.revise_model(svc, {"kind": "change", "brief": "", "parts": [], "remove": [],
                                   "move": [], "rename": [], "newRequirements": [],
                                   "requirementsChange": "REQ-002: the cutoff is 6 hours"},
                             executor=run)
    assert out["reworded"]["diff"]["changed"][0]["id"] == "REQ-002"
    assert approval.state_of(svc.doc, "understanding") == "approved"
    assert "stay approved" in gates.say_model_change(out)


def test_a_reworded_requirement_keeps_its_id_and_is_not_restated_beside_itself(svc):
    """Live, 2026-09-27: "capture country, state and city as well" — the
    requirements agent, told a reworded requirement keeps its id, wrote a
    second one beside it. Rewording is applied here; the agent is asked only
    for what is new, and here nothing is."""
    svc.doc["state"] = "BLUEPRINT_REVIEW"

    def must_not_be_asked(spec):
        raise AssertionError("a rewording alone must not reach the agent")
    out = gates.revise_requirements(
        svc, "", request="capture the location as well",
        reword=[{"id": "REQ-001", "description": "A parent books a visit for a child, "
                                                 "giving the clinic's city."}],
        executor=must_not_be_asked)
    reqs = {r["id"]: r["description"] for r in gates.requirement_items(svc.doc)}
    assert reqs["REQ-001"].endswith("giving the clinic's city.")
    assert len(reqs) == 3, "no second requirement beside the reworded one"
    assert out["diff"] == {"added": [], "removed": [],
                           "changed": [{"id": "REQ-001", "was": "A parent books a visit for a child."}]}
    # The id stays writable under its new wording: the next redraft updates it.
    from services.blueprint.ids import IdAllocator, natural_key_for
    alloc = IdAllocator.load(output_dir=svc.output_dir)
    assert alloc.lookup(natural_key_for("requirements", {"description": reqs["REQ-001"]})) == "REQ-001"


def test_who_may_do_what_is_a_part_of_the_model_briefed_to_security(svc):
    """Ecom L1 (2026-10-11): "vendors must only see and manage their own
    products" was filed as a requirement, no owner was briefed, and the gate
    said "Done." over a security section whose vendor rules were prose."""
    assert "access" in gates.TURN_SCHEMA["properties"]["parts"]["items"]["enum"]
    run = _executor({"security": [("roles", "Vendor", {"name": "Vendor", "description": "Sells"})]})
    out = gates.revise_model(svc, {"kind": "change", "brief": "vendors see only their own products",
                                   "parts": ["access"], "remove": [], "move": [], "rename": [],
                                   "newRequirements": []}, executor=run)
    assert [s.node for s in run.asked] == ["security"]
    assert "ownershipRules" in run.asked[0].brief and "prose" in run.asked[0].brief
    assert "who may do what" in gates.say_model_change(out)


def test_a_requirement_written_down_with_no_part_briefed_is_not_done(svc):
    approval.record(svc, "understanding")
    out = gates.revise_model(svc, {"kind": "change", "brief": "", "parts": [], "remove": [], "move": [],
                                   "rename": [], "newRequirements": [
                                       {"description": "Vendors see only their own products.", "area": "Vendors"}]},
                             executor=_executor({}))
    said = gates.say_model_change(out)
    assert "Done" not in said and "changed nothing in the model" in said and out["requirements"][0] in said
