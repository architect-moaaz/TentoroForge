"""Drift guard for the fixture fleet registry (fleet/fixtures/).

Fixtures are frozen pipeline inputs; these tests keep the registry
well-formed so the fleet runner (scripts/fleet.py) can trust its shape:
every fixture has a description + meta, plans are canonical (running
canonicalize_plan again changes nothing), and plan-less fixtures say so
explicitly in meta.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.plan_canonicalizer import canonicalize_plan

FLEET = Path(__file__).resolve().parents[2] / "fleet" / "fixtures"

FIXTURES = sorted(d.name for d in FLEET.iterdir() if d.is_dir()) \
    if FLEET.is_dir() else []


def test_registry_exists_with_expected_members():
    assert FLEET.is_dir()
    for name in ("doc-intel", "yoga-booking", "recruitment",
                 "leave-management", "banking", "commerce-cart"):
        assert name in FIXTURES, f"missing fixture {name}"


@pytest.mark.parametrize("name", FIXTURES)
def test_fixture_well_formed(name):
    d = FLEET / name
    desc = (d / "description.txt").read_text().strip()
    assert len(desc) > 40, "description too short to drive a generation"

    meta = json.loads((d / "meta.json").read_text())
    assert meta.get("archetype")
    assert isinstance(meta.get("stresses"), list) and meta["stresses"]
    assert meta.get("profile") in ("fast", "complete")

    plan_p = d / "plan.json"
    if not plan_p.is_file():
        # plan-less fixtures must declare how the plan gets seeded
        assert "replan" in str(meta.get("plan", "")), \
            f"{name} has no plan.json and meta.plan doesn't mention --replan"
        return
    plan = json.loads(plan_p.read_text())
    assert plan.get("data_models"), f"{name} plan has no data_models"
    assert plan.get("pages"), f"{name} plan has no pages"


@pytest.mark.parametrize("name", FIXTURES)
def test_fixture_plan_is_canonical(name):
    """Frozen plans are stored post-canonicalization — running the
    canonicalizer again must be a no-op, so fleet runs are deterministic
    with respect to the stored input."""
    plan_p = FLEET / name / "plan.json"
    if not plan_p.is_file():
        pytest.skip("plan seeded via --replan")
    plan = json.loads(plan_p.read_text())
    canonical, _report = canonicalize_plan(plan)
    assert canonical == plan, f"{name} plan.json is not canonical"
