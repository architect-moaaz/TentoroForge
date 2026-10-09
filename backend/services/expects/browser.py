"""The runner's browser: `scripts/expect_browser.mjs`, driven a command at a
time over its stdin and stdout. It does what it is told and reports what
happened; every decision and every judgement is made here, in Python."""
from __future__ import annotations

import itertools
import json
import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "expect_browser.mjs"


class BrowserGone(RuntimeError):
    """The browser stopped answering."""


class Browser:
    def __init__(self, work: Path):
        from services.blueprint.page_review import _playwright_modules
        work.mkdir(parents=True, exist_ok=True)
        link = work / "node_modules"
        if not link.exists():
            link.symlink_to(_playwright_modules())
        script = work / "expect_browser.mjs"
        shutil.copyfile(_SCRIPT, script)
        env = {**os.environ}
        env.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(Path.home() / "Library/Caches/ms-playwright"))
        self.proc = subprocess.Popen(["node", str(script)], cwd=work, stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                     bufsize=1, env=env)
        self._ids = itertools.count(1)
        self._answers: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            line = line.strip()
            if line.startswith("{"):
                try:
                    self._answers.put(json.loads(line))
                except ValueError:
                    continue
        self._answers.put(None)

    def call(self, cmd: str, timeout: float = 120, **args: Any) -> dict:
        if self.proc.poll() is not None:
            raise BrowserGone(f"the browser has stopped: {(self.proc.stderr.read() if self.proc.stderr else '')[-400:]}")
        rid = next(self._ids)
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps({"id": rid, "cmd": cmd, **args}) + "\n")
        self.proc.stdin.flush()
        while True:
            try:
                got = self._answers.get(timeout=timeout)
            except queue.Empty as exc:
                raise BrowserGone(f"the browser did not answer {cmd} within {timeout:.0f}s") from exc
            if got is None:
                raise BrowserGone("the browser stopped while answering")
            if got.get("id") == rid:
                return got

    def close(self) -> None:
        try:
            if self.proc.poll() is None:
                self.call("quit", timeout=20)
        except Exception:  # noqa: BLE001 — closing never fails a run
            pass
        try:
            self.proc.kill()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> "Browser":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


__all__ = ["Browser", "BrowserGone"]
