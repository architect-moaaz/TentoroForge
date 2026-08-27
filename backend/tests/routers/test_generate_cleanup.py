import pathlib
from routers.generate import _clean_schemas_dir


def test_cleans_nested_schemas(tmp_path):
    schemas = tmp_path / "src" / "schemas"
    (schemas / "requests").mkdir(parents=True)
    (schemas / "home.json").write_text("{}")
    (schemas / "requests" / "new.json").write_text("{}")
    (schemas / "requests" / "detail.json").write_text("{}")
    removed = _clean_schemas_dir(str(tmp_path))
    assert removed == 3
    # Empty subdirs cleaned up too
    assert not (schemas / "requests").exists() or not any((schemas / "requests").iterdir())


def test_no_op_when_dir_absent(tmp_path):
    """First generation on a fresh output dir shouldn't crash."""
    removed = _clean_schemas_dir(str(tmp_path))
    assert removed == 0


def test_does_not_touch_sibling_dirs(tmp_path):
    """Only src/schemas/ is cleared — db/, contracts/, etc. untouched."""
    (tmp_path / "src" / "schemas").mkdir(parents=True)
    (tmp_path / "src" / "contracts").mkdir(parents=True)
    (tmp_path / "src" / "schemas" / "x.json").write_text("{}")
    (tmp_path / "src" / "contracts" / "registry.json").write_text("{}")
    _clean_schemas_dir(str(tmp_path))
    assert (tmp_path / "src" / "contracts" / "registry.json").exists()
