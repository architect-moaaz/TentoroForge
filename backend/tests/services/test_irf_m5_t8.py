"""Tests for M5-T8 — multi-perspective critic panel."""
from __future__ import annotations

import pytest

from services import critic_panel as cp
from services import critic_personas as cps
from services import session_context as sc


# ══════════════════════════════════════════════════════════════════
# critic_personas — individual persona callables
# ══════════════════════════════════════════════════════════════════


class TestDesignCritique:
    def test_scaffold_root_passes(self):
        page = {"root": {"type": "Stack", "children": []}}
        # The M5-T8 shallow check (missing_scaffold_root / hero) passes;
        # the M6-T9 rubric extension may add advisory-severity findings
        # (palette diversity, aesthetic profile conformance) — assert
        # only that the scaffold + hero checks stayed quiet.
        result = cps.design_critique(page, {}, "/x")
        assert not any(f["rule"] == "design.missing_scaffold_root" for f in result)
        assert not any(f["rule"] == "design.hero_missing_at_landing" for f in result)

    def test_bare_root_flags_missing_scaffold(self):
        page = {"root": {"type": "Text", "props": {"content": "hi"}}}
        result = cps.design_critique(page, {}, "/x")
        assert any(f["rule"] == "design.missing_scaffold_root" for f in result)

    def test_landing_route_missing_hero_flags_when_shape_declares_one(self):
        # Shape says hero=media-hero but page has no hero-scale first child
        plan = {"app_shape": {"layout": {"hero": "media-hero"}}}
        page = {"root": {"type": "Stack", "children": [
            {"type": "Text"}, {"type": "Button"},
        ]}}
        result = cps.design_critique(page, plan, "/")
        assert any(f["rule"] == "design.hero_missing_at_landing" for f in result)

    def test_landing_route_with_hero_passes(self):
        plan = {"app_shape": {"layout": {"hero": "media-hero"}}}
        page = {"root": {"type": "Stack", "children": [
            {"type": "Hero"}, {"type": "Text"},
        ]}}
        result = cps.design_critique(page, plan, "/")
        assert not any(f["rule"] == "design.hero_missing_at_landing" for f in result)

    def test_hero_none_skips_landing_check(self):
        plan = {"app_shape": {"layout": {"hero": "none"}}}
        page = {"root": {"type": "Stack", "children": [{"type": "Text"}]}}
        result = cps.design_critique(page, plan, "/")
        assert not any(f["rule"] == "design.hero_missing_at_landing" for f in result)


class TestUxCritique:
    def test_form_with_submit_label_passes(self):
        page = {"root": {"type": "Stack", "children": [
            {"type": "Form", "props": {"submitLabel": "Save"}, "children": []},
        ]}}
        result = cps.ux_critique(page, {}, "/x")
        assert not any(f["rule"] == "ux.form_missing_submit" for f in result)

    def test_form_with_submit_button_passes(self):
        page = {"root": {"type": "Stack", "children": [
            {"type": "Form", "children": [
                {"type": "Button", "props": {"submit": True, "label": "Go"}},
            ]},
        ]}}
        result = cps.ux_critique(page, {}, "/x")
        assert not any(f["rule"] == "ux.form_missing_submit" for f in result)

    def test_form_without_submit_flags_error(self):
        page = {"root": {"type": "Stack", "children": [
            {"type": "Form", "children": [{"type": "Input"}]},
        ]}}
        result = cps.ux_critique(page, {}, "/x")
        errs = [f for f in result if f["rule"] == "ux.form_missing_submit"]
        assert errs and errs[0]["severity"] == "error"

    def test_data_bound_without_empty_state_warns(self):
        page = {"root": {"type": "Stack", "children": [
            {"type": "Table", "props": {"dataSource": "candidates"},
             "children": []},
        ]}}
        result = cps.ux_critique(page, {}, "/x")
        assert any(f["rule"] == "ux.data_bound_missing_empty_state"
                   for f in result)

    def test_data_bound_with_emptytext_passes(self):
        page = {"root": {"type": "Stack", "children": [
            {"type": "Table", "props": {"dataSource": "candidates",
                                        "emptyText": "No candidates yet"},
             "children": []},
        ]}}
        result = cps.ux_critique(page, {}, "/x")
        assert not any(f["rule"] == "ux.data_bound_missing_empty_state"
                       for f in result)

    def test_data_bound_with_illustrated_empty_child_passes(self):
        page = {"root": {"type": "Stack", "children": [
            {"type": "Table", "props": {"dataSource": "candidates"},
             "children": [{"type": "IllustratedEmpty"}]},
        ]}}
        result = cps.ux_critique(page, {}, "/x")
        assert not any(f["rule"] == "ux.data_bound_missing_empty_state"
                       for f in result)

    def test_unbound_table_not_flagged(self):
        page = {"root": {"type": "Stack", "children": [
            {"type": "Table"},
        ]}}
        result = cps.ux_critique(page, {}, "/x")
        assert result == []


class TestCorrectnessCritique:
    def test_known_datasource_passes(self):
        page = {
            "dataSources": [{"name": "candidates"}],
            "root": {"type": "Stack", "children": [
                {"type": "Table", "props": {"dataSource": "candidates"}},
            ]},
        }
        assert cps.correctness_critique(page, {}, "/x") == []

    def test_unknown_datasource_flags_error(self):
        page = {
            "dataSources": [{"name": "candidates"}],
            "root": {"type": "Stack", "children": [
                {"type": "Table", "props": {"dataSource": "ghosts"}},
            ]},
        }
        result = cps.correctness_critique(page, {}, "/x")
        errs = [f for f in result if f["rule"] == "correctness.unknown_datasource"]
        assert errs and errs[0]["severity"] == "error"

    def test_no_datasources_skips_check(self):
        # When the page didn't declare ANY sources, we can't tell what's
        # legit — skip rather than false-alarm.
        page = {
            "root": {"type": "Stack", "children": [
                {"type": "Table", "props": {"dataSource": "anything"}},
            ]},
        }
        assert cps.correctness_critique(page, {}, "/x") == []

    def test_unknown_optionsfrom_source_flags(self):
        page = {
            "dataSources": [{"name": "roles"}],
            "root": {"type": "Stack", "children": [
                {"type": "Select", "props": {"optionsFrom": {"source": "users"}}},
            ]},
        }
        result = cps.correctness_critique(page, {}, "/x")
        assert any(f["rule"] == "correctness.unknown_optionsfrom_source"
                   for f in result)

    def test_unknown_workflow_on_form_flags(self):
        page = {"root": {"type": "Stack", "children": [
            {"type": "Form", "props": {"workflow": "Phantom"}},
        ]}}
        plan = {"workflows": [{"name": "CreateThing"}]}
        result = cps.correctness_critique(page, plan, "/x")
        assert any(f["rule"] == "correctness.unknown_workflow_ref"
                   for f in result)

    def test_unknown_workflow_on_button_action_flags(self):
        page = {"root": {"type": "Stack", "children": [
            {"type": "Button", "props": {"action": {"workflow": "Phantom"}}},
        ]}}
        plan = {"workflows": [{"name": "CreateThing"}]}
        result = cps.correctness_critique(page, plan, "/x")
        assert any(f["rule"] == "correctness.unknown_workflow_ref"
                   for f in result)

    def test_known_workflow_passes(self):
        page = {"root": {"type": "Stack", "children": [
            {"type": "Form", "props": {"workflow": "CreateThing"}},
        ]}}
        plan = {"workflows": [{"name": "CreateThing"}]}
        assert cps.correctness_critique(page, plan, "/x") == []

    def test_no_plan_workflows_skips_check(self):
        page = {"root": {"type": "Stack", "children": [
            {"type": "Form", "props": {"workflow": "Anything"}},
        ]}}
        assert cps.correctness_critique(page, {}, "/x") == []


# ══════════════════════════════════════════════════════════════════
# critic_panel — composition
# ══════════════════════════════════════════════════════════════════


def _install_ctx(plan: dict):
    sc.set_current(None)
    ctx = sc.from_plan(plan)
    sc.set_current(ctx)
    return ctx


class TestCriticPanelFlag:
    def test_is_enabled_default_off(self, monkeypatch):
        monkeypatch.delenv("FORGE_CRITIC_PANEL", raising=False)
        assert cp.is_enabled() is False

    def test_is_enabled_on(self, monkeypatch):
        monkeypatch.setenv("FORGE_CRITIC_PANEL", "1")
        assert cp.is_enabled() is True


class TestCriticPanelRecordOnly:
    """Flag off: findings computed, records land, needs_revise stays False."""

    def _clean(self):
        return {
            "root": {"type": "Stack", "children": [
                {"type": "Form", "props": {"submitLabel": "Save"}, "children": [
                    {"type": "Input"}]},
            ]},
        }

    def test_clean_page_all_pass(self, monkeypatch):
        monkeypatch.delenv("FORGE_CRITIC_PANEL", raising=False)
        ctx = _install_ctx({})
        report = cp.run_panel(self._clean(), {}, "/x")
        assert report.passed is True
        assert report.enforced is False
        assert report.needs_revise is False
        # 3 personas → 3 records
        personas = {v.check for v in ctx.verify_history}
        assert "critic:design" in personas
        assert "critic:ux" in personas
        assert "critic:correctness" in personas
        sc.set_current(None)

    def test_dirty_page_records_but_no_revise(self, monkeypatch):
        monkeypatch.delenv("FORGE_CRITIC_PANEL", raising=False)
        _install_ctx({"workflows": [{"name": "CreateThing"}]})
        bad = {
            "root": {"type": "Text"},  # design.missing_scaffold_root
        }
        report = cp.run_panel(bad, {"workflows": [{"name": "CreateThing"}]}, "/x")
        assert report.passed is True  # only warnings, no errors from this
        # Regardless of pass/fail, record-only mode never asks for revise
        assert report.needs_revise is False
        sc.set_current(None)

    def test_error_severity_but_flag_off_no_revise(self, monkeypatch):
        monkeypatch.delenv("FORGE_CRITIC_PANEL", raising=False)
        _install_ctx({})
        # Form without submit = ux error
        bad = {"root": {"type": "Stack", "children": [
            {"type": "Form", "children": [{"type": "Input"}]},
        ]}}
        report = cp.run_panel(bad, {}, "/x")
        assert report.passed is False
        assert "ux" in report.failed_personas
        assert report.needs_revise is False  # flag off
        sc.set_current(None)


class TestCriticPanelFlagOn:
    def test_error_severity_requests_revise(self, monkeypatch):
        monkeypatch.setenv("FORGE_CRITIC_PANEL", "1")
        _install_ctx({})
        bad = {"root": {"type": "Stack", "children": [
            {"type": "Form", "children": [{"type": "Input"}]},
        ]}}
        report = cp.run_panel(bad, {}, "/x")
        assert report.enforced is True
        assert report.needs_revise is True
        assert "ux" in report.failed_personas
        sc.set_current(None)

    def test_clean_page_no_revise_even_when_enforced(self, monkeypatch):
        monkeypatch.setenv("FORGE_CRITIC_PANEL", "1")
        _install_ctx({})
        clean = {"root": {"type": "Stack", "children": [
            {"type": "Form", "props": {"submitLabel": "Save"}, "children": [
                {"type": "Input"}]},
        ]}}
        report = cp.run_panel(clean, {}, "/x")
        assert report.enforced is True
        assert report.needs_revise is False
        sc.set_current(None)


class TestCriticPanelNoAmbientContext:
    def test_no_ctx_still_returns_report(self, monkeypatch):
        monkeypatch.delenv("FORGE_CRITIC_PANEL", raising=False)
        sc.set_current(None)
        page = {"root": {"type": "Stack"}}
        report = cp.run_panel(page, {}, "/x")
        assert isinstance(report, cp.PanelReport)
        assert len(report.results) == 3


class TestCriticPanelPersonaCrashSafety:
    def test_crashing_persona_becomes_warning_not_abort(self, monkeypatch):
        monkeypatch.delenv("FORGE_CRITIC_PANEL", raising=False)
        _install_ctx({})

        # Swap in a crashing persona for the duration of the test
        original = cps.PERSONA_REGISTRY.copy()
        def _boom(*a, **kw):
            raise RuntimeError("kaboom")
        try:
            cps.PERSONA_REGISTRY["design"] = _boom
            page = {"root": {"type": "Stack"}}
            report = cp.run_panel(page, {}, "/x")
            # Panel completes
            assert len(report.results) == 3
            design_result = next(r for r in report.results if r.persona == "design")
            # Crash is treated as a warning (design persona still "passes"
            # because crashes are warning-severity, not error)
            assert design_result.passed is True
            assert any("critic.design.crashed" in (f.get("rule") or "")
                       for f in design_result.findings)
        finally:
            cps.PERSONA_REGISTRY.clear()
            cps.PERSONA_REGISTRY.update(original)
            sc.set_current(None)
