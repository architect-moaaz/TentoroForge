"""Tests for aggregate_metrics_guard — inject missing ``metrics`` entries onto
op:"aggregate" dataSources whose dotted bindings would otherwise resolve to
undefined and blank the KPI tiles."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import pytest

from services.aggregate_metrics_guard import guard_aggregate_metrics

def _subset(result: dict, expected: dict) -> dict:
    """Project a guard's return dict down to the keys the test asserts on.

    Whole-dict equality breaks every time a guard gains a counter (e.g.
    ``asserts_logged`` from the authority demotions) even though the
    behaviour under test is unchanged. Compare only what the test means.
    """
    return {k: result.get(k) for k in expected}


# The MRR-movement dashboard's registry, verbatim to the dz6jba0x bug: numeric
# metric columns on MonthlyMrrSnapshot + a non-numeric field the LLM might
# reference by accident.
_REGISTRY = {
    "entities": {
        "MonthlyMrrSnapshot": {
            "fields": {
                "id": {"type": "uuid", "nullable": False, "primaryKey": True},
                "year": {"type": "integer"},
                "month": {"type": "integer"},
                "totalMrr": {"type": "decimal"},
                "newMrr": {"type": "decimal"},
                "expansionMrr": {"type": "decimal"},
                "contractionMrr": {"type": "decimal"},
                "churnedMrr": {"type": "decimal"},
                "notes": {"type": "text"},
                "createdAt": {"type": "timestamp"},
            }
        }
    }
}


def _write_project(tmp_path: Path, schemas: dict[str, dict], registry=_REGISTRY) -> str:
    sdir = tmp_path / "src" / "schemas"
    sdir.mkdir(parents=True, exist_ok=True)
    for name, doc in schemas.items():
        (sdir / name).write_text(json.dumps(doc), encoding="utf-8")
    (tmp_path / "registry.json").write_text(json.dumps(registry), encoding="utf-8")
    return str(tmp_path)


def _load_schema(out: str, name: str) -> dict:
    with open(os.path.join(out, "src", "schemas", name)) as fh:
        return json.load(fh)


def _stat(label: str, value_binding: str) -> dict:
    return {
        "type": "MetricTile",
        "props": {"label": label, "value": value_binding},
    }


# --- The dz6jba0x bug, exactly ------------------------------------------------


def _mrr_page_missing_metrics() -> dict:
    return {
        "id": "mrr-movement", "route": "/mrr-movement",
        "dataSources": [
            {
                "name": "mrrSummary",
                "entity": "MonthlyMrrSnapshot",
                "op": "aggregate",
                # NO metrics block — the bug.
            },
        ],
        "root": {
            "type": "Stack",
            "children": [
                _stat("New MRR",         "{{mrrSummary.newMrr}}"),
                _stat("Expansion MRR",   "{{mrrSummary.expansionMrr}}"),
                _stat("Contraction MRR", "{{mrrSummary.contractionMrr}}"),
                _stat("Churned MRR",     "{{mrrSummary.churnedMrr}}"),
            ],
        },
    }


def test_dz6jba0x_bug_metrics_injected(tmp_path):
    out = _write_project(tmp_path, {"mrr.json": _mrr_page_missing_metrics()})
    res = guard_aggregate_metrics(out)

    assert res["injected"] == 4
    assert res["files_changed"] == 1
    assert res["unresolved"] == []

    page = _load_schema(out, "mrr.json")
    metrics = page["dataSources"][0]["metrics"]
    assert metrics == {
        "newMrr":         {"fn": "sum", "field": "newMrr"},
        "expansionMrr":   {"fn": "sum", "field": "expansionMrr"},
        "contractionMrr": {"fn": "sum", "field": "contractionMrr"},
        "churnedMrr":     {"fn": "sum", "field": "churnedMrr"},
    }


# --- Idempotency --------------------------------------------------------------


def test_second_run_is_a_noop(tmp_path):
    out = _write_project(tmp_path, {"mrr.json": _mrr_page_missing_metrics()})
    guard_aggregate_metrics(out)
    on_disk_after_first = _load_schema(out, "mrr.json")

    res2 = guard_aggregate_metrics(out)
    assert res2["injected"] == 0
    assert res2["files_changed"] == 0
    assert res2["unresolved"] == []

    assert _load_schema(out, "mrr.json") == on_disk_after_first


def test_partial_metrics_only_backfills_the_gap(tmp_path):
    """A dataSource with SOME metrics already present has only the missing keys
    injected — existing entries are preserved unchanged."""
    page = _mrr_page_missing_metrics()
    page["dataSources"][0]["metrics"] = {
        # LLM authored one but forgot the other three.
        "newMrr": {"fn": "sum", "field": "newMrr"},
    }
    out = _write_project(tmp_path, {"mrr.json": page})
    res = guard_aggregate_metrics(out)

    assert res["injected"] == 3
    metrics = _load_schema(out, "mrr.json")["dataSources"][0]["metrics"]
    assert metrics["newMrr"] == {"fn": "sum", "field": "newMrr"}
    assert set(metrics) == {"newMrr", "expansionMrr", "contractionMrr", "churnedMrr"}


def test_case_insensitive_match_uses_registry_casing_and_skips_dupes(tmp_path):
    """A binding of {{S.NewMrr}} finds the real ``newMrr`` column and injects
    with the binding key + the real column name — and a following {{S.newMrr}}
    is treated as a duplicate."""
    page = _mrr_page_missing_metrics()
    page["root"]["children"] = [
        _stat("New MRR (upper)", "{{mrrSummary.NewMrr}}"),
        _stat("New MRR (lower)", "{{mrrSummary.newMrr}}"),
    ]
    out = _write_project(tmp_path, {"mrr.json": page})
    res = guard_aggregate_metrics(out)

    metrics = _load_schema(out, "mrr.json")["dataSources"][0]["metrics"]
    # One entry injected; field name matches the real column casing.
    assert len(metrics) == 1
    only_key = next(iter(metrics))
    assert only_key in ("NewMrr", "newMrr")
    assert metrics[only_key] == {"fn": "sum", "field": "newMrr"}
    assert res["injected"] == 1


# --- Diagnostics for keys with no numeric backing column ----------------------


def test_non_numeric_key_reports_diagnostic_not_silent(tmp_path, caplog):
    """A key whose entity column is not numeric (or doesn't exist) is emitted
    as a diagnostic, never silently injected."""
    page = _mrr_page_missing_metrics()
    page["root"]["children"] = [
        _stat("Notes text", "{{mrrSummary.notes}}"),   # text column
        _stat("Missing",    "{{mrrSummary.mystery}}"), # no such column
    ]
    out = _write_project(tmp_path, {"mrr.json": page})
    with caplog.at_level(logging.WARNING, logger="services.aggregate_metrics_guard"):
        res = guard_aggregate_metrics(out)

    assert res["injected"] == 0
    routes = {(u["source"], u["key"]) for u in res["unresolved"]}
    assert routes == {("mrrSummary", "notes"), ("mrrSummary", "mystery")}
    # Diagnostic identifies the route + the missing key clearly.
    text = " ".join(r.getMessage() for r in caplog.records)
    assert "notes" in text and "mystery" in text and "/mrr-movement" in text


def test_strict_mode_logs_error(tmp_path, caplog, monkeypatch):
    """Under FORGE_BINDING_GATE strict, unresolved diagnostics are ERROR-level
    so guard_result's capture_guard_logs surfaces them as failures."""
    monkeypatch.setenv("FORGE_BINDING_GATE", "strict")
    page = _mrr_page_missing_metrics()
    page["root"]["children"] = [_stat("Missing", "{{mrrSummary.mystery}}")]
    out = _write_project(tmp_path, {"mrr.json": page})

    with caplog.at_level(logging.DEBUG, logger="services.aggregate_metrics_guard"):
        guard_aggregate_metrics(out)

    errors = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert errors, "expected an ERROR-level diagnostic under FORGE_BINDING_GATE=strict"


def test_warn_mode_default(tmp_path, caplog, monkeypatch):
    monkeypatch.delenv("FORGE_BINDING_GATE", raising=False)
    page = _mrr_page_missing_metrics()
    page["root"]["children"] = [_stat("Missing", "{{mrrSummary.mystery}}")]
    out = _write_project(tmp_path, {"mrr.json": page})

    with caplog.at_level(logging.DEBUG, logger="services.aggregate_metrics_guard"):
        guard_aggregate_metrics(out)

    assert not [r for r in caplog.records if r.levelno == logging.ERROR]
    assert [r for r in caplog.records if r.levelno == logging.WARNING]


# --- Edge cases ---------------------------------------------------------------


def test_non_aggregate_sources_are_ignored(tmp_path):
    """An op:"list" source with dotted bindings must NEVER have metrics added."""
    page = {
        "route": "/subs",
        "dataSources": [{"name": "subs", "entity": "MonthlyMrrSnapshot", "op": "list"}],
        "root": {"type": "Stack", "children": [_stat("First", "{{subs.newMrr}}")]},
    }
    out = _write_project(tmp_path, {"subs.json": page})
    res = guard_aggregate_metrics(out)

    assert res["injected"] == 0
    ds = _load_schema(out, "subs.json")["dataSources"][0]
    assert "metrics" not in ds


def test_no_bindings_no_write(tmp_path):
    """An aggregate source that no page binding references stays untouched
    (and the file isn't rewritten)."""
    page = {
        "route": "/x",
        "dataSources": [
            {"name": "orphan", "entity": "MonthlyMrrSnapshot", "op": "aggregate"},
        ],
        "root": {"type": "Stack", "children": [_stat("Static", "42")]},
    }
    out = _write_project(tmp_path, {"x.json": page})
    res = guard_aggregate_metrics(out)

    assert res["injected"] == 0
    assert res["files_changed"] == 0
    ds = _load_schema(out, "x.json")["dataSources"][0]
    assert "metrics" not in ds


def test_multiple_aggregate_sources_on_one_page(tmp_path):
    page = {
        "route": "/multi",
        "dataSources": [
            {"name": "aggA", "entity": "MonthlyMrrSnapshot", "op": "aggregate"},
            {"name": "aggB", "entity": "MonthlyMrrSnapshot", "op": "aggregate"},
        ],
        "root": {"type": "Stack", "children": [
            _stat("A", "{{aggA.newMrr}}"),
            _stat("B", "{{aggB.churnedMrr}}"),
        ]},
    }
    out = _write_project(tmp_path, {"m.json": page})
    guard_aggregate_metrics(out)

    ds = _load_schema(out, "m.json")["dataSources"]
    a = next(d for d in ds if d["name"] == "aggA")
    b = next(d for d in ds if d["name"] == "aggB")
    assert a["metrics"] == {"newMrr": {"fn": "sum", "field": "newMrr"}}
    assert b["metrics"] == {"churnedMrr": {"fn": "sum", "field": "churnedMrr"}}


def test_no_schemas_dir_returns_zero(tmp_path):
    """Missing src/schemas is not an error — just a no-op."""
    res = guard_aggregate_metrics(str(tmp_path))
    assert _subset(res, {"files_scanned": 0, "files_changed": 0, "injected": 0, "unresolved": []}) == {"files_scanned": 0, "files_changed": 0, "injected": 0, "unresolved": []}


def test_missing_registry_still_scans_and_reports(tmp_path):
    """Without a registry, every referenced key is unresolved — but the guard
    doesn't crash."""
    sdir = tmp_path / "src" / "schemas"
    sdir.mkdir(parents=True)
    (sdir / "mrr.json").write_text(json.dumps(_mrr_page_missing_metrics()), encoding="utf-8")
    # NO registry.json written.
    res = guard_aggregate_metrics(str(tmp_path))
    assert res["injected"] == 0
    # 4 bindings referenced, none can be resolved → 4 diagnostics.
    assert len(res["unresolved"]) == 4


def test_unknown_entity_reports_unresolved(tmp_path):
    """An aggregate whose ``entity`` doesn't exist in the registry can never be
    injected — every referenced key is reported."""
    page = {
        "route": "/ghost",
        "dataSources": [{"name": "g", "entity": "NoSuchEntity", "op": "aggregate"}],
        "root": {"type": "Stack", "children": [_stat("k", "{{g.newMrr}}")]},
    }
    out = _write_project(tmp_path, {"g.json": page})
    res = guard_aggregate_metrics(out)
    assert res["injected"] == 0
    assert res["unresolved"] == [{"route": "/ghost", "source": "g", "key": "newMrr"}]


def test_numeric_with_precision_suffix_is_recognized(tmp_path):
    """``numeric(10,2)`` must count as a numeric type — Postgres precision
    suffixes should not defeat the type check."""
    reg = {
        "entities": {
            "E": {
                "fields": {
                    "id": {"type": "uuid"},
                    "amount": {"type": "numeric(10,2)"},
                }
            }
        }
    }
    page = {
        "route": "/e",
        "dataSources": [{"name": "s", "entity": "E", "op": "aggregate"}],
        "root": {"type": "Stack", "children": [_stat("Amt", "{{s.amount}}")]},
    }
    out = _write_project(tmp_path, {"e.json": page}, registry=reg)
    guard_aggregate_metrics(out)
    m = _load_schema(out, "e.json")["dataSources"][0]["metrics"]
    assert m == {"amount": {"fn": "sum", "field": "amount"}}
