"""Tests for extracting brand identity from a paste-in URL."""
import pytest
from unittest.mock import patch, MagicMock
from services.url_brand_scraper import scrape_brand_from_url, ScrapedBrand


def test_scrape_returns_brand_with_palette():
    """When the URL serves an og:image, we extract a palette from it."""
    fake_html = """
    <html>
      <head>
        <meta property="og:image" content="https://example.com/logo.png" />
        <meta property="og:title" content="ACME Corp" />
      </head>
    </html>
    """
    fake_logo_bytes = b"\x89PNG\r\n\x1a\n" + b"\0" * 1020  # dummy png-ish bytes
    with patch("httpx.Client.get") as mock_get:
        mock_get.side_effect = [
            MagicMock(status_code=200, text=fake_html),
            MagicMock(status_code=200, content=fake_logo_bytes),
        ]
        with patch("services.url_brand_scraper.extract_palette_from_logo") as mock_extract:
            from services.brand_extractor import BrandPalette
            mock_extract.return_value = BrandPalette(
                primary_rgb=(220, 38, 38),
                primary_hex="#DC2626",
                secondary_rgb=None,
                secondary_hex=None,
                raw_clusters=[(220, 38, 38)],
            )
            result = scrape_brand_from_url("https://acme.com")
    assert isinstance(result, ScrapedBrand)
    assert result.title == "ACME Corp"
    assert result.primary_hex == "#DC2626"


def test_scrape_returns_none_when_no_og_image():
    fake_html = "<html><head></head><body>no metadata</body></html>"
    with patch("httpx.Client.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, text=fake_html)
        result = scrape_brand_from_url("https://no-og.example.com")
    assert result is None


def test_scrape_handles_network_failure():
    import httpx
    with patch("httpx.Client.get") as mock_get:
        mock_get.side_effect = httpx.RequestError("connection failed")
        result = scrape_brand_from_url("https://broken.example.com")
    assert result is None
