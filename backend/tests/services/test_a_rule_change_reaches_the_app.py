"""A rule recorded through Smith must reach what implements it, leave a trace,
not churn, and a market shift must be recognised and offered as a regeneration
(UAT SnapIT: 'scraping from fashion stores only', 'make it dubai centric')."""
import json

import pytest

from services.blueprint.service import BlueprintService
from services.blueprint.verification import requirement_verdict
from services.smith import big_shift, definition_change as dc, requirement_reach as rr


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="SnapIT", domain="retail")
    s.doc["requirements"] = [{"id": "REQ-019", "description": "Scrape product prices from online stores.",
                              "status": "APPROVED", "evidence": [{"message": "x", "type": "conversation"}]}]
    s.upsert("workflows", {"name": "Scrape Store Prices", "purpose": "Search stores and scrape product prices.",
                           "trigger": {"kind": "manual"}, "launchedFrom": [], "requirements": ["REQ-019"], "inputs": [],
                           "steps": [{"key": "start", "name": "Start", "type": "trigger", "config": {"type": "manual"}, "next": ["end"]},
                                     {"key": "end", "name": "End", "type": "end", "next": []}]}, natural_key="Scrape Store Prices")
    s.save()
    return s


class Recorder:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def __call__(self, svc, ref, request, **kw):
        self.calls.append((ref, request))
        if self.fail:
            raise RuntimeError("the author refused")


def _changers(rec):
    return {"workflow": rec, "rule": rec, "page": rec}


def test_a_new_rule_changes_what_does_the_work_and_is_traced_to_it(svc):
    rec = Recorder()
    out = dc.add_requirement(svc, "The web scraping should take place from fashion stores only.", changers=_changers(rec))
    assert out["changed"] == ["Scrape Store Prices"] and len(rec.calls) == 1
    assert out["requirement"] in rec.calls[0][1]
    wf = next(w for w in svc.doc["workflows"] if w["name"] == "Scrape Store Prices")
    assert out["requirement"] in wf["requirements"]                       # REQ -> implementer link
    assert "implemented" in dc.summary_of("add_requirement", out) and "Scrape Store Prices" in dc.summary_of("add_requirement", out)
    assert "Nothing implements it yet" not in dc.summary_of("add_requirement", out)


def test_a_rule_nothing_can_carry_is_said_plainly_with_a_specific_proposal(svc):
    out = dc.add_requirement(svc, "Orders must be refused for customers under eighteen.", changers=_changers(Recorder()))
    assert out["changed"] == [] and out["traced"] == []
    said = dc.summary_of("add_requirement", out)
    assert "Nothing implements it yet" in said
    assert "I propose" in said and "business rule" in said and "say what screen" not in said


def test_a_refused_change_is_reported_and_not_traced(svc):
    out = dc.add_requirement(svc, "Scraping must use fashion stores only.", changers=_changers(Recorder(fail=True)))
    assert out["traced"] == [] and out["failed"] and "author refused" in out["failed"][0]
    assert out["requirement"] not in next(w for w in svc.doc["workflows"])["requirements"]


def test_restating_the_same_requirement_is_not_authored_again(svc):
    rec = Recorder()
    first = dc.add_requirement(svc, "The web scraping should take place from fashion stores only.", changers=_changers(rec))
    again = dc.add_requirement(svc, "Web scraping should only take place from fashion stores.", changers=_changers(rec))
    assert again.get("unchanged") and again["requirement"] == first["requirement"]
    assert len(rec.calls) == 1
    assert len([r for r in svc.doc["requirements"] if "fashion" in r["description"]]) == 1


def test_an_edit_that_says_the_same_changes_nothing(svc):
    n_decisions = len(svc.doc.get("decisions") or [])
    out = dc.edit_requirement(svc, "REQ-019", "Scrape the product prices from online stores")
    assert out["unchanged"] and out["decision"] == "" and len(svc.doc.get("decisions") or []) == n_decisions


def test_only_the_clause_that_differs_is_passed_on():
    d = rr.clause_delta("Scrape product prices from online stores.",
                        "Scrape product prices from online stores. Only fashion stores are allowed.")
    assert d == "Only fashion stores are allowed."


def test_requirement_trace_makes_verify_hold_it(svc):
    out = dc.add_requirement(svc, "Scraping should be from fashion stores only.", changers=_changers(Recorder()))
    claimed = [a["id"] for a in svc.doc["workflows"] if out["requirement"] in a.get("requirements", [])]
    assert claimed                                                       # the thing Requirement<->Code reads
    verdict = requirement_verdict(svc.doc, out["requirement"])
    assert not any("no artifact claims" in n for n in verdict["facets"]["Requirement↔Code"]["notes"])


# --- 5B ----------------------------------------------------------------------------

def test_a_market_shift_is_recognised_and_a_plain_edit_is_not():
    s = big_shift.detect("make it dubai centric")
    assert s["kind"] == "market" and s["currency"] == "AED" and any("sample data" in t for t in s["touches"])
    assert big_shift.detect("change the currency to AED")["currency"] == "AED"
    assert big_shift.detect("make the header blue") is None
    assert big_shift.detect("the web scraping should take place from fashion stores only") is None


def test_currency_is_swapped_in_the_blueprint_and_the_seed_not_in_identifiers(svc, tmp_path):
    svc.doc["requirements"].append({"id": "REQ-040", "description": "Show all prices in INR (₹).", "status": "APPROVED",
                                    "evidence": [{"message": "p", "type": "conversation"}]})
    svc.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Product", "table": "products", "fields": [
        {"name": "id", "type": "uuid", "primaryKey": True},
        {"name": "priceINR", "type": "decimal", "description": "Price in INR"}]}], "relationships": []}
    svc.save()
    (tmp_path / "contracts").mkdir(exist_ok=True)
    (tmp_path / "contracts/seed-plan.json").write_text(json.dumps({"sample_data": {"Product": [{"note": "Rs. 499 / INR"}]}}))
    assert big_shift.current_currency(svc.doc) == "INR"
    prev = big_shift.preview_currency(svc.doc, "INR", "AED", output_dir=tmp_path)
    assert prev["total"] >= 3 and prev["seed_rows"] == 1
    assert "INR" in json.dumps(svc.doc)                                 # preview changed nothing
    out = big_shift.apply_currency(svc, "INR", "AED", output_dir=tmp_path)
    assert out["blueprint_changed"] and out["seed_changed"]
    text = json.dumps(svc.doc, ensure_ascii=False)
    assert "Show all prices in AED." in text and "Price in AED" in text
    assert '"priceINR"' in text                                          # a field's name is an identifier
    assert "AED" in (tmp_path / "contracts/seed-plan.json").read_text()
    assert big_shift.apply_currency(svc, "INR", "AED", output_dir=tmp_path)["applied"] is False   # idempotent


def test_the_offer_says_what_is_kept_and_what_is_not_converted():
    s = big_shift.proposal(big_shift.detect("make it dubai centric"),
                           {"from": "INR", "to": "AED", "blueprint": {"requirements": 2}, "seed_rows": 3, "total": 5})
    for word in ("go ahead", "not convert", "5 place", "Approve and build", "identifiers"):
        assert word in s
