"""Tests for Spec D Wave 2 — planner-authored `column.user_fk_role` precedence
on user_fk_types.reconcile_user_fk_types. Additive: name-allowlist path
stays intact as the fallback.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.user_fk_types import reconcile_user_fk_types


def _schema(tmp: Path):
    d = tmp / "src" / "db" / "schema"
    d.mkdir(parents=True)
    (d / "user.ts").write_text(
        'import { pgTable, serial, text } from "drizzle-orm/pg-core";\n'
        'export const users = pgTable("users", { id: serial("id").primaryKey() });'
    )
    return d


def _write_registry(tmp: Path, entities: dict) -> None:
    cdir = tmp / "contracts"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "resource-registry.json").write_text(
        json.dumps({"entities": entities}), encoding="utf-8"
    )


class TestPlannerActorRewritesUnusualName:
    def test_registry_planner_actor_rewrites(self, tmp_path):
        d = _schema(tmp_path)
        (d / "asset.ts").write_text(
            'import { pgTable, uuid, text } from "drizzle-orm/pg-core";\n'
            'export const assets = pgTable("assets", {\n'
            '  id: uuid("id").primaryKey(),\n'
            '  primaryOwnerRefId: uuid("primary_owner_ref_id").notNull(),\n'
            '});'
        )
        _write_registry(tmp_path, {
            "Asset": {
                "fields": {
                    "primaryOwnerRefId": {
                        "type": "uuid",
                        "user_fk_role": "actor",
                    }
                }
            }
        })
        rep = reconcile_user_fk_types(tmp_path)
        assert rep["reconciled"] is True
        txt = (d / "asset.ts").read_text()
        assert 'primaryOwnerRefId: integer("primary_owner_ref_id")' in txt


class TestPlannerOptOut:
    def test_planner_domain_role_opts_out_of_rewrite(self, tmp_path):
        # `landlordId` matches the legacy allowlist and would normally
        # be rewritten uuid→integer. Planner says it's actually a
        # 'domain' FK — respect that and leave uuid alone.
        d = _schema(tmp_path)
        (d / "property.ts").write_text(
            'import { pgTable, uuid, text } from "drizzle-orm/pg-core";\n'
            'export const properties = pgTable("properties", {\n'
            '  id: uuid("id").primaryKey(),\n'
            '  landlordId: uuid("landlord_id").notNull(),\n'
            '});'
        )
        _write_registry(tmp_path, {
            "Property": {
                "fields": {
                    "landlordId": {
                        "type": "uuid",
                        "user_fk_role": "domain",
                    }
                }
            }
        })
        rep = reconcile_user_fk_types(tmp_path)
        assert rep["reconciled"] is False
        txt = (d / "property.ts").read_text()
        assert 'landlordId: uuid("landlord_id")' in txt


class TestLegacyPathPreserved:
    def test_no_planner_hint_rewrites_by_name(self, tmp_path):
        # No planner role anywhere → legacy allowlist runs unchanged.
        d = _schema(tmp_path)
        (d / "property.ts").write_text(
            'import { pgTable, uuid, text } from "drizzle-orm/pg-core";\n'
            'export const properties = pgTable("properties", {\n'
            '  id: uuid("id").primaryKey(),\n'
            '  landlordId: uuid("landlord_id").notNull(),\n'
            '});'
        )
        rep = reconcile_user_fk_types(tmp_path)
        assert rep["reconciled"] is True
        assert rep["columns"] == 1
        txt = (d / "property.ts").read_text()
        assert 'landlordId: integer("landlord_id")' in txt

    def test_no_planner_hint_no_op_when_users_uuid(self, tmp_path):
        d = tmp_path / "src" / "db" / "schema"
        d.mkdir(parents=True)
        (d / "user.ts").write_text(
            'import { pgTable, uuid, text } from "drizzle-orm/pg-core";\n'
            'export const users = pgTable("users", { id: uuid("id").primaryKey() });'
        )
        (d / "property.ts").write_text(
            'import { pgTable, uuid, text } from "drizzle-orm/pg-core";\n'
            'export const properties = pgTable("properties", {\n'
            '  landlordId: uuid("landlord_id").notNull(),\n'
            '});'
        )
        rep = reconcile_user_fk_types(tmp_path)
        assert rep["reconciled"] is False


class TestFlagShapeTolerance:
    def test_non_string_role_falls_through(self, tmp_path):
        # `user_fk_role: True` isn't a valid string — legacy allowlist
        # still runs (landlordId is in it → rewritten).
        d = _schema(tmp_path)
        (d / "property.ts").write_text(
            'import { pgTable, uuid, text } from "drizzle-orm/pg-core";\n'
            'export const properties = pgTable("properties", {\n'
            '  landlordId: uuid("landlord_id").notNull(),\n'
            '});'
        )
        _write_registry(tmp_path, {
            "Property": {
                "fields": {"landlordId": {"type": "uuid", "user_fk_role": True}}
            }
        })
        rep = reconcile_user_fk_types(tmp_path)
        assert rep["reconciled"] is True
