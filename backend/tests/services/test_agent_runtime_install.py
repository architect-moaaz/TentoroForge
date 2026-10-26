"""The agent runtime installs into a generated app deterministically.

A graph from the Agent Builder (or the planner's ``agent_graph``) compiles to the
runtime's flat config; the fixed runtime is copied beside it; nothing about it is
decided by a model. These tests pin the compile rules, what lands on disk, and
that re-running is safe.
"""
from __future__ import annotations

import json
import re
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


def test_a_router_with_no_routes_guides_nothing_and_says_so():
    c = compile_agent(graph(node("r", "router", "R", {"strategy": "fallback"})))
    assert c.config["router"] == {"strategy": "fallback"}
    assert any("router box has no routes" in w for w in c.warnings)
    assert "How to choose what to do" not in c.config["systemPrompt"]


def test_a_routers_routes_become_a_routing_guide_the_agent_is_given():
    """The router steers by guiding: each route says what kind of request it is and which of the tools belong to it."""
    routes = [{"id": "r1", "label": "Tickets", "condition": "Questions about tickets.", "tools": ["list_tickets", "ghost_tool"]},
              {"id": "r2", "label": "Talk to a person", "condition": "The person asks for a human.", "tools": ["request_human"]},
              {"id": "r3", "label": "   ", "condition": "ignored: no label"}]
    c = compile_agent(graph(
        node("sp", "system_prompt", "P", {"prompt": "You help."}),
        tool("t1", "list_tickets", tool_type="data_engine", entity="tickets", operation="list"),
        node("h", "human_handoff", "H", {"handlers": {"roles": ["Admin"]}}),
        node("r", "router", "R", {"strategy": "intent_classification", "routes": routes})))
    prompt = c.config["systemPrompt"]
    assert "How to choose what to do" in prompt
    assert "- Tickets: Questions about tickets. Use: list_tickets." in prompt, "only tools that exist are named"
    assert "ghost_tool" not in prompt
    assert "- Talk to a person: The person asks for a human. Use: request_human." in prompt, "the handoff tool is a tool too"
    assert "no label" not in prompt
    assert "If a request fits none of these" in prompt
    assert c.warnings == [] and c.config["router"]["routes"] == routes


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



def test_a_handoff_box_gives_the_agent_a_real_way_to_hand_over_and_forbids_promising_it_early():
    """Before the box ran, a prompt that let the agent say 'passing you to support' made a promise nothing
    kept (Movie Review, 2026-10-10). Now there IS a tool; the rule is that nothing is claimed before it succeeds."""
    c = compile_agent(graph(
        node("sp", "system_prompt", "P", {"prompt": "You help."}),
        node("h", "human_handoff", "Escalate", {"handlers": {"roles": ["Manager"]}}),
    ))
    prompt = c.config["systemPrompt"]
    assert "request_human" in prompt and "ONLY after request_human succeeds" in prompt and "reference" in prompt
    assert "cannot transfer" not in prompt
    t = next(t for t in c.config["tools"] if t["name"] == "request_human")
    assert t["kind"] == "handoff" and t["inputSchema"]["required"] == ["reason"]
    assert t["inputSchema"]["properties"]["urgency"]["enum"] == ["low", "normal", "urgent"] and t["rateLimit"] == "3/min"
    assert c.warnings == []
    assert "cannot transfer" not in compile_agent(graph(node("sp", "system_prompt", "P", {"prompt": "You help."}))).config["systemPrompt"]


def handoff_of(**cfg):
    return compile_agent(graph(node("h", "human_handoff", "H", cfg)))


def test_a_handoff_box_with_nothing_filled_in_still_compiles_into_a_working_handoff():
    c = handoff_of()
    h = c.config["handoff"]
    assert h["handlers"] == {"roles": [], "people": []} and h["assignment"] == "queue"
    assert h["notify"] == {"inApp": True, "email": False, "emailUrgentOnly": True}
    assert h["questions"] == ["Why do you need a person?", "How urgent is it?", "How can we reach you?"]
    assert any("names no one to handle it" in w for w in c.warnings)
    assert any(t["name"] == "request_human" for t in c.config["tools"])


def test_handlers_assignment_questions_and_notification_are_read_from_the_box():
    c = handoff_of(handlers={"roles": ["Manager", " ", "Agent"], "people": [{"id": "u1", "name": "Maya"}, "u2", {"name": "no id"}]},
                   assignment="round_robin", questions=["What is wrong?", "Phone number?"],
                   notify={"in_app": False, "email": True, "email_urgent_only": False},
                   conditions={"keyword_triggers": ["human", "speak to someone"]})
    h = c.config["handoff"]
    assert h["handlers"] == {"roles": ["Manager", "Agent"], "people": [{"id": "u1", "name": "Maya"}, {"id": "u2"}]}
    assert h["assignment"] == "round_robin" and h["questions"] == ["What is wrong?", "Phone number?"]
    assert h["notify"] == {"inApp": False, "email": True, "emailUrgentOnly": False}
    assert "What is wrong?" in c.config["systemPrompt"] and '"human"' in c.config["systemPrompt"]
    assert not any("handoff" in w for w in c.warnings), "a fully filled-in box has nothing to warn about"


def test_a_handoff_assignment_that_cannot_work_falls_back_to_the_queue_and_says_so():
    c = handoff_of(handlers={"roles": ["M"]}, assignment="owner")
    assert c.config["handoff"]["assignment"] == "queue" and any("no owner is chosen" in w for w in c.warnings)
    c = handoff_of(handlers={"roles": ["M"]}, assignment="owner", owner_id="u9")
    assert c.config["handoff"]["assignment"] == "owner" and c.config["handoff"]["ownerId"] == "u9"
    c = handoff_of(handlers={"roles": ["M"]}, assignment="by_astrology")
    assert c.config["handoff"]["assignment"] == "queue" and any("by_astrology" in w for w in c.warnings)


def test_at_most_five_questions_are_asked():
    assert len(handoff_of(handlers={"roles": ["M"]}, questions=[f"q{i}?" for i in range(9)]).config["handoff"]["questions"]) == 5


def handoff_graph() -> dict:
    return graph(node("sp", "system_prompt", "P", {"prompt": "You help."}),
                 node("h", "human_handoff", "Hand over", {"handlers": {"roles": ["Manager"]}}))


def test_an_agent_with_a_handoff_box_gets_the_inbox_the_route_and_the_table(tmp_path):
    project, app = make_app(tmp_path)
    install_agent_runtime(project, graphs=[handoff_graph()])
    for rel in ("src/lib/agents/handoff.ts", "src/lib/agents/handoff-store.ts", "src/db/schema/_forge_agent_handoffs.ts",
                "src/app/api/agent/handoffs/route.ts", "src/app/(dashboard)/handoffs/page.tsx"):
        assert (app / rel).is_file(), rel
    barrel = (app / "src" / "db" / "schema" / "index.ts").read_text()
    assert "_forge_agent_handoffs" in barrel and "./_forge_agent\"" in barrel, "both tables are exported"
    cfg = json.loads((app / "src" / "agents" / "definitions" / "support.json").read_text())
    assert any(t["kind"] == "handoff" and t["name"] == "request_human" for t in cfg["tools"])
    manifest = json.loads((app / "contracts" / "runtime-injection-manifest.json").read_text())
    listed = json.dumps(manifest)
    assert "api/agent/handoffs/route.ts" in listed and "handoffs/page.tsx" in listed, "prune keeps them"


def test_an_agent_without_one_gets_no_inbox_but_the_build_still_finds_the_store(tmp_path):
    project, app = make_app(tmp_path)
    install_agent_runtime(project, graphs=[sample_graph()])
    assert not (app / "src" / "app" / "api" / "agent" / "handoffs").exists()
    assert not (app / "src" / "app" / "(dashboard)" / "handoffs").exists()
    # io.ts loads the store on demand, and the build resolves that import whether or not it is ever used
    assert (app / "src" / "lib" / "agents" / "handoff-store.ts").is_file()
    assert (app / "src" / "db" / "schema" / "_forge_agent_handoffs.ts").is_file()


def test_installing_a_handoff_agent_twice_changes_nothing(tmp_path):
    project, app = make_app(tmp_path)
    install_agent_runtime(project, graphs=[handoff_graph()])
    before = {str(p.relative_to(app)): p.read_bytes() for p in app.rglob("*") if p.is_file() and "node_modules" not in p.parts}
    install_agent_runtime(project)
    after = {str(p.relative_to(app)): p.read_bytes() for p in app.rglob("*") if p.is_file() and "node_modules" not in p.parts}
    assert before == after
    assert (app / "src" / "db" / "schema" / "index.ts").read_text().count("_forge_agent_handoffs") == 1


# ---------------------------------------------------------------------------
# the way to the inbox: a menu link, and a bell that opens the handoff
# ---------------------------------------------------------------------------

NAV_LAYOUT = LAYOUT.replace(
    "  const body = (<>",
    "  const session = await auth();\n  const role = '';\n  navProps.groups = visibleTo(navProps.groups, role);\n  const body = (<>",
)
STOCK_BELL = "// notifications\nwindow.addEventListener('forge:workflow-done', f);\n"


def handoff_graph() -> dict:
    return graph(
        node("sp", "system_prompt", "P", {"prompt": "You help."}),
        node("h", "human_handoff", "Escalate", {"handlers": {"roles": ["Manager"]}}),
    )


def test_the_menu_gets_a_handoffs_link_added_after_it_is_narrowed_to_the_person(tmp_path):
    project, app = make_app(tmp_path, layout=NAV_LAYOUT)
    install_agent_runtime(project, graphs=[handoff_graph()])
    layout = (app / "src" / "app" / "(dashboard)" / "layout.tsx").read_text()
    assert layout.count("withHandoffsLink(navProps.groups, session.user)") == 1
    assert layout.index("visibleTo(navProps.groups, role)") < layout.index("withHandoffsLink(navProps.groups")
    assert (app / "src" / "lib" / "agents" / "handoff-nav.ts").is_file()
    install_agent_runtime(project)  # again: still one
    layout = (app / "src" / "app" / "(dashboard)" / "layout.tsx").read_text()
    assert layout.count("withHandoffsLink(navProps.groups") == 1 and layout.count("import { withHandoffsLink }") == 1


def test_a_layout_without_the_menu_line_keeps_its_menu_and_still_gets_the_widget(tmp_path):
    project, app = make_app(tmp_path)  # LAYOUT has no navProps line
    r = install_agent_runtime(project, graphs=[handoff_graph()])
    layout = (app / "src" / "app" / "(dashboard)" / "layout.tsx").read_text()
    assert r["widget_mounted"] is True and "withHandoffsLink" not in layout


def test_an_app_built_before_handoffs_gets_the_bell_that_opens_them(tmp_path):
    project, app = make_app(tmp_path)
    bell = app / "src" / "app" / "(dashboard)" / "NotificationBell.tsx"
    bell.write_text(STOCK_BELL, encoding="utf-8")
    install_agent_runtime(project, graphs=[handoff_graph()])
    assert "/handoffs" in bell.read_text(encoding="utf-8")


def test_a_bell_the_app_changed_is_left_alone(tmp_path):
    project, app = make_app(tmp_path)
    bell = app / "src" / "app" / "(dashboard)" / "NotificationBell.tsx"
    bell.write_text("// my own bell\n", encoding="utf-8")
    install_agent_runtime(project, graphs=[handoff_graph()])
    assert bell.read_text(encoding="utf-8") == "// my own bell\n"


def test_the_bell_is_not_touched_when_no_agent_hands_over(tmp_path):
    project, app = make_app(tmp_path)
    bell = app / "src" / "app" / "(dashboard)" / "NotificationBell.tsx"
    bell.write_text(STOCK_BELL, encoding="utf-8")
    install_agent_runtime(project, graphs=[sample_graph()])
    assert bell.read_text(encoding="utf-8") == STOCK_BELL


# ---------------------------------------------------------------------------
# safety: changes are held until the person agrees; each person has limits
# ---------------------------------------------------------------------------

def compiled_tool(**cfg) -> tuple[dict, list[str]]:
    c = compile_agent(graph(node("sp", "system_prompt", "P", {"prompt": "x"}), tool("t", "do_it", **cfg)))
    return c.config["tools"][0], c.warnings


@pytest.mark.parametrize("cfg", [
    {"tool_type": "data_engine", "entity": "tickets", "operation": "create"},
    {"tool_type": "data_engine", "entity": "tickets", "operation": "update"},
    {"tool_type": "data_engine", "entity": "tickets", "operation": "delete"},
    {"tool_type": "workflow", "workflow_id": "assign_ticket"},
    {"tool_type": "api_call", "endpoint": "/api/tickets/close", "method": "POST"},
    {"tool_type": "api_call", "endpoint": "/api/tickets/1", "method": "delete"},
])
def test_a_tool_that_changes_data_is_held_until_the_person_agrees(cfg):
    t, _ = compiled_tool(**cfg)
    assert t["confirm"] is True


@pytest.mark.parametrize("cfg", [
    {"tool_type": "data_engine", "entity": "tickets", "operation": "list"},
    {"tool_type": "data_engine", "entity": "tickets", "operation": "get"},
    {"tool_type": "api_call", "endpoint": "/api/tickets", "method": "GET"},
    {"tool_type": "function", "code": "return { ok: true };"},
])
def test_a_read_is_never_held(cfg):
    t, _ = compiled_tool(**cfg)
    assert "confirm" not in t


def test_the_builder_can_switch_it_on_for_a_tool_the_compiler_cannot_judge():
    t, _ = compiled_tool(tool_type="function", code="return 1;", confirm=True)
    assert t["confirm"] is True


def test_switching_it_off_for_a_write_is_allowed_and_said():
    t, warnings = compiled_tool(tool_type="data_engine", entity="tickets", operation="update", confirm=False)
    assert "confirm" not in t
    assert any("without asking the person first" in w and "do_it" in w for w in warnings)


def test_switching_it_off_for_a_read_says_nothing():
    _, warnings = compiled_tool(tool_type="data_engine", entity="tickets", operation="list", confirm=False)
    assert not any("without asking" in w for w in warnings)


def test_the_check_names_a_write_that_runs_without_asking():
    from services.agent_check import check_agent

    g = graph(node("sp", "system_prompt", "P", {"prompt": "x"}),
              tool("t", "close_ticket", tool_type="data_engine", entity="tickets", operation="update", confirm=False))
    f = [x for x in check_agent(g)["findings"] if x["code"] == "writes_without_asking"]
    assert len(f) == 1 and f[0]["severity"] == "warning" and f[0]["nodeId"] == "t"


def test_usage_limits_come_from_the_guardrail_box_and_only_what_is_set():
    sp = node("sp", "system_prompt", "P", {"prompt": "x"})
    none = compile_agent(graph(sp)).config["guardrails"]
    assert "limits" not in none  # the runtime's defaults apply
    some = compile_agent(graph(sp, node("g", "guardrail", "G", {"max_messages_per_minute": 5, "max_tokens_per_day": 0}))).config["guardrails"]
    assert some["limits"] == {"perMinute": 5, "tokensPerDay": 0}
    junk = compile_agent(graph(sp, node("g", "guardrail", "G", {"max_messages_per_hour": -1, "max_tokens_per_day": "lots", "max_messages_per_minute": True}))).config["guardrails"]
    assert "limits" not in junk


def test_the_install_brings_the_safety_files_and_the_usage_table(tmp_path):
    project, app = make_app(tmp_path)
    install_agent_runtime(project, graphs=[sample_graph()])
    for f in ("confirm.ts", "limits.ts", "usage-store.ts"):
        assert (app / "src" / "lib" / "agents" / f).is_file()
    assert (app / "src" / "db" / "schema" / "_forge_agent_usage.ts").is_file()
    assert "forgeAgentUsage" in (app / "src" / "db" / "schema" / "index.ts").read_text()


def test_the_install_brings_the_turn_record_the_feedback_and_the_insights(tmp_path):
    project, app = make_app(tmp_path)
    install_agent_runtime(project, graphs=[sample_graph()])
    for f in ("turns-store.ts", "insights.ts"):
        assert (app / "src" / "lib" / "agents" / f).is_file(), f
    assert (app / "src" / "app" / "api" / "agent" / "feedback" / "route.ts").is_file()
    assert (app / "src" / "app" / "api" / "agent" / "insights" / "route.ts").is_file()
    schema = (app / "src" / "db" / "schema" / "_forge_agent_turns.ts").read_text()
    assert '"forge_agent_turns"' in schema
    # indexes are named by hand (drizzle's own long names are truncated by Postgres and re-created on every push)
    for name in ("idx_forge_agent_turns_time", "idx_forge_agent_turns_agent", "idx_forge_agent_turns_msg"):
        assert name in schema
    assert 'export { forgeAgentTurns } from "./_forge_agent_turns";' in (app / "src" / "db" / "schema" / "index.ts").read_text()
    # the new routes are infrastructure, not redundant CRUD, so the route prune must keep them
    from services.api_route_prune import _load_injected_paths

    paths = _load_injected_paths(app)
    assert "src/app/api/agent/feedback/route.ts" in paths and "src/app/api/agent/insights/route.ts" in paths


def test_installing_twice_exports_the_turns_table_once(tmp_path):
    project, app = make_app(tmp_path)
    install_agent_runtime(project, graphs=[sample_graph()])
    install_agent_runtime(project)
    assert (app / "src" / "db" / "schema" / "index.ts").read_text().count("_forge_agent_turns") == 1


def test_the_insights_route_is_opened_in_the_middleware_next_to_the_debug_route(tmp_path):
    project, app = make_app(tmp_path)
    mw = app / "src" / "middleware.ts"
    mw.write_text('export const config = {\n  matcher: ["/((?!api/auth|_next|login).*)"],\n};\n', encoding="utf-8")
    install_agent_runtime(project, graphs=[sample_graph()])
    once = mw.read_text()
    assert "(?!api/auth|api/agent/debug|api/agent/insights|" in once
    install_agent_runtime(project)
    assert mw.read_text() == once, "re-installing changes nothing"
    assert once.count("api/agent/insights") == 1 and once.count("api/agent/debug") == 1


def test_an_app_that_already_opened_only_the_debug_route_gets_the_insights_route_added(tmp_path):
    project, app = make_app(tmp_path)
    mw = app / "src" / "middleware.ts"
    mw.write_text('export const config = {\n  matcher: ["/((?!api/auth|api/agent/debug|_next|login).*)"],\n};\n', encoding="utf-8")
    install_agent_runtime(project, graphs=[sample_graph()])
    after = mw.read_text()
    assert "(?!api/auth|api/agent/debug|api/agent/insights|_next" in after
    assert after.count("api/agent/debug") == 1


def test_an_assistant_that_has_changing_tools_is_told_the_app_asks_so_it_does_not_ask_twice():
    sp = node("sp", "system_prompt", "P", {"prompt": "You help."})
    with_write = compile_agent(graph(sp, tool("t", "close", tool_type="data_engine", entity="tickets", operation="update")))
    assert "confirmed by the app" in with_write.config["systemPrompt"] and "same input" in with_write.config["systemPrompt"]
    reads_only = compile_agent(graph(sp, tool("t", "look", tool_type="data_engine", entity="tickets", operation="list")))
    assert "confirmed by the app" not in reads_only.config["systemPrompt"]


# ---------------------------------------------------------------------------
# the platform's insights: what the app sends every turn with, and the salt that hides the people
# ---------------------------------------------------------------------------

def _env_of(app: Path, name: str = ".env.local") -> dict[str, str]:
    f = app / name
    out: dict[str, str] = {}
    if f.is_file():
        for line in f.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.partition("=")
            if sep and k.strip() and not k.lstrip().startswith("#"):
                out[k.strip()] = v.strip()
    return out


def test_the_install_brings_the_shipper_the_outbox_and_the_catch_up_route(tmp_path):
    project, app = make_app(tmp_path)
    install_agent_runtime(project, graphs=[sample_graph()])
    for f in ("insights-shipper.ts", "insights-outbox.ts"):
        assert (app / "src" / "lib" / "agents" / f).is_file(), f
    # under /api/cron/, which the sign-in gate already lets through (the route guards itself with the tick's secret)
    route = app / "src" / "app" / "api" / "cron" / "insights" / "route.ts"
    assert route.is_file() and "runInsightsTick" in route.read_text(encoding="utf-8")
    from services.api_route_prune import _load_injected_paths

    assert "src/app/api/cron/insights/route.ts" in _load_injected_paths(app)
    # the chat hands the shipper its moment after the reply
    chat = (app / "src" / "app" / "api" / "agent" / "chat" / "route.ts").read_text(encoding="utf-8")
    assert "holdForShipping" in chat


def test_the_turns_table_is_the_outbox_and_old_rows_keep_working(tmp_path):
    project, app = make_app(tmp_path)
    install_agent_runtime(project, graphs=[sample_graph()])
    schema = (app / "src" / "db" / "schema" / "_forge_agent_turns.ts").read_text(encoding="utf-8")
    new_cols = ("shipped_at", "ship_attempts", "ship_error", "user_role", "turn_number", "rating_at", "problem_message")
    for col in new_cols:
        assert f'"{col}"' in schema, col
    # hand-named, unique, short enough for Postgres to keep (63 characters), and one for "oldest unsent"
    names = re.findall(r'index\("([^"]+)"\)', schema)
    assert len(names) == len(set(names)) and all(len(n) <= 63 and n.startswith("idx_forge_agent_turns_") for n in names)
    assert "idx_forge_agent_turns_shipped" in names and ".on(t.shippedAt, t.createdAt)" in schema
    # a column that was not there before must be allowed to be empty, or every existing row would break the push
    for col in new_cols:
        line = next(ln for ln in schema.splitlines() if f'("{col}")' in ln)
        assert "notNull" not in line, col


def test_the_people_salt_is_made_once_kept_and_never_shown(tmp_path):
    project, app = make_app(tmp_path)
    first = install_agent_runtime(project, graphs=[sample_graph()])
    salt = _env_of(app)["FORGE_INSIGHTS_USER_SALT"]
    assert re.fullmatch(r"[0-9a-f]{64}", salt), "a long random value"
    assert first["insights_salt"] == "created"
    assert salt not in json.dumps(first), "the result never carries the value"
    before = (app / ".env.local").read_bytes()
    second = install_agent_runtime(project)
    assert second["insights_salt"] == "kept"
    assert _env_of(app)["FORGE_INSIGHTS_USER_SALT"] == salt and (app / ".env.local").read_bytes() == before
    # a copy beside the app's other secret files, kept out of git
    assert (app / ".forge-insights-salt").read_text(encoding="utf-8").strip() == salt
    assert ".forge-insights-salt" in (app / ".gitignore").read_text(encoding="utf-8").split()


def test_the_salt_survives_a_rebuild_that_rewrites_the_env_file(tmp_path):
    project, app = make_app(tmp_path)
    install_agent_runtime(project, graphs=[sample_graph()])
    salt = _env_of(app)["FORGE_INSIGHTS_USER_SALT"]
    # an assembly writes .env.local whole, and it knows nothing of this key
    (app / ".env.local").write_text("DATABASE_URL=postgres://x\nAUTH_SECRET=abc\n", encoding="utf-8")
    install_agent_runtime(project)
    assert _env_of(app)["FORGE_INSIGHTS_USER_SALT"] == salt, "the same salt, not a new one (a new one would split every person's history)"
    assert _env_of(app)["DATABASE_URL"] == "postgres://x" and _env_of(app)["AUTH_SECRET"] == "abc", "and nothing else was touched"
    # only with both copies gone does the app get a fresh one
    (app / ".env.local").write_text("", encoding="utf-8")
    (app / ".forge-insights-salt").unlink()
    install_agent_runtime(project)
    assert re.fullmatch(r"[0-9a-f]{64}", _env_of(app)["FORGE_INSIGHTS_USER_SALT"])
    assert _env_of(app)["FORGE_INSIGHTS_USER_SALT"] != salt


def test_a_salt_the_app_already_has_is_never_replaced(tmp_path):
    project, app = make_app(tmp_path)
    (app / ".env.local").write_text("FORGE_INSIGHTS_USER_SALT=chosen-by-the-builder\n", encoding="utf-8")
    result = install_agent_runtime(project, graphs=[sample_graph()])
    assert result["insights_salt"] == "kept"
    assert _env_of(app)["FORGE_INSIGHTS_USER_SALT"] == "chosen-by-the-builder"
    assert (app / ".forge-insights-salt").read_text(encoding="utf-8").strip() == "chosen-by-the-builder"
    # one that lives only in .env (Next reads it second) counts as present too: it is not shadowed by a new one
    p2, app2 = make_app(tmp_path / "other")
    (app2 / ".env").write_text("FORGE_INSIGHTS_USER_SALT=in-dot-env\n", encoding="utf-8")
    install_agent_runtime(p2, graphs=[sample_graph()])
    assert "FORGE_INSIGHTS_USER_SALT" not in _env_of(app2)
    assert (app2 / ".forge-insights-salt").read_text(encoding="utf-8").strip() == "in-dot-env"


def test_the_install_never_writes_the_platforms_address_or_key(tmp_path):
    project, app = make_app(tmp_path)
    (app / ".env.local").write_text("FORGE_INSIGHTS_URL=https://builder.set/this\nFORGE_INSIGHTS_KEY=fik_builderset\n", encoding="utf-8")
    install_agent_runtime(project, graphs=[sample_graph()])
    install_agent_runtime(project)
    env = _env_of(app)
    assert env["FORGE_INSIGHTS_URL"] == "https://builder.set/this" and env["FORGE_INSIGHTS_KEY"] == "fik_builderset", "what the builder set is left as it was"
    bare_project, bare_app = make_app(tmp_path / "bare")
    install_agent_runtime(bare_project, graphs=[sample_graph()])
    bare = _env_of(bare_app)
    assert "FORGE_INSIGHTS_URL" not in bare and "FORGE_INSIGHTS_KEY" not in bare and "FORGE_INSIGHTS_INCLUDE_TEXT" not in bare
    assert "FORGE_INSIGHTS_KEY" not in (bare_app / ".forge-insights-salt").read_text(encoding="utf-8")


def test_an_app_with_no_agent_gets_no_salt(tmp_path):
    project, app = make_app(tmp_path)
    result = install_agent_runtime(project)
    assert result["installed"] is False
    assert not (app / ".env.local").exists() and not (app / ".forge-insights-salt").exists()


# ---------------------------------------------------------------------------
# an assistant as one step of a workflow (agent_step)
# ---------------------------------------------------------------------------

STEP_FILES = ("workflow-only", "workflow-actor", "workflow-run", "workflow-step")
HOOK_MARK = "@/lib/agents/workflow-step"


def workflow_graph(**config) -> dict:
    """An assistant made for a workflow step: read-only lookups, flagged `workflow_only` in its config."""
    g = graph(
        node("sp", "system_prompt", "P", {"prompt": "You triage."}),
        tool("t1", "list_pets", tool_type="data_engine", entity="pets", operation="list"),
    )
    g["id"] = "wf_handle_triage"
    g["config"] = config
    return g


@pytest.mark.parametrize("name", STEP_FILES + ("agent-step-hook",))
def test_every_assistant_step_template_exists(name):
    from services.agent_runtime_install import _TEMPLATES

    assert (_TEMPLATES / "agents" / f"{name}.ts").is_file()


def test_the_install_brings_the_assistant_step_runtime(tmp_path):
    project, app = make_app(tmp_path)
    r = install_agent_runtime(project, graphs=[sample_graph()])
    for stem in STEP_FILES:
        assert (app / "src" / "lib" / "agents" / f"{stem}.ts").is_file(), stem
        assert f"src/lib/agents/{stem}.ts" in r["written"]
    manifest = json.loads((app / "contracts" / "runtime-injection-manifest.json").read_text())["paths"]
    assert "src/lib/agents/workflow-run.ts" in manifest


def test_an_app_with_no_workflow_runtime_gets_no_hook_and_no_complaint(tmp_path):
    project, app = make_app(tmp_path)
    r = install_agent_runtime(project, graphs=[sample_graph()])
    assert not (app / "src" / "lib" / "workflows").exists(), "the install does not invent a workflow runtime"
    assert not any("agent_step" in w or "workflow runtime" in w for w in r["warnings"])


def test_the_hook_goes_over_the_stub_every_app_ships(tmp_path):
    from services.agent_runtime_install import _TEMPLATES
    from services.runtime_injector import inject_runtime

    project, app = make_app(tmp_path)
    inject_runtime(str(app), app_name="X")
    stub = (app / "src" / "lib" / "workflows" / "agent-step.ts").read_text(encoding="utf-8")
    assert "no assistants installed" in stub and HOOK_MARK not in stub, "an app without assistants ships the stub"
    assert not (app / "src" / "lib" / "agents").exists()
    assert '"./agent-step"' in (app / "src" / "lib" / "workflows" / "index.ts").read_text(encoding="utf-8"),         "the engine always imports it, so an app without assistants still compiles"

    r = install_agent_runtime(project, graphs=[sample_graph()])
    hook = (app / "src" / "lib" / "workflows" / "agent-step.ts").read_bytes()
    assert hook == (_TEMPLATES / "agents" / "agent-step-hook.ts").read_bytes()
    assert HOOK_MARK.encode() in hook
    assert "src/lib/workflows/agent-step.ts" in r["written"]
    assert not any("older than the assistant step" in w for w in r["warnings"])


def test_a_regenerate_puts_the_stub_back_and_the_install_puts_the_hook_back_again(tmp_path):
    from services.runtime_injector import inject_runtime

    project, app = make_app(tmp_path)
    inject_runtime(str(app), app_name="X")
    install_agent_runtime(project, graphs=[sample_graph()])
    inject_runtime(str(app), app_name="X")  # a rebuild: copies the workflow runtime over, then installs the assistants again
    assert HOOK_MARK in (app / "src" / "lib" / "workflows" / "agent-step.ts").read_text(encoding="utf-8")
    assert (app / "src" / "lib" / "agents" / "workflow-step.ts").is_file()


def test_installing_the_assistant_step_twice_changes_nothing(tmp_path):
    from services.runtime_injector import inject_runtime

    project, app = make_app(tmp_path)
    inject_runtime(str(app), app_name="X")
    install_agent_runtime(project, graphs=[workflow_graph(workflow_only=True)])
    first = {p.relative_to(app).as_posix(): p.read_bytes() for p in app.rglob("*") if p.is_file()}
    install_agent_runtime(project)
    second = {p.relative_to(app).as_posix(): p.read_bytes() for p in app.rglob("*") if p.is_file()}
    assert first == second


def test_a_workflow_runtime_older_than_the_step_is_told_to_reinject(tmp_path):
    project, app = make_app(tmp_path)
    wf = app / "src" / "lib" / "workflows"
    wf.mkdir(parents=True)
    (wf / "index.ts").write_text("export function registerDefaultActions() {}\n", encoding="utf-8")
    r = install_agent_runtime(project, graphs=[sample_graph()])
    assert any("re-inject the runtime" in w for w in r["warnings"])
    assert (wf / "index.ts").read_text(encoding="utf-8") == "export function registerDefaultActions() {}\n", "the engine file is not patched in place"
    assert HOOK_MARK in (wf / "agent-step.ts").read_text(encoding="utf-8")


def test_a_workflow_only_definition_is_flagged_in_the_runtime_config(tmp_path):
    project, app = make_app(tmp_path)
    install_agent_runtime(project, graphs=[workflow_graph(workflow_only=True), sample_graph()])
    flagged = json.loads((app / "src" / "agents" / "definitions" / "wf_handle_triage.json").read_text())
    normal = json.loads((app / "src" / "agents" / "definitions" / "support.json").read_text())
    assert flagged["workflowOnly"] is True
    assert "workflowOnly" not in normal, "an ordinary assistant carries no flag at all: it behaves exactly as before"


@pytest.mark.parametrize("value", [False, "true", 1, None, "yes"])
def test_only_a_real_true_makes_an_assistant_workflow_only(tmp_path, value):
    project, app = make_app(tmp_path)
    install_agent_runtime(project, graphs=[workflow_graph(workflow_only=value)])
    cfg = json.loads((app / "src" / "agents" / "definitions" / "wf_handle_triage.json").read_text())
    assert "workflowOnly" not in cfg


def test_the_flag_can_also_sit_on_the_definition_itself(tmp_path):
    from services.agent_runtime_install import is_workflow_only

    assert is_workflow_only({"workflow_only": True}) and is_workflow_only({"config": {"workflow_only": True}})
    assert not is_workflow_only({}) and not is_workflow_only({"config": None}) and not is_workflow_only({"config": {"workflow_only": "true"}})


def test_the_registry_still_lists_a_workflow_only_assistant(tmp_path):
    """The workflow engine finds its assistant in the same registry the chat route uses; it is the chat route that leaves it out."""
    project, app = make_app(tmp_path)
    install_agent_runtime(project, graphs=[workflow_graph(workflow_only=True)])
    assert "definitions/wf_handle_triage.json" in (app / "src" / "agents" / "registry.ts").read_text()
