"""ECom L2 (2026-10-11): the build compiled and booted with ten runtime
notes, so the assembly wrote `passed_with_issues`; read as not built, the
project sat in draft with Publish disabled."""
import json

from services.project_service import _build_passed


def _doc(tmp_path, status):
    d = tmp_path / ".forge" / "blueprint"
    d.mkdir(parents=True)
    (d / "current.json").write_text(json.dumps({"runtime": {"build": {"status": status}}}), "utf-8")
    return str(tmp_path)


def test_a_build_that_passed_with_issues_is_built(tmp_path):
    assert _build_passed(_doc(tmp_path, "passed_with_issues")) is True


def test_a_build_that_passed_is_built_and_a_failed_one_is_not(tmp_path):
    assert _build_passed(_doc(tmp_path / "a", "passed")) is True
    assert _build_passed(_doc(tmp_path / "b", "failed")) is False
    assert _build_passed(None) is False
