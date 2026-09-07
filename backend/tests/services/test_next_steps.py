"""Tests for services.next_steps — the "What next?" suggestion deriver.

The reliability guarantee for the NextStepsCard rests on these tests:
same plan → same suggestions, always plan-derived (no phantoms), never
more than ``max_steps`` chips, always something even when the plan is
missing.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.next_steps import (
    NextStep,
    derive_next_steps,
    derive_next_steps_from_output_dir,
    load_plan,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                     #
# --------------------------------------------------------------------------- #

def _recruitment_plan() -> dict:
    return {
        "module_name": "Recruitment",
        "data_models": [
            {"name": "Applicant", "fields": []},
            {"name": "Interview", "fields": []},
            # Should be skipped — auth entity.
            {"name": "User", "fields": []},
        ],
        "pages": [
            {"route": "/", "name": "Dashboard", "archetype": "dashboard"},
            {"route": "/applicants", "name": "Applicants"},
        ],
    }


def _no_dashboard_plan() -> dict:
    return {
        "data_models": [{"name": "Booking", "fields": []}],
        "pages": [{"route": "/bookings", "name": "Bookings"}],
    }


def _commerce_plan() -> dict:
    return {
        "data_models": [
            {"name": "Product", "fields": [], "commerce": True},
        ],
        "pages": [{"route": "/products", "name": "Products"}],
    }


# --------------------------------------------------------------------------- #
# Contract: card is always non-empty and small                                 #
# --------------------------------------------------------------------------- #

class TestBasicContract:
    def test_empty_plan_still_yields_steps(self):
        steps = derive_next_steps(None)
        assert len(steps) >= 1, "Fallback set must not be empty"

    def test_empty_plan_gets_theme_publish_mobile(self):
        steps = derive_next_steps(None)
        labels = [s.label for s in steps]
        assert any("theme" in l.lower() for l in labels)
        assert any("publish" in l.lower() for l in labels)
        assert any("mobile" in l.lower() for l in labels)

    def test_max_steps_is_honored(self):
        plan = _recruitment_plan()
        steps = derive_next_steps(plan, max_steps=3)
        assert len(steps) == 3

    def test_default_cap_is_six(self):
        # Contrived plan with many signals — the cap should still hold.
        plan = _recruitment_plan()
        plan["data_models"].append({"name": "Product", "commerce": True})
        steps = derive_next_steps(plan)
        assert len(steps) <= 6


# --------------------------------------------------------------------------- #
# Ordering: try-app-first, ship-last                                           #
# --------------------------------------------------------------------------- #

class TestOrdering:
    def test_add_a_record_comes_before_publish(self):
        steps = derive_next_steps(_recruitment_plan())
        labels = [s.label for s in steps]
        add_idx = next(i for i, l in enumerate(labels) if l.startswith("Add your first"))
        pub_idx = next(i for i, l in enumerate(labels) if "Publish" in l)
        assert add_idx < pub_idx

    def test_theme_comes_before_ship(self):
        steps = derive_next_steps(_recruitment_plan())
        labels = [s.label for s in steps]
        theme_idx = next(i for i, l in enumerate(labels) if "theme" in l.lower())
        pub_idx = next(i for i, l in enumerate(labels) if "Publish" in l)
        assert theme_idx < pub_idx


# --------------------------------------------------------------------------- #
# Plan-derived: no phantoms                                                    #
# --------------------------------------------------------------------------- #

class TestPlanDerived:
    def test_primary_entity_names_a_real_entity(self):
        steps = derive_next_steps(_recruitment_plan())
        add = next(s for s in steps if s.label.startswith("Add your first"))
        # First non-skipped entity is Applicant.
        assert "Applicant" in add.label
        assert add.url == "/applicants/new"

    def test_skips_auth_entity_when_picking_primary(self):
        # A plan whose FIRST entity is User (auth) — we should still pick
        # a real entity for the "Add your first" chip.
        plan = {
            "data_models": [
                {"name": "User", "fields": []},
                {"name": "Applicant", "fields": []},
            ],
            "pages": [],
        }
        steps = derive_next_steps(plan)
        add = next((s for s in steps if s.label.startswith("Add your first")), None)
        assert add is not None
        assert "User" not in add.label
        assert "Applicant" in add.label

    def test_no_add_chip_when_no_entities(self):
        plan = {"data_models": [], "pages": []}
        steps = derive_next_steps(plan)
        assert not any(s.label.startswith("Add your first") for s in steps)

    def test_dashboard_chip_only_when_dashboard_present(self):
        with_dash = derive_next_steps(_recruitment_plan())
        without = derive_next_steps(_no_dashboard_plan())
        assert any("dashboard" in s.label.lower() for s in with_dash)
        assert not any("dashboard" in s.label.lower() for s in without)

    def test_commerce_chip_only_when_commerce_entity_present(self):
        without = derive_next_steps(_recruitment_plan())
        with_commerce = derive_next_steps(_commerce_plan())
        assert not any("checkout" in s.label.lower() for s in without)
        assert any("checkout" in s.label.lower() for s in with_commerce)


# --------------------------------------------------------------------------- #
# Toggles                                                                      #
# --------------------------------------------------------------------------- #

class TestToggles:
    def test_include_publish_off(self):
        steps = derive_next_steps(_recruitment_plan(), include_publish=False)
        assert not any("Publish" in s.label for s in steps)

    def test_include_mobile_off(self):
        steps = derive_next_steps(_recruitment_plan(), include_mobile=False)
        assert not any("mobile" in s.label.lower() for s in steps)


# --------------------------------------------------------------------------- #
# Shape                                                                        #
# --------------------------------------------------------------------------- #

class TestShape:
    def test_every_step_has_valid_kind(self):
        steps = derive_next_steps(_recruitment_plan())
        for s in steps:
            assert s.kind in {"send", "navigate", "tool"}

    def test_navigate_steps_have_url(self):
        steps = derive_next_steps(_recruitment_plan())
        for s in steps:
            if s.kind == "navigate":
                assert s.url, f"navigate step {s.label!r} missing url"

    def test_send_and_tool_steps_have_message(self):
        steps = derive_next_steps(_recruitment_plan())
        for s in steps:
            if s.kind in ("send", "tool"):
                assert s.message, f"{s.kind} step {s.label!r} missing message"

    def test_to_dict_drops_nones(self):
        step = NextStep(label="X", kind="send", message="do X")
        payload = step.to_dict()
        assert "url" not in payload
        assert "icon" not in payload
        assert payload["label"] == "X"
        assert payload["kind"] == "send"
        assert payload["message"] == "do X"


# --------------------------------------------------------------------------- #
# Deterministic                                                                #
# --------------------------------------------------------------------------- #

class TestDeterminism:
    def test_same_plan_same_output(self):
        plan = _recruitment_plan()
        first = derive_next_steps(plan)
        second = derive_next_steps(plan)
        assert [s.to_dict() for s in first] == [s.to_dict() for s in second]


# --------------------------------------------------------------------------- #
# load_plan + convenience wrapper                                              #
# --------------------------------------------------------------------------- #

class TestLoadPlan:
    def test_reads_from_src_contracts(self, tmp_path: Path):
        plan_path = tmp_path / "src" / "contracts" / "plan.json"
        plan_path.parent.mkdir(parents=True)
        plan = {"module_name": "X", "data_models": []}
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        assert load_plan(tmp_path) == plan

    def test_reads_from_contracts(self, tmp_path: Path):
        plan_path = tmp_path / "contracts" / "plan.json"
        plan_path.parent.mkdir(parents=True)
        plan = {"module_name": "Y", "data_models": []}
        plan_path.write_text(json.dumps(plan), encoding="utf-8")
        assert load_plan(tmp_path) == plan

    def test_missing_returns_none(self, tmp_path: Path):
        assert load_plan(tmp_path) is None

    def test_bad_json_returns_none(self, tmp_path: Path):
        p = tmp_path / "contracts" / "plan.json"
        p.parent.mkdir(parents=True)
        p.write_text("{not json", encoding="utf-8")
        assert load_plan(tmp_path) is None

    def test_wrapper_falls_back_when_no_plan(self, tmp_path: Path):
        # No plan file — wrapper still returns the theme/publish/mobile
        # fallback set.
        steps = derive_next_steps_from_output_dir(tmp_path)
        assert len(steps) >= 1
        assert any("theme" in s.label.lower() for s in steps)
