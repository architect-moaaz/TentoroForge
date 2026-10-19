"""When a change of main address republishes the app (so sign-in and links
use the new address), the Domains panel says so, follows the republish at
Vercel, and says when it is done or why it failed.
"""
from __future__ import annotations

from datetime import timedelta

from tests.services.test_an_app_answers_at_its_own_address import (  # noqa: F401 — the fixture is used
    Clock, FakeVercel, _no_real_probe, _project, _service, run)


class Building(FakeVercel):
    def __init__(self):
        super().__init__()
        self.state = "BUILDING"

    async def redeploy(self, project_name, deployment_id):
        self.redeploys.append(deployment_id)
        return {"id": "dpl_new"}

    async def get_deployment(self, deployment_id):
        assert deployment_id == "dpl_new"
        return {"readyState": self.state, "errorMessage": "Build failed: out of memory" if self.state == "ERROR" else None}


def _live_main(tmp_path):
    root = _project(tmp_path)
    fake = Building()
    fake.configured.add("app.acme.com")
    clock = Clock()
    svc = _service(root, fake, clock=clock)
    run(svc.connect("app.acme.com"))
    return svc, fake, clock


def test_a_new_main_address_shows_the_app_being_updated_until_vercel_says_ready(tmp_path):
    svc, fake, clock = _live_main(tmp_path)
    u = svc.view()["updating"]
    assert u["state"] == "building" and u["to"] == "https://app.acme.com" and "deployment" not in u
    clock.t += timedelta(seconds=40)
    assert run(svc.check_updating())["state"] == "building"
    fake.state = "READY"
    assert run(svc.check_updating())["state"] == "done"
    clock.t += timedelta(minutes=11)
    assert svc.view()["updating"] is None, "a finished update stops being shown"


def test_a_republish_vercel_cannot_build_says_why(tmp_path):
    svc, fake, clock = _live_main(tmp_path)
    fake.state = "ERROR"
    u = run(svc.check_updating())
    assert u["state"] == "failed" and "out of memory" in u["reason"]


def test_removing_the_main_address_shows_the_app_moving_back(tmp_path):
    svc, fake, clock = _live_main(tmp_path)
    fake.state = "READY"
    run(svc.check_updating())
    run(svc.remove("app.acme.com"))
    u = svc.view()["updating"]
    assert u["state"] == "building" and u["to"] == "https://aqua.vercel.app"


def test_nothing_is_shown_when_nothing_is_republished(tmp_path):
    root = _project(tmp_path)
    fake = Building()
    svc = _service(root, fake, clock=Clock())
    run(svc.connect("app.acme.com"))  # waiting for DNS: the main address has not moved
    assert svc.view()["updating"] is None
