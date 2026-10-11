"""The integrations agent has a prompt of its own (it ran on a fallback
sentence before), is told the adapters the runtime has, and is refused
for a `serves` nothing carries, a value where a name belongs, or an
`inbound` that cannot be verified (2026-10-12)."""
from __future__ import annotations

import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal, InvalidIntegration, check_integrations
from services.blueprint.executors import NODE_TASKS, integration_adapters
from services.blueprint.orchestrator import DAG


def _integration(**body) -> AgentResult:
    return AgentResult(task_id="T", agent="integration", proposals=[ArtifactProposal(
        section="integrations", natural_key=body.get("name", "x"), body={"kind": "other", "provider": "", "secretRefs": [], **body})])


def test_the_agent_is_told_what_the_runtime_can_carry():
    assert "secretRefs" in NODE_TASKS["integrations"] and "`inbound`" in NODE_TASKS["integrations"]
    lines = integration_adapters("integrations")
    assert "send_email" in lines and "resend" in lines and "RESEND_API_KEY" in lines
    assert integration_adapters("workflows") == ""
    assert "integrations" in DAG["workflows"].depends_on, "a workflow may name an integration's secret or event"


def test_a_carried_action_uses_its_adapters_provider_and_names():
    check_integrations(_integration(name="Mail", kind="email", provider="resend", serves="send_email",
                                    secretRefs=["RESEND_API_KEY", "FORGE_EMAIL_FROM"]), {})
    check_integrations(_integration(name="Xero", provider="xero", secretRefs=["XERO_API_KEY"]), {})
    with pytest.raises(InvalidIntegration, match="names an action with an adapter"):
        check_integrations(_integration(name="Pay", provider="stripe", serves="take_payment", secretRefs=["STRIPE_KEY"]), {})
    with pytest.raises(InvalidIntegration, match="is carried by"):
        check_integrations(_integration(name="Mail", provider="mailchimp", serves="send_email", secretRefs=["MC_KEY"]), {})
    with pytest.raises(InvalidIntegration, match="add RESEND_API_KEY"):
        check_integrations(_integration(name="Mail", provider="resend", serves="send_email", secretRefs=["FORGE_EMAIL_FROM"]), {})


def test_a_value_where_a_name_belongs_is_refused():
    with pytest.raises(InvalidIntegration, match="holds NAMES"):
        check_integrations(_integration(name="Xero", secretRefs=["xero api key"]), {})
    with pytest.raises(InvalidIntegration, match="holds NAMES"):
        check_integrations(_integration(name="Pay", secretRefs=["sk_live_" "4eC39HqLyjWDarjtT1zdp7dc"]), {})


def test_an_inbound_names_its_secret_and_its_events():
    check_integrations(_integration(name="Shop", provider="shop", secretRefs=["SHOP_WEBHOOK_SECRET"],
                                    inbound={"events": ["order.paid"], "verify": "hmac_sha256", "signingSecretRef": "SHOP_WEBHOOK_SECRET"}), {})
    with pytest.raises(InvalidIntegration, match="names one of `secretRefs`"):
        check_integrations(_integration(name="Shop", secretRefs=["SHOP_KEY"], inbound={"events": ["order.paid"], "signingSecretRef": "OTHER"}), {})
    with pytest.raises(InvalidIntegration, match="lists the events"):
        check_integrations(_integration(name="Shop", secretRefs=["SHOP_KEY"], inbound={"events": [], "signingSecretRef": "SHOP_KEY"}), {})
