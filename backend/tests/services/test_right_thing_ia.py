"""RT sprint — right thing, right place, complete.

Covers the platform fixes distilled from the qeqorfii (Event Management
Platform) audit: join-entity IA suppression, shell-menu completeness with
literal-button rails, junk create pages, aggregate-root workspace tabs,
and the delivery-gate IA rules.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from services.entity_shape import (
    entity_slug_keys, is_join_entity, join_entities, join_route_slugs,
)
from services.shell_menu_sync import derive_shell_groups, sync_shell_menu
from services.ensure_edit_routes import remove_junk_create_pages
from services.record_subresource_tabs import inject_subresource_tabs
from services.delivery_gate import check_ia_shape


def _fk(name: str, table: str) -> dict:
    return {"name": name, "type": "uuid", "not_null": True,
            "fk": {"table": table, "column": "id"}}


SESSION_SPEAKER = {  # qeqorfii's real join shape
    "table": "session_speakers",
    "fields": [
        {"name": "id", "type": "uuid", "primaryKey": True},
        _fk("sessionId", "sessions"), _fk("speakerId", "speakers"),
        {"name": "role", "type": "varchar", "not_null": False},
        {"name": "createdAt", "type": "timestamp", "not_null": True},
        {"name": "updatedAt", "type": "timestamp", "not_null": True},
    ],
}

ENROLLMENT = {  # 2 FKs but real domain data → NOT a pure join
    "table": "enrollments",
    "fields": [
        {"name": "id", "type": "uuid", "primaryKey": True},
        _fk("studentId", "students"), _fk("courseId", "courses"),
        {"name": "grade", "type": "varchar", "not_null": True},
        {"name": "completedAt", "type": "timestamp", "not_null": True},
    ],
}

PLAN = {
    "entities": {
        "SessionSpeaker": SESSION_SPEAKER,
        "Enrollment": ENROLLMENT,
        "Event": {"table": "events", "fields": [
            {"name": "id", "type": "uuid", "primaryKey": True},
            {"name": "name", "type": "varchar", "not_null": True},
        ]},
    },
}


class TestJoinDetection:
    def test_session_speaker_is_join(self):
        assert is_join_entity(SESSION_SPEAKER) is True

    def test_enrollment_with_domain_data_is_not(self):
        assert is_join_entity(ENROLLMENT) is False

    def test_single_fk_is_not_join(self):
        e = {"fields": [{"name": "id", "primaryKey": True},
                        _fk("eventId", "events"),
                        {"name": "title", "type": "varchar", "not_null": True}]}
        assert is_join_entity(e) is False

    def test_join_entities_and_slugs(self):
        assert join_entities(PLAN) == {"SessionSpeaker"}
        slugs = join_route_slugs(PLAN)
        assert "session-speaker" in slugs
        assert "session_speakers" in slugs
        assert "events" not in slugs

    def test_entity_slug_keys_covers_names_and_tables(self):
        keys = entity_slug_keys(PLAN)
        assert any("event" in k for k in keys)


NAV_FLOW = {
    "pages": [
        {"route": "/", "title": "Dashboard", "shell": True},
        {"route": "/events", "title": "Events", "shell": True},
        {"route": "/session-speaker", "title": "Session Speaker", "shell": True},
        {"route": "/staffs", "title": "Staff", "shell": True},
        {"route": "/tasks/[id]", "title": "Tasks", "shell": True},
        {"route": "/login", "title": "Login", "shell": False},
    ],
}


class TestMenuDerivation:
    def test_join_route_excluded(self):
        groups = derive_shell_groups(NAV_FLOW, plan=PLAN)
        assert "/session-speaker" not in [g["route"] for g in groups]

    def test_extra_template_routes_included(self):
        groups = derive_shell_groups(NAV_FLOW, plan=PLAN, extra_routes=["/tasks"])
        assert "/tasks" in [g["route"] for g in groups]

    def test_authored_title_preferred_over_slug(self):
        groups = derive_shell_groups(NAV_FLOW, plan=PLAN)
        by_route = {g["route"]: g["label"] for g in groups}
        assert by_route["/staffs"] == "Staff"  # not "Staffs"


def _seed_app(root: Path, *, with_groups_anchor: bool) -> None:
    (root / "src" / "contracts").mkdir(parents=True)
    (root / "src" / "schemas").mkdir(parents=True)
    (root / "src" / "app" / "tasks").mkdir(parents=True)
    (root / "src" / "app" / "tasks" / "page.tsx").write_text("export default 1")
    (root / "src" / "contracts" / "nav-flow.json").write_text(json.dumps(NAV_FLOW))
    (root / "src" / "contracts" / "plan.json").write_text(json.dumps(PLAN))
    if with_groups_anchor:
        shell = {"root": {"type": "Stack", "props": {"groups": []}, "children": []}}
    else:
        # literal-button rail (the split frame): 3+ labeled nav buttons
        def btn(label, nav):
            return {"type": "Button", "props": {
                "label": label, "navigate": nav, "variant": "ghost",
                "onClick": {"action": "navigate", "to": nav},
                "className": "justify-start w-full"}}
        shell = {"root": {"type": "Row", "children": [
            {"type": "Stack", "children": [
                btn("Events", "/events"),
                btn("Session Speaker", "/session-speaker"),
                btn("Organizers", "/staffs"),  # mis-wired, like qeqorfii
            ]},
        ]}}
    (root / "src" / "schemas" / "shell.json").write_text(json.dumps(shell))


class TestSyncShellMenu:
    def test_groups_anchor_path(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_FIGMA_LLM", "0")   # real gate for icon_for_with_llm
        _seed_app(tmp_path, with_groups_anchor=True)
        res = sync_shell_menu(str(tmp_path))
        assert res["synced"] is True
        routes = [g["route"] for g in res["groups"]]
        assert "/session-speaker" not in routes
        assert "/tasks" in routes

    def test_literal_button_rail_rebuilt(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_FIGMA_LLM", "0")   # real gate for icon_for_with_llm
        _seed_app(tmp_path, with_groups_anchor=False)
        res = sync_shell_menu(str(tmp_path))
        assert res["synced"] is True
        shell = json.loads((tmp_path / "src" / "schemas" / "shell.json").read_text())
        navs = []
        def walk(n):
            if isinstance(n, dict):
                p = n.get("props") or {}
                if n.get("type") == "Button" and p.get("label"):
                    navs.append((p.get("navigate"), (p.get("onClick") or {}).get("to")))
                for c in n.get("children") or []:
                    walk(c)
        walk(shell["root"])
        routes = {nav for nav, _ in navs}
        assert "/session-speaker" not in routes
        assert "/tasks" in routes and "/events" in routes
        # navigate and onClick.to always agree after rebuild
        assert all(nav == oc for nav, oc in navs)


class TestJunkCreatePages:
    def test_home_new_removed_and_navflow_cleaned(self, tmp_path):
        sdir = tmp_path / "src" / "schemas" / "home"
        sdir.mkdir(parents=True)
        (sdir / "new.json").write_text(json.dumps({"route": "/home/new"}))
        cdir = tmp_path / "src" / "contracts"
        cdir.mkdir(parents=True)
        (cdir / "nav-flow.json").write_text(json.dumps({
            "pages": [{"route": "/home/new", "title": "Home New"},
                      {"route": "/events", "title": "Events"}]}))
        res = remove_junk_create_pages(str(tmp_path))
        assert res["removed"] == ["/home/new"]
        assert not (sdir / "new.json").exists()
        nav = json.loads((cdir / "nav-flow.json").read_text())
        assert [p["route"] for p in nav["pages"]] == ["/events"]

    def test_entity_create_pages_untouched(self, tmp_path):
        sdir = tmp_path / "src" / "schemas" / "events"
        sdir.mkdir(parents=True)
        (sdir / "new.json").write_text(json.dumps({"route": "/events/new"}))
        res = remove_junk_create_pages(str(tmp_path))
        assert res["removed"] == []
        assert (sdir / "new.json").exists()


class TestSubresourceTabs:
    def _seed(self, root: Path) -> Path:
        cdir = root / "src" / "contracts"
        cdir.mkdir(parents=True)
        (cdir / "nav-flow.json").write_text(json.dumps({"pages": [
            {"route": "/events/[id]"},
            {"route": "/events/[id]/sessions"},
            {"route": "/events/[id]/attendees"},
            {"route": "/events/[id]/check-in"},
            {"route": "/events/[id]/edit"},
            {"route": "/venues/[id]"},  # no children → untouched
        ]}))
        ddir = root / "src" / "schemas" / "events"
        ddir.mkdir(parents=True)
        detail = {
            "route": "/events/[id]",
            "dataSources": [{"name": "record", "entity": "Event", "op": "get",
                             "id": "{{route.id}}"}],
            "root": {"type": "Stack", "children": [
                {"type": "Heading", "props": {"content": "Event"}},
                {"type": "Card", "children": []},
            ]},
        }
        fp = ddir / "[id].json"
        fp.write_text(json.dumps(detail))
        return fp

    def test_tabs_injected_with_record_interpolation(self, tmp_path):
        fp = self._seed(tmp_path)
        res = inject_subresource_tabs(str(tmp_path))
        assert res["pages"] == ["/events/[id]"]
        schema = json.loads(fp.read_text())
        rows = [c for c in schema["root"]["children"]
                if isinstance(c, dict) and (c.get("props") or {}).get("data-subresource-tabs")]
        assert len(rows) == 1
        labels = [b["props"]["label"] for b in rows[0]["children"]]
        assert labels == ["Overview", "Sessions", "Attendees", "Check In"]
        navs = [b["props"]["navigate"] for b in rows[0]["children"][1:]]
        assert navs[0] == "/events/{{record.id}}/sessions"
        # edit excluded — it's an action, not a workspace
        assert not any(n.endswith("/edit") for n in navs)

    def test_idempotent_rerun_single_row(self, tmp_path):
        fp = self._seed(tmp_path)
        inject_subresource_tabs(str(tmp_path))
        inject_subresource_tabs(str(tmp_path))
        schema = json.loads(fp.read_text())
        rows = [c for c in schema["root"]["children"]
                if isinstance(c, dict) and (c.get("props") or {}).get("data-subresource-tabs")]
        assert len(rows) == 1


class TestGateIaRules:
    def _shell_with_buttons(self, routes: list[str]) -> dict:
        return {"root": {"type": "Stack", "children": [
            {"type": "Button", "props": {"label": r.strip("/") or "Home",
                                         "navigate": r}} for r in routes
        ]}}

    def test_join_entity_in_menu_flagged(self):
        shell = self._shell_with_buttons(["/events", "/session-speaker"])
        v = check_ia_shape(PLAN, NAV_FLOW, [], shell)
        assert any(x.rule == "join_entity_in_menu" for x in v)

    def test_menu_missing_section_flagged(self):
        shell = self._shell_with_buttons(["/events"])  # /staffs missing
        v = check_ia_shape(PLAN, NAV_FLOW, [], shell)
        subjects = {x.subject for x in v if x.rule == "menu_missing_section"}
        assert "/staffs" in subjects
        # join-table page must NOT be demanded in the menu
        assert "/session-speaker" not in subjects

    def test_junk_create_page_flagged(self):
        v = check_ia_shape(PLAN, NAV_FLOW,
                           [("/home/new", {"route": "/home/new"})], None)
        assert any(x.rule == "junk_create_page" for x in v)

    def test_clean_app_no_violations(self):
        shell = self._shell_with_buttons(["/", "/events", "/staffs"])
        v = check_ia_shape(PLAN, NAV_FLOW,
                           [("/events/new", {"route": "/events/new"})], shell)
        assert v == []
