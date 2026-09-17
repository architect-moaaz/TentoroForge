"""A deployment must not stop to ask whether to destroy the user's data.

MEASURED ON A VERCEL DEPLOY THAT TIMED OUT. The projected schema wrote

    id: uuid("id").primaryKey().defaultRandom().unique()

A primary key is already unique, so the extra `.unique()` indexes nothing new
— and it emits a second constraint, `<table>_id_unique`. `drizzle-kit push`
asks before adding a unique constraint to a table that holds rows:

    You're about to add records_id_unique unique constraint to the table,
    which contains 3 items. Do you want to truncate records table?

Then it waits. On a build there is no terminal to answer it, so the deployment
sits until the clock runs out — on a question about destroying data, asked
because of a constraint nobody needed.

Two fixes, because they fail differently. The constraint is not emitted any
more, which removes the question. And the migration reads EOF, so a prompt
nobody anticipated gives up in a second rather than hanging: `--force` is
already passed and did not suppress this one, so it cannot be relied on to
suppress the next.
"""
import json
from pathlib import Path

import pytest

from services.blueprint.projection import drizzle_column

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"


def test_a_primary_key_does_not_also_declare_itself_unique():
    line, _ = drizzle_column(
        {"name": "id", "type": "uuid", "primaryKey": True, "unique": True})
    assert ".primaryKey()" in line
    assert ".unique()" not in line


def test_a_key_without_the_flag_is_unchanged():
    line, _ = drizzle_column({"name": "id", "type": "uuid", "primaryKey": True})
    assert line == 'id: uuid("id").primaryKey().defaultRandom(),'


def test_a_real_unique_column_still_gets_its_constraint():
    """The entity asked for this one, and it is not the key."""
    line, _ = drizzle_column(
        {"name": "email", "type": "string", "unique": True, "required": True})
    assert ".unique()" in line and ".primaryKey()" not in line


def test_the_vercel_build_cannot_be_asked_a_question():
    cfg = json.loads((TEMPLATES / "runtime" / "vercel.json").read_text())
    command = cfg["buildCommand"]
    assert "drizzle-kit push" in command
    assert "--force" in command
    assert "< /dev/null" in command, (
        "a prompt with no terminal to answer it hangs the build until timeout")


def test_the_start_script_cannot_be_asked_a_question():
    from services import runtime_injector
    import inspect

    src = inspect.getsource(runtime_injector)
    # The comment above the command mentions it too; the INVOCATION is the
    # line that runs, so match the one that actually calls npx.
    runs = [l for l in src.splitlines()
            if "npx drizzle-kit push" in l]
    assert runs, "the start script no longer migrates"
    for line in runs:
        assert "--force" in line and "< /dev/null" in line, line
