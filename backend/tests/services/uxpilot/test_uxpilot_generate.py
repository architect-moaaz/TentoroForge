"""UX Pilot as the page designer: Forge writes the prompt, UX Pilot draws the
page, Forge binds it by the labels it chose (design note 2026-09-13)."""
from __future__ import annotations

import json

import pytest

from services.blueprint.service import BlueprintService
from services.uxpilot import generate as g
from services.uxpilot.gateway import ALLOWED_TOOLS, GENERATION_TOOLS, UxPilotGateway, UxPilotGatewayError
from services.uxpilot.credentials import EnvKeyResolver, UxPilotCredential


HTML = """<html><body><main style="display:flex;flex-direction:column;gap:16px">
<h1>Tasks</h1>
<div style="display:flex;gap:16px">
  <div style="display:flex;flex-direction:column"><p>Open tasks</p><h2>42</h2></div>
  <div style="display:flex;flex-direction:column"><p>Total tasks</p><h2>128</h2></div>
</div>
<div style="display:flex;gap:8px"><button>Create task</button><button>Archive done tasks</button></div>
<table><thead><tr><th>Title</th><th>Status</th><th>Due Date</th></tr></thead>
<tbody><tr><td>Write brief</td><td>open</td><td>2026-09-14</td></tr></tbody></table>
</main></body></html>"""


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="a", name="Taskboard", domain="Operations")
    s.doc["application"]["uiDesigner"] = "uxpilot"
    s.doc["data"] = {"entities": [{
        "id": "ENTITY-001", "name": "Task", "table": "tasks", "status": "VERIFIED",
        "fields": [{"name": "id", "type": "uuid", "primaryKey": True},
                   {"name": "title", "type": "string"},
                   {"name": "status", "type": "string", "enumValues": ["open", "done"]},
                   {"name": "dueDate", "type": "date"}]}]}
    s.doc["pages"] = [
        {"id": "PAGE-001", "name": "Tasks", "route": "/tasks", "purpose": "See every task",
         "pattern": "entity_list", "data": {"primaryEntity": "ENTITY-001"},
         "actions": ["Create task"], "status": "VERIFIED"},
        {"id": "PAGE-002", "name": "Task", "route": "/tasks/[id]", "purpose": "One task",
         "pattern": "record_workspace", "data": {"primaryEntity": "ENTITY-001"}, "status": "VERIFIED"},
        {"id": "PAGE-003", "name": "New task", "route": "/tasks/new", "purpose": "Add a task",
         "pattern": "form", "data": {"primaryEntity": "ENTITY-001"}, "status": "VERIFIED"},
    ]
    s.doc["widgets"] = [
        {"id": "WIDGET-001", "page": "PAGE-001", "kind": "metric", "label": "Open tasks",
         "dataSource": {"op": "aggregate", "entity": "ENTITY-001", "aggregation": "count",
                        "filter": {"status": "open"}}, "status": "VERIFIED"},
        {"id": "WIDGET-002", "page": "PAGE-001", "kind": "metric", "label": "Total tasks",
         "dataSource": {"op": "aggregate", "entity": "ENTITY-001", "aggregation": "count"},
         "status": "VERIFIED"},
    ]
    s.doc["workflows"] = [{"id": "FLOW-001", "name": "Archive done tasks",
                           "launchedFrom": ["PAGE-001"], "status": "VERIFIED",
                           "trigger": {"kind": "manual"}, "inputs": []}]
    s.validate()
    return s


class FakeGateway:
    """Answers `generate_design` with one fixed screen and counts the calls."""

    may_generate = True

    def __init__(self, html=HTML, fail=None):
        self.html, self.fail, self.calls = html, fail, []

    async def call(self, tool, **kw):
        self.calls.append((tool, kw))
        if self.fail:
            raise self.fail
        return [{"type": "text", "text": json.dumps(
            {"design": {"id": "dsg_1", "html": self.html, "previewUrl": "https://ux/p.png"}})}]


def _types(node, out=None):
    out = [] if out is None else out
    out.append(node.get("type"))
    for c in node.get("children") or []:
        _types(c, out)
    return out


def _find(node, **props):
    if all((node.get("props") or {}).get(k) == v for k, v in props.items()):
        return node
    for c in node.get("children") or []:
        hit = _find(c, **props)
        if hit:
            return hit
    return None


# --- the dispatch rule -------------------------------------------------------

def test_the_page_overrides_the_application_and_forge_is_the_default():
    assert g.designer_for({}, {}) == "forge"
    assert g.designer_for({"application": {"uiDesigner": "uxpilot"}}, {}) == "uxpilot"
    assert g.designer_for({"application": {"uiDesigner": "uxpilot"}}, {"designedBy": "forge"}) == "forge"
    assert g.designer_for({"application": {}}, {"designedBy": "uxpilot"}) == "uxpilot"
    assert g.designer_for({"application": {"uiDesigner": "vibes"}}, {}) == "forge"


# --- the gateway's consent ---------------------------------------------------

def test_generation_is_refused_unless_the_gateway_was_opened_for_it():
    gw = UxPilotGateway(credential=UxPilotCredential(ref="UXPILOT_API_KEY"), resolver=EnvKeyResolver())
    assert "generate_design" not in gw.allowed_tools()
    assert GENERATION_TOOLS.isdisjoint(ALLOWED_TOOLS)
    import asyncio
    with pytest.raises(UxPilotGatewayError, match="spends UX Pilot credits"):
        asyncio.run(gw.call("generate_design", prompt="x"))
    consenting = UxPilotGateway(credential=UxPilotCredential(ref="UXPILOT_API_KEY"),
                                resolver=EnvKeyResolver(), may_generate=True)
    assert consenting.allowed_tools() == ALLOWED_TOOLS | {"generate_design"}
    # Only one screen from one prompt; the other credit-spending tools stay out.
    assert "import_html_design" not in consenting.allowed_tools()
    assert "publish_design_preview" not in consenting.allowed_tools()


# --- the prompt --------------------------------------------------------------

def test_the_prompt_dictates_every_label_the_binder_will_look_for(svc):
    prompt = g.prompt_for(svc.doc, svc.doc["pages"][0])
    for label in ('"Open tasks"', '"Total tasks"', '"Title"', '"Status"', '"Due Date"',
                  '"Create task"', '"Archive done tasks"', 'heading "Tasks"'):
        assert label in prompt
    assert "PAGE BODY ONLY" in prompt and "sidebar" in prompt
    # Deterministic: the ledger's hash means "the brief has not changed".
    assert g.prompt_for(svc.doc, svc.doc["pages"][0]) == prompt
    assert g.brief_hash(prompt) == g.brief_hash(prompt)


def test_feedback_from_a_refused_attempt_goes_into_the_next_prompt(svc):
    prompt = g.prompt_for(svc.doc, svc.doc["pages"][0], feedback="the table had no rows")
    assert "previous attempt was refused" in prompt and "the table had no rows" in prompt


# --- generate → tree → bound tree -----------------------------------------

def test_a_generated_page_is_bound_by_the_labels_forge_chose(svc, tmp_path):
    gw = FakeGateway()
    out = g.compose(svc, svc.doc["pages"][0], app_root=tmp_path / "app", gateway=gw)
    assert out.root is not None, out.reason
    assert out.design_id == "dsg_1" and out.preview_url == "https://ux/p.png"
    assert [c[0] for c in gw.calls] == ["generate_design"]
    assert "Open tasks" in gw.calls[0][1]["prompt"]

    # Metric tiles keep their drawing and take a live number.
    assert _find(out.root, content="{{openTasks.value}}") is not None
    assert _find(out.root, content="{{totalTasks.value}}") is not None
    by_name = {s["name"]: s for s in out.data_sources}
    assert by_name["openTasks"]["op"] == "aggregate" and by_name["openTasks"]["entity"] == "Task"
    assert by_name["openTasks"]["filter"] == {"status": "open"}
    assert "filter" not in by_name["totalTasks"]

    # The table is live, rows and all: the generated example row is gone.
    table = next(n for n in _walk(out.root) if n.get("type") == "Table")
    assert [c["key"] for c in table["props"]["columns"]] == ["title", "status", "dueDate"]
    assert table["props"]["data"] == "{{tasks}}" and table["props"]["rowHref"] == "/tasks/{{id}}"
    assert by_name["tasks"]["op"] == "list"
    assert _find(out.root, content="Write brief") is None

    # Buttons launch what this page may launch, or open what it names.
    create = _find(out.root, label="Create task")
    assert create and create["type"] == "Button" and create["props"]["navigate"] == "/tasks/new"
    archive = _find(out.root, label="Archive done tasks")
    assert archive and archive["props"]["workflow"] == "FLOW-001"
    assert out.warnings == []

    # Forge's provenance stamp never reaches the Blueprint.
    assert all("_figmaNodeId" not in (n.get("props") or {}) for n in _walk(out.root))


def _walk(node):
    yield node
    for c in node.get("children") or []:
        yield from _walk(c)


def test_what_the_page_did_not_draw_is_a_warning_not_a_guess(svc, tmp_path):
    thin = "<html><body><main><h1>Tasks</h1><p>Nothing here yet</p></main></body></html>"
    out = g.compose(svc, svc.doc["pages"][0], app_root=tmp_path / "app", gateway=FakeGateway(html=thin))
    assert out.root is not None
    assert out.data_sources == []
    joined = " ".join(out.warnings)
    for missing in ("Open tasks", "Total tasks", "Tasks table", "create task", "archive done tasks"):
        assert missing.lower() in joined.lower(), missing


def test_the_ledger_means_a_rebuild_spends_nothing(svc, tmp_path):
    gw = FakeGateway()
    first = g.compose(svc, svc.doc["pages"][0], app_root=tmp_path / "app", gateway=gw)
    second = g.compose(svc, svc.doc["pages"][0], app_root=tmp_path / "app", gateway=gw)
    assert first.reused is False and second.reused is True
    assert len(gw.calls) == 1
    entry = g.ledger_entry(tmp_path, "PAGE-001")
    assert entry["designId"] == "dsg_1" and entry["briefHash"] == g.brief_hash(first_prompt(svc))

    # A changed brief is a new design.
    svc.doc["widgets"].append({"id": "WIDGET-003", "page": "PAGE-001", "kind": "metric",
                               "label": "Done tasks", "status": "VERIFIED",
                               "dataSource": {"op": "aggregate", "entity": "ENTITY-001",
                                              "aggregation": "count", "filter": {"status": "done"}}})
    third = g.compose(svc, svc.doc["pages"][0], app_root=tmp_path / "app", gateway=gw)
    assert third.reused is False and len(gw.calls) == 2
    # Feedback always regenerates: the refused design is not the one to reuse.
    g.compose(svc, svc.doc["pages"][0], app_root=tmp_path / "app", gateway=gw, feedback="fix it")
    assert len(gw.calls) == 3


def first_prompt(svc):
    return g.prompt_for(svc.doc, svc.doc["pages"][0])


def test_generated_designs_are_not_design_sources(svc, tmp_path):
    g.compose(svc, svc.doc["pages"][0], app_root=tmp_path / "app", gateway=FakeGateway())
    assert svc.doc.get("designSources", []) == []
    assert g.ledger_path(tmp_path).is_file()


def test_a_failure_is_a_reason_the_executor_can_record(svc, tmp_path):
    failing = FakeGateway(fail=UxPilotGatewayError("auth", "no key in UXPILOT_API_KEY"))
    out = g.compose(svc, svc.doc["pages"][0], app_root=tmp_path / "app", gateway=failing)
    assert out.root is None and "UX Pilot auth" in out.reason
    empty = FakeGateway(html="")
    out = g.compose(svc, svc.doc["pages"][0], app_root=tmp_path / "app", gateway=empty)
    assert out.root is None and "no HTML" in out.reason


def test_a_design_acknowledged_without_markup_is_read_back(svc, tmp_path):
    class TwoStep(FakeGateway):
        async def call(self, tool, **kw):
            self.calls.append((tool, kw))
            if tool == "generate_design":
                return [{"type": "text", "text": json.dumps({"designId": "dsg_9"})}]
            assert tool == "get_design" and kw["design"] == "dsg_9" and kw["include_html"]
            return [{"type": "text", "text": json.dumps({"design": {"id": "dsg_9", "html": HTML}})}]

    gw = TwoStep()
    out = g.compose(svc, svc.doc["pages"][0], app_root=tmp_path / "app", gateway=gw)
    assert out.root is not None and out.design_id == "dsg_9"
    assert [c[0] for c in gw.calls] == ["generate_design", "get_design"]


def test_configuration_is_read_by_name_never_by_value(monkeypatch, tmp_path):
    monkeypatch.setattr("services.figma.integrations.config_for", lambda *a, **k: {})
    monkeypatch.delenv("UXPILOT_API_KEY", raising=False)
    assert g.configured(tmp_path) is False
    monkeypatch.setenv("UXPILOT_API_KEY", "ep_secret_secret_secret")
    assert g.configured(tmp_path) is True
    gw = g.gateway_for(tmp_path)
    assert gw.may_generate is True and gw.credential.ref == "UXPILOT_API_KEY"
    assert "ep_secret" not in repr(gw.credential)
