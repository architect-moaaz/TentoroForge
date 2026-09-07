"""Tests for phase_gates.check_contract_completeness.

Focus: the contract gate must DEFER to the planner's own pages (fidelity), not
demand a CRUD list page for every entity (completeness). Auth-managed entities,
friendly-route entities, and nested sub-resources are legitimately page-less and
must NOT be flagged. Only a genuine DROP (planner declared a page for an entity
but app-model.json lacks it) is a real defect.
"""
import json

from services.contract_generator import generate_contracts
from services.phase_gates import check_contract_completeness


def _service_desk_plan() -> dict:
    """IT service-desk plan where the planner deliberately omits pages:
    - User          → auth-managed, no page
    - Ticket        → /tickets list page
    - KnowledgeArticle → friendly /knowledge route (not /knowledge-articles)
    - Comment       → nested sub-resource, no top-level page
    - TicketHistory → nested /tickets/[id]/history, no top-level page
    """
    return {
        "name": "IT Service Desk",
        "data_models": [
            {"name": "User", "fields": [
                {"name": "id", "type": "uuid"},
                {"name": "email", "type": "varchar"},
                {"name": "name", "type": "varchar"},
            ]},
            {"name": "Ticket", "fields": [
                {"name": "id", "type": "uuid"},
                {"name": "title", "type": "varchar"},
                {"name": "status", "type": "varchar"},
            ]},
            {"name": "KnowledgeArticle", "fields": [
                {"name": "id", "type": "uuid"},
                {"name": "title", "type": "varchar"},
                {"name": "body", "type": "text"},
            ]},
            {"name": "Comment", "fields": [
                {"name": "id", "type": "uuid"},
                {"name": "ticketId", "type": "uuid"},
                {"name": "body", "type": "text"},
            ]},
            {"name": "TicketHistory", "fields": [
                {"name": "id", "type": "uuid"},
                {"name": "ticketId", "type": "uuid"},
                {"name": "action", "type": "varchar"},
            ]},
        ],
        "pages": [
            {"route": "/tickets", "name": "TicketList", "entity": "Ticket", "archetype": "list"},
            {"route": "/knowledge", "name": "KnowledgeList", "entity": "KnowledgeArticle", "archetype": "list"},
            {"route": "/tickets/[id]/history", "name": "TicketHistoryView", "entity": "TicketHistory", "archetype": "detail"},
        ],
    }


def test_gate_passes_when_planner_omits_pages(tmp_path):
    """When the planner legitimately gives some entities no top-level list page
    (auth entity, friendly route, nested sub-resource), the gate must PASS and
    emit no 'missing list page' issues. FAILS before the fidelity relaxation
    (old gate flagged User, KnowledgeArticle, Comment, TicketHistory)."""
    plan = _service_desk_plan()
    res = generate_contracts(str(tmp_path), plan)
    assert not res["errors"], res["errors"]

    gate = check_contract_completeness(str(tmp_path), plan)
    missing_pages = [m for m in gate["missing"] if "missing list page" in m]
    assert not missing_pages, f"unexpected list-page flags: {missing_pages}"
    assert gate["passed"], f"gate should pass, got: {gate['missing']}"


def test_gate_flags_genuine_dropped_page(tmp_path):
    """When the planner DID declare a list page for an entity but app-model.json
    lacks it (a genuine drop), the gate must still flag that entity."""
    plan = {
        "name": "Orders",
        "data_models": [
            {"name": "User", "fields": [
                {"name": "id", "type": "uuid"},
                {"name": "email", "type": "varchar"},
            ]},
            {"name": "Order", "fields": [
                {"name": "id", "type": "uuid"},
                {"name": "total", "type": "numeric"},
                {"name": "status", "type": "varchar"},
            ]},
        ],
        "pages": [
            {"route": "/orders", "name": "OrderList", "entity": "Order", "archetype": "list"},
        ],
    }
    res = generate_contracts(str(tmp_path), plan)
    assert not res["errors"], res["errors"]

    # Hand-edit app-model.json to REMOVE the declared /orders page (simulate drop).
    app_model = tmp_path / "src" / "contracts" / "app-model.json"
    data = json.loads(app_model.read_text(encoding="utf-8"))
    data["pages"] = [p for p in data["pages"] if p.get("route") != "/orders"]
    app_model.write_text(json.dumps(data, indent=2), encoding="utf-8")

    gate = check_contract_completeness(str(tmp_path), plan)
    assert not gate["passed"], "gate should fail on a genuine dropped page"
    order_flags = [m for m in gate["missing"] if "missing list page" in m and "Order" in m]
    assert order_flags, f"expected Order flagged as missing list page, got: {gate['missing']}"
