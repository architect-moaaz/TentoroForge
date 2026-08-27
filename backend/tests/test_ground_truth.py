"""Ground-truth verification.

Spec: §7 and §11 of the Smith-as-architect spec.

The whole point of this module is that Smith's post-turn verification
runs against **the working tree**, not against Smith's self-reported
`edited_paths`. Today's session showed exactly how the self-report
path fails: Smith claims one file, edits another, and the orchestrator
believes the claim. This module is the answer.

Contract tests cover:
  * `git_status_modified` — real disk truth (staged + unstaged, no
    untracked-mode surprises)
  * `git_diff_lines` — the actual `-U1` diff a relevance check can grep
  * `guard_delta` — new-failures-only, filtering baseline noise
  * `probe_form_field` — for "wrong widget on field X" asks
  * `probe_list_binding` — for "list is empty" asks
  * `snapshot_baseline` — start-of-turn capture so `guard_delta` has
    something to diff against

Every helper is pure (input → return value); no state on the module
level. Tests use a real git repo in tmp_path.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from services import ground_truth


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _init_repo(tmp_path: Path) -> Path:
    subprocess.check_call(["git", "init", "-q", str(tmp_path)])
    subprocess.check_call(["git", "-C", str(tmp_path),
                           "config", "user.email", "t@t.t"])
    subprocess.check_call(["git", "-C", str(tmp_path),
                           "config", "user.name", "T"])
    (tmp_path / "seed.txt").write_text("seed")
    subprocess.check_call(["git", "-C", str(tmp_path), "add", "seed.txt"])
    subprocess.check_call(["git", "-C", str(tmp_path),
                           "commit", "-qm", "seed"])
    return tmp_path


# --------------------------------------------------------------------------- #
# git_status_modified
# --------------------------------------------------------------------------- #

def test_git_status_returns_empty_on_clean_tree(tmp_path):
    _init_repo(tmp_path)
    assert ground_truth.git_status_modified(str(tmp_path)) == []


def test_git_status_lists_modified_and_added_and_untracked(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "seed.txt").write_text("changed")           # modified
    (tmp_path / "new1.json").write_text("{}")               # untracked
    subprocess.check_call(["git", "-C", str(tmp_path), "add", "new1.json"])
    (tmp_path / "new2.txt").write_text("hi")                # untracked

    paths = set(ground_truth.git_status_modified(str(tmp_path)))
    assert paths == {"seed.txt", "new1.json", "new2.txt"}


def test_git_status_ignores_dot_git(tmp_path):
    """A stray file inside .git must not surface as a modified path."""
    _init_repo(tmp_path)
    (tmp_path / ".git" / "HEAD.tmp").write_text("junk")
    assert ".git/HEAD.tmp" not in ground_truth.git_status_modified(str(tmp_path))


def test_git_status_on_non_repo_returns_empty(tmp_path):
    """A directory that isn't a git repo returns [] rather than raising —
    Smith's caller shouldn't have to know whether the project is under
    git yet."""
    assert ground_truth.git_status_modified(str(tmp_path)) == []


# --------------------------------------------------------------------------- #
# git_diff_lines
# --------------------------------------------------------------------------- #

def test_git_diff_lines_returns_the_actual_changed_lines(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "schema.json").write_text(json.dumps({
        "field": {"type": "Select", "label": "Upload CV"}
    }, indent=2))
    subprocess.check_call(["git", "-C", str(tmp_path), "add", "schema.json"])
    subprocess.check_call(["git", "-C", str(tmp_path),
                           "commit", "-qm", "add schema"])

    (tmp_path / "schema.json").write_text(json.dumps({
        "field": {"type": "FileUpload", "label": "Upload CV"}
    }, indent=2))

    diff = ground_truth.git_diff_lines(str(tmp_path), ["schema.json"])
    # Diff must contain BOTH the removed Select line and the added
    # FileUpload line, plus the "Upload CV" label context.
    assert "Select" in diff
    assert "FileUpload" in diff
    assert "Upload CV" in diff


def test_git_diff_lines_empty_when_no_paths(tmp_path):
    _init_repo(tmp_path)
    assert ground_truth.git_diff_lines(str(tmp_path), []) == ""


def test_git_diff_lines_swallows_git_failure(tmp_path):
    """Non-git directory or bad path → empty string, not raise."""
    assert ground_truth.git_diff_lines(str(tmp_path), ["nonexistent.txt"]) == ""


# --------------------------------------------------------------------------- #
# guard_delta — regressions only
# --------------------------------------------------------------------------- #

def test_guard_delta_returns_only_new_failure_messages():
    baseline = [
        {"guard": "workflow_mutation_guard",
         "message": "19 mutation values still need a trigger input"},
    ]
    after = [
        {"guard": "workflow_mutation_guard",
         "message": "19 mutation values still need a trigger input"},  # pre-existing
        {"guard": "read_binding_guard",
         "message": "1 unresolved binding on candidates/new.json"},   # NEW
    ]
    delta = ground_truth.guard_delta(baseline, after)
    assert len(delta) == 1
    assert delta[0]["guard"] == "read_binding_guard"


def test_guard_delta_empty_when_after_matches_baseline():
    baseline = [{"guard": "g", "message": "m"}]
    assert ground_truth.guard_delta(baseline, list(baseline)) == []


def test_guard_delta_no_baseline_returns_after_as_delta():
    """First-turn semantics: no baseline recorded ⇒ everything counts."""
    after = [{"guard": "g", "message": "m"}]
    assert ground_truth.guard_delta(None, after) == after


# --------------------------------------------------------------------------- #
# probe_form_field
# --------------------------------------------------------------------------- #

def test_probe_form_field_reports_current_component_and_matches_expected(tmp_path):
    """The probe reads a page schema file and returns the current
    component + a match flag against the expected component."""
    schema = {
        "root": {
            "children": [
                {"type": "Form", "props": {}, "children": [
                    {"type": "Select", "props": {"name": "cv",
                                                 "label": "Upload CV"}},
                    {"type": "Input", "props": {"name": "email"}},
                ]},
            ],
        },
    }
    p = tmp_path / "new.json"
    p.write_text(json.dumps(schema))

    r = ground_truth.probe_form_field(
        schema_path=str(p),
        field_label="Upload CV",
        expected_component="FileUpload",
    )
    assert r["found"] is True
    assert r["current_component"] == "Select"
    assert r["matches_expected"] is False


def test_probe_form_field_returns_matches_when_component_agrees(tmp_path):
    schema = {"root": {"children": [
        {"type": "Form", "children": [
            {"type": "FileUpload", "props": {"name": "cv",
                                             "label": "Upload CV"}},
        ]},
    ]}}
    p = tmp_path / "new.json"
    p.write_text(json.dumps(schema))
    r = ground_truth.probe_form_field(
        schema_path=str(p), field_label="Upload CV",
        expected_component="FileUpload",
    )
    assert r["found"] and r["matches_expected"]


def test_probe_form_field_field_not_found(tmp_path):
    schema = {"root": {"children": [{"type": "Form", "children": []}]}}
    p = tmp_path / "new.json"
    p.write_text(json.dumps(schema))
    r = ground_truth.probe_form_field(
        schema_path=str(p), field_label="Nonexistent Field",
        expected_component="Whatever",
    )
    assert r["found"] is False


def test_probe_form_field_missing_file_reports_not_found(tmp_path):
    r = ground_truth.probe_form_field(
        schema_path=str(tmp_path / "does-not-exist.json"),
        field_label="X", expected_component="Y",
    )
    assert r["found"] is False


# --------------------------------------------------------------------------- #
# probe_list_binding
# --------------------------------------------------------------------------- #

def test_probe_list_binding_finds_datasource_on_a_table(tmp_path):
    schema = {"root": {"children": [
        {"type": "Table", "props": {
            "rows": "{{candidates}}",
            "dataSource": "candidates",
        }},
    ]}}
    p = tmp_path / "list.json"
    p.write_text(json.dumps(schema))
    r = ground_truth.probe_list_binding(
        schema_path=str(p), expected_datasource="candidates",
    )
    assert r["found"] and r["matches_expected"]


def test_probe_list_binding_mismatch(tmp_path):
    schema = {"root": {"children": [
        {"type": "Table", "props": {"dataSource": "assessments"}},
    ]}}
    p = tmp_path / "list.json"
    p.write_text(json.dumps(schema))
    r = ground_truth.probe_list_binding(
        schema_path=str(p), expected_datasource="candidates",
    )
    assert r["found"] and not r["matches_expected"]
    assert r["current_datasource"] == "assessments"


# --------------------------------------------------------------------------- #
# snapshot_baseline — captures {git_status, guard_result} for a turn
# --------------------------------------------------------------------------- #

def test_snapshot_baseline_captures_status_and_guards(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "extra.txt").write_text("pending change")

    def _fake_guards(_out):
        return [{"guard": "g1", "message": "pre-existing"}]

    snap = ground_truth.snapshot_baseline(
        str(tmp_path), guards_fn=_fake_guards,
    )
    assert snap["status"] == ["extra.txt"]
    assert snap["guards"] == [{"guard": "g1", "message": "pre-existing"}]
