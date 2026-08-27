"""LangGraph pipeline spine (LG-2 + O1) — topology, SSE bridge, crash-resume,
coverage-halt, and router default selection."""
from __future__ import annotations

import os

import pytest

import services.pipeline_graph as pg

EXPECTED_ORDER = ["bootstrap", "maquettes", "discovery", "foundation",
                  "design", "contracts", "contracts_gate", "schema",
                  "schema_gate", "workflows", "rules", "runtime", "pages",
                  "pages_gate", "finish", "finish_gate", "ship"]


def test_topology_matches_relay_order():
    g = pg.build_pipeline_graph()
    assert list(g.nodes) == EXPECTED_ORDER + ["archetype", "heal"]


def test_node_registry_matches_topology():
    assert [n for n, _ in pg._NODES] == EXPECTED_ORDER


@pytest.mark.asyncio
async def test_crash_then_resume_skips_completed_phases(tmp_path, monkeypatch):
    """The point of the StateGraph: a build that dies mid-phase resumes from
    its checkpoint instead of restarting. Phase 1 must NOT re-run."""
    calls: list[str] = []
    crash = {"armed": True}

    async def n1(state, config):
        calls.append("one")
        pg._emit(config, {"event": "log", "data": {"text": "one done"}})
        return {}

    async def n2(state, config):
        if crash["armed"]:
            raise RuntimeError("boom mid-build")
        calls.append("two")
        return {}

    async def n3(state, config):
        calls.append("three")
        return {}

    monkeypatch.setattr(pg, "_NODES", [("one", n1), ("two", n2), ("three", n3)])
    monkeypatch.setattr(pg, "_CHECKPOINT_DB", str(tmp_path / "ckpt.sqlite3"))

    out_dir = str(tmp_path / "myproj")

    # Run 1 — crashes in phase two.
    with pytest.raises(RuntimeError, match="boom"):
        async for _ in pg.run_pipeline_graph(out_dir, {"pages": []}, "desc"):
            pass
    assert calls == ["one"]

    # Run 2 — same project (same thread_id): phase one is checkpointed and
    # must be skipped; two and three run to completion.
    crash["armed"] = False
    events = []
    async for ev in pg.run_pipeline_graph(out_dir, {"pages": []}, "desc"):
        events.append(ev)
    assert calls == ["one", "two", "three"]
    # completion statuses for the resumed phases came through the SSE bridge
    texts = [str(e) for e in events]
    assert any("phase complete: three" in t for t in texts)


@pytest.mark.asyncio
async def test_sse_bridge_forwards_node_events(tmp_path, monkeypatch):
    async def n1(state, config):
        pg._emit(config, {"event": "log", "data": {"text": "hello from node"}})
        return {}

    monkeypatch.setattr(pg, "_NODES", [("only", n1)])
    monkeypatch.setattr(pg, "_CHECKPOINT_DB", str(tmp_path / "ckpt.sqlite3"))

    events = [e async for e in pg.run_pipeline_graph(
        str(tmp_path / "p2"), {}, "d")]
    assert any(e.get("data", {}).get("text") == "hello from node"
               for e in events if isinstance(e, dict))


@pytest.mark.asyncio
async def test_coverage_halt_stops_cleanly(tmp_path, monkeypatch):
    """A _CoverageHalt from a node ends the stream without raising and
    without running later phases — the refusal event is the last word."""
    ran: list[str] = []

    async def refuse(state, config):
        pg._emit(config, {"event": "coverage_verdict", "data": {"status": "out_of_scope"}})
        raise pg._CoverageHalt()

    async def never(state, config):
        ran.append("never")
        return {}

    monkeypatch.setattr(pg, "_NODES", [("gate", refuse), ("later", never)])
    monkeypatch.setattr(pg, "_CHECKPOINT_DB", str(tmp_path / "ckpt.sqlite3"))

    events = [e async for e in pg.run_pipeline_graph(str(tmp_path / "p3"), {}, "d")]
    assert ran == []
    assert any(e.get("event") == "coverage_verdict" for e in events if isinstance(e, dict))
    # the "spine complete" epilogue must NOT be emitted on a refusal
    assert not any("spine complete" in str(e) for e in events)


@pytest.mark.asyncio
async def test_totals_accumulate_across_nodes(tmp_path, monkeypatch):
    """Per-agent cost/turn accounting merges across nodes and lands in the
    final agent_result event (relay parity)."""
    async def a(state, config):
        return {"totals": pg._merge_totals(state, {"cost_usd": 1.0, "num_turns": 2, "duration_ms": 10})}

    async def b(state, config):
        return {"totals": pg._merge_totals(state, {"cost_usd": 0.5, "num_turns": 1, "duration_ms": 5})}

    async def tail(state, config):
        from sse_helpers import sse_event
        totals = state.get("totals") or {}
        pg._emit(config, sse_event("agent_result", {
            "num_turns": totals.get("num_turns", 0),
            "cost_usd": totals.get("cost_usd", 0.0),
            "duration_ms": totals.get("duration_ms", 0)}))
        return {}

    monkeypatch.setattr(pg, "_NODES", [("a", a), ("b", b), ("tail", tail)])
    monkeypatch.setattr(pg, "_CHECKPOINT_DB", str(tmp_path / "ckpt.sqlite3"))

    import json
    events = [e async for e in pg.run_pipeline_graph(str(tmp_path / "p4"), {}, "d")]
    results = [json.loads(e["data"]) if isinstance(e.get("data"), str) else e["data"]
               for e in events if isinstance(e, dict) and e.get("event") == "agent_result"]
    assert results and results[-1]["cost_usd"] == pytest.approx(1.5)
    assert results[-1]["num_turns"] == 3


def test_router_branch_defaults_to_spine():
    """O1: the router branch selects the spine by default for prompt builds
    (flag unset), and FORGE_LANGGRAPH_PIPELINE=0 opts out."""
    import inspect

    import routers.generate as g
    src = inspect.getsource(g._run_relay_pipeline)
    assert 'os.environ.get("FORGE_LANGGRAPH_PIPELINE", "1") != "0"' in src
    assert "figma_context is None" in src
    assert "SCHEMA_MODE_ENABLED" in src


# ── O2: approval gates ───────────────────────────────────────────────────

def test_approval_gates_parsing(monkeypatch):
    monkeypatch.delenv("FORGE_APPROVAL_GATES", raising=False)
    assert pg._approval_gates() == []
    monkeypatch.setenv("FORGE_APPROVAL_GATES", "0")
    assert pg._approval_gates() == []
    monkeypatch.setenv("FORGE_APPROVAL_GATES", "1")
    assert pg._approval_gates() == ["design", "pages"]
    monkeypatch.setenv("FORGE_APPROVAL_GATES", "contracts,pages,nonsense")
    assert pg._approval_gates() == ["contracts", "pages"]


@pytest.mark.asyncio
async def test_gate_pauses_then_resume_completes(tmp_path, monkeypatch):
    """FORGE_APPROVAL_GATES pauses the build BEFORE the gated node and emits
    approval_request; a second drive (the resume endpoint's path) runs the
    gated node and the rest to completion."""
    calls: list[str] = []

    async def n1(state, config):
        calls.append("one")
        return {}

    async def n2(state, config):
        calls.append("two")
        return {}

    async def n3(state, config):
        calls.append("three")
        return {}

    monkeypatch.setattr(pg, "_NODES", [("one", n1), ("two", n2), ("three", n3)])
    monkeypatch.setattr(pg, "_CHECKPOINT_DB", str(tmp_path / "ckpt.sqlite3"))
    monkeypatch.setenv("FORGE_APPROVAL_GATES", "two")

    out_dir = str(tmp_path / "gated")

    events = [e async for e in pg.run_pipeline_graph(out_dir, {"pages": []}, "d")]
    assert calls == ["one"]
    approvals = [e for e in events if isinstance(e, dict) and e.get("event") == "approval_request"]
    assert approvals, f"no approval_request in {events}"
    import json as _json
    payload = _json.loads(approvals[0]["data"]) if isinstance(approvals[0].get("data"), str) else approvals[0]["data"]
    assert payload["phase"] == "two"
    assert not any("spine complete" in str(e) for e in events)

    # Resume — same thread: gated node runs, then the rest.
    events2 = [e async for e in pg.run_pipeline_graph(out_dir, {"pages": []}, "d")]
    assert calls == ["one", "two", "three"]
    assert any("spine complete" in str(e) for e in events2)


def test_resume_endpoint_registered():
    import routers.generate as g
    paths = {getattr(r, "path", "") for r in g.router.routes}
    assert "/api/projects/{project_id}/pipeline/resume" in paths


# ── O4: plan-conditional routing ─────────────────────────────────────────

def test_route_after_pages_by_archetype():
    assert pg._route_after_pages({"plan": {"archetype": "visual-product-search"}}) == "archetype"
    assert pg._route_after_pages({"plan": {}}) == "pages_gate"
    assert pg._route_after_pages({}) == "pages_gate"


def test_parallel_groups_declared():
    assert pg._PARALLEL_AFTER["bootstrap"] == (["maquettes", "discovery", "foundation"], "design")
    assert pg._PARALLEL_AFTER["schema_gate"] == (["workflows", "rules"], "runtime")


def test_full_graph_compiles_with_conditional_edges():
    """The real topology (gates + archetype branch + conditional edges)
    must compile — catches unreachable-node or dangling-edge mistakes."""
    compiled = pg.build_pipeline_graph().compile()
    assert compiled is not None


# ── Agentic loop: ship → heal → re-verify → ship ─────────────────────────

def test_route_after_ship():
    import os
    os.environ.pop("FORGE_HEAL_ROUNDS", None)
    assert pg._route_after_ship({"ship_verdict": "pass"}) == "end"
    assert pg._route_after_ship({}) == "end"
    assert pg._route_after_ship({"ship_verdict": "warn", "heal_rounds": 0}) == "heal"
    assert pg._route_after_ship({"ship_verdict": "block", "heal_rounds": 1}) == "end"
    os.environ["FORGE_HEAL_ROUNDS"] = "0"
    assert pg._route_after_ship({"ship_verdict": "block", "heal_rounds": 0}) == "end"
    os.environ.pop("FORGE_HEAL_ROUNDS", None)


@pytest.mark.asyncio
async def test_heal_loop_converges_then_ends(tmp_path, monkeypatch):
    """Non-pass verdict enters heal; after the repair the re-verdict passes
    and the graph ends. finish_gate re-runs on the loop-back edge."""
    calls: list[str] = []
    world = {"broken": True}

    async def fgate(state, config):
        calls.append("finish_gate")
        return {}

    async def fake_ship(state, config):
        calls.append("ship")
        return {"ship_verdict": "warn" if world["broken"] else "pass"}

    async def fake_heal(state, config):
        calls.append("heal")
        world["broken"] = False
        return {"heal_rounds": int(state.get("heal_rounds") or 0) + 1,
                "quarantine": []}

    monkeypatch.setattr(pg, "_NODES", [("finish_gate", fgate), ("ship", fake_ship)])
    monkeypatch.setattr(pg, "_node_heal", fake_heal)
    monkeypatch.setattr(pg, "_CHECKPOINT_DB", str(tmp_path / "ckpt.sqlite3"))
    monkeypatch.delenv("FORGE_HEAL_ROUNDS", raising=False)

    events = [e async for e in pg.run_pipeline_graph(str(tmp_path / "loop1"), {}, "d")]
    assert calls == ["finish_gate", "ship", "heal", "finish_gate", "ship"]
    assert any("spine complete" in str(e) for e in events)


@pytest.mark.asyncio
async def test_heal_loop_bounded_when_never_converging(tmp_path, monkeypatch):
    """A verdict that never passes still terminates after FORGE_HEAL_ROUNDS."""
    calls: list[str] = []

    async def fgate(state, config):
        calls.append("finish_gate")
        return {}

    async def fake_ship(state, config):
        calls.append("ship")
        return {"ship_verdict": "warn"}

    async def fake_heal(state, config):
        calls.append("heal")
        return {"heal_rounds": int(state.get("heal_rounds") or 0) + 1}

    monkeypatch.setattr(pg, "_NODES", [("finish_gate", fgate), ("ship", fake_ship)])
    monkeypatch.setattr(pg, "_node_heal", fake_heal)
    monkeypatch.setattr(pg, "_CHECKPOINT_DB", str(tmp_path / "ckpt.sqlite3"))
    monkeypatch.setenv("FORGE_HEAL_ROUNDS", "2")

    [e async for e in pg.run_pipeline_graph(str(tmp_path / "loop2"), {}, "d")]
    assert calls == ["finish_gate", "ship",
                     "heal", "finish_gate", "ship",
                     "heal", "finish_gate", "ship"]


@pytest.mark.asyncio
async def test_pass_verdict_skips_heal(tmp_path, monkeypatch):
    calls: list[str] = []

    async def fgate(state, config):
        return {}

    async def fake_ship(state, config):
        calls.append("ship")
        return {"ship_verdict": "pass"}

    async def fake_heal(state, config):
        calls.append("heal")
        return {}

    monkeypatch.setattr(pg, "_NODES", [("finish_gate", fgate), ("ship", fake_ship)])
    monkeypatch.setattr(pg, "_node_heal", fake_heal)
    monkeypatch.setattr(pg, "_CHECKPOINT_DB", str(tmp_path / "ckpt.sqlite3"))
    monkeypatch.delenv("FORGE_HEAL_ROUNDS", raising=False)

    [e async for e in pg.run_pipeline_graph(str(tmp_path / "loop3"), {}, "d")]
    assert calls == ["ship"]


# ── parallel fan-out/join sections ───────────────────────────────────────

@pytest.mark.asyncio
async def test_fanout_members_run_concurrently_and_join_waits(tmp_path, monkeypatch):
    """maquettes/discovery/foundation overlap for real (two-way handshake —
    any sequential order would deadlock), and design starts only after all
    three completed."""
    import asyncio

    done: list[str] = []
    evt_m = asyncio.Event()
    evt_d = asyncio.Event()

    async def boot(state, config):
        done.append("bootstrap")
        return {}

    async def maq(state, config):
        evt_m.set()
        await evt_d.wait()   # needs discovery to be running concurrently
        done.append("maquettes")
        return {}

    async def disc(state, config):
        evt_d.set()
        await evt_m.wait()   # needs maquettes to be running concurrently
        done.append("discovery")
        return {"domain_context": {"domain": "X"}}

    async def found(state, config):
        done.append("foundation")
        return {"plan": {"touched": True}}

    async def design(state, config):
        # Barrier: every member must be finished before design starts.
        assert {"maquettes", "discovery", "foundation"} <= set(done)
        assert state.get("domain_context") == {"domain": "X"}
        assert state.get("plan") == {"touched": True}
        done.append("design")
        return {}

    monkeypatch.setattr(pg, "_NODES", [
        ("bootstrap", boot), ("maquettes", maq), ("discovery", disc),
        ("foundation", found), ("design", design)])
    monkeypatch.setattr(pg, "_CHECKPOINT_DB", str(tmp_path / "ckpt.sqlite3"))

    async def _run():
        return [e async for e in pg.run_pipeline_graph(str(tmp_path / "par1"), {}, "d")]

    await asyncio.wait_for(_run(), timeout=10)
    assert done[-1] == "design"


@pytest.mark.asyncio
async def test_partial_name_match_stays_linear(tmp_path, monkeypatch):
    """A monkeypatched topology that contains 'bootstrap' but not the full
    member window must not get fan-out edges (linear fallback)."""
    calls: list[str] = []

    async def a(state, config):
        calls.append("bootstrap")
        return {}

    async def b(state, config):
        calls.append("other")
        return {}

    monkeypatch.setattr(pg, "_NODES", [("bootstrap", a), ("other", b)])
    monkeypatch.setattr(pg, "_CHECKPOINT_DB", str(tmp_path / "ckpt.sqlite3"))
    [e async for e in pg.run_pipeline_graph(str(tmp_path / "par2"), {}, "d")]
    assert calls == ["bootstrap", "other"]
