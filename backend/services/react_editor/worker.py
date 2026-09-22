"""A Node script kept running, answering one request after another.

The adapter and the JIT are Node scripts; starting Node for every call cost
more than the call — three starts per edit, ~170 ms each, were most of what
a person waited for. A worker is the same script started once with
``--serve``: requests go in as JSON lines on stdin, answers come back as JSON
lines on stdout, matched by id. One worker per script and environment (the
app whose node_modules it resolves against); requests to one worker are
serialised, a crash or a timeout starts a fresh one on the next request, and
an idle worker is stopped so an editor nobody has open holds no process.

The one-shot mode of both scripts stays as it was: it is what runs when the
worker cannot (no Node, a refused start), and what the tests of the scripts
themselves use.
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import queue
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: A worker nobody has used for this long is stopped.
IDLE_SECONDS = float(os.environ.get("FORGE_EDITOR_WORKER_IDLE", "600"))
#: A worker is replaced after this many requests, so a leak in a library it
#: loads cannot grow without bound.
MAX_REQUESTS = int(os.environ.get("FORGE_EDITOR_WORKER_MAX", "2000"))


class WorkerError(RuntimeError):
    """The worker could not answer: not started, gone, or out of time."""


class NodeWorker:
    def __init__(self, script: Path, *, cwd: Path | None, env: dict[str, str], args: list[str] | None = None):
        self.script = script
        self.cwd = cwd
        self.env = env
        self.args = list(args or [])
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._lines: queue.Queue[str | None] = queue.Queue()
        self._served = 0
        self._last_used = time.monotonic()

    # ----------------------------------------------------------- lifecycle
    def _spawn(self) -> None:
        self.stop()
        try:
            self._proc = subprocess.Popen(["node", str(self.script), *self.args, "--serve"], stdin=subprocess.PIPE,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
                                          cwd=str(self.cwd) if self.cwd else None, env=self.env)
        except OSError as exc:
            raise WorkerError(f"could not start node: {exc}") from exc
        self._lines = queue.Queue()
        self._served = 0
        threading.Thread(target=self._read_stdout, args=(self._proc, self._lines), daemon=True).start()
        threading.Thread(target=self._read_stderr, args=(self._proc,), daemon=True).start()

    @staticmethod
    def _read_stdout(proc: subprocess.Popen[str], lines: queue.Queue[str | None]) -> None:
        try:
            for line in proc.stdout or []:
                lines.put(line)
        finally:
            lines.put(None)

    @staticmethod
    def _read_stderr(proc: subprocess.Popen[str]) -> None:
        for line in proc.stderr or []:
            if line.strip():
                logger.debug("[worker %s] %s", proc.pid, line.rstrip()[:400])

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
        except OSError:
            pass

    def idle_for(self) -> float:
        return time.monotonic() - self._last_used

    # ------------------------------------------------------------- request
    def request(self, payload: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        with self._lock:
            if not self.alive() or self._served >= MAX_REQUESTS:
                self._spawn()
            self._last_used = time.monotonic()
            rid = uuid.uuid4().hex
            proc = self._proc
            assert proc is not None and proc.stdin is not None
            try:
                proc.stdin.write(json.dumps({"id": rid, **payload}) + "\n")
                proc.stdin.flush()
            except (OSError, ValueError) as exc:
                self.stop()
                raise WorkerError(f"the worker went away: {exc}") from exc
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.stop()
                    raise WorkerError("timeout")
                try:
                    line = self._lines.get(timeout=remaining)
                except queue.Empty:
                    self.stop()
                    raise WorkerError("timeout")
                if line is None:
                    self.stop()
                    raise WorkerError("the worker exited")
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("[worker] not JSON: %s", line[:200])
                    continue
                if msg.get("id") != rid:
                    continue
                self._served += 1
                self._last_used = time.monotonic()
                msg.pop("id", None)
                return msg


_workers: dict[tuple[str, str, str], NodeWorker] = {}
_registry_lock = threading.Lock()
_reaper_started = False


def _reap() -> None:
    while True:
        time.sleep(30)
        with _registry_lock:
            for key, w in list(_workers.items()):
                if w.alive() and w.idle_for() > IDLE_SECONDS:
                    w.stop()


def get_worker(script: Path, *, cwd: Path | None, env: dict[str, str]) -> NodeWorker:
    """The worker for this script in this environment, started on first use."""
    global _reaper_started
    key = (str(script), str(cwd or ""), env.get("NODE_PATH", ""))
    with _registry_lock:
        w = _workers.get(key)
        if w is None:
            w = _workers[key] = NodeWorker(script, cwd=cwd, env=env)
        if not _reaper_started:
            _reaper_started = True
            threading.Thread(target=_reap, daemon=True).start()
        return w


def enabled() -> bool:
    return os.environ.get("FORGE_EDITOR_WORKER", "1") not in ("0", "false", "no")


def stop_all() -> None:
    with _registry_lock:
        for w in _workers.values():
            w.stop()


atexit.register(stop_all)
