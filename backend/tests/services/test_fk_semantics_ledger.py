"""Tests for the decision-ledger instrumentation in fk_semantics.

Covers the three confidence bands the FK resolver produces:
- high: exact norm-match on a single candidate
- medium: norm-collision (multiple entities share the same normalized name)
- low: no exact match, only fuzzy near-misses
"""
from __future__ import annotations

from pathlib import Path

from services.decision_ledger import (
    BAND_HIGH, BAND_LOW, BAND_MEDIUM, KIND_FK_TARGET, load_ledger,
)
from services.fk_semantics import (
    _resolve_target_verbose, classify_registry,
)


# ── _resolve_target_verbose: pure resolver ─────────────────────────

def test_resolve_target_verbose_exact_match_no_alternatives():
    reg = {"entities": {
        "User": {"name": "User", "slug": "users", "table": "users"},
        "Post": {"name": "Post", "slug": "posts", "table": "posts"},
    }}
    picked, alts = _resolve_target_verbose(reg, "User")
    assert picked is not None
    assert picked["name"] == "User"
    assert alts == []


def test_resolve_target_verbose_norm_collision_records_alternatives():
    """Two entities normalize to the same `_norm(owner)` — the losing
    candidate becomes a runner-up alternative (silent ambiguity)."""
    reg = {"entities": {
        "Owner":  {"name": "Owner",  "slug": "owner"},
        "OWNER":  {"name": "OWNER",  "slug": "owner"},
    }}
    picked, alts = _resolve_target_verbose(reg, "owner")
    assert picked is not None
    assert len(alts) == 1
    assert alts[0]["score"] == 1.0
    assert "same _norm" in alts[0]["reason"]


def test_resolve_target_verbose_no_match_returns_fuzzy_candidates():
    reg = {"entities": {
        "Reviewer":  {"name": "Reviewer",  "slug": "reviewers"},
        "Recruiter": {"name": "Recruiter", "slug": "recruiters"},
        "Post":      {"name": "Post",      "slug": "posts"},
    }}
    picked, alts = _resolve_target_verbose(reg, "reviwer")  # typo
    assert picked is None
    assert alts  # at least one candidate
    # closest match sorts first
    assert alts[0]["target"] == "Reviewer"


def test_resolve_target_verbose_empty_reg_returns_nothing():
    assert _resolve_target_verbose({"entities": {}}, "anything") == (None, [])


def test_resolve_target_verbose_empty_fk_returns_nothing():
    assert _resolve_target_verbose({"entities": {"x": {"name": "x"}}}, "") == (None, [])


# ── classify_registry: ledger side-effect ──────────────────────────

def test_classify_registry_records_high_confidence_for_exact_match(tmp_path: Path):
    """Every FK column that resolves cleanly writes a HIGH band row —
    audit trail even when silent."""
    (tmp_path / "src" / "contracts").mkdir(parents=True)
    (tmp_path / "src" / "contracts" / "plan.json").write_text("{}", encoding="utf-8")

    reg = {
        "entities": {
            "Post": {
                "name": "Post", "slug": "posts", "table": "posts",
                "columns": [
                    {"name": "authorId", "type": "uuid", "fk": "User"},
                ],
            },
            "User": {"name": "User", "slug": "users", "table": "users"},
        },
    }
    classify_registry(reg, str(tmp_path))
    ledger = load_ledger(str(tmp_path))
    fk_rows = [r for r in ledger if r["kind"] == KIND_FK_TARGET]
    assert len(fk_rows) == 1
    assert fk_rows[0]["confidence"] == BAND_HIGH
    assert fk_rows[0]["target_picked"] == "User"
    assert fk_rows[0]["identity"] == "authorId"
    assert "entity:Post" in fk_rows[0]["scope"]


def test_classify_registry_medium_band_on_norm_collision(tmp_path: Path):
    """Two entities normalize to the same key — the losing candidate
    surfaces as an alternative at MEDIUM band."""
    (tmp_path / "src" / "contracts").mkdir(parents=True)
    (tmp_path / "src" / "contracts" / "plan.json").write_text("{}", encoding="utf-8")

    reg = {
        "entities": {
            "Post": {
                "name": "Post",
                "columns": [{"name": "ownerId", "type": "uuid", "fk": "owner"}],
            },
            "Owner": {"name": "Owner", "slug": "owner"},
            "OWNER": {"name": "OWNER", "slug": "owner"},
        },
    }
    classify_registry(reg, str(tmp_path))
    ledger = load_ledger(str(tmp_path))
    fk_rows = [r for r in ledger if r["kind"] == KIND_FK_TARGET]
    assert len(fk_rows) == 1
    assert fk_rows[0]["confidence"] == BAND_MEDIUM
    assert len(fk_rows[0]["alternatives"]) >= 1


def test_classify_registry_low_band_on_no_match(tmp_path: Path):
    """FK ref doesn't hit any entity — LOW band with fuzzy suggestions
    so the user gets 'did you mean?'."""
    (tmp_path / "src" / "contracts").mkdir(parents=True)
    (tmp_path / "src" / "contracts" / "plan.json").write_text("{}", encoding="utf-8")

    reg = {
        "entities": {
            "Post": {
                "name": "Post",
                "columns": [{"name": "authorId", "type": "uuid", "fk": "Autor"}],
            },
            "Author":    {"name": "Author"},
            "Publisher": {"name": "Publisher"},
        },
    }
    classify_registry(reg, str(tmp_path))
    ledger = load_ledger(str(tmp_path))
    fk_rows = [r for r in ledger if r["kind"] == KIND_FK_TARGET]
    assert len(fk_rows) == 1
    assert fk_rows[0]["confidence"] == BAND_LOW
    assert fk_rows[0]["target_picked"].startswith("unresolved:")
    # Author is close to "Autor" — should appear as alternative
    assert any(a["target"] == "Author" for a in fk_rows[0]["alternatives"])


def test_classify_registry_no_output_dir_no_ledger_writes(tmp_path: Path):
    """When output_dir isn't given, classify still works but writes no
    ledger rows — pure classifier mode for callers that don't want IO."""
    reg = {
        "entities": {
            "Post": {"name": "Post",
                     "columns": [{"name": "authorId", "fk": "User"}]},
            "User": {"name": "User"},
        },
    }
    classify_registry(reg, None)  # no output_dir
    assert load_ledger(str(tmp_path)) == []
