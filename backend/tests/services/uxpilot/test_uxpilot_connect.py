"""Smith connects a UX Pilot page the way it connects a Figma file: it asks
for the page and a variable NAME, never the key (§42)."""
from __future__ import annotations

import pytest

from services.smith.understand_ask import _PROMPT
from services.smith.uxpilot_connect import find_in
from services.smith.verbs import REQUIRED_BY_VERB, VERB_HELP
from services.smith_session import SmithSession


def _session(output_dir="/tmp/does-not-exist"):
    s = SmithSession.__new__(SmithSession)
    s.output_dir = output_dir
    return s


def test_the_verb_needs_a_page_and_a_variable_name():
    assert REQUIRED_BY_VERB["connect_uxpilot"] == {"uxpilot_ref", "key_env"}
    assert "never the key" in VERB_HELP["connect_uxpilot"].lower()
    assert "connect_uxpilot" in _PROMPT and "ep_" in _PROMPT


def test_a_brief_naming_a_page_is_found_with_a_named_key():
    named = find_in("Build a shop admin. Use the UX Pilot page pg_42 as a reference; the key is UXPILOT_API_KEY.")
    assert named == {"provider": "uxpilot", "uxpilot_ref": "pg_42", "key_env": "UXPILOT_API_KEY", "treat_as": "reference"}
    url = find_in("Connect this UX Pilot page as the specification: https://uxpilot.ai/app/design/pg_9")
    assert url["uxpilot_ref"].endswith("pg_9") and url["treat_as"] == "specification"
    assert find_in("Build me a CRM") is None


def test_smith_asks_for_the_page_then_the_name_then_the_scope():
    s = _session()
    asked = s._connect_uxpilot({"uxpilot_ref": "", "key_env": ""})
    assert asked.status == "asked" and "Which UX Pilot page" in asked.answer
    asked = s._connect_uxpilot({"uxpilot_ref": "pg_42", "key_env": ""})
    assert asked.status == "asked" and "NAME" in asked.answer and "ep_" not in asked.answer
    bad = s._connect_uxpilot({"uxpilot_ref": "not a page!", "key_env": "UXPILOT_API_KEY"})
    assert bad.status == "needs_user"
    scope = s._connect_uxpilot({"uxpilot_ref": "pg_42", "key_env": "UXPILOT_API_KEY", "treat_as": ""})
    assert scope.status == "asked" and "SPECIFICATION" in scope.answer


def test_a_connect_failure_is_reported_not_raised(monkeypatch):
    import services.smith.uxpilot_connect as uc

    def boom(*a, **k):
        raise uc.UxPilotConnectError("UX Pilot auth: no key in UXPILOT_API_KEY")

    monkeypatch.setattr(uc, "connect", boom)
    out = _session()._connect_uxpilot({"uxpilot_ref": "pg_42", "key_env": "UXPILOT_API_KEY", "treat_as": "evidence"})
    assert out.status == "needs_user" and "UXPILOT_API_KEY" in out.answer


def test_uxpilot_is_a_provider_the_settings_page_can_render():
    from services.node_config_specs import all_providers, keys_for_provider

    assert "uxpilot" in all_providers()
    keys = {k.key: k for k in keys_for_provider("uxpilot")}
    assert keys["UXPILOT_API_KEY"].kind == "password" and keys["UXPILOT_API_KEY"].required
    assert keys["UXPILOT_MCP_URL"].default == "https://mcp.uxpilot.net/mcp"
