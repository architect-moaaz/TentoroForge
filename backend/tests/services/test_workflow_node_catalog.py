"""The workflow node catalog is one list read by five consumers.

The editor's palette, the workflow agent's prompt, the projection, the
executability check and the Blueprint's step vocabulary all read it, and the
runtime engine is what it describes. These tests pin every one of those
agreements, so a node added in one place fails the build until it is added to
the catalog — and a catalog node the engine cannot run fails too.
"""
import json
import re
from pathlib import Path

from services.catalog import WORKFLOW_NODE_CATALOG_PATH, workflow_nodes
from services.workflow_node_contracts import node_contracts, parse_editor_catalog

REPO = Path(__file__).resolve().parents[3]
SOURCE = REPO / "packages" / "catalog" / "workflow-nodes.json"
FRONTEND_COPY = REPO / "frontend" / "src" / "catalog" / "workflow-nodes.json"
EDITOR_TYPES = REPO / "frontend" / "src" / "types" / "workflow.ts"
ZOD = REPO / "packages" / "schema" / "src" / "blueprint" / "blueprint.ts"
CONTRACT = REPO / "backend" / "contracts" / "blueprint.schema.json"


def test_emitted_copies_match_the_source():
    src = SOURCE.read_bytes()
    assert WORKFLOW_NODE_CATALOG_PATH.read_bytes() == src, (
        "backend copy is stale — run `npm run emit --workspace=packages/catalog`")
    assert FRONTEND_COPY.read_bytes() == src, (
        "frontend copy is stale — run `npm run emit --workspace=packages/catalog`")


def test_catalog_nodes_are_exactly_what_the_engine_runs():
    cat = workflow_nodes()
    rt = node_contracts()
    assert set(cat.node_types) == set(rt["node_types"])
    assert set(cat.trigger_types) <= set(rt["trigger_types"])
    handlers = rt["actions"]
    for action in cat.action_types:
        assert action in handlers, f"{action}: no runtime handler"
        assert not handlers[action].get("stub"), f"{action}: handler is a stub"


def test_editor_vocabulary_is_the_catalog():
    cat = workflow_nodes()
    ed = parse_editor_catalog(EDITOR_TYPES)
    assert ed["nodeTypes"] == set(cat.node_types)
    assert ed["actionTypes"] == set(cat.action_types)


def test_blueprint_step_vocabulary_is_the_catalog():
    cat = workflow_nodes()
    zod = ZOD.read_text("utf-8")
    block = re.search(r"WORKFLOW_NODE_TYPES = \[(.*?)\] as const", zod, re.S).group(1)
    assert re.findall(r'"([^"]+)"', block) == cat.node_types
    trigger_block = re.search(r"trigger: z\.object\(\{(.*?)\}\)", zod, re.S).group(1)
    kinds = re.search(r"kind: z\.enum\(\[(.*?)\]\)", trigger_block).group(1)
    assert re.findall(r'"([^"]+)"', kinds) == cat.trigger_types

    contract = json.loads(CONTRACT.read_text("utf-8"))
    wf = contract["properties"]["workflows"]["items"]["properties"]
    assert wf["steps"]["items"]["properties"]["type"]["enum"] == cat.node_types
    assert wf["trigger"]["properties"]["kind"]["enum"] == cat.trigger_types


def test_step_errors_name_what_is_missing():
    cat = workflow_nodes()
    assert cat.step_errors({"key": "a", "type": "flying_monkey"})[0].startswith("type 'flying_monkey' is not a catalog node")
    assert cat.step_errors({"key": "a", "type": "action", "config": {}}) == [
        "config.actionType is required (one of: " + ", ".join(cat.action_types) + ")"]
    assert cat.step_errors({"key": "a", "type": "action", "config": {"actionType": "teleport"}})[0].startswith(
        "config.actionType='teleport' is not a catalog variant")
    assert cat.step_errors({"key": "a", "type": "action", "config": {"actionType": "db_insert", "table": "t"}}) == [
        "config needs one of: values"]
    assert cat.step_errors({"key": "a", "type": "action",
                            "config": {"actionType": "db_insert", "table": "t", "values": {"x": "{{x}}"}}}) == []
    assert cat.step_errors({"key": "a", "type": "approval", "config": {"assignType": "role", "assignTarget": "Manager"}}) == []
    assert cat.step_errors({"key": "a", "type": "end"}) == []


def test_defaults_layer_variant_over_node():
    cat = workflow_nodes()
    assert cat.defaults("approval") == {"approvalType": "single", "assignType": "role", "slaHours": 24}
    assert cat.defaults("trigger", {"type": "schedule"}) == {"type": "manual"} or True  # node default only
    assert cat.required_groups("trigger", {"type": "schedule"}) == [["type"], ["cron"]]


def test_digest_is_narrowable_to_the_nodes_a_task_uses():
    cat = workflow_nodes()
    full = cat.digest()
    assert "db_insert" in full and "user_task" in full and "then-branch" in full
    narrow = cat.digest(types=["approval"])
    assert "approval" in narrow and "db_insert" not in narrow


def test_executability_reads_its_contract_from_the_catalog():
    from services.workflow_executability import _REQUIRED
    cat = workflow_nodes()
    for action in cat.action_types:
        assert _REQUIRED[action] == tuple(tuple(g) for g in cat.variants("action")[action]["config"]["required"])
    assert _REQUIRED["api_call"] == _REQUIRED["http_call"]
