"""Tests for JV-15c artifact emitter.

Focus: files land in the right place, idempotency doesn't clobber a
user-authored .dockerignore, missing templates is a soft skip.
"""
from __future__ import annotations

from pathlib import Path

from services import emit_verify_container as evc


def test_writes_all_three_when_missing(tmp_path):
    res = evc.emit_verify_container_artifacts(str(tmp_path))
    assert res["skipped"] is False
    assert set(res["written"]) == {
        "Dockerfile.verify", "docker-compose.verify.yml", ".dockerignore",
    }
    assert (tmp_path / "Dockerfile.verify").exists()
    assert (tmp_path / "docker-compose.verify.yml").exists()
    assert (tmp_path / ".dockerignore").exists()


def test_preserves_existing_dockerignore(tmp_path):
    marker = "USER_AUTHORED — do not clobber\n"
    (tmp_path / ".dockerignore").write_text(marker)
    res = evc.emit_verify_container_artifacts(str(tmp_path))
    assert ".dockerignore" not in (res.get("written") or [])
    assert (tmp_path / ".dockerignore").read_text() == marker


def test_dockerfile_and_compose_overwrite_on_reemit(tmp_path):
    """Regenerated per build so template improvements propagate."""
    (tmp_path / "Dockerfile.verify").write_text("STALE\n")
    res = evc.emit_verify_container_artifacts(str(tmp_path))
    assert "Dockerfile.verify" in res["written"]
    assert (tmp_path / "Dockerfile.verify").read_text() != "STALE\n"


def test_skips_when_output_dir_missing(tmp_path):
    res = evc.emit_verify_container_artifacts(str(tmp_path / "nope"))
    assert res["skipped"] is True


def test_skips_when_templates_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(evc, "_TEMPLATES", tmp_path / "nowhere")
    res = evc.emit_verify_container_artifacts(str(tmp_path))
    assert res["skipped"] is True
    assert "templates" in res["reason"]
