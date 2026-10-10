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
    "modules": [{"id": "MODULE-001", "name": "Catalogue", "pages": ["PAGE-001", "PAGE-002"], "requirements": ["REQ-001", "REQ-002"]},
                {"id": "MODULE-002", "name": "Cart & Checkout", "pages": ["PAGE-003"], "requirements": ["REQ-004"]},
                {"id": "MODULE-003", "name": "Accounts", "pages": ["PAGE-004"], "requirements": ["REQ-008"]}],
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
    "roles": [{"id": "ROLE-001", "name": "Customer"}],
    "pageLayouts": [{"page": pid, "composedBy": "deterministic", "tree": {}}
                    for pid in ("PAGE-001", "PAGE-002", "PAGE-003", "PAGE-004", "PAGE-005")],
    "workflows": [
        {"id": "FLOW-001", "name": "Add to Cart", "launchedFrom": ["PAGE-002"], "inputs": [], "steps": [{"id": "s1"}]},
        {"id": "FLOW-005", "name": "Update Profile", "launchedFrom": ["PAGE-004"], "inputs": [], "steps": [{"id": "s1"}]},
        {"id": "FLOW-009", "name": "Restock", "trigger": {"kind": "scheduled"}, "steps": [{"id": "s1"}],
         "inputs": [{"name": "product", "kind": "record", "entity": "ENTITY-003"}]},
    ],
    "expectations": [
        {"id": "EXP-001", "requirements": ["REQ-001"], "kind": "arrival", "steps": [{"act": "open", "page": "PAGE-002"}]},
        {"id": "EXP-013", "requirements": ["REQ-004"], "steps": [{"act": "do", "workflow": "FLOW-001"}]},
        {"id": "EXP-027", "requirements": [], "steps": [{"act": "sign_in"}, {"act": "open", "page": "PAGE-004"},
                                                        {"act": "do", "workflow": "FLOW-005"}]},
        {"id": "EXP-030", "requirements": ["REQ-002", "REQ-008"], "kind": "arrival", "steps": [{"act": "open", "page": "PAGE-002"}]},
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


def test_screens_in_no_module_are_built_one_record_at_a_time():
    """Ecommerce1 (forge-v3, 2026-10-10): seven approved modules naming no
    pages, 33 screens naming no module — one feature, "the rest of the
    application"."""
    doc = {**DOC, "modules": [{**m, "pages": []} for m in DOC["modules"]],
           "pages": [{k: v for k, v in p.items() if k != "module"} for p in DOC["pages"]]
           + [{"id": "PAGE-020", "route": "/about", "pattern": "static"}]}
    plan = F.features(doc)
    assert [f.id for f in plan] == ["MODULE-REST:ENTITY-003", "MODULE-REST:ENTITY-001", "MODULE-REST:ENTITY-004",
                                    "MODULE-REST:other"], "by record, dependence first (the cart after both)"
    assert plan[0].name == "the Product screens" and plan[0].pages == ["PAGE-001", "PAGE-002", "PAGE-005"]
    assert plan[3].name == "the other screens" and plan[3].pages == ["PAGE-020"]
    assert not any(f.id == "MODULE-REST" for f in plan)


def test_each_node_has_a_part_that_belongs_to_the_feature(monkeypatch):
    from services.blueprint import orchestrator
    plan = F.features(DOC)
    cat, acc, cart = plan
    pages = ["PAGE-001", "PAGE-002", "PAGE-003", "PAGE-004", "PAGE-005"]
    assert F.subjects_of(cat, "page_code", DOC, pages, first=True) == ["PAGE-001", "PAGE-002", "PAGE-005"]
    assert F.subjects_of(cat, "page_code", DOC, pages + ["PAGE-014"], first=True)[-1] == "PAGE-014", \
        "the sign-in screen is written with the first feature"
    assert "PAGE-014" not in F.subjects_of(cart, "page_code", DOC, pages + ["PAGE-014"], first=False)
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
    """LANDED ONCE, PROVEN FEATURE BY FEATURE (ecom v2, 2026-10-10: $15.76
    and 85 minutes for three of seven features when each was authored,
    landed and proven in turn). Everything that writes the definition is
    written once, in the opening; the landing is one pass; the features are
    the order of proving."""
    from services.blueprint.orchestrator import DAG
    once, per, last = build_nodes()
    for k in ("install", "decisions", "design_system", "page_details", "auth_pages", "ui_direction", "workflows",
              "workflow_steps", "business_rules", "analytics", "app_flows", "expectations", "content_fields", "apis"):
        assert k in once, f"{k} is written once, before the landing"
    assert per == ["page_layouts", "backend", "page_code", "frontend", "integration", "assemble"], \
        "the landing: the layouts, the code, the projections, the build"
    assert last == ["memory", "verification"]
    assert not set(once) & set(per) and not set(per) & set(last)
    for k in once:
        assert not any(d in per or d in last for d in DAG[k].depends_on), f"{k} runs once but depends on a later node"
    for k in per:
        assert not any(d in last for d in DAG[k].depends_on), f"{k} lands but depends on a last node"


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
    assert [r[1] for r in runs] == [None, None, None], "the opening, one landing, the last — nothing per feature"
    once, per, last = build_nodes()
    assert {"install", "decisions", "design_system", "page_details"} <= set(runs[0][0]) and not set(runs[0][0]) & set(per), \
        "the opening run is everything pending above the landing: the contracts and statements included"
    assert runs[1][0] == per and runs[-1][0] == last and per[-1] == "assemble"
    assert [p[0] for p in proofs[:4]] == [["EXP-001"], ["EXP-027"], ["EXP-013"], ["EXP-013"]], \
        "then each feature is proven in order of dependence; the cart's failing statement is tried again after the fix"
    assert proofs[0] == (["EXP-001"], True), "the first feature's own statements, with the authors' look"
    assert (["EXP-013"], True) in proofs and (["EXP-013"], False) in proofs, "then the fix turn's result is tried again"
    assert len(fixes) == 1 and "Cart & Checkout" in fixes[0] and "nothing was sent" in fixes[0]
    assert sorted(proofs[-1][0]) == ["EXP-001", "EXP-030"] and proofs[-1][1] is True, \
        "every statement once more at the end, with its authors' look"
    assert [f["feature"] for f in out["features"]] == ["MODULE-001", "MODULE-003", "MODULE-002"]
    cart = out["features"][2]
    assert cart["passed"] == 1 and cart["fixed"] == ["EXP-013"] and cart["failing"] == []
    assert any("Cart & Checkout: 1 of 1 statement of what must happen hold; fixed while building: EXP-013" in s for s in said)
    assert out["statements"]["passed"] == 2 and not out["stopped"], "the arrival and the uncovered one, at the end"
    from services.engineer.journal import Journal
    assert Journal(tmp_path).finished() == ["MODULE-001", "MODULE-003", "MODULE-002"]


def test_a_run_picks_up_where_the_last_one_stopped_and_stops_on_its_budget(tmp_path, monkeypatch):
    _project(tmp_path)
    from services.engineer.journal import Journal
    j = Journal(tmp_path)
    j.write("feature:done", feature="MODULE-001", pages=["PAGE-001", "PAGE-002", "PAGE-005"], statements=1)
    runs = []
    proofs: list = []

    def run(svc, executor, *, plan, scope=None, **kw):
        runs.append(scope.feature.id if scope else None)
        return SimpleNamespace(failed=[], paused_because="")

    def prove(svc, od, only=None, **kw):
        proofs.append(list(only or []))
        return {"statements": 0, "passed": 0, "failing": [], "untried": [], "fixed": [], "results": []}
    from services.engineer import build as B
    monkeypatch.setattr(B.Budget, "over", lambda self: len(proofs) >= 1)   # time runs out after one feature is proven
    out = build(str(tmp_path), str(tmp_path / "app"), executor=object(), run=run, prove=prove,
                fix=lambda od, ask: {}, budget_minutes=1)
    assert runs == [None, None], "what is pending above the landing runs again, and the landing; nothing per feature"
    assert proofs == [["EXP-027"]], "the finished feature is not proven again; the next one is"
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


def test_a_lock_nobody_has_pulsed_is_taken_over(tmp_path):
    """A killed resume left its lock with pid 63; in the container that pid
    is the next worker's (Ecommerce1, forge-v3, 2026-10-10)."""
    import os
    import time
    from services.engineer.journal import Busy, Journal, STALE_MINUTES
    j = Journal(tmp_path)
    j.acquire()                                    # our own live pid holds it
    old = time.time() - (STALE_MINUTES + 1) * 60
    os.utime(j.lock, (old, old))
    Journal(tmp_path).acquire()                    # alive, but nothing pulsed: taken over
    runs = tmp_path / ".forge" / "runs"
    runs.mkdir(parents=True)
    (runs / "20261010-010225-engineer.jsonl").write_text("{}\n")
    os.utime(j.lock, (old, old))
    with pytest.raises(Busy):
        Journal(tmp_path).acquire()               # an engineer's ledger pulsed just now


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
        if calls["n"] == 2 and "page_code" in plan:           # the landing
            return SimpleNamespace(failed=["assemble", "page_code:PAGE-001"], paused_because="",
                                   failed_because={"assemble": "NeedsWorkflow: needs a workflow that does not exist yet: unmark an item"})
        return SimpleNamespace(failed=[], paused_because="")
    prove = lambda svc, od, **kw: {"statements": 0, "passed": 0, "failing": [], "untried": [], "fixed": [], "results": []}

    def fix(od, ask):
        fixes.append(ask)
        return {"status": "resolved", "answer": "declared Mark Available and wrote the screen"}
    out = build(str(tmp_path), str(tmp_path / "app"), executor=object(), run=run, prove=prove, fix=fix)
    from services.engineer.journal import Journal
    assert len(fixes) == 1 and "While building the application, the build could not finish" in fixes[0]
    assert "assemble: NeedsWorkflow" in fixes[0] and "report_platform_fault" in fixes[0]
    mend = [p for p, f in plans if p == ["page_code", "assemble"]]
    assert len(mend) == 1, "the failed nodes run again, assembly last"
    assert not out["stopped"] and Journal(tmp_path).last("land:done")["failed"] == [], "and nothing still failed"


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
    assert sorted(proofs[-2][0]) == ["EXP-001", "EXP-030"], "the whole-app pass tries the arrivals and what no feature covered"
    assert proofs[-1][0] == ["EXP-001"] and proofs[-1][1] is False, "then what the fix changed is tried again"
    assert len(fixes) == 1 and "While building the whole application" in fixes[0] and "/orders, not /menu" in fixes[0]
    assert out["statements"]["fixed"] == ["EXP-001"] and out["statements"]["failing"] == []


def test_the_opening_says_when_everything_is_already_proven():
    from services.engineer.build import _opening
    plan = F.features(DOC)
    assert _opening(plan, [f.id for f in plan], "Crumb") == \
        "Every feature of Crumb is already proven (3); trying what is left once more and finishing it."
    assert "picking up from there: Accounts, Cart & Checkout" in _opening(plan, ["MODULE-001"], "Crumb")


def test_the_build_is_in_flight_from_its_first_feature_to_its_last(tmp_path, monkeypatch):
    """A deploy's cutover read Crumb's build as idle between two graph runs
    and restarted the backend under it (forge-v3, 2026-10-09 21:29)."""
    import json
    from services.run_registry import ledger_snapshot
    _project(tmp_path)
    seen: list = []

    def run(svc, executor, *, plan, scope=None, **kw):
        snap = ledger_snapshot(tmp_path, turns=False)
        seen.append(bool(snap and snap.get("active")))
        return SimpleNamespace(failed=[], paused_because="")
    prove = lambda svc, od, **kw: {"statements": 0, "passed": 0, "failing": [], "untried": [], "fixed": [], "results": []}
    build(str(tmp_path), str(tmp_path / "app"), executor=object(), run=run, prove=prove, fix=lambda od, ask: {})
    assert seen and all(seen), "in flight at every run of the build, not only inside one"
    ledgers = sorted((tmp_path / ".forge" / "runs").glob("*-engineer.jsonl"))
    assert len(ledgers) == 1
    events = [json.loads(l) for l in ledgers[0].read_text().splitlines()]
    kinds = [e["event"] for e in events]
    assert kinds[0] == "run:start" and kinds[1] == "plan" and kinds[-1] == "run:end"
    assert events[1]["nodes"] == ["opening"], "in flight from the opening run on"
    plans = [e for e in events if e["event"] == "plan"]
    assert plans[-1]["nodes"] == ["feature:MODULE-001", "feature:MODULE-003", "feature:MODULE-002"]
    assert [e["node"] for e in events if e["event"] == "node:done"] == ["opening", *plans[-1]["nodes"]]
    after = ledger_snapshot(tmp_path, turns=False)
    assert not (after and after.get("active")), "and idle once it has finished"


def test_the_engineer_finishes_the_model_first_and_stops_when_it_cannot(tmp_path):
    """Ecommerce1 (forge-v3, 2026-10-10): the tester pressed Build on an
    unfinished model; the engineer built on no entity fields, no page
    contracts and no roles, and 33 pages had nothing to be composed from."""
    _project(tmp_path)
    plans: list = []

    def run(svc, executor, *, plan, scope=None, **kw):
        plans.append(list(plan))
        if "entity_fields" in plan:
            return SimpleNamespace(failed=["entity_fields:ENTITY-001"], paused_because="",
                                   failed_because={"entity_fields:ENTITY-001": "InvalidEntityFields: Customer: `account: true` is already on Vendor"})
        return SimpleNamespace(failed=[], paused_because="")
    said: list[str] = []
    out = build(str(tmp_path), str(tmp_path / "app"), executor=object(), run=run,
                prove=lambda *a, **k: {}, fix=lambda *a: {}, emit=lambda k, d: said.append(d.get("text", "")),
                plan=["entity_fields", "page_contracts", "security", "install", "page_details", "assemble"])
    assert len(plans) == 2 and "assemble" not in plans[0] and plans[1] == ["entity_fields"], \
        "one opening run of what is pending above the features, the failed node once more, and nothing built after"
    assert [k for k in plans[0] if k != "install"] == ["entity_fields", "page_contracts", "security", "page_details"]
    assert out["stopped"].startswith("the application could not be defined") and out["features"] == []
    assert out["report"].paused_because == out["stopped"], "the entry reads it and does not hand over"
    assert any("I could not finish defining the application" in s and "already on Vendor" in s for s in said)


def test_the_model_is_finished_first_on_a_resumed_build_too(tmp_path):
    """Ecommerce1's resume (forge-v3, 2026-10-10 01:02) skipped the pending
    model nodes because a feature was already "done", and wrote 33 page
    contracts on entities with no fields and an app with no roles."""
    _project(tmp_path)
    from services.engineer.journal import Journal
    Journal(tmp_path).write("feature:done", feature="MODULE-001", pages=["PAGE-001", "PAGE-002", "PAGE-005"],
                            statements=1)
    plans: list = []

    def run(svc, executor, *, plan, scope=None, **kw):
        plans.append((list(plan), scope.feature.id if scope else None))
        return SimpleNamespace(failed=[], paused_because="")
    prove = lambda svc, od, **kw: {"statements": 0, "passed": 0, "failing": [], "untried": [], "fixed": [], "results": []}
    build(str(tmp_path), str(tmp_path / "app"), executor=object(), run=run, prove=prove, fix=lambda *a: {},
          plan=["entity_fields", "security", "install", "page_details", "page_code", "assemble", "memory"])
    assert plans[0][1] is None and {"entity_fields", "security"} <= set(plans[0][0]), "the model nodes run first"
    assert [f for _, f in plans] == [None, None, None] and "assemble" in plans[1][0], "then one landing, then the last"
    assert [r["feature"] for r in Journal(tmp_path).finished_rows()] == ["MODULE-001", "MODULE-003", "MODULE-002"]


def test_a_stale_journal_row_is_not_a_proven_feature(tmp_path):
    """Ecommerce1's first run wrote `feature:done MODULE-ALL, pages: []`
    and its resume counted it as proven (forge-v3, 2026-10-10)."""
    from services.engineer.build import proven_before
    cat = F.features(DOC)[0]
    row = {"feature": "MODULE-001", "pages": ["PAGE-001", "PAGE-002", "PAGE-005"], "statements": 1}
    assert proven_before(cat, [row], DOC)
    assert not proven_before(cat, [{**row, "pages": []}], DOC), "a row over different screens"
    assert not proven_before(cat, [{**row, "unbuilt": ["2 screens have no code and no layout"]}], DOC)
    assert not proven_before(cat, [{**row, "feature": "MODULE-ALL"}], DOC), "a feature that is not in the plan"
    bare = {**DOC, "pageLayouts": []}
    assert not proven_before(cat, [row], bare), "proven then, but its screens are not built now"


def test_a_feature_whose_screens_are_not_built_stops_the_build(tmp_path):
    """Ecommerce1 (forge-v3, 2026-10-10): "the application is built; it has
    no statements of its own to try" over 33 screens nothing composed, and
    the app was handed over at PREVIEW."""
    svc = _project(tmp_path)
    svc.doc["pageLayouts"] = [l for l in svc.doc["pageLayouts"] if l["page"] not in ("PAGE-001", "PAGE-002")]
    svc.save()
    runs: list = []
    proofs: list = []

    def run(s, executor, *, plan, scope=None, **kw):
        runs.append(scope.feature.id if scope else None)
        return SimpleNamespace(failed=[], paused_because="")

    def prove(s, od, only=None, **kw):
        proofs.append(only)
        return {"statements": 0, "passed": 0, "failing": [], "untried": [], "fixed": [], "results": []}
    said: list[str] = []
    out = build(str(tmp_path), str(tmp_path / "app"), executor=object(), run=run, prove=prove, fix=lambda *a: {},
                emit=lambda k, d: said.append(d.get("text", "")))
    assert runs == [None, None], "the opening and the landing; nothing more is built on an unbuilt feature"
    assert proofs == [], "and nothing is tried on it"
    assert out["stopped"].startswith("Catalogue is not built: 2 screens have no code and no layout: /, /products")
    assert out["report"].paused_because == out["stopped"]
    assert out["features"][0]["unbuilt"] and any("Catalogue is not built" in s for s in said)
    from services.engineer.journal import Journal
    assert Journal(tmp_path).finished_rows()[0]["unbuilt"]


def test_a_feature_is_not_proven_while_its_statements_are_unwritten():
    """Ecommerce1's Storefront (forge-v3, 2026-10-10 05:30): six screens built,
    "no statements of its own to try" — the pages named no requirements, so
    the writer was never asked about shopping and nothing was tried."""
    cat = F.features(DOC)[0]
    assert cat.requirements == ["REQ-001", "REQ-002"], "the module's requirements are the feature's"
    assert F.unwritten_statement_groups(DOC, cat) == []
    bare = {**DOC, "expectations": [e for e in DOC["expectations"] if e["id"] != "EXP-030"]}
    assert F.unwritten_statement_groups(bare, cat) == ["REQ-001"], "REQ-002 is covered by no statement"
    assert F.unbuilt_of(bare, cat) == ["the statements about Catalogue are not written (REQ-001)"]
    whole = F.features({**DOC, "modules": []})[0]
    assert whole.requirements == ["REQ-001", "REQ-002", "REQ-004", "REQ-008"], "the whole application's are every one"


def test_what_is_missing_at_the_end_is_the_engineers_to_finish(tmp_path):
    """"I have not handed the application over … Build again to finish it"
    was said to a tester about a process the build itself had left without
    steps (Ecommerce1, forge-v3, 2026-10-10 05:50)."""
    svc = _project(tmp_path)
    svc.doc["workflows"].append({"id": "FLOW-020", "name": "Abandon Inactive Carts", "trigger": {"kind": "scheduled"},
                                 "inputs": [], "steps": []})
    svc.save()
    plans: list = []
    fixes: list[str] = []

    def run(s, executor, *, plan, scope=None, **kw):
        plans.append((list(plan), getattr(getattr(scope, "feature", None), "id", None)))
        return SimpleNamespace(failed=[], paused_because="")

    def fix(od, ask):
        fixes.append(ask)
        for w in svc.doc["workflows"]:
            if w["id"] == "FLOW-020":
                w["steps"] = [{"id": "s1"}]
        svc.save()
        return {"status": "resolved", "answer": "wrote the clean-up's steps"}
    prove = lambda s, od, only=None, **kw: {"statements": len(only or []), "passed": len(only or []), "failing": [],
                                             "untried": [], "fixed": [], "results": [{"id": i, "verdict": "passed"} for i in only or []]}
    said: list[str] = []
    out = build(str(tmp_path), str(tmp_path / "app"), executor=object(), run=run, prove=prove, fix=fix,
                emit=lambda k, d: said.append(d.get("text", "")))
    assert "workflow_steps" in plans[0][0], "the process's steps are written in the opening, with every other"
    assert len(fixes) == 1 and "Abandon Inactive Carts" in fixes[0], "what is still missing at the end goes to one fix turn"
    assert plans[-1][0] == build_nodes()[1], "and what it wrote is landed and built once more"
    assert not out["stopped"] and out["statements"]["passed"] == 2, "then the whole application is tried and handed over"
    assert not any("Build again" in s for s in said)


def test_the_whole_application_is_checked_before_it_is_handed_over():
    from services.engineer.features import app_unbuilt
    assert app_unbuilt(DOC) == []
    assert app_unbuilt({**DOC, "roles": []}) == ["no roles are declared while 5 screens need a sign-in"]
    assert app_unbuilt({**DOC, "expectations": []}) == ["no statements of what must happen were written"]
    stepless = {**DOC, "workflows": [{**w, "steps": []} for w in DOC["workflows"]]}
    assert app_unbuilt(stepless) == ["3 processes have no steps: Add to Cart, Update Profile, Restock"]
    assert app_unbuilt({**DOC, "pageLayouts": [], "pageCode": [{"page": "PAGE-001"}]})[0] == \
        "4 screens have no code and no layout: /products, /cart, /account, /products/compare"


def test_a_second_login_entity_sends_the_declaration_back_to_its_author(tmp_path):
    svc = _project(tmp_path)
    svc.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Customer", "table": "customers", "account": True, "fields": []},
                                    {"id": "ENTITY-002", "name": "Vendor", "table": "vendors", "account": True, "fields": []}]}
    svc.save()
    from services.engineer.build import first_nodes
    nodes, scope = first_nodes(["entity_fields", "page_contracts", "security", "install"], svc.doc)
    assert "data_model" in nodes and nodes.index("data_model") < nodes.index("entity_fields"), "the declarer goes first"
    assert "Customer and Vendor are each marked `account: true`" in scope.brief("data_model", "")
    assert scope.brief("entity_fields", "ENTITY-001") == ""
    nodes, scope = first_nodes(["entity_fields"], {"data": {"entities": [{"id": "E1", "name": "Customer", "account": True}]}})
    assert nodes == ["entity_fields"] and scope is None


def test_the_statements_are_written_after_the_landing_not_before_it(svc):
    """Ecom L1 (2026-10-11): the statements writer stood in front of every
    page and retried at its output cap for twenty minutes; nothing was laid
    out meanwhile."""
    from services.engineer.build import AFTER_LANDING, build_nodes, first_nodes
    once, per, last = build_nodes()
    assert "expectations" in once and "expectations" not in per
    nodes, _ = first_nodes(["workflow_steps", "expectations", "page_code", "memory"], svc.doc)
    assert "workflow_steps" in nodes and "expectations" not in nodes
    assert AFTER_LANDING == ("expectations",)
