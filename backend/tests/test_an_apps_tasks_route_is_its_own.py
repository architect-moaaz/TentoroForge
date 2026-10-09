"""An app whose own pages are at /tasks keeps them; the workflow inbox moves.

A task board built from the Blueprint showed the platform's "your inbox is
clear" page at /tasks instead of its own list: the guard read only the old
pipeline's `plan.json`, and the foundation's inbox copy stayed at /tasks even
when the guard fired. The moved inbox also rewrote its data route
`/api/tasks/` to `/api/inbox/`, which nothing serves.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from services import runtime_injector as ri

FOUNDATION = ri._TEMPLATE_DIR.parent / "app-foundation" / "src" / "app" / "(dashboard)" / "tasks"


def _app(tmp_path: Path, pages: list[str], entities: list[str]) -> Path:
    root = tmp_path / "proj"
    (root / ".forge" / "blueprint").mkdir(parents=True)
    (root / ".forge" / "blueprint" / "current.json").write_text(json.dumps({
        "pages": [{"route": r} for r in pages],
        "data": {"entities": [{"name": n} for n in entities]}}))
    app = root / "app"
    # What the foundation copy leaves before the injector runs.
    shutil.copytree(FOUNDATION, app / "src" / "app" / "(dashboard)" / "tasks")
    return app


def test_a_task_board_keeps_tasks_and_the_inbox_moves_to_inbox(tmp_path):
    app = _app(tmp_path, ["/tasks", "/login"], ["Task"])
    ri._inject_task_inbox_pages(app)
    dash = app / "src" / "app" / "(dashboard)"
    assert not (dash / "tasks").exists(), "the app's catch-all serves /tasks"
    detail = (dash / "inbox" / "[id]" / "page.tsx").read_text()
    assert (dash / "inbox" / "page.tsx").is_file()
    assert "/api/tasks/" in detail and "/api/inbox/" not in detail


def test_an_app_without_tasks_keeps_the_inbox_at_tasks(tmp_path):
    app = _app(tmp_path, ["/projects"], ["Project"])
    ri._inject_task_inbox_pages(app)
    dash = app / "src" / "app" / "(dashboard)"
    assert (dash / "tasks" / "page.tsx").is_file() and not (dash / "inbox").exists()


def test_a_page_of_the_apps_own_at_tasks_is_never_removed(tmp_path):
    app = _app(tmp_path, ["/tasks"], [])
    own = app / "src" / "app" / "(dashboard)" / "tasks" / "page.tsx"
    own.write_text("export default function Tasks() { return null }\n")
    ri._inject_task_inbox_pages(app)
    assert own.is_file()


def test_an_apps_api_requests_go_under_the_preview_base_path(tmp_path):
    """The SDK, hooks and pages call `fetch("/api/...")`; behind the Preview's
    prefix that reached Forge and every write answered 404. A side-effect
    module installed from providers.tsx prefixes them — once."""
    shim = (ri._TEMPLATE_DIR / "base_path_fetch.ts").read_text()
    assert "NEXT_PUBLIC_BASE_PATH" in shim and 'startsWith("/api/")' in shim
    foundation = ri._TEMPLATE_DIR.parent / "app-foundation" / "src" / "app" / "providers.tsx"
    assert 'import "@/lib/base_path_fetch";' in foundation.read_text()

    providers = tmp_path / "providers.tsx"
    providers.write_text('"use client";\nimport x from "y";\n')
    ri._ensure_providers_import(providers, "@/lib/base_path_fetch", "why")
    ri._ensure_providers_import(providers, "@/lib/base_path_fetch", "why")
    text = providers.read_text()
    assert text.count('import "@/lib/base_path_fetch";') == 1
    assert text.splitlines()[0] == '"use client";', "the pragma stays first"


def test_a_widget_range_on_a_date_column_is_passed_as_text():
    engine = (ri._TEMPLATE_DIR / "data-engine.ts").read_text()
    assert "gte(cols[timeField], asBound(cols[timeField], from))" in engine
    assert "lt(cols[timeField], asBound(cols[timeField], to))" in engine
