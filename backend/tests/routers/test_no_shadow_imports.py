"""Structural guard against the shadow-import UnboundLocalError class.

Root cause pattern (B-022.2 `_progress`, B-022.11 `time` in
`_handle_smith_turn`, and 3 others found by this scanner):

    import time  # module-level

    def handle():
        t0 = time.monotonic()   # <-- appears to read the module's time
        ...
        import time             # <-- but Python sees this and makes
                                #     `time` a function-local name for
                                #     the ENTIRE function. The read at
                                #     the top raises UnboundLocalError.

The bug only appears when the local re-binding sits later in the source
than at least one read. Every function that re-imports a top-level name
is at risk of drifting into this trap even if the read/write order is
currently safe.

This test walks every function in `backend/` and fails the moment a
name that is imported at module top is:
  - locally re-bound (via `import X`, `from X import Y`, or `X = ...`)
  - AND read at an earlier line within the same function.

Loop variables, comprehension targets, and function arguments are
ignored — they don't shadow module scope in ways that trip this bug.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
SKIP_DIRS = {"tests", "test", "__pycache__", "alembic", "scripts"}


def _iter_python_files() -> list[Path]:
    out: list[Path] = []
    for p in BACKEND.rglob("*.py"):
        if any(seg in SKIP_DIRS for seg in p.relative_to(BACKEND).parts):
            continue
        out.append(p)
    return sorted(out)


def _module_top_imports(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound = alias.asname or alias.name
                if bound != "*":
                    names.add(bound)
    return names


def _local_bindings(fn: ast.AST) -> list[tuple[str, int]]:
    """(name, first-lineno) for local `import` / `from-import` /
    top-body assignments inside `fn`, skipping nested defs, loop targets,
    comprehension targets, and function arguments."""
    binds: list[tuple[str, int]] = []
    for sub in ast.walk(fn):
        if sub is fn:
            continue
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if isinstance(sub, ast.Import):
            for alias in sub.names:
                binds.append((alias.asname or alias.name.split(".")[0], sub.lineno))
        elif isinstance(sub, ast.ImportFrom):
            for alias in sub.names:
                bound = alias.asname or alias.name
                if bound != "*":
                    binds.append((bound, sub.lineno))
        elif isinstance(sub, ast.Assign):
            for tgt in sub.targets:
                if isinstance(tgt, ast.Name):
                    binds.append((tgt.id, sub.lineno))
    return binds


def _first_read_line(fn: ast.AST, name: str) -> int | None:
    first: int | None = None
    for sub in ast.walk(fn):
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub is not fn:
            continue
        ln = None
        if (
            isinstance(sub, ast.Attribute)
            and isinstance(sub.value, ast.Name)
            and sub.value.id == name
        ):
            ln = sub.value.lineno
        elif isinstance(sub, ast.Name) and sub.id == name and isinstance(sub.ctx, ast.Load):
            ln = sub.lineno
        if ln is not None and (first is None or ln < first):
            first = ln
    return first


def _scan_file(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:
        return []
    top_imports = _module_top_imports(tree)
    if not top_imports:
        return []
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        arg_names = {a.arg for a in node.args.args} | {a.arg for a in node.args.kwonlyargs}
        if node.args.vararg:
            arg_names.add(node.args.vararg.arg)
        if node.args.kwarg:
            arg_names.add(node.args.kwarg.arg)
        for name, bind_ln in _local_bindings(node):
            if name not in top_imports or name in arg_names:
                continue
            read_ln = _first_read_line(node, name)
            if read_ln is None or read_ln >= bind_ln:
                continue
            rel = path.relative_to(BACKEND)
            findings.append(
                f"{rel}:{read_ln} in {node.name}(): reads `{name}` at line "
                f"{read_ln} but shadows top-level import at line {bind_ln} — "
                f"UnboundLocalError on that path (drop the local re-import "
                f"and rely on the module-level one)."
            )
    return findings


def test_no_shadow_import_traps():
    """Zero-tolerance guard: no function may re-bind a module-top import
    with an earlier read in the same function."""
    all_findings: list[str] = []
    for p in _iter_python_files():
        all_findings.extend(_scan_file(p))
    if all_findings:
        pytest.fail(
            "Shadow-import trap(s) found — same class as B-022.2 / B-022.11:\n  "
            + "\n  ".join(all_findings)
        )
