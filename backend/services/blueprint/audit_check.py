"""Every change is on the record — proven on a running copy.

As the administrator, one record of a record type that has rows is
changed through the data API (a field set to the value it already has:
nothing moves, the trail still fills), and the trail is read back: the
row is there, with the actor and the action. Then the trail is attacked
with SQL (`UPDATE`, `DELETE`) and must refuse; the chain is verified; the
audit API is asked as a reviewer and as somebody else; the export is
fetched and is itself on the record. An application declaring no trail
has nothing to prove here (0 of 0).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Callable

from services.blueprint.scorecard import item

logger = logging.getLogger(__name__)


def policy(doc: dict) -> dict:
    from services.blueprint.projection import audit_policy
    return audit_policy(doc)


def _http(app: Any, method: str, path: str, body: Any, cookies: list[dict], headers: dict | None = None) -> tuple[int, str, str]:
    from services.smith.trials import _http as raw
    return raw(app, method, path, body, cookies)


def _rows(app: Any, sql: str) -> list[list[str]]:
    from services.blueprint.page_review import _query
    return _query(app, sql)


def _q(s: Any) -> str:
    return str(s).replace("'", "''")


def _first_record(app: Any, doc: dict) -> tuple[dict, str, str, dict] | None:
    """`(entity, slug, id, row)` of one row of a record type with rows."""
    from services.blueprint.process_trials import _records
    records = _records(app, doc)
    entities = {str(e.get("name")): e for e in (doc.get("data") or {}).get("entities") or [] if isinstance(e, dict)}
    for name, rows in records.items():
        ent = entities.get(name)
        if ent is None or not rows or str(ent.get("appendOnly") or "") == "True":
            continue
        from services.blueprint.projection import to_snake
        slug = to_snake(str(ent.get("name") or "")).replace("_", "-")
        rid = str(rows[0].get("id") or "")
        if rid:
            return ent, slug, rid, rows[0]
    return None


def check_audit(app: Any, doc: dict, *, cancelled: Callable[[], bool] = lambda: False) -> dict:
    """`{total, green, red, untried}`."""
    from services.smith.trials import _session
    pol = policy(doc)
    if pol["level"] == "none":
        return {"total": 0, "green": [], "red": [], "untried": []}
    green: list[dict] = []
    red: list[dict] = []
    untried: list[dict] = []
    it = lambda what, why: item(f"audit::{what}", "Audit trail", why, "audit")  # noqa: E731
    try:
        _who, admin = _session(app, doc, "")
    except Exception as exc:  # noqa: BLE001
        return {"total": 1, "green": [], "red": [], "untried": [it("recorded", f"could not sign in as the administrator: {str(exc)[:160]}")]}
    # 1. A change through the API lands on the trail with its actor.
    picked = _first_record(app, doc)
    if picked is None:
        untried.append(it("recorded", "no record with rows to change"))
    else:
        ent, slug, rid, row = picked
        label = str(ent.get("labelField") or "")
        # The label set to the value it holds. Never `id` — the API strips it,
        # and an empty save was the engine's `set where` 500 (pah7lhfz).
        body = {label: row.get(label)} if label and label != "id" and row.get(label) is not None else {}
        before = _rows(app, "select count(*) from forge_audit")
        status, _loc, text = _http(app, "PUT", f"/api/data/{slug}/{rid}", body, admin)
        if status == 422 and "reason is required" in text:
            green.append(it("reason", f"a change to a {ent.get('name')} without a reason is refused"))
        elif status >= 400:
            untried.append(it("recorded", f"the change was answered {status}: {text[:120]}"))
        else:
            rows = _rows(app, f"select actor_id, action from forge_audit where entity = '{_q(ent.get('name'))}' "
                              f"and entity_id = '{_q(rid)}' and action = 'update' order by seq desc limit 1")
            if rows and rows[0] and rows[0][0]:
                green.append(it("recorded", f"a change to a {ent.get('name')} is on the record with who made it"))
            else:
                red.append(it("recorded", f"a change to a {ent.get('name')} left nothing on the record"))
        del before
    # 2. The record cannot be changed or erased.
    changed = _rows(app, "update forge_audit set reason = 'tampered' where seq = (select min(seq) from forge_audit) returning seq")
    erased = _rows(app, "delete from forge_audit where seq = (select min(seq) from forge_audit) returning seq")
    if changed or erased:
        red.append(it("immutable", "a row of the trail could be " + ("changed" if changed else "erased") + " with SQL"))
    else:
        green.append(it("immutable", "the trail refuses change and erasure"))
    # 3. The chain verifies; 4. reviewers read it, others do not; 5. the export.
    reviewers = list(pol["reviewers"])
    roles = [str(r.get("name")) for r in doc.get("roles") or [] if isinstance(r, dict) and r.get("name")]
    other = next((r for r in roles if r not in reviewers), None)
    jars: dict[str, list[dict] | None] = {}
    for role in [*reviewers[:1], *([other] if other else [])]:
        try:
            jars[role] = _session(app, doc, role)[1]
        except Exception:  # noqa: BLE001
            jars[role] = None
    reviewer = reviewers[0] if reviewers else None
    if reviewer and jars.get(reviewer):
        status, _l, text = _http(app, "GET", "/api/audit/verify", None, jars[reviewer])
        try:
            ok = json.loads(text).get("ok") is True
        except ValueError:
            ok = False
        (green if status == 200 and ok else red).append(it("verify", "the chain verifies" if status == 200 and ok
                                                            else f"the chain did not verify ({status}: {text[:100]})"))
        status, _l, _t = _http(app, "GET", "/api/audit?limit=1", None, jars[reviewer])
        (green if status == 200 else red).append(it("reviewers", f"a {reviewer} reads the trail" if status == 200
                                                     else f"a {reviewer} was answered {status} reading the trail"))
        status, _l, _t = _http(app, "GET", "/api/audit/export", None, jars[reviewer])
        if status == 200:
            if pol["level"] == "regulated":
                rows = _rows(app, "select count(*) from forge_audit where action = 'export' and entity = 'forge_audit'")
                n = int(rows[0][0]) if rows and rows[0] and rows[0][0].isdigit() else 0
                (green if n else red).append(it("export", "the trail exports, and the export is on the record" if n
                                                 else "the trail exported and the export is not on the record"))
            else:
                green.append(it("export", "the trail exports"))
        else:
            red.append(it("export", f"the export was answered {status}"))
    else:
        untried.append(it("reviewers", "no reviewer login to read the trail as"))
    if other and jars.get(other):
        status, _l, _t = _http(app, "GET", "/api/audit?limit=1", None, jars[other])
        (green if status == 403 else red).append(it("others", f"a {other} is kept out of the trail" if status == 403
                                                     else f"a {other} was answered {status} reading the trail"))
    return {"total": len(green) + len(red) + len(untried), "green": green, "red": red, "untried": untried}


__all__ = ["check_audit", "policy"]
