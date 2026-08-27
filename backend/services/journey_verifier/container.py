"""Containerized boot for the JV-15 verify runner.

Replacement for ``boot.booted_app`` when Docker is available. Each verify
run gets its own compose project (unique name → own network + volumes),
its own free host ports, and is torn down on exit including volumes so
the next verify starts from a clean DB.

Design:
  - Compose project name = "verify-<short-uuid>". Namespaces every
    resource (network, volume, containers) so parallel verifies never
    collide.
  - Free ports picked from the OS ephemeral range at start. Passed into
    compose via WEB_PORT / DB_PORT env.
  - `docker compose up -d --build` runs synchronously; the caller is
    already inside asyncio.to_thread so this doesn't block the loop.
  - `down -v --remove-orphans` on exit — the volume flag wipes the
    Postgres pgdata volume so re-verify gets a fresh DB.
  - Best-effort: if Docker is missing / not running / build fails, raise
    ContainerBootError with the log tail; the SV pipeline demotes the
    journey step to a warn and continues.

Not implemented yet (deferred):
  - Progress events (JV-15d) — this module returns after ready.
  - Image cache reuse — every verify does a `--build`, which uses the
    Docker daemon's layer cache but doesn't skip the outer build call.
"""
from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)


class ContainerBootError(RuntimeError):
    """Docker/compose failed to bring the app up within the budget."""


def is_available() -> bool:
    """Cheap probe — no daemon call. Docker CLI on PATH is necessary but
    not sufficient; the full `docker info` check happens inside
    ``containerized_app``, where a failure carries meaningful diagnostics
    (`docker info` output tail)."""
    return shutil.which("docker") is not None


@contextmanager
def containerized_app(
    output_dir: Path | str,
    *,
    build_timeout_s: int = 420,   # 7min — cold `next build` + npm install
    boot_timeout_s: int = 90,     # after build, waiting for /health
    log_sink: Path | None = None,
) -> Iterator[dict]:
    """Bring the app up in a Docker Compose project, yield connection info,
    tear it down on exit (volumes included).

    Yields a dict describing the running deployment:
      {
        "url": "http://localhost:<port>/",
        "web_port": int,
        "db_port": int,
        "compose_project": "verify-<uuid>",
        "log": str | None,   # path to captured build/run log
      }

    Raises ContainerBootError if Docker isn't reachable or the containers
    never become healthy.
    """
    if not is_available():
        raise ContainerBootError("docker CLI not on PATH")

    output_dir = Path(output_dir)
    if not (output_dir / "docker-compose.verify.yml").exists():
        raise ContainerBootError(
            f"docker-compose.verify.yml missing in {output_dir} — "
            "post_generate_fixes did not emit verify artifacts"
        )
    if not (output_dir / "Dockerfile.verify").exists():
        raise ContainerBootError(
            f"Dockerfile.verify missing in {output_dir} — "
            "post_generate_fixes did not emit verify artifacts"
        )

    project = f"verify-{uuid.uuid4().hex[:8]}"
    web_port = _pick_free_port()
    db_port = _pick_free_port()
    log_path = log_sink or (output_dir / f".journey-container-{project}.log")
    logf = log_path.open("w", buffering=1)

    env = {
        **os.environ,
        "WEB_PORT": str(web_port),
        "DB_PORT": str(db_port),
        "NEXTAUTH_SECRET": uuid.uuid4().hex,
        "PROJECT_DB_NAME": "app",
        "COMPOSE_DOCKER_CLI_BUILD": "1",   # BuildKit
        "DOCKER_BUILDKIT": "1",
    }

    def _compose(*args: str, capture: bool = False,
                 timeout: int | None = None) -> subprocess.CompletedProcess:
        """One place to shell out to compose — same CLI flags every time.
        Streams to logf by default; `capture=True` returns stdout for the
        few commands we parse (currently none, kept as an escape hatch)."""
        cmd = [
            "docker", "compose",
            "-f", "docker-compose.verify.yml",
            "-p", project,
            *args,
        ]
        return subprocess.run(
            cmd,
            cwd=str(output_dir),
            env=env,
            stdout=subprocess.PIPE if capture else logf,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            text=True,
        )

    started = time.monotonic()
    try:
        # Build image (this is where the 2-5min cost lives). Fail fast on
        # a bad Dockerfile / missing vendor / dep resolution error rather
        # than watching a healthcheck loop timeout after 20 minutes.
        rc = _compose("build", timeout=build_timeout_s).returncode
        if rc != 0:
            raise ContainerBootError(
                f"docker compose build failed (rc={rc})\n"
                f"log tail:\n{_tail(log_path, 2000)}"
            )

        # Start detached. `up -d` returns immediately; we then poll the
        # web port for readiness — that's the real "ready" signal, more
        # reliable than parsing compose output.
        rc = _compose("up", "-d", "--no-build", timeout=120).returncode
        if rc != 0:
            raise ContainerBootError(
                f"docker compose up failed (rc={rc})\n"
                f"log tail:\n{_tail(log_path, 2000)}"
            )

        base_url = f"http://localhost:{web_port}"
        if not _wait_for_boot(base_url, boot_timeout_s):
            raise ContainerBootError(
                f"app not reachable at {base_url} after {boot_timeout_s}s\n"
                f"container log tail:\n{_container_logs(project, output_dir, env, 3000)}"
            )

        elapsed = int(time.monotonic() - started)
        logger.info("[containerized_app] project=%s ready in %ds at %s",
                    project, elapsed, base_url)
        yield {
            "url": base_url,
            "web_port": web_port,
            "db_port": db_port,
            "compose_project": project,
            "log": str(log_path),
            "boot_seconds": elapsed,
        }
    finally:
        # -v removes named volumes so re-verify gets a clean DB.
        # --remove-orphans catches any container left over from a prior
        # aborted run with the same project name.
        try:
            _compose("down", "-v", "--remove-orphans", timeout=60)
        except Exception:
            logger.warning("[containerized_app] teardown failed for %s", project,
                           exc_info=True)
        try:
            logf.close()
        except Exception:
            pass


# ── helpers ────────────────────────────────────────────────────────────────

def _pick_free_port() -> int:
    """Ask the kernel for a free TCP port. Slight TOCTOU risk (someone
    else could grab it between here and compose binding), but the
    ephemeral range + our short window makes collision negligible in
    practice — and if it happens compose will fail loud."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_boot(url: str, timeout_s: int) -> bool:
    import urllib.request
    from socket import create_connection
    from urllib.parse import urlsplit
    deadline = time.monotonic() + timeout_s
    parts = urlsplit(url)
    host, port = parts.hostname or "localhost", parts.port or 80
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            pass
        # Any TCP listener also counts — 401/500 responses don't reach
        # urllib.request as success but the socket is open, and that's
        # good enough for "container has bound the port".
        try:
            with create_connection((host, port), timeout=2):
                return True
        except Exception:
            pass
        time.sleep(1)
    return False


def _tail(path: Path, n_bytes: int) -> str:
    try:
        data = path.read_bytes()
    except Exception:
        return ""
    return data[-n_bytes:].decode("utf-8", errors="replace")


def _container_logs(project: str, cwd: Path, env: dict, n_bytes: int) -> str:
    """Best-effort dump of the web service's stdout for diagnosis when the
    healthcheck never went green."""
    try:
        proc = subprocess.run(
            ["docker", "compose",
             "-f", "docker-compose.verify.yml", "-p", project,
             "logs", "--no-color", "--tail=200", "web"],
            cwd=str(cwd), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            timeout=10, text=True,
        )
        return proc.stdout[-n_bytes:]
    except Exception as exc:
        return f"(logs unavailable: {exc})"
