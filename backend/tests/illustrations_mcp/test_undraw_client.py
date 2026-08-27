import pytest
from unittest.mock import patch, MagicMock
from illustrations_mcp.undraw_client import UndrawClient, IllustrationMeta


@pytest.fixture
def client(tmp_path):
    return UndrawClient(cache_dir=tmp_path / "cache")


def test_list_illustrations_returns_metadata(client):
    sample_response = {
        "illustrations": [
            {"slug": "running-athlete", "title": "Running athlete", "tags": ["sport", "fitness"]},
            {"slug": "happy-news",      "title": "Happy news",      "tags": ["celebration"]},
        ],
        "next": None,
    }
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, json=lambda: sample_response)
        results = client.list_illustrations(tags=["fitness"], limit=5)
    assert len(results) >= 1
    assert all(isinstance(r, IllustrationMeta) for r in results)
    assert any(r.slug == "running-athlete" for r in results)


def test_get_illustration_svg_caches_to_disk(client, tmp_path):
    fake_svg = b'<svg xmlns="http://www.w3.org/2000/svg"><circle/></svg>'
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, content=fake_svg)
        svg1 = client.get_illustration_svg("running-athlete", color="6b7280")
    assert mock_get.call_count == 1
    assert svg1 == fake_svg
    cache_files = list((tmp_path / "cache").rglob("running-athlete*.svg"))
    assert len(cache_files) == 1
    with patch("httpx.Client.get") as mock_get2:
        svg2 = client.get_illustration_svg("running-athlete", color="6b7280")
    assert mock_get2.call_count == 0
    assert svg2 == fake_svg


def test_get_illustration_svg_different_color_separate_cache(client):
    fake_svg_a = b'<svg fill="#ff0000"/>'
    fake_svg_b = b'<svg fill="#00ff00"/>'
    with patch("httpx.Client.get") as mock_get:
        mock_get.side_effect = [
            MagicMock(status_code=200, content=fake_svg_a),
            MagicMock(status_code=200, content=fake_svg_b),
        ]
        a = client.get_illustration_svg("happy-news", color="ff0000")
        b = client.get_illustration_svg("happy-news", color="00ff00")
    assert a == fake_svg_a
    assert b == fake_svg_b
    assert mock_get.call_count == 2


def test_unknown_slug_returns_none(client):
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=404, content=b"not found")
        result = client.get_illustration_svg("does-not-exist", color="000000")
    assert result is None
