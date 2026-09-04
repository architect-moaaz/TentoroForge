"""Tests for M6 batch — T1 profile JSONs, T3 picker, T4 surface pass,
T5 form patterns loaded, T6 form UX invariants, T8 critic enforcement
trigger, T9 rubric + score."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import (
    aesthetic_profile_picker,
    critic_panel,
    critic_personas,
    form_ux_invariants,
    surface_treatment_pass,
)


# ══════════════════════════════════════════════════════════════════
# M6-T1 — profile JSONs
# ══════════════════════════════════════════════════════════════════


class TestProfileJsons:
    def test_all_six_profiles_load(self):
        aesthetic_profile_picker.clear_cache()
        names = aesthetic_profile_picker.known_profiles()
        assert set(names) >= {
            "glass-dark", "carbon", "polaris",
            "material-3", "fluent-2", "clean-editorial",
        }

    def test_each_profile_has_required_keys(self):
        aesthetic_profile_picker.clear_cache()
        for name in aesthetic_profile_picker.known_profiles():
            p = aesthetic_profile_picker.get_profile(name)
            assert p is not None
            assert "tokens" in p
            assert "css_variables" in p
            assert "surface_treatment" in p


# ══════════════════════════════════════════════════════════════════
# M6-T3 — picker
# ══════════════════════════════════════════════════════════════════


class TestPicker:
    def test_empty_plan_returns_default(self):
        aesthetic_profile_picker.clear_cache()
        name = aesthetic_profile_picker.pick({})
        assert name in {"fluent-2", "glass-dark", "carbon", "polaris"}

    def test_explicit_override_wins(self):
        aesthetic_profile_picker.clear_cache()
        assert aesthetic_profile_picker.pick({"aesthetic_profile": "carbon"}) == "carbon"

    def test_hero_glow_shape_picks_glass_dark(self):
        aesthetic_profile_picker.clear_cache()
        plan = {
            "app_shape": {
                "layout": {"hero": "full-bleed-gradient", "primaryInteraction": "capture"},
                "identity": {"usageMode": "single-session"},
            },
        }
        # glass-dark scores 2 (hero + identity), fluent-2 scores 0
        assert aesthetic_profile_picker.pick(plan) == "glass-dark"

    def test_workspace_data_grid_picks_carbon(self):
        aesthetic_profile_picker.clear_cache()
        plan = {
            "app_shape": {
                "layout": {"density": "dense", "primaryInteraction": "data-grid"},
                "identity": {"usageMode": "multi-user-team"},
            },
        }
        assert aesthetic_profile_picker.pick(plan) == "carbon"

    def test_ecommerce_industry_picks_polaris(self):
        aesthetic_profile_picker.clear_cache()
        plan = {
            "industry": "ecommerce-retail",
            "app_shape": {"layout": {"density": "comfortable"}},
        }
        assert aesthetic_profile_picker.pick(plan) == "polaris"


# ══════════════════════════════════════════════════════════════════
# M6-T4 — surface treatment pass
# ══════════════════════════════════════════════════════════════════


def _install_app(tmp_path: Path):
    (tmp_path / "src" / "app").mkdir(parents=True)
    (tmp_path / "src" / "app" / "globals.css").write_text(
        ":root { --foo: 1; }\n", encoding="utf-8"
    )
    (tmp_path / "src" / "app" / "layout.tsx").write_text(
        'export default function L({ children }: any) {\n'
        '  return (<html><body>{children}</body></html>);\n'
        '}\n', encoding="utf-8"
    )
    (tmp_path / "src" / "schemas").mkdir(parents=True)
    (tmp_path / "src" / "schemas" / "home.json").write_text(json.dumps({
        "schemaVersion": "2",
        "id": "home",
        "route": "/",
        "root": {"type": "Stack", "children": [
            {"type": "Card", "children": [{"type": "Text"}]},
            {"type": "Button", "props": {"variant": "primary", "label": "Go"}},
            {"type": "Heading", "props": {"level": 1, "content": "Hi"}},
        ]},
    }), encoding="utf-8")
    return tmp_path


class TestSurfaceTreatment:
    def test_flag_off_no_op(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FORGE_SURFACE_TREATMENT", raising=False)
        result = surface_treatment_pass.apply(tmp_path, {})
        assert result["applied"] is False

    def test_flag_on_writes_css_body_class_and_styles(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_SURFACE_TREATMENT", "1")
        aesthetic_profile_picker.clear_cache()
        _install_app(tmp_path)
        result = surface_treatment_pass.apply(tmp_path, {"aesthetic_profile": "glass-dark"})
        assert result["applied"] is True
        assert result["profile"] == "glass-dark"
        # CSS scope written
        css = (tmp_path / "src" / "app" / "globals.css").read_text(encoding="utf-8")
        assert ".aesthetic-glass-dark" in css
        assert "--primary" in css
        # Layout body class added
        layout = (tmp_path / "src" / "app" / "layout.tsx").read_text(encoding="utf-8")
        assert "aesthetic-glass-dark" in layout
        # Card + Button got style hints
        page = json.loads((tmp_path / "src" / "schemas" / "home.json").read_text(encoding="utf-8"))
        card = next(n for n in page["root"]["children"] if n["type"] == "Card")
        assert "style" in card.get("props", {})
        btn = next(n for n in page["root"]["children"] if n["type"] == "Button")
        assert "style" in btn.get("props", {})

    def test_idempotent_second_run(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_SURFACE_TREATMENT", "1")
        aesthetic_profile_picker.clear_cache()
        _install_app(tmp_path)
        r1 = surface_treatment_pass.apply(tmp_path, {"aesthetic_profile": "carbon"})
        r2 = surface_treatment_pass.apply(tmp_path, {"aesthetic_profile": "carbon"})
        assert r1["applied"] and r2["applied"]
        # Second run's CSS should be unchanged
        assert r2["css_written"] is False
        assert r2["body_class_added"] is False

    def test_profile_swap_replaces_prior_scope(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_SURFACE_TREATMENT", "1")
        aesthetic_profile_picker.clear_cache()
        _install_app(tmp_path)
        surface_treatment_pass.apply(tmp_path, {"aesthetic_profile": "carbon"})
        surface_treatment_pass.apply(tmp_path, {"aesthetic_profile": "polaris"})
        css = (tmp_path / "src" / "app" / "globals.css").read_text(encoding="utf-8")
        # Only the current profile's scope survives
        assert ".aesthetic-polaris" in css
        assert ".aesthetic-carbon" not in css


# ══════════════════════════════════════════════════════════════════
# M6-T5 — form patterns present
# ══════════════════════════════════════════════════════════════════


class TestFormPatterns:
    def test_all_ten_patterns_load(self):
        # Anchored to this file, not the cwd. `Path("backend/forms/patterns")`
        # only resolves when pytest is invoked from the repo root, so the test
        # reported a missing index for a directory that has always been there.
        root = Path(__file__).resolve().parents[2] / "forms" / "patterns"
        index = json.loads((root / "index.json").read_text(encoding="utf-8"))
        assert len(index["patterns"]) == 10
        for entry in index["patterns"]:
            p = root / entry["file"]
            assert p.exists(), f"{entry['file']} missing"
            data = json.loads(p.read_text(encoding="utf-8"))
            assert data.get("name") == entry["name"]
            assert "shape" in data
            assert "invariants" in data


# ══════════════════════════════════════════════════════════════════
# M6-T6 — form UX invariants
# ══════════════════════════════════════════════════════════════════


def _write_form_schema(tmp_path: Path, form_root: dict, name: str = "form"):
    sdir = tmp_path / "src" / "schemas"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / f"{name}.json").write_text(json.dumps({
        "schemaVersion": "2", "id": name, "route": f"/{name}",
        "root": form_root,
    }), encoding="utf-8")


class TestFormUxInvariants:
    def test_flag_off_no_op(self, tmp_path, monkeypatch):
        monkeypatch.delenv("FORGE_FORM_UX_INVARIANTS", raising=False)
        result = form_ux_invariants.apply(tmp_path)
        assert result["applied"] is False

    def test_required_marker_star_appended(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_FORM_UX_INVARIANTS", "1")
        _write_form_schema(tmp_path, {
            "type": "Form", "props": {"submitLabel": "Save"}, "children": [
                {"type": "Input", "props": {"label": "Email", "required": True}}
            ],
        })
        result = form_ux_invariants.apply(tmp_path)
        assert result["applied"] is True
        page = json.loads((tmp_path / "src" / "schemas" / "form.json").read_text(encoding="utf-8"))
        inp = page["root"]["children"][0]
        assert inp["props"]["label"] == "Email *"

    def test_numeric_input_mode(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_FORM_UX_INVARIANTS", "1")
        _write_form_schema(tmp_path, {
            "type": "Form", "props": {"submitLabel": "Save"}, "children": [
                {"type": "NumberInput", "props": {"label": "Age"}}
            ],
        })
        form_ux_invariants.apply(tmp_path)
        page = json.loads((tmp_path / "src" / "schemas" / "form.json").read_text(encoding="utf-8"))
        assert page["root"]["children"][0]["props"]["inputMode"] == "numeric"

    def test_email_autocomplete_and_inputmode(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_FORM_UX_INVARIANTS", "1")
        _write_form_schema(tmp_path, {
            "type": "Form", "props": {"submitLabel": "Save"}, "children": [
                {"type": "Input", "props": {"label": "Email address", "name": "email"}}
            ],
        })
        form_ux_invariants.apply(tmp_path)
        page = json.loads((tmp_path / "src" / "schemas" / "form.json").read_text(encoding="utf-8"))
        props = page["root"]["children"][0]["props"]
        assert props["inputMode"] == "email"
        assert props["autoComplete"] == "email"

    def test_submit_button_disabled_while_submitting(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_FORM_UX_INVARIANTS", "1")
        _write_form_schema(tmp_path, {
            "type": "Form", "props": {"submitLabel": "Save"}, "children": [
                {"type": "Button", "props": {"label": "Save", "submit": True}}
            ],
        })
        form_ux_invariants.apply(tmp_path)
        page = json.loads((tmp_path / "src" / "schemas" / "form.json").read_text(encoding="utf-8"))
        assert page["root"]["children"][0]["props"]["disabledWhileSubmitting"] is True
        assert page["root"]["children"][0]["props"]["noDoubleSubmit"] is True

    def test_generic_cta_verb_rewritten(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_FORM_UX_INVARIANTS", "1")
        _write_form_schema(tmp_path, {
            "type": "Form", "props": {"submitLabel": "OK"}, "children": [
                {"type": "Button", "props": {"label": "Submit", "submit": True}}
            ],
        })
        form_ux_invariants.apply(tmp_path)
        page = json.loads((tmp_path / "src" / "schemas" / "form.json").read_text(encoding="utf-8"))
        btn = page["root"]["children"][0]
        assert btn["props"]["label"] == "Save"

    def test_placeholder_no_label_flagged(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_FORM_UX_INVARIANTS", "1")
        _write_form_schema(tmp_path, {
            "type": "Form", "props": {"submitLabel": "Save"}, "children": [
                {"type": "Input", "props": {"placeholder": "Email"}}
            ],
        })
        result = form_ux_invariants.apply(tmp_path)
        rules = {f["rule"] for f in result["findings"]}
        assert "form_ux.placeholder_not_label" in rules
        # missing-label also flagged
        assert "form_ux.field_missing_label" in rules

    def test_pages_without_forms_untouched(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_FORM_UX_INVARIANTS", "1")
        _write_form_schema(tmp_path, {
            "type": "Stack", "children": [{"type": "Table", "props": {"dataSource": "x"}}],
        }, name="list")
        result = form_ux_invariants.apply(tmp_path)
        assert result["fixed"] == 0
        assert result["files"] == 0


# ══════════════════════════════════════════════════════════════════
# M6-T8 — enforcement trigger
# ══════════════════════════════════════════════════════════════════


class TestCriticEnforcementTrigger:
    def test_flag_off_no_shape_not_enforced(self, monkeypatch):
        monkeypatch.delenv("FORGE_CRITIC_PANEL", raising=False)
        assert critic_panel.enforcement_active({}) is False

    def test_single_session_triggers(self, monkeypatch):
        monkeypatch.delenv("FORGE_CRITIC_PANEL", raising=False)
        plan = {"app_shape": {"identity": {"usageMode": "single-session"}}}
        assert critic_panel.enforcement_active(plan) is True

    def test_public_anonymous_triggers(self, monkeypatch):
        monkeypatch.delenv("FORGE_CRITIC_PANEL", raising=False)
        plan = {"app_shape": {"identity": {"usageMode": "public-anonymous"}}}
        assert critic_panel.enforcement_active(plan) is True

    def test_hero_present_triggers(self, monkeypatch):
        monkeypatch.delenv("FORGE_CRITIC_PANEL", raising=False)
        plan = {"app_shape": {"layout": {"hero": "media-hero"}}}
        assert critic_panel.enforcement_active(plan) is True

    def test_workspace_hero_none_not_triggered(self, monkeypatch):
        monkeypatch.delenv("FORGE_CRITIC_PANEL", raising=False)
        plan = {
            "app_shape": {
                "identity": {"usageMode": "multi-user-team"},
                "layout": {"hero": "none"},
            },
        }
        assert critic_panel.enforcement_active(plan) is False

    def test_flag_forces_on(self, monkeypatch):
        monkeypatch.setenv("FORGE_CRITIC_PANEL", "1")
        assert critic_panel.enforcement_active({}) is True

    def test_revise_notes_from_failing_panel(self, monkeypatch):
        monkeypatch.setenv("FORGE_CRITIC_PANEL", "1")
        from services import session_context as sc
        sc.set_current(None)
        page = {"root": {"type": "Stack", "children": [
            {"type": "Form", "children": [{"type": "Input"}]},  # no submit — error
        ]}}
        report = critic_panel.run_panel(page, {}, "/x")
        notes = report.revise_notes()
        assert "Design critic findings" in notes
        assert "ux critic" in notes
        assert "form_missing_submit" in notes

    def test_max_revise_attempts_constant(self):
        assert critic_panel.MAX_REVISE_ATTEMPTS == 2


# ══════════════════════════════════════════════════════════════════
# M6-T9 — rubric + score
# ══════════════════════════════════════════════════════════════════


class TestDesignCriticRubric:
    def test_clean_page_scores_high(self):
        aesthetic_profile_picker.clear_cache()
        plan = {"aesthetic_profile": "carbon"}
        page = {
            "root": {"type": "Stack", "children": [
                {"type": "Card", "props": {"style": {
                    "background": "hsl(var(--card))", "color": "hsl(var(--card-foreground))",
                    "borderColor": "hsl(var(--border))",
                }}, "children": [
                    {"type": "Heading", "props": {"style": {"color": "hsl(var(--foreground))"}}},
                    {"type": "Button", "props": {"variant": "primary", "style": {
                        "background": "hsl(var(--primary))", "color": "hsl(var(--primary-foreground))",
                    }}},
                    {"type": "Text", "props": {"style": {"color": "hsl(var(--muted-foreground))",
                                                          "background": "hsl(var(--muted))"}}},
                ]},
                {"type": "Card", "props": {"style": {"background": "hsl(var(--background))"}}},
                {"type": "Text", "props": {"style": {
                    "color": "#ff5533", "background": "#22aa88",
                    "borderColor": "#4477ee", "outline": "#dd9922",
                }}},
            ]},
        }
        score = critic_personas.design_critic_score(page, plan, "/x")
        assert score >= 70

    def test_bare_page_scores_low(self):
        aesthetic_profile_picker.clear_cache()
        plan = {"aesthetic_profile": "carbon"}
        page = {"root": {"type": "Stack"}}
        score = critic_personas.design_critic_score(page, plan, "/x")
        assert score < 100

    def test_missing_hero_at_landing_flags(self):
        plan = {"app_shape": {"layout": {"hero": "media-hero"}}}
        page = {"root": {"type": "Stack", "children": [{"type": "Text"}]}}
        findings = critic_personas.design_critique(page, plan, "/")
        assert any(f["rule"] == "design.hero_missing_at_landing" for f in findings)

    def test_low_palette_diversity_flags(self):
        aesthetic_profile_picker.clear_cache()
        page = {"root": {"type": "Stack", "children": [
            {"type": "Card", "props": {"style": {"color": "#000000", "background": "#ffffff"}}},
        ]}}
        findings = critic_personas.design_critique(page, {}, "/x")
        assert any(f["rule"] == "design.rubric.palette_diversity_low" for f in findings)

    def test_shadcn_class_overlap_flags(self):
        aesthetic_profile_picker.clear_cache()
        page = {"root": {"type": "Stack", "props": {"className": "bg-background text-foreground border-border bg-card"}}}
        findings = critic_personas.design_critique(page, {}, "/x")
        # All 4 classes are baseline → 0% diversity → flagged
        assert any(f["rule"] == "design.rubric.class_diversity_low" for f in findings)
