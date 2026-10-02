"""The migrations can be walked from nothing, not only topped up.

Every live database is already at a head, so `alembic upgrade head` there
starts past most of the graph and says nothing about whether the graph is
walkable from base. The first time this platform was deployed BESIDE itself
(smithv3 on UAT, 2026-09-20) its backend crash-looped on an empty database:

    File ".../alembic/runtime/migration.py", line 717, in _delete_version
        self.heads.remove(version)
    KeyError: 'd1e2f3a4b5c6'

`sv3108a1b2c3` named `d1e2f3a4b5c6` as one of its parents, and
`f3ffbf62087c` had already merged that same revision. A merge CONSUMES the
heads it names, so the second one reached for a head that was gone. Nobody
would have seen it until a customer's first install.

A revision consumed by two merges is the shape of that fault, and it is
readable straight off the files — no database required.
"""
from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

import pytest

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _revisions() -> dict[str, tuple[str, ...]]:
    """`{revision: its parents}` for every migration on disk."""
    out: dict[str, tuple[str, ...]] = {}
    for path in sorted(VERSIONS.glob("*.py")):
        tree = ast.parse(path.read_text("utf-8"))
        rev, down = None, ()
        for node in tree.body:
            # `revision = "x"` and `revision: str = "x"` are both in use.
            if isinstance(node, ast.Assign):
                name = next((t.id for t in node.targets if isinstance(t, ast.Name)), "")
                value_node = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                name, value_node = node.target.id, node.value
            else:
                continue
            if value_node is None:
                continue
            if name == "revision" and isinstance(value_node, ast.Constant):
                rev = str(value_node.value)
            elif name == "down_revision":
                value = ast.literal_eval(value_node)
                down = () if value is None else (value,) if isinstance(value, str) else tuple(value)
        if rev:
            out[rev] = down
    return out


def test_a_database_created_from_nothing_reaches_head():
    """The one check that caught it: walk the whole graph into a real, empty
    database. A static rule over the files is not enough — alembic tolerates
    some shapes that look identical on paper — and every other environment is
    already at a head, so nothing else exercises the walk.

    Skipped when there is no throwaway Postgres to hand (the same gate the
    data model is proved against).
    """
    import subprocess
    import uuid

    from services.blueprint.data_gate import gate_server

    base, why = gate_server()
    if base is None:
        pytest.skip(f"no database to create: {why}")
    name = f"alembic_{uuid.uuid4().hex[:10]}"
    from services.blueprint.data_gate import _psql

    assert _psql(f'CREATE DATABASE "{name}"').returncode == 0
    try:
        url = f"{base}/{name}".replace("postgresql://", "postgresql+asyncpg://")
        done = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                              cwd=Path(__file__).resolve().parents[1],
                              env={**os.environ, "DATABASE_URL": url},
                              capture_output=True, text=True, timeout=600)
        assert done.returncode == 0, (done.stdout + done.stderr)[-2000:]
    finally:
        _psql(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def test_every_parent_exists():
    """A parent that is not on disk is a chain that cannot be walked at all."""
    revisions = _revisions()
    missing = {rev: [p for p in parents if p not in revisions]
               for rev, parents in revisions.items()}
    assert not {r: p for r, p in missing.items() if p}, f"unknown parents: {missing}"


def test_the_chain_ends_in_one_head():
    """Two heads and `upgrade head` refuses to choose."""
    revisions = _revisions()
    parents = {p for ps in revisions.values() for p in ps}
    heads = sorted(r for r in revisions if r not in parents)
    assert len(heads) == 1, f"expected one head, found {heads}"


def test_the_graph_was_measured_against_a_real_database():
    """The fix is recorded where the next person will look."""
    source = (VERSIONS / "sv3108a1b2c3_add_verify_runs.py").read_text("utf-8")
    assert "d1e2f3a4b5c6" in source, "the removed parent is explained, not silently dropped"
    assert re.search(r'down_revision\s*=\s*\("mb2907c3d4e5",\s*"b8d4e1f9a3c2"\)', source)
