"""Tests for the photo picker (domain + entity → photo URL)."""
from __future__ import annotations
import tempfile
from pathlib import Path
from unittest.mock import patch

from services.photo_picker import pick_photo_for


def _mock_client_url(_query, size="1600x900"):
    return f"https://images.unsplash.com/photo-for-{_query.replace(' ', '-')}"


def test_pick_photo_for_user_in_healthcare_returns_url():
    with patch("services.photo_picker._client_photo_url", side_effect=_mock_client_url):
        url = pick_photo_for("User", domain="healthcare")
    assert url.startswith("https://images.unsplash.com/")


def test_pick_photo_for_user_uses_person_query():
    """User entity should map to a person-y query."""
    captured = {}
    def capture(q, size="1600x900"):
        captured["q"] = q
        return "https://images.unsplash.com/photo-x"
    with patch("services.photo_picker._client_photo_url", side_effect=capture):
        pick_photo_for("User", domain="saas")
    # Query should reference person / portrait / face
    q = captured["q"].lower()
    assert any(w in q for w in ["person", "portrait", "face", "professional", "people"])


def test_pick_photo_for_property_uses_real_estate_query():
    captured = {}
    def capture(q, size="1600x900"):
        captured["q"] = q
        return "https://images.unsplash.com/photo-x"
    with patch("services.photo_picker._client_photo_url", side_effect=capture):
        pick_photo_for("Property", domain="real-estate")
    q = captured["q"].lower()
    assert any(w in q for w in ["house", "home", "real estate", "interior", "architecture", "property"])


def test_pick_photo_for_unknown_entity_falls_back_to_domain_seed():
    """Unknown entity + healthcare domain → uses a healthcare domain seed."""
    captured = {}
    def capture(q, size="1600x900"):
        captured["q"] = q
        return "https://images.unsplash.com/photo-x"
    with patch("services.photo_picker._client_photo_url", side_effect=capture):
        pick_photo_for("Widget", domain="healthcare")
    # Should reflect a healthcare-y query
    q = captured["q"].lower()
    assert any(w in q for w in ["medical", "hospital", "doctor", "healthcare", "clinic", "nurse"])


def test_pick_photo_for_unknown_domain_uses_generic_fallback():
    captured = {}
    def capture(q, size="1600x900"):
        captured["q"] = q
        return "https://images.unsplash.com/photo-x"
    with patch("services.photo_picker._client_photo_url", side_effect=capture):
        url = pick_photo_for("Widget", domain="completely-unknown-domain")
    assert url
    # Generic fallback should still be a valid query
    assert captured["q"]


# ---------------------------------------------------------------------------
# Per-project photo rotation tests (Task 7)
# ---------------------------------------------------------------------------

from services.photo_picker import _query_for  # noqa: E402


def test_different_project_seeds_yield_different_queries():
    """The whole point — two projects must not get identical photos.

    Uses "User" which has 3 query candidates in the seeds file.
    """
    a = _query_for("User", "saas", project_seed="proj-a")
    b = _query_for("User", "saas", project_seed="proj-b")
    assert a != b, f"same query for both seeds: {a!r}"


def test_same_project_seed_is_stable_across_calls():
    a1 = _query_for("User", "saas", project_seed="proj-a")
    a2 = _query_for("User", "saas", project_seed="proj-a")
    assert a1 == a2


def test_omitting_project_seed_preserves_old_behavior():
    """Backwards-compat — old callers without project_seed still work."""
    a = _query_for("User", "saas")
    b = _query_for("User", "saas")
    assert a == b


def test_pick_photo_for_threads_project_seed():
    """End-to-end: pick_photo_for honours project_seed all the way down."""
    with patch("services.photo_picker._client_photo_url", side_effect=lambda q, s="1600x900": f"URL::{q}"):
        url_a = pick_photo_for("User", "saas", project_seed="seed-A")
        url_b = pick_photo_for("User", "saas", project_seed="seed-B")
    assert url_a != url_b
