"""§98 — the controlled hop: allowed operations, auth, retries, logging."""
import asyncio

import pytest

from services.figma.credentials import FigmaCredential, FigmaCredentialError
from services.figma.gateway import (
    ALLOWED_TOOLS,
    FigmaGateway,
    FigmaGatewayError,
    _blocks_of,
)


class StubResolver:
    def __init__(self, token="figd_stub_token_value_0123456789abcdef"):
        self.token = token
        self.calls = 0

    def resolve(self, ref):
        self.calls += 1
        if self.token is None:
            raise FigmaCredentialError(f"no Figma token for {ref!r}")
        return self.token


def gateway(**kw):
    kw.setdefault("credential", FigmaCredential(ref="FIGMA_PAT"))
    kw.setdefault("resolver", StubResolver())
    kw.setdefault("min_interval_s", 0)
    return FigmaGateway(**kw)


def run(coro):
    return asyncio.run(coro)


# -- allowed operations ----------------------------------------------------

def test_write_tools_are_not_allowed():
    """The user connects a file as a reference; nothing here may edit it."""
    for tool in ("create_new_file", "use_figma", "upload_assets", "add_code_connect_map"):
        assert tool not in ALLOWED_TOOLS


def test_disallowed_tool_raises_rather_than_returning_empty():
    gw = gateway()
    with pytest.raises(FigmaGatewayError) as exc:
        run(gw.call("create_new_file", file_key="AbcDef123456"))
    assert exc.value.kind == "not_allowed"


def test_disallowed_tool_never_resolves_the_secret():
    resolver = StubResolver()
    gw = gateway(resolver=resolver)
    with pytest.raises(FigmaGatewayError):
        run(gw.call("use_figma", file_key="AbcDef123456"))
    assert resolver.calls == 0


def test_missing_file_key_is_a_config_error():
    with pytest.raises(FigmaGatewayError) as exc:
        run(gateway().call("get_metadata", file_key=""))
    assert exc.value.kind == "config"


# -- auth ------------------------------------------------------------------

def test_remote_endpoint_sends_bearer_token():
    gw = gateway(endpoint="https://mcp.figma.com/mcp")
    assert gw._headers()["Authorization"].startswith("Bearer figd_")


def test_local_dev_mode_sends_no_credential():
    """Dev Mode authenticates as the signed-in desktop user; putting a token
    on a localhost wire buys nothing and risks a log."""
    gw = gateway(endpoint="http://127.0.0.1:3845/mcp")
    assert gw._headers() == {}


def test_unresolvable_secret_is_an_auth_error():
    gw = gateway(resolver=StubResolver(token=None))
    with pytest.raises(FigmaGatewayError) as exc:
        gw._headers()
    assert exc.value.kind == "auth"


# -- retries (§103) --------------------------------------------------------

def test_transport_failure_retries_then_raises(monkeypatch):
    attempts = []

    async def boom(self, tool, args):
        attempts.append(tool)
        raise FigmaGatewayError("unreachable", "connection reset")

    monkeypatch.setattr(FigmaGateway, "_invoke", boom)
    gw = gateway(max_attempts=3)
    with pytest.raises(FigmaGatewayError) as exc:
        run(gw.call("get_metadata", file_key="AbcDef123456"))
    assert exc.value.kind == "unreachable"
    assert len(attempts) == 3


def test_auth_failure_does_not_retry(monkeypatch):
    """Retrying a rejected token rejects it again and spends the rate limit."""
    attempts = []

    async def boom(self, tool, args):
        attempts.append(tool)
        raise FigmaGatewayError("auth", "401")

    monkeypatch.setattr(FigmaGateway, "_invoke", boom)
    with pytest.raises(FigmaGatewayError):
        run(gateway(max_attempts=3).call("get_metadata", file_key="AbcDef123456"))
    assert len(attempts) == 1


def test_retry_succeeds_on_second_attempt(monkeypatch):
    state = {"n": 0}

    async def flaky(self, tool, args):
        state["n"] += 1
        if state["n"] == 1:
            raise FigmaGatewayError("timeout", "slow")
        return [{"type": "text", "text": "{}"}]

    monkeypatch.setattr(FigmaGateway, "_invoke", flaky)
    gw = gateway(max_attempts=2)
    assert run(gw.call("get_metadata", file_key="AbcDef123456")) == [
        {"type": "text", "text": "{}"}
    ]


# -- logging (§98) and secret isolation (§42) -------------------------------

def test_calls_are_recorded_without_the_token(monkeypatch):
    async def ok(self, tool, args):
        return [{"type": "text", "text": "{}"}]

    monkeypatch.setattr(FigmaGateway, "_invoke", ok)
    gw = gateway()
    run(gw.call("get_metadata", file_key="AbcDef123456", node_id="1:2"))
    assert len(gw.calls) == 1
    record = gw.calls[0]
    assert (record.tool, record.file_key, record.node_id, record.ok) == (
        "get_metadata", "AbcDef123456", "1:2", True
    )
    assert "figd_" not in repr(record)


def test_error_detail_is_redacted():
    err = FigmaGatewayError("auth", "rejected token figd_abcdefghijklmnopqrstuvwxyz01")
    assert "figd_abcdefghij" not in str(err)


def test_node_id_is_omitted_when_targeting_the_whole_file(monkeypatch):
    seen = {}

    async def capture(self, tool, args):
        seen.update(args)
        return []

    monkeypatch.setattr(FigmaGateway, "_invoke", capture)
    run(gateway().call("get_metadata", file_key="AbcDef123456"))
    assert "nodeId" not in seen
    assert seen["fileKey"] == "AbcDef123456"


# -- result shaping --------------------------------------------------------

def test_structured_content_wins_over_text():
    class R:
        structuredContent = {"nodes": {}}
        content = [type("T", (), {"type": "text", "text": "ignored"})()]

    assert _blocks_of(R()) == [{"type": "structured", "data": {"nodes": {}}}]


def test_image_blocks_survive():
    class R:
        structuredContent = None
        content = [type("I", (), {"type": "image", "mimeType": "image/png", "data": "AAA"})()]

    assert _blocks_of(R()) == [{"type": "image", "mimeType": "image/png", "data": "AAA"}]
