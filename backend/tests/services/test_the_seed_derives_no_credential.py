"""The projected seed wrote a value for a password field, and there is no value
it could have written that works.

A hash is not derivable from a Blueprint, so `_seed_value` produced the label
its rule produces for any text column — "Password Hash 1" — and the runtime
inserted it verbatim. `auth.ts` bcrypt-compares what it finds, so the account
existed and nobody could sign into it; had the field been named `password` and
the value a plaintext, a readable credential would have sat in a file that is
committed, exported and published (§42).

So the field is left out of every seeded row, and the runtime fills the column
with a hash nobody holds (`_unusableCredentials` in templates/runtime/seed.ts,
tested beside it). The row exists as data and the account cannot be signed
into, which is the honest state of an account nobody was given.
"""
import json
from pathlib import Path

import pytest

from services.blueprint.projection import _is_credential_field, project_seed


def _seed(tmp_path, fields: list[dict]) -> dict:
    project_seed({"data": {"entities": [
        {"id": "ENT-001", "name": "Nurse", "table": "nurses", "fields": fields}]}}, tmp_path)
    return json.loads((Path(tmp_path) / "src" / "db" / "seed.json").read_text())


@pytest.mark.parametrize("name", ["password", "passwordHash", "password_hash",
                                  "hashedPassword", "userPassword"])
def test_no_row_carries_a_credential_however_the_field_is_spelled(tmp_path, name):
    seed = _seed(tmp_path, [
        {"name": "id", "type": "uuid", "primaryKey": True},
        {"name": "email", "type": "email"},
        {"name": name, "type": "string"},
    ])
    rows = seed["nurses"]
    assert rows, "the rows still seed — an empty table is not the fix"
    for row in rows:
        assert name not in row, row
        # And nothing else quietly holds one either.
        assert not any(_is_credential_field(k) for k in row), row
    # The rest of the record is untouched: this leaves out one field, it does
    # not stop seeding the entity.
    assert rows[0]["email"] == "nurse1@example.com"


def test_a_column_that_merely_sounds_alike_keeps_its_value(tmp_path):
    """`salt` is a real column in a recipe app and `passes` in a gym one.
    Emptying them to fix a credential trades one broken app for another."""
    seed = _seed(tmp_path, [
        {"name": "id", "type": "uuid", "primaryKey": True},
        {"name": "salt", "type": "string"},
        {"name": "passes", "type": "int"},
        {"name": "passType", "type": "string"},
    ])
    row = seed["nurses"][0]
    assert row["salt"] == "Salt 1"
    assert row["passes"] == 1
    assert row["passType"] == "Pass Type 1"


def test_which_names_count_is_one_rule_with_no_exceptions():
    for name in ("password", "passwordHash", "password_hash", "PASSWORD",
                 "hashedPassword", "confirmPassword"):
        assert _is_credential_field(name), name
    for name in ("salt", "passes", "passType", "email", "name", "passport"):
        assert not _is_credential_field(name), name
