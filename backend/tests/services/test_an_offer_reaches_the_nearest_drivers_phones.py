"""A ride that starts searching reaches the drivers NEAREST to its pickup, on their phones, even with the app closed.

The pieces: the phone registers an Expo push token (`forge_device_tokens`, `/api/push/device`); the push module sends to a
person's phones through Expo as well as their browsers; the live fleet says who is on duty and where; a `send_notification`
step with `nearest` alerts the closest few; and Smith is taught to write that step, and refused when it cannot work."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal, InvalidMobile, check_mobile
from services.blueprint.executors import NODE_TASKS

BACKEND = Path(__file__).resolve().parents[2]
RUNTIME = BACKEND / "templates" / "runtime"


def _flow(nearest):
    return ArtifactProposal(section="workflows", natural_key="Offer the ride", body={
        "name": "Offer the ride", "steps": [{"id": "s1", "type": "action", "config": {
            "actionType": "send_notification", "channels": ["in_app", "push"], "nearest": nearest}}]})


def _check(nearest, doc=None):
    doc = {"mobile": {"push": True}, "data": {"entities": [{"name": "Driver"}, {"name": "Ride"}]}, **(doc or {})}
    check_mobile(AgentResult(task_id="T", agent="workflow", proposals=[_flow(nearest)]), doc)


def test_a_nearest_step_that_can_work_is_accepted():
    _check({"entity": "Driver", "from": "{{entity.pickupLocation}}", "limit": 5, "maxKm": 15})
    _check({"entity": "Driver", "from": "{{entity.pickupLocation}}"})


def test_a_nearest_step_that_cannot_work_is_refused_in_words():
    for bad, said in (
        ({"from": "{{entity.pickupLocation}}"}, "nearest.entity"),
        ({"entity": "Pilot", "from": "{{entity.pickupLocation}}"}, "not an entity"),
        ({"entity": "Driver"}, "nearest.from"),
        ({"entity": "Driver", "from": "x", "limit": 0}, "nearest.limit"),
        ({"entity": "Driver", "from": "x", "maxKm": -3}, "nearest.maxKm"),
        ("the nearest five", "an object"),
    ):
        with pytest.raises(InvalidMobile) as e:
            _check(bad)
        assert said in str(e.value), (bad, str(e.value))


def test_a_nearest_step_still_needs_push_turned_on_for_its_push_channel():
    with pytest.raises(InvalidMobile) as e:
        _check({"entity": "Driver", "from": "x"}, {"mobile": {"push": False}})
    assert "mobile.push" in str(e.value)


def test_smith_is_taught_to_offer_work_to_whoever_is_nearest():
    text = NODE_TASKS["workflow_steps"]
    assert "TELL WHOEVER IS NEAREST" in text and "nearest" in text and "Do NOT name a `recipient`" in text


def test_the_contract_knows_the_nearest_setting():
    import json
    schema = json.loads((BACKEND / "contracts" / "blueprint.schema.json").read_text(encoding="utf-8"))
    flat = json.dumps(schema)
    assert '"nearest"' in flat and '"ttlSeconds"' in flat


def test_every_app_gets_the_phone_side_of_push():
    from services.smith import sync_app
    shipped = {rel for _tmpl, rel in sync_app.AUTH_ROUTES}
    assert {"src/app/api/push/device/route.ts", "src/db/schema/_forge_device_tokens.ts", "src/lib/expo-push.ts"} <= shipped
    assert "tracking" in sync_app.ENGINE_DIRS_WHERE_PRESENT         # an app that tracks keeps the fleet read current
    assert "tracking" not in sync_app.ENGINE_DIRS                   # but one that does not is not handed its sign-in modules
    assert sync_app._runtime_modules()["lib/expo-push"] == "expo-push.ts"
    for _tmpl, _rel in sync_app.AUTH_ROUTES:
        assert (RUNTIME / _tmpl).is_file(), _tmpl
    from services import runtime_injector
    code = Path(runtime_injector.__file__).read_text(encoding="utf-8")
    assert "forge-device-tokens.schema.ts" in code and "expo-push.ts" in code and "api-push/device/route.ts" in code


def test_a_phone_registers_only_a_real_expo_token_and_forgets_only_its_own():
    route = (RUNTIME / "api-push" / "device" / "route.ts").read_text(encoding="utf-8")
    assert "validExpoToken(token)" in route and "MOBILE.push" in route and "onConflictDoUpdate" in route
    assert "eq(forgeDeviceTokens.userId, String(user.id))" in route            # a person cannot forget someone else's phone


def test_the_workflow_step_alerts_the_people_it_found_and_not_a_named_recipient():
    flow = (RUNTIME / "workflows" / "index.ts").read_text(encoding="utf-8")
    assert "whoIsNear(near" in flow and "fleetOnDuty(fleetKey(kind))" in flow
    assert "nearIds ? { userIds: nearIds }" in flow


@pytest.mark.skipif(shutil.which("node") is None, reason="node is needed to run the shipped code")
def test_the_phone_logic_runs_under_node():
    run = subprocess.run(["node", "--experimental-strip-types", "--no-warnings",
                          str(RUNTIME / "__tests__" / "an-alert-reaches-the-nearest-phones-through-expo.test.mts")],
                         capture_output=True, text=True, timeout=120)
    if "unknown option" in run.stderr or "bad option" in run.stderr:
        pytest.skip("this node cannot strip types")
    assert run.returncode == 0, run.stdout[-2500:] + run.stderr[-2500:]
