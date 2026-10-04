"""Task 5 re-test (SnapIT): real changes are never swallowed as 'the same',
a big shift is wired into the turn and swaps only what people read, and a
requirement is never sent to the wrong implementer."""
import json
import sys

import pytest

from services.blueprint.service import BlueprintService
from services.smith import big_shift, definition_change as dc, requirement_reach as rr


# --- 5.1 -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("a,b", [
    ("Allow at most 5 items per order.", "Allow at most 8 items per order."),
    ("Refunds are allowed within 30 days.", "Refunds are allowed within 90 days."),
    ("Orders are allowed for all customers.", "Orders are not allowed for customers."),
    ("Users can export data.", "Users can not export data."),
    ("Scraping takes place from fashion stores only.", "Scraping takes place from fashion stores."),
    ("Scrape only fashion stores", "Scrape no fashion stores"),
    ("Only admins can delete orders.", "Only managers can delete orders."),
])
def test_a_real_change_is_never_the_same_meaning(a, b):
    assert not rr.same_meaning(a, b)


def test_a_restatement_is_still_the_same():
    assert rr.same_meaning("The web scraping should only take place from fashion stores.",
                           "Web scraping should take place from fashion stores only")


# --- 5.5 -----------------------------------------------------------------------------------------

@pytest.mark.parametrize("ask,cur", [("make it dubai-centric", "AED"), ("Make it UAE-centric", "AED"), ("make it dubai", "AED"),
                                      ("go dubai", "AED"), ("ksa centric", "SAR"), ("make it Abu Dhabi focused", "AED"),
                                      ("let's go Qatar first", "QAR"), ("build this for Dubai", "AED")])
def test_a_market_shift_is_recognised_however_it_is_spelled(ask, cur):
    s = big_shift.detect(ask)
    assert s and s["kind"] == "market" and s["currency"] == cur


def test_ordinary_asks_are_not_shifts():
    for ask in ("make the header blue", "the web scraping should take place from fashion stores only", "add a Dubai store"):
        assert big_shift.detect(ask) is None, ask


# --- 5.3 / 5.4 / 5.7 -------------------------------------------------------------------------------

@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="SnapIT", domain="retail")
    s.doc["requirements"] = [
        {"id": "REQ-040", "description": "Show all prices in INR (₹), e.g. ₹50,000 or 50 rupees.", "status": "APPROVED",
         "evidence": [{"message": "p", "type": "conversation"}]}]
    s.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Product", "table": "products", "fields": [
        {"name": "id", "type": "uuid", "primaryKey": True},
        {"name": "price_INR", "type": "decimal", "description": "Price in INR"},
        {"name": "MRP_INR", "type": "decimal"}, {"name": "priceINR", "type": "decimal"},
        {"name": "currency", "type": "string"}]}], "relationships": []}
    s.upsert("businessRules", {"name": "Premium", "statement": "Premium when price is above ₹10,000.",
                               "kind": "condition_action", "entity": "ENTITY-001", "when": "currency == 'INR' and price_INR > 10000",
                               "appliesTo": ["ENTITY-001"], "then": [{"type": "show_error", "field": "price_INR", "message": "Over INR 10,000"}]},
             natural_key="Premium")
    s.save()
    (tmp_path / "contracts").mkdir(exist_ok=True)
    (tmp_path / "contracts/seed-plan.json").write_text(json.dumps(
        {"sample_data": {"Product": [{"name": "Kurta", "price_INR": 499, "currency": "INR", "note": "Rs. 499 only"}]}}))
    return s


def test_only_what_people_read_changes_and_identifiers_stay(svc, tmp_path):
    out = big_shift.apply_currency(svc, "INR", "AED", output_dir=tmp_path)
    blob = json.dumps(svc.doc, ensure_ascii=False)
    assert "Show all prices in AED, e.g. AED 50,000 or 50 dirhams." in blob          # no 'AED (AED)', spaced, rupees swapped
    assert "above AED 10,000" in blob and "Over AED 10,000" in blob
    for ident in ('"price_INR"', '"MRP_INR"', '"priceINR"'):
        assert ident in blob, ident                                                    # a field's name is an identifier
    assert "currency == 'INR' and price_INR > 10000" in blob                          # an expression is not copy
    seed = json.loads((tmp_path / "contracts/seed-plan.json").read_text())["sample_data"]["Product"][0]
    assert seed["price_INR"] == 499 and seed["currency"] == "INR" and seed["note"] == "AED 499 only"
    assert out["kept_values"] >= 2                                                      # flagged, not silently desynced
    assert big_shift.apply_currency(svc, "INR", "AED", output_dir=tmp_path)["applied"] is False   # idempotent


def test_an_invalid_result_leaves_the_blueprint_exactly_as_it_was(svc, tmp_path, monkeypatch):
    before = json.dumps(svc.doc, sort_keys=True)

    def refuse():
        raise ValueError("invalid")
    monkeypatch.setattr(svc, "validate", refuse)
    with pytest.raises(ValueError):
        big_shift.apply_currency(svc, "INR", "AED", output_dir=tmp_path)
    assert json.dumps(svc.doc, sort_keys=True) == before


# --- 5.2: wired into the turn, and a yes runs it ---------------------------------------------------

def test_the_turn_offers_the_shift_and_a_yes_runs_it(svc, tmp_path, monkeypatch):
    from services.smith import confirm
    from services.smith4 import handle as handle_fn
    H = sys.modules["services.smith4.handle"]
    monkeypatch.setattr(H, "_in_step", lambda o, v, r: r, raising=False)
    monkeypatch.setattr(H, "_engine_current", lambda o: [], raising=False)
    never = lambda *a: (_ for _ in ()).throw(AssertionError("the model must not be asked"))
    r1 = handle_fn(project_id="p", output_dir=str(tmp_path), message="make it dubai centric", choose=never, move=None)
    assert r1.status == "asked" and "go ahead" in r1.said.lower() and "Approve and build" in r1.said
    assert "regenerate from the updated requirements" not in r1.said                    # promises nothing it cannot do
    assert confirm.waiting(tmp_path)
    r2 = handle_fn(project_id="p", output_dir=str(tmp_path), message="Go ahead", choose=never, move=None)
    assert r2.status == "resolved" and "Changed INR to AED" in r2.said
    assert "AED 50,000" in json.dumps(BlueprintService.load(output_dir=str(tmp_path)).doc, ensure_ascii=False)
    assert not confirm.waiting(tmp_path)


def test_a_no_changes_nothing(svc, tmp_path, monkeypatch):
    from services.smith import confirm
    from services.smith4 import handle as handle_fn
    H = sys.modules["services.smith4.handle"]
    monkeypatch.setattr(H, "_in_step", lambda o, v, r: r, raising=False)
    monkeypatch.setattr(H, "_engine_current", lambda o: [], raising=False)
    before = json.dumps(BlueprintService.load(output_dir=str(tmp_path)).doc, sort_keys=True)
    handle_fn(project_id="p", output_dir=str(tmp_path), message="make it dubai centric", choose=lambda *a: {"tool": "answer", "args": {"text": "x"}}, move=None)
    handle_fn(project_id="p", output_dir=str(tmp_path), message="No, leave it", choose=lambda *a: {"tool": "answer", "args": {"text": "x"}}, move=None)
    assert not confirm.waiting(tmp_path)
    assert json.dumps(BlueprintService.load(output_dir=str(tmp_path)).doc, sort_keys=True) == before


# --- 5.6: the right implementer, or a proposal -------------------------------------------------------

@pytest.fixture()
def snap(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="SnapIT", domain="retail")
    s.doc["requirements"] = [
        {"id": "REQ-019", "description": "Only scrape from an allowlist of approved retailer websites.", "status": "APPROVED",
         "evidence": [{"message": "x", "type": "conversation"}]}]

    def wf(name, purpose, reqs=()):
        s.upsert("workflows", {"name": name, "purpose": purpose, "trigger": {"kind": "manual"}, "launchedFrom": [],
                               "requirements": list(reqs), "inputs": [],
                               "steps": [{"key": "start", "name": "Start", "type": "trigger", "config": {"type": "manual"}, "next": ["end"]},
                                         {"key": "end", "name": "End", "type": "end", "next": []}]}, natural_key=name)
    wf("Search Product Across Stores", "Search product on retailer websites and compare prices.")
    wf("Manage Retailer Allowlist", "Admin adds approved retailer websites.", ["REQ-019"])
    wf("Save Wishlist Pin", "Pin a product to the user's board.")
    s.save()
    return s


class Rec:
    def __init__(self):
        self.calls = []

    def __call__(self, svc, ref, request, **kw):
        self.calls.append(ref)


def _names(s, rec):
    by = {w["id"]: w["name"] for w in s.doc["workflows"]}
    return [by.get(c, c) for c in rec.calls]


@pytest.mark.parametrize("ask", ["Users can sort products by price on the product page.",
                                 "Show product pins on the board in a grid.",
                                 "Search results must show the store logo."])
def test_a_display_requirement_never_edits_a_workflow(snap, ask):
    rec = Rec()
    out = dc.add_requirement(snap, ask, changers={"workflow": rec, "rule": rec, "page": rec})
    assert rec.calls == [] and out["proposal"]


def test_a_new_limit_on_scraping_goes_where_the_earlier_limit_is_carried(snap):
    rec = Rec()
    out = dc.add_requirement(snap, "Web scraping only from fashion stores.", changers={"workflow": rec, "rule": rec, "page": rec})
    assert _names(snap, rec) == ["Manage Retailer Allowlist"] and out["changed"] == ["Manage Retailer Allowlist"]
