"""Composer-authored pages are ASSERT-only for every demoted guard.

The composers (dashboard / collection / record) are the sole writer for the
pages they claim. A guard that still rewrites those pages is fighting the
authority — it undoes a deliberate composition decision and reports a repair
that shouldn't have been needed. Each guard below must count the page and
leave it byte-identical.

The counterpart (guard DOES repair a page no composer claims) is covered by
each guard's own suite; these tests only pin the new skip.
"""
import json
from pathlib import Path

import pytest

from services.artifact_authority import _MARKER_KEY


def _page(marker: str | None, **extra) -> dict:
    """A page schema that every guard below would otherwise want to rewrite."""
    doc = {
        "route": "/things",
        "dataSources": [
            {"name": "things", "entity": "Thing", "op": "aggregate",
             "filter": {"field": "nope", "value": "x"}},
        ],
        "children": [
            # bare surface → bare_container_guard
            {"type": "Card", "children": []},
            # borders → surface_border_guard
            {"type": "Card", "props": {"border": "2px solid red"}, "children": [
                {"type": "Text", "props": {"content": "hi"}}]},
            # bound iframe → file_preview_guard
            {"type": "CustomBlock",
             "props": {"html": '<iframe src="{{thing.fileUrl}}"></iframe>'}},
            # edit/delete buttons → detail_action_guard
            {"type": "Button", "props": {"label": "Edit"}},
            {"type": "Button", "props": {"label": "Delete"}},
        ],
    }
    if marker:
        doc["meta"] = {marker: True}
    doc.update(extra)
    return doc


def _write(root: Path, rel: str, doc: dict) -> Path:
    p = root / "src" / "schemas" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return p


def _scaffold_inputs(root: Path) -> None:
    """Registry + seed plan.

    Three of the demoted guards (detail_action, filter_field,
    list_entity_coherence) return early when these are absent — they have
    nothing to reconcile against. Without them the assert path is never
    reached and the test would pass for the wrong reason.
    """
    (root / "registry.json").write_text(json.dumps({
        "entities": {
            "Thing": {"table": "things",
                      "fields": {"id": "uuid", "name": "text",
                                 "status": "text", "fileUrl": "text"}},
        },
        "relations": [],
    }, indent=2), encoding="utf-8")
    contracts = root / "contracts"
    contracts.mkdir(parents=True, exist_ok=True)
    # filter_field_guard reads `tables[].seed_data`, not `entities` — it
    # harvests observed enum-ish values to remap mis-fielded filters.
    (contracts / "seed-plan.json").write_text(json.dumps({
        "tables": [
            {"name": "things",
             "seed_data": [{"id": "1", "name": "a", "status": "open"},
                           {"id": "2", "name": "b", "status": "closed"}]},
        ],
    }, indent=2), encoding="utf-8")


# Every guard demoted in S2, as (module, entrypoint).
DEMOTED = [
    ("bare_container_guard", "apply_bare_container_guard"),
    ("file_preview_guard", "apply_file_preview_guard"),
    ("surface_border_guard", "harmonize_surface_borders"),
    ("list_entity_coherence_guard", "reconcile_list_entities"),
    ("filter_field_guard", "guard_filter_fields"),
    ("detail_action_guard", "wire_detail_actions"),
    ("aggregate_metrics_guard", "guard_aggregate_metrics"),
]


@pytest.mark.parametrize("module,fn_name", DEMOTED)
def test_composer_authored_page_is_left_byte_identical(
    tmp_path, monkeypatch, module, fn_name
):
    monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
    _scaffold_inputs(tmp_path)
    path = _write(tmp_path, "things.json", _page(_MARKER_KEY["dashboard"]))
    before = path.read_text(encoding="utf-8")

    fn = getattr(__import__(f"services.{module}", fromlist=[fn_name]), fn_name)
    fn(str(tmp_path))

    assert path.read_text(encoding="utf-8") == before, (
        f"{module} rewrote a composer-authored page"
    )


@pytest.mark.parametrize("module,fn_name", DEMOTED)
def test_assert_path_is_counted_not_silent(tmp_path, monkeypatch, module, fn_name):
    """A skip has to be observable — a silent one is indistinguishable from a
    guard that simply found nothing to do."""
    monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
    _scaffold_inputs(tmp_path)
    _write(tmp_path, "things.json", _page(_MARKER_KEY["dashboard"]))

    fn = getattr(__import__(f"services.{module}", fromlist=[fn_name]), fn_name)
    result = fn(str(tmp_path))

    assert isinstance(result, dict)
    assert result.get("asserts_logged", 0) >= 1, f"{module} skipped silently"


@pytest.mark.parametrize("module,fn_name", DEMOTED)
def test_unmarked_page_still_reaches_the_repair_path(
    tmp_path, monkeypatch, module, fn_name
):
    """No marker → no composer owns it → the guard must NOT take the assert
    path. Guards still do real work on auth / search / custom pages."""
    monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "1")
    _scaffold_inputs(tmp_path)
    _write(tmp_path, "things.json", _page(None))

    fn = getattr(__import__(f"services.{module}", fromlist=[fn_name]), fn_name)
    result = fn(str(tmp_path))

    assert result.get("asserts_logged", 0) == 0, (
        f"{module} asserted on a page no composer authored"
    )


@pytest.mark.parametrize("module,fn_name", DEMOTED)
def test_marker_without_the_flag_does_not_assert(
    tmp_path, monkeypatch, module, fn_name
):
    """Authority off ⇒ old behaviour. The marker alone must not disable a
    guard, or turning a flag off would silently stop repairing."""
    monkeypatch.setenv("FORGE_DASHBOARD_AUTHORITY", "0")
    monkeypatch.setenv("FORGE_COLLECTION_AUTHORITY", "0")
    monkeypatch.setenv("FORGE_RECORD_AUTHORITY", "0")
    _scaffold_inputs(tmp_path)
    _write(tmp_path, "things.json", _page(_MARKER_KEY["dashboard"]))

    fn = getattr(__import__(f"services.{module}", fromlist=[fn_name]), fn_name)
    result = fn(str(tmp_path))

    assert result.get("asserts_logged", 0) == 0
