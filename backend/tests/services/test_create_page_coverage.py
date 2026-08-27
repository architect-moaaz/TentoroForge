"""Every '/{entity}/new' a page links to must exist, else the route handler 404s.
The page agent emits 'New X' buttons for all entities but the planner under-declares
the create pages — this pass fills the gap deterministically."""
import json
from pathlib import Path
from services.create_page_coverage import ensure_create_pages, build_create_page, _input_type


def test_input_type_never_returns_date():
    # Input.type enum has no "date"; date-ish columns must fall back to text.
    for col in ("createdAt", "dateOfBirth", "paidAt", "gdprConsentAt"):
        assert _input_type(col) in ("text", "email", "number", "tel", "url", "password")
    assert _input_type("email") == "email"
    assert _input_type("phone") == "tel"
    assert _input_type("total") == "number"


def test_build_create_page_shape():
    page = build_create_page("/owners/new", "Owner", ["firstName", "email"], "CreateOwner")
    assert page["route"] == "/owners/new" and page["schemaVersion"] == "2"
    # has a Form bound to the Create workflow + a field per column
    s = json.dumps(page)
    assert '"CreateOwner"' in s and '"firstName"' in s and '"email"' in s
    assert '"Form"' in s


def _app(tmp_path):
    sch = tmp_path / "src" / "schemas"
    (sch / "owners").mkdir(parents=True)
    # a list page that links to /owners/new but no owners/new.json exists
    (sch / "owners.json").write_text(json.dumps({
        "schemaVersion": "2", "route": "/owners",
        "root": {"type": "Button", "props": {"onClick": {"action": "navigate", "to": "/owners/new"}}},
    }))
    (tmp_path / "workflows").mkdir()
    (tmp_path / "workflows" / "CreateOwner.json").write_text("{}")
    return tmp_path


def test_generates_missing_create_page(tmp_path):
    app = _app(tmp_path)
    reg = {"entities": {"Owner": {"fields": {"firstName": {}, "email": {}, "createdAt": {}}}}}
    made = ensure_create_pages(app, reg)
    assert "/owners/new" in made
    out = json.loads((app / "src" / "schemas" / "owners" / "new.json").read_text())
    assert out["route"] == "/owners/new"
    # idempotent: a second run creates nothing
    assert ensure_create_pages(app, reg) == []


# --- friendly-route bridging + husk upgrade (Category-B follow-up) ---
from services.create_page_coverage import _segment_entity_map, _page_has_fields
from pathlib import Path as _P


def test_segment_map_bridges_friendly_route_via_datasource(tmp_path):
    """A list page at /bookings backed by dataSource entity ClassBooking must let
    segment 'bookings' resolve to 'ClassBooking' — the entity slug alone can't."""
    sch = tmp_path / "src" / "schemas"
    sch.mkdir(parents=True)
    (sch / "bookings.json").write_text(json.dumps({
        "route": "/bookings",
        "dataSources": [{"name": "bookings", "entity": "ClassBooking", "op": "list"}],
        "root": {"type": "Stack", "children": []},
    }))
    reg = {"entities": {"ClassBooking": {"fields": {"id": {}}}}}
    seg_map = _segment_entity_map(sch.parent.parent, reg)
    assert seg_map.get("bookings") == "ClassBooking"
    # slug-based entries still present
    assert seg_map.get("classbooking") == "ClassBooking"


def test_page_has_fields_detects_husk():
    husk = {"root": {"type": "Form", "props": {"workflow": "CreateX"}, "children": [
        {"type": "Heading", "props": {"content": "New X"}},
        {"type": "Stack", "children": []},
    ]}}
    filled = {"root": {"type": "Form", "children": [
        {"type": "Input", "props": {"name": "title"}},
    ]}}
    assert _page_has_fields(husk) is False
    assert _page_has_fields(filled) is True


import pytest
from services import create_page_coverage as _cpc


def _husk(route, workflow):
    return {"route": route, "root": {"type": "Form", "props": {"workflow": workflow},
            "children": [{"type": "Heading", "props": {"content": "New"}},
                         {"type": "Stack", "children": []}]}}


@pytest.mark.asyncio
async def test_llm_coverage_upgrades_husks_concurrently(tmp_path, monkeypatch):
    """Two husks (friendly routes resolved via dataSource) are BOTH upgraded to real
    forms, and the per-route agent calls run concurrently (not one-after-another).
    (Opt out of deterministic-first so the LLM path under test actually runs.)"""
    import asyncio
    monkeypatch.setenv("FORGE_DETERMINISTIC_CRUD", "off")
    sch = tmp_path / "src" / "schemas"
    for seg, ent in (("bookings", "ClassBooking"), ("plans", "MembershipPlan")):
        (sch / seg).mkdir(parents=True)
        (sch / f"{seg}.json").write_text(json.dumps({
            "route": f"/{seg}",
            "dataSources": [{"name": seg, "entity": ent, "op": "list"}],
            "root": {"type": "Button", "props": {"label": "New", "navigate": f"/{seg}/new"}},
        }))
        (sch / seg / "new.json").write_text(json.dumps(_husk(f"/{seg}/new", f"Create{ent}")))

    inflight = {"cur": 0, "max": 0}
    async def _fake_agent(out, plan, page, domain_context=None):
        inflight["cur"] += 1
        inflight["max"] = max(inflight["max"], inflight["cur"])
        await asyncio.sleep(0.05)                       # hold the slot so overlap is observable
        seg = page["route"].strip("/").split("/")[0]
        (_P(out) / "src" / "schemas" / seg / "new.json").write_text(json.dumps(
            {"route": page["route"], "root": {"type": "Form", "children": [
                {"type": "Input", "props": {"name": "title"}}]}}))
        inflight["cur"] -= 1
    monkeypatch.setattr("agents.page_schema_agent.run_page_schema_agent", _fake_agent)
    async def _noop(*a, **k):
        return None
    monkeypatch.setattr("services.schema_pipeline._apply_plan_binding", _noop)

    reg = {"entities": {"ClassBooking": {"fields": {"title": {}}},
                        "MembershipPlan": {"fields": {"title": {}}}}}
    made = await _cpc.ensure_create_pages_llm(tmp_path, reg, {"pages": []})
    assert set(made) == {"/bookings/new", "/plans/new"}
    assert inflight["max"] >= 2                          # the two agent calls overlapped
    for seg in ("bookings", "plans"):
        assert _cpc._page_has_fields(json.loads((sch / seg / "new.json").read_text())) is True


@pytest.mark.asyncio
async def test_deterministic_first_builds_create_form_without_llm(tmp_path, monkeypatch):
    """Default path: when the entity's columns are known, the /new form is built
    deterministically (0 LLM calls) instead of a multi-turn agent — this is what
    turned e.g. inbox/new from ~2-3 min into ~0s. The agent must NOT be called."""
    sch = tmp_path / "src" / "schemas"
    (sch / "inbox").mkdir(parents=True)
    (sch / "inbox.json").write_text(json.dumps({
        "route": "/inbox",
        "dataSources": [{"name": "inbox", "entity": "Notification", "op": "list"}],
        "root": {"type": "Button", "props": {"label": "New", "navigate": "/inbox/new"}},
    }))

    called = {"n": 0}
    async def _agent_should_not_run(*a, **k):
        called["n"] += 1
    monkeypatch.setattr("agents.page_schema_agent.run_page_schema_agent", _agent_should_not_run)

    reg = {"entities": {"Notification": {"fields": {"title": {}, "body": {}, "recipientId": {}}}}}
    made = await _cpc.ensure_create_pages_llm(tmp_path, reg, {"pages": []})
    assert "/inbox/new" in made
    assert called["n"] == 0                                        # no LLM turn
    built = json.loads((sch / "inbox" / "new.json").read_text())
    assert _cpc._page_has_fields(built) is True
    s = json.dumps(built)
    assert '"title"' in s and '"body"' in s and '"CreateNotification"' in s


@pytest.mark.asyncio
async def test_llm_failure_leaves_husk_for_form_scaffold(tmp_path, monkeypatch):
    """If the agent fails, an existing husk is NOT overwritten by the plain-Input
    deterministic form — it's left for form_scaffold (which adds FK Selects).
    (LLM path only; deterministic-first is opted out.)"""
    monkeypatch.setenv("FORGE_DETERMINISTIC_CRUD", "off")
    sch = tmp_path / "src" / "schemas"
    (sch / "bookings").mkdir(parents=True)
    (sch / "bookings.json").write_text(json.dumps({
        "route": "/bookings",
        "dataSources": [{"name": "bookings", "entity": "ClassBooking", "op": "list"}],
        "root": {"type": "Button", "props": {"label": "New", "navigate": "/bookings/new"}},
    }))
    husk = _husk("/bookings/new", "CreateClassBooking")
    (sch / "bookings" / "new.json").write_text(json.dumps(husk))

    async def _boom(*a, **k):
        raise RuntimeError("agent down")
    monkeypatch.setattr("agents.page_schema_agent.run_page_schema_agent", _boom)
    monkeypatch.setattr("services.schema_pipeline._apply_plan_binding", _boom)

    reg = {"entities": {"ClassBooking": {"fields": {"memberId": {}}}}}
    made = await _cpc.ensure_create_pages_llm(tmp_path, reg, {"pages": []})
    assert made == []                                              # husk not counted as done
    assert json.loads((sch / "bookings" / "new.json").read_text()) == husk  # untouched


# --- B-5a: a /{slug}/new page bound to the WRONG entity is rebuilt from the ROUTE entity ---

_B5A_REG = {"entities": {
    "InterviewFeedback": {"slug": "interview-feedback", "fields": {
        "id": {"primaryKey": True}, "applicationId": {}, "rating": {"type": "integer"},
        "strengths": {"type": "text"}, "recommendation": {}, "createdAt": {},
    }},
    "Assessment": {"slug": "assessment", "fields": {
        "id": {"primaryKey": True}, "assessmentType": {}, "scheduledAt": {"type": "timestamp"},
        "location": {}, "status": {}, "createdAt": {},
    }},
    "Candidate": {"slug": "candidate", "fields": {
        "id": {"primaryKey": True}, "fullName": {}, "email": {}, "createdAt": {},
    }},
}}


def _wrong_entity_page(route, workflow, field_names):
    """A create page that HAS fields but is bound to the wrong entity's Create<X>
    workflow — the exact husk B-5a must detect and rebuild."""
    return {"schemaVersion": "2", "route": route, "root": {"type": "Stack", "children": [
        {"type": "Form", "props": {"workflow": workflow}, "children": [
            {"type": "Input", "props": {"name": n}} for n in field_names]}]}}


def _form_workflow_and_fields(page):
    wfs, fields = [], []
    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "Form":
                wf = (n.get("props") or {}).get("workflow")
                if wf:
                    wfs.append(wf)
            if n.get("type") in _cpc._FIELD_TYPES and (n.get("props") or {}).get("name"):
                fields.append(n["props"]["name"])
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)
    walk(page)
    return wfs, fields


@pytest.mark.asyncio
async def test_wrong_entity_create_page_is_rebuilt_from_route_entity(tmp_path):
    """`/interview-feedback/new` authored with `CreateAssessment` + Assessment fields is
    a husk for the InterviewFeedback route — coverage REBUILDS it deterministically from
    the route entity (workflow `CreateInterviewFeedback`, InterviewFeedback columns). A
    correctly-bound `/candidates/new` (`CreateCandidate`) is left byte-for-byte."""
    sch = tmp_path / "src" / "schemas"
    (sch / "interview-feedback").mkdir(parents=True)
    (sch / "candidates").mkdir(parents=True)
    # list pages so the /new routes are discoverable
    (sch / "interview-feedback.json").write_text(json.dumps({
        "route": "/interview-feedback",
        "root": {"type": "Button", "props": {"navigate": "/interview-feedback/new"}}}))
    (sch / "candidates.json").write_text(json.dumps({
        "route": "/candidates",
        "root": {"type": "Button", "props": {"navigate": "/candidates/new"}}}))
    # WRONG-entity create page (bound to CreateAssessment / Assessment fields)
    (sch / "interview-feedback" / "new.json").write_text(json.dumps(_wrong_entity_page(
        "/interview-feedback/new", "CreateAssessment",
        ["applicationId", "candidateId", "assessmentType", "scheduledAt", "location", "status"])))
    # correctly-bound create page (CreateCandidate)
    cand = _wrong_entity_page("/candidates/new", "CreateCandidate", ["fullName", "email"])
    (sch / "candidates" / "new.json").write_text(json.dumps(cand, indent=2))
    cand_before = (sch / "candidates" / "new.json").read_text()

    made = await _cpc.ensure_create_pages_llm(tmp_path, _B5A_REG, {"pages": []})

    assert "/interview-feedback/new" in made
    assert "/candidates/new" not in made
    rebuilt = json.loads((sch / "interview-feedback" / "new.json").read_text())
    wfs, fields = _form_workflow_and_fields(rebuilt)
    assert wfs == ["CreateInterviewFeedback"]
    assert "rating" in fields and "recommendation" in fields          # InterviewFeedback cols
    assert "assessmentType" not in fields and "scheduledAt" not in fields  # Assessment cols gone
    # correctly-bound page untouched
    assert (sch / "candidates" / "new.json").read_text() == cand_before
