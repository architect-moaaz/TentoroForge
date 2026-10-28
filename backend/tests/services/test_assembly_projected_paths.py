"""Assembly must keep its hands off what the projections wrote — on every platform.

`PROJECTED_PATHS` and `SCAFFOLD_DEFAULTS` are written with forward slashes. On
Windows `str(Path)` uses backslashes, so none of them matched and the scaffold's
neutral tokens, gate-everything middleware, login page and empty page registry
were copied over the application's own."""
from pathlib import Path

from services.blueprint.assembly import PROJECTED_PATHS, SCAFFOLD_DEFAULTS, copy_scaffold


def _write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_a_projected_file_survives_the_scaffold_copy(tmp_path):
    projected = {
        "src/app/tokens.css": "/* the application's own palette */",
        "src/middleware.ts": "// generated from the pages",
        "src/schemas/registry.ts": "// the application's routes",
        "src/lib/account.ts": "// who signs in",
        "src/app/login/page.tsx": "// the designed sign-in page",
    }
    for rel, text in projected.items():
        _write(tmp_path, rel, text)

    copy_scaffold(tmp_path, project_short_id="demo")

    for rel, text in projected.items():
        assert (tmp_path / rel).read_text("utf-8") == text, f"{rel} was overwritten by the scaffold"


def test_the_scaffold_still_fills_a_hole(tmp_path):
    copy_scaffold(tmp_path, project_short_id="demo")
    for rel in ("src/app/tokens.css", "src/lib/account.ts"):
        assert (tmp_path / rel).is_file(), f"{rel} is missing: the floor must be buildable"


def test_the_lists_are_written_with_forward_slashes():
    assert all("\\" not in p for p in (*PROJECTED_PATHS, *SCAFFOLD_DEFAULTS))


def test_a_nested_page_schema_is_not_swept_as_stale():
    """`/books/new` is written to src/schemas/books/new.json; the sweep of schemas the
    projection no longer writes must recognise it by its forward-slash path, or on Windows
    every nested page is deleted as soon as it is written."""
    import inspect

    import services.blueprint.projection as projection

    source = inspect.getsource(projection)
    assert 'f"src/schemas/{f.relative_to(root).as_posix()}" not in written_set' in source
