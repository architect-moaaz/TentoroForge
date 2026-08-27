"""Slice E T2 — /tasks inbox + /tasks/[id] detail page templates.

The workflow_tasks table (Slice E T1) and the /api/tasks GET route
already ship. What's missing is the UI: an inbox page listing pending
tasks for the current user, and a per-task detail page that renders
a form derived from the task's process_variables and submits to
/api/workflows/[id]/execute with the taskId (existing execute route
handles resume when taskId is present).

This test locks in the templates exist + get shipped by the runtime
injector + hit the right server endpoints. Full end-to-end rendering
is tested inside the generated app's own suite.
"""
from __future__ import annotations

from pathlib import Path


_BACKEND = Path(__file__).parent.parent.parent


# ─────────────────────────────────────────────────────────────────────
# Template file presence + shape
# ─────────────────────────────────────────────────────────────────────

def test_inbox_page_template_exists():
    tmpl = _BACKEND / "templates" / "app-foundation" / "src" / "app" / "tasks" / "page.tsx"
    assert tmpl.is_file(), f"expected task-inbox page template at {tmpl}"


def test_detail_page_template_exists():
    tmpl = (
        _BACKEND / "templates" / "app-foundation" / "src" / "app" / "tasks"
        / "[id]" / "page.tsx"
    )
    assert tmpl.is_file(), f"expected task-detail page template at {tmpl}"


def test_single_task_api_route_template_exists():
    """GET /api/tasks/[id] — the detail page needs this to fetch one
    task's process_variables + form_binding before rendering the form."""
    tmpl = _BACKEND / "templates" / "api-tasks" / "id-route.ts"
    assert tmpl.is_file(), f"expected single-task GET route at {tmpl}"


def test_inbox_page_reads_tasks_api():
    tmpl = _BACKEND / "templates" / "app-foundation" / "src" / "app" / "tasks" / "page.tsx"
    text = tmpl.read_text(encoding="utf-8")
    # Server-side fetch of the tasks route so no client-only auth pain.
    assert "/api/tasks" in text
    # Users should be able to click into individual tasks.
    assert "/tasks/" in text


def test_detail_page_dispatches_to_workflow_execute():
    tmpl = (
        _BACKEND / "templates" / "app-foundation" / "src" / "app" / "tasks"
        / "[id]" / "page.tsx"
    )
    text = tmpl.read_text(encoding="utf-8")
    # Submit path: POST to /api/workflows/[wfId]/execute with taskId in body.
    assert "/api/workflows/" in text
    assert "/execute" in text
    assert "taskId" in text


def test_single_task_api_route_selects_by_id():
    tmpl = _BACKEND / "templates" / "api-tasks" / "id-route.ts"
    text = tmpl.read_text(encoding="utf-8")
    # Must query the workflow_tasks table by id.
    assert "workflow_tasks" in text
    assert "params" in text  # Reads [id] from route params
    # Must be an auth-gated GET; anyone else's tasks are not viewable.
    assert "GET" in text
    assert "auth" in text.lower()


# ─────────────────────────────────────────────────────────────────────
# Runtime-injector wiring
# ─────────────────────────────────────────────────────────────────────

def test_runtime_injector_ships_all_three_templates(tmp_path):
    """The three files must land at their canonical paths in a
    generated app when the injector runs."""
    from services import runtime_injector

    # Minimal app skeleton the injector expects.
    (tmp_path / "src" / "app" / "api").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "lib").mkdir(parents=True, exist_ok=True)

    runtime_injector._inject_task_inbox_pages(tmp_path)

    inbox = tmp_path / "src" / "app" / "tasks" / "page.tsx"
    detail = tmp_path / "src" / "app" / "tasks" / "[id]" / "page.tsx"
    api = tmp_path / "src" / "app" / "api" / "tasks" / "[id]" / "route.ts"

    assert inbox.is_file(), f"missing inbox page at {inbox}"
    assert detail.is_file(), f"missing detail page at {detail}"
    assert api.is_file(), f"missing single-task API route at {api}"


def test_runtime_injector_task_inbox_is_idempotent(tmp_path):
    """Running twice does not overwrite non-empty files."""
    from services import runtime_injector

    (tmp_path / "src" / "app" / "api").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "lib").mkdir(parents=True, exist_ok=True)

    runtime_injector._inject_task_inbox_pages(tmp_path)
    inbox = tmp_path / "src" / "app" / "tasks" / "page.tsx"
    first = inbox.read_text(encoding="utf-8")
    # Second call must not blow away or duplicate.
    runtime_injector._inject_task_inbox_pages(tmp_path)
    assert inbox.read_text(encoding="utf-8") == first
