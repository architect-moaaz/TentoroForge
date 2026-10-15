"""The cockpit's tables are made by the models (so the test database has
them) and by two migrations that chain in one line from the head the
branch had — never two children of one revision, which would stop
`alembic upgrade head` on the container's start."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _revisions() -> dict[str, str | tuple]:
    out: dict[str, str | tuple] = {}
    for f in VERSIONS.glob("*.py"):
        s = f.read_text()
        rev = re.search(r"^revision(?:\s*:\s*\w+)?\s*=\s*['\"]([^'\"]+)['\"]", s, re.M)
        down = re.search(r"^down_revision(?:\s*:[^=]+)?\s*=\s*(.+)$", s, re.M)
        if rev:
            out[rev.group(1)] = tuple(re.findall(r"['\"]([^'\"]+)['\"]", down.group(1))) if down else ()
    return out


def test_the_cockpit_migrations_chain_in_one_line_from_the_old_head():
    revs = _revisions()
    assert revs["sa1015_super_admin"] == ("bd0920_brand_profiles",)
    assert revs["cr1015_credits"] == ("sa1015_super_admin",)
    children: dict[str, list[str]] = {}
    for rev, downs in revs.items():
        for d in downs:
            children.setdefault(d, []).append(rev)
    assert children.get("bd0920_brand_profiles") == ["sa1015_super_admin"], "one child, not a fork"
    heads = [r for r in revs if r not in children]
    assert revs["ft1015_features"] == ("cr1015_credits",)
    assert revs["dp1015_deployment_url"] == ("ft1015_features",)
    assert heads == ["dp1015_deployment_url"], heads


@pytest.mark.asyncio
async def test_the_tables_exist_in_the_test_database(test_db):
    from sqlalchemy import text
    from database import engine
    async with engine.connect() as conn:
        names = {row[0] for row in (await conn.execute(text("select name from sqlite_master where type='table'"))).all()}
    assert {"credit_entries", "spend_limits", "audit_logs", "deployments"} <= names
