"""Mozato (forge-v3, 2026-10-06): a notification showed its text and opened
nothing — nothing knew where a record lives. A record's address is its screen's
panel (`?param=<id>`) or its record page; a notify step that names the record
gets a link to it when the app's workflow definitions are written, and the
breadcrumb reads the screen's tabs and panels from the navigation contract."""
import json
from pathlib import Path

from services.blueprint.projection import project_nav_flow, project_workflows
from services.blueprint.record_links import notification_link, record_address

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"

DOC = {
    "application": {"id": "m", "name": "Mozato"},
    "data": {"entities": [{"id": "ENTITY-001", "name": "Order", "table": "orders", "fields": [{"name": "id", "type": "uuid"}]},
                          {"id": "ENTITY-002", "name": "Ticket", "table": "tickets", "fields": [{"name": "id", "type": "uuid"}]},
                          {"id": "ENTITY-003", "name": "Note", "table": "notes", "fields": [{"name": "id", "type": "uuid"}]}]},
    "pages": [
        {"id": "PAGE-001", "name": "My orders", "route": "/orders", "pattern": "master_detail", "access": "authenticated",
         "data": {"primaryEntity": "ENTITY-001"},
         "sections": [{"key": "orders", "label": "Orders", "entity": "ENTITY-001", "shows": "list", "placement": "main"},
                      {"key": "order", "label": "Order", "entity": "ENTITY-001", "shows": "record",
                       "placement": "panel", "opensFrom": "orders", "param": "order"},
                      {"key": "history", "label": "Past orders", "entity": "ENTITY-001", "placement": "tab"}]},
        {"id": "PAGE-002", "name": "Ticket", "route": "/tickets/[id]", "pattern": "record_workspace",
         "access": "authenticated", "data": {"primaryEntity": "ENTITY-002"}},
    ],
    "workflows": [{"id": "FLOW-001", "name": "Dispatch Order", "trigger": {"kind": "manual"}, "launchedFrom": ["PAGE-001"],
                   "steps": [{"key": "tell", "name": "Tell the customer", "type": "action", "entity": "ENTITY-001",
                              "config": {"actionType": "send_notification", "title": "Out for delivery",
                                         "recipient": "{{order.customerId}}", "entityId": "{{order.id}}"},
                              "next": []}]}],
}


def test_a_record_lives_in_its_screens_panel_or_on_its_page():
    assert record_address(DOC, "ENTITY-001") == "/orders?order={id}"
    assert record_address(DOC, "ENTITY-002") == "/tickets/{id}"
    assert record_address(DOC, "ENTITY-003") is None, "nothing opens a note: no link rather than a wrong one"


def test_a_notify_step_naming_its_record_gets_a_link():
    step = DOC["workflows"][0]["steps"][0]
    assert notification_link(DOC, step, step["config"]) == "/orders?order={{order.id}}"
    assert notification_link(DOC, step, {**step["config"], "link": "/x"}) is None, "an authored link stands"
    assert notification_link(DOC, step, {k: v for k, v in step["config"].items() if k != "entityId"}) is None


def test_the_definition_the_app_runs_carries_the_link(tmp_path):
    project_workflows(DOC, tmp_path)
    definition = json.loads(next((tmp_path / "src/lib/workflows/definitions").glob("*.json")).read_text())
    nodes = definition.get("definition", definition).get("nodes")
    tell = next(n for n in nodes if n["id"] == "tell")
    assert tell["data"]["config"]["link"] == "/orders?order={{order.id}}"


def test_the_breadcrumb_knows_each_screens_tabs_and_panels(tmp_path):
    project_nav_flow(DOC, tmp_path)
    flow = json.loads((tmp_path / "src/contracts/nav-flow.json").read_text())
    assert flow["screens"]["/orders"] == {"title": "My orders", "tabs": {"history": "Past orders"},
                                          "panels": {"order": "Order"}}


def test_the_frame_reads_them_without_breaking_an_owned_breadcrumb():
    layout = (TEMPLATES / "app-foundation/src/app/(dashboard)/layout.tsx").read_text()
    assert "type ScreenNode = " in layout and "type ScreenNode } from" not in layout
    assert "{...({ screens } as Record<string, unknown>)}" in layout
    crumb = (TEMPLATES / "app-foundation/src/app/(dashboard)/RouteBreadcrumb.tsx").read_text()
    assert "useSearchParams" in crumb and "<React.Suspense" in crumb
    bell = (TEMPLATES / "app-foundation/src/app/(dashboard)/NotificationBell.tsx").read_text()
    assert "window.location.assign(n.link)" in bell
    table = (TEMPLATES / "runtime/db/forge-notifications.schema.ts").read_text()
    assert 'link: text("link")' in table
