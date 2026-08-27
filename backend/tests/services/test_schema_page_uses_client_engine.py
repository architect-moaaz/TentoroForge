"""renderSchemaPage must render via the CLIENT Engine, not the server SchemaRenderer.
The library components (MetricTile, Card, …) are client components (useTokens/useDensity),
so the server-side SchemaRenderer throws 'Attempted to call useTokens() from the server'.
The Engine is a client component and renders the tree on the client — matching the
working /[...slug] route."""
from pathlib import Path

_SP = Path("templates/app-foundation/src/lib/schema-page.tsx")


def test_renders_via_client_engine_not_server_renderer():
    src = _SP.read_text()
    assert 'from "@tentoroforge/engine"' in src
    assert "<Engine" in src
    # the server-side renderer must NOT be imported/used (it can't run client hooks)
    assert 'from "@tentoroforge/renderer"' not in src


def test_keeps_workflow_dispatch_wrapper_and_registry():
    src = _SP.read_text()
    assert "WorkflowDispatchProvider" in src
    assert "getSchema" in src
