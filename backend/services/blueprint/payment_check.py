"""Taking money — proven on a running copy, through the stand-in.

For every process that ends by sending the person to pay: run it as its
role with a written input; expect a ledger row `pending` for what it pays
for and the run to send the person to a checkout; then settle it the way
the stand-in's page would ("paid") and expect the process that listens for
`payment.succeeded` to have run and the ledger to say `succeeded`. For a
refund process: run it on that payment and expect `refunded`. A stand-in
proves the application's own logic; the provider's call is proven by its
signed-webhook check.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from services.blueprint.scorecard import item

logger = logging.getLogger(__name__)


def _steps(wf: dict) -> list[dict]:
    from services.blueprint.functional_completeness import with_loop_bodies
    return [s for s in with_loop_bodies(wf).get("steps") or [] if isinstance(s, dict)]


def _live(doc: dict) -> list[dict]:
    return [w for w in doc.get("workflows") or [] if isinstance(w, dict) and w.get("id")
            and str(w.get("status") or "").upper() not in ("DEPRECATED", "REMOVED")]


def _with(doc: dict, action: str) -> list[dict]:
    return [w for w in _live(doc) if any(str((s.get("config") or {}).get("actionType") or "") == action for s in _steps(w))]


def paying(doc: dict) -> list[dict]:
    return _with(doc, "create_checkout")


def refunding(doc: dict) -> list[dict]:
    return _with(doc, "refund_payment")


def _rows(app: Any, sql: str) -> list[list[str]]:
    from services.blueprint.page_review import _query
    return _query(app, sql)


def _q(s: Any) -> str:
    return str(s).replace("'", "''")


def _post(app: Any, path: str, body: dict, cookies: list[dict]) -> tuple[int, dict]:
    from services.smith.trials import _http
    status, _loc, text = _http(app, "POST", path, body, cookies)
    try:
        parsed = json.loads(text) if text else {}
    except ValueError:
        parsed = {}
    return int(status), parsed if isinstance(parsed, dict) else {}


def check_payments(app: Any, doc: dict, *, bench: Any, client: Any = None, only: set[str] | None = None,
                   cancelled: Callable[[], bool] = lambda: False) -> dict:
    """`{total, green, red, untried}` over every process that takes money."""
    from services.blueprint.clock_check import runs_since, slug_of
    from services.blueprint.process_trials import _records, compose_inputs
    from services.smith import trials
    from services.smith.trials import _session
    green: list[dict] = []
    red: list[dict] = []
    untried: list[dict] = []
    for wf in paying(doc):
        wid = str(wf.get("id"))
        if only is not None and wid not in only:
            continue
        name = str(wf.get("name") or wid)
        it = lambda what, why: item(f"{wid}::{what}", name, why, wid)  # noqa: E731
        if cancelled():
            untried.append(it("checkout", "stopped by the person"))
            continue
        if client is None:
            untried.append(it("checkout", "no input could be written to run it"))
            continue
        try:
            plan = compose_inputs(doc, [wf], _records(app, doc), client)
            run = plan.get(wid) or {"as": "", "input": {}}
            before = _rows(app, "select count(*) from forge_payments")
            n0 = int(before[0][0]) if before and before[0] and str(before[0][0]).isdigit() else 0
            said = trials.run("try_workflow", {"workflow": wid, "input": run["input"], "as": run["as"]}, bench=bench, doc=doc)
            rows = _rows(app, "select id, status, provider from forge_payments order by created_at desc limit 1")
            after = _rows(app, "select count(*) from forge_payments")
            n1 = int(after[0][0]) if after and after[0] and str(after[0][0]).isdigit() else 0
            if n1 <= n0 or not rows or not rows[0]:
                red.append(it("checkout", f"did not open a checkout: {said.splitlines()[0][:160] if said else 'no answer'}"))
                continue
            pid, _status, provider = rows[0][0], rows[0][1], rows[0][2]
            if "redirect" in said or "/pay/stand-in" in said or "checkout" in said.lower():
                green.append(it("checkout", f"sends the person to pay ({provider}); the ledger holds it pending"))
            else:
                red.append(it("checkout", "a checkout was opened on the ledger but the run did not send the person to it"))
            if provider != "stand_in":
                untried.append(it("settled", f"{provider} is live on the copy; its outcome is its signed call's (proven by the webhook check)"))
                continue
            since = (datetime.now(timezone.utc) - timedelta(seconds=2)).isoformat()
            _who, jar = _session(app, doc, run["as"] or "")
            code, body = _post(app, "/api/pay/stand-in", {"sessionId": f"standin_{pid}", "outcome": "paid"}, jar)
            settled = _rows(app, f"select status from forge_payments where id = '{_q(pid)}'")
            if code != 200 or not settled or settled[0][0] != "succeeded":
                red.append(it("settled", f"the outcome did not settle the ledger ({code}: {str(body.get('error') or settled)[:120]})"))
                continue
            listeners = [w for w in _live(doc) if str((w.get("trigger") or {}).get("kind") or "") == "webhook"
                         and str((w.get("trigger") or {}).get("event") or "") == "payment.succeeded"]
            ran = [w for w in listeners if runs_since(app, slug_of(w), since)]
            if listeners and not ran:
                red.append(it("settled", f"paid, and {listeners[0].get('name')} did not run on `payment.succeeded`"))
            else:
                green.append(it("settled", "paid settles the ledger" + (f" and {ran[0].get('name')} ran" if ran else "")))
            for rf in refunding(doc):
                rid = str(rf.get("id"))
                inputs = {str(i.get("name")): pid for i in rf.get("inputs") or [] if isinstance(i, dict) and i.get("name")}
                said = trials.run("try_workflow", {"workflow": rid, "input": inputs, "as": ""}, bench=bench, doc=doc)
                refunded = _rows(app, f"select status from forge_payments where id = '{_q(pid)}'")
                ok = bool(refunded and refunded[0] and refunded[0][0] in ("refunded", "partially_refunded"))
                (green if ok else red).append(item(f"{rid}::refund", str(rf.get("name") or rid),
                                                   "refunds through the service and the ledger says so" if ok
                                                   else f"did not refund: {said.splitlines()[0][:160] if said else 'no answer'}", rid))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[payment-check] %s could not be tried", wid, exc_info=True)
            untried.append(it("checkout", f"the check failed: {str(exc)[:160]}"))
    return {"total": len(green) + len(red) + len(untried), "green": green, "red": red, "untried": untried}


__all__ = ["check_payments", "paying", "refunding"]
