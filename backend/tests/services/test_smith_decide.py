"""Tests for services.smith_decide — Smith Auto-Act decision function."""
from __future__ import annotations

import pytest

from services.smith_decide import (
    Candidate,
    build_candidates_from_scan,
    harvest_metadata,
    resolve,
    score_candidate,
    universal_intent,
)


# --------------------------------------------------------------------------- #
# universal_intent
# --------------------------------------------------------------------------- #

class TestUniversalIntent:
    @pytest.mark.parametrize("q", [
        "make it a badge everywhere",
        "change everywhere it appears",
        "on all pages",
        "on all page",       # tolerant of missing plural
        "on every screen",
        "across the app",
        "for every candidate",
        "in all places",
        "wherever it appears",
        "update all instances of status",
    ])
    def test_positive(self, q):
        assert universal_intent(q) is True, f"should match: {q!r}"

    @pytest.mark.parametrize("q", [
        "change the Status field",             # generic — no
        "fix Status on the applications page", # specific target — no
        "everyone loves status",               # word contains "every" but not phrase — no
        "",
    ])
    def test_negative(self, q):
        assert universal_intent(q) is False, f"should NOT match: {q!r}"


# --------------------------------------------------------------------------- #
# score_candidate
# --------------------------------------------------------------------------- #

class TestScoreCandidate:
    def test_current_route_dominates(self):
        c = Candidate(kind="page", route="/candidates", path="p.json",
                      matched_by=("label",))
        s = score_candidate(c, current_route="/candidates")
        # 50 (route) + 15 (label) = 65
        assert s == 65

    def test_no_signals(self):
        c = Candidate(kind="page", route="/x", path="p.json", matched_by=())
        assert score_candidate(c, current_route=None) == 0

    def test_recent_edit_hit(self):
        c = Candidate(kind="page", route="/interviews", path="p.json",
                      matched_by=("field_name",))
        s = score_candidate(c, current_route="/somewhere-else",
                            recent_edits=("/interviews", "/candidates"))
        # 20 (recent) + 0 (label absent) = 20; field_name isn't in scoring signals
        assert s == 20

    def test_all_signals_stack(self):
        c = Candidate(kind="page", route="/candidates", path="p.json",
                      matched_by=("label", "entity_ref"))
        s = score_candidate(c, current_route="/candidates",
                            recent_edits=("/candidates",))
        # 50 + 20 + 15 + 10
        assert s == 95


# --------------------------------------------------------------------------- #
# resolve — decision branches
# --------------------------------------------------------------------------- #

class TestResolve:
    def test_no_candidates_asks(self):
        r = resolve("anything", candidates=[])
        assert r.kind == "ask"
        assert "no matching" in r.reason.lower()
        assert r.targets == ()

    def test_current_route_hit_acts(self):
        cands = [
            Candidate(kind="page", route="/candidates", path="cand.json",
                      matched_by=("label",)),   # 50+15 = 65
            Candidate(kind="page", route="/applications", path="app.json",
                      matched_by=("label",)),   # 15
        ]
        r = resolve("fix status", cands, current_route="/candidates")
        assert r.kind == "act"
        assert len(r.targets) == 1
        assert r.targets[0].route == "/candidates"

    def test_label_only_two_pages_becomes_chip(self):
        cands = [
            Candidate(kind="page", route="/candidates", path="c.json",
                      matched_by=("label",)),   # 15
            Candidate(kind="page", route="/applications", path="a.json",
                      matched_by=("label",)),   # 15
        ]
        r = resolve("fix status", cands, current_route=None)
        # Top 15, gap 0 → below act floor of 60 → chip (2 candidates)
        assert r.kind == "chip"
        assert len(r.targets) == 2

    def test_universal_intent_acts_all(self):
        cands = [
            Candidate(kind="page", route="/a", path="a.json", matched_by=("label",)),
            Candidate(kind="page", route="/b", path="b.json", matched_by=("label",)),
            Candidate(kind="page", route="/c", path="c.json", matched_by=("label",)),
        ]
        r = resolve("make status a badge everywhere", cands)
        assert r.kind == "act_all"
        assert len(r.targets) == 3

    def test_universal_intent_overrides_route_bias(self):
        cands = [
            Candidate(kind="page", route="/a", path="a.json", matched_by=("label",)),
            Candidate(kind="page", route="/b", path="b.json", matched_by=("label",)),
        ]
        # /a would win on route bias, but universal intent should still act_all
        r = resolve("everywhere it appears", cands, current_route="/a")
        assert r.kind == "act_all"
        assert len(r.targets) == 2

    def test_too_many_candidates_asks(self):
        cands = [
            Candidate(kind="page", route=f"/p{i}", path=f"p{i}.json",
                      matched_by=("label",))
            for i in range(5)
        ]
        r = resolve("fix status", cands)
        # 5 candidates → above chip cap → ask
        assert r.kind == "ask"
        assert "weak/similar" in r.reason or "clarification" in r.reason

    def test_score_gap_required_for_act(self):
        # Two candidates that both have current-route + label = tied at 65 each.
        # Gap = 0 → fails act threshold → falls to chip.
        cands = [
            Candidate(kind="page", route="/x", path="a.json",
                      matched_by=("label",)),
            Candidate(kind="page", route="/x", path="b.json",
                      matched_by=("label",)),
        ]
        r = resolve("fix status", cands, current_route="/x")
        # Both score 65, gap = 0 → chip
        assert r.kind == "chip"

    def test_scores_included_for_debugging(self):
        cands = [
            Candidate(kind="page", route="/a", path="a.json", matched_by=("label",)),
        ]
        r = resolve("fix status", cands, current_route="/a")
        assert len(r.scores) == 1
        assert r.scores[0][1] > 0


# --------------------------------------------------------------------------- #
# build_candidates_from_scan
# --------------------------------------------------------------------------- #

class TestBuildCandidatesFromScan:
    def test_grep_matches_become_page_candidates(self):
        page_index = {"src/schemas/candidates.json": "/candidates"}
        grep = [
            {"path": "src/schemas/candidates.json", "count": 2,
             "previews": ["\"label\": \"Status\""]},
        ]
        c = build_candidates_from_scan(grep_matches=grep, page_index=page_index)
        assert len(c) == 1
        assert c[0].kind == "page"
        assert c[0].route == "/candidates"
        assert "label" in c[0].matched_by
        assert "Status" in c[0].excerpt

    def test_dedup_across_signal_sources(self):
        page_index = {"src/schemas/candidates.json": "/candidates"}
        grep = [{"path": "src/schemas/candidates.json", "previews": ["hit"]}]
        comp = [{"path": "src/schemas/candidates.json", "fields": ["status"]}]
        c = build_candidates_from_scan(
            grep_matches=grep, component_usages=comp, page_index=page_index,
        )
        # Same file appears in two sources → ONE candidate with both signals.
        assert len(c) == 1
        assert set(c[0].matched_by) == {"label", "field_name"}

    def test_no_page_index_falls_back_to_workflow_kind(self):
        grep = [{"path": "src/workflows/schedule.json", "previews": ["hit"]}]
        c = build_candidates_from_scan(grep_matches=grep, page_index={})
        assert len(c) == 1
        assert c[0].kind == "workflow"
        assert c[0].route is None

    def test_entity_matches(self):
        entities = [{"path": "src/schemas/entities/Candidate.json", "excerpt": "e"}]
        c = build_candidates_from_scan(entity_matches=entities)
        assert len(c) == 1
        assert c[0].kind == "entity"
        assert "entity_ref" in c[0].matched_by

    def test_excerpt_truncated(self):
        long_excerpt = "x" * 500
        grep = [{"path": "p.json", "previews": [long_excerpt]}]
        c = build_candidates_from_scan(grep_matches=grep)
        assert len(c[0].excerpt) == 200


# --------------------------------------------------------------------------- #
# harvest_metadata — trace → UI-ready metadata
# --------------------------------------------------------------------------- #

class TestHarvestMetadata:
    def test_empty_trace(self):
        assert harvest_metadata(None) == {}
        assert harvest_metadata([]) == {}

    def test_no_resolve_calls(self):
        trace = [{"tool": "grep_schemas", "result": {"matches": []}}]
        assert harvest_metadata(trace) == {}

    def test_chip_becomes_disambiguation(self):
        trace = [{
            "tool": "resolve_target",
            "args": {"query": "change the Status field"},
            "result": {
                "kind": "chip",
                "targets": [
                    {"route": "/candidates", "path": "c.json", "excerpt": "Status"},
                    {"route": "/applications", "path": "a.json", "excerpt": "Status"},
                ],
                "reason": "top 15 gap 0",
            },
        }]
        md = harvest_metadata(trace)
        assert "disambiguation" in md
        d = md["disambiguation"]
        assert d["query"] == "change the Status field"
        assert len(d["candidates"]) == 2
        assert d["candidates"][0]["route"] == "/candidates"
        assert "also_applies_to" not in md

    def test_act_with_extra_targets_becomes_also_applies_to(self):
        trace = [{
            "tool": "resolve_target",
            "args": {"query": "make Status a badge"},
            "result": {
                "kind": "act",
                "targets": [
                    {"route": "/candidates", "path": "c.json", "excerpt": ""},
                    {"route": "/applications", "path": "a.json", "excerpt": ""},
                    {"route": "/reviews", "path": "r.json", "excerpt": ""},
                ],
            },
        }]
        md = harvest_metadata(trace)
        aat = md.get("also_applies_to") or []
        assert [t["route"] for t in aat] == ["/applications", "/reviews"]
        assert "disambiguation" not in md

    def test_act_alone_no_metadata(self):
        trace = [{
            "tool": "resolve_target",
            "args": {"query": "q"},
            "result": {"kind": "act", "targets": [{"route": "/x", "path": "x.json"}]},
        }]
        assert harvest_metadata(trace) == {}

    def test_act_all_no_also_applies(self):
        # act_all means Smith did apply to all — nothing left to offer.
        trace = [{
            "tool": "resolve_target",
            "args": {"query": "everywhere"},
            "result": {
                "kind": "act_all",
                "targets": [
                    {"route": "/a", "path": "a.json"},
                    {"route": "/b", "path": "b.json"},
                ],
            },
        }]
        assert harvest_metadata(trace) == {}

    def test_last_resolve_wins(self):
        trace = [
            {"tool": "resolve_target",
             "args": {"query": "first"},
             "result": {"kind": "act", "targets": [
                 {"route": "/x"}, {"route": "/y"},
             ]}},
            {"tool": "resolve_target",
             "args": {"query": "second"},
             "result": {"kind": "chip", "targets": [
                 {"route": "/p"}, {"route": "/q"},
             ]}},
        ]
        md = harvest_metadata(trace)
        # Second resolve won → disambiguation, not also_applies_to.
        assert "disambiguation" in md
        assert md["disambiguation"]["query"] == "second"
        assert "also_applies_to" not in md

    def test_malformed_entries_ignored(self):
        trace = [
            "not-a-dict",
            {"tool": "resolve_target", "result": "not-a-dict"},
            {"tool": "resolve_target",
             "args": {"query": "q"},
             "result": {"kind": "chip", "targets": [
                 {"route": "/a"}, {"route": "/b"},
             ]}},
        ]
        md = harvest_metadata(trace)
        assert "disambiguation" in md
