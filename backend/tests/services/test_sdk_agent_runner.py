"""The SDK runner replaces the bundled CLI (which wedged under throttle) for the
contract/schema/api/auth agents. The query() loop needs a live API key, but the
in-process file tools are pure and tested here."""
from services.sdk_agent_runner import _exec_tool, _TOOL_DEFS


def test_write_then_read(tmp_path):
    cwd = str(tmp_path)
    assert "Wrote" in _exec_tool(cwd, "Write", {"file_path": "src/a.ts", "content": "export const x = 1;"})
    assert (tmp_path / "src" / "a.ts").read_text() == "export const x = 1;"
    assert _exec_tool(cwd, "Read", {"file_path": "src/a.ts"}) == "export const x = 1;"


def test_glob(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.ts").write_text("a")
    (tmp_path / "src" / "b.ts").write_text("b")
    out = _exec_tool(str(tmp_path), "Glob", {"pattern": "src/*.ts"})
    assert "src/a.ts" in out and "src/b.ts" in out


def test_edit_replaces_first_occurrence(tmp_path):
    f = tmp_path / "x.ts"
    f.write_text("foo bar foo")
    assert "Edited" in _exec_tool(str(tmp_path), "Edit", {"file_path": "x.ts", "old_string": "foo", "new_string": "baz"})
    assert f.read_text() == "baz bar foo"


def test_edit_missing_string_is_soft_error(tmp_path):
    (tmp_path / "x.ts").write_text("hello")
    out = _exec_tool(str(tmp_path), "Edit", {"file_path": "x.ts", "old_string": "nope", "new_string": "y"})
    assert out.startswith("ERROR")


def test_tool_defs_cover_the_agent_tools():
    names = {t["name"] for t in _TOOL_DEFS}
    assert {"Write", "Read", "Glob", "Edit"} <= names
