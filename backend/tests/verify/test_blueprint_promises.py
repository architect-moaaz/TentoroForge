"""SV-STRICT-4 — blueprint_promises: extract structured promises from
the app's contract files (the *sources* BLUEPRINT.md renders, not the
Markdown itself — Markdown is a lossy view; the JSON contracts are
authoritative and always in sync).

The returned Promises dataclass is what fills ComponentContract.slots["why"]
and what promise_gate checks reachability against.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.blueprint_promises import (
    PersonaJob,
    Promises,
    load_promises,
)


def _write(root: Path, rel: str, data: dict | list) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ── Shape ────────────────────────────────────────────────────────────────


class TestEmpty:
    def test_no_files_returns_empty_promises(self, tmp_path: Path):
        p = load_promises(tmp_path)
        assert isinstance(p, Promises)
        assert p.page_purposes == {}
        assert p.workflow_purposes == {}
        assert p.persona_jobs == []

    def test_malformed_json_does_not_raise(self, tmp_path: Path):
        (tmp_path / "src" / "contracts").mkdir(parents=True)
        (tmp_path / "src" / "contracts" / "product-brief.json").write_text(
            "{not valid", encoding="utf-8",
        )
        p = load_promises(tmp_path)
        # Fail-open: bad JSON → empty section, not a crash.
        assert p.persona_jobs == []


# ── Persona jobs (from product-brief) ────────────────────────────────────


class TestPersonaJobs:
    def test_extracts_persona_jobs_from_product_brief(self, tmp_path: Path):
        _write(tmp_path, "src/contracts/product-brief.json", {
            "brand": {"name": "Yoga Studio"},
            "personas": [
                {
                    "id": "member", "name": "Member", "role": "member",
                    "one_liner": "books classes",
                    "jobs": [
                        {"id": "book-class", "label": "Book a class",
                         "primary_entities": ["Session"]},
                        {"id": "view-schedule", "label": "See my schedule",
                         "primary_entities": ["Booking"]},
                    ],
                },
                {
                    "id": "instructor", "name": "Instructor", "role": "instructor",
                    "jobs": [{"id": "mark-attendance", "label": "Mark attendance",
                              "primary_entities": ["Attendance"]}],
                },
            ],
        })
        p = load_promises(tmp_path)
        assert len(p.persona_jobs) == 3
        labels = {j.job_label for j in p.persona_jobs}
        assert labels == {"Book a class", "See my schedule", "Mark attendance"}

    def test_persona_job_carries_persona_metadata(self, tmp_path: Path):
        _write(tmp_path, "src/contracts/product-brief.json", {
            "personas": [{
                "id": "member", "name": "Member", "role": "member",
                "jobs": [{"id": "book", "label": "Book a class",
                          "primary_entities": ["Session"]}],
            }],
        })
        p = load_promises(tmp_path)
        j = p.persona_jobs[0]
        assert isinstance(j, PersonaJob)
        assert j.persona_id == "member"
        assert j.persona_name == "Member"
        assert j.primary_entities == ("Session",)

    def test_missing_product_brief_returns_empty_jobs(self, tmp_path: Path):
        # nav-flow + plan may exist without product-brief — degrade cleanly.
        _write(tmp_path, "src/contracts/nav-flow.json",
                {"version": "1.0", "initialPage": None, "pages": []})
        p = load_promises(tmp_path)
        assert p.persona_jobs == []


# ── Page purposes ────────────────────────────────────────────────────────


class TestPagePurposes:
    def test_reads_page_purpose_from_plan(self, tmp_path: Path):
        _write(tmp_path, "src/contracts/plan.json", {
            "pages": [
                {"route": "/schedule", "name": "Schedule",
                 "description": "Where students book classes"},
                {"route": "/attendance", "name": "Attendance",
                 "purpose": "Instructors mark who showed up"},
            ],
        })
        p = load_promises(tmp_path)
        assert p.page_purposes["/schedule"] == "Where students book classes"
        # Accept either 'description' or 'purpose' as source key.
        assert "showed up" in p.page_purposes["/attendance"]

    def test_falls_back_to_nav_flow_title_when_no_plan_description(self, tmp_path: Path):
        _write(tmp_path, "src/contracts/nav-flow.json", {
            "version": "1.0",
            "initialPage": "home",
            "pages": [{"id": "home", "route": "/",
                        "title": "Home Dashboard", "shell": True}],
        })
        p = load_promises(tmp_path)
        assert p.page_purposes["/"] == "Home Dashboard"

    def test_plan_description_wins_over_nav_flow_title(self, tmp_path: Path):
        _write(tmp_path, "src/contracts/nav-flow.json", {
            "version": "1.0", "initialPage": "home",
            "pages": [{"id": "home", "route": "/", "title": "Home", "shell": True}],
        })
        _write(tmp_path, "src/contracts/plan.json", {
            "pages": [{"route": "/", "name": "Home",
                        "description": "The dashboard every user lands on"}],
        })
        assert (load_promises(tmp_path).page_purposes["/"]
                == "The dashboard every user lands on")


# ── Workflow purposes ────────────────────────────────────────────────────


class TestWorkflowPurposes:
    def test_reads_workflow_description(self, tmp_path: Path):
        _write(tmp_path, "src/contracts/plan.json", {
            "workflows": [
                {"name": "BookClass", "description": "Reserves a spot in a session"},
                {"name": "CancelBooking", "purpose": "Cancels a member's booking"},
            ],
        })
        p = load_promises(tmp_path)
        assert p.workflow_purposes["BookClass"] == "Reserves a spot in a session"
        assert "Cancels" in p.workflow_purposes["CancelBooking"]

    def test_missing_workflows_returns_empty(self, tmp_path: Path):
        assert load_promises(tmp_path).workflow_purposes == {}
