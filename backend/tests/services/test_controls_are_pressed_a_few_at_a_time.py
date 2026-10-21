"""Controls are pressed a few at a time, and a control that looked broken is
pressed again alone, so parallel presses never make a working one read as
broken. A Smith turn on Personal Finance spent 56 of 72 minutes pressing
controls one at a time (u8w3uw4j, 2026-10-21).

Measured on forge-v3's backend against a slow test app (9 controls: links, a
change, a process, a failing process, a dead button, an option already
chosen): verdicts identical serial and parallel, 90 s → 64 s; links only,
24 s → 15 s."""
from pathlib import Path

SHOTS = (Path(__file__).resolve().parents[2] / "scripts" / "page_shots.mjs").read_text()


def test_presses_run_a_few_at_a_time():
    assert "const PRESS_PARALLEL = Math.max(1, Number(cfg.pressParallel ?? 3) || 1);" in SHOTS
    assert "await inTurns(picked, PRESS_PARALLEL, (c) => press(who.ctx, url, c))" in SHOTS


def test_only_what_worked_is_taken_from_the_parallel_round():
    assert 'const WORKED = new Set(["navigated", "changed", "workflow", "refused"]);' in SHOTS
    assert "if (first[k] && WORKED.has(first[k].outcome))" in SHOTS


def test_what_looked_broken_is_pressed_again_alone():
    # An error is pressed again alone; "nothing" is the first of its two presses.
    assert 'first[k]?.outcome === "nothing" ? first[k] : await press(who.ctx, url, c)' in SHOTS
    assert 'if (outcome.outcome === "nothing") outcome = await press(who.ctx, url, c);' in SHOTS
