"""Entry-point helpers: request shape, adapter resolution, and the plan +
context a design import produces."""
from __future__ import annotations

import json

import pytest

from schemas.project import DesignImportRequest, GenerateRequest
from services.design_import import import_design_plan, page_texts, plan_source_from_metadata, resolve_design
from services.design_source import DesignMarkup, DesignPage, DesignScope, DesignSourceError, DesignTokens


def test_generate_request_reads_either_shape():
    old = GenerateRequest(description="x", figma_url="https://www.figma.com/design/abc/x", figma_token="figd_1")
    d = old.design_import()
    assert d.provider == "figma" and d.ref.endswith("/x") and d.token == "figd_1"
    new = GenerateRequest(description="x", design=DesignImportRequest(provider="uxpilot", ref="pg_1", credential_id="row"))
    assert new.design_import().provider == "uxpilot"
    assert GenerateRequest(description="x").design_import() is None
    # `design` wins when both are present.
    both = GenerateRequest(description="x", figma_url="https://www.figma.com/design/abc/x",
                           design=DesignImportRequest(provider="uxpilot", ref="pg_2"))
    assert both.design_import().provider == "uxpilot"


@pytest.mark.asyncio
async def test_resolve_design_figma_needs_no_db():
    r = await resolve_design(provider="figma", ref="https://www.figma.com/design/abc123/My?node-id=1-2", token="figd_x")
    assert r.plan_source.kind == "figma" and r.plan_source.secret == "figd_x"
    assert r.metadata == {"provider": "figma", "ref": "https://www.figma.com/design/abc123/My?node-id=1-2", "container": "abc123"}
    assert "figd_x" not in json.dumps(r.metadata)


@pytest.mark.asyncio
async def test_resolve_design_rejects_unknown_provider_and_bad_figma_url():
    with pytest.raises(DesignSourceError):
        await resolve_design(provider="sketch", ref="x")
    with pytest.raises(DesignSourceError):
        await resolve_design(provider="figma", ref="https://example.com/not-figma")


@pytest.mark.asyncio
async def test_plan_source_from_figma_metadata(monkeypatch):
    monkeypatch.delenv("FIGMA_TOKEN", raising=False)
    # A plan persisted before the credential store still builds, from its token.
    src = await plan_source_from_metadata({"provider": "figma", "ref": "https://www.figma.com/design/abc/x", "token": "t"})
    assert src.is_figma and src.secret == "t"
    with pytest.raises(DesignSourceError):
        await plan_source_from_metadata({"provider": "nope", "ref": "x"})


class _Src:
    provider = "uxpilot"
    container = "pg"

    def __init__(self, tokens=None, fail_tokens=False):
        self._tokens = tokens
        self._fail = fail_tokens

    async def scope(self):
        return DesignScope(provider="uxpilot", container="pg", name="Shop", ref="pg",
                           pages=(DesignPage(route="/", title="Home", ref="d1", prompt="overview"),))

    async def tokens(self):
        if self._fail:
            raise DesignSourceError("no theme")
        return self._tokens or DesignTokens()

    async def markup(self, ref):
        return DesignMarkup(ref, "html", "<div><h1>Welcome</h1><p>Orders today</p><script>x</script></div>")

    async def assets(self, urls, output_dir, project_id=None):
        return {}


@pytest.mark.asyncio
async def test_import_design_plan_writes_context_when_tokens_exist(tmp_path):
    plan = await import_design_plan(_Src(DesignTokens(colors=("#112233",))), str(tmp_path), "a shop")
    assert plan["_design_driven"] and plan["description"] == "a shop"
    assert plan["pages"][0]["design_ref"] == "d1"
    ctx = json.loads((tmp_path / "src/contracts/design-context.json").read_text())
    assert ctx["provider"] == "uxpilot" and ctx["design_tokens"]["colors"] == ["#112233"]


@pytest.mark.asyncio
async def test_import_design_plan_without_tokens_writes_no_context(tmp_path):
    plan = await import_design_plan(_Src(fail_tokens=True), str(tmp_path))
    assert plan["pages"]
    assert not (tmp_path / "src/contracts/design-context.json").exists()


@pytest.mark.asyncio
async def test_page_texts_collects_visible_text_only():
    texts = await page_texts(_Src(), {"pages": [{"route": "/", "design_ref": "d1"}]})
    assert texts == {"/": ["Welcome", "Orders today"]}


# ---------------------------------------------------------------------------
# Figma credential from the org's MCP-server row
# ---------------------------------------------------------------------------

import uuid as _uuid
from types import SimpleNamespace

from services.design_import import figma_token_for, resolve_design_credential


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _Db:
    """Just enough of AsyncSession for the resolver: get() by id, execute()
    returning every row (the resolver filters by host itself)."""

    def __init__(self, rows):
        self.rows = rows

    async def get(self, model, row_id):
        return next((r for r in self.rows if r.id == row_id), None)

    async def execute(self, stmt):
        return _Result(list(self.rows))


def _row(url, *, org="org-1", enabled=True, secret="figd_row", name="Figma"):
    return SimpleNamespace(id=_uuid.uuid4(), org_id=org, server_url=url, enabled=enabled,
                           auth_kind="bearer", auth_secret_ct="ct", auth_secret_iv="iv", name=name,
                           _secret=secret)


@pytest.fixture
def decode(monkeypatch):
    import services.design_import as di
    import services.mcp_client as mc
    monkeypatch.setattr(mc, "_decode_secret", lambda row: row._secret)
    return di


@pytest.mark.asyncio
async def test_resolve_design_credential_matches_rows_by_provider_host(decode):
    figma = _row("https://mcp.figma.com/mcp")
    uxp = _row("https://mcp.uxpilot.net/mcp", secret="ep_row", name="UX Pilot")
    db = _Db([figma, uxp])
    assert await resolve_design_credential(db, "org-1", "figma", None) == (str(figma.id), figma.server_url, "figd_row")
    assert await resolve_design_credential(db, "org-1", "uxpilot", None) == (str(uxp.id), uxp.server_url, "ep_row")
    # Naming the wrong row for a provider is refused, not silently used.
    with pytest.raises(DesignSourceError, match="not a Figma server"):
        await resolve_design_credential(db, "org-1", "figma", str(uxp.id))
    with pytest.raises(DesignSourceError, match="not registered"):
        await resolve_design_credential(db, "org-2", "figma", str(figma.id))


@pytest.mark.asyncio
async def test_figma_token_prefers_row_then_env_then_legacy(decode, monkeypatch):
    monkeypatch.delenv("FIGMA_TOKEN", raising=False)
    figma = _row("https://mcp.figma.com/mcp")
    token, row_id = await figma_token_for({}, db=_Db([figma]), org_id="org-1")
    assert (token, row_id) == ("figd_row", str(figma.id))
    # No row: environment.
    monkeypatch.setenv("FIGMA_TOKEN", "figd_env")
    assert await figma_token_for({}, db=_Db([]), org_id="org-1") == ("figd_env", None)
    # No row, no env: a token an old plan persisted.
    monkeypatch.delenv("FIGMA_TOKEN")
    assert await figma_token_for({}, db=_Db([]), org_id="org-1", legacy_token="figd_old") == ("figd_old", None)
    assert await figma_token_for({}, db=_Db([]), org_id="org-1") == ("", None)


@pytest.mark.asyncio
async def test_figma_token_refuses_a_named_row_that_no_longer_serves(decode, monkeypatch):
    monkeypatch.setenv("FIGMA_TOKEN", "figd_env")
    with pytest.raises(DesignSourceError):
        await figma_token_for({"credential_id": str(_uuid.uuid4())}, db=_Db([]), org_id="org-1")


@pytest.mark.asyncio
async def test_resolve_design_figma_uses_the_row_and_records_it(decode, monkeypatch):
    monkeypatch.delenv("FIGMA_TOKEN", raising=False)
    figma = _row("https://mcp.figma.com/mcp")
    r = await resolve_design(provider="figma", ref="https://www.figma.com/design/abc/x", db=_Db([figma]), org_id="org-1")
    assert r.plan_source.secret == "figd_row"
    assert r.metadata["credential_id"] == str(figma.id)
    assert "figd_row" not in json.dumps(r.metadata)
    # A pasted token wins for this call and leaves no credential id behind.
    r2 = await resolve_design(provider="figma", ref="https://www.figma.com/design/abc/x", db=_Db([figma]), org_id="org-1", token="figd_pasted")
    assert r2.plan_source.secret == "figd_pasted" and "credential_id" not in r2.metadata
    with pytest.raises(DesignSourceError, match="no Figma access token"):
        await resolve_design(provider="figma", ref="https://www.figma.com/design/abc/x", db=_Db([]), org_id="org-1")


@pytest.mark.asyncio
async def test_plan_source_from_figma_metadata_resolves_the_row(decode, monkeypatch):
    monkeypatch.delenv("FIGMA_TOKEN", raising=False)
    figma = _row("https://mcp.figma.com/mcp")
    src = await plan_source_from_metadata(
        {"provider": "figma", "ref": "https://www.figma.com/design/abc/x", "credential_id": str(figma.id)},
        db=_Db([figma]), org_id="org-1",
    )
    assert src.is_figma and src.secret == "figd_row" and src.credential_id == str(figma.id)
