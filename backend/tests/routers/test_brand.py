"""Tests for the /api/brand/extract endpoints."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
import io
from PIL import Image


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def _make_red_png_bytes() -> bytes:
    img = Image.new("RGB", (16, 16), (220, 38, 38))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_extract_from_logo_upload(client):
    files = {"logo": ("logo.png", _make_red_png_bytes(), "image/png")}
    resp = client.post("/api/brand/extract/logo", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert "primary_hex" in data
    assert data["primary_hex"].startswith("#")


def test_extract_from_url(client):
    with patch("routers.brand.scrape_brand_from_url") as mock_scrape:
        from services.brand_extractor import BrandPalette
        from services.url_brand_scraper import ScrapedBrand
        palette = BrandPalette(
            primary_rgb=(220, 38, 38),
            primary_hex="#DC2626",
            secondary_rgb=None,
            secondary_hex=None,
            raw_clusters=[(220, 38, 38)],
        )
        mock_scrape.return_value = ScrapedBrand(
            url="https://acme.com",
            title="ACME",
            og_image_url="https://acme.com/logo.png",
            primary_hex="#DC2626",
            palette=palette,
        )
        resp = client.post("/api/brand/extract/url", json={"url": "https://acme.com"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["primary_hex"] == "#DC2626"
    assert data["title"] == "ACME"


def test_extract_from_url_returns_404_when_no_og_image(client):
    with patch("routers.brand.scrape_brand_from_url") as mock_scrape:
        mock_scrape.return_value = None
        resp = client.post("/api/brand/extract/url", json={"url": "https://no-og.com"})
    assert resp.status_code == 404
