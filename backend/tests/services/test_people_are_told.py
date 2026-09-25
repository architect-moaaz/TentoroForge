"""The person a workflow names is told, in the app, and only they see it.

Tool Share wrote three `send_notification` steps ("A neighbour has requested
to borrow your tool") and nobody ever saw one: the handler did not read the
`recipient` the step named, a lookup step's field did not resolve, the only
bell in any shell had no handler, and `/api/notifications` handed every row to
anyone who asked.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from services.blueprint.executors import NODE_TASKS

_BACKEND = Path(__file__).resolve().parents[2]
_TEMPLATES = _BACKEND / "templates"
_SHELL = _TEMPLATES / "app-foundation" / "src" / "app" / "(dashboard)"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_shipped_handler_notifies_the_named_person():
    test = _TEMPLATES / "runtime" / "__tests__" / "notification-reaches-the-person-it-names.test.mts"
    run = subprocess.run(["node", str(test)], capture_output=True, text=True, timeout=120)
    assert run.returncode == 0, run.stdout[-2000:] + run.stderr[-2000:]
    assert "All send_notification recipient tests passed." in run.stdout


def test_the_api_gives_a_person_only_their_own():
    route = (_TEMPLATES / "runtime" / "api-notifications" / "route.ts").read_text()
    assert 'from "@/auth"' in route
    assert "status: 401" in route, "signed out sees nothing"
    assert "eq(forgeNotifications.userId, String(user.id))" in route
    assert ".where(scope)" in route, "reads are scoped"
    assert "and(scope, eq(forgeNotifications.id" in route, "a person marks only their own read"


def test_every_shell_has_one_working_bell():
    layout = (_SHELL / "layout.tsx").read_text()
    assert 'import { NotificationBell } from "./NotificationBell";' in layout
    # Rendered ONCE, as the frame's own controls (`cluster`), which every
    # chrome places: a rail's footer, a top bar's right end, or the row above
    # the page for the chromes with neither.
    cluster = layout[layout.index("const cluster = "):layout.index("const chromeName")]
    assert "<NotificationBell />" in cluster and layout.count("<NotificationBell />") == 1
    assert layout.count("footer={cluster}") == 4 and "right={cluster}" in layout
    body = layout[layout.index("const body = ("):layout.index("const appName")]
    assert "{cluster}" in body and "!clusterInRail && !clusterInBar" in body
    bell = (_SHELL / "NotificationBell.tsx").read_text()
    assert 'fetch("/api/notifications"' in bell and 'method: "PATCH"' in bell
    assert "forge:workflow-done" in bell
    assert "Bell" not in (_SHELL / "PersonaChrome.tsx").read_text().split("export")[0].split("from \"lucide-react\"")[0]
    client = (_TEMPLATES / "app-foundation" / "src" / "sdk" / "client.tsx").read_text()
    assert 'new Event("forge:workflow-done")' in client


def test_step_authors_are_told_to_tell_the_other_person():
    task = NODE_TASKS["workflow_steps"]
    assert "TELL THE OTHER PERSON" in task
    assert "`recipient`" in task and "never `$user.id`" in task


def test_negotiated_terms_are_offers_not_one_approval():
    assert "AGREEING TERMS IS A CONVERSATION OF OFFERS" in NODE_TASKS["workflows"]
    assert "`countered`" in NODE_TASKS["workflows"]
    assert "TERMS TWO PEOPLE NEGOTIATE" in NODE_TASKS["data_model"]
