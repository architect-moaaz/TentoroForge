"""Tests for services.reorder_column_pass — Spec E Wave 1."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from services import reorder_column_pass as rcp


def _setup_app(root: Path, schema_ts: str, page: dict) -> None:
    schema_dir = root / "src" / "db" / "schema"
    schemas_dir = root / "src" / "schemas"
    schema_dir.mkdir(parents=True, exist_ok=True)
    schemas_dir.mkdir(parents=True, exist_ok=True)
    (schema_dir / "orders.ts").write_text(schema_ts, encoding="utf-8")
    (schemas_dir / "orders.json").write_text(json.dumps(page), encoding="utf-8")


ORDERS_TS = '''\
import { pgTable, uuid, varchar } from "drizzle-orm/pg-core";

export const orders = pgTable("orders", {
  id: uuid("id").primaryKey().defaultRandom(),
  name: varchar("name", { length: 100 }),
});
'''


ORDERS_PAGE_REORDERABLE = {
    "route": "/orders",
    "entity": "Order",
    "dataSources": [{"op": "list", "entity": "Order"}],
    "content": [
        {"type": "Table", "props": {"reorderable": True, "columns": []}},
    ],
}


ORDERS_PAGE_PLAIN = {
    "route": "/orders",
    "entity": "Order",
    "dataSources": [{"op": "list", "entity": "Order"}],
    "content": [{"type": "Table", "props": {"columns": []}}],
}


def test_is_disabled_without_flag(tmp_path, monkeypatch):
    monkeypatch.delenv("FORGE_E_INTERACTIONS", raising=False)
    _setup_app(tmp_path, ORDERS_TS, ORDERS_PAGE_REORDERABLE)
    report = rcp.run(str(tmp_path))
    assert report["enabled"] is False
    assert report["schema_files_patched"] == []
    # Schema untouched
    assert "sortOrder" not in (tmp_path / "src" / "db" / "schema" / "orders.ts").read_text(encoding="utf-8")


def test_patches_schema_when_reorderable(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_E_INTERACTIONS", "1")
    _setup_app(tmp_path, ORDERS_TS, ORDERS_PAGE_REORDERABLE)
    report = rcp.run(str(tmp_path))
    assert report["enabled"] is True
    assert "Order" in report["entities"]
    assert report["schema_files_patched"], "expected orders.ts to be patched"
    patched = (tmp_path / "src" / "db" / "schema" / "orders.ts").read_text(encoding="utf-8")
    assert "sortOrder" in patched
    assert "integer(" in patched
    # Idempotent — second run does not re-inject
    report2 = rcp.run(str(tmp_path))
    assert report2["schema_files_patched"] == []


def test_skips_when_no_reorderable(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_E_INTERACTIONS", "1")
    _setup_app(tmp_path, ORDERS_TS, ORDERS_PAGE_PLAIN)
    report = rcp.run(str(tmp_path))
    assert report["entities"] == []
    assert report["schema_files_patched"] == []
    assert report["route_copied"] is False


def test_copies_reorder_route(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_E_INTERACTIONS", "1")
    _setup_app(tmp_path, ORDERS_TS, ORDERS_PAGE_REORDERABLE)
    rcp.run(str(tmp_path))
    route = tmp_path / "src" / "app" / "api" / "data" / "[...path]" / "reorder" / "route.ts"
    assert route.exists()
    body = route.read_text(encoding="utf-8")
    assert "PATCH" in body and "sortOrder" in body
