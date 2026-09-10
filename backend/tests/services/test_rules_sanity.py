"""Tests for services.rules_sanity — self-clobbering computed rules."""
from __future__ import annotations

import json
from pathlib import Path

from services.rules_sanity import sanitize_rules


def _mk(tmp_path: Path, rules: list) -> Path:
    root = tmp_path / "app"
    p = root / "src" / "rules" / "index.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rules), encoding="utf-8")
    return root


def _rules(root: Path) -> list:
    return json.loads((root / "src" / "rules" / "index.json").read_text(encoding="utf-8"))


_CLOBBER = {
    "name": "document-confidence-tier-computed",
    "rule_type": "computed",
    "model_name": "Document",
    "field_name": "confidenceScore",
    "config": {"expression":
               'if confidenceScore >= 0.85 then "high" else "low"'},
    "is_active": True,
}


def test_self_clobbering_computed_rule_deactivated(tmp_path: Path):
    root = _mk(tmp_path, [_CLOBBER])
    rep = sanitize_rules(root)
    assert rep["summary"]["deactivated"] == 1
    assert _rules(root)[0]["is_active"] is False


def test_type_stable_computed_rule_kept(tmp_path: Path):
    """`total = price * quantity` doesn't read total — perfectly fine."""
    rule = {"name": "order-total", "rule_type": "computed",
            "field_name": "total",
            "config": {"expression": "price * quantity"},
            "is_active": True}
    root = _mk(tmp_path, [rule])
    rep = sanitize_rules(root)
    assert rep["summary"]["deactivated"] == 0
    assert _rules(root)[0]["is_active"] is True


def test_validation_rules_untouched(tmp_path: Path):
    rule = {"name": "range", "rule_type": "validation",
            "field_name": "confidenceScore",
            "config": {"min": 0, "max": 1}, "is_active": True}
    root = _mk(tmp_path, [rule])
    assert sanitize_rules(root)["summary"]["deactivated"] == 0


def test_missing_file_no_crash(tmp_path: Path):
    assert sanitize_rules(tmp_path / "nope")["summary"]["deactivated"] == 0
