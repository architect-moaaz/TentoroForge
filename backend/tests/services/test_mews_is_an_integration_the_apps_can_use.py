"""Mews is an integration the apps can use, and every system an app declares
has a card in Settings → Integrations.

Three Case Management apps on forge-v3 declared a Mews integration and were
told to "set MEWS_ACCESS_TOKEN under Settings → Integrations" — where nothing
showed it: the list the settings page draws its cards from walked the
platform's registry alone, so no declared system ever had a card. And no
step could have signed a Mews call anyway: the Connector API reads its two
tokens and a client name from the JSON body, which the generic `auth`
(bearer, header, basic, query) cannot put there. The runtime half is
`templates/runtime/__tests__/a-step-reaches-mews-the-way-mews-reads-it`.
"""
from __future__ import annotations

import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal, InvalidTrigger, check_workflow_triggers
from services.declared_secrets import declared_keys
from services.node_config_specs import ConfigKey, all_providers, keys_for_provider

MEWS_APP = {"integrations": [
    {"id": "INT-001", "name": "Mews PMS Connector", "kind": "other", "provider": "mews", "status": "PROPOSED",
     "secretRefs": ["MEWS_CLIENT_TOKEN", "MEWS_ACCESS_TOKEN", "MEWS_ENTERPRISE_ID"]},
    {"id": "INT-002", "name": "Xero", "status": "APPROVED", "secretRefs": ["XERO_API_KEY"]},
]}


def test_mews_has_its_card_with_the_names_the_runtime_reads():
    assert "mews" in all_providers()
    keys = {k.key: k for k in keys_for_provider("mews")}
    assert set(keys) == {"MEWS_CLIENT_TOKEN", "MEWS_ACCESS_TOKEN", "MEWS_CLIENT", "MEWS_ENVIRONMENT"}
    assert keys["MEWS_CLIENT_TOKEN"].kind == keys["MEWS_ACCESS_TOKEN"].kind == "password"
    assert keys["MEWS_CLIENT_TOKEN"].required and keys["MEWS_ACCESS_TOKEN"].required
    assert keys["MEWS_ENVIRONMENT"].options == ("demo", "production") and keys["MEWS_ENVIRONMENT"].default == "demo"
    assert not any(k.platform_only for k in keys.values()), "the apps read them"
    from services.signed_services import SIGNED
    assert set(SIGNED["mews"]["keys"]) <= set(keys)


def test_an_apps_mews_names_are_on_the_mews_card_and_the_rest_on_its_own():
    got = [(k.provider, k.key) for k in declared_keys(MEWS_APP)]
    assert ("app:mews-p-m-s-connector", "MEWS_ACCESS_TOKEN") not in got, "one variable, one field: the Mews card's"
    assert ("app:mews-p-m-s-connector", "MEWS_ENTERPRISE_ID") in got
    assert ("app:xero", "XERO_API_KEY") in got


@pytest.mark.asyncio
async def test_the_list_the_settings_page_reads_has_every_declared_system(auth_client, org_id, monkeypatch):
    async def declared(db, org):
        return declared_keys(MEWS_APP)
    monkeypatch.setattr("services.declared_secrets.declared_keys_for_org", declared)
    rows = (await auth_client.get(f"/api/orgs/{org_id}/integrations")).json()
    have = {(r["provider"], r["key"]) for r in rows}
    assert {("mews", "MEWS_CLIENT_TOKEN"), ("mews", "MEWS_ACCESS_TOKEN"), ("app:xero", "XERO_API_KEY"),
            ("app:mews-p-m-s-connector", "MEWS_ENTERPRISE_ID")} <= have
    xero = next(r for r in rows if r["key"] == "XERO_API_KEY")
    assert xero["is_set"] is False and xero["label"] == "Xero — XERO_API_KEY"


def _flow(auth: dict, doc_integrations=MEWS_APP["integrations"]):
    cfg = {"actionType": "http_call", "url": "/api/connector/v1/configuration/get", "auth": auth}
    result = AgentResult(task_id="T", agent="workflow", proposals=[ArtifactProposal(
        section="workflows", natural_key="Pull rooms", body={"name": "Pull rooms", "trigger": {"kind": "manual"},
                                                             "steps": [{"key": "pull", "name": "Pull", "type": "action",
                                                                        "config": cfg}]})])
    return result, {"roles": [], "data": {"entities": []}, "integrations": doc_integrations}


def test_a_step_names_mews_by_its_provider_once_the_integration_is_declared():
    check_workflow_triggers(*_flow({"provider": "mews"}))
    with pytest.raises(InvalidTrigger, match="no integration has `provider: \"mews\"`"):
        check_workflow_triggers(*_flow({"provider": "mews"}, MEWS_APP["integrations"][1:]))
    with pytest.raises(InvalidTrigger, match="not a system the runtime signs for itself"):
        check_workflow_triggers(*_flow({"provider": "opera"}))


def test_the_agents_are_told_how_mews_is_reached():
    from services.blueprint.executors import NODE_TASKS
    from services.smith.connect_service import adapter_lines
    steps = NODE_TASKS["workflow_steps"]
    assert '`auth: {"provider": "mews"}`' in steps and "/api/connector/v1/" in steps
    assert "provider `mews`" in adapter_lines() and "MEWS_CLIENT_TOKEN, MEWS_ACCESS_TOKEN" in adapter_lines()


def test_the_runtime_suite_for_mews_is_run():
    from pathlib import Path
    suites = Path(__file__).resolve().parents[2] / "templates" / "runtime" / "__tests__"
    assert "a-step-reaches-mews-the-way-mews-reads-it" in (suites / "run-mews-tests.sh").read_text()


def test_a_config_key_is_still_a_plain_record():
    # The registry entry is the shape every other provider uses.
    assert isinstance(keys_for_provider("mews")[0], ConfigKey)
