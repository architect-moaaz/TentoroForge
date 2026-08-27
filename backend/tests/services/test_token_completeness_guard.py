"""Tests for token_completeness_guard.

Guards the invariant that after this pass runs, no library component
that reads a token subtree unconditionally can NPE on a JSON emitted
by the design pipeline.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.token_completeness_guard import (
    apply_token_completeness_guard,
    ensure_token_completeness,
)


class TestEnsureTokenCompleteness:
    def test_fills_empty_typography(self):
        spec = {"typography": {}}
        added = ensure_token_completeness(spec)
        assert added > 0
        # MetricTile reads these two:
        assert spec["typography"]["numeric"]["family"]
        assert "tabular" in spec["typography"]["numeric"]

    def test_fills_missing_typography_entirely(self):
        spec = {"colorPalette": {"primary": "#000"}}
        added = ensure_token_completeness(spec)
        assert added > 0
        assert "typography" in spec
        assert "numeric" in spec["typography"]

    def test_fills_empty_spacing_semantic(self):
        spec = {"spacing": {}}
        added = ensure_token_completeness(spec)
        assert added > 0
        assert spec["spacing"]["semantic"]["card"]
        assert spec["spacing"]["semantic"]["page"]

    def test_preserves_existing_values(self):
        # Existing values must not be clobbered — this guard is purely
        # additive, otherwise a design edit would silently reset.
        spec = {
            "typography": {
                "numeric": {"family": "Roboto Mono", "tabular": False},
            }
        }
        added = ensure_token_completeness(spec)
        assert spec["typography"]["numeric"]["family"] == "Roboto Mono"
        assert spec["typography"]["numeric"]["tabular"] is False
        # Other subtrees still get filled.
        assert added > 0

    def test_replaces_non_dict_subtree(self):
        # A list-shaped `typography: []` (LLM occasionally emits this) is
        # just as dangerous as missing — property access still crashes.
        spec: dict = {"typography": []}
        ensure_token_completeness(spec)
        assert isinstance(spec["typography"], dict)
        assert "numeric" in spec["typography"]

    def test_returns_zero_when_already_complete(self):
        spec = {
            "typography": {
                "numeric": {"family": "Foo", "tabular": True},
                "display": {"family": "Foo", "weight": 700},
                "bodyText": {"family": "Foo", "weight": 400, "lineHeight": 1.5},
            },
            "spacing": {
                # Numeric scale is part of "complete" now — Cluster resolves
                # `tokens.spacing.N` via inline var(--token-spacing-N), and a
                # missing key collapses gaps to `normal` app-wide.
                "0": "0px", "1": "0.25rem", "2": "0.5rem", "3": "0.75rem",
                "4": "1rem", "5": "1.25rem", "6": "1.5rem", "8": "2rem",
                "10": "2.5rem", "12": "3rem", "16": "4rem",
                "semantic": {
                    "page": "1rem", "card": "1rem", "section": "2rem",
                    "element": "0.5rem", "input": "0.5rem",
                }
            },
        }
        assert ensure_token_completeness(spec) == 0

    def test_non_dict_input_is_noop(self):
        # Guard mustn't crash on a garbage top-level (e.g. a list emitted by
        # a broken read). The higher-level file entry point catches this too
        # but the pure helper should be safe standalone.
        assert ensure_token_completeness([]) == 0  # type: ignore[arg-type]
        assert ensure_token_completeness(None) == 0  # type: ignore[arg-type]


class TestApplyTokenCompletenessGuard:
    def _write(self, root: Path, rel: str, data: dict) -> Path:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return p

    def test_backfills_design_spec(self, tmp_path: Path):
        self._write(tmp_path, "src/contracts/design-spec.json", {"typography": {}})
        report = apply_token_completeness_guard(tmp_path)
        assert report["total_keys_added"] > 0
        assert "src/contracts/design-spec.json" in report["files_touched"]

        with open(tmp_path / "src/contracts/design-spec.json") as f:
            data = json.load(f)
        assert data["typography"]["numeric"]["family"]

    def test_backfills_tokens_custom(self, tmp_path: Path):
        # tokens.custom.json is what the visual-editor writes; the design
        # editor can strip keys, so this file is a real risk surface even
        # when design-spec was fine.
        self._write(tmp_path, "src/theme/tokens.custom.json", {})
        report = apply_token_completeness_guard(tmp_path)
        assert report["total_keys_added"] > 0
        assert "src/theme/tokens.custom.json" in report["files_touched"]

    def test_leaves_complete_file_untouched(self, tmp_path: Path):
        complete = {
            "typography": {
                "numeric": {"family": "X", "tabular": True},
                "display": {"family": "X", "weight": 700},
                "bodyText": {"family": "X", "weight": 400, "lineHeight": 1.5},
            },
            "spacing": {
                # Numeric scale is part of "complete" now — Cluster resolves
                # `tokens.spacing.N` via inline var(--token-spacing-N), and a
                # missing key collapses gaps to `normal` app-wide.
                "0": "0px", "1": "0.25rem", "2": "0.5rem", "3": "0.75rem",
                "4": "1rem", "5": "1.25rem", "6": "1.5rem", "8": "2rem",
                "10": "2.5rem", "12": "3rem", "16": "4rem",
                "semantic": {
                    "page": "1rem", "card": "1rem", "section": "2rem",
                    "element": "0.5rem", "input": "0.5rem",
                }
            },
        }
        path = self._write(tmp_path, "src/contracts/design-spec.json", complete)
        mtime_before = path.stat().st_mtime_ns
        report = apply_token_completeness_guard(tmp_path)
        assert report["total_keys_added"] == 0
        assert report["files_touched"] == []
        # No write means mtime unchanged — cheap regression against
        # spurious rewrites clobbering downstream cache heuristics.
        assert path.stat().st_mtime_ns == mtime_before

    def test_missing_output_dir_is_noop(self, tmp_path: Path):
        # Deploy pipeline calls this on any given root; a non-existent path
        # must degrade silently rather than raise.
        report = apply_token_completeness_guard(tmp_path / "does-not-exist")
        assert report["total_keys_added"] == 0

    def test_malformed_json_is_skipped(self, tmp_path: Path):
        p = tmp_path / "src/contracts/design-spec.json"
        p.parent.mkdir(parents=True)
        p.write_text("{ this is not json", encoding="utf-8")
        report = apply_token_completeness_guard(tmp_path)
        # Skips gracefully, doesn't crash the whole guard suite.
        assert report["total_keys_added"] == 0
