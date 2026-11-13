"""Web Push keys (VAPID) are generated per project, written beside the
app's other secrets, kept across a rebuild (a new pair orphans every
device), shipped by a publish when the deployment lacks them, and
settable on the platform (2026-10-12)."""
from __future__ import annotations

from pathlib import Path

from services.blueprint.assembly import _SECRET_KEYS, existing_secrets
from services.deploy.env_sync import build_deploy_env
from services.node_config_specs import NODE_CONFIG_SPECS, providers_used_by_plan
from services.push_keys import VAPID_KEYS, generate_vapid, is_public_key

ROOT = Path(__file__).resolve().parents[2]


def test_a_pair_is_the_shape_web_push_reads():
    pair = generate_vapid("mailto:ops@acme.test")
    assert set(pair) == set(VAPID_KEYS) and is_public_key(pair["VAPID_PUBLIC_KEY"]) and not is_public_key("nope")
    assert len(pair["VAPID_PRIVATE_KEY"]) == 43 and pair["VAPID_SUBJECT"] == "mailto:ops@acme.test"
    assert generate_vapid()["VAPID_PUBLIC_KEY"] != pair["VAPID_PUBLIC_KEY"]


def test_the_keys_survive_a_rebuild_and_an_old_app_gets_a_pair_once(tmp_path):
    (tmp_path / ".env.local").write_text("NEXTAUTH_SECRET=s\nVAPID_PUBLIC_KEY=pub\nVAPID_PRIVATE_KEY=priv\nVAPID_SUBJECT=mailto:x\n")
    found = existing_secrets(tmp_path)
    assert found["VAPID_PUBLIC_KEY"] == "pub" and all(k in _SECRET_KEYS for k in VAPID_KEYS)
    injector = (ROOT / "services/runtime_injector.py").read_text()
    assert "VAPID_PUBLIC_KEY={vapid[\"VAPID_PUBLIC_KEY\"]}" in injector
    assert "if not all(k in present for k in VAPID_KEYS):" in injector, "an app assembled before push existed gets a pair on its next assembly, once"


def test_a_publish_ships_the_pair_the_app_already_signs_with():
    env = build_deploy_env(integrations={"VAPID_SUBJECT": "mailto:org@acme.test"}, neon_url="postgres://n", vercel_url="", nextauth_secret="s",
                           app_secrets={"VAPID_PUBLIC_KEY": "pub", "VAPID_PRIVATE_KEY": "priv", "VAPID_SUBJECT": "mailto:app@acme.test"})
    assert env["VAPID_PUBLIC_KEY"] == "pub" and env["VAPID_PRIVATE_KEY"] == "priv"
    assert env["VAPID_SUBJECT"] == "mailto:org@acme.test", "the organisation's store wins"
    provider = (ROOT / "services/deploy/vercel_provider.py").read_text()
    assert '(*VAPID_KEYS, "SENSITIVE_ENCRYPTION_KEY"' in provider and "app_secrets=app_secrets" in provider


def test_the_platform_knows_the_keys_when_the_app_sends_push():
    assert [k.key for k in NODE_CONFIG_SPECS["__push__"]] == list(VAPID_KEYS)
    assert providers_used_by_plan({"mobile": {"push": True}, "workflows": []}) == ["push"]
    assert providers_used_by_plan({"mobile": {"push": False}, "workflows": []}) == []
