"""Ground-truth verification for Smith turns.

Spec: `docs/superpowers/specs/2026-07-17-smith-as-architect.md` §7, §11.

The whole premise of the Smith-as-architect rewrite is that the
system trusts the **working tree** and the **guard suite** as
source-of-truth about what changed and whether anything broke —
never Smith's self-reported bookkeeping. Today's live session made
that gap concrete: Smith claimed one edit path, edited another,
and the orchestrator committed the wrong thing because it trusted
the claim.

This module is the answer. Every function here reads real disk /
real subprocess output and returns plain data. Nothing in here
talks to a model, keeps state, or writes files.

Public surface:

  * :func:`git_status_modified` — every modified / added / untracked
    path in the working tree, relative to the repo root.
  * :func:`git_diff_lines` — the actual `-U1` line-level diff for a
    set of paths. This is what a relevance check greps against
    (fixing the earlier bug where `--stat` output was checked and
    naturally never contained label text).
  * :func:`guard_delta` — filter a post-turn guard list against a
    baseline so only *new* failures reach Smith (§6.6 semantics).
  * :func:`probe_form_field` — for "wrong widget on field X" asks:
    reads the schema, finds the field by label, returns the current
    component + a match verdict against the expected component.
  * :func:`probe_list_binding` — for "list is empty / bound wrong"
    asks: reads the schema, finds the Table, returns the current
    dataSource + a match verdict.
  * :func:`snapshot_baseline` — {status, guards} captured at turn
    start so guard_delta and git_diff_lines have a reference.

Every helper returns something safe for a non-repo / missing file
so callers don't have to guard the call site.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Any, Callable


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# git-based helpers
# --------------------------------------------------------------------------- #

def git_status_modified(output_dir: str) -> list[str]:
    """Every modified/added/untracked path in the working tree.

    Returns paths relative to `output_dir`. Empty list for a
    non-repo directory or on any git failure — the caller shouldn't
    have to know whether the project is versioned yet."""
    if not _is_git_dir(output_dir):
        return []
    try:
        out = subprocess.check_output(
            ["git", "-C", output_dir, "status", "--porcelain=v1"],
            text=True, timeout=15, stderr=subprocess.DEVNULL,
        )
    except Exception:  # noqa: BLE001
        return []

    paths: list[str] = []
    for line in out.splitlines():
        if not line:
            continue
        # porcelain v1: XY <space> path OR XY <space> path -> renamed
        path = line[3:]
        # rename: 'old -> new'
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        # git-quoted paths ("path with spaces") — strip surrounding quotes
        if path.startswith('"') and path.endswith('"'):
            path = path[1:-1]
        if not path.startswith(".git/"):
            paths.append(path)
    return paths


def git_diff_lines(output_dir: str, paths: list[str]) -> str:
    """Actual `-U1` line-level diff for the given paths against HEAD.

    Returns "" when there's nothing to diff, when git fails, or when
    `paths` is empty. The `-U1` context is what a relevance gate
    (§7.4 architect self-review) actually needs — bare labels and
    surrounding lines — as opposed to `--stat` which only prints
    file names + change counts."""
    if not paths or not _is_git_dir(output_dir):
        return ""
    try:
        return subprocess.check_output(
            ["git", "-C", output_dir, "diff", "-U1", "HEAD", "--", *paths],
            text=True, timeout=15, stderr=subprocess.DEVNULL,
        )
    except Exception:  # noqa: BLE001
        return ""


def _is_git_dir(output_dir: str) -> bool:
    return (Path(output_dir) / ".git").is_dir()


# --------------------------------------------------------------------------- #
# Guard delta — regressions only
# --------------------------------------------------------------------------- #

def guard_delta(
    baseline: list[dict[str, Any]] | None,
    after: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return guard failures in `after` that are NOT present in
    `baseline`.

    Matching is by `(guard, message)` pair. `baseline=None` treats
    everything as new (first-turn semantics)."""
    if not baseline:
        return list(after)
    seen: set[tuple[str, str]] = {
        (str(b.get("guard") or ""), str(b.get("message") or ""))
        for b in baseline
    }
    return [
        a for a in after
        if (str(a.get("guard") or ""), str(a.get("message") or "")) not in seen
    ]


# --------------------------------------------------------------------------- #
# Symptom probes — read the actual schema for the ask class
# --------------------------------------------------------------------------- #

def probe_form_field(
    *, schema_path: str, field_label: str, expected_component: str,
) -> dict[str, Any]:
    """Find a Form field by its visible label, return the current
    component name and whether it matches `expected_component`.

    Contract:
      * `{found: False}` when the schema is unreadable or no field
        with that label exists.
      * `{found: True, current_component, matches_expected}` when
        the field is located. `matches_expected` is a
        case-insensitive comparison.
    """
    schema = _load_json(schema_path)
    if schema is None:
        return {"found": False, "reason": f"schema not readable: {schema_path}"}

    hit = _find_field_by_label(schema, field_label)
    if hit is None:
        return {"found": False, "reason": f"no field with label {field_label!r}"}

    current = str(hit.get("type") or "")
    return {
        "found": True,
        "current_component": current,
        "matches_expected": current.lower() == str(expected_component).lower(),
    }


def probe_list_binding(
    *, schema_path: str, expected_datasource: str,
) -> dict[str, Any]:
    """Find a Table node in the schema and report its `dataSource`
    against the expected one."""
    schema = _load_json(schema_path)
    if schema is None:
        return {"found": False, "reason": f"schema not readable: {schema_path}"}

    hit = _find_first_node_of_type(schema, "Table")
    if hit is None:
        return {"found": False, "reason": "no Table node"}

    current = str((hit.get("props") or {}).get("dataSource") or "")
    return {
        "found": True,
        "current_datasource": current,
        "matches_expected": current == expected_datasource,
    }


# --------------------------------------------------------------------------- #
# Baseline snapshot — one call at turn start
# --------------------------------------------------------------------------- #

def snapshot_baseline(
    output_dir: str,
    *,
    guards_fn: Callable[[str], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Capture {status, guards} at start of Smith's turn.

    `guards_fn` is injected so callers can pick which guard reader
    to use (post_generate_fixes-aware wrapper, a mocked one for
    tests, etc.). None-returns as [] so downstream comparisons work
    without extra branching."""
    status = git_status_modified(output_dir)
    guards = []
    if guards_fn is not None:
        try:
            guards = list(guards_fn(output_dir) or [])
        except Exception:  # noqa: BLE001
            logger.warning("snapshot_baseline: guards_fn crashed", exc_info=True)
    return {"status": status, "guards": guards}


# --------------------------------------------------------------------------- #
# Internal — schema walker
# --------------------------------------------------------------------------- #

def _load_json(path: str) -> Any | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _find_field_by_label(root: Any, label: str) -> dict[str, Any] | None:
    target = label.strip().lower()
    for node in _walk_nodes(root):
        props = node.get("props") if isinstance(node, dict) else None
        if isinstance(props, dict):
            node_label = str(props.get("label") or "").strip().lower()
            if node_label == target:
                return node
    return None


def _find_first_node_of_type(root: Any, kind: str) -> dict[str, Any] | None:
    for node in _walk_nodes(root):
        if isinstance(node, dict) and str(node.get("type") or "") == kind:
            return node
    return None


def _walk_nodes(root: Any):
    """Depth-first walk over any nested dict/list structure, yielding
    every dict node. Robust to shape drift — the schema formats used
    across the app aren't fully uniform."""
    if isinstance(root, dict):
        yield root
        for v in root.values():
            yield from _walk_nodes(v)
    elif isinstance(root, list):
        for item in root:
            yield from _walk_nodes(item)
