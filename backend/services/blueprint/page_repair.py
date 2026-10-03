"""A page the build could not finish is finished, by fixing why it failed.

F&B's build (fxa532bj, 2026-10-01) planned eleven pages and served eight:
Edit Category, Edit Menu Item and Orders each failed with "needs a workflow
that does not exist yet". The page writer was right — a Save that saves
nothing is worse than no page — and the build's answer was to ship without
them. SnapIT lost two pages the same way the day before. The cause is rarely
the page: a workflow nobody planned, a step a flow lacks, a field the data
model does not have, a rule, an access setting. Writing the page again does
not touch any of those.

So after assembly, when the application exists and can be run, each page that
failed or is not served goes to Smith's loop as a fault: the page, and the
build's own words for why it failed. Smith has every fixer a person's ask
would reach — add or change a workflow and its steps, add a field or a record,
push the schema, change a rule or access — and the trials to prove it. Its
turn ends only when it has written the page and tried it. The turn is
unattended: nobody is there to answer a question, so it decides from the
definition and acts.

Up to `ROUNDS` rounds, one page at a time (each fix changes the definition the
next page is written against). What is still unfinished after that is said by
name — in `runtime.pages` and in the completion message — never shipped as
"built".
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

#: Rounds over the unfinished pages. The second round sees what the first
#: one's fixes made possible (a workflow added for one page serves another).
ROUNDS = 2
#: Steps per page turn: the fix, the page, and the try that proves both.
STEPS = 12


def unfinished_pages(doc: dict, report: Any, missing_routes: list[str] | None = None) -> list[dict]:
    """{page, route, name, reason} for each page the build did not finish:
    its `page_code` failed (the report's reason), or its route is not served."""
    pages = {str(p.get("id")): p for p in doc.get("pages") or []
             if isinstance(p, dict) and str(p.get("status") or "").upper() != "REMOVED"}
    by_route = {str(p.get("route")): pid for pid, p in pages.items()}
    reasons: dict[str, str] = {}
    for source in (getattr(report, "failed_because", None) or {},
                   getattr(report, "degraded", None) or {}):
        for label, why in source.items():
            node, _, subject = str(label).partition(":")
            if node in ("page_code", "page_layouts") and subject in pages:
                reasons.setdefault(subject, str(why or "it failed"))
    for label in getattr(report, "failed", None) or []:
        node, _, subject = str(label).partition(":")
        if node in ("page_code", "page_layouts") and subject in pages:
            reasons.setdefault(subject, "it failed")
    for route in missing_routes or []:
        pid = by_route.get(str(route))
        if pid:
            reasons.setdefault(pid, "nothing composed it, so its address is not served")
    return [{"page": pid, "route": str(pages[pid].get("route") or ""),
             "name": str(pages[pid].get("name") or pages[pid].get("route") or pid),
             "reason": why} for pid, why in reasons.items()]


def fault_ask(item: dict) -> str:
    """What Smith is asked to do about one page."""
    return (
        f"The build could not finish the page {item['name']} ({item['route']}, {item['page']}). "
        f"Why it failed: {item['reason']}\n\n"
        "Find the cause and fix it where it lives — a workflow that is missing or wrong, a step a "
        "flow lacks, how a flow runs, a field or record the data model does not have, a rule, who "
        "may open it. Then write the page so it does everything its definition says, and try it: "
        "open it, and run what its controls run. The page is finished only when it opens and its "
        "actions work. Nobody is waiting to answer questions: decide from the definition and act."
    )


def repair_pages(svc: Any, output_dir: str, *args: Any, **kwargs: Any) -> dict:
    """See `_repair_pages`; its model calls, and the Smith turns it starts, are the build's spend."""
    from services.build_usage import usage_scope
    with usage_scope(agent="page_repair", output_dir=str(output_dir), phase="build", kind="build"):
        return _repair_pages(svc, output_dir, *args, **kwargs)


def _repair_pages(svc: Any, output_dir: str, app_root: str, report: Any, *,
                 emit: Callable[[str, dict], None] | None = None,
                 run_turn: Callable[..., dict] | None = None,
                 funnel: Callable[[dict, str], dict] | None = None,
                 rounds: int = ROUNDS, record: bool = True) -> dict:
    """Finish every page the build did not; returns {fixed, left}. `svc.doc`
    is reloaded from disk after each turn (Smith writes through its own
    service) and `runtime.pages` is recomputed at the end."""
    from services.blueprint.scope import built_view
    if funnel is None:
        from services.blueprint.assembly import page_funnel as funnel
    if run_turn is None:
        from services.smith4.platform import smith_result as run_turn
    say = emit or (lambda _e, _d: None)

    def reload() -> None:
        from services.blueprint.service import BlueprintService
        try:
            svc.doc = BlueprintService.load(output_dir=output_dir).doc
        except Exception:  # noqa: BLE001 — keep the copy we have
            logger.warning("[page-repair] could not reload the Blueprint", exc_info=True)

    missing = list(((svc.doc.get("runtime") or {}).get("pages") or {}).get("missing") or [])
    todo = unfinished_pages(built_view(svc.doc), report, missing)
    if not todo:
        return {"fixed": [], "left": []}
    with _ledger(output_dir if record else None, len(todo)) as ledger:
        return _repair(svc, output_dir, app_root, todo, say=say, run_turn=run_turn, funnel=funnel,
                       rounds=rounds, reload=reload, ledger=ledger)


class _NoLedger:
    def __getattr__(self, _name: str) -> Callable[..., None]:
        return lambda *a, **k: None


class _ledger:
    """The repair's own run ledger, with a pulse. Smith's turns write none,
    and the run's ledger has said `run:end`: without this a repair ten minutes
    long looked idle to the status poll and to the deploy's idle gate."""

    def __init__(self, output_dir: str | None, total: int, *, node: str = "page_repair"):
        self.output_dir, self.total, self.node = output_dir, total, node
        self.ledger: Any = _NoLedger()
        self._stop: Any = None

    def __enter__(self) -> Any:
        if not self.output_dir:
            return self.ledger
        import threading
        from datetime import datetime, timezone
        from services.blueprint.run_ledger import RunLedger
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + self.node.replace("_", "-")
        self.ledger = RunLedger(self.output_dir, run_id, phase="build")
        self.ledger.planned([self.node])
        self.ledger.node_start(self.node, self.total)
        self._stop = threading.Event()

        def pulse() -> None:
            while not self._stop.wait(20):
                self.ledger.heartbeat()
        threading.Thread(target=pulse, daemon=True, name="page-repair-pulse").start()
        return self.ledger

    def __exit__(self, *exc: Any) -> None:
        if self._stop is not None:
            self._stop.set()
            self.ledger.node_done(self.node)
            from types import SimpleNamespace
            self.ledger.finish(SimpleNamespace(completed=[self.node]))


def _repair(svc: Any, output_dir: str, app_root: str, todo: list[dict], *, say: Callable,
            run_turn: Callable, funnel: Callable, rounds: int, reload: Callable, ledger: Any) -> dict:
    from services.blueprint.scope import built_view

    fixed: list[str] = []
    tried: dict[str, str] = {}
    total = len(todo)
    for round_ in range(1, rounds + 1):
        if not todo:
            break
        for i, item in enumerate(todo, 1):
            ledger.repair("page_repair", item["page"], round_, rounds, item["reason"])
            say("message", {"text": f"{item['name']} ({item['route']}) did not build — {item['reason'][:200]} "
                                    "Fixing the cause and writing it again."})
            try:
                out = run_turn("", output_dir, fault_ask(item), max_steps=STEPS, unattended=True)
                tried[item["page"]] = str((out or {}).get("answer") or "")[:400]
            except Exception as exc:  # noqa: BLE001 — one page's repair never ends the build
                logger.warning("[page-repair] %s: %s", item["route"], exc)
                tried[item["page"]] = f"the repair failed: {exc}"[:400]
            reload()
        current = funnel(built_view(svc.doc), app_root)
        still = set(current.get("missing") or [])
        coded = {str(r.get("page")) for r in svc.doc.get("pageCode") or [] if isinstance(r, dict)}
        next_todo = []
        for item in todo:
            if item["route"] in still or item["page"] not in coded:
                next_todo.append({**item, "reason": (f"{item['reason']} — after a repair it is still not "
                                                     f"finished: {tried.get(item['page']) or 'no answer'}")})
            else:
                fixed.append(item["route"])
                ledger.node_subject("page_repair", item["page"], len(fixed), total, True)
        logger.info("[page-repair] round %d: %d fixed, %d left", round_, len(todo) - len(next_todo),
                    len(next_todo))
        todo = next_todo

    for t in todo:
        ledger.unrepaired("page_repair", t["page"], t["reason"])
    runtime = dict(svc.doc.get("runtime") or {})
    runtime["pages"] = funnel(built_view(svc.doc), app_root)
    # What is still unfinished is an issue of the application, said with the
    # build's reason and what the repair found — the shape `build_repair`
    # records, in the section the contract declares for it.
    issues = [i for i in runtime.get("issues") or []
              if not (isinstance(i, dict) and i.get("kind") == "page")]
    issues += [{"kind": "page", "page": t["page"], "route": t["route"], "detail": t["reason"][:600]}
               for t in todo]
    runtime["issues"] = issues
    svc.doc["runtime"] = runtime
    svc.save()
    return {"fixed": fixed, "left": todo}
