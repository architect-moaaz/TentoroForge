import asyncio
import agents.shell_layout_agent as sla
from services.shell_guardrail import validate_shell


def _bad_shell():
    """A shell with a duplicate PageOutlet — a renderability fault."""
    return {"schemaVersion": "2", "type": "Container", "children": [
        {"type": "Button", "props": {"label": "Home", "navigate": "/"}},
        {"type": "PageOutlet", "id": "page-outlet"},
        {"type": "PageOutlet", "id": "page-outlet-2"},
    ]}


def test_a_duplicate_outlet_is_repaired_not_rejected():
    """The repair itself, asked for directly.

    This used to drive `generate_shell_to_file` with the LLM agent stubbed to
    return the bad shell. The deterministic builder runs FIRST now —
    `build_shell_from_brief` when the project has a brief, otherwise
    `build_shell_deterministic`, with the LLM reached only if those error — so
    the injected shell never got near the repair and the call returned None.
    Stubbing two more builders to get back to it would be testing the order of
    the branches, not the guardrail. The guardrail is what this is for.
    """
    from services.shell_guardrail import repair_shell

    bad = _bad_shell()
    assert validate_shell(bad), "the fixture must be faulty for this to mean anything"
    fixed = repair_shell(bad)
    assert fixed is not None
    assert validate_shell(fixed) == []
    outlets = [n for n in _walk(fixed) if n.get("type") == "PageOutlet"]
    assert len(outlets) == 1


def _walk(node):
    if isinstance(node, dict):
        yield node
        for child in node.get("children") or []:
            yield from _walk(child)
    elif isinstance(node, list):
        for child in node:
            yield from _walk(child)
