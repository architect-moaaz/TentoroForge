"""Saving the Blueprint waits out a file Windows is holding, and only on Windows.

The first full ToolShare build ended with every node done except the last, which failed with
`PermissionError: [WinError 5] Access is denied: 'current.json.tmp' -> 'current.json'` while the panel was
reading the Blueprint. The hold lasts milliseconds; the swap never tried twice."""
from __future__ import annotations

import pytest

from services import proc_compat
from services.blueprint import service as bp


def _held(times: int, real):
    calls = {"n": 0}

    def replace(src, dst):
        calls["n"] += 1
        if calls["n"] <= times:
            raise PermissionError(13, "Access is denied")
        return real(src, dst)

    return replace, calls


def test_on_windows_a_swap_refused_for_a_moment_goes_through(tmp_path, monkeypatch):
    src, dst = tmp_path / "a.tmp", tmp_path / "a.json"
    src.write_text("new", "utf-8")
    dst.write_text("old", "utf-8")
    replace, calls = _held(3, bp.os.replace)
    monkeypatch.setattr(proc_compat, "IS_WINDOWS", True)
    monkeypatch.setattr(bp.os, "replace", replace)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    bp.replace_file(src, dst)
    assert dst.read_text("utf-8") == "new" and calls["n"] == 4


def test_on_windows_a_file_that_stays_held_still_fails_in_the_end(tmp_path, monkeypatch):
    src, dst = tmp_path / "a.tmp", tmp_path / "a.json"
    src.write_text("new", "utf-8")
    replace, calls = _held(99, bp.os.replace)
    monkeypatch.setattr(proc_compat, "IS_WINDOWS", True)
    monkeypatch.setattr(bp.os, "replace", replace)
    monkeypatch.setattr("time.sleep", lambda _s: None)
    with pytest.raises(PermissionError):
        bp.replace_file(src, dst, tries=5)
    assert calls["n"] == 5


def test_elsewhere_the_first_refusal_is_the_answer_as_it_always_was(tmp_path, monkeypatch):
    src, dst = tmp_path / "a.tmp", tmp_path / "a.json"
    src.write_text("new", "utf-8")
    replace, calls = _held(1, bp.os.replace)
    monkeypatch.setattr(proc_compat, "IS_WINDOWS", False)
    monkeypatch.setattr(bp.os, "replace", replace)
    with pytest.raises(PermissionError):
        bp.replace_file(src, dst)
    assert calls["n"] == 1


def test_a_normal_save_writes_the_blueprint(tmp_path):
    svc = bp.BlueprintService.create(output_dir=tmp_path, app_id="a", name="X", domain="d")
    svc.doc["application"]["description"] = "changed"
    svc.save()
    assert bp.BlueprintService.load(output_dir=tmp_path).doc["application"]["description"] == "changed"
    assert not (svc.root / "current.json.tmp").exists()
