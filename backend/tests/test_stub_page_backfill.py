"""Tests for services.stub_page_backfill — deterministic backfill of empty page schemas."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.stub_page_backfill import backfill_stub_pages, is_stub_page


# Two real registered slugs: applicants (Applicant) + interviews (Interview).
_SCHEMA_APPLICANTS = '''\
import { pgTable, uuid, varchar, timestamp } from "drizzle-orm/pg-core";
export const applicants = pgTable("applicants", {
  id: uuid("id").primaryKey().defaultRandom(),
  fullName: varchar("full_name"),
  email: varchar("email"),
  createdAt: timestamp("created_at"),
});
'''

_SCHEMA_INTERVIEWS = '''\
import { pgTable, uuid, integer, timestamp } from "drizzle-orm/pg-core";
export const interviews = pgTable("interviews", {
  id: uuid("id").primaryKey().defaultRandom(),
  applicantId: uuid("applicant_id"),
  round: integer("round"),
  scheduledAt: timestamp("scheduled_at"),
});
'''

_REGISTRY = {
    "entities": {
        "Applicant": {"fields": {
            "id": {"type": "uuid", "primaryKey": True},
            "fullName": {"type": "varchar"},
            "email": {"type": "varchar"},
            "createdAt": {"type": "timestamp"},
        }},
        "Interview": {"fields": {
            "id": {"type": "uuid", "primaryKey": True},
            "applicantId": {"type": "uuid"},
            "round": {"type": "integer"},
            "scheduledAt": {"type": "timestamp"},
        }},
        # a system entity that must NOT become a dashboard tile
        "Users": {"fields": {"id": {"type": "uuid"}, "email": {"type": "text"}}},
    }
}


def _make_app(tmp_path: Path) -> Path:
    out = tmp_path / "app"
    (out / "src" / "db" / "schema").mkdir(parents=True)
    (out / "src" / "schemas").mkdir(parents=True)
    (out / "src" / "db" / "schema" / "applicants.ts").write_text(_SCHEMA_APPLICANTS)
    (out / "src" / "db" / "schema" / "interviews.ts").write_text(_SCHEMA_INTERVIEWS)
    (out / "registry.json").write_text(json.dumps(_REGISTRY))
    return out


def _stub(slug: str, route: str, heading: str) -> dict:
    return {
        "schemaVersion": "2", "id": slug, "route": route, "layout": "main",
        "root": {"type": "Stack", "id": "root", "children": [
            {"type": "Heading", "id": "title", "props": {"level": 1, "content": heading}},
        ]},
    }


def _write(out: Path, slug: str, page: dict) -> Path:
    p = out / "src" / "schemas" / f"{slug}.json"
    p.write_text(json.dumps(page))
    return p


def _node_types(page: dict) -> set[str]:
    from services.stub_page_backfill import _iter_nodes, _canon
    return {_canon(n.get("type")) for n in _iter_nodes(page.get("root"))}


def _ds_sources(page: dict) -> list[str]:
    out = []
    for ds in page.get("dataSources") or []:
        for k in ("source", "table", "from", "entity", "name"):
            if isinstance(ds.get(k), str) and ds[k]:
                out.append(ds[k])
                break
    return out


def test_stub_home_gets_metric_tiles_and_recent_list(tmp_path):
    out = _make_app(tmp_path)
    home = _write(out, "home", _stub("home", "/", "Dashboard"))

    res = backfill_stub_pages(str(out))

    assert any(b["id"] == "home" and b["kind"] == "dashboard" for b in res["backfilled"])
    page = json.loads(home.read_text())
    assert not is_stub_page(page)
    types = _node_types(page)
    assert "metrictile" in types
    assert "table" in types  # recent-<entity> list
    # aggregate dataSources for the two domain entities (Users excluded)
    agg = [ds for ds in page["dataSources"] if ds.get("op") == "aggregate"]
    assert {ds["entity"] for ds in agg} == {"Applicant", "Interview"}
    assert all(ds["metrics"]["count"]["fn"] == "count" for ds in agg)
    # Users (system entity) must NOT be featured
    assert "Users" not in {ds.get("entity") for ds in page["dataSources"]}


def test_stub_list_route_gets_real_table(tmp_path):
    out = _make_app(tmp_path)
    lst = _write(out, "interviews", _stub("interviews", "/interviews", "Dashboard"))

    res = backfill_stub_pages(str(out))

    assert any(b["id"] == "interviews" and b["kind"] == "list" for b in res["backfilled"])
    page = json.loads(lst.read_text())
    assert not is_stub_page(page)
    assert "table" in _node_types(page)
    list_ds = [ds for ds in page["dataSources"] if ds.get("op") == "list"]
    assert list_ds and list_ds[0]["entity"] == "Interview"
    # rows binding resolves to the declared dataSource name
    ds_names = {ds["name"] for ds in page["dataSources"]}
    for n in page["dataSources"]:
        if n.get("op") == "list":
            assert n["name"] in ("interviews",)
    assert "interviews" in ds_names


def test_full_page_left_untouched(tmp_path):
    out = _make_app(tmp_path)
    full = {
        "schemaVersion": "2", "id": "applicants", "route": "/applicants", "layout": "main",
        "dataSources": [{"name": "applicants", "entity": "Applicant", "op": "list"}],
        "root": {"type": "Stack", "children": [
            {"type": "Heading", "props": {"level": 1, "content": "Applicants"}},
            {"type": "Table", "props": {"columns": [{"key": "email", "label": "Email"}],
                                        "rows": "{{applicants}}"}},
        ]},
    }
    p = _write(out, "applicants", full)
    before = p.read_text()

    res = backfill_stub_pages(str(out))

    assert all(b["id"] != "applicants" for b in res["backfilled"])
    assert p.read_text() == before  # byte-identical, untouched


def test_emitted_datasources_pass_binding_validator(tmp_path):
    out = _make_app(tmp_path)
    _write(out, "home", _stub("home", "/", "Dashboard"))
    _write(out, "interviews", _stub("interviews", "/interviews", "Dashboard"))

    backfill_stub_pages(str(out))

    from services.binding_validator import validate_bindings
    report = validate_bindings(str(out))
    unresolved = [e for e in report["errors"]
                  if e["kind"] in ("datasource_unresolved", "binding_unresolved")]
    assert unresolved == [], f"backfilled pages have unresolved bindings: {unresolved}"


def test_idempotent_second_run_no_change(tmp_path):
    out = _make_app(tmp_path)
    home = _write(out, "home", _stub("home", "/", "Dashboard"))

    backfill_stub_pages(str(out))
    after_first = home.read_text()
    res2 = backfill_stub_pages(str(out))

    assert all(b["id"] != "home" for b in res2["backfilled"])
    assert home.read_text() == after_first


def test_never_raises_on_missing_registry(tmp_path):
    out = tmp_path / "bare"
    (out / "src" / "schemas").mkdir(parents=True)
    _write(out, "home", _stub("home", "/", "Dashboard"))
    # no registry.json, no db schema — must not raise, just skip
    res = backfill_stub_pages(str(out))
    assert res["backfilled"] == []


def test_is_stub_detection():
    assert is_stub_page(_stub("home", "/", "Dashboard"))
    assert not is_stub_page({"root": {"type": "Stack", "children": [
        {"type": "Table", "props": {"rows": "{{x}}"}}]}})
    assert not is_stub_page({"dataSources": [{"name": "x"}],
                             "root": {"type": "Stack", "children": []}})
