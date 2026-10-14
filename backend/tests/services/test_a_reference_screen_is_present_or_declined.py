"""Every item of the domain reference is answered by name or declined with a
reason; an item that is neither is a finding the observer sends to the
section's author — judged edge by edge, so a screen is judged at the model
gate while the processes are not yet planned."""
from __future__ import annotations

from services.blueprint import reference_coverage as rc
from services.blueprint.observer import ready_edges
from services.blueprint.verification import CHECKS, EDGE_SECTIONS, EDGES, SECTION_OWNER, verify

REF = {"domain": "Retail", "subdomain": "Multi-vendor marketplace",
       "screens": [{"name": "Order book", "purpose": "every order, by status", "forRoles": ["Vendor"]},
                   {"name": "Payout statement", "purpose": "what each vendor is owed", "forRoles": ["Vendor", "Admin"]},
                   {"name": "Dispute centre", "purpose": "buyer and vendor disagree"}],
       "records": [{"name": "Invoice"}, {"name": "Return"}],
       "processes": [{"name": "Refund an order", "roles": ["Admin"]}],
       "rules": [{"name": "Stock cap", "statement": "no more than in stock", "refusedCase": "999 of 3"}],
       "integrations": [{"name": "Payments", "providers": ["Stripe"]}]}


def _doc(**over):
    doc = {"domainReference": REF,
           "pages": [{"id": "PAGE-001", "name": "Orders", "route": "/orders", "reference": "Order book"},
                     {"id": "PAGE-002", "name": "Payout Statements", "route": "/payouts"}],
           "data": {"entities": [{"id": "ENTITY-001", "name": "Invoice", "table": "invoices"}]},
           "workflows": [{"id": "FLOW-001", "name": "Refund order", "trigger": {"kind": "manual"}}],
           "businessRules": [], "integrations": []}
    doc.update(over)
    return doc


def test_an_item_is_answered_by_exact_reference_or_by_its_own_name():
    items = {(it.kind, it.name): it for it in rc.coverage(_doc())}
    assert items[("screen", "Order book")].covered_by == "PAGE-001"          # by `reference`
    assert items[("screen", "Payout statement")].covered_by == "PAGE-002"    # by name, plural and case aside
    assert items[("screen", "Dispute centre")].open
    assert items[("record", "Invoice")].covered_by == "ENTITY-001" and items[("record", "Return")].open
    assert items[("process", "Refund an order")].open                        # 'Refund order' is not the same name
    assert items[("rule", "Stock cap")].open and items[("integration", "Payments")].open


def test_what_is_neither_answered_nor_declined_is_a_finding_for_the_sections_author():
    found = {f.edge: [] for f in ()}
    for f in verify(_doc(), edges=rc.REFERENCE_EDGES).findings:
        found.setdefault(f.edge, []).append(f)
    pages = found["Reference↔Page"]
    assert len(pages) == 1 and "'Dispute centre'" in pages[0].detail and pages[0].section == "pages"
    assert pages[0].responsible_agent == "page_design" and pages[0].artifact_id is None
    assert "declined with a reason" in pages[0].detail
    assert [f.detail.split("'")[1] for f in found["Reference↔Record"]] == ["Return"]
    assert sorted(f.detail.split("'")[1] for f in found["Reference↔Process"]) == ["Refund an order", "Stock cap"]
    assert {f.responsible_agent for f in found["Reference↔Process"]} == {"workflow", "business_rules"}
    assert [f.responsible_agent for f in found["Reference↔Integration"]] == ["integration"]


def test_a_decline_with_a_reason_silences_the_item_and_is_counted_apart():
    doc = _doc()
    doc["domainReference"] = {**REF, "declined": [
        {"kind": "screen", "name": "dispute centre", "reason": "disputes go by email in v1", "by": "owner"},
        {"kind": "record", "name": "Return", "reason": "no returns in v1", "by": "data_model"}]}
    assert not [f for f in verify(doc, edges=("Reference↔Page", "Reference↔Record")).findings]
    s = rc.summary(doc)
    assert (s["total"], s["green"]) == (6, 3)                      # 8 items, 2 declined, 3 answered
    assert {d["item"] for d in s["declined"]} == {"Dispute centre", "Return"}
    assert {r["item"] for r in s["red"]} == {"Refund an order", "Stock cap", "Payments"}


def test_an_application_without_a_reference_has_nothing_to_answer():
    assert verify({"pages": [{"id": "PAGE-001", "name": "Home"}]}, edges=rc.REFERENCE_EDGES).findings == []
    assert rc.summary({}) == {"total": 0, "green": 0, "red": [], "declined": []}


def test_the_edges_are_declared_like_every_other_and_wait_for_their_side():
    assert set(EDGE_SECTIONS) == set(CHECKS) == set(EDGES)
    for edge in rc.REFERENCE_EDGES:
        assert all(s in SECTION_OWNER for s in EDGE_SECTIONS[edge]), edge
    ready = ready_edges(_doc(), pending={"pages"}, planned={"pages", "domainReference", "data.entities"})
    assert "Reference↔Page" not in ready and "Reference↔Record" in ready


def test_declines_are_recorded_once_by_kind_and_name():
    class _Svc:
        doc = _doc()
    added = rc.record_declines(_Svc, [{"kind": "screen", "name": "Dispute centre", "reason": "later"},
                                      {"kind": "screen", "name": "dispute-centre", "reason": "twice"},
                                      {"kind": "screen", "name": "No reason"},
                                      {"kind": "widget", "name": "x", "reason": "no such kind"}], by="page_design")
    assert added == [{"kind": "screen", "name": "Dispute centre", "reason": "later", "by": "page_design"}]
    assert _Svc.doc["domainReference"]["declined"] == added
