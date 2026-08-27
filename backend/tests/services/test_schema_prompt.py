"""Tests for schema_prompt.py — design context + gold-example injection."""
import json
from pathlib import Path
import pytest


class TestRenderTokenPaths:
    """render_token_paths walks defaultTokens, emits one path per leaf."""

    def test_returns_string_with_token_paths(self):
        from services.schema_prompt import render_token_paths
        # Realistic defaultTokens shape
        sample = {
            "color": {
                "primary": {"50": "#fff", "500": "#ccc", "950": "#111"},
                "surface": {"0": "#fff"},
                "text": {"primary": "#000"},
            },
            "spacing": {"4": "1rem", "semantic": {"page": "2rem"}},
            "radius": {"sm": "4px"},
        }
        out = render_token_paths(sample)
        assert "tokens.color.primary.50" in out
        assert "tokens.color.primary.500" in out
        assert "tokens.color.primary.950" in out
        assert "tokens.color.surface.0" in out
        assert "tokens.color.text.primary" in out
        assert "tokens.spacing.4" in out
        assert "tokens.spacing.semantic.page" in out
        assert "tokens.radius.sm" in out

    def test_skips_non_dict_branches(self):
        from services.schema_prompt import render_token_paths
        # Only leaves should appear — branches (objects with sub-objects) should not
        out = render_token_paths({"color": {"primary": {"500": "#xx"}}})
        # "tokens.color" alone (the branch) should NOT appear
        # "tokens.color.primary" alone (the branch) should NOT appear
        # Only the leaf path should
        assert "tokens.color.primary.500" in out
        # Sanity: the branch-only path is absent
        assert "\ntokens.color\n" not in out
        assert "\ntokens.color.primary\n" not in out


class TestLoadGoldExample:
    """load_gold_example reads schema_examples/<page_type>/<archetype>.json."""

    def test_loads_existing_example(self):
        from services.schema_prompt import load_gold_example
        # The plan ships card-grid for list — this should load
        result = load_gold_example("list", "card-grid")
        assert result is not None
        assert "schemaVersion" in result
        assert result["schemaVersion"] == "2"

    def test_returns_none_for_unknown_archetype(self):
        from services.schema_prompt import load_gold_example
        result = load_gold_example("list", "made-up-archetype")
        # Should fall back to first available list example, NOT None
        # (per plan §5.4: unknown archetype → first example fallback)
        assert result is not None
        assert "schemaVersion" in result

    def test_returns_none_for_unknown_page_type(self):
        from services.schema_prompt import load_gold_example
        # Unknown page-type entirely (no fallback possible)
        result = load_gold_example("nonexistent", "any")
        assert result is None


class TestBuildSchemaPrompt:
    """build_schema_prompt assembles the full LLM prompt."""

    def test_minimum_plan_produces_valid_string(self):
        from services.schema_prompt import build_schema_prompt
        plan = {
            "description": "leave management",
            "entity": {"name": "LeaveRequest", "fields": []},
            "page_type": "list",
        }
        prompt = build_schema_prompt(plan)
        assert isinstance(prompt, str)
        assert len(prompt) > 100

    def test_includes_token_paths_section(self):
        from services.schema_prompt import build_schema_prompt
        plan = {
            "description": "x",
            "entity": {"name": "X", "fields": []},
            "page_type": "list",
        }
        prompt = build_schema_prompt(plan)
        # Token paths section must be present
        assert "tokens.color.primary.500" in prompt
        assert "tokens.spacing" in prompt

    def test_includes_design_rationale_when_present(self, tmp_path, monkeypatch):
        """If output_dir/src/contracts/design-spec.json exists, include the rationale."""
        from services.schema_prompt import build_schema_prompt
        # Create a temp output_dir with a design-spec.json
        contracts_dir = tmp_path / "src" / "contracts"
        contracts_dir.mkdir(parents=True)
        spec = {"designRationale": "Trustworthy fintech with deep blue + crisp typography."}
        (contracts_dir / "design-spec.json").write_text(json.dumps(spec))

        plan = {
            "description": "x",
            "entity": {"name": "X", "fields": []},
            "page_type": "list",
            "_output_dir": str(tmp_path),  # convention: pass via plan dict
        }
        prompt = build_schema_prompt(plan)
        assert "Trustworthy fintech" in prompt

    def test_includes_gold_example_for_archetype(self):
        from services.schema_prompt import build_schema_prompt
        plan = {
            "description": "x",
            "entity": {"name": "X", "fields": []},
            "page_type": "list",
            "archetype": "card-grid",
        }
        prompt = build_schema_prompt(plan)
        # Gold example schemaVersion should appear in prompt
        assert "schemaVersion" in prompt
        # Card-grid example uses Hero with gradient — check a fingerprint
        assert "Hero" in prompt

    def test_falls_back_to_first_archetype_when_unknown(self):
        from services.schema_prompt import build_schema_prompt
        plan = {
            "description": "x",
            "entity": {"name": "X", "fields": []},
            "page_type": "list",
            "archetype": "doesnt-exist",
        }
        # Should not raise
        prompt = build_schema_prompt(plan)
        assert isinstance(prompt, str)
        assert len(prompt) > 100

    def test_includes_library_component_list(self):
        from services.schema_prompt import build_schema_prompt
        plan = {
            "description": "x",
            "entity": {"name": "X", "fields": []},
            "page_type": "list",
        }
        prompt = build_schema_prompt(plan)
        # Library descriptor should mention key components
        for component in ["Hero", "Section", "MetricTile", "Button"]:
            assert component in prompt


def test_build_schema_prompt_without_grounding_returns_string():
    """Calling without page_brief should not crash."""
    from services.schema_prompt import build_schema_prompt
    plan = {"appName": "Test", "description": "test app", "entities": []}
    prompt = build_schema_prompt(plan)
    assert isinstance(prompt, str)
    assert len(prompt) > 100


def test_build_schema_prompt_with_no_exemplars_skips_block(monkeypatch):
    """When no exemplars exist for the cell, no exemplar block is added."""
    monkeypatch.setattr("services.schema_prompt.load_exemplars", lambda *a, **kw: [])
    from services.schema_prompt import build_schema_prompt
    plan = {"appName": "Test", "description": "test app", "entities": []}
    prompt = build_schema_prompt(plan, page_brief={"route": "/users/list"}, domain="healthcare")
    assert "REFERENCE EXEMPLARS" not in prompt


def test_build_schema_prompt_with_exemplars_includes_block(monkeypatch):
    from services.reference_bank import Exemplar
    from services.schema_prompt import build_schema_prompt
    fake = Exemplar(
        schema={"id": "x", "schemaVersion": "2"},
        score=8.4,
        meta={}, domain="healthcare", page_type="list", file_stem="exemplar_01",
    )
    monkeypatch.setattr("services.schema_prompt.load_exemplars", lambda *a, **kw: [fake])
    plan = {"appName": "Test", "description": "test app", "entities": []}
    prompt = build_schema_prompt(plan, page_brief={"route": "/users/list"}, domain="healthcare")
    assert "REFERENCE EXEMPLARS" in prompt
    assert "8.4" in prompt


# ── Color guardrails ─────────────────────────────────────────────────────────

class TestColorRules:
    """COLOR_RULES block must appear in every prompt produced by build_schema_prompt."""

    def _make_prompt(self, **kwargs):
        from services.schema_prompt import build_schema_prompt
        plan = {
            "description": "leave management",
            "entity": {"name": "LeaveRequest", "fields": []},
            "page_type": "list",
            **kwargs,
        }
        return build_schema_prompt(plan)

    def test_color_rules_present_in_every_prompt(self):
        """The color rules heading must appear unconditionally."""
        prompt = self._make_prompt()
        assert "Color Rules" in prompt
        assert "STRICT" in prompt

    def test_forbidden_palette_classes_listed(self):
        """Forbidden classes (purple, blue, pink, etc.) must be named explicitly."""
        prompt = self._make_prompt()
        assert "bg-purple-*" in prompt
        assert "bg-blue-*" in prompt
        assert "bg-pink-*" in prompt

    def test_semantic_token_guidance_present(self):
        """Acceptable semantic token classes (bg-primary etc.) must be listed."""
        prompt = self._make_prompt()
        assert "bg-primary" in prompt
        assert "bg-muted" in prompt

    def test_color_rules_present_for_dashboard_page_type(self):
        """Color rules still appear for dashboard page type."""
        prompt = self._make_prompt(page_type="dashboard")
        assert "Color Rules" in prompt

    def test_color_rules_present_for_form_page_type(self):
        """Color rules still appear for form page type."""
        prompt = self._make_prompt(page_type="form")
        assert "Color Rules" in prompt

    def test_responsive_rules_in_prompt(self):
        """Responsive Rules section must appear in the schema prompt."""
        prompt = self._make_prompt(page_type="list")
        assert "Responsive Rules" in prompt

    def test_responsive_rules_mention_columns_prop(self):
        """Prompt must teach LLM to use columns prop (not hardcoded className)."""
        prompt = self._make_prompt(page_type="dashboard")
        assert "columns" in prompt
        assert "grid-cols-3" in prompt or "hardcoded" in prompt.lower()

    def test_responsive_rules_forbid_fixed_px_widths(self):
        """Prompt must warn against fixed-px container widths."""
        prompt = self._make_prompt(page_type="detail")
        assert "w-[400px]" in prompt or "fixed px" in prompt.lower()
