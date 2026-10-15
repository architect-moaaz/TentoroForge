"""The domain watch's one-holder lock works on Windows, which has no `fcntl`.

Importing `fcntl` at the top of `services/deploy/domain_watch.py` stopped the backend from starting at all on a
Windows machine (the startup hook imports it), so nothing could be tried there after the domain work landed."""
from __future__ import annotations

import importlib
import sys


def test_the_module_imports_where_fcntl_does_not_exist(monkeypatch):
    monkeypatch.setitem(sys.modules, "fcntl", None)            # `import fcntl` now raises ImportError
    import services.deploy.domain_watch as watch
    importlib.reload(watch)
    assert watch.INTERVAL_S == 60


def test_one_watch_per_host_without_fcntl(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "fcntl", None)
    import services.deploy.domain_watch as watch
    importlib.reload(watch)
    lock = tmp_path / "watch.lock"
    first = watch._hold_watch(lock)
    try:
        assert first is not None, "the first worker takes the watch"
        assert watch._hold_watch(lock) is None, "a second worker does not"
    finally:
        first.close()
    again = watch._hold_watch(lock)
    assert again is not None, "the lock goes with the holder"
    again.close()


def test_one_watch_per_host_with_fcntl_is_unchanged(tmp_path):
    import services.deploy.domain_watch as watch
    importlib.reload(watch)
    lock = tmp_path / "watch2.lock"
    first = watch._hold_watch(lock)
    try:
        assert first is not None and watch._hold_watch(lock) is None
    finally:
        first.close()
