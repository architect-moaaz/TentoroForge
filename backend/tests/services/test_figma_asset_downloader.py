import asyncio
import hashlib
import pathlib
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.figma_asset_downloader import extract_asset_urls, download_figma_assets


def _hash(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:12]


def _resp(status: int, content: bytes = b"", content_type: str = "image/svg+xml"):
    r = MagicMock()
    r.status_code = status
    r.content = content
    r.headers = {"content-type": content_type}
    return r


# ── extract_asset_urls ──

def test_extract_basic():
    jsx = '''
    const imgLogo = "https://www.figma.com/api/mcp/asset/abc-123";
    const imgIcon = "https://www.figma.com/api/mcp/asset/def-456";
    function App() { return <img src={imgLogo} />; }
    '''
    urls = extract_asset_urls(jsx)
    assert "https://www.figma.com/api/mcp/asset/abc-123" in urls
    assert "https://www.figma.com/api/mcp/asset/def-456" in urls
    assert len(urls) == 2


def test_extract_dedupes():
    jsx = '''
    const a = "https://www.figma.com/api/mcp/asset/X";
    const b = "https://www.figma.com/api/mcp/asset/X";
    '''
    assert extract_asset_urls(jsx) == ["https://www.figma.com/api/mcp/asset/X"]


def test_extract_ignores_non_mcp_urls():
    jsx = '''
    const a = "https://www.figma.com/api/mcp/asset/keep";
    const b = "https://cdn.example.com/skip.png";
    const c = "https://www.figma.com/design/abc";
    '''
    urls = extract_asset_urls(jsx)
    assert urls == ["https://www.figma.com/api/mcp/asset/keep"]


def test_extract_returns_sorted_unique():
    jsx = '''
    const c = "https://www.figma.com/api/mcp/asset/c";
    const a = "https://www.figma.com/api/mcp/asset/a";
    const b = "https://www.figma.com/api/mcp/asset/b";
    '''
    urls = extract_asset_urls(jsx)
    assert urls == [
        "https://www.figma.com/api/mcp/asset/a",
        "https://www.figma.com/api/mcp/asset/b",
        "https://www.figma.com/api/mcp/asset/c",
    ]


def test_extract_empty_when_no_assets():
    jsx = '<div>no images</div>'
    assert extract_asset_urls(jsx) == []


def test_extract_uuid_with_hyphens():
    """Figma asset IDs are UUID-shaped (8-4-4-4-12 hex with hyphens)."""
    url = "https://www.figma.com/api/mcp/asset/69aea68a-2de1-413f-8a38-5c86eef4de0a"
    jsx = f'const x = "{url}";'
    assert extract_asset_urls(jsx) == [url]


# ── download_figma_assets ──

@pytest.mark.asyncio
async def test_download_creates_files(tmp_path):
    urls = [
        "https://www.figma.com/api/mcp/asset/abc-123",
        "https://www.figma.com/api/mcp/asset/def-456",
    ]
    async def fake_get(url, **kwargs):
        return _resp(200, b"<svg>fake</svg>", "image/svg+xml")
    with patch("httpx.AsyncClient.get", AsyncMock(side_effect=fake_get)):
        result = await download_figma_assets(urls, str(tmp_path))
    assert len(result) == 2
    for url in urls:
        public_path = result[url]
        assert public_path.startswith("/figma/")
        on_disk = tmp_path / "public" / public_path.lstrip("/")
        assert on_disk.exists()
        assert on_disk.read_bytes() == b"<svg>fake</svg>"


@pytest.mark.asyncio
async def test_download_uses_extension_from_content_type(tmp_path):
    urls = ["https://www.figma.com/api/mcp/asset/png-thing"]
    async def fake_get(url, **kwargs):
        return _resp(200, b"\x89PNG...", "image/png")
    with patch("httpx.AsyncClient.get", AsyncMock(side_effect=fake_get)):
        result = await download_figma_assets(urls, str(tmp_path))
    public_path = result[urls[0]]
    assert public_path.endswith(".png")


@pytest.mark.asyncio
async def test_download_handles_404(tmp_path):
    """Failed downloads are silently omitted from the result, not raised."""
    urls = [
        "https://www.figma.com/api/mcp/asset/exists",
        "https://www.figma.com/api/mcp/asset/missing",
    ]
    async def fake_get(url, **kwargs):
        if "missing" in url:
            return _resp(404)
        return _resp(200, b"ok", "image/svg+xml")
    with patch("httpx.AsyncClient.get", AsyncMock(side_effect=fake_get)):
        result = await download_figma_assets(urls, str(tmp_path))
    assert urls[0] in result
    assert urls[1] not in result


@pytest.mark.asyncio
async def test_download_idempotent_skips_existing(tmp_path):
    """If the cached file already exists, no GET is fired."""
    url = "https://www.figma.com/api/mcp/asset/already-here"
    figma_dir = tmp_path / "public" / "figma"
    figma_dir.mkdir(parents=True)
    h = _hash(url)
    (figma_dir / f"{h}.svg").write_bytes(b"cached")

    mock_get = AsyncMock()
    with patch("httpx.AsyncClient.get", mock_get):
        result = await download_figma_assets([url], str(tmp_path))
    mock_get.assert_not_called()
    assert result[url].endswith(f"{h}.svg")


@pytest.mark.asyncio
async def test_download_empty_list_returns_empty(tmp_path):
    result = await download_figma_assets([], str(tmp_path))
    assert result == {}


@pytest.mark.asyncio
async def test_download_creates_public_figma_dir(tmp_path):
    """Even when no urls, public/figma/ is created so downstream writes succeed."""
    await download_figma_assets([], str(tmp_path))
    assert (tmp_path / "public" / "figma").is_dir()


@pytest.mark.asyncio
async def test_download_concurrent(tmp_path):
    """Many URLs should all download (capped concurrency, but no drops)."""
    urls = [f"https://www.figma.com/api/mcp/asset/n-{i}" for i in range(20)]
    async def fake_get(url, **kwargs):
        await asyncio.sleep(0.001)
        return _resp(200, b"ok", "image/svg+xml")
    with patch("httpx.AsyncClient.get", AsyncMock(side_effect=fake_get)):
        result = await download_figma_assets(urls, str(tmp_path), concurrency=4)
    assert len(result) == 20
    for url in urls:
        assert url in result


@pytest.mark.asyncio
async def test_download_path_stable_across_runs(tmp_path):
    """Same URL → same local path on subsequent runs (idempotency contract)."""
    url = "https://www.figma.com/api/mcp/asset/stable-id"
    async def fake_get(u, **kwargs):
        return _resp(200, b"v1", "image/svg+xml")
    with patch("httpx.AsyncClient.get", AsyncMock(side_effect=fake_get)):
        r1 = await download_figma_assets([url], str(tmp_path))
    # Second run — same dir, but cached file exists so no GET should fire
    mock_get = AsyncMock()
    with patch("httpx.AsyncClient.get", mock_get):
        r2 = await download_figma_assets([url], str(tmp_path))
    assert r1[url] == r2[url]
    mock_get.assert_not_called()
