"""Adding, removing and resetting the people who log into a generated app.

"Set up logins for my six staff" and "reset Dave's password" were dead ends:
`edit_access` changes what a ROLE may do, and nothing could create, retire or
restore one PERSON's account — so an application whose roles were perfectly
modelled still had exactly one login, the seeded administrator.

Two properties are load-bearing and each has its own test below:

  * NO PLAINTEXT CREDENTIAL, ANYWHERE. Smith mints a one-time setup link and
    keeps only its digest; the person chooses their own password at a platform
    route that hashes it. §97 makes `users` a platform table and a workflow
    writing `password`/`passwordHash` is refused at the author, for the same
    reason: the column holds a bcrypt hash, so anything else written there is
    a password nobody can log in with.
  * NOT A BLUEPRINT CHANGE. People are data, not definition. Recorded in the
    document, an `undo` of an unrelated change would silently re-admit someone
    who had been removed.
"""

from __future__ import annotations

import json

import pytest

from services.smith import accounts as acc


@pytest.fixture()
def project(tmp_path):
    """An output_dir with an app tree, the shape Smith is handed."""
    (tmp_path / "app" / "src" / "db").mkdir(parents=True)
    return tmp_path


def _roster(project) -> dict:
    return json.loads(acc.roster_path(project).read_text("utf-8"))


def _projected(project) -> dict:
    return json.loads((project / "app" / acc.PROJECTED_RELATIVE).read_text("utf-8"))


# ---------------------------------------------------------------------------
# adding
# ---------------------------------------------------------------------------

def test_a_person_gets_a_login_and_a_link_to_set_their_own_password(project):
    out = acc.add(project, email="Dave@Clinic.com", name="Dave Okafor",
                  role="Ward Manager", app_root=str(project / "app"))

    [entry] = _roster(project)["accounts"]
    assert entry["email"] == "dave@clinic.com"     # an address is not case-sensitive
    assert entry["name"] == "Dave Okafor"
    assert entry["role"] == "Ward Manager"
    assert entry["status"] == "active"
    assert entry["log"][-1]["did"] == "added"
    # The invite is what the seed turns into a pending password setup.
    assert entry["invite"]["purpose"] == "invite"
    assert entry["invite"]["issue"].startswith("INV-")
    # And the link is shown once, to be sent to the person.
    assert out["token"] and out["token"] in acc.setup_link(out["token"])


def test_the_setup_token_is_never_written_down_anywhere(project):
    """Only its digest is kept, so neither the project nor a copy of the
    database is a way into someone's account."""
    import hashlib

    out = acc.add(project, email="dave@clinic.com", app_root=str(project / "app"))
    token = out["token"]

    ledger = acc.roster_path(project).read_text("utf-8")
    projected = (project / "app" / acc.PROJECTED_RELATIVE).read_text("utf-8")
    assert token not in ledger and token not in projected
    digest = hashlib.sha256(token.encode()).hexdigest()
    assert digest in ledger and digest in projected


def test_no_password_is_asked_for_held_or_said(project):
    """There is nowhere in this contract to put one, on purpose."""
    out = acc.add(project, email="dave@clinic.com", app_root=str(project / "app"))
    said = acc.summary_of(out)
    ledger = acc.roster_path(project).read_text("utf-8").lower()

    assert "password" not in json.dumps(_roster(project)["accounts"]).lower()
    assert "passwordhash" not in ledger
    # What the owner is told instead: a link, and that its holder chooses.
    assert "choose their own password" in said
    assert "I never see it" in said


def test_an_email_is_what_identifies_an_account(project):
    with pytest.raises(acc.AccountsError) as refused:
        acc.add(project, email="Dave", app_root=str(project / "app"))
    assert "not an email address" in str(refused.value)
    # Nothing was written: a refusal changes nothing.
    assert not acc.roster_path(project).exists()

    with pytest.raises(acc.AccountsError) as empty:
        acc.add(project, email="", app_root=str(project / "app"))
    assert "email address they will sign in with" in str(empty.value)


def test_adding_someone_who_can_already_log_in_offers_the_reset_instead(project):
    acc.add(project, email="dave@clinic.com", app_root=str(project / "app"))
    with pytest.raises(acc.AccountsError) as refused:
        acc.add(project, email="dave@clinic.com", app_root=str(project / "app"))
    said = str(refused.value)
    assert "can already log in" in said and "reset dave@clinic.com" in said
    # And the first person's pending link was not replaced behind their back.
    assert len(_roster(project)["accounts"]) == 1


def test_the_seeded_administrator_already_exists(project):
    with pytest.raises(acc.AccountsError) as refused:
        acc.add(project, email=acc.SEEDED_ADMIN, app_root=str(project / "app"))
    assert "already exists" in str(refused.value)


# ---------------------------------------------------------------------------
# naming a person
# ---------------------------------------------------------------------------

def test_a_person_is_named_by_their_address_or_the_name_they_were_added_under(project):
    acc.add(project, email="dave@clinic.com", name="Dave Okafor", app_root=str(project / "app"))
    roster = acc.load(project)

    for said in ("dave@clinic.com", "DAVE@clinic.com", "Dave Okafor", "dave"):
        assert acc.resolve(roster, said)["email"] == "dave@clinic.com", said


def test_two_daves_is_a_question_not_a_guess(project):
    """Picking one resets the wrong person's password."""
    acc.add(project, email="dave.o@clinic.com", name="Dave Okafor", app_root=str(project / "app"))
    acc.add(project, email="dave.s@clinic.com", name="Dave Singh", app_root=str(project / "app"))

    with pytest.raises(acc.AccountsError) as refused:
        acc.resolve(acc.load(project), "Dave")
    said = str(refused.value)
    assert "matches 2" in said
    assert "dave.o@clinic.com" in said and "dave.s@clinic.com" in said
    assert "Say which by email address" in said


def test_a_name_nobody_logs_in_under_is_said_with_the_names_that_do(project):
    acc.add(project, email="dave@clinic.com", name="Dave Okafor", app_root=str(project / "app"))
    with pytest.raises(acc.AccountsError) as refused:
        acc.resolve(acc.load(project), "Sarah")
    assert "nobody who logs in is called “Sarah”" in str(refused.value)
    assert "Dave Okafor (dave@clinic.com)" in str(refused.value)


def test_before_anyone_has_a_login_that_is_what_is_said(project):
    with pytest.raises(acc.AccountsError) as refused:
        acc.resolve(acc.load(project), "Dave")
    assert "nobody has been given a login yet" in str(refused.value)


# ---------------------------------------------------------------------------
# removing
# ---------------------------------------------------------------------------

def test_removing_someone_deactivates_the_account_and_keeps_their_work(project):
    acc.add(project, email="sarah@clinic.com", name="Sarah", app_root=str(project / "app"))
    out = acc.remove(project, person="Sarah", app_root=str(project / "app"))

    [entry] = _roster(project)["accounts"]
    assert entry["status"] == "removed"
    # A LINK IN AN INBOX IS A WAY IN: setting a password activates an account.
    assert entry["invite"] is None
    assert entry["log"][-1]["did"] == "removed"
    assert acc.live(acc.load(project)) == []

    said = acc.summary_of(out)
    assert "can no longer sign in" in said
    assert "deactivated rather than deleted" in said
    assert "setup link they were sent has been cancelled" in said


def test_the_account_that_makes_the_app_loginable_cannot_be_removed(project):
    """The seed re-creates it on every start, so a removal would not even hold."""
    acc.save(project, {"accounts": [{"email": acc.SEEDED_ADMIN, "status": "active"}]})
    with pytest.raises(acc.AccountsError) as refused:
        acc.remove(project, person=acc.SEEDED_ADMIN, app_root=str(project / "app"))
    said = str(refused.value)
    assert "lock everyone out" in said and "Reset it instead" in said


def test_removing_someone_already_removed_says_so(project):
    acc.add(project, email="sarah@clinic.com", app_root=str(project / "app"))
    acc.remove(project, person="sarah@clinic.com", app_root=str(project / "app"))
    with pytest.raises(acc.AccountsError) as refused:
        acc.remove(project, person="sarah@clinic.com", app_root=str(project / "app"))
    assert "cannot sign in already" in str(refused.value)


def test_someone_removed_can_be_given_a_login_again(project):
    acc.add(project, email="sarah@clinic.com", name="Sarah", app_root=str(project / "app"))
    acc.remove(project, person="Sarah", app_root=str(project / "app"))
    out = acc.add(project, email="sarah@clinic.com", app_root=str(project / "app"))

    [entry] = _roster(project)["accounts"]      # the same account, not a second one
    assert entry["status"] == "active"
    assert entry["invite"]["issue"] == out["account"]["invite"]["issue"]
    assert [e["did"] for e in entry["log"]] == ["added", "removed", "re-added"]


# ---------------------------------------------------------------------------
# resetting
# ---------------------------------------------------------------------------

def test_a_reset_issues_a_fresh_link_and_retires_the_old_one(project):
    added = acc.add(project, email="dave@clinic.com", name="Dave", app_root=str(project / "app"))
    first = _roster(project)["accounts"][0]["invite"]

    out = acc.reset(project, person="Dave", app_root=str(project / "app"))
    second = _roster(project)["accounts"][0]["invite"]

    assert second["issue"] != first["issue"]          # a new issuance
    assert second["tokenHash"] != first["tokenHash"]  # a different link
    assert out["token"] != added["token"]
    assert second["purpose"] == "reset"
    assert _roster(project)["accounts"][0]["log"][-1]["did"] == "reset"

    said = acc.summary_of(out)
    assert "has a new password to set" in said
    assert "works once" in said and f"{acc.INVITE_DAYS} days" in said


def test_resetting_someone_who_was_removed_points_at_adding_them_back(project):
    acc.add(project, email="sarah@clinic.com", app_root=str(project / "app"))
    acc.remove(project, person="sarah@clinic.com", app_root=str(project / "app"))
    with pytest.raises(acc.AccountsError) as refused:
        acc.reset(project, person="sarah@clinic.com", app_root=str(project / "app"))
    assert "was removed, so there is no password to reset" in str(refused.value)


# ---------------------------------------------------------------------------
# what reaches the application
# ---------------------------------------------------------------------------

def test_the_seed_is_given_exactly_what_it_reads(project):
    """`seedAccounts` in src/db/seed.ts reads these keys and no others."""
    acc.add(project, email="dave@clinic.com", name="Dave", role="Nurse",
            app_root=str(project / "app"))
    [entry] = _projected(project)["accounts"]

    assert set(entry) >= {"email", "name", "role", "status", "invite"}
    assert set(entry["invite"]) == {"issue", "tokenHash", "purpose", "expiresAt"}


def test_a_rebuilt_app_tree_gets_the_roster_back(project):
    """The roster is a project ledger, so nothing in the Blueprint carries it
    into a freshly assembled tree — this is what does."""
    acc.add(project, email="dave@clinic.com", app_root=str(project / "app"))
    (project / "app" / acc.PROJECTED_RELATIVE).unlink()

    assert acc.project(project, project / "app") == [str(acc.PROJECTED_RELATIVE)]
    assert _projected(project)["accounts"][0]["email"] == "dave@clinic.com"


def test_an_unreadable_roster_stops_the_change_rather_than_emptying_it(project):
    acc.roster_path(project).parent.mkdir(parents=True, exist_ok=True)
    acc.roster_path(project).write_text("{not json", "utf-8")
    with pytest.raises(acc.AccountsError) as refused:
        acc.add(project, email="dave@clinic.com", app_root=str(project / "app"))
    assert "could not read the list of people who log in" in str(refused.value)


# ---------------------------------------------------------------------------
# the link the owner is given
# ---------------------------------------------------------------------------

def test_the_link_is_absolute_when_the_app_says_where_it_answers(project):
    (project / "app" / ".env.local").write_text(
        "DATABASE_URL=postgresql://x\nNEXTAUTH_URL=http://localhost:3217/\n", "utf-8")
    out = acc.run(str(project), "add_login", email="dave@clinic.com")

    assert "http://localhost:3217/set-password?token=" in out["diff_summary"]


def test_without_that_the_path_is_given_and_said_to_be_a_path(project):
    out = acc.run(str(project), "add_login", email="dave@clinic.com")
    assert "`/set-password?token=" in out["diff_summary"]
    assert "after your application's own address" in out["diff_summary"]


def test_it_is_said_when_the_change_takes_effect(project):
    """The next start. A login written into the project is a login that
    survives the redeploy that rebuilds the database."""
    out = acc.run(str(project), "add_login", email="dave@clinic.com")
    assert "next time the application starts" in out["diff_summary"]
    assert "survives a redeploy" in out["diff_summary"]


# ---------------------------------------------------------------------------
# the shape a turn and a tool need
# ---------------------------------------------------------------------------

def test_the_run_shape_is_the_one_every_other_verb_returns(project):
    out = acc.run(str(project), "add_login", email="dave@clinic.com", name="Dave")
    assert out["applied"] is True
    assert out["edited_paths"] == [str(acc.PROJECTED_RELATIVE)]
    assert out["reason"] == "" and out["did"] == "added"
    assert out["email"] == "dave@clinic.com"

    refused = acc.run(str(project), "remove_login", person="nobody@nowhere.com")
    assert refused["applied"] is False
    assert refused["edited_paths"] == []
    assert "nobody who logs in" in refused["reason"]


def test_a_verb_this_module_does_not_serve_is_said_to_be_one(project):
    out = acc.run(str(project), "rename_login", person="Dave")
    assert out["applied"] is False and "not something I do to a login" in out["reason"]


# ---------------------------------------------------------------------------
# not a Blueprint change
# ---------------------------------------------------------------------------

def test_an_undo_of_something_else_does_not_re_admit_someone_removed(project):
    """THE REASON THE ROSTER IS NOT IN THE DOCUMENT. Versioned beside the
    definition, undoing an unrelated change would hand a removed person their
    account back — silently, and with no way for anyone to notice."""
    from services.blueprint.service import BlueprintService
    from services.smith import revert as rv

    svc = BlueprintService.create(output_dir=project, app_id="t", name="Roster", domain="health")
    svc.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Nurse", "table": "nurses",
                                     "fields": [{"name": "id", "type": "uuid", "primaryKey": True}]}]}
    svc.save()

    acc.add(project, email="sarah@clinic.com", name="Sarah", app_root=str(project / "app"))
    acc.remove(project, person="Sarah", app_root=str(project / "app"))

    before = svc.snapshot()
    svc.doc["data"]["entities"][0]["fields"].append({"name": "phone", "type": "string"})
    svc.validate()
    svc.commit(user_request="add Nurse.phone", smith_interpretation="add a phone", before=before)
    rv.revert(svc, app_root=str(project / "app"))

    assert acc.load(project)["accounts"][0]["status"] == "removed"
    assert acc.live(acc.load(project)) == []


def test_giving_someone_a_login_changes_nothing_about_the_definition(project):
    from services.blueprint.service import BlueprintService

    svc = BlueprintService.create(output_dir=project, app_id="t", name="Roster", domain="health")
    svc.save()
    before = json.dumps(svc.doc, sort_keys=True)

    acc.add(project, email="dave@clinic.com", app_root=str(project / "app"))

    after = BlueprintService.load(output_dir=str(project)).doc
    assert json.dumps(after, sort_keys=True) == before
    # No version, no change-history entry: an account is not a change to what
    # the application IS.
    assert after.get("version") == svc.doc.get("version")
    assert len(after.get("changeHistory") or []) == 0
