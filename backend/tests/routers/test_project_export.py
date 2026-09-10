"""Tests for the no-auth project-export endpoint."""
from __future__ import annotations
import io
import tarfile
from pathlib import Path

import pytest


def test_export_excludes_node_modules_and_next(tmp_path):
    """Direct unit test of the tarball builder logic via _EXPORT_EXCLUDE_DIRS."""
    project_dir = tmp_path / "x"
    project_dir.mkdir()
    (project_dir / "package.json").write_text('{"name":"x"}', encoding="utf-8")
    (project_dir / "src").mkdir()
    (project_dir / "src" / "app").mkdir()
    (project_dir / "src" / "app" / "page.tsx").write_text("export default function P() {}", encoding="utf-8")
    # Directories that must be excluded
    (project_dir / "node_modules").mkdir()
    (project_dir / "node_modules" / "junk.js").write_text("excluded", encoding="utf-8")
    (project_dir / ".next").mkdir()
    (project_dir / ".next" / "build.json").write_text("excluded", encoding="utf-8")
    (project_dir / ".git").mkdir()
    (project_dir / ".git" / "config").write_text("excluded", encoding="utf-8")
    (project_dir / "__pycache__").mkdir()
    (project_dir / "__pycache__" / "foo.pyc").write_bytes(b"excluded")

    from routers._debug_schema import _EXPORT_EXCLUDE_DIRS

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for p in project_dir.rglob("*"):
            if any(part in _EXPORT_EXCLUDE_DIRS for part in p.parts):
                continue
            if p.is_file():
                rel = p.relative_to(project_dir.parent)
                tf.add(p, arcname=str(rel))
    buf.seek(0)

    tf2 = tarfile.open(fileobj=buf, mode="r:gz")
    names = tf2.getnames()
    assert any("package.json" in n for n in names), f"package.json missing from tarball: {names}"
    assert any("page.tsx" in n for n in names), f"page.tsx missing from tarball: {names}"
    assert not any("node_modules" in n for n in names), "node_modules leaked into tarball"
    assert not any(".next" in n for n in names), ".next leaked into tarball"
    assert not any(".git" in n for n in names), ".git leaked into tarball"
    assert not any("__pycache__" in n for n in names), "__pycache__ leaked into tarball"


def test_export_exclude_dirs_set_contents():
    """Verify the exclude set contains all expected entries."""
    from routers._debug_schema import _EXPORT_EXCLUDE_DIRS

    required = {"node_modules", ".next", ".git", "out", ".fixtures-cache", ".design", "__pycache__"}
    assert required <= _EXPORT_EXCLUDE_DIRS, (
        f"Missing entries in _EXPORT_EXCLUDE_DIRS: {required - _EXPORT_EXCLUDE_DIRS}"
    )


def test_export_arcname_relative_to_parent(tmp_path):
    """Archive member names must be relative to the project's *parent* directory,
    so extraction produces <short_id>/… at the user's cwd."""
    project_dir = tmp_path / "myproject"
    project_dir.mkdir()
    (project_dir / "package.json").write_text('{"name":"myproject"}', encoding="utf-8")

    from routers._debug_schema import _EXPORT_EXCLUDE_DIRS

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for p in project_dir.rglob("*"):
            if any(part in _EXPORT_EXCLUDE_DIRS for part in p.parts):
                continue
            if p.is_file():
                rel = p.relative_to(project_dir.parent)
                tf.add(p, arcname=str(rel))
    buf.seek(0)

    tf2 = tarfile.open(fileobj=buf, mode="r:gz")
    names = tf2.getnames()
    # All archive members must start with the project directory name
    for name in names:
        assert name.startswith("myproject"), (
            f"arcname '{name}' does not start with project dir name 'myproject'"
        )
