"""An overdue task goes to the role its step named, and that role is told.
`processTaskEscalations` was written against a `db.execute(text, params)`
drizzle does not have and called by nothing (2026-10-12)."""
from __future__ import annotations

import re
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[2] / "templates" / "runtime"


def test_the_tick_hands_overdue_tasks_on_with_its_own_clock():
    route = (RUNTIME / "api-cron" / "route.ts").read_text()
    assert "processTaskEscalations(db," in route and "}, now);" in route
    assert "forgeNotifications" in route, "the role is told in the app"
    assert 'params.get("at")' in route and 'params.get("force") === "1"' in route


def test_escalation_is_real_sql_with_a_clock():
    src = (RUNTIME / "workflows" / "escalation.ts").read_text()
    body = src.split("export async function processTaskEscalations(", 1)[1]
    assert "now: Date = new Date()" in body.split("{", 1)[0]
    assert "$1" not in body and "$2" not in body, "positional placeholders drizzle never bound"
    assert re.search(r"due_at < \$\{now\.toISOString\(\)\}::timestamptz", body)
    assert "assignee_role = ${target}" in body


def test_the_escalation_role_reaches_the_app_by_name():
    from services.blueprint.projection import _ROLE_KEYS
    assert "escalateTo" in _ROLE_KEYS
