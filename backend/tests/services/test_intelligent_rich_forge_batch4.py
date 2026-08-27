"""Tests for M3-T4/T5/T9/T10 + M2-T5 (batch 4)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import (
    reframe_plan,
    root_layout_toaster_guard,
    runtime_context_integrations,
)


# ══════════════════════════════════════════════════════════════════
# root_layout_toaster_guard — M3-T5
# ══════════════════════════════════════════════════════════════════


class TestRootLayoutToasterGuard:
    def _write_default_layout(self, tmp_path: Path) -> Path:
        layout_dir = tmp_path / "src" / "app"
        layout_dir.mkdir(parents=True)
        layout_path = layout_dir / "layout.tsx"
        layout_path.write_text(
            'import type { Metadata } from "next";\n'
            'import "./globals.css";\n'
            'import { Providers } from "./providers";\n'
            '\n'
            'export default function RootLayout({ children }: { children: React.ReactNode }) {\n'
            '  return (\n'
            '    <html lang="en">\n'
            '      <body>\n'
            '        <Providers>{children}</Providers>\n'
            '      </body>\n'
            '    </html>\n'
            '  );\n'
            '}\n',
            encoding="utf-8",
        )
        return layout_path

    def _shell_none_plan(self):
        return {
            "app_shape": {
                "layout": {"shell": "none", "hero": "full-bleed-gradient", "primaryInteraction": "capture", "density": "spacious"},
                "auth": {"surface": "modal", "gating": "on-action"},
                "nav": {"menu": "none", "back": "history"},
                "workflows": {"executionMode": "fire-and-forget"},
                "data": {"readShape": "list", "denormalization": "aggressive"},
                "identity": {"usageMode": "single-session"},
            }
        }

    def test_snap2app_shape_injects_toaster(self, tmp_path):
        self._write_default_layout(tmp_path)
        result = root_layout_toaster_guard.apply_toaster_guard(
            str(tmp_path), self._shell_none_plan()
        )
        assert result["applied"] is True
        content = (tmp_path / "src" / "app" / "layout.tsx").read_text(encoding="utf-8")
        assert '<Toaster' in content
        assert 'from "sonner"' in content

    def test_workspace_shape_does_not_inject(self, tmp_path):
        self._write_default_layout(tmp_path)
        plan = {
            "app_shape": {
                "layout": {"shell": "sidebar", "hero": "none", "primaryInteraction": "data-grid", "density": "comfortable"},
                "auth": {"surface": "route", "gating": "on-load"},
                "nav": {"menu": "sidebar-links", "back": "crumb"},
                "workflows": {"executionMode": "await-with-progress"},
                "data": {"readShape": "list", "denormalization": "moderate"},
                "identity": {"usageMode": "multi-user-team"},
            }
        }
        result = root_layout_toaster_guard.apply_toaster_guard(str(tmp_path), plan)
        assert result["applied"] is False
        content = (tmp_path / "src" / "app" / "layout.tsx").read_text(encoding="utf-8")
        assert '<Toaster' not in content

    def test_idempotent_second_run_is_no_op(self, tmp_path):
        self._write_default_layout(tmp_path)
        r1 = root_layout_toaster_guard.apply_toaster_guard(str(tmp_path), self._shell_none_plan())
        r2 = root_layout_toaster_guard.apply_toaster_guard(str(tmp_path), self._shell_none_plan())
        assert r1["applied"] is True
        assert r2["applied"] is False
        content = (tmp_path / "src" / "app" / "layout.tsx").read_text(encoding="utf-8")
        assert content.count('<Toaster') == 1

    def test_missing_plan_is_noop(self, tmp_path):
        self._write_default_layout(tmp_path)
        r = root_layout_toaster_guard.apply_toaster_guard(str(tmp_path), None)
        assert r["applied"] is False

    def test_missing_layout_file_is_noop(self, tmp_path):
        r = root_layout_toaster_guard.apply_toaster_guard(str(tmp_path), self._shell_none_plan())
        assert r["applied"] is False
        assert "not present" in r["reason"]

    def test_inject_toaster_pure_transform(self):
        source = (
            'import "./globals.css";\n'
            '\n'
            'export default function L() {\n'
            '  return (<html><body><X /></body></html>);\n'
            '}\n'
        )
        result = root_layout_toaster_guard.inject_toaster(source)
        assert 'from "sonner"' in result
        assert '<Toaster' in result

    def test_inject_toaster_preserves_when_already_present(self):
        source = (
            'import { Toaster } from "sonner";\n'
            'export default function L() {\n'
            '  return (<html><body><X /><Toaster /></body></html>);\n'
            '}\n'
        )
        result = root_layout_toaster_guard.inject_toaster(source)
        assert result == source


# ══════════════════════════════════════════════════════════════════
# runtime_context_integrations — M3-T10
# ══════════════════════════════════════════════════════════════════


class TestRuntimeContextIntegrations:
    def test_no_runtime_context_returns_empty(self):
        assert runtime_context_integrations.required_integrations_for_plan({}) == []
        assert runtime_context_integrations.required_integrations_for_plan(None) == []
        assert runtime_context_integrations.required_integrations_for_plan({"runtime_context": []}) == []

    def test_geo_returns_geocoding_key(self):
        plan = {"runtime_context": ["geo"]}
        reqs = runtime_context_integrations.required_integrations_for_plan(plan)
        env_vars = {r.env_var for r in reqs}
        assert "GEOCODING_API_KEY" in env_vars
        # All entries carry source_capability
        assert all(r.source_capability == "geo" for r in reqs)

    def test_push_notifications_returns_fcm(self):
        plan = {"runtime_context": ["push_notifications"]}
        reqs = runtime_context_integrations.required_integrations_for_plan(plan)
        env_vars = {r.env_var for r in reqs}
        assert "FCM_SERVER_KEY" in env_vars

    def test_multiple_capabilities_attribute_correctly(self):
        plan = {"runtime_context": ["geo", "push_notifications"]}
        reqs = runtime_context_integrations.required_integrations_for_plan(plan)
        sources = {r.source_capability for r in reqs}
        assert sources == {"geo", "push_notifications"}

    def test_unknown_capability_dropped(self):
        plan = {"runtime_context": ["telepathy", "geo"]}
        reqs = runtime_context_integrations.required_integrations_for_plan(plan)
        sources = {r.source_capability for r in reqs}
        assert sources == {"geo"}

    def test_required_env_vars_deduplicated(self):
        plan = {"runtime_context": ["geo", "geo"]}
        env_vars = runtime_context_integrations.required_env_vars_for_plan(plan)
        # Even though geo appears twice, GEOCODING_API_KEY appears once
        assert env_vars.count("GEOCODING_API_KEY") <= 1

    def test_group_by_capability(self):
        plan = {"runtime_context": ["geo", "push_notifications"]}
        reqs = runtime_context_integrations.required_integrations_for_plan(plan)
        groups = runtime_context_integrations.group_by_capability(reqs)
        assert "geo" in groups
        assert "push_notifications" in groups
        assert all(r.source_capability == "geo" for r in groups["geo"])


# ══════════════════════════════════════════════════════════════════
# reframe_plan — M2-T5
# ══════════════════════════════════════════════════════════════════


class TestReframePlan:
    def _out_of_scope_plan(self):
        return {
            "description": "Build me a multiplayer FPS game with anti-cheat",
            "coverage_verdict": {
                "status": "out_of_scope",
                "reason": "Real-time multiplayer game with physics — needs a game engine.",
                "nearest_supported": "game-catalog + leaderboard + player-stats app",
            },
            "archetypes": [],
        }

    def test_rewrites_description_to_nearest_supported(self):
        plan = self._out_of_scope_plan()
        new_plan, report = reframe_plan.reframe_from_verdict(plan)
        assert "game-catalog + leaderboard + player-stats app" in new_plan["description"]
        assert report["reframed_to"] == "game-catalog + leaderboard + player-stats app"

    def test_clears_coverage_verdict(self):
        plan = self._out_of_scope_plan()
        new_plan, _ = reframe_plan.reframe_from_verdict(plan)
        assert "coverage_verdict" not in new_plan

    def test_records_history(self):
        plan = self._out_of_scope_plan()
        new_plan, _ = reframe_plan.reframe_from_verdict(plan)
        assert len(new_plan["reframe_history"]) == 1
        entry = new_plan["reframe_history"][0]
        assert entry["from_status"] == "out_of_scope"
        assert entry["nearest_supported"].startswith("game-catalog")

    def test_second_reframe_appends_history(self):
        # A plan that was reframed once, then LLM re-emitted out_of_scope again
        plan = self._out_of_scope_plan()
        plan["reframe_history"] = [{"ts": "prev", "from_status": "out_of_scope"}]
        new_plan, _ = reframe_plan.reframe_from_verdict(plan)
        assert len(new_plan["reframe_history"]) == 2

    def test_never_mutates_input(self):
        plan = self._out_of_scope_plan()
        original_copy = {"description": plan["description"], "coverage_verdict": dict(plan["coverage_verdict"])}
        reframe_plan.reframe_from_verdict(plan)
        assert plan["description"] == original_copy["description"]
        assert plan["coverage_verdict"] == original_copy["coverage_verdict"]

    def test_in_scope_verdict_raises(self):
        plan = {
            "description": "workspace",
            "coverage_verdict": {"status": "in_scope", "reason": "fine"},
        }
        with pytest.raises(reframe_plan.ReframeError):
            reframe_plan.reframe_from_verdict(plan)

    def test_missing_verdict_raises(self):
        with pytest.raises(reframe_plan.ReframeError):
            reframe_plan.reframe_from_verdict({"description": "x"})

    def test_missing_nearest_supported_raises(self):
        plan = {
            "description": "x",
            "coverage_verdict": {"status": "out_of_scope", "reason": "no"},
        }
        with pytest.raises(reframe_plan.ReframeError):
            reframe_plan.reframe_from_verdict(plan)

    def test_not_dict_raises(self):
        with pytest.raises(reframe_plan.ReframeError):
            reframe_plan.reframe_from_verdict("plan?")  # type: ignore[arg-type]


# ══════════════════════════════════════════════════════════════════
# shell_menu_sync — M3-T4 (nav.menu=none early return)
# ══════════════════════════════════════════════════════════════════


class TestShellMenuSyncShapeAware:
    def test_shell_menu_sync_skipped_when_nav_menu_none(self, tmp_path, monkeypatch):
        # Create the minimum required file structure
        contracts = tmp_path / "src" / "contracts"
        schemas = tmp_path / "src" / "schemas"
        contracts.mkdir(parents=True)
        schemas.mkdir(parents=True)
        (contracts / "nav-flow.json").write_text(json.dumps({"pages": []}), encoding="utf-8")
        (schemas / "shell.json").write_text(json.dumps({
            "root": {"type": "SideNav", "props": {"groups": []}}
        }), encoding="utf-8")
        # Plan with nav.menu = none
        (contracts / "plan.json").write_text(json.dumps({
            "app_shape": {
                "nav": {"menu": "none"},
            }
        }), encoding="utf-8")

        from services.shell_menu_sync import sync_shell_menu
        result = sync_shell_menu(str(tmp_path))
        assert result["synced"] is False
        assert "nav.menu=none" in result["message"]

    def test_shell_menu_sync_runs_when_nav_menu_sidebar_links(self, tmp_path):
        contracts = tmp_path / "src" / "contracts"
        schemas = tmp_path / "src" / "schemas"
        contracts.mkdir(parents=True)
        schemas.mkdir(parents=True)
        (contracts / "nav-flow.json").write_text(json.dumps({"pages": []}), encoding="utf-8")
        (schemas / "shell.json").write_text(json.dumps({
            "root": {"type": "SideNav", "props": {"groups": []}}
        }), encoding="utf-8")
        (contracts / "plan.json").write_text(json.dumps({
            "app_shape": {"nav": {"menu": "sidebar-links"}}
        }), encoding="utf-8")

        from services.shell_menu_sync import sync_shell_menu
        result = sync_shell_menu(str(tmp_path))
        # Should proceed (may or may not sync depending on nav-flow content;
        # what matters is it wasn't shape-vetoed).
        assert "nav.menu=none" not in result["message"]
