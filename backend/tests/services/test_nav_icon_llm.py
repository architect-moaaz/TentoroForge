"""Tests for services.nav_icon_llm — LLM-based Lucide icon picker.

Every test injects a fake ``query_fn`` that returns a canned JSON
string. No live LLM calls. The module never raises — every failure
path degrades to ``NavIconChoice(icon="Folder", confidence=0.0)``.
"""

from __future__ import annotations

import pytest

from services.nav_icon_llm import (
    LUCIDE_ICON_SET,
    NavIconChoice,
    choose_nav_icon_llm,
)


def _stub(payload: str):
    def _q(system_prompt: str, user_prompt: str) -> str:
        return payload
    return _q


# --------------------------------------------------------------------------- #
# Vocabulary contract                                                         #
# --------------------------------------------------------------------------- #

class TestVocabularyContract:
    def test_exactly_60_icons(self):
        assert len(LUCIDE_ICON_SET) == 60

    def test_generic_icons_present(self):
        # A handful of must-have generic app-chrome icons.
        for name in ("Home", "Users", "Settings", "Search", "Folder"):
            assert name in LUCIDE_ICON_SET

    def test_domain_icons_present(self):
        # Cross-domain coverage: healthcare + transport + reward.
        for name in ("Stethoscope", "Truck", "Trophy"):
            assert name in LUCIDE_ICON_SET


# --------------------------------------------------------------------------- #
# Happy paths                                                                 #
# --------------------------------------------------------------------------- #

class TestHappyPath:
    def test_pick_icon_in_vocabulary(self):
        r = choose_nav_icon_llm(
            "Patients",
            domain="healthcare",
            query_fn=_stub('{"icon":"Stethoscope","confidence":0.95}'),
        )
        assert r.icon == "Stethoscope"
        assert r.confidence == pytest.approx(0.95)

    def test_neighbors_and_domain_accepted(self):
        r = choose_nav_icon_llm(
            "Shipments",
            neighbors=["Orders", "Deliveries"],
            domain="logistics",
            query_fn=_stub('{"icon":"Truck","confidence":0.9}'),
        )
        assert r.icon == "Truck"

    def test_generic_pick_when_domain_missing(self):
        r = choose_nav_icon_llm(
            "Dashboard",
            query_fn=_stub('{"icon":"LayoutDashboard","confidence":0.9}'),
        )
        assert r.icon == "LayoutDashboard"


# --------------------------------------------------------------------------- #
# Registry safety                                                             #
# --------------------------------------------------------------------------- #

class TestRegistrySafety:
    def test_icon_outside_vocabulary_falls_back(self):
        r = choose_nav_icon_llm(
            "Widgets",
            query_fn=_stub('{"icon":"NotARealLucideIcon","confidence":0.9}'),
        )
        assert r.icon == "Folder"
        assert r.confidence == 0.0

    def test_case_sensitive_membership(self):
        # Lucide names are strictly PascalCase; "home" is not "Home".
        r = choose_nav_icon_llm(
            "Home",
            query_fn=_stub('{"icon":"home","confidence":0.9}'),
        )
        assert r.icon == "Folder"

    def test_empty_icon_returns_folder(self):
        r = choose_nav_icon_llm(
            "X",
            query_fn=_stub('{"icon":"","confidence":0.5}'),
        )
        assert r.icon == "Folder"


# --------------------------------------------------------------------------- #
# Malformed / edge inputs                                                     #
# --------------------------------------------------------------------------- #

class TestMalformed:
    def test_garbage_string_falls_back_to_folder(self):
        r = choose_nav_icon_llm(
            "Home",
            query_fn=_stub("not json"),
        )
        assert r.icon == "Folder"
        assert r.confidence == 0.0

    def test_empty_string_falls_back(self):
        r = choose_nav_icon_llm("Home", query_fn=_stub(""))
        assert r.icon == "Folder"

    def test_code_fence_wrapper_is_stripped(self):
        payload = (
            "```json\n"
            '{"icon":"Home","confidence":0.9}\n'
            "```"
        )
        r = choose_nav_icon_llm("Home", query_fn=_stub(payload))
        assert r.icon == "Home"
        assert r.confidence == pytest.approx(0.9)

    def test_missing_confidence_defaults_to_zero(self):
        r = choose_nav_icon_llm(
            "Home",
            query_fn=_stub('{"icon":"Home"}'),
        )
        assert r.icon == "Home"
        assert r.confidence == 0.0

    def test_confidence_clamped_high(self):
        r = choose_nav_icon_llm(
            "Home",
            query_fn=_stub('{"icon":"Home","confidence":10.0}'),
        )
        assert r.confidence == 1.0

    def test_confidence_clamped_low(self):
        r = choose_nav_icon_llm(
            "Home",
            query_fn=_stub('{"icon":"Home","confidence":-1.5}'),
        )
        assert r.confidence == 0.0

    def test_query_fn_raises_falls_back(self):
        def _boom(system_prompt: str, user_prompt: str) -> str:
            raise RuntimeError("boom")

        r = choose_nav_icon_llm("Home", query_fn=_boom)
        assert r.icon == "Folder"

    def test_leading_prose_before_json_is_tolerated(self):
        payload = 'Sure thing: {"icon":"Home","confidence":0.8}'
        r = choose_nav_icon_llm("Home", query_fn=_stub(payload))
        assert r.icon == "Home"


# --------------------------------------------------------------------------- #
# Tolerance / call-shape                                                      #
# --------------------------------------------------------------------------- #

class TestTolerance:
    def test_no_neighbors_or_domain_ok(self):
        r = choose_nav_icon_llm(
            "Home",
            query_fn=_stub('{"icon":"Home","confidence":0.7}'),
        )
        assert r.icon == "Home"

    def test_empty_neighbors_list_ok(self):
        r = choose_nav_icon_llm(
            "Home",
            neighbors=[],
            query_fn=_stub('{"icon":"Home","confidence":0.7}'),
        )
        assert r.icon == "Home"

    def test_whitespace_around_payload_stripped(self):
        payload = '  {"icon":"Home","confidence":0.7}  '
        r = choose_nav_icon_llm("Home", query_fn=_stub(payload))
        assert r.icon == "Home"
