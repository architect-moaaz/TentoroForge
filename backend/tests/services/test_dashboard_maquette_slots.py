"""Tests for the Phase 2 slot extensions to DashboardMaquette:
empty_state, ornament, footer.

These slots let the LLM author dashboard-level moments beyond hero
alone. Composer honors them as sections in the assembled schema.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.apply_dashboard_maquette import (
    _build_dashboard_empty_state,
    _build_dashboard_footer,
    _build_ornament_node,
    apply_maquette_to_dashboard,
)
from services.dashboard_maquette import (
    DASHBOARD_FOOTER_KINDS,
    ORNAMENT_KINDS,
    DashboardEmptyStateSpec,
    DashboardFooterSpec,
    DashboardMaquette,
    OrnamentSpec,
)


# ─────────────────────────── vocabulary ────────────────────────────────


class TestVocabulary:
    def test_ornament_kinds(self):
        assert set(ORNAMENT_KINDS) == {
            "eyebrow-line", "corner-illustration", "section-divider", "accent-badge",
        }

    def test_dashboard_footer_kinds(self):
        assert set(DASHBOARD_FOOTER_KINDS) == {
            "support-links", "attribution", "next-steps", "insight",
        }


# ─────────────────────────── data-shape parsing ────────────────────────


class TestEmptyStateParse:
    def test_missing_headline_drops(self):
        m = DashboardMaquette.from_dict({"empty_state": {"illustration": "welcome-mat"}})
        assert m.empty_state is None

    def test_full_shape(self):
        m = DashboardMaquette.from_dict({"empty_state": {
            "illustration": "empty-inbox",
            "headline": "No activity yet",
            "subhead": "Once you get going, it shows here.",
            "cta_label": "Get started",
            "cta_action": "/onboarding",
        }})
        assert m.empty_state is not None
        assert m.empty_state.illustration == "empty-inbox"
        assert m.empty_state.headline == "No activity yet"
        assert m.empty_state.cta_action == "/onboarding"

    def test_unknown_illustration_falls_back(self):
        # Composer would otherwise render a broken asset key.
        m = DashboardMaquette.from_dict({"empty_state": {
            "illustration": "space-cowboy", "headline": "H",
        }})
        assert m.empty_state is not None
        assert m.empty_state.illustration == "welcome-mat"


class TestOrnamentParse:
    def test_unknown_kind_dropped(self):
        m = DashboardMaquette.from_dict({"ornament": {"kind": "spicy-flourish"}})
        assert m.ornament is None

    def test_full_shape(self):
        m = DashboardMaquette.from_dict({"ornament": {
            "kind": "corner-illustration",
            "placement": "before-hero",
            "illustration": "sunlit-window",
        }})
        assert m.ornament is not None
        assert m.ornament.kind == "corner-illustration"
        assert m.ornament.placement == "before-hero"


class TestFooterParse:
    def test_unknown_kind_dropped(self):
        m = DashboardMaquette.from_dict({"footer": {"kind": "kitchen-sink"}})
        assert m.footer is None

    def test_known_kinds_kept(self):
        for kind in DASHBOARD_FOOTER_KINDS:
            m = DashboardMaquette.from_dict({"footer": {"kind": kind}})
            assert m.footer is not None
            assert m.footer.kind == kind


class TestToDictSurfacesSlots:
    def test_new_slots_serialize(self):
        m = DashboardMaquette(
            empty_state=DashboardEmptyStateSpec(illustration="welcome-mat", headline="H"),
            ornament=OrnamentSpec(kind="eyebrow-line", placement="before-hero"),
            footer=DashboardFooterSpec(kind="insight", content="Peak day: Tuesday"),
        )
        d = m.to_dict()
        assert d["empty_state"]["headline"] == "H"
        assert d["ornament"]["kind"] == "eyebrow-line"
        assert d["footer"]["kind"] == "insight"


# ─────────────────────────── pure composers ────────────────────────────


class TestBuildDashboardEmptyState:
    def test_none_input(self):
        assert _build_dashboard_empty_state(None) is None
        assert _build_dashboard_empty_state("nope") is None

    def test_missing_headline_returns_none(self):
        assert _build_dashboard_empty_state({"illustration": "welcome-mat"}) is None

    def test_headline_only(self):
        node = _build_dashboard_empty_state({"headline": "Nothing yet"})
        assert node is not None
        assert node["type"] == "IllustratedEmpty"
        assert node["props"]["headline"] == "Nothing yet"

    def test_full_props(self):
        node = _build_dashboard_empty_state({
            "illustration": "planted-seed", "headline": "H",
            "subhead": "S", "cta_label": "Go", "cta_action": "/x",
        })
        assert node is not None
        props = node["props"]
        assert props["illustration"] == "planted-seed"
        assert props["subhead"] == "S"
        assert props["cta-label"] == "Go"
        assert props["cta-action"] == "/x"


class TestBuildOrnamentNode:
    def test_placement_filter(self):
        # Ornament only emits at its own placement.
        orn = {"kind": "eyebrow-line", "placement": "before-hero"}
        assert _build_ornament_node(orn, placement="before-hero") is not None
        assert _build_ornament_node(orn, placement="after-kpis") is None

    def test_eyebrow_becomes_divider(self):
        node = _build_ornament_node({"kind": "eyebrow-line", "placement": "before-hero"},
                                     placement="before-hero")
        assert node["type"] == "Divider"
        assert node["props"]["variant"] == "eyebrow"

    def test_section_divider(self):
        node = _build_ornament_node({"kind": "section-divider", "placement": "after-kpis"},
                                     placement="after-kpis")
        assert node["type"] == "Divider"
        assert node["props"]["data-ornament"] == "section-divider"

    def test_accent_badge_default_content(self):
        node = _build_ornament_node({"kind": "accent-badge", "placement": "before-footer"},
                                     placement="before-footer")
        assert node["type"] == "Badge"
        assert node["props"]["content"] == "•"

    def test_corner_illustration(self):
        node = _build_ornament_node({
            "kind": "corner-illustration",
            "placement": "before-hero",
            "illustration": "sunlit-window",
        }, placement="before-hero")
        assert node["type"] == "IllustratedEmpty"
        assert node["props"]["illustration"] == "sunlit-window"

    def test_unknown_kind_returns_none(self):
        assert _build_ornament_node({"kind": "spicy", "placement": "before-hero"},
                                     placement="before-hero") is None


class TestBuildDashboardFooter:
    def test_none_input(self):
        assert _build_dashboard_footer(None) is None

    def test_unknown_kind(self):
        assert _build_dashboard_footer({"kind": "kitchen-sink"}) is None

    def test_support_links_default_copy(self):
        node = _build_dashboard_footer({"kind": "support-links"})
        assert node["type"] == "Row"
        assert node["props"]["data-footer-kind"] == "support-links"
        # Default copy present so the footer is never a bare empty row.
        _text_child = node["children"][0]
        assert _text_child["props"]["content"]

    def test_next_steps_card_shape(self):
        node = _build_dashboard_footer({"kind": "next-steps", "content": "Try adding a session"})
        assert node["type"] == "Card"
        assert node["props"]["data-footer-kind"] == "next-steps"
        assert any(c.get("type") == "Heading" for c in node["children"])

    def test_insight_carries_content(self):
        node = _build_dashboard_footer({"kind": "insight", "content": "Peak: Tue"})
        assert node["type"] == "Card"
        assert node["children"][0]["props"]["content"] == "Peak: Tue"


# ─────────────────────────── integration ───────────────────────────────


def _seed_project(root: Path, maquette: dict) -> Path:
    """Write plan.json + dashboard-maquette.json + a bare dashboard schema."""
    (root / "src" / "contracts").mkdir(parents=True, exist_ok=True)
    (root / "src" / "contracts" / "plan.json").write_text(json.dumps({
        "pages": [{"route": "/dashboard", "type": "dashboard"}],
    }), encoding="utf-8")
    (root / "src" / "contracts" / "dashboard-maquette.json").write_text(
        json.dumps(maquette), encoding="utf-8",
    )
    (root / "src" / "schemas").mkdir(parents=True, exist_ok=True)
    p = root / "src" / "schemas" / "dashboard.json"
    p.write_text(json.dumps({"id": "dashboard", "route": "/dashboard", "root": {}}),
                 encoding="utf-8")
    return p


def _find(node, kind: str):
    """DFS: first node with type=kind."""
    if isinstance(node, dict):
        if node.get("type") == kind:
            return node
        for k in ("children", "root"):
            v = node.get(k)
            if v is not None:
                hit = _find(v, kind)
                if hit is not None:
                    return hit
    elif isinstance(node, list):
        for x in node:
            hit = _find(x, kind)
            if hit is not None:
                return hit
    return None


def _find_by_data_slot(node, slot: str):
    if isinstance(node, dict):
        if node.get("props", {}).get("data-slot") == slot:
            return node
        for k in ("children", "root"):
            v = node.get(k)
            if v is not None:
                hit = _find_by_data_slot(v, slot)
                if hit is not None:
                    return hit
    elif isinstance(node, list):
        for x in node:
            hit = _find_by_data_slot(x, slot)
            if hit is not None:
                return hit
    return None


class TestComposerHonorsNewSlots:
    def test_empty_state_appears_in_dashboard(self, tmp_path: Path):
        p = _seed_project(tmp_path, {
            "empty_state": {"illustration": "empty-inbox", "headline": "No data yet"},
        })
        apply_maquette_to_dashboard(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        node = _find_by_data_slot(out, "dashboard-empty-state")
        assert node is not None
        assert node["props"]["headline"] == "No data yet"

    def test_footer_appears_in_dashboard(self, tmp_path: Path):
        p = _seed_project(tmp_path, {
            "kpis": [{"label": "Users", "entity": "users", "op": "count"}],
            "footer": {"kind": "insight", "content": "Peak: Tuesday"},
        })
        apply_maquette_to_dashboard(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        node = _find_by_data_slot(out, "dashboard-footer")
        assert node is not None
        assert node["props"]["data-footer-kind"] == "insight"

    def test_ornament_before_hero_appears_first(self, tmp_path: Path):
        p = _seed_project(tmp_path, {
            "hero": {"kind": "personalised-greeting", "greeting": "Welcome"},
            "ornament": {"kind": "eyebrow-line", "placement": "before-hero"},
        })
        apply_maquette_to_dashboard(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        # First child of the root Stack must be the ornament (before-hero).
        first = out["root"]["children"][0]
        assert first.get("type") == "Divider"
        assert first["props"]["data-ornament"] == "eyebrow-line"

    def test_ornament_after_kpis(self, tmp_path: Path):
        # KPI row is now emitted as a responsive Grid (cols base:1 sm:2
        # lg:4) so the 4 tiles stack on mobile — was a flat Row before,
        # which crammed unusably on small viewports.
        p = _seed_project(tmp_path, {
            "kpis": [{"label": "U", "entity": "users", "op": "count"}],
            "ornament": {"kind": "section-divider", "placement": "after-kpis"},
        })
        apply_maquette_to_dashboard(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        children = out["root"]["children"]
        kpi_row_idx = None
        for i, c in enumerate(children):
            if c.get("type") == "Grid" and any(
                gc.get("type") == "MetricTile" for gc in c.get("children", [])
            ):
                kpi_row_idx = i
                break
        assert kpi_row_idx is not None
        div = children[kpi_row_idx + 1]
        assert div.get("type") == "Divider"
        assert div["props"]["data-ornament"] == "section-divider"

    def test_ornament_only_at_declared_placement(self, tmp_path: Path):
        # An ornament with placement="before-footer" must NOT appear
        # at "before-hero" (or any other placement).
        p = _seed_project(tmp_path, {
            "hero": {"kind": "personalised-greeting", "greeting": "Hi"},
            "ornament": {"kind": "accent-badge", "placement": "before-footer"},
        })
        apply_maquette_to_dashboard(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        # First child is the hero, not a Badge.
        first = out["root"]["children"][0]
        assert first.get("type") != "Badge"

    def test_no_slots_matches_legacy_behavior(self, tmp_path: Path):
        # Confirming back-compat: a maquette with only pre-existing
        # fields (hero + kpis) still composes correctly.
        p = _seed_project(tmp_path, {
            "hero": {"kind": "personalised-greeting", "greeting": "Hi"},
            "kpis": [{"label": "U", "entity": "users", "op": "count"}],
        })
        apply_maquette_to_dashboard(str(tmp_path))
        out = json.loads(p.read_text(encoding="utf-8"))
        assert _find(out, "Hero") is not None
        assert _find(out, "MetricTile") is not None
        # And no empty-state / footer / ornament sneaked in.
        assert _find_by_data_slot(out, "dashboard-empty-state") is None
        assert _find_by_data_slot(out, "dashboard-footer") is None
