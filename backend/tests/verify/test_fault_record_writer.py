"""SV-STRICT-5 — FaultRecord writer.

Two layers:
  * Pure: build_records(...) → list of row-dicts (no DB, fast tests)
  * Async: persist_records + mark_fix_outcomes against the in-memory
    SQLite test DB fixture (from backend/tests/conftest.py).
"""
from __future__ import annotations

import uuid
from typing import Any

import pytest

from services.fault_record_writer import (
    build_records,
    mark_fix_outcomes,
    persist_records,
)


# ── Fixtures ─────────────────────────────────────────────────────────────


def _button_fault(component_id: str = "button:/x:root.children[0]",
                  signature: str = "BUTTON_NO_ACTION_DECLARED",
                  contract_id: str | None = None) -> dict[str, Any]:
    return {
        "interaction_id": component_id,
        "interaction": {
            "kind": "button", "id": component_id, "route": "/x",
            "selector": "", "label": "Click Me",
            "action": {"kind": "none"},
        },
        "evidence": {"status": 200, "body_excerpt": "b" * 800},
        "signature": signature,
        "priority": "BROKEN",
        "layer": "dom",
        "w_slot": "when",
        "hypothesis": "…",
        "suggested_tools": [],
        "contract_id": contract_id,
    }


def _narrated_for(component_id: str, text: str = "The button doesn't work.") -> dict:
    return {
        "narratives": [{
            "text": text, "priority": "BROKEN",
            "signature": "BUTTON_NO_ACTION_DECLARED",
            "w_slot": "when",
            "component_id": component_id, "route": "/x",
        }],
        "by_w_slot": {"when": [{"component_id": component_id}]},
    }


# ── Pure: build_records ──────────────────────────────────────────────────


class TestBuildRecords:
    def test_no_faults_returns_empty(self):
        assert build_records(
            run_id="r1", project_id="p1", report={},
        ) == []

    def test_one_fault_produces_one_row(self):
        rows = build_records(
            run_id="r1", project_id="p1",
            report={"faults": [_button_fault()]},
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["run_id"] == "r1"
        assert row["project_id"] == "p1"
        assert row["signature"] == "BUTTON_NO_ACTION_DECLARED"
        assert row["w_slot"] == "when"
        assert row["component_type"] == "button"
        assert row["route"] == "/x"

    def test_narrative_joined_by_component_id(self):
        cid = "button:/x:root.children[0]"
        rows = build_records(
            run_id="r1", project_id="p1",
            report={"faults": [_button_fault(component_id=cid)]},
            narrated=_narrated_for(cid),
        )
        assert rows[0]["narrative"] == "The button doesn't work."

    def test_evidence_body_is_capped(self):
        rows = build_records(
            run_id="r1", project_id="p1",
            report={"faults": [_button_fault()]},
        )
        # Body was 800 chars; writer clamps to <=400.
        assert len(rows[0]["evidence"]["body_excerpt"]) <= 400

    def test_generation_hash_stamped(self):
        rows = build_records(
            run_id="r1", project_id="p1",
            report={"faults": [_button_fault()]},
            generation_hash="abc1234",
        )
        assert rows[0]["generation_hash"] == "abc1234"

    def test_fix_flags_default_false_none(self):
        row = build_records(
            run_id="r1", project_id="p1",
            report={"faults": [_button_fault()]},
        )[0]
        assert row["fix_applied"] is False
        assert row["fix_stuck"] is None

    def test_contract_id_passthrough(self):
        rows = build_records(
            run_id="r1", project_id="p1",
            report={"faults": [_button_fault(contract_id="button:/x:click-me")]},
        )
        assert rows[0]["contract_id"] == "button:/x:click-me"

    def test_bad_fault_shape_skipped_not_raised(self):
        rows = build_records(
            run_id="r1", project_id="p1",
            report={"faults": [None, _button_fault(), {"garbage": True}]},
        )
        # The single valid fault survives; the other two are dropped.
        assert len(rows) == 2  # None and {"garbage":True} still produce minimal rows
        assert any(r["signature"] == "BUTTON_NO_ACTION_DECLARED" for r in rows)


# ── Async: persist_records + mark_fix_outcomes ───────────────────────────
#
# Exercise the SQL round-trip against the in-memory SQLite fixture
# from conftest.py. The conftest fixture strips PG-only nextval()
# server_defaults before `Base.metadata.create_all` runs.


@pytest.mark.asyncio
async def test_persist_records_inserts_rows(test_db):
    from database import async_session
    from models.auth import PlatformUser
    from models.org import Organization, OrgMember
    from models.project import Project
    from models.verify_run import VerifyRun

    async with async_session() as db:
        # Build the minimal auth + org + project + verify_run chain.
        user = PlatformUser(email="test@example.com", name="T",
                             password_hash="x")
        db.add(user)
        await db.flush()
        org = Organization(name="Test", slug="test-org")
        db.add(org)
        await db.flush()
        db.add(OrgMember(org_id=org.id, user_id=user.id, role="owner"))
        proj = Project(org_id=org.id, short_id="p1", name="p",
                        owner_id=user.id, output_dir="/tmp/x")
        db.add(proj)
        await db.flush()
        run = VerifyRun(project_id=proj.id, target="preview", scope="*")
        db.add(run)
        await db.flush()

        rows = build_records(
            run_id=run.id, project_id=proj.id,
            report={"faults": [
                _button_fault(component_id="button:/x:a"),
                _button_fault(component_id="button:/x:b",
                               signature="FORM_SUBMIT_500_GENERIC"),
            ]},
        )
        n = await persist_records(db, rows)
        await db.commit()
        assert n == 2

        from sqlalchemy import select
        from models.fault_record import FaultRecord

        result = (await db.execute(
            select(FaultRecord).where(FaultRecord.run_id == run.id),
        )).scalars().all()
        assert len(result) == 2
        sigs = {r.signature for r in result}
        assert sigs == {"BUTTON_NO_ACTION_DECLARED", "FORM_SUBMIT_500_GENERIC"}


@pytest.mark.asyncio
async def test_mark_fix_outcomes_updates_flags(test_db):
    from database import async_session
    from models.auth import PlatformUser
    from models.org import Organization, OrgMember
    from models.project import Project
    from models.verify_run import VerifyRun

    async with async_session() as db:
        user = PlatformUser(email="t@x.com", name="T", password_hash="x")
        db.add(user); await db.flush()
        org = Organization(name="O", slug="o-org")
        db.add(org); await db.flush()
        db.add(OrgMember(org_id=org.id, user_id=user.id, role="owner"))
        proj = Project(org_id=org.id, short_id="p2", name="p",
                        owner_id=user.id, output_dir="/tmp/x")
        db.add(proj); await db.flush()
        run = VerifyRun(project_id=proj.id, target="preview", scope="*")
        db.add(run); await db.flush()

        rows = build_records(
            run_id=run.id, project_id=proj.id,
            report={"faults": [
                _button_fault(component_id="button:/x:a"),
                _button_fault(component_id="button:/x:b"),
            ]},
        )
        await persist_records(db, rows)
        await db.flush()

        await mark_fix_outcomes(
            db, run_id=run.id,
            fixed_component_ids=["button:/x:a"],
            still_failing_component_ids=["button:/x:b"],
        )
        await db.commit()

        from sqlalchemy import select
        from models.fault_record import FaultRecord

        result = {
            r.component_id: r for r in (await db.execute(
                select(FaultRecord).where(FaultRecord.run_id == run.id),
            )).scalars().all()
        }
        assert result["button:/x:a"].fix_applied is True
        assert result["button:/x:a"].fix_stuck is True
        assert result["button:/x:b"].fix_applied is True
        assert result["button:/x:b"].fix_stuck is False
