"""Tests for services.alias_unknown_components.

Covers:
  * an unknown ``type`` with an alias → rewritten
  * an unknown ``type`` without an alias → untouched
  * a known ``type`` → untouched (passes through)
  * an alias whose target isn't in the registry → not applied
  * nested/list traversal (aliases inside ``children`` arrays)
  * missing registry file → graceful no-op
  * idempotency (second run rewrites zero nodes)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.alias_unknown_components import _ALIASES, run


def _write_schema(root: Path, rel: str, data: dict) -> Path:
    p = root / "src" / "schemas" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _stub_registry(root: Path, names: list[str]) -> None:
    """Write a minimal ``packages/registry/dist/starter.json`` next to the
    given output root. ``run()`` looks two levels up from the output_dir
    for the registry, so the layout here is:
        <tmp>/packages/registry/dist/starter.json
        <tmp>/output/<id>/  ← the ``output_dir`` passed to run()
    """
    reg = root / "packages" / "registry" / "dist" / "starter.json"
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text(json.dumps({n: {} for n in names}), encoding="utf-8")


def _make_output(tmp_path: Path) -> Path:
    out = tmp_path / "output" / "app_test"
    out.mkdir(parents=True)
    return out


def test_aliases_datetime_picker_to_date_picker(tmp_path: Path) -> None:
    out = _make_output(tmp_path)
    _stub_registry(tmp_path, ["DatePicker", "Input", "Stack", "Form"])
    schema_path = _write_schema(out, "new.json", {
        "root": {"type": "Stack", "children": [
            {"type": "Form", "children": [
                {"type": "DateTimePicker", "props": {"name": "startAt"}},
            ]},
        ]},
    })
    res = run(str(out))
    assert res == {"aliased": 1, "files": 1}
    after = json.loads(schema_path.read_text(encoding="utf-8"))
    assert after["root"]["children"][0]["children"][0]["type"] == "DatePicker"


def test_unknown_without_alias_untouched(tmp_path: Path) -> None:
    out = _make_output(tmp_path)
    _stub_registry(tmp_path, ["DatePicker"])
    schema_path = _write_schema(out, "new.json", {
        "root": {"type": "MysteryComponent", "props": {}},
    })
    res = run(str(out))
    assert res == {"aliased": 0, "files": 0}
    after = json.loads(schema_path.read_text(encoding="utf-8"))
    assert after["root"]["type"] == "MysteryComponent"


def test_known_type_passes_through(tmp_path: Path) -> None:
    out = _make_output(tmp_path)
    _stub_registry(tmp_path, ["DatePicker", "Input"])
    schema_path = _write_schema(out, "new.json", {
        "root": {"type": "Input", "props": {"name": "x"}},
    })
    res = run(str(out))
    assert res["aliased"] == 0
    after = json.loads(schema_path.read_text(encoding="utf-8"))
    assert after["root"]["type"] == "Input"


def test_alias_target_not_registered_skipped(tmp_path: Path) -> None:
    """If the alias target itself isn't in the registry, we must NOT rewrite —
    that would produce a different broken node."""
    out = _make_output(tmp_path)
    # DatePicker missing from registry, so DateTimePicker→DatePicker must not fire.
    _stub_registry(tmp_path, ["Input", "Form"])
    schema_path = _write_schema(out, "new.json", {
        "root": {"type": "DateTimePicker", "props": {"name": "startAt"}},
    })
    res = run(str(out))
    assert res == {"aliased": 0, "files": 0}
    after = json.loads(schema_path.read_text(encoding="utf-8"))
    assert after["root"]["type"] == "DateTimePicker"


def test_missing_registry_is_noop(tmp_path: Path) -> None:
    out = _make_output(tmp_path)
    # No registry stub — file doesn't exist.
    _write_schema(out, "new.json", {
        "root": {"type": "DateTimePicker", "props": {}},
    })
    res = run(str(out))
    assert res == {"aliased": 0, "files": 0}


def test_multiple_files_and_nodes(tmp_path: Path) -> None:
    out = _make_output(tmp_path)
    _stub_registry(tmp_path, ["DatePicker", "TimePicker", "Input", "Textarea",
                              "NumberInput", "Form", "Stack"])
    _write_schema(out, "a/new.json", {"root": {"type": "Stack", "children": [
        {"type": "DateTimePicker"}, {"type": "TextField"}, {"type": "NumberField"},
    ]}})
    _write_schema(out, "b/new.json", {"root": {"type": "TimeField"}})
    res = run(str(out))
    assert res["files"] == 2
    assert res["aliased"] == 4


def test_idempotent(tmp_path: Path) -> None:
    out = _make_output(tmp_path)
    _stub_registry(tmp_path, ["DatePicker", "Input", "Form"])
    _write_schema(out, "new.json", {"root": {"type": "DateTimePicker"}})
    run(str(out))
    res2 = run(str(out))
    assert res2 == {"aliased": 0, "files": 0}


def test_alias_table_maps_only_to_valid_targets_when_registry_present(tmp_path: Path) -> None:
    """Documents the intent: Checkbox is NOT in the alias table (it IS
    registered as its own component)."""
    assert "Checkbox" not in _ALIASES
    assert _ALIASES["DateTimePicker"] == "DatePicker"
    assert _ALIASES["TextArea"] == "Textarea"
