"""A deploy preserves what somebody entered, and resets only what is empty.

`reset-schema.ts` runs first in the Vercel build and used to open with

    DROP SCHEMA public CASCADE

unless `FORGE_KEEP_DB_STATE=1` was set. Its own comment justified that: "the
generated app has no user data worth preserving across deploys". True of an
app nobody has used, false the moment somebody enters something — and the end
user's path is to click publish, which runs exactly this.

Destroying data should take intent, not the absence of an environment
variable. So the rule inverted: if any DOMAIN table holds a row, the database
is migrated in place and nothing is dropped. Only a database with nothing to
lose is reset, which is the case the script was written for — a push that
emits DDL Postgres refuses, leaving half a schema and an app that 500s.

Scaffold tables do not count. `seed.ts` writes an admin user on every deploy
and the `_forge_*` tables are runtime bookkeeping; counting those would mean
the reset never ran again after the first deploy.

VERIFIED AGAINST A REAL DATABASE. With three rows in `records` it reported
"records hold data — migrating in place, nothing dropped" and left every table
standing. With `records` empty and only a seeded admin in `users`, it reset and
the schema came back with nothing in it.
"""
from pathlib import Path

import pytest

SCRIPT = (Path(__file__).resolve().parents[2] / "templates" / "app-foundation"
          / "src" / "db" / "reset-schema.ts")


@pytest.fixture(scope="module")
def source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_nothing_is_dropped_before_the_database_is_known_to_be_empty(source):
    """The order is the guarantee: the emptiness check has to come first."""
    assert source.index("holding.length") < source.index("DROP SCHEMA")


def test_a_table_holding_rows_stops_the_drop(source):
    assert "migrating in place" in source
    assert "nothing dropped" in source
    # Returns rather than falling through to the drop.
    guard = source[source.index("if (holding.length)"):source.index("DROP SCHEMA")]
    assert "return;" in guard


def test_the_seeded_admin_does_not_count_as_the_users_work(source):
    """Counting it would mean the reset never ran after the first deploy,
    including on the broken-DDL case it exists for."""
    assert '"users"' in source
    assert "_forge_" in source
    assert "isScaffold" in source


def test_asking_whether_anything_is_there_does_not_read_whole_tables(source):
    assert "LIMIT 1" in source


def test_a_table_name_cannot_carry_an_injection(source):
    """Table names come from information_schema, and are still quoted."""
    assert 'replace(/"/g' in source


def test_the_explicit_override_still_preserves(source):
    # The docstring mentions it too; the CHECK is the one inside an `if`.
    i = source.index('process.env.FORGE_KEEP_DB_STATE')
    assert "return;" in source[i:i + 300]


def test_the_build_still_runs_it_first():
    """It has to see the database before drizzle-kit touches it."""
    import json

    cfg = json.loads((SCRIPT.parents[3] / "runtime" / "vercel.json").read_text())
    command = cfg["buildCommand"]
    assert command.index("reset-schema") < command.index("drizzle-kit push")
