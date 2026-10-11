"""Runs on time and talks to the outside — proven on a running copy.

Three things a process can be driven by that no person presses: the clock
(`schedule`), a record's change (`db_change`) and another system's call
(`api_event`, `webhook`); and one thing a process can do that outlives the
request: `wait`. None of them was proven before 2026-10-12 — the tick was
behind the sign-in gate, a `db_change` projected to nothing the bus read,
and a wait of "1 hour" waited zero.

Each is proven the way it happens: a schedule is fired through the tick
(`?workflow=&force=1`); an event is put on the app's own bus and the tick
dispatches it; a wait is reached by running the process, then the tick is
asked what the clock does at the wait's due time (`?at=`). Green is a run
that started, and a wait that ended. A tick the check cannot reach (no
route, a key it does not hold) is `untried`, never red.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode

from services.blueprint.scorecard import item

logger = logging.getLogger(__name__)

CLOCKED_KINDS = ("schedule", "db_change", "api_event", "webhook")
WAIT_TASKS = ("wait_timer", "wait_for_event")


def _live(doc: dict) -> list[dict]:
    return [w for w in doc.get("workflows") or []
            if isinstance(w, dict) and w.get("id")
            and str(w.get("status") or "").upper() not in ("DEPRECATED", "REMOVED")]


def _steps(wf: dict) -> list[dict]:
    from services.blueprint.functional_completeness import with_loop_bodies
    return [s for s in with_loop_bodies(wf).get("steps") or [] if isinstance(s, dict)]


def waits(wf: dict) -> list[dict]:
    """The steps of `wf` the clock has to end."""
    out = []
    for s in _steps(wf):
        cfg = s.get("config") if isinstance(s.get("config"), dict) else {}
        if str(s.get("type") or "") == "wait" or str(cfg.get("actionType") or "") == "wait_for_event":
            out.append(s)
    return out


def kind_of(wf: dict) -> str:
    return str((wf.get("trigger") or {}).get("kind") or "manual")


def clocked(doc: dict) -> list[dict]:
    """The processes this criterion is about."""
    return [w for w in _live(doc) if kind_of(w) in CLOCKED_KINDS or waits(w)]


def slug_of(wf: dict) -> str:
    """The definition id the runtime logs under — as `project_workflows` names it."""
    from services.blueprint.projection import to_snake
    return to_snake(str(wf.get("name") or wf.get("id") or "workflow")).replace("_", "-")


def cron_secret(app_root: str | Path) -> str:
    from services.blueprint.assembly import existing_secrets
    return existing_secrets(app_root).get("CRON_SECRET", "")


def tick(app: Any, app_root: str | Path, **params: Any) -> tuple[int, dict]:
    """`(status, body)` of one tick, with the app's own key."""
    from services.smith.trials import _http
    query = {k: str(v) for k, v in params.items() if v not in (None, "")}
    secret = cron_secret(app_root)
    if secret:
        query["secret"] = secret
    status, _where, body = _http(app, "GET", "/api/cron/tick" + (f"?{urlencode(query)}" if query else ""), None, [])
    try:
        parsed = json.loads(body) if body else {}
    except ValueError:
        parsed = {}
    return int(status), parsed if isinstance(parsed, dict) else {}


def _q(text: str) -> str:
    return str(text).replace("'", "''")


def _rows(app: Any, sql: str) -> list[list[str]]:
    from services.blueprint.page_review import _query
    return _query(app, sql)


def _count(app: Any, sql: str) -> int:
    rows = _rows(app, sql)
    try:
        return int(rows[0][0])
    except (IndexError, ValueError, TypeError):
        return 0


def runs_since(app: Any, slug: str, since: str) -> int:
    return _count(app, f"select count(*) from workflow_execution_log where workflow_id = '{_q(slug)}' "
                       f"and created_at >= '{_q(since)}'")


def put_event(app: Any, event: str) -> None:
    """One event on the app's own bus, as the data engine would put it."""
    entity = event.split(".", 1)[0]
    _rows(app, f"insert into forge_events (type, entity, entity_id, payload) values "
               f"('{_q(event)}', '{_q(entity)}', 'clock-check', '{{}}'::jsonb)")


def pending_wait(app: Any, slug: str) -> dict | None:
    rows = _rows(app, f"select id, task_type, due_at from workflow_tasks where workflow_id = '{_q(slug)}' "
                      f"and status = 'pending' and task_type in ('wait_timer', 'wait_for_event') "
                      f"order by created_at desc limit 1")
    if not rows or len(rows[0]) < 3:
        return None
    return {"id": rows[0][0], "type": rows[0][1], "due": rows[0][2]}


def task_status(app: Any, task_id: str) -> str:
    rows = _rows(app, f"select status from workflow_tasks where id = '{_q(task_id)}'")
    return rows[0][0] if rows and rows[0] else ""


def _after(due: str) -> str:
    """A minute past `due`, as the tick's `at`."""
    text = str(due or "").strip().replace(" ", "T")
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        when = datetime.now(timezone.utc)
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (when + timedelta(minutes=1)).isoformat()


def check_clock(app: Any, doc: dict, *, bench: Any, app_root: str | Path, client: Any = None,
                only: set[str] | None = None, cancelled: Callable[[], bool] = lambda: False) -> dict:
    """`{total, green, red, untried}` over every clocked process."""
    from services.blueprint.projection import _trigger_contract
    green: list[dict] = []
    red: list[dict] = []
    untried: list[dict] = []
    for wf in clocked(doc):
        wid = str(wf.get("id"))
        if only is not None and wid not in only:
            continue
        name = str(wf.get("name") or wid)
        it = lambda what, why: item(f"{wid}::{what}", name, why, wid)  # noqa: E731
        if cancelled():
            untried.append(it("trigger", "stopped by the person"))
            continue
        kind = kind_of(wf)
        slug = slug_of(wf)
        since = (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat()
        started = False
        said = ""
        try:
            if kind == "schedule":
                status, body = tick(app, app_root, workflow=wid, force="1")
                if status == 401:
                    untried.append(it("trigger", "the tick refused the check's key"))
                    continue
                if status == 404:
                    untried.append(it("trigger", "the app has no tick route"))
                    continue
                forced = body.get("forced") if isinstance(body.get("forced"), dict) else {}
                if not forced.get("fired"):
                    red.append(it("trigger", f"the clock could not start it: {forced.get('reason') or 'the tick did not answer'}"))
                elif runs_since(app, slug, since):
                    green.append(it("trigger", "fires when its time comes"))
                    started = True
                else:
                    red.append(it("trigger", "the tick fired it and no step ran"))
            elif kind in ("db_change", "api_event", "webhook"):
                contract = _trigger_contract(doc, wf)
                if not contract or contract.get("kind") != "event":
                    red.append(it("trigger", "its trigger names no event the app's bus carries"))
                    continue
                event = str(contract["event"])
                put_event(app, event)
                status, body = tick(app, app_root)
                if status == 401:
                    untried.append(it("trigger", "the tick refused the check's key"))
                    continue
                if status == 404:
                    untried.append(it("trigger", "the app has no tick route"))
                    continue
                if runs_since(app, slug, since):
                    green.append(it("trigger", f"starts when `{event}` happens"))
                    started = True
                else:
                    red.append(it("trigger", f"`{event}` reached the bus and started nothing"))
            else:
                if client is None:
                    untried.append(it("wait", "no input could be written to run it"))
                    continue
                from services.blueprint.process_trials import _records, compose_inputs
                from services.smith import trials
                plan = compose_inputs(doc, [wf], _records(app, doc), client)
                run = plan.get(wid) or {"as": "", "input": {}}
                said = trials.run("try_workflow", {"workflow": wid, "input": run["input"], "as": run["as"]},
                                  bench=bench, doc=doc)
                started = True
            if waits(wf) and started:
                task = pending_wait(app, slug)
                if task is None:
                    red.append(it("wait", "did not pause at its wait" + (f": {said[:160]}" if said else "")))
                    continue
                status, _body = tick(app, app_root, at=_after(task["due"]))
                if status in (401, 404):
                    untried.append(it("wait", "the tick could not be asked to move the clock"))
                    continue
                if task_status(app, task["id"]) == "completed":
                    green.append(it("wait", "pauses at its wait and the clock picks it up"))
                else:
                    red.append(it("wait", "its wait never ended when the time came"))
        except Exception as exc:  # noqa: BLE001 — the check's own shortfall
            logger.warning("[clock-check] %s could not be tried", wid, exc_info=True)
            untried.append(it("trigger", f"the check failed: {str(exc)[:160]}"))
    return {"total": len(green) + len(red) + len(untried), "green": green, "red": red, "untried": untried}


__all__ = ["CLOCKED_KINDS", "check_clock", "clocked", "kind_of", "slug_of", "tick", "waits"]
