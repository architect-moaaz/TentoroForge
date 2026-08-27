import asyncio
import agents.page_schema_agent as psa


def _patch(monkeypatch, *, raise_overflow=False, single_text=None, chunked=None):
    async def fake_collect(prompt, *a, **k):
        if raise_overflow:
            raise Exception("Claude's response exceeded the 64000 output token maximum")
        return single_text or ""
    monkeypatch.setattr(psa, "_collect_llm_text", fake_collect)

    async def fake_chunked(base_prompt, page_brief, call_llm):
        return chunked
    monkeypatch.setattr("services.chunked_schema.generate_chunked_schema", fake_chunked)

    # _validate_schema_json is a Node subprocess (pnpm Zod) that the whole test
    # suite mocks; here it would reject the chunked result in CI. Treat as valid
    # so these tests exercise the ROUTING logic, not the subprocess validator.
    monkeypatch.setattr(psa, "_validate_schema_json", lambda d: None)


def _valid_chunked():
    # Root type "Grid" + content "CHUNKED" deliberately differ from _minimal_schema
    # (root "Stack", content = page_type.capitalize()) so the tests genuinely prove
    # the chunked path was taken rather than the minimal fallback.
    return {"schemaVersion": "2", "id": "rep", "route": "/rep", "layout": "main",
            "root": {"type": "Grid", "id": "root",
                     "children": [{"type": "Heading", "id": "h", "props": {"level": 1, "content": "CHUNKED"}}]}}


def test_overflow_routes_to_chunked(monkeypatch):
    _patch(monkeypatch, raise_overflow=True, chunked=_valid_chunked())
    page = {"route": "/rep", "type": "report"}
    out = asyncio.run(psa._generate_schema_for_page({"entities": {}}, page, "rep", None, max_retries=1))
    assert out["id"] == "rep"
    assert out["root"]["type"] == "Grid"                                 # only chunked yields Grid
    assert out["root"]["children"][0]["props"]["content"] == "CHUNKED"


def test_chunked_used_as_fallback_when_single_call_unparseable(monkeypatch):
    # single call returns junk every retry → falls through to chunked (not minimal)
    _patch(monkeypatch, single_text="not json at all", chunked=_valid_chunked())
    page = {"route": "/rep", "type": "report"}
    out = asyncio.run(psa._generate_schema_for_page({"entities": {}}, page, "rep", None, max_retries=1))
    assert out["root"]["type"] == "Grid"                                 # chunked, not _minimal_schema (Stack)


def test_minimal_schema_when_chunked_also_fails(monkeypatch):
    _patch(monkeypatch, single_text="junk", chunked=None)   # chunked skeleton failed → None
    page = {"route": "/rep", "type": "report"}
    out = asyncio.run(psa._generate_schema_for_page({"entities": {}}, page, "rep", None, max_retries=1))
    # _minimal_schema shape (root Stack) — proves we did NOT return a chunked schema
    assert out["root"]["type"] == "Stack" and out["id"] == "rep"
