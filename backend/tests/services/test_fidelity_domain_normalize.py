"""plan.domain must reach the reference index, or scoring never runs.

``reference_path_for`` does an exact dict lookup against the index keys
(saas, healthcare, ecommerce, recipe, admin, fitness). The planner emits
human-readable industry labels — "E-Commerce & Retail", "CRM & Sales",
"fintech". Zero of twelve recent apps matched, so FIDELITY_SCORING_ENABLED
was a no-op across the entire corpus: every page logged "no reference for
<domain>/<page_type>" and no score was ever produced.
"""
from __future__ import annotations

import pytest

from services.fidelity_scorer import normalize_domain, reference_path_for

# Every plan.domain observed across the output corpus.
LIVE_DOMAINS = [
    ("E-Commerce & Retail",       "ecommerce"),
    ("Logistics & Supply Chain",  "admin"),
    ("Project Management",        "admin"),
    ("General Business",          "saas"),
    ("general",                   "saas"),
    ("hr",                        "admin"),
    ("fintech",                   "admin"),
    ("CRM & Sales",               "saas"),
    ("Hospitality & Food",        "recipe"),
]


class TestNormalize:
    @pytest.mark.parametrize("raw,expected", LIVE_DOMAINS)
    def test_live_corpus_domains_all_map(self, raw, expected):
        assert normalize_domain(raw) == expected

    @pytest.mark.parametrize("raw", ["saas", "SaaS", "Healthcare", "  ecommerce  "])
    def test_index_keys_pass_through(self, raw):
        assert normalize_domain(raw) == raw.strip().lower()

    def test_healthcare_is_recognised_from_prose(self):
        assert normalize_domain("Healthcare & Life Sciences") == "healthcare"
        assert normalize_domain("clinic scheduling") == "healthcare"

    def test_unknown_falls_back_to_a_real_key(self):
        # Never returns something the index lacks — that would reintroduce
        # the silent skip this function exists to remove.
        for raw in ("", None, "Underwater Basket Weaving", 42):
            assert normalize_domain(raw) in {
                "saas", "healthcare", "ecommerce", "recipe", "admin"}

    def test_fitness_is_never_returned(self):
        # fitness exists as an index key but carries zero page_types, so
        # resolving to it is indistinguishable from not resolving at all.
        assert all(normalize_domain(r) != "fitness" for r, _ in LIVE_DOMAINS)


class TestReachesTheIndex:
    @pytest.mark.parametrize("raw,_", LIVE_DOMAINS)
    def test_normalized_domain_resolves_a_real_reference(self, raw, _):
        # dashboard + login exist for every usable domain in the index.
        assert reference_path_for(normalize_domain(raw), "dashboard") is not None

    def test_raw_planner_label_still_misses(self):
        # Documents WHY the normalizer is needed — the bug, pinned.
        assert reference_path_for("E-Commerce & Retail", "dashboard") is None
