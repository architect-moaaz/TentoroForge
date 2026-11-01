"""The boot check starts a real process tree and always ends the whole of it.

A build on Linux reached the boot check and ended with `NameError: name 'signal' is not defined`, leaving `npm run dev` and its
`next-server` child running. The tests that existed read the source text of `verify_boot`, so none of them ran the line that stops the
tree. These start a real one: a fake `npm` that, like the real one, starts a child server of its own and waits for it. After
`verify_boot` returns or fails, neither the fake npm nor its child may still be running and the port must be closed.

POSIX only: Windows ends the tree with `taskkill`, a different path.
"""
import os
import socket
import stat
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from unittest import mock

import pytest

pytestmark = pytest.mark.skipif(os.name == "nt", reason="the POSIX process-group path; Windows ends the tree with taskkill")

CHILD = textwrap.dedent("""
    import http.server, os, sys, time
    port, pidfile, mode = int(sys.argv[1]), sys.argv[2], sys.argv[3]
    open(pidfile, "w").write(str(os.getpid()))
    if mode == "serve":
        class H(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
            def log_message(self, *a): pass
        http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
    else:
        time.sleep(300)
""")


def _fake_npm(bin_dir: Path, child_py: Path, pidfile: Path, mode: str) -> None:
    """`npm run dev -- --port N`: starts a child server (a grandchild of the build) and waits for it, as npm does for next."""
    script = bin_dir / "npm"
    script.write_text(
        "#!/bin/sh\n"
        'while [ "$1" != "--port" ]; do shift; done\n'
        'port="$2"\n'
        f'"{sys.executable}" "{child_py}" "$port" "{pidfile}" {mode} &\n'
        "wait\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


def _alive(pid: int) -> bool:
    """Running, not a zombie waiting to be collected."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError:
        return True
    return state != "Z"


def _wait_gone(pid: int, seconds: float = 8.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return False


def _port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def _run(mode: str, **kwargs):
    """Run verify_boot against the fake npm; returns (result or error, child pid)."""
    from services import dev_servers
    from services.blueprint import assembly

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        app = tmp / "app"
        app.mkdir()
        child_py, pidfile = tmp / "child.py", tmp / "child.pid"
        child_py.write_text(CHILD)
        _fake_npm(bin_dir, child_py, pidfile, mode)
        env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}
        outcome: object
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(dev_servers, "DIR", tmp / "dev-servers"):
            try:
                outcome = assembly.verify_boot(app, **kwargs)
            except Exception as exc:  # noqa: BLE001
                outcome = exc
        pid = int(pidfile.read_text()) if pidfile.exists() else 0
        return outcome, pid


def test_a_server_that_answers_is_stopped_with_everything_it_started():
    outcome, child = _run("serve", timeout=30)
    assert isinstance(outcome, dict), f"the boot check should have passed, got {outcome!r}"
    assert outcome["status"] == 200
    assert child, "the fake server never started"
    assert _wait_gone(child), "the child server (what npm starts) is still running after the boot check"
    assert not _port_open(outcome["port"]), "its port is still open"


def test_a_server_that_never_listens_fails_and_is_still_stopped():
    outcome, child = _run("hang", timeout=3)
    assert type(outcome).__name__ == "BootFailed", f"expected BootFailed, got {outcome!r}"
    assert "did not listen" in str(outcome)
    assert child, "the fake server never started"
    assert _wait_gone(child), "the child of a failed boot check is still running"
