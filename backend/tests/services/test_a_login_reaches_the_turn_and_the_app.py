"""The account verbs end to end: the turn that runs them, and the app that
serves the setup link they hand out.

`services.smith.accounts` is tested on its own beside this. What is tested
here is the wiring, which is where a verb usually dies: classified but not
routed (the turn falls through to "I did not recognise that"), or routed but
with nowhere for its link to land (the middleware gates `/set-password`, so
the one visitor who certainly cannot sign in is sent to the sign-in).
"""

from __future__ import annotations

import json
import re

import pytest

from services.smith import accounts as acc


@pytest.fixture()
def project(tmp_path):
    (tmp_path / "app" / "src" / "db").mkdir(parents=True)
    return tmp_path


def _session(project, understanding: dict):
    from tests.services._front_door import SmithSession

    return SmithSession(project_id="p1", output_dir=str(project),
                        guards_fn=lambda *a, **kw: [],
                        understand_ask_fn=lambda m, ctx, **kw: understanding,
                        iteration_move_fn=lambda *a, **kw: None)


# ---------------------------------------------------------------------------
# the turn
# ---------------------------------------------------------------------------

def test_a_turn_gives_a_person_a_login(project):
    session = _session(project, {"verb": "add_login", "email": "dave@clinic.com",
                                 "person_name": "Dave Okafor", "role": "Ward Manager"})
    result = session.run_iteration(user_message="set up a login for dave@clinic.com")

    assert result.status == "resolved"
    assert "Dave Okafor" in result.answer and "/set-password?token=" in result.answer
    [entry] = acc.load(project)["accounts"]
    assert entry["email"] == "dave@clinic.com" and entry["status"] == "active"


def test_a_turn_without_the_address_asks_for_it_rather_than_inventing_one(project):
    """An account is identified by the address its person signs in with, and a
    made-up one locks them out of their own login."""
    session = _session(project, {"verb": "add_login", "email": ""})
    result = session.run_iteration(user_message="set up a login for Dave")

    assert result.status == "asked"
    assert result.answer == "What email address will they sign in with?"
    assert not acc.roster_path(project).exists()


def test_a_turn_resets_a_password_without_anyone_holding_one(project):
    acc.add(project, email="dave@clinic.com", name="Dave", app_root=str(project / "app"))
    session = _session(project, {"verb": "reset_login", "person": "Dave"})
    result = session.run_iteration(user_message="reset Dave's password")

    assert result.status == "resolved"
    assert "new password to set" in result.answer
    assert "password" not in json.dumps(acc.load(project)).lower()


def test_a_turn_that_cannot_find_the_person_says_who_it_knows(project):
    acc.add(project, email="dave@clinic.com", name="Dave", app_root=str(project / "app"))
    session = _session(project, {"verb": "remove_login", "person": "Sarah"})
    result = session.run_iteration(user_message="remove Sarah's login")

    assert result.status == "needs_user"
    assert "nobody who logs in is called “Sarah”" in result.answer
    assert acc.live(acc.load(project))[0]["email"] == "dave@clinic.com"


# ---------------------------------------------------------------------------
# the tools
# ---------------------------------------------------------------------------

def test_each_verb_is_a_tool_the_agent_can_dispatch():
    from services import smith_tools

    catalog = {t["name"] for t in smith_tools.TOOL_CATALOG}
    for name in ("add_login", "remove_login", "reset_login"):
        assert name in catalog, name
        assert name in smith_tools.READONLY_HANDLERS, name


def test_no_tool_offers_to_take_a_password(project):
    """There is no `password` argument anywhere, and one handed in is ignored
    rather than honoured: a tool call is written to the conversation log."""
    from services import smith_tools

    for tool in smith_tools.TOOL_CATALOG:
        if tool["name"].endswith("_login"):
            assert "password" not in tool["signature"], tool["name"]

    out = smith_tools.READONLY_HANDLERS["add_login"](
        str(project), {"email": "dave@clinic.com", "password": "Summer2026"})
    assert out["applied"] is True
    assert "Summer2026" not in json.dumps(acc.load(project))
    assert "Summer2026" not in out["diff_summary"]


def test_a_tool_with_nobody_named_says_what_it_needs(project):
    from services import smith_tools

    out = smith_tools.READONLY_HANDLERS["reset_login"](str(project), {})
    assert out["applied"] is False and "nobody named" in out["reason"]

    out = smith_tools.READONLY_HANDLERS["add_login"](str(project), {})
    assert out["applied"] is False and "no email address given" in out["reason"]


# ---------------------------------------------------------------------------
# where the link lands
# ---------------------------------------------------------------------------

def test_the_middleware_leaves_the_setup_page_open(tmp_path):
    """Gated, it would redirect the visitor holding a setup link to the
    sign-in they cannot complete — the same defect `/signup` had."""
    from services.blueprint.projection import project_middleware

    app_root = tmp_path / "app"
    app_root.mkdir()
    project_middleware({"pages": [{"id": "PAGE-001", "route": "/nurses",
                                   "access": "authenticated"}]}, app_root)
    written = (app_root / "src" / "middleware.ts").read_text("utf-8")

    matcher = re.search(r'matcher:\s*\[\s*"([^"]+)"', written)
    assert matcher, written
    assert "set-password" in matcher.group(1)
    # Beside the other two pages that cannot require a session.
    assert "login" in matcher.group(1) and "signup" in matcher.group(1)


def test_the_scaffold_middleware_leaves_it_open_too(tmp_path):
    """The projection is not always what runs: assembly ships the scaffold's
    middleware when no projection wrote one."""
    from pathlib import Path

    shipped = Path("templates/app-foundation/src/middleware.ts").read_text("utf-8")
    assert "set-password" in shipped


def test_the_app_is_given_the_invite_table_and_the_route_that_hashes(tmp_path):
    """Both halves of the only way an account gets a password other than
    sign-up. Without the route there is nowhere for a setup link to go."""
    from services.runtime_injector import _inject_account_setup

    (tmp_path / "src" / "db" / "schema").mkdir(parents=True)
    (tmp_path / "src" / "db" / "schema" / "index.ts").write_text(
        'export * from "./user";\n', "utf-8")

    written = _inject_account_setup(tmp_path)

    assert "src/db/schema/_forge_invites.ts" in written
    assert "src/app/api/auth/set-password/route.ts" in written
    # Drizzle resolves the schema through the barrel: a module nothing
    # re-exports is invisible to it and the table is in no migration.
    assert "_forge_invites" in (tmp_path / "src" / "db" / "schema" / "index.ts").read_text("utf-8")

    route = (tmp_path / "src" / "app" / "api" / "auth" / "set-password" / "route.ts").read_text("utf-8")
    assert "bcrypt.hash(password, 12)" in route      # the algorithm auth.ts verifies
    assert "createHash(\"sha256\")" in route          # only a digest is ever compared
    assert "usedAt: new Date()" in route              # and a link works once

    table = (tmp_path / "src" / "db" / "schema" / "_forge_invites.ts").read_text("utf-8")
    # The token lives here and not on the users row, every scalar column of
    # which auth.ts copies into the session — and no credential lives here.
    assert 'tokenHash: text("token_hash")' in table
    assert 'password: text(' not in table


def test_the_platform_still_refuses_a_workflow_that_writes_a_credential():
    """This work did not open a second door. Account creation goes through the
    platform's own hashing path; a workflow writing the column is still
    refused at the author (rule `platform-credential-write`)."""
    from services.blueprint.functional_completeness import platform_write_findings

    [finding] = platform_write_findings({"workflows": [{
        "id": "FLOW-001", "name": "Create Account", "status": "ACTIVE",
        "steps": [{"key": "insert", "type": "action",
                   "config": {"actionType": "db_insert", "table": "users",
                              "values": {"email": "{{e}}", "passwordHash": "{{p}}"}}}]}]})
    assert finding["rule"] == "platform-credential-write"
