"""A standard-library module used by name is imported where it is used.

A build that reached the boot check on Linux ended with `NameError: name 'signal' is not defined`: `assembly.py` imported `subprocess` and
`time` inside the function but never `signal`, and the only line that uses it sits on the path that stops the booted app, which no
test and no Windows run takes. This reads every build module and checks the same thing for any standard-library module name: where
`name.attribute` is used, `name` has to be imported at the top of the file or in a function around the use.
"""
import ast
import sys
from pathlib import Path

import pytest

BLUEPRINT = Path(__file__).resolve().parents[2] / "services" / "blueprint"
STDLIB = set(sys.stdlib_module_names)


def _imported_names(body) -> set[str]:
    names: set[str] = set()
    for node in body:
        if isinstance(node, ast.Import):
            names.update((a.asname or a.name).split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.update(a.asname or a.name for a in node.names)
    return names


def _bound_locally(fn) -> set[str]:
    """Names a function gets from somewhere other than an import: parameters and assignments, which may shadow a module name."""
    names = {a.arg for a in fn.args.args + fn.args.kwonlyargs + fn.args.posonlyargs}
    if fn.args.vararg:
        names.add(fn.args.vararg.arg)
    if fn.args.kwarg:
        names.add(fn.args.kwarg.arg)
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
    return names


def _missing(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    at_top = _imported_names(tree.body)
    # imports anywhere inside a class body or module-level `if`/`try` also count as top level
    for node in ast.walk(tree):
        if isinstance(node, (ast.If, ast.Try)) and node in tree.body:
            at_top |= _imported_names(getattr(node, "body", []))
    problems: list[str] = []

    def visit(node, scopes: list[set[str]]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                own = {
                    n for sub in ast.walk(child) if isinstance(sub, (ast.Import, ast.ImportFrom))
                    for n in _imported_names([sub])
                }
                visit(child, scopes + [own | _bound_locally(child)])
                continue
            if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
                name = child.value.id
                if name in STDLIB and name not in at_top and not any(name in s for s in scopes):
                    problems.append(f"{path.name}:{child.lineno} uses {name}.{child.attr} but {name} is not imported there")
            visit(child, scopes)

    visit(tree, [])
    return problems


FILES = sorted(p for p in BLUEPRINT.glob("*.py") if p.name != "__init__.py")


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_every_stdlib_module_used_by_name_is_imported(path):
    assert _missing(path) == []
