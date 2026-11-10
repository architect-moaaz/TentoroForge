"""Test and Production: the two sides of a published app.

Publish sends an app to whichever side its switch is on (`Project.publish_target`):

* **Production** is the live app, as every publish was before this existed:
  Vercel production, the app's Neon database, its domains, its real data and
  the organisation's keys.
* **Test** never touches any of that. It is a Vercel *preview* deployment of
  the same project, at its own fixed address (`<app>-test.vercel.app`), on its
  own empty database inside the app's Neon project (`forge_test`, seeded with
  demo data), with its own settings: test payment keys or none (the payment
  stand-in takes over), email only to the organisation's own members, a
  "test version" ribbon and no search-engine indexing. Vercel runs scheduled
  jobs on production only, so the test side has none.

Promote sends exactly what Test runs to Production: a production deployment of
the test deployment's files, built with production's settings.
"""
from __future__ import annotations

import hashlib
from typing import Iterable

TEST = "test"
PRODUCTION = "production"
ENVIRONMENTS = (TEST, PRODUCTION)

#: The database the test side runs on, inside the app's own Neon project:
#: empty when made, so the build seeds demo data into it and nothing else.
TEST_DATABASE = "forge_test"

#: Keys that move real money. On the test side each is replaced by its test
#: twin when the organisation set one (Stripe test mode), and dropped
#: otherwise, so the app's payment stand-in takes over and nobody is charged.
#: The twins themselves never reach either side under their own names.
TEST_TWINS = {
    "STRIPE_SECRET_KEY": "STRIPE_TEST_SECRET_KEY",
    "STRIPE_PUBLISHABLE_KEY": "STRIPE_TEST_PUBLISHABLE_KEY",
    "STRIPE_WEBHOOK_SECRET": "STRIPE_TEST_WEBHOOK_SECRET",
}
#: Keys that reach real people outside the organisation and have no test twin:
#: never on the test side.
TEST_NEVER = ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER")


def normalise(environment: str | None) -> str:
    """"test"/"production" as written, or ValueError for anything else."""
    env = str(environment or "").strip().lower()
    if env not in ENVIRONMENTS:
        raise ValueError(f"publish to {TEST!r} or {PRODUCTION!r}, not {environment!r}")
    return env


def vercel_target(environment: str) -> str | None:
    """Vercel's deployment target: "production", or None for a preview."""
    return PRODUCTION if environment == PRODUCTION else None


def env_targets(environment: str) -> list[str]:
    """Which of Vercel's environments a setting is written for."""
    return ["production"] if environment == PRODUCTION else ["preview"]


def test_alias(project_name: str) -> str:
    """The test side's fixed address: the same every publish, and never one a
    production deploy moves (a manual alias is not a production domain)."""
    return f"{project_name[:52]}-test.vercel.app"


def integrations_for(environment: str, integrations: dict[str, str | None]) -> dict[str, str | None]:
    """The organisation's keys as each side gets them: production as stored
    (minus the test twins); test with money keys swapped for their twins or
    dropped, and people-reaching keys without a twin dropped."""
    twins = set(TEST_TWINS.values())
    if environment == PRODUCTION:
        return {k: v for k, v in integrations.items() if k not in twins}
    out = {k: v for k, v in integrations.items() if k not in twins and k not in TEST_TWINS and k not in TEST_NEVER}
    for live, twin in TEST_TWINS.items():
        if integrations.get(twin):
            out[live] = integrations[twin]
    return out


def side_settings(environment: str, *, test_recipients: Iterable[str] = ()) -> dict[str, str]:
    """What tells the app which side it is on, read by its runtime (the
    ribbon, robots, the email guard)."""
    if environment == PRODUCTION:
        return {"FORGE_ENVIRONMENT": PRODUCTION}
    people = sorted({str(e).strip().lower() for e in test_recipients if str(e or "").strip()})
    return {"FORGE_ENVIRONMENT": TEST, "FORGE_TEST_RECIPIENTS": ",".join(people)}


def source_digest(files: Iterable[dict]) -> str:
    """A fingerprint of what is shipped: every file's path and content sha."""
    h = hashlib.sha256()
    for f in sorted(files, key=lambda x: str(x.get("file"))):
        h.update(f"{f.get('file')}\0{f.get('sha')}\n".encode())
    return h.hexdigest()


__all__ = ["ENVIRONMENTS", "PRODUCTION", "TEST", "TEST_DATABASE", "TEST_NEVER", "TEST_TWINS", "env_targets",
           "integrations_for", "normalise", "side_settings", "source_digest", "test_alias", "vercel_target"]
