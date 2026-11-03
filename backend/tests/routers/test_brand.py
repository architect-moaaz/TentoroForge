"""Tests for the /api/brand/extract endpoints."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
import io
from PIL import Image


@pytest.fixture
def client():
    """Signed in: the extract routes fetch and decode for a person, never for anyone."""
    from types import SimpleNamespace
    import uuid

    from auth import get_current_user
    from main import app

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid.uuid4(), email="a@example.com")
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)


def test_the_extract_routes_want_a_sign_in():
    from main import app

    nobody = TestClient(app)
    assert nobody.post("/api/brand/extract/url", json={"url": "https://acme.com"}).status_code in (401, 403)
    assert nobody.post("/api/brand/extract/logo", files={"logo": ("l.png", b"x", "image/png")}).status_code in (401, 403)


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
