"""The source adapter — the Node script that parses and patches a page's JSX.

Python never touches the JSX itself: every read is a `model`, every edit a
`patch`, both done by `static/react-model.mjs` on a real parser so that an
edit lands exactly at the element it names and nothing else moves. The script
needs only `@babel/parser`, which every generated application carries under
its own node_modules (Next brings it), with the repository's as the fallback.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve().parents[2] / "static" / "react-model.mjs"
_REPO_NODE_MODULES = Path(__file__).resolve().parents[3] / "node_modules"


class AdapterError(RuntimeError):
    """The adapter refused an operation; ``code`` names why, ``message`` says it plainly."""

    def __init__(self, code: str, message: str, line: int | None = None):
        super().__init__(message)
        self.code = code
        self.line = line

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "line": self.line}


def _node_path(app_root: Path | None) -> str:
    parts = []
    if app_root is not None:
        parts.append(str(Path(app_root) / "node_modules"))
    parts.append(str(_REPO_NODE_MODULES))
    if os.environ.get("NODE_PATH"):
        parts.append(os.environ["NODE_PATH"])
    return os.pathsep.join(parts)


def run(command: str, payload: dict[str, Any], *, app_root: Path | None = None,
        timeout: float = 30.0) -> dict[str, Any]:
    env = {**os.environ, "NODE_PATH": _node_path(app_root)}
    try:
        proc = subprocess.run(["node", str(SCRIPT), command], input=json.dumps(payload),
                              capture_output=True, text=True, timeout=timeout, env=env)
    except FileNotFoundError as exc:
        raise AdapterError("no-node", "Node.js is not installed where the platform runs, so pages "
                                      "cannot be read or edited here.") from exc
    except subprocess.TimeoutExpired as exc:
        raise AdapterError("timeout", "Reading the page took too long.") from exc
    out = (proc.stdout or "").strip()
    if not out:
        raise AdapterError("adapter", "The page could not be read: " + (proc.stderr or "").strip()[:400])
    try:
        result = json.loads(out)
    except json.JSONDecodeError as exc:
        raise AdapterError("adapter", f"The page could not be read: {out[:200]}") from exc
    if not result.get("ok"):
        err = result.get("error") or {}
        raise AdapterError(str(err.get("code") or "adapter"), str(err.get("message") or "The change could not be made."),
                           err.get("line"))
    return result


def model(view: str, load: str = "", *, app_root: Path | None = None) -> dict[str, Any]:
    return run("model", {"view": view, "load": load}, app_root=app_root)


def patch(view: str, ops: list[dict[str, Any]], *, app_root: Path | None = None) -> str:
    return str(run("patch", {"view": view, "ops": ops}, app_root=app_root)["view"])


def annotate(view: str, *, app_root: Path | None = None) -> str:
    return str(run("annotate", {"view": view}, app_root=app_root)["view"])


def revision_of(view: str, load: str) -> str:
    """A revision is the content: the same sources are the same revision, on
    any machine, which is what makes an apply idempotent to retry."""
    h = hashlib.sha1()
    h.update(view.encode("utf-8"))
    h.update(b"\0")
    h.update(load.encode("utf-8"))
    return h.hexdigest()[:16]
