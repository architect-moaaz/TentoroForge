"""figma_overlay_strip — in-shell pages lose the full-bleed escape flag."""
from __future__ import annotations

import json
from pathlib import Path

from services.figma_overlay_strip import strip_figma_overlay


def _mkapp(tmp_path, shell_targets=("/dashboard", "/history")):
    out = tmp_path / "app"
    schemas = out / "src" / "schemas"
    schemas.mkdir(parents=True)
    shell = {
        "id": "shell",
        "children": [
            {"type": "NavLink", "props": {"label": t.strip("/").title() or "Home",
                                          "navigate": t}}
            for t in shell_targets
        ],
    }
    (schemas / "shell.json").write_text(json.dumps(shell), encoding="utf-8")
    return out, schemas


def test_strips_flag_from_menu_pages_only(tmp_path):
    out, schemas = _mkapp(tmp_path)
    (schemas / "dashboard.json").write_text(json.dumps(
        {"route": "/dashboard", "_figmaDerived": True, "root": {"type": "Stack"}}), encoding="utf-8")
    # /login is NOT in the shell menu — a standalone Figma page keeps its escape.
    (schemas / "login.json").write_text(json.dumps(
        {"route": "/login", "_figmaDerived": True, "root": {"type": "Stack"}}), encoding="utf-8")
    res = strip_figma_overlay(str(out))
    assert res["stripped"] == 1
    assert "_figmaDerived" not in json.loads((schemas / "dashboard.json").read_text(encoding="utf-8"))
    assert json.loads((schemas / "login.json").read_text(encoding="utf-8"))["_figmaDerived"] is True


def test_route_derived_from_path_when_missing(tmp_path):
    out, schemas = _mkapp(tmp_path, shell_targets=("/history",))
    (schemas / "history.json").write_text(json.dumps(
        {"_figmaDerived": True, "root": {"type": "Stack"}}), encoding="utf-8")
    res = strip_figma_overlay(str(out))
    assert res["stripped"] == 1


def test_idempotent_and_noop_without_shell(tmp_path):
    out, schemas = _mkapp(tmp_path)
    (schemas / "dashboard.json").write_text(json.dumps(
        {"route": "/dashboard", "_figmaDerived": True, "root": {"type": "Stack"}}), encoding="utf-8")
    strip_figma_overlay(str(out))
    assert strip_figma_overlay(str(out))["stripped"] == 0
    # no shell.json → leave everything alone
    (schemas / "shell.json").unlink()
    (schemas / "dashboard.json").write_text(json.dumps(
        {"route": "/dashboard", "_figmaDerived": True, "root": {"type": "Stack"}}), encoding="utf-8")
    assert strip_figma_overlay(str(out))["stripped"] == 0
