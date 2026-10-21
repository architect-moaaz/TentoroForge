"""An application's spend stays with its organisation — when nobody asked for
the work in person, and after the application is deleted.

zoro-corp's total fell from $128 to $120 when q3lcz9t8 was deleted: its calls,
made before calls were stamped, found their organisation through the
application's row. $92.78 of Criterion Hospitality's went the same way with
pah7lhfz, unattended work never stamped (2026-10-21)."""
from __future__ import annotations

import json
import uuid

import pytest

from services import app_register, build_usage, spending


@pytest.fixture()
def ledger(tmp_path, monkeypatch):
    path = tmp_path / "usage.jsonl"
    monkeypatch.setenv("FORGE_USAGE_LOG", str(path))
    return path


def _call(project: str) -> None:
    build_usage.record_usage(project=project, agent="smith", model="claude-opus-5",
                             usage={"input_tokens": 100, "output_tokens": 50}, phase="change")


def test_unattended_work_takes_the_applications_organisation(ledger):
    app_register.remember({"pf1": {"org": "org-zoro", "owner": "nm@tentoro.ai", "name": "Personal Finance"}})
    _call("pf1")
    with build_usage.acting(user="someone@x.com", org="org-asked"):
        _call("pf1")
    rows = [json.loads(l) for l in ledger.read_text().splitlines()]
    assert rows[0]["org"] == "org-zoro" and rows[0]["user"] == "", "unattended: the app's organisation, nobody's name"
    assert rows[1]["org"] == "org-asked", "a person's own request keeps its own stamp"


def test_an_unknown_application_is_left_unstamped(ledger):
    _call("never-seen")
    assert json.loads(ledger.read_text())["org"] == ""


def test_the_register_keeps_what_it_knew_and_never_forgets():
    app_register.remember({"a": {"org": "o1", "owner": "x@y", "name": "A"}})
    app_register.remember({"a": {"org": "", "owner": "", "name": "A renamed"}, "b": {"org": "o2"}})
    apps = app_register.all_apps()
    assert apps["a"] == {"org": "o1", "owner": "x@y", "name": "A renamed"}
    assert apps["b"] == {"org": "o2"}


def test_a_deleted_applications_old_calls_are_still_its_organisations():
    rows = [{"ts": 1, "project": "q3lcz9t8", "agent": "a", "est_cost_usd": 8.15}]
    app_register.remember({"q3lcz9t8": {"org": "org-zoro", "owner": "", "name": "Old app"}})
    known = {"other": {"org": "org-x", "owner": "", "name": "Other"}}
    for app_id, info in app_register.all_apps().items():
        known.setdefault(app_id, {**info, "deleted": True})
    (row,) = spending.attributed(rows, known)
    assert row["org"] == "org-zoro"


@pytest.mark.asyncio
async def test_spend_lookups_remember_every_application_and_list_the_deleted(test_db, auth_client, org_id):
    from database import async_session
    from services.credits import projects_known
    made = (await auth_client.post(f"/api/orgs/{org_id}/projects", json={"name": "Kept"})).json()
    app_register.remember({"gone1": {"org": org_id, "owner": "o@x", "name": "Deleted one"}})
    async with async_session() as db:
        projects, names = await projects_known(db)
    short = next(k for k, v in projects.items() if v.get("name") == "Kept")
    assert app_register.lookup(short)["org"] == org_id, "a live application is written down"
    assert projects["gone1"]["deleted"] is True and projects["gone1"]["org"] == org_id
    assert names["project:gone1"] == "Deleted one"
    assert uuid.UUID(made["id"])
