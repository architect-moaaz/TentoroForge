"""Tests for the GATED, read-only runtime probe (Fix-Assistant, Task 2-C).

The probe is the slice-2 evidence seam the diagnoser MAY request before
proposing. It is read-only, bounded (timeout + max bytes/lines), and never
writes. No real network here — ``read_endpoint`` goes through an injected
``http_get`` stub; logs come from a temp file.
"""
from __future__ import annotations

from pathlib import Path

from services.fix_probe import probe


# --------------------------------------------------------------------------- #
# logs
# --------------------------------------------------------------------------- #

def test_probe_logs_reads_capped(tmp_path: Path):
    log = tmp_path / "logs" / "server.log"
    log.parent.mkdir(parents=True)
    log.write_text("\n".join(f"line-{i}" for i in range(500)) + "\n")

    res = probe(str(tmp_path), {"kind": "logs"}, max_lines=100)

    assert res["available"] is True
    ev = res["evidence"]
    assert ev["kind"] == "logs"
    # Capped to the last max_lines, and flagged truncated.
    assert len(ev["lines"]) == 100
    assert ev["lines"][-1] == "line-499"
    assert ev["truncated"] is True
    assert ev["path"].endswith("logs/server.log")


def test_probe_logs_explicit_path(tmp_path: Path):
    log = tmp_path / "my-dev.log"
    log.write_text("hello\nworld\n")

    res = probe(str(tmp_path), {"kind": "logs", "path": "my-dev.log"}, max_lines=50)

    assert res["available"] is True
    assert res["evidence"]["lines"] == ["hello", "world"]
    assert res["evidence"]["truncated"] is False


def test_probe_logs_missing_is_unavailable(tmp_path: Path):
    res = probe(str(tmp_path), {"kind": "logs"})
    assert res["available"] is False
    assert res["evidence"] is None
    assert "reason" in res  # honest, no crash


def test_probe_logs_byte_capped(tmp_path: Path):
    log = tmp_path / "logs" / "console.log"
    log.parent.mkdir(parents=True)
    log.write_text("x" * 200_000 + "\ntail-line\n")

    res = probe(str(tmp_path), {"kind": "logs"}, max_bytes=1024, max_lines=100)

    assert res["available"] is True
    assert res["evidence"]["truncated"] is True
    # Only the tail (<= max_bytes) was read — the giant leading line is gone.
    assert res["evidence"]["lines"][-1] == "tail-line"


# --------------------------------------------------------------------------- #
# read_endpoint (stubbed getter — never real network)
# --------------------------------------------------------------------------- #

def test_probe_read_endpoint_stubbed(tmp_path: Path):
    calls = []

    def _stub_get(url, *, timeout):
        calls.append((url, timeout))
        return {"status": 200, "body": "pong"}

    res = probe(
        str(tmp_path),
        {"kind": "read_endpoint", "url": "http://localhost:6500/api/health"},
        http_get=_stub_get,
    )

    assert res["available"] is True
    ev = res["evidence"]
    assert ev["kind"] == "read_endpoint"
    assert ev["status"] == 200
    assert ev["body"] == "pong"
    assert calls and calls[0][0] == "http://localhost:6500/api/health"


def test_probe_read_endpoint_down_is_unavailable(tmp_path: Path):
    def _boom(url, *, timeout):
        raise ConnectionError("connection refused")

    res = probe(
        str(tmp_path),
        {"kind": "read_endpoint", "url": "http://127.0.0.1:6500/"},
        http_get=_boom,
    )

    assert res["available"] is False
    assert res["evidence"] is None
    assert "reason" in res  # no crash when the app is down


def test_probe_read_endpoint_refuses_non_local(tmp_path: Path):
    called = {"n": 0}

    def _stub_get(url, *, timeout):
        called["n"] += 1
        return {"status": 200, "body": "should not run"}

    res = probe(
        str(tmp_path),
        {"kind": "read_endpoint", "url": "http://example.com/steal"},
        http_get=_stub_get,
    )

    # A non-local URL is refused BEFORE any request is made.
    assert res["available"] is False
    assert called["n"] == 0
    assert "local" in res["reason"].lower()


def test_probe_read_endpoint_body_capped(tmp_path: Path):
    def _stub_get(url, *, timeout):
        return {"status": 200, "body": "y" * 10_000}

    res = probe(
        str(tmp_path),
        {"kind": "read_endpoint", "url": "http://localhost:3000/"},
        http_get=_stub_get,
        max_bytes=256,
    )

    assert res["available"] is True
    assert len(res["evidence"]["body"]) == 256
    assert res["evidence"]["truncated"] is True


# --------------------------------------------------------------------------- #
# unknown kind
# --------------------------------------------------------------------------- #

def test_probe_unknown_kind(tmp_path: Path):
    res = probe(str(tmp_path), {"kind": "spawn_shell"})
    assert res["available"] is False
    assert "reason" in res
