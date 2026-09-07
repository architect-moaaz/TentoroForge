"""renderSchemaPage must render via the CLIENT Engine, not the server SchemaRenderer.
The library components (MetricTile, Card, …) are client components (useTokens/useDensity),
so the server-side SchemaRenderer throws 'Attempted to call useTokens() from the server'.
The Engine is a client component and renders the tree on the client — matching the
working /[...slug] route."""
from pathlib import Path

_SP = Path("templates/app-foundation/src/lib/schema-page.tsx")


def test_renders_via_client_engine_not_server_renderer():
    src = _SP.read_text(encoding="utf-8")
    assert 'from "@tentoroforge/engine"' in src
    assert "<Engine" in src
    # The hazard is the server-side SchemaRenderer COMPONENT, which cannot run
    # client hooks — not the renderer package. This banned the whole module,
    # and the file legitimately imports `resolveCrumbHrefs` from it: a pure
    # function in runtime/crumbHrefs.ts with no hooks and no rendering. So the
    # ban now names the component.
    #
    # Matched as import/JSX rather than by substring: the file explains in a
    # comment why it does not use SchemaRenderer, and a bare `in src` test
    # would trip over the explanation.
    assert "import { SchemaRenderer" not in src
    assert "<SchemaRenderer" not in src
    assert "SchemaRenderer," not in src


def test_keeps_workflow_dispatch_wrapper_and_registry():
    src = _SP.read_text(encoding="utf-8")
    assert "WorkflowDispatchProvider" in src
    assert "getSchema" in src
