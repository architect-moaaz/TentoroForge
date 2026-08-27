"""Platform heals — deterministic in-place repair of known regression
classes (distilled from the 2026-08-21 cwx1stzz live-debug session)."""
from __future__ import annotations

import json
from pathlib import Path

from services.platform_heals import (
    align_dashboard_filter_enums,
    apply_platform_heals,
    ensure_tailwind_safelist,
    floor_dashboard_rhythm,
    strip_destructive_skin_css,
)

PLAN = {
    "entities": {
        "Event": {"table": "events", "fields": [
            {"name": "id", "type": "uuid"},
            {"name": "status", "type": "varchar",
             "enum_values": ["draft", "published", "live", "completed", "cancelled"]},
        ]},
        "Task": {"table": "tasks", "fields": [
            {"name": "status", "type": "varchar",
             "enum_values": ["todo", "in_progress", "done"]},
            {"name": "priority", "type": "varchar",
             "enum_values": ["low", "medium", "high"]},
        ]},
    },
}


def _seed_app(root: Path, *, dashboard: dict | None = None) -> None:
    (root / "src" / "contracts").mkdir(parents=True)
    (root / "src" / "schemas").mkdir(parents=True)
    (root / "src" / "app").mkdir(parents=True)
    (root / "src" / "contracts" / "plan.json").write_text(json.dumps(PLAN))
    if dashboard is not None:
        (root / "src" / "schemas" / "dashboard.json").write_text(json.dumps(dashboard))


class TestSkinCssStrip:
    def test_strips_important_kpi_rule_keeps_rest(self, tmp_path):
        _seed_app(tmp_path)
        css = tmp_path / "src" / "app" / "globals.css"
        css.write_text(
            ".keep { color: red; }\n"
            '[data-skin="langx"] .grid:has([data-metric-tile]), '
            '[data-skin="langx"] .grid:has([data-importance]) '
            "{ grid-template-columns: repeat(2, 1fr) !important; gap: 0px !important; }\n"
            ".also-keep { gap: 1rem; }\n"
        )
        res = strip_destructive_skin_css(str(tmp_path))
        assert res["stripped"] == 1
        out = css.read_text()
        assert "!important" not in out
        assert ".keep { color: red; }" in out
        assert ".also-keep { gap: 1rem; }" in out

    def test_idempotent(self, tmp_path):
        _seed_app(tmp_path)
        (tmp_path / "src" / "app" / "globals.css").write_text(".x{}")
        assert strip_destructive_skin_css(str(tmp_path))["stripped"] == 0


class TestTailwindSafelist:
    CFG = (
        "const config = {\n"
        '  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],\n'
        "  theme: {},\n"
        "};\n"
    )

    def test_inserts_safelist_once(self, tmp_path):
        cfg = tmp_path / "tailwind.config.ts"
        cfg.write_text(self.CFG)
        assert ensure_tailwind_safelist(str(tmp_path))["added"] is True
        assert "safelist" in cfg.read_text()
        # second run: already present → no-op
        assert ensure_tailwind_safelist(str(tmp_path))["added"] is False


class TestRhythmFloor:
    def test_spacing3_floored_to_4(self, tmp_path):
        _seed_app(tmp_path, dashboard={
            "route": "/dashboard",
            "root": {"type": "Stack", "props": {"gap": "tokens.spacing.3"},
                     "children": []},
        })
        res = floor_dashboard_rhythm(str(tmp_path))
        assert res["floored"] == ["src/schemas/dashboard.json"]
        data = json.loads((tmp_path / "src" / "schemas" / "dashboard.json").read_text())
        assert data["root"]["props"]["gap"] == "tokens.spacing.4"

    def test_other_gaps_untouched(self, tmp_path):
        _seed_app(tmp_path, dashboard={
            "root": {"type": "Stack", "props": {"gap": "tokens.spacing.6"},
                     "children": []},
        })
        assert floor_dashboard_rhythm(str(tmp_path))["floored"] == []


class TestFilterEnums:
    def _dashboard(self) -> dict:
        return {
            "route": "/dashboard",
            "root": {"type": "Stack", "children": [
                {"type": "Cluster", "children": [
                    {"type": "Select", "props": {
                        "name": "status", "label": "Event Status",
                        "data-dashboard-filter": "status",
                        # invented values — Event has no active/upcoming
                        "options": [
                            {"value": "", "label": "All event status"},
                            {"value": "active", "label": "active"},
                            {"value": "upcoming", "label": "upcoming"},
                        ]}},
                    {"type": "Select", "props": {
                        "name": "priority", "label": "Task Priority",
                        "data-dashboard-filter": "priority",
                        # `critical` doesn't exist in the plan
                        "options": [
                            {"value": "", "label": "All priorities"},
                            {"value": "critical", "label": "critical"},
                        ]}},
                ]},
            ]},
        }

    def test_options_rewritten_from_plan(self, tmp_path):
        _seed_app(tmp_path, dashboard=self._dashboard())
        res = align_dashboard_filter_enums(str(tmp_path))
        assert res["aligned"] == ["src/schemas/dashboard.json"]
        data = json.loads((tmp_path / "src" / "schemas" / "dashboard.json").read_text())
        status, priority = data["root"]["children"][0]["children"]
        s_opts = status["props"]["options"]
        # label-matched to Event (not Task) even though both have `status`
        assert [o["value"] for o in s_opts] == \
            ["", "draft", "published", "live", "completed", "cancelled"]
        assert s_opts[0]["label"] == "All event status"   # keeps authored All-label
        assert s_opts[3]["label"] == "Live"                # Title Case
        p_opts = priority["props"]["options"]
        assert [o["value"] for o in p_opts] == ["", "low", "medium", "high"]

    def test_ambiguous_column_left_alone(self, tmp_path):
        dash = self._dashboard()
        # no entity name in the label + two entities disagree on `status`
        dash["root"]["children"][0]["children"][0]["props"]["label"] = "Status"
        _seed_app(tmp_path, dashboard=dash)
        align_dashboard_filter_enums(str(tmp_path))
        data = json.loads((tmp_path / "src" / "schemas" / "dashboard.json").read_text())
        status = data["root"]["children"][0]["children"][0]
        assert {"value": "active", "label": "active"} in status["props"]["options"]

    def test_idempotent(self, tmp_path):
        _seed_app(tmp_path, dashboard=self._dashboard())
        align_dashboard_filter_enums(str(tmp_path))
        assert align_dashboard_filter_enums(str(tmp_path))["aligned"] == []


class TestOrchestrator:
    def test_runs_all_heals_and_reports(self, tmp_path):
        _seed_app(tmp_path, dashboard={
            "root": {"type": "Stack", "props": {"gap": "tokens.spacing.3"},
                     "children": []},
        })
        (tmp_path / "src" / "app" / "globals.css").write_text(".x{}")
        (tmp_path / "tailwind.config.ts").write_text(TestTailwindSafelist.CFG)
        report = apply_platform_heals(str(tmp_path))
        assert report["tailwind_safelist"]["added"] is True
        assert report["dashboard_rhythm"]["floored"]
        assert report["changed"] is True
        # every heal ran without raising
        for key in ("template_runtime", "skin_css", "engine_token_prefix",
                    "filter_enums", "tokens"):
            assert "error" not in report[key]

    def test_clean_app_reports_unchanged_heals(self, tmp_path):
        _seed_app(tmp_path)
        report = apply_platform_heals(str(tmp_path))
        assert report["skin_css"]["stripped"] == 0
        assert report["filter_enums"]["aligned"] == []


class TestWorkflowInboxRelocation:
    INBOX = (
        "/**\n * Task Inbox (Slice E T2) — queue of pending human tasks.\n */\n"
        'export default function TasksPage() { return <a href="/tasks/1">t</a>; }\n'
    )

    def _seed(self, tmp_path, *, with_task_entity=True):
        plan = dict(PLAN) if with_task_entity else {
            "entities": {"Event": PLAN["entities"]["Event"]}}
        _seed_app(tmp_path)
        (tmp_path / "src" / "contracts" / "plan.json").write_text(json.dumps(plan))
        (tmp_path / "src" / "contracts" / "nav-flow.json").write_text(json.dumps({
            "pages": [{"route": "/task", "title": "Tasks"}],
            "personas": [{"id": "p1", "jobs": [{"label": "Tasks", "route": "/tasks"}]}],
        }))
        tasks_dir = tmp_path / "src" / "app" / "tasks"
        tasks_dir.mkdir(parents=True)
        (tasks_dir / "page.tsx").write_text(self.INBOX)

    def test_relocates_and_repoints(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_FIGMA_LLM", "0")   # real gate for icon_for_with_llm
        from services.platform_heals import relocate_workflow_inbox
        self._seed(tmp_path)
        res = relocate_workflow_inbox(str(tmp_path))
        assert res["relocated"] is True
        assert not (tmp_path / "src" / "app" / "tasks").exists()
        moved = (tmp_path / "src" / "app" / "inbox" / "page.tsx").read_text()
        assert '"/inbox/1"' in moved            # internal links rewritten
        nav = json.loads((tmp_path / "src" / "contracts" / "nav-flow.json").read_text())
        assert nav["personas"][0]["jobs"][0]["route"] == "/task"
        assert res["nav_repointed"] is True

    def test_no_task_entity_leaves_inbox_at_tasks(self, tmp_path):
        from services.platform_heals import relocate_workflow_inbox
        self._seed(tmp_path, with_task_entity=False)
        assert relocate_workflow_inbox(str(tmp_path))["relocated"] is False
        assert (tmp_path / "src" / "app" / "tasks" / "page.tsx").exists()

    def test_entity_list_page_never_touched(self, tmp_path):
        # an app whose /tasks page is NOT the inbox template (hand-authored)
        from services.platform_heals import relocate_workflow_inbox
        self._seed(tmp_path)
        (tmp_path / "src" / "app" / "tasks" / "page.tsx").write_text(
            "export default function Custom() { return null; }")
        assert relocate_workflow_inbox(str(tmp_path))["relocated"] is False


class TestDetailShapedCollections:
    def _seed(self, tmp_path, schema: dict):
        _seed_app(tmp_path)
        (tmp_path / "src" / "schemas" / "task.json").write_text(json.dumps(schema))

    def test_detail_at_collection_route_becomes_kanban(self, tmp_path):
        from services.platform_heals import rebuild_detail_shaped_collections
        # the cwx1stzz shape: /task carried a single-record get + update form
        self._seed(tmp_path, {
            "route": "/task",
            "dataSources": [{"name": "task", "entity": "Task", "op": "get"}],
            "root": {"type": "Stack", "children": []},
        })
        res = rebuild_detail_shaped_collections(str(tmp_path))
        assert res["rebuilt"] == ["/task"]
        schema = json.loads((tmp_path / "src" / "schemas" / "task.json").read_text())
        ops = [ds.get("op") for ds in schema.get("dataSources") or []]
        assert "list" in ops
        # Task.status enum (todo/in_progress/done) → kanban shape
        dumped = json.dumps(schema)
        assert "Kanban" in dumped

    def test_real_list_page_untouched(self, tmp_path):
        from services.platform_heals import rebuild_detail_shaped_collections
        original = {
            "route": "/task",
            "dataSources": [{"name": "tasks", "entity": "Task", "op": "list"}],
            "root": {"type": "Stack", "children": [{"type": "Table", "props": {}}]},
        }
        self._seed(tmp_path, original)
        assert rebuild_detail_shaped_collections(str(tmp_path))["rebuilt"] == []
        assert json.loads(
            (tmp_path / "src" / "schemas" / "task.json").read_text()) == original

    def test_idempotent_after_rebuild(self, tmp_path):
        from services.platform_heals import rebuild_detail_shaped_collections
        self._seed(tmp_path, {
            "route": "/task",
            "dataSources": [{"name": "task", "entity": "Task", "op": "get"}],
            "root": {"type": "Stack", "children": []},
        })
        rebuild_detail_shaped_collections(str(tmp_path))
        assert rebuild_detail_shaped_collections(str(tmp_path))["rebuilt"] == []
