from services.app_design_guardrail import ensure_entity_reachability


def _plan(entities, relations, pages):
    return {
        "entities": [{"name": n, "fields": []} for n in entities],
        "relations": relations,
        "pages": pages,
    }


def test_orphaned_entity_is_promoted_with_a_page():
    # AuditLog has no page AND no relation -> its data is unreachable. The guard
    # must promote it with a list page (never silently drop an entity).
    plan = _plan(
        entities=["Invoice", "AuditLog"],
        relations=[],
        pages=[{"route": "/invoices", "name": "InvoiceList", "entity": "Invoice", "archetype": "list"}],
    )
    out, report = ensure_entity_reachability(plan)
    paged = {p.get("entity") for p in out["pages"]}
    assert "AuditLog" in paged
    assert "AuditLog" in report["promoted"]
    promoted_page = next(p for p in out["pages"] if p.get("entity") == "AuditLog")
    assert promoted_page["archetype"] == "list"
    assert promoted_page["route"] == "/audit_log"


def test_supporting_entity_reachable_via_relation_is_not_promoted():
    # Category has no page but is referenced by Product -> reachable inline (dropdown
    # in Product's form). It must NOT be promoted; it's classified supporting.
    plan = _plan(
        entities=["Product", "Category"],
        relations=[{"from": "Product", "to": "Category", "type": "many-to-one", "foreignKey": "category_id"}],
        pages=[{"route": "/products", "name": "ProductList", "entity": "Product", "archetype": "list"}],
    )
    out, report = ensure_entity_reachability(plan)
    paged = {p.get("entity") for p in out["pages"]}
    assert "Category" not in paged
    assert "Category" in report["supporting_inline"]
    assert "Category" not in report["promoted"]


def test_primary_entity_with_pages_classified_primary_and_untouched():
    plan = _plan(
        entities=["Order"],
        relations=[],
        pages=[{"route": "/orders", "name": "OrderList", "entity": "Order", "archetype": "list"}],
    )
    before = len(plan["pages"])
    out, report = ensure_entity_reachability(plan)
    assert "Order" in report["primary"]
    assert report["promoted"] == []
    assert len(out["pages"]) == before  # no pages added
