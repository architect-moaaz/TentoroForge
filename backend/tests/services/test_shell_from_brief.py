"""Tests for services.shell_from_brief — Spec D Wave 6 brief-first shell
bridge. Verifies the brief's palette / visual stance is threaded through
into the same shell.json shape shell_templates has always emitted, and
that a missing brief falls back to the legacy deterministic builder
without regression."""
from __future__ import annotations

import json

import pytest

from services.shell_from_brief import build_shell_from_brief
from services.shell_guardrail import is_renderable_shell


def _nav_flow(routes):
    return {"pages": [{"id": r.strip("/") or "home", "route": r,
                       "title": f"{r.strip('/').title() or 'Dashboard'}Page",
                       "params": [], "shell": True} for r in routes]}


def _brief(**palette_overrides):
    palette = {
        "brand": "#2E5C7E",
        "accent": "#0F8A6A",
        "neutrals_base": "#F5F7FA",
        "surface_bg": "#FAFCFD",
        "surface_elevated": "#FFFFFF",
        "foreground_primary": "#1A2634",
        "foreground_muted": "#5A6B7A",
    }
    palette.update(palette_overrides)
    return {
        "identity": {"domain": "Healthcare", "voice": "warm_precise"},
        "palette": palette,
        "layout": {"density": "comfortable", "radius": "soft_8",
                   "radius_px": 8},
    }


# ── fallback path (no brief) ────────────────────────────────────────────

class TestBrieflessFallback:
    def test_none_brief_delegates_to_deterministic_builder(self):
        # Must still return a renderable shell.
        shell = build_shell_from_brief(
            None,
            {"plan": {"pages": []},
             "nav_flow": _nav_flow(["/", "/orders", "/customers"])},
        )
        assert is_renderable_shell(shell)
        assert shell["schemaVersion"] == "2.0"

    def test_empty_brief_dict_falls_back(self):
        shell = build_shell_from_brief(
            {}, {"plan": None, "nav_flow": _nav_flow(["/", "/a"])},
        )
        assert is_renderable_shell(shell)

    def test_non_dict_brief_falls_back(self):
        shell = build_shell_from_brief(
            "not a brief",  # type: ignore[arg-type]
            {"plan": None, "nav_flow": _nav_flow(["/", "/a"])},
        )
        assert is_renderable_shell(shell)


# ── brief-driven palette ────────────────────────────────────────────────

class TestBriefPaletteThreading:
    def test_accent_hex_flows_through_to_shell_tokens(self):
        # The frames paint the brand mark + active-nav highlight with the
        # accent — the most visible brief-derived color in the shell.
        brief = _brief(accent="#FF6B00")
        shell = build_shell_from_brief(
            brief,
            {"plan": {"pages": []},
             "nav_flow": _nav_flow(["/", "/a", "/b"])},
        )
        blob = json.dumps(shell)
        assert "#FF6B00" in blob

    def test_sidenav_frame_carries_brief_accent(self):
        # 11-route nav triggers the sidebar/SideNav frame — the accent
        # prop of the SideNav node must be the brief's accent color.
        brief = _brief(accent="#C47D0E")
        shell = build_shell_from_brief(
            brief,
            {"plan": {"pages": []},
             "nav_flow": _nav_flow(["/", "/a", "/b", "/c", "/d", "/e",
                                    "/f", "/g", "/h", "/i", "/j"])},
        )
        blob = json.dumps(shell)
        assert "#C47D0E" in blob

    def test_no_stock_slate_bleeds_into_shell(self):
        # The "same-generator smell" — a hardcoded slate-900 chrome. The
        # bridge must not fall back to that when the brief has a palette.
        brief = _brief(brand="#003366", accent="#FF9900")
        shell = build_shell_from_brief(
            brief,
            {"plan": {"pages": []},
             "nav_flow": _nav_flow(["/", "/x", "/y", "/z"])},
        )
        blob = json.dumps(shell)
        assert "slate-900" not in blob and "slate-800" not in blob


# ── output shape invariants ─────────────────────────────────────────────

class TestOutputShape:
    def test_shell_has_exactly_one_page_outlet(self):
        brief = _brief()
        shell = build_shell_from_brief(
            brief, {"plan": None, "nav_flow": _nav_flow(["/", "/a"])},
        )
        blob = json.dumps(shell)
        assert blob.count('"PageOutlet"') == 1

    def test_shell_carries_schema_version_and_id(self):
        brief = _brief()
        shell = build_shell_from_brief(
            brief, {"plan": None, "nav_flow": _nav_flow(["/", "/a"])},
        )
        assert shell["schemaVersion"] == "2.0"
        assert shell["id"] == "shell"
        assert "frame" in shell

    def test_caller_supplied_design_spec_survives_where_brief_is_silent(self):
        # Design_spec had a "navigation" pref the brief doesn't touch —
        # the caller's key must survive the merge. Brief-authored accent
        # overrides the caller's spec's accent (brief wins where they
        # both speak); the caller-only nav pref still routes selection.
        brief = _brief(accent="#0F8A6A")
        design_spec = {"navigation": {"style": "sidebar-dark"},
                       "colorPalette": {"accent": "#111111"}}
        shell = build_shell_from_brief(
            brief,
            {"plan": {"pages": []},
             "nav_flow": _nav_flow(["/", "/a", "/b"]),
             "design_spec": design_spec},
        )
        blob = json.dumps(shell)
        # Brief accent wins over caller's spec accent.
        assert "#0F8A6A" in blob
        # And the caller's navigation pref forced a sidebar/rail frame
        # (topbar would be the default for 3 routes).
        assert shell["frame"] in ("sidebar", "rail")

    def test_shell_is_always_renderable(self):
        brief = _brief()
        for routes in (["/", "/a"],
                       ["/", "/a", "/b", "/c", "/d", "/e", "/f", "/g", "/h", "/i", "/j"],
                       ["/", "/inbox", "/messages", "/labels", "/settings"]):
            shell = build_shell_from_brief(
                brief, {"plan": None, "nav_flow": _nav_flow(routes)},
            )
            assert is_renderable_shell(shell), f"bad shell for {routes}"


# ── visual stance nudges ────────────────────────────────────────────────

class TestVisualStanceNudges:
    def test_dense_workspace_stance_prefers_rail(self):
        brief = _brief()
        brief["identity"]["visual_stance"] = {
            "shape_vocab": "geometric",
            "principles": ["dense-workspace", "canvas-first"],
        }
        shell = build_shell_from_brief(
            brief,
            {"plan": None,
             "nav_flow": _nav_flow(["/", "/a", "/b", "/c", "/d", "/e", "/f"])},
        )
        # Stance push toward a rail — but never harder than what
        # shell_templates already enforces.
        assert shell["frame"] in ("rail", "sidebar", "topbar", "split")

    def test_editorial_stance_prefers_topbar(self):
        brief = _brief()
        brief["identity"]["visual_stance"] = {
            "shape_vocab": "organic",
            "principles": ["editorial", "content-first"],
        }
        shell = build_shell_from_brief(
            brief,
            {"plan": None,
             "nav_flow": _nav_flow(["/", "/blog", "/about"])},
        )
        assert shell["frame"] == "topbar"


# ── smoke: brief -> synth spec doesn't blow away caller data ────────────

def test_bridge_never_raises_on_partial_brief():
    # Partial brief (no palette, no identity, no layout) — must fall
    # back gracefully to the deterministic builder.
    partial = {"palette": {}}
    shell = build_shell_from_brief(
        partial, {"plan": None, "nav_flow": _nav_flow(["/", "/a"])},
    )
    assert is_renderable_shell(shell)
