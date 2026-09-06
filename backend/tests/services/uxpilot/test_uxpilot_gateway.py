"""The UX Pilot gateway: read-only, argument names from the server's own
schemas, credentials by reference (§42, §98)."""
from __future__ import annotations

import pytest

from services.uxpilot.credentials import (
    EnvKeyResolver, UxPilotCredential, UxPilotCredentialError, looks_like_key, redact,
)
from services.uxpilot.gateway import ALLOWED_TOOLS, UxPilotGateway, UxPilotGatewayError


class _Tool:
    def __init__(self, name, props, required):
        self.name = name
        self.inputSchema = {"properties": props, "required": required}


class _Result:
    def __init__(self, text="", is_error=False, structured=None):
        self.isError = is_error
        self.structuredContent = structured
        self.content = [type("T", (), {"type": "text", "text": text})()]


class _Session:
    """A fake `ClientSession` the gateway drives through `_session`."""
    calls: list = []

    async def list_tools(self):
        return type("R", (), {"tools": [
            _Tool("get_page_context", {"pageId": {}}, ["pageId"]),
            _Tool("get_design", {"designId": {}, "includeHtml": {}}, ["designId"]),
        ]})()

    async def call_tool(self, name, arguments=None):
        _Session.calls.append((name, arguments))
        if name == "get_design":
            return _Result('{"design": {"id": "d1", "html": "<div>x</div>"}}')
        return _Result("boom", is_error=True)


@pytest.fixture
def gateway(monkeypatch):
    from contextlib import asynccontextmanager

    _Session.calls = []
    gw = UxPilotGateway(credential=UxPilotCredential(ref="UXPILOT_API_KEY"),
                        resolver=EnvKeyResolver(), min_interval_s=0)

    @asynccontextmanager
    async def fake_session():
        yield _Session()

    monkeypatch.setattr(gw, "_session", lambda: fake_session())
    return gw


def test_a_raw_key_is_refused_as_a_reference():
    with pytest.raises(UxPilotCredentialError, match="raw UX Pilot key"):
        UxPilotCredential(ref="ep_" + "a" * 30)
    assert looks_like_key("ep_" + "b" * 20) and not looks_like_key("UXPILOT_API_KEY")
    assert "ep_" not in redact("key ep_" + "c" * 20 + " leaked")


def test_only_read_tools_are_allowed():
    for spender in ("generate_design", "import_html_design", "run_ux_review", "publish_prototype"):
        assert spender not in ALLOWED_TOOLS


@pytest.mark.asyncio
async def test_a_credit_spending_tool_is_refused_before_any_call(gateway):
    with pytest.raises(UxPilotGatewayError) as exc:
        await gateway.call("generate_design", page="p")
    assert exc.value.kind == "not_allowed" and _Session.calls == []


@pytest.mark.asyncio
async def test_arguments_take_the_names_the_schema_uses(gateway):
    blocks = await gateway.call("get_design", design="d1", include_html=True)
    assert _Session.calls == [("get_design", {"designId": "d1", "includeHtml": True})]
    assert blocks and blocks[0]["type"] == "text"


@pytest.mark.asyncio
async def test_a_tool_error_is_classified_and_not_retried_forever(gateway):
    gateway.max_attempts = 2
    with pytest.raises(UxPilotGatewayError) as exc:
        await gateway.call("get_page_context", page="pg")
    assert exc.value.kind == "tool_error"
    assert len(_Session.calls) == 2


@pytest.mark.asyncio
async def test_a_missing_key_is_an_auth_error_naming_the_reference(monkeypatch):
    monkeypatch.delenv("UXPILOT_API_KEY", raising=False)
    gw = UxPilotGateway(credential=UxPilotCredential(ref="UXPILOT_API_KEY"), resolver=EnvKeyResolver())
    with pytest.raises(UxPilotGatewayError) as exc:
        gw._headers()
    assert exc.value.kind == "auth" and "UXPILOT_API_KEY" in exc.value.detail
