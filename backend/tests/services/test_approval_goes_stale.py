"""QA C-04: an approval goes STALE after a material definition change, and
re-approving restores it — so a build cannot ship against an approval that no
longer describes the app."""
from services.blueprint import approval as A


class _FakeSvc:
    def __init__(self, doc): self.doc = doc
    def save(self): pass


def _doc():
    return {
        "application": {"name": "Offer Tracker", "domain": "sales"},
        "product": {"objectives": ["track offers"]},
        "data": {"entities": [{"id": "ENTITY-001", "name": "Offer"}]},
        "pages": [{"id": "PAGE-001", "name": "Offers", "route": "/offers"}],
        "workflows": [{"id": "FLOW-001", "name": "Create Offer"}],
        "version": 1,
    }


def test_stale_after_a_material_change_then_re_approve_restores():
    doc = _doc(); svc = _FakeSvc(doc)
    A.record(svc, "build")                       # approve as built
    assert A.state_of(doc, "build") == "approved"
    assert A.is_approved(doc, "build")

    # MATERIAL change: a new entity (part of the product surface)
    doc["data"]["entities"].append({"id": "ENTITY-002", "name": "Discount"})
    assert A.state_of(doc, "build") == "stale"
    assert not A.is_approved(doc, "build")

    # re-approve against the changed doc
    A.record(svc, "build")
    assert A.state_of(doc, "build") == "approved"


def test_adding_only_a_field_does_not_invalidate_approval():
    """A field-add (F-01) is an implementation detail, not a product-surface
    change, so it must NOT make a prior approval stale."""
    doc = _doc(); svc = _FakeSvc(doc)
    A.record(svc, "build")
    doc["data"]["entities"][0].setdefault("fields", []).append(
        {"name": "discountPercent", "type": "decimal"})
    assert A.state_of(doc, "build") == "approved"
