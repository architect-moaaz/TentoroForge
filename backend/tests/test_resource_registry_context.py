"""Tests for the closed resource-set prompt block (Slice 2 resource-binding contract)."""
from __future__ import annotations

import json
import os

from services.resource_registry_context import (
    build_resource_context,
    build_resource_context_slice,
)


# ── fixtures ─────────────────────────────────────────────────────────────────

_SCHEMA_DRIVES = """\
import { pgTable, uuid, varchar, timestamp } from "drizzle-orm/pg-core";

export const recruitmentDrives = pgTable("recruitmentDrives", {
  id: uuid("id").primaryKey().defaultRandom(),
  title: varchar("title", { length: 255 }).notNull(),
  createdAt: timestamp("created_at").defaultNow().notNull(),
});
"""

_SCHEMA_ARTICLES = """\
import { pgTable, uuid, varchar, integer, boolean } from "drizzle-orm/pg-core";
import { recruitmentDrives } from "./recruitment_drives";

export const knowledgeArticles = pgTable("knowledgeArticles", {
  id: uuid("id").primaryKey().defaultRandom(),
  driveId: uuid("drive_id")
    .notNull()
    .references(() => recruitmentDrives.id),
  title: varchar("title", { length: 255 }).notNull(),
  viewCount: integer("view_count"),
  published: boolean("published"),
});
"""

_WORKFLOW = {
    "id": "create-knowledge-article",
    "name": "CreateKnowledgeArticle",
    "definition": {
        "trigger": {"type": "manual"},
        "nodes": [
            {
                "id": "db_insert",
                "type": "action",
                "data": {
                    "config": {
                        "actionType": "db_insert",
                        "table": "knowledgeArticles",
                        "values": {
                            "title": "title",
                            "driveId": "driveId",
                            "viewCount": "viewCount",
                        },
                    }
                },
            }
        ],
    },
}


def _mkapp(tmp_path) -> str:
    out = os.path.join(str(tmp_path), "app")
    os.makedirs(os.path.join(out, "src", "db", "schema"), exist_ok=True)
    os.makedirs(os.path.join(out, "workflows"), exist_ok=True)
    with open(os.path.join(out, "src", "db", "schema", "recruitment_drives.ts"), "w") as fh:
        fh.write(_SCHEMA_DRIVES)
    with open(os.path.join(out, "src", "db", "schema", "knowledge_articles.ts"), "w") as fh:
        fh.write(_SCHEMA_ARTICLES)
    with open(os.path.join(out, "workflows", "wf.json"), "w") as fh:
        json.dump(_WORKFLOW, fh)
    return out


# ── tests ────────────────────────────────────────────────────────────────────

def test_lists_exact_registered_slugs(tmp_path):
    ctx = build_resource_context(_mkapp(tmp_path))
    assert "recruitmentDrives" in ctx
    assert "knowledgeArticles" in ctx


def test_lists_columns_with_types(tmp_path):
    ctx = build_resource_context(_mkapp(tmp_path))
    # column:type pairs surface for both entities
    assert "title:varchar" in ctx
    assert "viewCount:integer" in ctx
    assert "published:boolean" in ctx
    assert "id:uuid" in ctx


def test_annotates_fk_target(tmp_path):
    ctx = build_resource_context(_mkapp(tmp_path))
    # driveId is a uuid FK referencing recruitmentDrives
    assert "driveId:uuid→recruitmentDrives" in ctx


def test_marks_required_columns(tmp_path):
    ctx = build_resource_context(_mkapp(tmp_path))
    # title is notNull -> trailing required marker
    assert "title:varchar*" in ctx


def test_lists_workflow_id_and_input_columns(tmp_path):
    ctx = build_resource_context(_mkapp(tmp_path))
    assert "create-knowledge-article" in ctx
    assert "trigger: manual" in ctx
    # input columns come from db_insert values
    assert "driveId" in ctx and "viewCount" in ctx and "title" in ctx


def test_does_not_list_unregistered_names(tmp_path):
    ctx = build_resource_context(_mkapp(tmp_path))
    # a plausible-but-invented name must not appear
    assert "articles" not in ctx.replace("knowledgeArticles", "")
    assert "phantomEntity" not in ctx


def test_includes_bind_only_instruction(tmp_path):
    ctx = build_resource_context(_mkapp(tmp_path))
    assert "bind" in ctx.lower()
    assert "never invent" in ctx.lower()
    assert "optionsFrom" in ctx


def test_empty_when_no_resources(tmp_path):
    out = os.path.join(str(tmp_path), "empty")
    os.makedirs(out, exist_ok=True)
    assert build_resource_context(out) == ""


def test_injected_into_page_schema_prompt():
    """The builder is imported + invoked by the page-schema agent (no LLM call)."""
    import inspect

    import agents.page_schema_agent as psa

    src = inspect.getsource(psa._generate_schema_for_page)
    assert "build_resource_context" in src


def test_read_widget_binding_rules_cover_charts_maps_stats(tmp_path):
    """Binding rules must instruct every read widget (not only Table-rows) to
    bind its data prop to a declared dataSource over a real entity."""
    ctx = build_resource_context(_mkapp(tmp_path))
    lower = ctx.lower()
    # Read-widget guidance is present for the broadened surface.
    assert "chart" in lower
    assert "list" in lower
    assert "calendar" in lower or "timeline" in lower
    assert "stat" in lower
    # It must talk about DECLARING a dataSource for these widgets.
    assert "datasource" in lower
    assert "declare" in lower
    # And it must not have dropped the pre-existing entity block.
    assert "recruitmentDrives" in ctx
    assert "Entities you may bind to" in ctx


# ── canonical registry: interactions + relationships (P4) ─────────────────────

_REGISTRY = {
    "version": 1,
    "entities": {
        "Equipment": {
            "id": "equipment",
            "name": "Equipment",
            "table": "equipment",
            "slug": "equipment",
            "columns": [],
            "fks": [],
        },
        "MaintenanceLog": {
            "id": "maintenance-log",
            "name": "MaintenanceLog",
            "table": "maintenanceLogs",
            "slug": "maintenance-logs",
            "columns": [],
            "fks": [],
        },
    },
    "relationships": [
        {
            "from": "maintenance-log",
            "to": "equipment",
            "type": "many-to-one",
            "fkColumn": "equipmentId",
        }
    ],
    "interactions": [
        {
            "id": "AddEquipment",
            "sourcePage": "/equipment",
            "trigger": "primary_action",
            "label": "Add Equipment",
            "workflowId": "CreateEquipment",
            "targetEntityId": "equipment",
            "inputMap": {},
        }
    ],
    "roles": [],
}


def _mkapp_with_registry(tmp_path) -> str:
    """`_mkapp` plus a canonical contracts/resource-registry.json."""
    out = _mkapp(tmp_path)
    os.makedirs(os.path.join(out, "contracts"), exist_ok=True)
    with open(os.path.join(out, "contracts", "resource-registry.json"), "w") as fh:
        json.dump(_REGISTRY, fh)
    return out


def test_surfaces_registry_interactions(tmp_path):
    ctx = build_resource_context(_mkapp_with_registry(tmp_path))
    # An interaction line names the label, the workflow id, and the RESOLVED
    # target entity display name (equipment id → "Equipment").
    assert "Add Equipment" in ctx
    assert "CreateEquipment" in ctx
    assert "targeting Equipment" in ctx
    assert "primary_action" in ctx


def test_surfaces_registry_relationships(tmp_path):
    ctx = build_resource_context(_mkapp_with_registry(tmp_path))
    # A relationship line resolves both ids to display names.
    assert "MaintenanceLog many-to-one Equipment" in ctx
    assert "equipmentId" in ctx


def test_registry_sections_omitted_without_registry_file(tmp_path):
    """Back-compat: an app dir with NO resource-registry.json still returns the
    prior entity/closed-set context — non-empty, no crash, no new headers."""
    ctx = build_resource_context(_mkapp(tmp_path))
    assert ctx  # non-empty
    assert "recruitmentDrives" in ctx
    assert "Entities you may bind to" in ctx
    assert "Interactions" not in ctx
    assert "Relationships" not in ctx


# ── registry-slice per-page context (enterprise scale, B1) ────────────────────

_SLICE_TS = {
    "customers.ts": """\
import { pgTable, uuid, varchar } from "drizzle-orm/pg-core";
export const customers = pgTable("customers", {
  id: uuid("id").primaryKey().defaultRandom(),
  name: varchar("name", { length: 255 }).notNull(),
  email: varchar("email", { length: 255 }),
});
""",
    "equipment.ts": """\
import { pgTable, uuid, varchar } from "drizzle-orm/pg-core";
export const equipment = pgTable("equipment", {
  id: uuid("id").primaryKey().defaultRandom(),
  name: varchar("name", { length: 255 }).notNull(),
  status: varchar("status", { length: 64 }),
});
""",
    "rentals.ts": """\
import { pgTable, uuid, timestamp, text } from "drizzle-orm/pg-core";
import { customers } from "./customers";
import { equipment } from "./equipment";
export const rentals = pgTable("rentals", {
  id: uuid("id").primaryKey().defaultRandom(),
  customerId: uuid("customer_id").notNull().references(() => customers.id),
  equipmentId: uuid("equipment_id").notNull().references(() => equipment.id),
  startDate: timestamp("start_date"),
  notes: text("notes"),
});
""",
    "payments.ts": """\
import { pgTable, uuid, integer, varchar } from "drizzle-orm/pg-core";
export const payments = pgTable("payments", {
  id: uuid("id").primaryKey().defaultRandom(),
  amount: integer("amount").notNull(),
  method: varchar("method", { length: 64 }),
});
""",
}

_SLICE_WORKFLOWS = {
    "create_rental.json": {
        "id": "CreateRental",
        "name": "CreateRental",
        "definition": {
            "trigger": {"type": "manual"},
            "nodes": [{
                "id": "db_insert",
                "type": "action",
                "data": {"config": {
                    "actionType": "db_insert",
                    "table": "rentals",
                    "values": {"customerId": "customerId", "equipmentId": "equipmentId",
                               "startDate": "startDate"},
                }},
            }],
        },
    },
    "create_payment.json": {
        "id": "CreatePayment",
        "name": "CreatePayment",
        "definition": {
            "trigger": {"type": "manual"},
            "nodes": [{
                "id": "db_insert",
                "type": "action",
                "data": {"config": {
                    "actionType": "db_insert",
                    "table": "payments",
                    "values": {"amount": "amount", "method": "method"},
                }},
            }],
        },
    },
}

_SLICE_REGISTRY = {
    "version": 1,
    "entities": {
        "Customer": {
            "id": "customer", "name": "Customer", "table": "customers", "slug": "customers",
            "columns": [
                {"name": "id", "type": "uuid", "notNull": True, "fk": None, "enum": None},
                {"name": "name", "type": "varchar", "notNull": True, "fk": None, "enum": None},
                {"name": "email", "type": "varchar", "notNull": False, "fk": None, "enum": None},
            ],
            "fks": [],
        },
        "Equipment": {
            "id": "equipment", "name": "Equipment", "table": "equipment", "slug": "equipment",
            "columns": [
                {"name": "id", "type": "uuid", "notNull": True, "fk": None, "enum": None},
                {"name": "name", "type": "varchar", "notNull": True, "fk": None, "enum": None},
                {"name": "status", "type": "varchar", "notNull": False, "fk": None, "enum": None},
            ],
            "fks": [],
        },
        "Rental": {
            "id": "rental", "name": "Rental", "table": "rentals", "slug": "rentals",
            "columns": [
                {"name": "id", "type": "uuid", "notNull": True, "fk": None, "enum": None},
                {"name": "customerId", "type": "uuid", "notNull": True, "fk": "customer", "enum": None},
                {"name": "equipmentId", "type": "uuid", "notNull": True, "fk": "equipment", "enum": None},
                {"name": "startDate", "type": "timestamp", "notNull": False, "fk": None, "enum": None},
                {"name": "notes", "type": "text", "notNull": False, "fk": None, "enum": None},
            ],
            "fks": [
                {"column": "customerId", "targetEntityId": "customer"},
                {"column": "equipmentId", "targetEntityId": "equipment"},
            ],
        },
        "Payment": {
            "id": "payment", "name": "Payment", "table": "payments", "slug": "payments",
            "columns": [
                {"name": "id", "type": "uuid", "notNull": True, "fk": None, "enum": None},
                {"name": "amount", "type": "integer", "notNull": True, "fk": None, "enum": None},
                {"name": "method", "type": "varchar", "notNull": False, "fk": None, "enum": None},
            ],
            "fks": [],
        },
    },
    "relationships": [
        {"from": "rental", "to": "customer", "type": "many-to-one", "fkColumn": "customerId"},
        {"from": "rental", "to": "equipment", "type": "many-to-one", "fkColumn": "equipmentId"},
    ],
    "interactions": [
        {"id": "AddRental", "sourcePage": "/rentals", "trigger": "primary_action",
         "label": "Add Rental", "workflowId": "CreateRental", "targetEntityId": "rental",
         "inputMap": {}},
        {"id": "AddPayment", "sourcePage": "/payments", "trigger": "primary_action",
         "label": "Add Payment", "workflowId": "CreatePayment", "targetEntityId": "payment",
         "inputMap": {}},
    ],
    "roles": [],
}


def _mkapp_slice(tmp_path) -> str:
    """A 4-entity app: TS schema + workflows + canonical registry."""
    out = os.path.join(str(tmp_path), "sliceapp")
    os.makedirs(os.path.join(out, "src", "db", "schema"), exist_ok=True)
    os.makedirs(os.path.join(out, "workflows"), exist_ok=True)
    os.makedirs(os.path.join(out, "contracts"), exist_ok=True)
    for fn, src in _SLICE_TS.items():
        with open(os.path.join(out, "src", "db", "schema", fn), "w") as fh:
            fh.write(src)
    for fn, wf in _SLICE_WORKFLOWS.items():
        with open(os.path.join(out, "workflows", fn), "w") as fh:
            json.dump(wf, fh)
    with open(os.path.join(out, "contracts", "resource-registry.json"), "w") as fh:
        json.dump(_SLICE_REGISTRY, fh)
    return out


def test_slice_includes_focal_full_columns(tmp_path):
    ctx = build_resource_context_slice(_mkapp_slice(tmp_path), "Rental")
    # Rental's FULL column set, with FK targets resolved to neighbor slugs.
    assert "`rentals`" in ctx
    assert "customerId:uuid→customers" in ctx
    assert "equipmentId:uuid→equipment" in ctx
    assert "startDate:timestamp" in ctx
    assert "notes:text" in ctx


def test_slice_includes_fk_neighbors_key_cols_only(tmp_path):
    ctx = build_resource_context_slice(_mkapp_slice(tmp_path), "Rental")
    # Customer + Equipment appear as neighbors...
    assert "`customers`" in ctx
    assert "`equipment`" in ctx
    # ...with their key/label columns (id + name)...
    assert "name:varchar" in ctx
    # ...but NOT their full column list (Customer.email is dropped).
    assert "email" not in ctx


def test_slice_includes_only_targeting_workflow(tmp_path):
    ctx = build_resource_context_slice(_mkapp_slice(tmp_path), "Rental")
    assert "CreateRental" in ctx
    assert "Add Rental" in ctx
    assert "targeting Rental" in ctx


def test_slice_excludes_unrelated_entity_and_workflow(tmp_path):
    ctx = build_resource_context_slice(_mkapp_slice(tmp_path), "Rental")
    # Payment is unrelated to Rental — no columns, no workflow, no interaction.
    assert "Payment" not in ctx
    assert "payments" not in ctx
    assert "amount" not in ctx
    assert "method" not in ctx


def test_slice_is_strictly_smaller_than_whole_app(tmp_path):
    app = _mkapp_slice(tmp_path)
    whole = build_resource_context(app)
    sliced = build_resource_context_slice(app, "Rental")
    assert sliced  # non-empty
    assert len(sliced) < len(whole)


def test_slice_falls_back_when_registry_missing(tmp_path):
    # `_mkapp` has TS entities + a workflow but NO resource-registry.json.
    app = _mkapp(tmp_path)
    ctx = build_resource_context_slice(app, "knowledgeArticles")
    # Falls back to whole-app: non-empty, contains the whole-app entities.
    assert ctx
    assert "recruitmentDrives" in ctx
    assert "knowledgeArticles" in ctx


def test_slice_falls_back_when_entity_unknown(tmp_path):
    app = _mkapp_slice(tmp_path)
    ctx = build_resource_context_slice(app, "NoSuchEntity")
    # Unknown focal entity → whole-app context (includes the unrelated Payment).
    assert ctx
    assert "payments" in ctx


def test_slice_wired_into_page_schema_prompt():
    """The slice builder is imported + invoked by the page-schema agent."""
    import inspect

    import agents.page_schema_agent as psa

    src = inspect.getsource(psa._generate_schema_for_page)
    assert "build_resource_context_slice" in src
