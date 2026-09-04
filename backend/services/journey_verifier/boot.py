"""Lazy dev-server boot for the journey gate.

If the app under test is already reachable at `base_url` we use it as-is;
otherwise we spawn `npm run dev` in the app dir, wait for the port to
answer, run journeys, then kill the process tree.

The gate stays cheap for the common local-dev case (server already up),
adds real end-to-end coverage in CI, and never leaks node processes —
`__exit__` runs even on Playwright crash / KeyboardInterrupt / strict-mode
raise.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit


class BootError(RuntimeError):
    """App wouldn't come up within the boot budget."""


@contextmanager
def booted_app(
    output_dir: Path | str,
    *,
    base_url: str = "http://localhost:3000",
    boot_timeout_s: int = 90,
    log_sink: Path | None = None,
    env_extra: dict[str, str] | None = None,
) -> Iterator[dict]:
    """Context manager that guarantees a reachable app at `base_url`.

    Yields a dict describing what happened so callers can log it:
      { "booted": bool, "url": str, "pid": int | None, "log": str | None }

    `booted=False` means we found the app already listening and used it
    unchanged — no boot, no teardown, no reset. `booted=True` means we
    spawned `npm run dev` and will kill it on exit.
    """
    output_dir = Path(output_dir)
    port = _port_of(base_url)

    if _reachable(base_url, timeout_s=2):
        # `booted=False` matters to more than logging now: an app we did not
        # start does not have `env_extra`, so a caller that needs it must be
        # able to tell.
        yield {"booted": False, "url": base_url, "pid": None, "log": None}
        return

    if not (output_dir / "package.json").exists():
        raise BootError(f"no package.json in {output_dir}; cannot boot")

    log_path = log_sink or (output_dir / ".journey-boot.log")
    logf = log_path.open("w", buffering=1)

    # `env_extra` last, so a caller that needs the app booted a particular way
    # — a known NEXTAUTH_SECRET, so a session cookie can be minted for it —
    # wins over the ambient environment rather than being silently overridden
    # by whatever the developer happens to have exported.
    env = {**os.environ, "PORT": str(port), "NODE_ENV": "development",
           **(env_extra or {})}
    # Suppress open-browser-on-start etc. — the harness drives the app,
    # not a human.
    env.setdefault("BROWSER", "none")

    # start_new_session so we can SIGTERM the whole tree (next dev
    # spawns child workers).
    proc = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=str(output_dir),
        env=env,
        stdout=logf,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )

    try:
        if not _wait_for_boot(base_url, boot_timeout_s):
            tail = _tail(log_path, 2000)
            raise BootError(
                f"app failed to boot within {boot_timeout_s}s at {base_url}\n"
                f"log tail:\n{tail}"
            )
        yield {
            "booted": True,
            "url": base_url,
            "pid": proc.pid,
            "log": str(log_path),
        }
    finally:
        _terminate_tree(proc)
        try:
            logf.close()
        except Exception:
            pass


# ── helpers ────────────────────────────────────────────────────────────────

def _port_of(url: str) -> int:
    parts = urlsplit(url)
    if parts.port:
        return parts.port
    return 443 if parts.scheme == "https" else 80 if parts.scheme == "http" else 3000


def _reachable(url: str, *, timeout_s: int = 2) -> bool:
    import urllib.request
    try:
        urllib.request.urlopen(url, timeout=timeout_s)
        return True
    except Exception:
        pass
    # Non-200 (401/500) still means "listening" — treat as reachable.
    from socket import create_connection
    parts = urlsplit(url)
    host = parts.hostname or "localhost"
    try:
        with create_connection((host, _port_of(url)), timeout=timeout_s):
            return True
    except Exception:
        return False


def _wait_for_boot(url: str, timeout_s: int) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _reachable(url, timeout_s=2):
            return True
        time.sleep(1)
    return False


def _tail(path: Path, n_bytes: int) -> str:
    try:
        data = path.read_bytes()
    except Exception:
        return ""
    return data[-n_bytes:].decode("utf-8", errors="replace")


def _terminate_tree(proc: subprocess.Popen) -> None:
    """Kill the process group we launched. next dev spawns workers, so
    signalling only the direct child leaves orphaned node processes."""
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except Exception:
        # Fallback: direct signal to the child. Not perfect on macOS if
        # the workers detach, but better than nothing.
        try:
            proc.terminate()
        except Exception:
            pass
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
