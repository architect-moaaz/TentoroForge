"""Structural test guarding B-022.2 regression.

Root cause: in `_run_relay_pipeline` (and its Figma twin), `_progress` was
called from the discovery-else branch BEFORE its `= _ProgressTracker(...)`
assignment. Python's local-scope rule makes this UnboundLocalError on every
recreate-plan / direct-generate path.

Fix: hoist the ProgressTracker init to the top of the function.

Regression guard: walk the AST for every async pipeline function and verify
the first `_progress = _ProgressTracker(...)` assignment precedes the first
attribute read on `_progress`. This is a static check — no runtime setup
needed — so it can catch a future refactor that reintroduces the bug.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

GENERATE_PY = Path(__file__).resolve().parents[2] / "routers" / "generate.py"

# Functions whose `_progress` use pattern must be safe.
PIPELINE_FUNCTIONS = {
    "_run_relay_pipeline",
    "_run_figma_relay_pipeline",
}


def _load_function_bodies() -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(GENERATE_PY.read_text(encoding="utf-8"))
    out: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in PIPELINE_FUNCTIONS:
                out[node.name] = node
    return out


def _first_progress_read_line(fn: ast.AST) -> int | None:
    """Line number of the first `_progress.<attr>` access, or None."""
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name):
            if sub.value.id == "_progress":
                return sub.lineno
    return None


def _first_progress_assignment_line(fn: ast.AST) -> int | None:
    """Line number of the first `_progress = ...` assignment, or None."""
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Assign):
            for tgt in sub.targets:
                if isinstance(tgt, ast.Name) and tgt.id == "_progress":
                    return sub.lineno
    return None


@pytest.mark.parametrize("fn_name", sorted(PIPELINE_FUNCTIONS))
def test_progress_assigned_before_first_use(fn_name):
    """Guarantees `_progress = ...` precedes every `_progress.<attr>` read
    inside the pipeline function — the exact class of bug B-022.2 hit."""
    fns = _load_function_bodies()
    assert fn_name in fns, f"{fn_name} not found in generate.py"
    fn = fns[fn_name]
    assign_line = _first_progress_assignment_line(fn)
    read_line = _first_progress_read_line(fn)
    assert assign_line is not None, (
        f"{fn_name}: no `_progress = ...` assignment found — did the pipeline "
        f"stop initialising the ProgressTracker?"
    )
    if read_line is not None:
        assert assign_line < read_line, (
            f"{fn_name}: `_progress` used at line {read_line} before its "
            f"assignment at line {assign_line}. This is the B-022.2 pattern — "
            f"Python raises UnboundLocalError on any code path that reaches "
            f"the read without going through the assignment."
        )


def test_no_duplicate_progress_init_per_function():
    """Guard against the older duplicate init pattern (two
    `_progress = _ProgressTracker(...)` blocks in the same function). Duplicates
    aren't a runtime bug but they mask the hoist and make the next refactor
    fragile."""
    fns = _load_function_bodies()
    for name, fn in fns.items():
        assigns = [
            sub for sub in ast.walk(fn)
            if isinstance(sub, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "_progress"
                for t in sub.targets
            )
        ]
        assert len(assigns) == 1, (
            f"{name}: expected exactly one `_progress = ...` assignment, "
            f"found {len(assigns)} (at lines {[a.lineno for a in assigns]}). "
            f"Extra assignments mask the hoisted init and can regress B-022.2."
        )
