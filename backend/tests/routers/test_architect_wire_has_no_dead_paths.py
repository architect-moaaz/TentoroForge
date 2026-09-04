"""Nothing in the architect wire that no caller can reach.

Half this module was the form-filler the ReAct loop replaced: `_understand_ask`
extracting a rename-shaped target, `_make_iteration_move` dispatching to six
seams. The loop took over and none of it was deleted — 500 lines, module-level,
imported, reading to anyone opening the file as the live path. Establishing
that the understanding it produced was never consulted cost the better part of
an hour, twice.

Dead code that LOOKS live is worse than no code, because the next person
debugging a turn reads it first. This test is what stops it growing back.
"""
from __future__ import annotations

import ast
import pathlib

#: What `routers/generate.py` imports from the wire. Adding an entry point is
#: fine; growing an unreachable one is what this catches.
ENTRY_POINTS = {
    "run_iteration_via_architect",
    "run_bootstrap_stage",
    "turn_result_to_legacy_dict",
}

_SOURCE = pathlib.Path(__file__).resolve().parents[2] / "services" / "smith_architect_wire.py"


def _reachable_and_dead():
    tree = ast.parse(_SOURCE.read_text(encoding="utf-8"))
    defs = {n.name: n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    calls = {name: {s.id for s in ast.walk(node) if isinstance(s, ast.Name)} & set(defs)
             for name, node in defs.items()}
    seen: set[str] = set()
    stack = [e for e in ENTRY_POINTS if e in defs]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(calls.get(n, ()))
    return seen, set(defs) - seen


def test_every_entry_point_the_router_imports_still_exists():
    reachable, _ = _reachable_and_dead()
    assert ENTRY_POINTS <= reachable


def test_no_function_is_unreachable_from_an_entry_point():
    _, dead = _reachable_and_dead()
    assert not dead, (
        "unreachable in services/smith_architect_wire.py: "
        f"{sorted(dead)}. Either an entry point is missing from ENTRY_POINTS "
        "above, or this is dead code — delete it; git log keeps it."
    )


def test_the_form_filler_is_gone():
    """Named explicitly: these are what the ReAct loop replaced, and what a
    reader mistook for the live path."""
    src = _SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(src)
    names = {n.name for n in tree.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert not names & {"_understand_ask", "_make_iteration_move",
                        "_seam_edit_page", "_seam_add_page", "_seam_replan",
                        "_author_page_patch"}
