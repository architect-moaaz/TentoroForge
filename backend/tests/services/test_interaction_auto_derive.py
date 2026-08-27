"""Tests for interaction_auto_derive — the deterministic pass that
fills in obvious computed/cascade interactions the LLM missed."""

from __future__ import annotations

from services.interaction_auto_derive import apply_auto_derivations


def _plan(fields: list[dict]) -> dict:
    return {"pages": [{"id": "form", "fields": fields}]}


class TestLineTotal:
    def test_quantity_and_price(self):
        plan = _plan([
            {"name": "quantity"}, {"name": "unitPrice"}, {"name": "lineTotal"},
        ])
        report = apply_auto_derivations(plan)
        assert any("lineTotal" in a for a in report["applied"]), report
        total = plan["pages"][0]["fields"][2]
        assert total["interaction"]["computed"]["formula"] == "quantity * unitPrice"

    def test_qty_and_rate_synonyms(self):
        plan = _plan([{"name": "qty"}, {"name": "rate"}, {"name": "amount"}])
        apply_auto_derivations(plan)
        assert plan["pages"][0]["fields"][2]["interaction"]["computed"]["formula"] == "qty * rate"

    def test_missing_siblings_skips(self):
        plan = _plan([{"name": "quantity"}, {"name": "lineTotal"}])  # no price
        apply_auto_derivations(plan)
        assert "interaction" not in plan["pages"][0]["fields"][1]


class TestGrandTotal:
    def test_subtotal_plus_tax_minus_discount(self):
        plan = _plan([
            {"name": "subtotal"}, {"name": "tax"}, {"name": "discount"},
            {"name": "grandTotal"},
        ])
        apply_auto_derivations(plan)
        gt = plan["pages"][0]["fields"][3]
        assert "subtotal" in gt["interaction"]["computed"]["formula"]
        assert "+ tax" in gt["interaction"]["computed"]["formula"]
        assert "- discount" in gt["interaction"]["computed"]["formula"]

    def test_subtotal_alone_does_not_derive(self):
        plan = _plan([{"name": "subtotal"}, {"name": "grandTotal"}])
        apply_auto_derivations(plan)
        assert "interaction" not in plan["pages"][0]["fields"][1]


class TestPayroll:
    def test_hra_from_basic(self):
        plan = _plan([{"name": "basicSalary"}, {"name": "hra"}])
        apply_auto_derivations(plan)
        assert plan["pages"][0]["fields"][1]["interaction"]["computed"]["formula"] == "basicSalary * 0.4"

    def test_da_from_basic(self):
        plan = _plan([{"name": "basic"}, {"name": "da"}])
        apply_auto_derivations(plan)
        assert plan["pages"][0]["fields"][1]["interaction"]["computed"]["formula"] == "basic * 0.12"


class TestAgeAndDuration:
    def test_age_from_dob(self):
        plan = _plan([{"name": "dob"}, {"name": "age"}])
        apply_auto_derivations(plan)
        assert plan["pages"][0]["fields"][1]["interaction"]["computed"]["formula"] == "age(dob)"

    def test_days_between(self):
        plan = _plan([
            {"name": "checkIn"}, {"name": "checkOut"}, {"name": "nights"},
        ])
        apply_auto_derivations(plan)
        nights = plan["pages"][0]["fields"][2]
        assert nights["interaction"]["computed"]["formula"] == "daysBetween(checkIn, checkOut)"


class TestGeoCascade:
    def test_state_depends_on_country(self):
        plan = _plan([{"name": "countryId"}, {"name": "stateId"}])
        apply_auto_derivations(plan)
        st = plan["pages"][0]["fields"][1]
        of = st["interaction"]["optionsFrom"]
        assert of["source"] == "states"
        assert of["filter"] == {"countryId": "{{countryId}}"}


class TestGuards:
    def test_never_overwrites_existing_interaction(self):
        plan = _plan([
            {"name": "basicSalary"},
            {"name": "hra", "interaction": {"computed": {"formula": "basicSalary * 0.5"}}},
        ])
        apply_auto_derivations(plan)
        # Existing formula preserved untouched
        assert plan["pages"][0]["fields"][1]["interaction"]["computed"]["formula"] == "basicSalary * 0.5"

    def test_idempotent(self):
        plan = _plan([{"name": "dob"}, {"name": "age"}])
        apply_auto_derivations(plan)
        first = plan["pages"][0]["fields"][1]["interaction"]
        apply_auto_derivations(plan)  # second run: already has interaction, skips
        second = plan["pages"][0]["fields"][1]["interaction"]
        assert first == second

    def test_no_pages_no_error(self):
        report = apply_auto_derivations({})
        assert report == {"applied": [], "skipped": []}
