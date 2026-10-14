"""Smith sets when a process runs, pauses and resumes it, sets a deadline
that hands a late task on, and refuses a cadence the clock cannot keep
with what to say instead (2026-10-12)."""
from __future__ import annotations

import json

import pytest

from services.blueprint.service import BlueprintService
from services.smith import schedule_change as sch


class _Client:
    def __init__(self, answer: dict):
        self.answer = answer

    def __call__(self, *, system: str, user: str, schema: dict, **_):
        return json.dumps(self.answer)


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="a", name="Clinic", domain="health")
    s.doc["roles"] = [{"id": "ROLE-001", "name": "Nurse"}, {"id": "ROLE-002", "name": "Manager"}]
    s.doc["workflows"] = [
        {"id": "FLOW-001", "name": "Payment reminder", "status": "APPROVED", "trigger": {"kind": "manual"},
         "steps": [{"key": "start", "name": "Start", "type": "trigger", "config": {"type": "manual"}},
                   {"key": "done", "name": "Done", "type": "end", "config": {}}]},
        {"id": "FLOW-002", "name": "Approve leave", "status": "APPROVED", "trigger": {"kind": "manual"},
         "steps": [{"key": "start", "name": "Start", "type": "trigger", "config": {"type": "manual"}},
                   {"key": "sign", "name": "Sign off", "type": "approval", "config": {"assignType": "role", "assignTarget": "ROLE-002"}},
                   {"key": "done", "name": "Done", "type": "end", "config": {}}]},
    ]
    s.save()
    return s


def test_a_cadence_becomes_a_cron_the_clock_keeps(svc, tmp_path):
    out = sch.set_schedule(svc, str(tmp_path), workflow="payment reminder", change="every Monday at 9",
                           client=_Client({"cron": "0 9 * * 1", "timezone": "Asia/Dubai", "reading": "Mondays at 09:00"}))
    assert out["applied"] and "Mondays at 09:00" in out["diff_summary"]
    wf = BlueprintService.load(output_dir=tmp_path).doc["workflows"][0]
    assert wf["trigger"] == {"kind": "schedule", "cron": "0 9 * * 1", "timezone": "Asia/Dubai", "enabled": True,
                             "detail": "every Monday at 9"}


def test_a_cadence_the_clock_cannot_keep_is_refused_with_choices(svc, tmp_path):
    out = sch.set_schedule(svc, str(tmp_path), workflow="payment reminder", change="when it rains",
                           client=_Client({"cron": "", "timezone": "", "reading": "rain is not a time"}))
    assert not out["applied"] and "rain is not a time" in out["reason"] and out["options"]
    assert BlueprintService.load(output_dir=tmp_path).doc["workflows"][0]["trigger"] == {"kind": "manual"}


def test_pausing_and_resuming_flip_the_clocks_switch(svc, tmp_path):
    out = sch.pause_schedule(svc, str(tmp_path), workflow="payment reminder")
    assert not out["applied"] and "not run by the clock" in out["reason"]
    sch.set_schedule(svc, str(tmp_path), workflow="payment reminder", change="daily",
                     client=_Client({"cron": "0 9 * * *", "timezone": "", "reading": "daily at 09:00"}))
    assert sch.pause_schedule(svc, str(tmp_path), workflow="payment reminder")["applied"]
    assert BlueprintService.load(output_dir=tmp_path).doc["workflows"][0]["trigger"]["enabled"] is False
    assert sch.resume_schedule(svc, str(tmp_path), workflow="payment reminder")["applied"]
    assert BlueprintService.load(output_dir=tmp_path).doc["workflows"][0]["trigger"]["enabled"] is True


def test_a_deadline_lands_on_the_human_step_with_who_gets_it(svc, tmp_path):
    out = sch.set_deadline(svc, str(tmp_path), workflow="approve leave", change="2 days, then the manager",
                           client=_Client({"dueInMinutes": 2880, "escalateTo": "Manager", "reading": "2 days"}))
    assert out["applied"] and "Manager" in out["diff_summary"]
    step = BlueprintService.load(output_dir=tmp_path).doc["workflows"][1]["steps"][1]
    assert step["config"]["dueIn"] == 2880 and step["config"]["escalateTo"] == "ROLE-002", "the role's id; the projection writes its name"
    out = sch.set_deadline(svc, str(tmp_path), workflow="payment reminder", change="2 days", client=_Client({}))
    assert not out["applied"] and "no step a person does" in out["reason"]


def test_an_unknown_process_is_asked_about_not_guessed(svc, tmp_path):
    out = sch.run(str(tmp_path), "pause_schedule", workflow="the thing")
    assert not out["applied"] and "cannot tell which process" in out["reason"]


def test_the_verbs_are_smiths():
    from services.smith.verbs import REQUIRED_BY_VERB, VERB_EXAMPLES, VERB_HELP
    from services.smith4.verbs import PERFORM
    for v in sch.VERBS:
        assert v in REQUIRED_BY_VERB and v in VERB_HELP and v in VERB_EXAMPLES and v in PERFORM
