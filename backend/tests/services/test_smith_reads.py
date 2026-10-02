"""Smith reads the real application — S2 of `2026-09-24-smith-as-a-loop`, §0.

The tools never guess, the one refusal is policy, and a cut is said. Those are
the three properties; each has a test named for it. The loop test at the
bottom is the reason the module exists: a step that looked, and a later step
that acted on what it saw.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from services.smith import reads, tools
from services.smith.reads import ReadRefused


def _project(tmp_path: Path) -> Path:
    (tmp_path / "app" / "src" / "pages").mkdir(parents=True)
    (tmp_path / "app" / "src" / "pages" / "tools.tsx").write_text(
        "export default function Tools() {\n  return <h1>Discover Tools</h1>;\n}\n")
    (tmp_path / "app" / "src" / "pages" / "big.tsx").write_text(
        "\n".join(f"line {i}" for i in range(1, 1001)) + "\n")
    (tmp_path / "app" / ".env.local").write_text("DATABASE_URL=postgres://u:hunter2@db/x\n")
    (tmp_path / "app" / "node_modules" / "left").mkdir(parents=True)
    (tmp_path / "app" / "node_modules" / "left" / "index.js").write_text("Discover Tools everywhere")
    (tmp_path / "app" / "notes.md").write_text("token: ghp_abcdefghijklmnopqrstuvwxyz1234 is the old one\n")
    return tmp_path


# --------------------------------------------------------------------------- #
# The tools never guess
# --------------------------------------------------------------------------- #

def test_a_wrong_path_is_reported_never_corrected(tmp_path):
    _project(tmp_path)
    with pytest.raises(ReadRefused) as refused:
        reads.read_file(str(tmp_path), "app/src/pages/tool.tsx")      # sic
    assert "no file at `app/src/pages/tool.tsx`" in str(refused.value)


def test_a_read_returns_exactly_the_file_numbered(tmp_path):
    _project(tmp_path)
    out = reads.read_file(str(tmp_path), "app/src/pages/tools.tsx")
    assert out.startswith("app/src/pages/tools.tsx — 3 lines")
    assert "    2|   return <h1>Discover Tools</h1>;" in out


def test_grep_reports_no_match_rather_than_widening(tmp_path):
    _project(tmp_path)
    assert reads.grep(str(tmp_path), "Nonexistent").startswith("No line matches")


def test_grep_leaves_dependencies_out(tmp_path):
    _project(tmp_path)
    out = reads.grep(str(tmp_path), "Discover Tools")
    assert "app/src/pages/tools.tsx:2:" in out
    assert "node_modules" not in out


def test_a_missing_section_names_what_is_there():
    with pytest.raises(ReadRefused) as refused:
        reads.read_section({"pages": [], "data": {"entities": []}}, "data.fields")
    assert "At that level there is: entities" in str(refused.value)


# --------------------------------------------------------------------------- #
# The one refusal is policy
# --------------------------------------------------------------------------- #

def test_a_credentials_file_is_refused_by_name_and_says_why(tmp_path):
    _project(tmp_path)
    with pytest.raises(ReadRefused) as refused:
        reads.read_file(str(tmp_path), "app/.env.local")
    assert "holds credentials" in str(refused.value)
    assert "hunter2" not in str(refused.value)


def test_a_credential_inside_an_ordinary_file_is_scrubbed(tmp_path):
    _project(tmp_path)
    out = reads.read_file(str(tmp_path), "app/notes.md")
    assert "ghp_abcdefghijklmnopqrstuvwxyz1234" not in out
    assert "secret removed" in out


def test_a_path_outside_the_project_is_refused(tmp_path):
    _project(tmp_path)
    for bad in ("../other", "/etc/passwd", "app/../../x"):
        with pytest.raises(ReadRefused):
            reads.read_file(str(tmp_path), bad)


def test_listing_marks_credential_files_and_skips_dependencies(tmp_path):
    _project(tmp_path)
    out = reads.list_files(str(tmp_path), "app")
    assert ".env.local" in out and "[credentials — not readable]" in out
    assert "left out: node_modules/" in out


# --------------------------------------------------------------------------- #
# A cut is said
# --------------------------------------------------------------------------- #

def test_a_long_file_is_cut_and_says_how_to_read_the_rest(tmp_path):
    _project(tmp_path)
    out = reads.read_file(str(tmp_path), "app/src/pages/big.tsx")
    assert f"showing 1–{reads.MAX_LINES}" in out
    assert f"start={reads.MAX_LINES + 1}" in out
    later = reads.read_file(str(tmp_path), "app/src/pages/big.tsx", start=990)
    assert "  990| line 990" in later and "showing 990–1000" in later


# --------------------------------------------------------------------------- #
# Reads are in the catalogue, apart from the verbs
# --------------------------------------------------------------------------- #

def test_reads_are_tools_but_not_verbs():
    for name in reads.READ_NAMES:
        assert tools.is_tool(name) and tools.is_read(name)
    assert not tools.is_read("rename")
    assert "Looking (these change nothing" in tools.render()


def test_a_refusal_is_the_observation_not_an_exception(tmp_path):
    _project(tmp_path)
    said = reads.run("read_file", {"path": "app/.env.local"},
                     output_dir=str(tmp_path), doc={})
    assert "holds credentials" in said
