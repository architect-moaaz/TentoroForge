"""Followup-2 — first analytics queries on FaultRecord.

The DB substrate landed in Slice 5. This exercises the four canonical
questions the log was designed to answer:

  1. Which fault signatures dominate for a project?
  2. What's the fix-stuck rate across all attempted fixes?
  3. Which component types fault most often?
  4. How often does PROMISE_NOT_DELIVERED fire per project?

Every query is a pure SQL aggregation against FaultRecord — no LLM.
"""
from __future__ import annotations

import uuid

import pytest

from services.fault_record_analytics import (
    fix_stuck_rate,
    promise_gaps_count,
    signature_count_by_component_type,
    top_signatures,
)


async def _seed(db, *, project_id: uuid.UUID, run_id: uuid.UUID,
                signature: str, w_slot: str = "when",
                component_type: str | None = "button",
                priority: str = "BROKEN", layer: str = "dom",
                fix_applied: bool = False, fix_stuck: bool | None = None):
    from models.fault_record import FaultRecord
    db.add(FaultRecord(
        run_id=run_id, project_id=project_id,
        signature=signature, priority=priority, layer=layer,
        w_slot=w_slot, component_type=component_type,
        fix_applied=fix_applied, fix_stuck=fix_stuck,
    ))


async def _run_scaffold(db):
    """Create the minimum FK chain for VerifyRun rows."""
    from models.auth import PlatformUser
    from models.org import Organization, OrgMember
    from models.project import Project
    from models.verify_run import VerifyRun

    user = PlatformUser(email="a@x.com", name="A", password_hash="x")
    db.add(user); await db.flush()
    org = Organization(name="O", slug="o1")
    db.add(org); await db.flush()
    db.add(OrgMember(org_id=org.id, user_id=user.id, role="owner"))
    proj = Project(org_id=org.id, short_id="p1", name="p",
                    owner_id=user.id, output_dir="/tmp/x")
    db.add(proj); await db.flush()
    run = VerifyRun(project_id=proj.id, target="preview", scope="*")
    db.add(run); await db.flush()
    return proj.id, run.id


# ── top_signatures ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_top_signatures_ranks_by_count(test_db):
    from database import async_session
    async with async_session() as db:
        pid, rid = await _run_scaffold(db)
        for _ in range(3):
            await _seed(db, project_id=pid, run_id=rid,
                        signature="BUTTON_NO_ACTION_DECLARED")
        await _seed(db, project_id=pid, run_id=rid,
                    signature="FORM_SUBMIT_500_GENERIC")
        await db.commit()

        result = await top_signatures(db, project_id=pid, limit=5)
        # (signature, count) tuples, ordered desc by count
        assert result[0] == ("BUTTON_NO_ACTION_DECLARED", 3)
        assert result[1] == ("FORM_SUBMIT_500_GENERIC", 1)


@pytest.mark.asyncio
async def test_top_signatures_scoped_to_project(test_db):
    from database import async_session
    async with async_session() as db:
        pid_a, rid_a = await _run_scaffold(db)
        # Another project
        from models.auth import PlatformUser
        from models.org import Organization, OrgMember
        from models.project import Project
        from models.verify_run import VerifyRun
        user2 = PlatformUser(email="b@x.com", name="B", password_hash="x")
        db.add(user2); await db.flush()
        org2 = Organization(name="O2", slug="o2")
        db.add(org2); await db.flush()
        db.add(OrgMember(org_id=org2.id, user_id=user2.id, role="owner"))
        proj2 = Project(org_id=org2.id, short_id="p2", name="p",
                        owner_id=user2.id, output_dir="/tmp/y")
        db.add(proj2); await db.flush()
        run2 = VerifyRun(project_id=proj2.id, target="preview", scope="*")
        db.add(run2); await db.flush()

        await _seed(db, project_id=pid_a, run_id=rid_a, signature="SIG_A")
        await _seed(db, project_id=proj2.id, run_id=run2.id, signature="SIG_B")
        await db.commit()

        a_top = await top_signatures(db, project_id=pid_a)
        assert [s for s, _ in a_top] == ["SIG_A"]


# ── fix_stuck_rate ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fix_stuck_rate(test_db):
    from database import async_session
    async with async_session() as db:
        pid, rid = await _run_scaffold(db)
        # 3 stuck, 1 regressed
        for _ in range(3):
            await _seed(db, project_id=pid, run_id=rid, signature="S",
                        fix_applied=True, fix_stuck=True)
        await _seed(db, project_id=pid, run_id=rid, signature="S",
                    fix_applied=True, fix_stuck=False)
        # Unattempted rows don't count in denominator
        await _seed(db, project_id=pid, run_id=rid, signature="S")
        await db.commit()

        rate = await fix_stuck_rate(db, project_id=pid)
        assert rate == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_fix_stuck_rate_no_attempts_returns_none(test_db):
    from database import async_session
    async with async_session() as db:
        pid, rid = await _run_scaffold(db)
        await _seed(db, project_id=pid, run_id=rid, signature="S")
        await db.commit()
        assert await fix_stuck_rate(db, project_id=pid) is None


# ── signature_count_by_component_type ────────────────────────────────────


@pytest.mark.asyncio
async def test_signature_count_by_component_type(test_db):
    from database import async_session
    async with async_session() as db:
        pid, rid = await _run_scaffold(db)
        for _ in range(2):
            await _seed(db, project_id=pid, run_id=rid,
                        signature="X", component_type="button")
        await _seed(db, project_id=pid, run_id=rid,
                    signature="X", component_type="form")
        await db.commit()

        result = await signature_count_by_component_type(db, project_id=pid)
        # dict-of-dicts: {component_type: {signature: count}}
        assert result["button"]["X"] == 2
        assert result["form"]["X"] == 1


# ── promise_gaps_count ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_promise_gaps_count(test_db):
    from database import async_session
    async with async_session() as db:
        pid, rid = await _run_scaffold(db)
        for _ in range(3):
            await _seed(db, project_id=pid, run_id=rid,
                        signature="PROMISE_NOT_DELIVERED", w_slot="why",
                        component_type=None)
        await _seed(db, project_id=pid, run_id=rid,
                    signature="BUTTON_NO_ACTION_DECLARED")
        await db.commit()

        assert await promise_gaps_count(db, project_id=pid) == 3
