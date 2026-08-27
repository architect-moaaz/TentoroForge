"""Unit tests for build_snapshot — turns a generated-app dir into the
files[] payload Vercel's create_deployment expects."""
from __future__ import annotations

from pathlib import Path

import pytest

from services.deploy.snapshot import (
    SnapshotTooLarge,
    build_snapshot,
    build_snapshot_upload,
)


def _mk(root: Path, path: str, content: bytes | str = b"") -> Path:
    full = root / path
    full.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        full.write_text(content)
    else:
        full.write_bytes(content)
    return full


def test_includes_source_files(tmp_path: Path) -> None:
    _mk(tmp_path, "package.json", '{"name":"x"}')
    _mk(tmp_path, "src/app.tsx", "export default () => null;")
    _mk(tmp_path, "next.config.js", "module.exports = {};")

    files = build_snapshot(tmp_path)
    paths = {f["file"] for f in files}
    assert paths == {"package.json", "src/app.tsx", "next.config.js"}


def test_excludes_build_and_secret_files(tmp_path: Path) -> None:
    _mk(tmp_path, "package.json", "{}")
    _mk(tmp_path, "node_modules/foo/index.js", "bar")
    _mk(tmp_path, ".next/chunk.js", "bar")
    _mk(tmp_path, ".env", "SECRET=1")
    _mk(tmp_path, ".env.local", "SECRET=1")
    _mk(tmp_path, ".git/config", "[core]")
    _mk(tmp_path, ".DS_Store", "x")

    files = build_snapshot(tmp_path)
    paths = {f["file"] for f in files}
    assert paths == {"package.json"}


def test_encodes_binary_files_as_base64(tmp_path: Path) -> None:
    _mk(tmp_path, "public/logo.png", b"\x89PNG\r\n\x1a\n\xff\xfe")
    _mk(tmp_path, "package.json", "{}")

    files = build_snapshot(tmp_path)
    logo = next(f for f in files if f["file"] == "public/logo.png")
    assert logo["encoding"] == "base64"
    # base64 alphabet only
    assert all(
        c.isalnum() or c in "+/=" for c in logo["data"]
    ), "base64 content should not leak raw bytes"


def test_utf8_text_stays_plain(tmp_path: Path) -> None:
    _mk(tmp_path, "src/greet.ts", "export const s = 'héllo';")
    _mk(tmp_path, "package.json", "{}")

    files = build_snapshot(tmp_path)
    greet = next(f for f in files if f["file"] == "src/greet.ts")
    assert "encoding" not in greet, "utf-8 text should ship plain, not base64"
    assert "héllo" in greet["data"]


def test_rejects_oversized_single_file(tmp_path: Path) -> None:
    _mk(tmp_path, "big.bin", b"0" * (101 * 1024 * 1024))
    with pytest.raises(SnapshotTooLarge):
        build_snapshot(tmp_path)


def test_rejects_oversized_total_snapshot(tmp_path: Path) -> None:
    # Three 90 MB files → 270 MB > 250 MB cap
    for i in range(3):
        _mk(tmp_path, f"chunks/{i}.bin", b"0" * (90 * 1024 * 1024))
    with pytest.raises(SnapshotTooLarge):
        build_snapshot(tmp_path)


def test_returns_deterministic_order(tmp_path: Path) -> None:
    _mk(tmp_path, "z.txt", "z")
    _mk(tmp_path, "a.txt", "a")
    _mk(tmp_path, "m.txt", "m")
    files = build_snapshot(tmp_path)
    assert [f["file"] for f in files] == ["a.txt", "m.txt", "z.txt"]


# ── build_snapshot_upload ──────────────────────────────────────────

def test_upload_shape_has_sha_size_raw(tmp_path: Path) -> None:
    _mk(tmp_path, "hello.txt", "hi")
    files = build_snapshot_upload(tmp_path)
    assert len(files) == 1
    e = files[0]
    assert e["file"] == "hello.txt"
    assert e["size"] == 2
    assert e["raw"] == b"hi"
    import hashlib
    assert e["sha"] == hashlib.sha1(b"hi").hexdigest()


def test_upload_shape_applies_same_filters(tmp_path: Path) -> None:
    _mk(tmp_path, "src/keep.ts", "// keep")
    _mk(tmp_path, "node_modules/react/index.js", "// skip")
    _mk(tmp_path, ".env", "SECRET=nope")
    files = build_snapshot_upload(tmp_path)
    assert [f["file"] for f in files] == ["src/keep.ts"]


def test_upload_shape_rejects_oversized_single_file(tmp_path: Path) -> None:
    _mk(tmp_path, "big.bin", b"0" * (101 * 1024 * 1024))
    with pytest.raises(SnapshotTooLarge):
        build_snapshot_upload(tmp_path)
