"""Smith's eyes: `open_page` with `look: true` (2026-10-31).

What a person met on DITANS and no check could see — the arrow over every
drawn control, filter chips that did nothing, the account menu cut off by the
bar that holds it — is measured in the browser from React's own handlers and
the boxes drawn, and said to Smith as lines marked ✗.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from services.smith import trials
from services.smith.trials import look_lines

BACKEND = Path(__file__).resolve().parents[2]
FIXTURES = BACKEND / "tests/fixtures/look"


def _measure(html: Path) -> dict:
    from services.blueprint.page_review import ReviewUnavailable, _playwright_modules
    try:
        modules = _playwright_modules()
    except ReviewUnavailable:
        pytest.skip("Playwright is not installed here")
    if not shutil.which("node"):
        pytest.skip("node is not installed here")
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "node_modules").symlink_to(modules)
        shutil.copyfile(FIXTURES / "measure.mjs", work / "measure.mjs")
        env = dict(os.environ)
        cache = Path.home() / "Library/Caches/ms-playwright"
        if cache.is_dir():
            env.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(cache))
        proc = subprocess.run(["node", str(work / "measure.mjs"), str(BACKEND / "scripts/page_shots.mjs"), str(html)],
                              cwd=work, capture_output=True, text=True, timeout=120, env=env)
    if proc.returncode:
        pytest.skip(f"the browser could not run here: {proc.stderr[-300:]}")
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_the_browser_measures_what_a_person_meets():
    seen = _measure(FIXTURES / "clipped_menu.html")
    measured = seen["measured"]
    # A control React handles, showing the arrow, in the frame (outside <main>).
    assert {"label": "A Admin", "where": "frame", "n": 1} in measured["noHand"]
    # Drawn as a filter chip; nothing handles a press.
    assert [d["label"] for d in measured["drawnDead"]] == ["Remote only"]
    # Shows the hand; nothing handles a press.
    assert [d["label"] for d in measured["dead"]] == ["Looks pressable"]
    # The account menu opens under the 72px bar that clips it.
    opened = seen["opened"][0]
    assert opened["text"].startswith("Profile")
    assert opened["shown"] < 50 and "Top bar" in opened["clippedBy"]


def test_what_was_measured_is_said_as_findings():
    lines = look_lines({
        "noHand": [{"label": "Find talent", "where": "frame", "n": 1}, {"label": "Save", "where": "page", "n": 3}],
        "drawnDead": [{"label": "Remote only", "where": "page", "layer": "Filter chip", "n": 2}],
        "dead": [],
        "opened": [{"opener": "A Admin", "where": "frame", "text": "Profile Sign out", "shown": 18,
                    "clippedBy": "<div \"Top bar\" class=\"h-[72px] overflow-hidden\">", "coveredBy": ""}],
        "wider": 0,
    })
    text = "\n".join(lines)
    assert "4 pressable thing(s) show the arrow" in text and '"Find talent" (frame)' in text and '"Save" ×3' in text
    assert 'drawn as "Filter chip"' in text and '"Remote only" ×2' in text
    assert "only 18% of it shows" in text and "overflow-hidden" in text
    assert text.count(trials.CHECK_RED) == 3


def test_a_screen_with_nothing_wrong_says_so():
    lines = look_lines({"noHand": [], "dead": [], "drawnDead": [], "opened": [
        {"opener": "Bell", "where": "frame", "text": "Nothing yet", "shown": 100, "clippedBy": "", "coveredBy": ""}],
        "wider": 0})
    assert lines[-1].strip().startswith("✓ nothing measured is wrong") and "1 panel(s)" in lines[-1]


def test_open_page_offers_the_look():
    said, args = next((d, a) for n, d, a in trials.TRIALS if n == "open_page")
    assert args.get("look") == "boolean" and "EYES" in said


def test_the_rules_say_when_to_look_where_to_fix_and_whom_to_tell():
    from services.smith import tools
    from services.smith.loop import _RULES
    for said in ("`look: true`", "ONE CAUSE, ONE PLACE", "`edit_pages` with `having`", "`bind_menu`",
                 "`run_checks` with\n  `workflows`", "`translate_words`", "`report_platform_fault`"):
        assert said in _RULES, said
    rendered = tools.render()
    for name in ("edit_pages", "bind_menu", "translate_words", "report_platform_fault"):
        assert f"`{name}`" in rendered
