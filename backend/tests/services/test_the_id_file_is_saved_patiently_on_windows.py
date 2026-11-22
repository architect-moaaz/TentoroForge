"""A Zomato build died on its first step with "[WinError 5] Access is denied: ids.json.tmp -> ids.json": on Windows the swap is
refused for milliseconds while anything else holds the file open. The id file now waits and tries again, as the Blueprint's own file does."""
from __future__ import annotations

import os

import pytest

from services.blueprint import ids
from services.blueprint.ids import IdAllocator


def test_a_swap_refused_for_a_moment_is_tried_again(tmp_path, monkeypatch):
    real = os.replace
    refusals = {"n": 0}

    def flaky(src, dst):
        if refusals["n"] < 3:
            refusals["n"] += 1
            raise PermissionError(5, "Access is denied")
        return real(src, dst)

    monkeypatch.setattr(ids.os, "replace", flaky)
    monkeypatch.setattr("services.proc_compat.IS_WINDOWS", True)
    alloc = IdAllocator(counters={}, bindings={}, retired=set(), _output_dir=str(tmp_path))
    path = alloc.save()
    assert path.is_file() and refusals["n"] == 3


def test_elsewhere_the_first_refusal_is_the_answer(tmp_path, monkeypatch):
    monkeypatch.setattr(ids.os, "replace", lambda *a: (_ for _ in ()).throw(PermissionError(13, "denied")))
    monkeypatch.setattr("services.proc_compat.IS_WINDOWS", False)
    alloc = IdAllocator(counters={}, bindings={}, retired=set(), _output_dir=str(tmp_path))
    with pytest.raises(PermissionError):
        alloc.save()
