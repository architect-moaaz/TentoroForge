"""The agent runtime installs into a generated app deterministically.

A graph from the Agent Builder (or the planner's ``agent_graph``) compiles to the
runtime's flat config; the fixed runtime is copied beside it; nothing about it is
decided by a model. These tests pin the compile rules, what lands on disk, and
that re-running is safe.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from services.agent_runtime_config import compile_agent, render_registry, safe_id
from services.agent_runtime_install import has_agents, install_agent_runtime, resolve_roots

SERVER_ID = "0b1c2d3e-4f50-6172-8394-a5b6c7d8e9f0"


def node(nid: str, kind: str, label: str, config: dict) -> dict:
    return {"id": nid, "type": kind, "position": {"x": 0, "y": 0},
            "data": {"label": label, "nodeType": kind, "config": config}}


def graph(*nodes: dict, **extra) -> dict:
    return {"id": "support", "name": "Support Bot", "description": "Helps customers", "nodes": list(nodes),
            "edges": [], **extra}


def tool(nid: str, name: str, **cfg) -> dict:
    return node(nid, "tool", name, {"tool_name": name, **cfg})


def by_name(config: dict, name: str) -> dict:
    return next(t for t in config["tools"] if t["name"] == name)


# ---------------------------------------------------------------------------
# compile
# ---------------------------------------------------------------------------

def test_the_system_prompt_node_becomes_the_prompt_and_model():
    c = compile_agent(graph(node("sp", "system_prompt", "Prompt", {
        "prompt": "You help.", "model": "claude-haiku-4-5", "temperature": 0.3, "max_tokens": 900})))
    assert c.config["systemPrompt"] == "You help."
    assert c.config["model"] == {"maxTokens": 900, "name": "claude-haiku-4-5", "temperature": 0.3}
    assert c.config["id"] == "support" and c.config["name"] == "Support Bot"


def test_a_missing_prompt_gets_a_default_and_says_so():
    c = compile_agent(graph())
    assert "Support Bot" in c.config["systemPrompt"]
    assert any("no system prompt" in w for w in c.warnings)


def test_the_entry_point_prompt_wins():
    c = compile_agent(graph(
        node("a", "system_prompt", "A", {"prompt": "first"}),
        node("b", "system_prompt", "B", {"prompt": "entry", "is_entry_point": True}),
    ))
    assert c.config["systemPrompt"] == "entry"


def test_a_data_tool_offers_the_model_only_what_the_operation_takes():
    c = compile_agent(graph(
        tool("t1", "list_orders", tool_type="data_engine", entity="orders", operation="list"),
        tool("t2", "get_order", tool_type="data_engine", entity="orders", operation="get"),
        tool("t3", "make_order", tool_type="data_engine", entity="orders", operation="create"),
    ))
    lst, get, make = (by_name(c.config, n) for n in ("list_orders", "get_order", "make_order"))
    assert lst["kind"] == "data" and lst["entity"] == "orders" and lst["operation"] == "list"
    assert {"search", "filters", "limit"} <= set(lst["inputSchema"]["properties"])
    assert get["inputSchema"]["required"] == ["id"]
    assert make["inputSchema"]["required"] == ["data"]


def test_a_data_tool_with_no_entity_is_dropped_with_a_warning():
    c = compile_agent(graph(tool("t", "orders", tool_type="data_engine")))
    assert c.config["tools"] == []
    assert any("no entity" in w for w in c.warnings)


def test_an_api_tool_reads_its_path_params_and_stays_inside_the_app():
    c = compile_agent(graph(
        tool("t1", "order", tool_type="api_call", endpoint="/api/orders/:id", method="get"),
        tool("t2", "outside", tool_type="api_call", endpoint="https://example.com/x"),
        tool("t3", "itself", tool_type="api_call", endpoint="/api/agent/chat"),
    ))
    order = by_name(c.config, "order")
    assert order["kind"] == "api" and order["method"] == "GET"
    assert order["inputSchema"]["required"] == ["id"]
    for n in ("outside", "itself"):
        t = by_name(c.config, n)
        assert t["kind"] == "function" and "handler" not in t, "it must not be callable"
    assert sum("kept as unimplemented" in w for w in c.warnings) == 2


def test_raw_sql_is_never_handed_to_an_agent():
    c = compile_agent(graph(tool("t", "sql", tool_type="db_query", query="select * from users")))
    t = by_name(c.config, "sql")
    assert t["kind"] == "function" and "handler" not in t
    assert not any("select" in json.dumps(v) for v in t.values())
    assert any("raw SQL" in w for w in c.warnings)


def test_a_workflow_tool_names_its_workflow():
    c = compile_agent(graph(tool("t", "refund", tool_type="workflow", workflow_id="refund-flow",
                                 parameters=[{"name": "amount", "type": "number", "required": True}])))
    t = by_name(c.config, "refund")
    assert t["kind"] == "workflow" and t["workflowId"] == "refund-flow"
    assert t["inputSchema"]["properties"]["amount"]["type"] == "number"
    assert t["inputSchema"]["required"] == ["amount"]


def test_an_mcp_tool_uses_the_slug_the_app_env_is_keyed_by():
    from services.env_writer import _mcp_id_slug

    c = compile_agent(graph(
        tool("t1", "identify_thing", tool_type="function", code="return {brand: 'a', model: 'b'};"),
        tool("t2", "search_web", tool_type="mcp", mcp_server_id=SERVER_ID, mcp_tool_name="firecrawl_search",
             args_mapping={"query": "{{identify_thing.brand}} {{identify_thing.model}}", "limit": "{{input.n}}"}),
    ))
    t = by_name(c.config, "search_web")
    assert t["kind"] == "mcp" and t["mcpToolName"] == "firecrawl_search"
    assert t["mcpServerId"] == _mcp_id_slug(uuid.UUID(SERVER_ID)) == "0B1C2D3E4F50"
    # a reference to another tool's result is not something the model supplies
    assert list(t["inputSchema"]["properties"]) == ["n"]
    assert t["argsMapping"]["query"] == "{{identify_thing.brand}} {{identify_thing.model}}"


def test_a_function_tool_with_code_gets_a_module_and_one_without_says_so():
    c = compile_agent(graph(
        tool("t1", "lookup", tool_type="function", code="return { ok: true };"),
        tool("t2", "vague", tool_type="function"),
    ))
    assert by_name(c.config, "lookup")["handler"] == "lookup"
    assert "export default async function lookup" in c.tool_files["lookup"]
    assert "return { ok: true };" in c.tool_files["lookup"]
    assert c.tool_files["lookup"].startswith("// forge-agent-tool")
    assert "handler" not in by_name(c.config, "vague")
    assert any("no code" in w for w in c.warnings)


def test_a_module_that_already_exports_a_default_is_kept_as_written():
    src = "export default async function f() { return 1; }"
    c = compile_agent(graph(tool("t", "f", tool_type="function", code=src)))
    assert src in c.tool_files["f"] and c.tool_files["f"].count("export default") == 1


def test_a_described_identify_tool_maps_to_the_ai_preset():
    c = compile_agent(graph(tool("t", "identify_product", tool_type="function",
                                 description="Identify the product in a photo")))
    t = by_name(c.config, "identify_product")
    assert t["kind"] == "ai_action" and t["aiAction"] == "identify_product"
    assert t["inputSchema"]["required"] == ["image_file_id"]


def test_tool_names_are_made_legal_and_unique():
    c = compile_agent(graph(
        tool("a", "Get Order!", tool_type="workflow", workflow_id="w"),
        tool("b", "Get Order!", tool_type="workflow", workflow_id="w"),
    ))
    names = [t["name"] for t in c.config["tools"]]
    assert names == ["Get_Order", "Get_Order_2"]


def test_guardrail_rules_become_input_patterns_output_patterns_and_output_rules():
    c = compile_agent(graph(
        node("g1", "guardrail", "Topics", {"guardrail_type": "both", "rules": [
            {"id": "1", "name": "no politics", "type": "block_topics", "expression": "politics, religion"}]}),
        node("g2", "guardrail", "PII", {"guardrail_type": "output_filter", "rules": [
            {"id": "2", "name": "pii", "type": "pii_redaction"}]}),
        node("g3", "guardrail", "Gate", {"guardrail_type": "output_filter", "rules": [
            {"id": "3", "name": "confident", "type": "custom", "expression": "identify.confidence >= 0.5"}]}),
    ))
    g = c.config["guardrails"]
    assert any("politics" in p for p in g["input"]["blockPatterns"])
    assert any("ignore" in p for p in g["input"]["blockPatterns"]), "the injection default stays"
    assert g["input"]["requireAuth"] is True
    assert g["output"]["contentFilter"] == "strict"
    assert any("\\d{3}-\\d{2}-\\d{4}" in p for p in g["output"]["blockPatterns"])
    assert g["outputRules"][0]["expression"] == "identify.confidence >= 0.5"


def test_a_custom_input_filter_is_refused_not_pretended():
    c = compile_agent(graph(node("g", "guardrail", "G", {"guardrail_type": "input_filter", "rules": [
        {"id": "1", "name": "x", "type": "custom", "expression": "a = 1"}]})))
    assert c.config["guardrails"]["outputRules"] == []
    assert any("custom input filter" in w for w in c.warnings)


def test_memory_defaults_and_unsupported_kinds_degrade_loudly():
    assert compile_agent(graph()).config["memory"] == {"type": "conversation", "maxMessages": 20, "summarizeAfter": 30}
    c = compile_agent(graph(node("m", "memory", "M", {"memory_type": "vector", "capacity": 500})))
    assert c.config["memory"]["type"] == "vector" and c.config["memory"]["maxMessages"] == 20
    assert any("not supported yet" in w for w in c.warnings)
    c = compile_agent(graph(node("m", "memory", "M", {"memory_type": "conversation", "capacity": 8})))
    assert c.config["memory"] == {"type": "conversation", "maxMessages": 8, "summarizeAfter": 18}


def test_router_and_handoff_are_carried_but_flagged_as_not_executed():
    c = compile_agent(graph(
        node("r", "router", "R", {"strategy": "fallback"}),
        node("h", "human_handoff", "H", {"target": {"type": "email", "value": "a@b.c"}}),
    ))
    assert c.config["router"] == {"strategy": "fallback"}
    assert c.config["handoff"]["target"]["value"] == "a@b.c"
    assert any("not executed yet" in w for w in c.warnings)


def test_turns_are_capped_and_the_ui_has_a_welcome_line():
    c = compile_agent(graph(config={"max_turns": 99}))
    assert c.config["maxTurns"] == 12
    assert c.config["ui"]["position"] == "bottom-right" and "Support Bot" in c.config["ui"]["welcomeMessage"]


def test_compiling_is_deterministic():
    g = graph(node("sp", "system_prompt", "P", {"prompt": "x"}),
              tool("t", "o", tool_type="data_engine", entity="orders", operation="list"))
    assert compile_agent(g).config == compile_agent(json.loads(json.dumps(g))).config


def test_safe_id_is_filename_safe():
    assert safe_id("a/b c") == "a-b-c" and safe_id("") == "agent" and safe_id("../x") == "x"


def test_registry_lists_every_agent_and_handler():
    ts = render_registry(["a", "b"], ["lookup"])
    assert 'from "./definitions/a.json"' in ts and 'from "./definitions/b.json"' in ts
    assert "[agent0, agent1]" in ts
    assert '"lookup": () => import("./tools/lookup")' in ts


# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------

LAYOUT = (
    'import { schemas } from "@/schemas/registry";\n'
    "export default function L({ children }) {\n"
    "  const body = (<>\n"
    "      {children}\n"
    "      {mobileTabs.length > 0 && (<b/>)}\n"
    "  </>);\n"
    "}\n"
)


def make_app(tmp_path: Path, *, nested: bool = False, layout: str = LAYOUT) -> tuple[Path, Path]:
    project = tmp_path / "proj"
    app = project / "app" if nested else project
    (app / "src" / "db" / "schema").mkdir(parents=True)
    (app / "src" / "db" / "schema" / "index.ts").write_text('export * from "./user";\n', encoding="utf-8")
    (app / "src" / "app" / "(dashboard)").mkdir(parents=True)
    (app / "src" / "app" / "(dashboard)" / "layout.tsx").write_text(layout, encoding="utf-8")
    (app / "package.json").write_text(json.dumps({"name": "x", "dependencies": {"next": "^15"}}), encoding="utf-8")
    return project, app


def sample_graph() -> dict:
    return graph(
        node("sp", "system_prompt", "P", {"prompt": "You help."}),
        tool("t1", "list_orders", tool_type="data_engine", entity="orders", operation="list"),
        tool("t2", "lookup", tool_type="function", code="return { ok: true };"),
    )


def test_nothing_to_install_without_a_definition(tmp_path):
    project, _ = make_app(tmp_path)
    assert has_agents(project) is False
    assert install_agent_runtime(project)["installed"] is False
    assert not (project / "src" / "lib" / "agents").exists()


def test_install_lays_down_the_runtime_the_definition_and_the_wiring(tmp_path):
    project, app = make_app(tmp_path)
    r = install_agent_runtime(project, graphs=[sample_graph()])
    assert r["installed"] and r["widget_mounted"] and r["agents"][0]["tools"] == 2

    for rel in ("types", "guardrails", "memory", "tools", "runtime", "io", "store"):
        assert (app / "src" / "lib" / "agents" / f"{rel}.ts").is_file(), rel
    assert (app / "src" / "components" / "agents" / "ChatWidget.tsx").is_file()
    assert (app / "src" / "app" / "api" / "agent" / "chat" / "route.ts").is_file()
    assert (app / "src" / "app" / "api" / "agent" / "conversations" / "route.ts").is_file()
    assert (app / "src" / "app" / "(dashboard)" / "assistant" / "page.tsx").is_file()
    assert (app / "src" / "db" / "schema" / "_forge_agent.ts").is_file()
    assert "_forge_agent" in (app / "src" / "db" / "schema" / "index.ts").read_text()

    cfg = json.loads((app / "src" / "agents" / "definitions" / "support.json").read_text())
    assert cfg["name"] == "Support Bot" and [t["name"] for t in cfg["tools"]] == ["list_orders", "lookup"]
    assert (app / "src" / "agents" / "tools" / "lookup.ts").is_file()
    reg = (app / "src" / "agents" / "registry.ts").read_text()
    assert "definitions/support.json" in reg and '"lookup"' in reg

    pkg = json.loads((app / "package.json").read_text())["dependencies"]
    assert "@anthropic-ai/sdk" in pkg and "@modelcontextprotocol/sdk" in pkg
    assert (project / "agent-definitions" / "support.json").is_file(), "the graph stays the source of truth"


def test_the_widget_is_mounted_once(tmp_path):
    project, app = make_app(tmp_path)
    install_agent_runtime(project, graphs=[sample_graph()])
    install_agent_runtime(project)
    layout = (app / "src" / "app" / "(dashboard)" / "layout.tsx").read_text()
    assert layout.count("<ChatWidget />") == 1 and layout.count("import { ChatWidget }") == 1


def test_an_unrecognised_layout_is_reported_not_broken(tmp_path):
    project, app = make_app(tmp_path, layout="export default function L(){return null}\n")
    r = install_agent_runtime(project, graphs=[sample_graph()])
    assert r["installed"] and r["widget_mounted"] is False
    assert any("not mounted" in w for w in r["warnings"])
    assert (app / "src" / "app" / "(dashboard)" / "layout.tsx").read_text() == "export default function L(){return null}\n"


def test_the_routes_are_in_the_injection_manifest_so_prune_keeps_them(tmp_path):
    from services.api_route_prune import _load_injected_paths

    project, app = make_app(tmp_path)
    install_agent_runtime(project, graphs=[sample_graph()])
    paths = _load_injected_paths(app)
    assert "src/app/api/agent/chat/route.ts" in paths
    assert "src/app/api/agent/conversations/route.ts" in paths


def test_install_is_idempotent(tmp_path):
    project, app = make_app(tmp_path)
    install_agent_runtime(project, graphs=[sample_graph()])
    first = {p.relative_to(app).as_posix(): p.read_bytes() for p in app.rglob("*") if p.is_file()}
    install_agent_runtime(project)
    second = {p.relative_to(app).as_posix(): p.read_bytes() for p in app.rglob("*") if p.is_file()}
    assert first == second


def test_removing_an_agent_removes_what_it_installed(tmp_path):
    project, app = make_app(tmp_path)
    install_agent_runtime(project, graphs=[sample_graph()])
    assert (app / "src" / "agents" / "tools" / "lookup.ts").is_file()
    (project / "agent-definitions" / "support.json").unlink()
    install_agent_runtime(project, graphs=[{**graph(node("sp", "system_prompt", "P", {"prompt": "x"})), "id": "other"}])
    assert not (app / "src" / "agents" / "definitions" / "support.json").exists()
    assert not (app / "src" / "agents" / "tools" / "lookup.ts").exists()
    assert (app / "src" / "agents" / "definitions" / "other.json").is_file()


def test_a_tool_module_the_user_wrote_by_hand_is_left_alone(tmp_path):
    project, app = make_app(tmp_path)
    install_agent_runtime(project, graphs=[sample_graph()])
    mine = app / "src" / "agents" / "tools" / "mine.ts"
    mine.write_text("export default 1;\n", encoding="utf-8")
    install_agent_runtime(project)
    assert mine.is_file()


def test_a_blueprint_project_installs_into_its_app_directory(tmp_path):
    project, app = make_app(tmp_path, nested=True)
    assert resolve_roots(project) == (project, app)
    install_agent_runtime(project, graphs=[sample_graph()])
    assert resolve_roots(app) == (project, app), "the app root finds its project once definitions exist"
    assert (app / "src" / "agents" / "registry.ts").is_file()
    assert not (project / "src").exists()
    assert has_agents(app) is True, "the injector is handed the app root and must still find the project's agents"


def test_inject_runtime_installs_agents_only_for_a_project_that_has_them(tmp_path):
    from services.runtime_injector import inject_runtime

    project, app = make_app(tmp_path)
    inject_runtime(str(app), app_name="X")
    assert not (app / "src" / "lib" / "agents").exists(), "no agent, no runtime"

    install_agent_runtime(project, graphs=[sample_graph()])
    # a regenerate re-runs injection, which rewrites the manifest — the agent files must survive it
    res = inject_runtime(str(app), app_name="X")
    assert (app / "src" / "lib" / "agents" / "runtime.ts").is_file()
    assert "src/lib/agents/runtime.ts" in res["copied"]
    manifest = json.loads((app / "contracts" / "runtime-injection-manifest.json").read_text())["paths"]
    assert "src/app/api/agent/chat/route.ts" in manifest


@pytest.mark.parametrize("name", ["runtime", "tools", "guardrails", "memory", "types", "io", "store"])
def test_every_core_template_exists(name):
    from services.agent_runtime_install import _TEMPLATES

    assert (_TEMPLATES / "agents" / f"{name}.ts").is_file()

def test_a_project_that_was_never_built_keeps_the_definition_and_gets_no_src(tmp_path):
    """Saved is saved; the install waits for an app. Scaffolding src/ into a draft
    would make it look built (the chat treats any src/ file as 'this project has code')."""
    project = tmp_path / "draft"
    project.mkdir()
    r = install_agent_runtime(project, graphs=[sample_graph()])
    assert r["installed"] is False and r["no_app"] is True
    assert any("no generated app yet" in w for w in r["warnings"])
    assert (project / "agent-definitions" / "support.json").is_file(), "the definition is kept"
    assert not (project / "src").exists(), "nothing is scaffolded into a project with no app"
    assert has_agents(project) is True


def test_a_project_whose_folder_is_gone_still_keeps_the_definition(tmp_path):
    project = tmp_path / "output" / "gone"  # neither it nor its parent exists
    r = install_agent_runtime(project, graphs=[sample_graph()])
    assert r["no_app"] is True
    assert (project / "agent-definitions" / "support.json").is_file()


def test_the_build_installs_what_a_draft_saved(tmp_path):
    """The agent saved before the app existed is installed when the app is built:
    inject_runtime finds the definitions and runs the install."""
    from services.runtime_injector import inject_runtime

    project = tmp_path / "p"
    project.mkdir()
    install_agent_runtime(project, graphs=[sample_graph()])  # saved while a draft
    assert not (project / "src").exists()
    (project / "package.json").write_text(json.dumps({"dependencies": {}}), encoding="utf-8")
    (project / "src" / "db" / "schema").mkdir(parents=True)
    inject_runtime(str(project), app_name="X")  # the build
    assert (project / "src" / "lib" / "agents" / "runtime.ts").is_file()
    assert (project / "src" / "agents" / "definitions" / "support.json").is_file()



def test_an_agent_with_a_handoff_node_is_not_told_it_can_hand_off():
    """Handoff is not executed yet: a prompt that lets the agent say 'passing you to support'
    makes a promise nothing keeps (Movie Review, 2026-10-10)."""
    c = compile_agent(graph(
        node("sp", "system_prompt", "P", {"prompt": "You help."}),
        node("h", "human_handoff", "Escalate", {"target": {"type": "queue", "value": "support-queue"}}),
    ))
    assert "cannot transfer anyone to a human" in c.config["systemPrompt"]
    assert c.config["handoff"]["target"]["value"] == "support-queue"
    assert "cannot transfer" not in compile_agent(graph(node("sp", "system_prompt", "P", {"prompt": "You help."}))).config["systemPrompt"]
