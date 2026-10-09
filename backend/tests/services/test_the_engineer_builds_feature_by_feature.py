"""The engineer builds the approved definition one feature at a time, and
proves each before the next.

The build was a graph of 33 steps authored by 22 roles, each filling a slice
and judged by code, the app run only at the end: 9 of 35 apps on forge-v3
shipped with no page code, 5 processes with no steps were wired to live
buttons, 126 of 169 statements were never tried (2026-10-09). The engineer
runs the same nodes for one feature — a module the person approved — then
builds, tries the feature's statements, fixes, and only then moves on.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.engineer import features as F
from services.engineer.build import FeatureScope, build, build_nodes, fix_ask

DOC = {
    "modules": [{"id": "MODULE-001", "name": "Catalogue", "pages": ["PAGE-001", "PAGE-002"]},
                {"id": "MODULE-002", "name": "Cart & Checkout", "pages": ["PAGE-003"]},
                {"id": "MODULE-003", "name": "Accounts", "pages": ["PAGE-004"]}],
    "pages": [
        {"id": "PAGE-001", "route": "/", "pattern": "dashboard", "module": "MODULE-001",
         "data": {"primaryEntity": "ENTITY-003"}, "requirements": ["REQ-001"]},
        {"id": "PAGE-002", "route": "/products", "pattern": "entity_list", "module": "MODULE-001",
         "data": {"primaryEntity": "ENTITY-003"}, "requirements": ["REQ-001", "REQ-002"]},
        {"id": "PAGE-003", "route": "/cart", "pattern": "entity_list", "module": "MODULE-002",
         "data": {"primaryEntity": "ENTITY-004"}, "requirements": ["REQ-004"]},
        {"id": "PAGE-004", "route": "/account", "pattern": "dashboard", "module": "MODULE-003",
         "data": {"primaryEntity": "ENTITY-001"}, "requirements": ["REQ-008"]},
        {"id": "PAGE-005", "route": "/products/compare", "pattern": "entity_list",   # no module: joins Product's home
         "data": {"primaryEntity": "ENTITY-003"}, "requirements": ["REQ-002"]},
        {"id": "PAGE-014", "route": "/login", "pattern": "auth"},
    ],
    "data": {"entities": [
        {"id": "ENTITY-001", "name": "Customer", "fields": [{"name": "email", "type": "string"}]},
        {"id": "ENTITY-003", "name": "Product", "fields": [{"name": "name", "type": "string"}]},
        {"id": "ENTITY-004", "name": "CartItem", "fields": [
            {"name": "customerId", "type": "uuid", "references": "ENTITY-001"},
            {"name": "productId", "type": "uuid", "references": "ENTITY-003"}]},
    ]},
    "requirements": [{"id": f"REQ-00{n}", "area": a, "acceptanceCriteria": ["x"]}
                     for n, a in ((1, "Catalogue"), (2, "Catalogue"), (4, "Cart"), (8, "Accounts"))],
    "workflows": [
        {"id": "FLOW-001", "name": "Add to Cart", "launchedFrom": ["PAGE-002"], "inputs": []},
        {"id": "FLOW-005", "name": "Update Profile", "launchedFrom": ["PAGE-004"], "inputs": []},
        {"id": "FLOW-009", "name": "Restock", "trigger": {"kind": "scheduled"},
         "inputs": [{"name": "product", "kind": "record", "entity": "ENTITY-003"}]},
    ],
    "expectations": [
        {"id": "EXP-001", "requirements": ["REQ-001"], "steps": [{"act": "open", "page": "PAGE-002"}]},
        {"id": "EXP-013", "requirements": ["REQ-004"], "steps": [{"act": "do", "workflow": "FLOW-001"}]},
        {"id": "EXP-027", "requirements": [], "steps": [{"act": "sign_in"}, {"act": "open", "page": "PAGE-004"}]},
    ],
}


def test_features_are_the_approved_modules_in_order_of_dependence():
    plan = F.features(DOC)
    assert [f.id for f in plan] == ["MODULE-001", "MODULE-003", "MODULE-002"], \
        "the cart points at customers and products, so it comes after both"
    cat = plan[0]
    assert cat.pages == ["PAGE-001", "PAGE-002", "PAGE-005"], "a page in no module joins its entity's home"
    assert cat.entities == ["ENTITY-003"] and cat.requirements == ["REQ-001", "REQ-002"]
    assert not any("PAGE-014" in f.pages for f in plan), "an auth page belongs to no feature"


def test_with_no_modules_the_whole_application_is_one_feature():
    doc = {**DOC, "modules": []}
    doc["pages"] = [{k: v for k, v in p.items() if k != "module"} for p in DOC["pages"]]
    plan = F.features(doc)
    assert len(plan) == 1 and plan[0].name == F.WHOLE and len(plan[0].pages) == 5


def test_each_node_has_a_part_that_belongs_to_the_feature(monkeypatch):
    from services.blueprint import orchestrator
    plan = F.features(DOC)
    cat, acc, cart = plan
    pages = ["PAGE-001", "PAGE-002", "PAGE-003", "PAGE-004", "PAGE-005"]
    assert F.subjects_of(cat, "page_code", DOC, pages, first=True) == ["PAGE-001", "PAGE-002", "PAGE-005"]
    groups = orchestrator.page_subjects(DOC)
    assert F.subjects_of(cart, "page_details", DOC, list(groups), first=False) == ["ENTITY-004"]
    assert F.subjects_of(cat, "workflow_steps", DOC, ["FLOW-001", "FLOW-005", "FLOW-009"], first=True) == ["FLOW-001", "FLOW-009"], \
        "a process is written with the screen that launches it; one nothing launches, where its records are"
    assert F.subjects_of(cart, "workflow_steps", DOC, ["FLOW-001", "FLOW-005", "FLOW-009"], first=False) == []
    assert F.subjects_of(acc, "workflow_steps", DOC, ["FLOW-001", "FLOW-005", "FLOW-009"], first=False) == ["FLOW-005"]
    assert F.subjects_of(cat, "workflows", DOC, [""], first=True) == [""], "a node that writes once runs once"
    monkeypatch.setattr("services.expects.statements.expect_subjects",
                        lambda doc: {"people": {}, "REQ-001": {"requirements": ["REQ-001", "REQ-002"]},
                                     "REQ-004": {"requirements": ["REQ-004", "REQ-008"]}})
    assert F.subjects_of(cat, "expectations", DOC, ["people", "REQ-001", "REQ-004"], first=True) == ["people", "REQ-001"]
    assert F.subjects_of(cart, "expectations", DOC, ["people", "REQ-001", "REQ-004"], first=False) == ["REQ-004"]
    assert F.statements_of(cat, DOC) == ["EXP-001"]
    assert F.statements_of(cart, DOC) == ["EXP-013"]
    assert F.statements_of(acc, DOC) == ["EXP-027"], "a statement that moves through its screen is its"


def test_a_node_that_writes_once_is_told_which_feature_this_call_is_for():
    cat = F.features(DOC)[0]
    brief = F.brief_for(cat, "workflows", DOC)
    assert "THIS CALL IS FOR ONE FEATURE: Catalogue" in brief and "/products" in brief
    assert "stays exactly as it is" in brief
    assert F.brief_for(cat, "page_code", DOC) == "", "a fan-out node is narrowed by subject, not briefed"
    scope = FeatureScope(cat, first=True).on(DOC)
    assert scope.brief("workflows", "") and scope.brief("page_code", "PAGE-001") == ""


def test_the_build_phase_is_split_into_once_per_feature_and_last():
    once, per, last = build_nodes()
    assert "install" in once and "auth_pages" in once
    assert per[0] == "page_details" and per[-1] == "assemble" and "workflow_steps" in per
    assert per.index("workflows") < per.index("workflow_steps") < per.index("page_code")
    assert last == ["memory", "verification"]
    assert not set(once) & set(per) and not set(per) & set(last)


def _project(tmp_path):
    import json
    from services.blueprint.service import BlueprintService
    svc = BlueprintService.create(output_dir=tmp_path, app_id="shop", name="Shop", domain="retail")
    for k, v in DOC.items():
        svc.doc[k] = json.loads(json.dumps(v))
    svc.save()
    (tmp_path / "app").mkdir()
    return svc


def test_the_engineer_builds_each_feature_and_proves_it_before_the_next(tmp_path):
    _project(tmp_path)
    runs: list[tuple[list[str], str | None]] = []
    proofs: list[tuple[list[str] | None, bool | None]] = []
    fixes: list[str] = []
    said: list[str] = []
    attempts = {"EXP-013": 0}

    def run(svc, executor, *, plan, scope=None, **kw):
        runs.append((list(plan), scope.feature.id if scope else None))
        return SimpleNamespace(failed=[], paused_because="")

    def prove(svc, output_dir, only=None, give_back=None, **kw):
        proofs.append((only, give_back))
        rows = []
        for sid in only or ["EXP-001", "EXP-013", "EXP-027"]:
            if sid == "EXP-013":
                attempts[sid] += 1
                ok = attempts[sid] >= 2           # fails with its authors' look; holds after one fix turn
            else:
                ok = True
            rows.append({"id": sid, "says": sid, "verdict": "passed" if ok else "failed",
                         "failures": [] if ok else ["Customer was told nothing: nothing was sent"]})
        return {"statements": len(rows), "passed": sum(r["verdict"] == "passed" for r in rows),
                "failing": [r["id"] for r in rows if r["verdict"] == "failed"], "untried": [],
                "fixed": [], "results": rows}

    def fix(output_dir, ask):
        fixes.append(ask)
        return {"status": "done", "answer": "wired the button"}

    out = build(str(tmp_path), str(tmp_path / "app"), emit=lambda k, d: said.append(d.get("text", "")),
                executor=object(), run=run, prove=prove, fix=fix)
    assert [r[1] for r in runs] == [None, "MODULE-001", "MODULE-003", "MODULE-002", None]
    once, per, last = build_nodes()
    assert runs[0][0] == once and runs[1][0] == per and runs[-1][0] == last
    assert proofs[0] == (["EXP-001"], True), "the first feature's own statements, with the authors' look"
    assert (["EXP-013"], True) in proofs and (["EXP-013"], False) in proofs, "then the fix turn's result is tried again"
    assert len(fixes) == 1 and "Cart & Checkout" in fixes[0] and "nothing was sent" in fixes[0]
    assert sorted(proofs[-1][0]) == ["EXP-001", "EXP-013", "EXP-027"] and proofs[-1][1] is True, \
        "every statement once more at the end, with its authors' look"
    assert [f["feature"] for f in out["features"]] == ["MODULE-001", "MODULE-003", "MODULE-002"]
    cart = out["features"][2]
    assert cart["passed"] == 1 and cart["fixed"] == ["EXP-013"] and cart["failing"] == []
    assert any("Cart & Checkout: 1 of 1 statement of what must happen hold; fixed while building: EXP-013" in s for s in said)
    assert out["statements"]["passed"] == 3 and not out["stopped"]
    from services.engineer.journal import Journal
    assert Journal(tmp_path).finished() == ["MODULE-001", "MODULE-003", "MODULE-002"]


def test_a_run_picks_up_where_the_last_one_stopped_and_stops_on_its_budget(tmp_path, monkeypatch):
    _project(tmp_path)
    from services.engineer.journal import Journal
    j = Journal(tmp_path)
    j.write("feature:done", feature="MODULE-001")
    runs = []

    def run(svc, executor, *, plan, scope=None, **kw):
        runs.append(scope.feature.id if scope else None)
        return SimpleNamespace(failed=[], paused_because="")
    prove = lambda svc, od, **kw: {"statements": 0, "passed": 0, "failing": [], "untried": [], "fixed": [], "results": []}
    from services.engineer import build as B
    monkeypatch.setattr(B.Budget, "over", lambda self: len(runs) >= 1)   # time runs out after one feature
    out = build(str(tmp_path), str(tmp_path / "app"), executor=object(), run=run, prove=prove,
                fix=lambda od, ask: {}, budget_minutes=1)
    assert runs == ["MODULE-003"], "the once-nodes and the finished feature are not run again"
    assert out["stopped"].startswith("out of time") and out["statements"] == {}
    assert j.finished() == ["MODULE-001", "MODULE-003"]
    assert j.last("run:out_of_time")["left"] == ["MODULE-002"]


def test_one_engineer_per_app_at_a_time(tmp_path):
    from services.engineer.journal import Busy, Journal
    _project(tmp_path)
    Journal(tmp_path).acquire()
    with pytest.raises(Busy):
        build(str(tmp_path), str(tmp_path / "app"), executor=object(), run=lambda *a, **k: None,
              prove=lambda *a, **k: {}, fix=lambda *a: {})


def test_the_fix_turn_is_told_the_feature_the_failures_and_the_rule():
    cat = F.features(DOC)[0]
    ask = fix_ask(cat, [{"says": "A shopper sees the products", "failures": ["guest does not see 'Mug' on /products"]}])
    assert "While building Catalogue" in ask and "guest does not see 'Mug'" in ask
    assert "try_expectation" in ask and "platform itself is not yours to patch around" in ask


def test_the_scheduler_runs_only_the_scoped_subjects(tmp_path, monkeypatch):
    """A feature's run of `entity_fields` authors the feature's entities and
    no other; a scope's brief rides on the call."""
    from services.blueprint import orchestrator
    from services.blueprint.agent_contract import AgentResult, ArtifactProposal
    from services.blueprint.service import BlueprintService
    monkeypatch.delitem(orchestrator.OBSERVER_ROUNDS_BY_NODE, "entity_fields", raising=False)
    svc = BlueprintService.create(output_dir=tmp_path, app_id="lab", name="Lab", domain="health")
    svc.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "User", "table": "users"},
                                    {"id": "ENTITY-002", "name": "Booking", "table": "bookings"}]}
    svc.save()
    asked = []

    def author(spec):
        asked.append((spec.subject, spec.brief))
        entity = next(e for e in svc.doc["data"]["entities"] if e["id"] == spec.subject)
        body = {k: v for k, v in entity.items() if k not in ("id", "fields")}
        body["fields"] = [{"name": "id", "type": "uuid", "primaryKey": True}]
        return AgentResult(task_id=spec.task_id, agent=spec.agent, confidence=0.9,
                           proposals=[ArtifactProposal(section="data.entities", natural_key=entity["name"], body=body)])

    class OnlyBooking:
        def subjects(self, node, doc, pending):
            return [s for s in pending if s == "ENTITY-002"]

        def brief(self, node, subject):
            return "for the booking feature"

    report = orchestrator.run(svc, author, plan=["entity_fields"], commit=True, scope=OnlyBooking())
    assert asked == [("ENTITY-002", "for the booking feature")]
    assert "entity_fields" in report.completed


def test_the_engineer_works_on_the_callers_document(tmp_path):
    """Crumb (forge-v3, 2026-10-09): the build entry kept its own copy of the
    definition while the engineer loaded another; the state-settling save at
    the end wrote the model-phase document (v27) over the built one (v62)."""
    svc = _project(tmp_path)
    seen = []
    run = lambda s, executor, *, plan, scope=None, **kw: (seen.append(s), SimpleNamespace(failed=[], paused_because=""))[1]
    prove = lambda s, od, **kw: {"statements": 0, "passed": 0, "failing": [], "untried": [], "fixed": [], "results": []}
    build(str(tmp_path), str(tmp_path / "app"), executor=object(), run=run, prove=prove, fix=lambda od, ask: {}, svc=svc)
    assert seen and all(s is svc for s in seen), "every run is on the one document the caller holds"


def test_a_node_that_failed_for_a_feature_is_mended_and_run_again(tmp_path):
    """Crumb's assemble refused /baker/items — "needs a workflow that does not
    exist yet: unmark an item as sold out" — and the engineer went on to try
    the feature as if it had built (2026-10-09)."""
    _project(tmp_path)
    plans: list[tuple[list[str], str | None]] = []
    fixes: list[str] = []
    calls = {"n": 0}

    def run(svc, executor, *, plan, scope=None, **kw):
        plans.append((list(plan), scope.feature.id if scope else None))
        calls["n"] += 1
        if scope and scope.feature.id == "MODULE-001" and "page_details" in plan:
            return SimpleNamespace(failed=["assemble", "page_code:PAGE-001"], paused_because="",
                                   failed_because={"assemble": "NeedsWorkflow: needs a workflow that does not exist yet: unmark an item"})
        return SimpleNamespace(failed=[], paused_because="")
    prove = lambda svc, od, **kw: {"statements": 0, "passed": 0, "failing": [], "untried": [], "fixed": [], "results": []}

    def fix(od, ask):
        fixes.append(ask)
        return {"status": "resolved", "answer": "declared Mark Available and wrote the screen"}
    out = build(str(tmp_path), str(tmp_path / "app"), executor=object(), run=run, prove=prove, fix=fix)
    assert len(fixes) == 1 and "While building Catalogue, the build could not finish" in fixes[0]
    assert "assemble: NeedsWorkflow" in fixes[0] and "report_platform_fault" in fixes[0]
    mend = [p for p, f in plans if f == "MODULE-001" and "page_details" not in p]
    assert mend == [["page_code", "assemble"]], "the failed nodes run again, assembly last"
    assert out["features"][0]["failed_nodes"] == [], "and the feature records what still failed: nothing"


def test_the_whole_app_pass_fixes_what_a_later_feature_broke(tmp_path):
    """Crumb's customer landed on /orders once the Orders feature existed; the
    first feature's statement failed at the end with nobody sent to mend it."""
    _project(tmp_path)
    proofs: list = []
    fixes: list[str] = []
    def run(svc, executor, *, plan, scope=None, **kw):
        return SimpleNamespace(failed=[], paused_because="")

    def prove(svc, od, only=None, give_back=None, **kw):
        proofs.append((only, give_back))
        rows = []
        for sid in only or []:
            # EXP-001 holds in its own feature and fails once the whole app
            # is tried (a later feature moved the landing), until a fix lands.
            ok = not (sid == "EXP-001" and len(only or []) > 1 and not fixes)
            rows.append({"id": sid, "says": sid, "verdict": "passed" if ok else "failed",
                         "failures": [] if ok else ["Customer is on /orders, not /menu"]})
        return {"statements": len(rows), "passed": sum(r["verdict"] == "passed" for r in rows),
                "failing": [r["id"] for r in rows if r["verdict"] == "failed"], "untried": [], "fixed": [], "results": rows}

    def fix(od, ask):
        fixes.append(ask)
        return {"status": "resolved", "answer": "set the customer's landing to the menu"}
    out = build(str(tmp_path), str(tmp_path / "app"), executor=object(), run=run, prove=prove, fix=fix)
    assert sorted(proofs[-2][0]) == ["EXP-001", "EXP-013", "EXP-027"], "the whole-app pass tries every statement"
    assert proofs[-1][0] == ["EXP-001"] and proofs[-1][1] is False, "then what the fix changed is tried again"
    assert len(fixes) == 1 and "While building the whole application" in fixes[0] and "/orders, not /menu" in fixes[0]
    assert out["statements"]["fixed"] == ["EXP-001"] and out["statements"]["failing"] == []
