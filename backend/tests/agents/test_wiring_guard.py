# backend/tests/agents/test_wiring_guard.py
import asyncio

from agents.wiring_guard import collect_actionable, apply_guard_repairs, run_wiring_guard


def _schema():
    return {"root": {"type": "Stack", "children": [
        {"id": "b1", "type": "Button", "props": {"label": "Approve", "workflow": "ApproveTask"}},
        {"id": "b2", "type": "Button", "props": {"label": "Escalate"}},          # unwired
        {"id": "b3", "type": "Button", "props": {"label": "Back", "navigate": "/tasks"}},
    ]}}


def test_collect_actionable_lists_unwired_and_wired():
    items = collect_actionable(_schema())
    by_id = {i["id"]: i for i in items}
    assert by_id["b1"]["wired"] is True
    assert by_id["b2"]["wired"] is False
    assert by_id["b3"]["wired"] is True


def test_collect_actionable_flags_phantom_workflow():
    schema = {"root": {"type": "Stack", "children": [
        {"id": "bg", "type": "Button", "props": {"label": "Approve", "workflow": "GhostWF"}},
        {"id": "br", "type": "Button", "props": {"label": "Approve", "workflow": "RealWF"}},
    ]}}
    items = collect_actionable(schema, real_workflows={"RealWF"})
    by_id = {i["id"]: i for i in items}
    assert by_id["bg"]["wired"] is False
    assert by_id["bg"]["phantom"] is True
    assert by_id["br"]["wired"] is True


def test_collect_actionable_inspects_form_nodes():
    # A Form has no navigate/onClick; it is wired only when its workflow is real.
    schema = {"root": {"type": "Stack", "children": [
        {"id": "fg", "type": "Form", "props": {"workflow": "GhostWF"}},
        {"id": "fr", "type": "Form", "props": {"workflow": "CreateX"}},
    ]}}
    items = collect_actionable(schema, real_workflows={"CreateX"})
    by_id = {i["id"]: i for i in items}
    assert by_id["fg"]["wired"] is False
    assert by_id["fg"]["phantom"] is True
    assert by_id["fr"]["wired"] is True


def test_apply_repairs_overrides_phantom_form_workflow():
    schema = {"root": {"type": "Stack", "children": [
        {"id": "fg", "type": "Form", "props": {"workflow": "GhostWF"}}]}}
    repairs = [{"id": "fg", "kind": "workflow", "workflow": "CreateX"}]
    out, applied = apply_guard_repairs(schema, repairs,
                                       real_workflows={"CreateX"}, real_routes=set())
    from agents.wiring_guard import _walk_nodes
    form = next(n for n in _walk_nodes(out) if n.get("id") == "fg")
    assert form["props"]["workflow"] == "CreateX"   # phantom overridden
    assert {a["id"] for a in applied} == {"fg"}


def test_apply_repairs_only_accepts_real_backends():
    repairs = [
        {"id": "b2", "kind": "workflow", "workflow": "EscalateTask"},   # real
        {"id": "b2b", "kind": "workflow", "workflow": "GhostWF"},        # phantom -> reject
        {"id": "b9", "kind": "navigate", "to": "/ghost"},                # bad route -> reject
    ]
    schema = {"root": {"type": "Stack", "children": [
        {"id": "b2", "type": "Button", "props": {"label": "Escalate"}},
        {"id": "b2b", "type": "Button", "props": {"label": "X"}},
        {"id": "b9", "type": "Button", "props": {"label": "Y"}}]}}
    out, applied = apply_guard_repairs(schema, repairs,
                                       real_workflows={"EscalateTask"}, real_routes={"/tasks"})
    def find(i):
        from agents.wiring_guard import _walk_nodes
        return next(n for n in _walk_nodes(out) if n.get("id") == i)
    assert find("b2")["props"]["workflow"] == "EscalateTask"
    assert "workflow" not in find("b2b")["props"]   # phantom rejected
    assert "navigate" not in find("b9")["props"]    # bad route rejected
    assert {a["id"] for a in applied} == {"b2"}


def test_apply_repairs_overrides_phantom_but_not_real_workflow():
    schema = {"root": {"type": "Stack", "children": [
        {"id": "bg", "type": "Button", "props": {"label": "Approve", "workflow": "GhostWF"}},
        {"id": "br", "type": "Button", "props": {"label": "Approve", "workflow": "RealWF"}},
    ]}}
    repairs = [
        {"id": "bg", "kind": "workflow", "workflow": "RealWF"},        # phantom -> override
        {"id": "br", "kind": "workflow", "workflow": "OtherWF"},       # already real -> keep
    ]
    out, applied = apply_guard_repairs(schema, repairs,
                                       real_workflows={"RealWF", "OtherWF"}, real_routes=set())
    from agents.wiring_guard import _walk_nodes
    by_id = {n.get("id"): n for n in _walk_nodes(out) if n.get("id")}
    assert by_id["bg"]["props"]["workflow"] == "RealWF"    # phantom overridden
    assert by_id["br"]["props"]["workflow"] == "RealWF"    # real not overridden
    assert {a["id"] for a in applied} == {"bg"}


def test_run_guard_applies_validated_repair_via_injected_llm():
    schema = {"root": {"type": "Stack", "children": [
        {"id": "b2", "type": "Button", "props": {"label": "Escalate"}}]}}

    async def fake_llm(prompt: str) -> list:
        return [{"id": "b2", "kind": "workflow", "workflow": "EscalateTask"}]

    out, report = asyncio.run(run_wiring_guard(
        schema, real_workflows={"EscalateTask"}, real_routes=set(), call_llm=fake_llm))
    btn = next(n for n in __import__("agents.wiring_guard", fromlist=["_walk_nodes"])._walk_nodes(out) if n.get("id") == "b2")
    assert btn["props"]["workflow"] == "EscalateTask"
    assert report["repaired"] == 1


def test_run_guard_detects_and_repairs_phantom_workflow():
    schema = {"root": {"type": "Stack", "children": [
        {"id": "bg", "type": "Button", "props": {"label": "Approve", "workflow": "GhostWF"}}]}}

    async def fake_llm(prompt: str) -> list:
        return [{"id": "bg", "kind": "workflow", "workflow": "RealWF"}]

    out, report = asyncio.run(run_wiring_guard(
        schema, real_workflows={"RealWF"}, real_routes=set(), call_llm=fake_llm))
    btn = next(n for n in __import__("agents.wiring_guard", fromlist=["_walk_nodes"])._walk_nodes(out) if n.get("id") == "bg")
    assert btn["props"]["workflow"] == "RealWF"
    assert report["unwired"] == 1
    assert report["repaired"] == 1


def test_run_guard_noops_without_llm():
    schema = {"root": {"type": "Stack", "children": [
        {"id": "b", "type": "Button", "props": {"label": "X"}}]}}
    out, report = asyncio.run(run_wiring_guard(schema, real_workflows=set(),
                                               real_routes=set(), call_llm=None))
    assert out == schema and report["repaired"] == 0
