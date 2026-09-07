"""onboarding_tour_pass — Spec E Wave 3.

Emits src/config/onboarding-tour.json + src/lib/useTour.ts and
injects a <TourOverlay/> mount into the shell/layout when the plan
declares journey.onboarding. Flag-gated on FORGE_E_PATTERNS.
"""
from __future__ import annotations

import json

import pytest

from services.onboarding_tour_pass import (
    enumerate_onboarding_steps,
    is_enabled,
    run,
)


def _write_plan(root, plan):
    d = root / "contracts"
    d.mkdir(parents=True, exist_ok=True)
    (d / "plan.json").write_text(json.dumps(plan), encoding="utf-8")


def _write_shell(root, body='"use client";\nexport default function Layout({ children }) {\n  return (\n    <div>{children}</div>\n  );\n}\n'):
    d = root / "src" / "app"
    d.mkdir(parents=True, exist_ok=True)
    (d / "layout.tsx").write_text(body, encoding="utf-8")


# ── enablement ────────────────────────────────────────────────

def test_disabled_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE_E_PATTERNS", raising=False)
    assert is_enabled() is False
    r = run(str(tmp_path))
    assert r["config_written"] is False
    assert r["helper_written"] is False


def test_enabled_flag(monkeypatch):
    monkeypatch.setenv("FORGE_E_PATTERNS", "yes")
    assert is_enabled() is True


# ── no-op paths ────────────────────────────────────────────────

def test_no_journey_onboarding_key(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_E_PATTERNS", "1")
    _write_plan(tmp_path, {})
    r = run(str(tmp_path))
    assert r["steps"] == 0
    assert not (tmp_path / "src" / "config" / "onboarding-tour.json").exists()


def test_dropped_malformed_steps(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_E_PATTERNS", "1")
    _write_plan(tmp_path, {
        "journey": {"onboarding": {"steps": [
            "not a dict",
            {"target_selector": "", "title": "Bad"},
            {"title": "No selector"},
            {"target_selector": "#ok"},  # missing title
        ]}}
    })
    r = run(str(tmp_path))
    assert r["steps"] == 0


# ── happy paths ────────────────────────────────────────────────

def test_emits_config_and_helper(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_E_PATTERNS", "1")
    _write_plan(tmp_path, {
        "journey": {"onboarding": {"steps": [
            {"target_selector": "#nav-new", "title": "Create",
             "body": "Start here", "page": "/"},
            {"target": "#nav-invite", "title": "Invite"},
        ]}}
    })
    r = run(str(tmp_path))
    assert r["steps"] == 2
    assert r["config_written"] is True
    assert r["helper_written"] is True
    cfg = json.loads((tmp_path / "src" / "config" / "onboarding-tour.json").read_text(encoding="utf-8"))
    assert cfg["storageKey"] == "forge-onboarding-tour"
    assert cfg["steps"][0]["target"] == "#nav-new"
    assert cfg["steps"][0]["body"] == "Start here"
    assert cfg["steps"][1]["target"] == "#nav-invite"
    helper = (tmp_path / "src" / "lib" / "useTour.ts").read_text(encoding="utf-8")
    assert "useTour" in helper


def test_shell_injection_adds_import_and_mount(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_E_PATTERNS", "1")
    _write_plan(tmp_path, {
        "journey": {"onboarding": {"steps": [
            {"target_selector": "#a", "title": "A"},
        ]}}
    })
    _write_shell(tmp_path)
    r = run(str(tmp_path))
    assert r["shells_patched"] == ["src/app/layout.tsx"]
    src = (tmp_path / "src" / "app" / "layout.tsx").read_text(encoding="utf-8")
    assert "TourOverlay" in src
    assert "useTour" in src


def test_shell_injection_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_E_PATTERNS", "1")
    _write_plan(tmp_path, {
        "journey": {"onboarding": {"steps": [
            {"target_selector": "#a", "title": "A"},
        ]}}
    })
    _write_shell(tmp_path)
    run(str(tmp_path))
    r2 = run(str(tmp_path))
    # Second run: shell already has TourOverlay, so no re-patch.
    assert r2["shells_patched"] == []


def test_enumerate_helper(tmp_path):
    _write_plan(tmp_path, {
        "journey": {"onboarding": {"steps": [
            {"target_selector": "#a", "title": "A"},
        ]}}
    })
    steps = enumerate_onboarding_steps(str(tmp_path))
    assert steps == [{"target": "#a", "title": "A"}]
