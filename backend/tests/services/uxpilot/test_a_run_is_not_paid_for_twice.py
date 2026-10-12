"""A UX Pilot run is paid for once per brief, whatever it returns, and one project never waits for another.

Review of 3057b929: the cached drawings were reused only when EVERY page of the batch had one. If UX Pilot
drew N-1 screens, a title failed to match, or the run failed, nothing was recorded for the page that missed,
so every later page writer started another paid `start_design_agent` run (two pages, four lookups: four runs
where one is expected; a twelve-page application could pay for twelve). The lock was one for the whole
process, so projects on the same backend waited behind each other for the length of a run."""
from __future__ import annotations

import concurrent.futures
import json
import re
import threading
import time

import pytest

from services.uxpilot import generate as g
from tests.services.uxpilot.test_uxpilot_react_reference import HTML, _doc


class Gateway:
    """UX Pilot's design agent. `draw` says which of the asked-for screens it actually draws."""
    may_generate = True

    def __init__(self, draw=None, fail=None, slow=0.0):
        self.calls, self.draw, self.fail, self.slow, self._titles = [], draw, fail, slow, []

    async def call(self, tool, **kw):
        if tool == "start_design_agent":
            self.calls.append(tool)                       # the call that spends credits
            self._titles = re.findall(r'=== Screen "([^"]+)"', kw["prompt"])
            if self.slow:
                time.sleep(self.slow)
        if self.fail:
            raise self.fail
        if tool == "start_design_agent":
            body = {"agentJobId": "job_1", "status": "queued"}
        elif tool == "get_agent_job":
            titles = self._titles if self.draw is None else [t for t in self._titles if t in self.draw]
            body = {"status": "completed", "screens": [
                {"designId": f"dsg_{i}", "title": f"App - {t}", "previewUrl": "https://ux/p.png"}
                for i, t in enumerate(titles, 1)]}
        else:
            body = {"design": {"id": kw.get("design"), "html": HTML}}
        return [{"type": "text", "text": json.dumps(body)}]


def _lookups(doc, tmp_path, gw, times=2):
    """What the page writers do: each page asks, several times over, as a rebuild or a retry would."""
    said = []
    for page in doc["pages"] * times:
        ref, why = g.reference_for(doc, page, tmp_path, gateway=gw)
        said.append((ref is not None, why))
    return said


def test_a_screen_uxpilot_did_not_draw_does_not_start_another_run(tmp_path):
    doc = _doc()
    first, second = (p["name"] for p in doc["pages"][:2])
    gw = Gateway(draw=[first])                            # N-1 screens: the second page is not drawn
    said = _lookups(doc, tmp_path, gw)                    # 2 pages, 4 lookups
    assert gw.calls == ["start_design_agent"], f"{len(gw.calls)} paid runs where 1 is expected"
    assert [ok for ok, _ in said] == [True, False, True, False]
    assert "drew no screen" in said[1][1]


def test_a_failed_run_is_not_repeated_for_every_page(tmp_path):
    doc = _doc()
    gw = Gateway(fail=RuntimeError("provider down"))
    said = _lookups(doc, tmp_path, gw)
    assert len(gw.calls) == 1, f"{len(gw.calls)} paid runs where 1 is expected"
    assert all(not ok for ok, _ in said) and all("provider down" in why for _ok, why in said)


def test_a_title_that_does_not_match_is_a_miss_recorded_once(tmp_path):
    doc = _doc()

    class Renamed(Gateway):
        async def call(self, tool, **kw):
            out = await super().call(tool, **kw)
            return [{"type": "text", "text": t["text"].replace("App - ", "Totally different - ")}
                    for t in out] if tool == "get_agent_job" else out

    gw = Renamed()
    _lookups(doc, tmp_path, gw)
    assert len(gw.calls) == 1


def test_a_recorded_miss_is_tried_again_after_the_ttl(tmp_path, monkeypatch):
    doc = _doc()
    gw = Gateway(fail=RuntimeError("provider down"))
    _lookups(doc, tmp_path, gw, times=1)
    assert len(gw.calls) == 1
    # two hours later: the recorded misses are older than the time they are believed for
    from datetime import datetime, timedelta, timezone
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="seconds")
    for page in doc["pages"]:
        entry = g.ledger_entry(tmp_path, page["id"])
        g._record(tmp_path, page["id"], {**entry, "generatedAt": old})
    _lookups(doc, tmp_path, gw, times=1)
    assert len(gw.calls) == 2, "a rebuild after a while tries again, once, not once per page"


def test_drawings_are_still_read_from_the_ledger_and_cost_nothing(tmp_path):
    doc = _doc()
    gw = Gateway()
    _lookups(doc, tmp_path, gw, times=3)
    assert len(gw.calls) == 1


def test_projects_do_not_wait_for_each_other(tmp_path):
    """A run holds its own project's lock only: two projects draw side by side."""
    a, b = tmp_path / "a", tmp_path / "b"
    assert g._app_lock_for(a) is not g._app_lock_for(b)
    assert g._app_lock_for(a) is g._app_lock_for(a), "one lock per project, however it is spelled"
    assert g._app_lock_for(a) is g._app_lock_for(a / ".." / "a")

    doc = _doc()
    inside, overlap = [], []
    lock = threading.Lock()

    class Slow(Gateway):
        async def call(self, tool, **kw):
            if tool == "start_design_agent":
                with lock:
                    inside.append(1)
                    overlap.append(len(inside))
                time.sleep(0.3)
                with lock:
                    inside.pop()
            return await super().call(tool, **kw)

    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(g.reference_for, doc, doc["pages"][0], d, gateway=Slow()) for d in (a, b)]
        for f in futures:
            f.result()
    assert max(overlap) == 2, "both projects were drawing at the same time"


@pytest.mark.parametrize("names,page,screens,expected", [
    # an exact title wins wherever it is in the list
    (["Task", "Task Detail"], "Task", ["Task Detail", "Task"], "Task"),
    # a page called Task is not given the screen drawn for its longer sibling
    (["Task", "Task Detail"], "Task", ["Task Detail"], None),
    # and Task Detail still finds its own
    (["Task", "Task Detail"], "Task Detail", ["Task Detail"], "Task Detail"),
    # a partial match with nobody else claiming the screen is still accepted
    (["Tasks"], "Tasks", ["App - Tasks board"], "App - Tasks board"),
])
def test_a_screen_goes_to_the_page_it_was_drawn_for(names, page, screens, expected):
    pages = [{"id": f"P{i}", "name": n} for i, n in enumerate(names)]
    me = next(p for p in pages if p["name"] == page)
    shown = [{"designId": f"d{i}", "title": t} for i, t in enumerate(screens)]
    found = g._screen_for(me, shown, set(), [p["name"] for p in pages if p is not me])
    assert (found["title"] if found else None) == expected
