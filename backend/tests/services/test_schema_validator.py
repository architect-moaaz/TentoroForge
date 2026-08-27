"""Tests for the post-Zod token-path validator."""
import pytest


class TestCollectTokenRefs:
    """walk a schema, return list of (path, ref) tuples."""

    def test_finds_refs_in_style_block(self):
        from services.schema_validator import collect_token_refs
        schema = {
            "schemaVersion": "2",
            "root": {
                "type": "Stack",
                "style": {
                    "padding": "tokens.spacing.4",
                    "background": {
                        "type": "gradient",
                        "from": "tokens.color.primary.50",
                        "to": "tokens.color.surface.0",
                    },
                },
            },
        }
        refs = collect_token_refs(schema)
        ref_values = [r for _, r in refs]
        assert "tokens.spacing.4" in ref_values
        assert "tokens.color.primary.50" in ref_values
        assert "tokens.color.surface.0" in ref_values

    def test_finds_nested_refs(self):
        from services.schema_validator import collect_token_refs
        schema = {
            "root": {
                "type": "Stack",
                "children": [
                    {"type": "Hero", "style": {"radius": "tokens.radius.lg"}},
                    {"type": "Section", "style": {"shadow": "tokens.shadow.md"}},
                ],
            },
        }
        refs = collect_token_refs(schema)
        ref_values = [r for _, r in refs]
        assert "tokens.radius.lg" in ref_values
        assert "tokens.shadow.md" in ref_values

    def test_ignores_non_token_strings(self):
        from services.schema_validator import collect_token_refs
        schema = {
            "root": {
                "type": "Hero",
                "props": {"headline": "Hello", "layout": "centered"},
                "style": {"padding": "tokens.spacing.4"},
            },
        }
        refs = collect_token_refs(schema)
        ref_values = [r for _, r in refs]
        assert "Hello" not in ref_values
        assert "centered" not in ref_values
        assert "tokens.spacing.4" in ref_values


class TestPathExistsIn:
    """path_exists_in(ref, tokens_dict) — does the path resolve to a leaf?"""

    def test_existing_path_returns_true(self):
        from services.schema_validator import path_exists_in
        tokens = {"color": {"primary": {"500": "#3b82f6"}}}
        assert path_exists_in("tokens.color.primary.500", tokens) is True

    def test_missing_namespace_returns_false(self):
        from services.schema_validator import path_exists_in
        tokens = {"color": {"primary": {"500": "#3b82f6"}}}
        assert path_exists_in("tokens.color.brand.500", tokens) is False

    def test_missing_stop_returns_false(self):
        from services.schema_validator import path_exists_in
        tokens = {"color": {"primary": {"500": "#3b82f6"}}}
        assert path_exists_in("tokens.color.primary.450", tokens) is False

    def test_branch_only_path_returns_false(self):
        """tokens.color.primary alone (without a stop) is a branch — not a leaf."""
        from services.schema_validator import path_exists_in
        tokens = {"color": {"primary": {"500": "#3b82f6"}}}
        assert path_exists_in("tokens.color.primary", tokens) is False

    def test_handles_invalid_format(self):
        from services.schema_validator import path_exists_in
        tokens = {"color": {"primary": {"500": "#3b82f6"}}}
        # Not starting with tokens.
        assert path_exists_in("color.primary.500", tokens) is False


class TestValidateTokenRefs:
    """validate_token_refs returns (valid_count, invalid_refs)."""

    def test_all_valid(self):
        from services.schema_validator import validate_token_refs
        tokens = {"color": {"primary": {"500": "#3b82f6"}}, "spacing": {"4": "1rem"}}
        schema = {
            "root": {
                "type": "Stack",
                "style": {
                    "padding": "tokens.spacing.4",
                    "background": {"type": "solid", "value": "tokens.color.primary.500"},
                },
            },
        }
        valid, invalid = validate_token_refs(schema, tokens)
        assert valid == 2
        assert invalid == []

    def test_some_invalid(self):
        from services.schema_validator import validate_token_refs
        tokens = {"color": {"primary": {"500": "#3b82f6"}}}
        schema = {
            "root": {
                "type": "Stack",
                "style": {
                    "padding": "tokens.spacing.4",  # invalid: spacing missing
                    "background": {"type": "solid", "value": "tokens.color.primary.500"},  # valid
                },
            },
        }
        valid, invalid = validate_token_refs(schema, tokens)
        assert valid == 1
        assert len(invalid) == 1
        assert invalid[0][1] == "tokens.spacing.4"

    def test_invalid_pct_helper(self):
        from services.schema_validator import invalid_ref_pct
        # 1 valid, 3 invalid → 75%
        assert invalid_ref_pct(1, 3) == 75.0
        # 0 invalid → 0%
        assert invalid_ref_pct(5, 0) == 0.0
        # No refs at all → 0% (don't divide by zero)
        assert invalid_ref_pct(0, 0) == 0.0
