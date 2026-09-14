"""The runtime seed adds email-keyed rows beside the admin backstop.

``seedAdmin`` inserts admin@example.com before ``seedDomain`` runs, so the
users table always "has rows" by the time the declared logins are read from
seed.json. A table keyed by email must take those rows anyway, idempotently.
"""
from pathlib import Path

_SEED = Path(__file__).resolve().parents[2] / "templates" / "runtime" / "seed.ts"


def test_seed_inserts_email_keyed_rows_beside_existing():
    src = _SEED.read_text(encoding="utf-8")
    assert "onConflictDoNothing({ target: emailCol })" in src
    assert "keyed by email" in src
    # The skip still applies to tables without an email key.
    assert "already has ${c} rows — skipping insert" in src
