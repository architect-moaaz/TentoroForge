"""Tests for the fidelity scorer service."""
from __future__ import annotations
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from services.fidelity_scorer import (
    score_against_reference,
    reference_path_for,
    FidelityScore,
)


_MOCK_VISION_RESPONSE_JSON = """
{
  "score_0_to_10": 7.5,
  "color_match_score": 8,
  "layout_score": 7,
  "density_score": 7,
  "polish_score": 8,
  "qualitative_notes": "Strong color match; cards are slightly too tall."
}
"""


def test_reference_path_returns_correct_path_for_known_pair():
    p = reference_path_for(domain="saas", page_type="dashboard")
    assert p is not None
    assert p.name == "dashboard.png"
    assert p.parent.name == "saas"
    assert p.exists()


def test_reference_path_returns_none_for_missing_domain():
    assert reference_path_for(domain="fitness", page_type="dashboard") is None


def test_reference_path_returns_none_for_missing_page_type():
    assert reference_path_for(domain="saas", page_type="zzzunknown") is None


def test_score_against_reference_returns_full_score_object():
    with tempfile.TemporaryDirectory() as td:
        gen = Path(td) / "gen.png"
        gen.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)  # minimal PNG header
        with patch("services.fidelity_scorer._call_vision_model",
                   return_value=_MOCK_VISION_RESPONSE_JSON):
            result = score_against_reference(
                generated_screenshot=gen, domain="saas", page_type="dashboard"
            )
        assert isinstance(result, FidelityScore)
        assert result.score_0_to_10 == 7.5
        assert result.color_match_score == 8
        assert result.layout_score == 7
        assert result.density_score == 7
        assert result.polish_score == 8
        assert "color match" in result.qualitative_notes.lower()


def test_score_against_reference_returns_none_when_no_reference():
    with tempfile.TemporaryDirectory() as td:
        gen = Path(td) / "gen.png"
        gen.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        result = score_against_reference(
            generated_screenshot=gen, domain="fitness", page_type="dashboard"
        )
        assert result is None


def test_score_handles_malformed_json_gracefully():
    with tempfile.TemporaryDirectory() as td:
        gen = Path(td) / "gen.png"
        gen.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        with patch("services.fidelity_scorer._call_vision_model",
                   return_value="this is not json"):
            result = score_against_reference(
                generated_screenshot=gen, domain="saas", page_type="dashboard"
            )
        assert result is None
