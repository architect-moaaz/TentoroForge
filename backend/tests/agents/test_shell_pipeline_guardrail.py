import asyncio
import agents.shell_layout_agent as sla
from services.shell_guardrail import validate_shell


def test_generate_shell_repairs_duplicate_outlet(monkeypatch, tmp_path):
    # A free shell with a duplicate PageOutlet (renderability fault).
    bad = {"schemaVersion": "2", "type": "Container", "children": [
        {"type": "Button", "props": {"label": "Home", "navigate": "/"}},
        {"type": "PageOutlet", "id": "page-outlet"},
        {"type": "PageOutlet", "id": "page-outlet-2"},
    ]}

    async def fake_run(plan, nav_flow, brand=None, domain_context=None, design_spec=None):
        if False:  # make this an async generator that yields nothing
            yield None
        return
    monkeypatch.setattr(sla, "run_shell_layout_agent", fake_run)
    monkeypatch.setattr(sla, "extract_shell", lambda text: bad)

    out = asyncio.run(sla.generate_shell_to_file(
        output_dir=str(tmp_path),
        plan={"name": "X", "pages": []},
        nav_flow={"pages": [{"route": "/", "title": "Home"}]},
    ))
    assert out is not None
    # The guardrail repaired the duplicate PageOutlet → renderable.
    assert validate_shell(out) == []


def test_run_shell_layout_agent_accepts_design_spec():
    # signature carries design_spec (threaded for the rich context builder)
    import inspect
    sig = inspect.signature(sla.run_shell_layout_agent)
    assert "design_spec" in sig.parameters
    sig2 = inspect.signature(sla.generate_shell_to_file)
    assert "design_spec" in sig2.parameters
