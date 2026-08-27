"""Slices 2+3: repair routing + validate→repair loop control (browser-free via
injected validate/repair/sweep/fix_agent)."""
from services.repair_dispatcher import dispatch_repairs
from services.validate_repair_loop import validate_and_repair

# ---- Slice 2: dispatch_repairs routing --------------------------------------

def test_deterministic_findings_trigger_one_sweep():
    calls = {"n": 0}
    def sweep(app): calls["n"] += 1; return 5
    r = dispatch_repairs("app", [
        {"type": "route_404", "route": "/x"},
        {"type": "dead_button", "route": "/y", "buttonLabel": "Approve"},
    ], sweep=sweep)
    assert calls["n"] == 1            # one sweep fixes all deterministic findings
    assert r["deterministic_fixed"] == 5 and r["made_progress"] is True

def test_sweep_runs_for_render_errors_too():
    # The deterministic guards often resolve the schema cause behind a render_error,
    # so the sweep runs on ANY findings (not only classic dead-button/404 ones).
    calls = {"n": 0}
    def sweep(app): calls["n"] += 1; return 0
    dispatch_repairs("app", [{"type": "render_error", "route": "/z", "detail": "boom"}], sweep=sweep)
    assert calls["n"] == 1


def test_no_sweep_when_no_findings():
    calls = {"n": 0}
    def sweep(app): calls["n"] += 1; return 0
    r = dispatch_repairs("app", [], sweep=sweep)
    assert calls["n"] == 0 and r["made_progress"] is False

def test_render_errors_routed_to_fix_agent_grouped_by_route():
    seen = []
    def agent(app, route, errs): seen.append(route); return True
    r = dispatch_repairs("app", [
        {"type": "render_error", "route": "/a", "detail": "1"},
        {"type": "render_error", "route": "/a", "detail": "2"},
        {"type": "render_error", "route": "/b", "detail": "3"},
    ], sweep=lambda a: 0, fix_agent=agent)
    assert sorted(seen) == ["/a", "/b"]      # grouped by route, one call each
    assert set(r["agent_routes"]) == {"/a", "/b"}

def test_render_errors_unhandled_when_no_agent():
    r = dispatch_repairs("app", [{"type": "render_error", "route": "/a", "detail": "x"}],
                         sweep=lambda a: 0, fix_agent=None)
    assert r["made_progress"] is False and len(r["unhandled"]) == 1

# ---- Slice 3: loop control ---------------------------------------------------

def test_loop_stops_when_clean():
    seq = [[{"type": "route_404", "route": "/x"}], []]   # dirty then clean
    it = iter(seq)
    out = validate_and_repair("app", validate=lambda a: next(it),
                              repair=lambda a, f: {"made_progress": True})
    assert out["clean"] is True and out["stopped"] == "clean"
    assert [r["round"] for r in out["rounds"]] == [1, 2]

def test_loop_stops_on_no_progress():
    out = validate_and_repair("app",
        validate=lambda a: [{"type": "render_error", "route": "/a", "detail": "x"}],
        repair=lambda a, f: {"made_progress": False})
    assert out["clean"] is False and out["stopped"] == "no_progress"
    assert len(out["rounds"]) == 1

def test_loop_stops_on_thrash_identical_findings():
    same = [{"type": "route_404", "route": "/x"}]
    out = validate_and_repair("app", validate=lambda a: list(same),
                              repair=lambda a, f: {"made_progress": True}, max_rounds=5)
    # round1 dirty→repair, round2 identical→stop
    assert out["stopped"] == "no_change" and len(out["rounds"]) == 2

def test_loop_respects_max_rounds():
    # always dirty + always "progress" → capped at max_rounds with changing findings
    n = {"i": 0}
    def validate(a):
        n["i"] += 1
        return [{"type": "dead_button", "route": f"/p{n['i']}", "buttonLabel": "x"}]
    out = validate_and_repair("app", validate=validate,
                              repair=lambda a, f: {"made_progress": True}, max_rounds=3)
    assert out["stopped"] == "max_rounds" and len(out["rounds"]) == 3
