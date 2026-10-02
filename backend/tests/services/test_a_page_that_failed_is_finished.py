"""A page the build could not finish is finished by fixing why it failed.

F&B (fxa532bj, 2026-10-01): Edit Category, Edit Menu Item and Orders failed
with "needs a workflow that does not exist yet" and the app shipped without
them. After assembly each unfinished page goes to Smith with the build's
reason, unattended, to fix the cause and write the page; what is still
unfinished is recorded by name.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from services.blueprint import page_repair
from services.smith import plan as plan_mod
from services.smith4.turn import NOBODY_TO_ASK
from tests.services._loop_fixtures import _Chooser, _repo

PAGES = [
    {"id": "PAGE-003", "name": "Edit Category", "route": "/admin/categories/[id]"},
    {"id": "PAGE-007", "name": "Orders", "route": "/admin/orders"},
    {"id": "PAGE-008", "name": "Menu", "route": "/"},
    {"id": "PAGE-009", "name": "Gone", "route": "/gone", "status": "REMOVED"},
]


def _report(**over):
    base = dict(failed=[], failed_because={}, degraded={})
    base.update(over)
    return SimpleNamespace(**base)


class _Svc:
    """The build's service: a document in memory, saved where Smith reads it."""

    def __init__(self, out: Path, doc: dict):
        self.out, self.doc = out, doc
        self.save()

    @property
    def path(self) -> Path:
        return self.out / ".forge" / "blueprint" / "current.json"

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.doc))


def _reload_from(out: Path, monkeypatch):
    from services.blueprint import service
    monkeypatch.setattr(service.BlueprintService, "load", classmethod(
        lambda cls, output_dir: SimpleNamespace(doc=json.loads(
            (Path(output_dir) / ".forge/blueprint/current.json").read_text()))))


def _funnel(doc: dict, _root: str) -> dict:
    """Served = the pages with code."""
    coded = {r["page"] for r in doc.get("pageCode") or []}
    live = [p for p in doc["pages"] if p.get("status") != "REMOVED"]
    missing = sorted(p["route"] for p in live if p["id"] not in coded)
    return {"planned": len(live), "served": len(live) - len(missing), "missing": missing,
            "status": "complete" if not missing else "short"}


def test_the_unfinished_pages_carry_the_builds_own_reason():
    doc = {"pages": PAGES}
    report = _report(failed=["page_code:PAGE-003"],
                     failed_because={"page_code:PAGE-003": "NeedsWorkflow: update a category"},
                     degraded={"page_code:PAGE-007": "NeedsWorkflow: mark an order fulfilled"})
    got = {u["page"]: u for u in page_repair.unfinished_pages(doc, report, missing_routes=["/", "/gone"])}
    assert got["PAGE-003"]["reason"] == "NeedsWorkflow: update a category"
    assert got["PAGE-007"]["reason"] == "NeedsWorkflow: mark an order fulfilled"
    assert "not served" in got["PAGE-008"]["reason"]
    assert "PAGE-009" not in got, "a removed page is not unfinished"


def test_the_ask_names_the_page_the_cause_and_what_done_means():
    ask = page_repair.fault_ask({"page": "PAGE-007", "route": "/admin/orders", "name": "Orders",
                                 "reason": "NeedsWorkflow: mark an order fulfilled"})
    assert "/admin/orders" in ask and "mark an order fulfilled" in ask
    for cause in ("workflow", "step", "field", "rule"):
        assert cause in ask
    assert "try it" in ask and "Nobody is waiting" in ask


def test_each_page_is_repaired_unattended_and_the_count_is_put_right(tmp_path, monkeypatch):
    _reload_from(tmp_path, monkeypatch)
    svc = _Svc(tmp_path, {"pages": PAGES, "pageCode": [{"page": "PAGE-008"}],
                          "runtime": {"pages": {"missing": ["/admin/categories/[id]", "/admin/orders"]},
                                      "issues": [{"kind": "check", "detail": "kept"}]}})
    calls = []

    def smith(project_id, output_dir, message, *, max_steps, unattended):
        calls.append((message, max_steps, unattended))
        doc = json.loads(svc.path.read_text())
        if "Edit Category" in message:              # Smith adds the workflow and writes the page
            doc["pageCode"].append({"page": "PAGE-003"})
        svc.path.write_text(json.dumps(doc))
        return {"answer": "Added Update Category and wrote the page." if "Edit" in message
                else "Could not: the order has no status field to change."}

    out = page_repair.repair_pages(svc, str(tmp_path), str(tmp_path), _report(),
                                   run_turn=smith, funnel=_funnel)
    assert all(u for _m, _s, u in calls), "nobody can answer during a build"
    assert out["fixed"] == ["/admin/categories/[id]"]
    assert [t["route"] for t in out["left"]] == ["/admin/orders"]
    # the second round is told what the first found
    assert len(calls) == 3 and "no status field" in calls[2][0]
    saved = json.loads(svc.path.read_text())
    assert saved["runtime"]["pages"]["missing"] == ["/admin/orders"]
    issues = saved["runtime"]["issues"]
    assert {"kind": "check", "detail": "kept"} in issues
    assert any(i.get("kind") == "page" and i["route"] == "/admin/orders" for i in issues)


def test_nothing_to_finish_runs_no_turn(tmp_path, monkeypatch):
    _reload_from(tmp_path, monkeypatch)
    svc = _Svc(tmp_path, {"pages": PAGES[:1], "pageCode": [{"page": "PAGE-003"}], "runtime": {}})
    out = page_repair.repair_pages(svc, str(tmp_path), str(tmp_path), _report(),
                                   run_turn=lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran")),
                                   funnel=_funnel)
    assert out == {"fixed": [], "left": []}


def test_one_pages_repair_failing_does_not_stop_the_others(tmp_path, monkeypatch):
    _reload_from(tmp_path, monkeypatch)
    svc = _Svc(tmp_path, {"pages": PAGES[:2], "pageCode": [],
                          "runtime": {"pages": {"missing": ["/admin/categories/[id]", "/admin/orders"]}}})
    seen = []

    def smith(project_id, output_dir, message, **k):
        seen.append(message)
        raise RuntimeError("model unavailable")

    out = page_repair.repair_pages(svc, str(tmp_path), str(tmp_path), _report(),
                                   run_turn=smith, funnel=_funnel, rounds=1)
    assert len(seen) == 2 and len(out["left"]) == 2
    assert "model unavailable" in out["left"][0]["reason"]


# --- the unattended turn -----------------------------------------------------

def test_an_unattended_turn_cannot_ask_or_propose_and_is_told_to_act(tmp_path):
    from services.smith4 import handle
    _repo(tmp_path)
    chooser = _Chooser({"tool": "ask_user", "args": {"question": "Which status?"}, "why": ""},
                       {"tool": "propose_plan", "args": {"steps": ["a", "b"]}, "why": ""},
                       {"tool": "answer", "args": {"text": "Could not finish."}, "why": ""})
    out = handle(project_id="p", output_dir=str(tmp_path), message="finish /admin/orders",
                 choose=chooser, unattended=True, max_steps=5)
    refused = [o for o in chooser.seen[-1] if o.said == NOBODY_TO_ASK]
    assert len(refused) == 2
    assert out.status != "asked"


def test_an_unattended_turn_leaves_the_persons_plan_alone(tmp_path):
    from services.smith4 import handle
    _repo(tmp_path)
    plan_mod.remember(tmp_path, ["add a menu", "rename orders"], agreed=False)
    handle(project_id="p", output_dir=str(tmp_path), message="finish /admin/orders",
           choose=_Chooser(), unattended=True, max_steps=2)
    assert plan_mod.peek(tmp_path) == ["add a menu", "rename orders"]


def test_the_build_skips_repair_when_there_is_no_tree(tmp_path):
    from routers.blueprint_generate import _finish_unfinished_pages
    _finish_unfinished_pages(SimpleNamespace(doc={}), str(tmp_path), str(tmp_path / "app"), _report(),
                             lambda *_: None)          # no package.json: returns, never raises


def test_the_repair_keeps_its_own_ledger_so_it_never_looks_idle(tmp_path, monkeypatch):
    from services.run_registry import ledger_snapshot
    _reload_from(tmp_path, monkeypatch)
    svc = _Svc(tmp_path, {"pages": PAGES[:1], "pageCode": [],
                          "runtime": {"pages": {"missing": ["/admin/categories/[id]"]}}})
    during = []

    def smith(project_id, output_dir, message, **k):
        during.append(ledger_snapshot(output_dir))
        return {"answer": "no"}

    page_repair.repair_pages(svc, str(tmp_path), str(tmp_path), _report(), run_turn=smith,
                             funnel=_funnel, rounds=1)
    assert during[0]["active"] and during[0]["stage"] == "page_repair"
    after = ledger_snapshot(str(tmp_path))
    assert after["status"] == "complete" and not after["active"]
    events = [json.loads(l)["event"] for l in next((tmp_path / ".forge/runs").glob("*-page-repair.jsonl")).open()]
    assert events[0] == "run:start" and "observer:unrepaired" in events and events[-1] == "run:end"
