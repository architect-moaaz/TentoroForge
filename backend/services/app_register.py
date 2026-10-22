"""Whose each application is — kept after the application is gone.

Spend is attributed to an organisation through the application a call was
made for. A call recorded before calls were stamped with their organisation
(2026-10-15), or made by work nobody asked for in person (a self-heal, the
checks after a build), carried none, and found its organisation through the
application's row; when the application was deleted, its spend left the
organisation with it. zoro-corp's total fell from $128 to $120 when q3lcz9t8
was deleted, and $92.78 of Criterion Hospitality's went the same way with
pah7lhfz (2026-10-21).

The register sits beside the usage ledger: application id → organisation,
owner, name. It is refreshed whenever spend is looked up (`credits.
projects_known`, which every build and turn passes through), written once
more just before an application is removed, and read wherever a call lacks
its organisation — when it is recorded, and when it is attributed after the
application has gone. Entries are never dropped.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_CACHE: dict[str, Any] = {"mtime": None, "path": None, "apps": {}}


def _path() -> Path:
    if os.environ.get("FORGE_APP_REGISTER"):
        return Path(os.environ["FORGE_APP_REGISTER"])
    from services.build_usage import _ledger_path
    return _ledger_path().parent / "apps.json"


def _read(path: Path) -> dict[str, dict[str, str]]:
    try:
        data = json.loads(path.read_text("utf-8"))
        return {str(k): dict(v) for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def all_apps() -> dict[str, dict[str, str]]:
    """Every application the register knows, by id. Re-read only when the
    file changed — `record_usage` asks on every call."""
    path = _path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    if _CACHE["path"] != str(path) or _CACHE["mtime"] != mtime:
        _CACHE.update(path=str(path), mtime=mtime, apps=_read(path))
    return dict(_CACHE["apps"])


def lookup(app_id: str) -> dict[str, str]:
    return dict(all_apps().get(str(app_id)) or {})


def remember(apps: Mapping[str, Mapping[str, Any]]) -> int:
    """Add or update applications (`{id: {org, owner, name}}`); returns how
    many changed. An empty field never overwrites a known one."""
    if not apps:
        return 0
    path = _path()
    with _LOCK:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                import fcntl
                lock = open(path.with_suffix(".lock"), "a")
                fcntl.flock(lock, fcntl.LOCK_EX)
            except Exception:  # noqa: BLE001 — no file locks here: the thread lock is what there is
                lock = None
            try:
                current = _read(path)
                changed = 0
                for app_id, info in apps.items():
                    if not app_id:
                        continue
                    was = current.get(str(app_id), {})
                    now = dict(was)
                    for k in ("org", "owner", "name"):
                        v = str(info.get(k) or "")
                        if v:
                            now[k] = v
                    if now != was:
                        current[str(app_id)] = now
                        changed += 1
                if changed:
                    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".apps.", suffix=".json")
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        json.dump(current, f, indent=1, sort_keys=True)
                    os.replace(tmp, path)
                return changed
            finally:
                if lock is not None:
                    lock.close()
        except Exception:  # noqa: BLE001 — accounting never breaks the work it accounts for
            logger.warning("[app-register] could not write", exc_info=True)
            return 0


__all__ = ["all_apps", "lookup", "remember"]
