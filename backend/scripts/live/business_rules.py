"""Live check: Business Rules, end to end, against a running Forge and a real app.

Run:  backend/.venv/bin/python backend/scripts/live/business_rules.py

Two apps of the local Forge Dev Org (builder: dev.tester):
  · a calculator that keeps NO records (made here if missing) — the shape of
    an app whose rules all read "Not enforced" with "New rule" greyed out;
  · Expense Desk (built; Expense: title, amount, category, status, managerNote)
    — rules authored here are tested by the app's engine, enforced by the
    app's own API (preview, with Docker), and run as workflow steps.
Everything made here is removed at the end.
"""
from __future__ import annotations

import json
import re
import sys
import time
import uuid
from pathlib import Path

from _live import BACKEND, app_session, builder_token, check, client, done

EXPENSE_DESK = "c8389db4-98bf-4cb9-8375-af789b1c6677"
EXPENSE = "ENTITY-001"
OUTPUT = BACKEND.parent / "output"
TAG = uuid.uuid4().hex[:6]           # this run's rules are told apart from any left behind


def calculator(B, org: str) -> str:
    """The no-records app: a calculator whose rules are about its screens."""
    from services.blueprint.service import BlueprintService
    projects = B.get(f"/api/orgs/{org}/projects").json()
    projects = projects.get("items", projects) if isinstance(projects, dict) else projects
    p = next((x for x in projects if x["name"] == "Calculator (rules check)"), None)
    if p is None:
        p = B.post(f"/api/orgs/{org}/projects", json={"name": "Calculator (rules check)"}).json()
    out = OUTPUT / p["short_id"]
    if not (out / ".forge" / "blueprint" / "current.json").is_file():
        svc = BlueprintService.create(output_dir=out, app_id=p["short_id"], name="Calculator (rules check)",
                                      domain="utility", description="A desk calculator with an amber-on-slate display.")
        svc.doc["businessRules"] = [
            {"id": "RULE-001", "name": "No division by zero", "kind": "statement", "origin": "brief", "status": "PROPOSED",
             "statement": "Dividing by zero shows a clear 'Error' state, never Infinity or NaN."},
            {"id": "RULE-002", "name": "Single pending operator", "kind": "statement", "origin": "brief", "status": "PROPOSED",
             "statement": "Pressing a second operator replaces the pending one instead of queuing both."},
        ]
        svc.validate()
        svc.save()
    return p["id"]


def sweep(B) -> None:
    """Rules an interrupted run left behind (named "… <6 hex>"), so this run starts clean."""
    for v in B.get(f"/api/projects/{EXPENSE_DESK}/business-rules").json()["rules"]:
        if v["origin"] == "editor" and re.search(r" [0-9a-f]{6}$", v["rule"]["name"]):
            B.delete(f"/api/projects/{EXPENSE_DESK}/business-rules/{v['rule']['id']}")


def main() -> None:
    tok, org = builder_token()
    B = client(tok)
    sweep(B)

    # ---- an app with no records -------------------------------------------
    calc = calculator(B, org)
    r = B.get(f"/api/projects/{calc}/business-rules").json()
    check(r["mode"] == "blueprint" and r["catalogue"]["entities"] == [], "N  a calculator keeps no records")
    check(all(v["runs"] == "nowhere" for v in r["rules"]) and len(r["rules"]) >= 2, "N  its rules are written, not enforced")
    made = B.post(f"/api/projects/{calc}/business-rules", json={
        "kind": "statement", "name": f"Display precision {TAG}",
        "statement": "A result longer than the display is rounded, never cut off mid-digit."})
    check(made.status_code == 201 and made.json()["rule"]["kind"] == "statement", "N  a written rule can be added (New rule is never a dead end)")
    calc_rule = made.json()["rule"]["rule"]["id"]
    bad = B.post(f"/api/projects/{calc}/business-rules", json={
        "kind": "condition_action", "name": "x", "statement": "x", "when": "true",
        "then": [{"type": "show_error", "message": "no"}]})
    check(bad.status_code == 400 and "record" in json.dumps(bad.json()), "N  a when/then rule says it needs a record")
    t = B.post(f"/api/projects/{calc}/business-rules/test", json={
        "rule": {"kind": "statement", "name": "x", "statement": "x"}, "record": {}}).json()
    check(not t["ok"] and "written rule" in t["problems"][0], "N  testing a written rule says why there is nothing to test")
    B.delete(f"/api/projects/{calc}/business-rules/{calc_rule}")

    # ---- Expense Desk: author, test ------------------------------------------
    r = B.get(f"/api/projects/{EXPENSE_DESK}/business-rules").json()
    ent = next(e for e in r["catalogue"]["entities"] if e["id"] == EXPENSE)
    cats = next(f for f in ent["fields"] if f["name"] == "category")
    check(cats["type"] == "enum" and cats["enumValues"] == ["travel", "meals", "office"], "E  category is a list: travel, meals, office")
    log = next(w for w in r["catalogue"]["workflows"] if w["id"] == "FLOW-001")
    check("check_category" in [s["key"] for s in log["steps"]], "E  the catalogue lists each workflow's steps")

    bad = B.post(f"/api/projects/{EXPENSE_DESK}/business-rules/check", json={
        "kind": "condition_action", "name": "x", "entity": EXPENSE, "when": "budget > 1",
        "then": [{"type": "show_error", "message": "x"}]}).json()
    check(not bad["ok"] and "budget" in " ".join(bad["problems"]), "E  a condition on a field the record lacks is named")

    msg = f"LIVE {TAG}: office spend over 3000 needs approval first."
    gate = {"kind": "condition_action", "name": f"Office spend cap {TAG}", "entity": EXPENSE, "on": ["create"],
            "when": 'category = "office" and amount > 3000', "then": [{"type": "show_error", "message": msg}]}
    made = B.post(f"/api/projects/{EXPENSE_DESK}/business-rules", json=gate)
    check(made.status_code == 201 and made.json()["rule"]["runs"] == "everywhere", "E  a gate on create is saved, enforced everywhere")
    gate_id = made.json()["rule"]["rule"]["id"]
    check(made.json()["rule"]["rule"]["on"] == ["create"], "E  it fires on create only")
    t = B.post(f"/api/projects/{EXPENSE_DESK}/business-rules/test", json={
        "rule_id": gate_id, "rule": gate, "record": {"title": "Desk", "amount": 3500, "category": "office"}}).json()
    check(t["refused"] and msg in t["errors"] and t["focus"]["held"], "E  Test it: 3500 of office is refused, by this rule")
    t = B.post(f"/api/projects/{EXPENSE_DESK}/business-rules/test", json={
        "rule_id": gate_id, "rule": gate, "event": "update", "previous": {"amount": 10, "category": "office"},
        "record": {"title": "Desk", "amount": 3500, "category": "office"}}).json()
    check(msg not in (t.get("errors") or []) and t["focus"]["fires"] is False, "E  Test it: on a change it does not fire")

    table = {"kind": "decision_table", "name": f"Note by category {TAG}", "entity": EXPENSE, "on": ["create"],
             "table": {"hitPolicy": "U",
                       "inputs": [{"name": "managerNote"}, {"name": "category"}],
                       "outputs": [{"name": "managerNote"}],
                       "rules": [{"inputEntries": ["null", "travel"], "outputEntries": ["Travel: attach the ticket."]},
                                 {"inputEntries": ["null", "meals"], "outputEntries": ["Meals: list who attended."]},
                                 {"inputEntries": ["null", "office"], "outputEntries": ["Office: name the supplier."]},
                                 {"inputEntries": ["null", "travel, meals"], "outputEntries": ["Either."]}]}}
    refused = B.post(f"/api/projects/{EXPENSE_DESK}/business-rules", json=table)
    check(refused.status_code == 400 and "Unique" in json.dumps(refused.json()), "E  an overlapping Unique table is refused, naming the rows")
    typo = json.loads(json.dumps(table))
    typo["table"]["rules"] = typo["table"]["rules"][:3]
    typo["table"]["rules"][1]["inputEntries"][1] = "meal"
    r2 = B.post(f"/api/projects/{EXPENSE_DESK}/business-rules", json=typo)
    check(r2.status_code == 400 and "“meal” is not one of travel, meals, office" in json.dumps(r2.json(), ensure_ascii=False), "E  a typo against the list is caught")
    table["table"]["rules"] = table["table"]["rules"][:3]
    made = B.post(f"/api/projects/{EXPENSE_DESK}/business-rules", json=table)
    check(made.status_code == 201 and made.json()["rule"]["runs"] == "save", "E  the table is saved; it runs on every save")
    table_id = made.json()["rule"]["rule"]["id"]
    t = B.post(f"/api/projects/{EXPENSE_DESK}/business-rules/test", json={
        "rule_id": table_id, "rule": table, "record": {"title": "Lunch", "amount": 40, "category": "meals"}}).json()
    check(t["patches"].get("managerNote") == "Meals: list who attended." and t["focus"]["matched"] == [2], "E  Test it: row 2 matched, the note is set")

    # ---- the app enforces them ------------------------------------------------
    out = OUTPUT / "72o1ekkf" / "app"
    check((out / "src" / "lib" / "rules" / "decision-table.ts").is_file(), "A  the app received the new engine on the save")
    port = B.post(f"/api/projects/{EXPENSE_DESK}/preview/start", timeout=900).json()["port"]
    S, APP = app_session(port, "72o1ekkf")
    time.sleep(2.5)                                  # the engine re-reads its rules files at most once a second
    r = S.post(f"{APP}/api/data/expenses", json={"title": f"Chair {TAG}", "amount": 3500, "category": "office"})
    check(r.status_code in (400, 422) and msg in r.text, f"A  the app's API refuses 3500 of office ({r.status_code})")
    r = S.post(f"{APP}/api/data/expenses", json={"title": f"Lunch {TAG}", "amount": 40, "category": "meals"})
    check(r.status_code == 201 and r.json().get("managerNote") == "Meals: list who attended.", "A  the app's API saves lunch with the note the table set")
    lunch = r.json().get("id")

    # ---- in a workflow ------------------------------------------------------------
    att = B.post(f"/api/projects/{EXPENSE_DESK}/business-rules/{gate_id}/workflows",
                 json={"workflow": "FLOW-001", "after": "check_category", "on_refusal": "stop"})
    check(att.status_code == 200 and att.json()["rule"]["usages"]["steps"][0]["workflow"] == "FLOW-001", "W  the gate is a step of Log an expense")
    graph = json.loads((out / "src" / "lib" / "workflows" / "definitions" / "log-an-expense.json").read_text())
    key = gate_id.lower().replace("-", "_")          # RULE-008 -> rule_008
    nodes = {n["id"]: n for n in graph["definition"]["nodes"]}
    check(nodes.get(key, {}).get("type") == "decision", "W  the app's workflow file has the step")
    time.sleep(1.5)
    r = S.post(f"{APP}/api/workflows/log-an-expense/execute",
               json={"input": {"title": f"Desk {TAG}", "amount": 3600, "category": "office"}})
    body = r.json()
    check(r.status_code == 422 and body.get("refused") and body.get("error") == msg,
          f"W  running the workflow, it is refused with the rule's message ({r.status_code})")
    path = [step["nodeId"] for step in body.get("log") or []]
    check(key in path and f"{key}_refused" in path and "insert_expense" not in path,
          f"W  the rule's step refused it before the save step: {' > '.join(path)}")
    r = S.post(f"{APP}/api/workflows/log-an-expense/execute",
               json={"input": {"title": f"Taxi {TAG}", "amount": 30, "category": "travel"}})
    check(r.status_code == 200, f"W  a travel expense goes through the step ({r.status_code})")
    det = B.delete(f"/api/projects/{EXPENSE_DESK}/business-rules/{gate_id}/workflows/FLOW-001")
    graph = json.loads((out / "src" / "lib" / "workflows" / "definitions" / "log-an-expense.json").read_text())
    check(det.status_code == 200 and key not in {n["id"] for n in graph["definition"]["nodes"]}, "W  taken out again, the workflow is as it was")

    # Approve carries the record as one variable (expense.amount): the rule reads it there.
    att = B.post(f"/api/projects/{EXPENSE_DESK}/business-rules/{gate_id}/workflows",
                 json={"workflow": "FLOW-002", "after": "check_rejected", "path": "else"})
    check(att.status_code == 200, "W  the gate is a step of Approve, on its not-rejected path")
    time.sleep(1.5)
    desk = {"id": lunch, "title": f"Desk {TAG}", "amount": 3600, "category": "office", "status": "submitted"}
    r = S.post(f"{APP}/api/workflows/approve/execute", json={"input": {"expense": desk}})
    check(r.status_code == 422 and r.json().get("error") == msg,
          f"W  approving expense.amount 3600 of office is refused by the rule ({r.status_code})")
    r = S.post(f"{APP}/api/workflows/approve/execute", json={"input": {"expense": {**desk, "category": "travel"}}})
    path2 = [s["nodeId"] for s in r.json().get("log") or []]
    check(r.status_code == 200 and path2[:3] == ["trigger", "check_rejected", key],
          f"W  a travel one is approved through the step after the rejected check ({' > '.join(path2)})")
    r = S.post(f"{APP}/api/workflows/approve/execute", json={"input": {"expense": {**desk, "status": "rejected"}}})
    check(r.status_code == 422 and key not in [s["nodeId"] for s in r.json().get("log") or []],
          "W  a rejected one stops at its own check, before the rule's step")

    # Values first, judgement last: a table that fills in the category satisfies "category must be one of".
    cat_table = {"kind": "decision_table", "name": f"Category by amount {TAG}", "entity": EXPENSE,
                 "table": {"hitPolicy": "F", "inputs": [{"name": "amount"}], "outputs": [{"name": "category"}],
                           "rules": [{"inputEntries": ["> 1000"], "outputEntries": ["office"]},
                                     {"inputEntries": ["-"], "outputEntries": ["meals"]}]}}
    made2 = B.post(f"/api/projects/{EXPENSE_DESK}/business-rules", json=cat_table)
    check(made2.status_code == 201, "V  a table that fills in the category is saved")
    time.sleep(2.5)
    r = S.post(f"{APP}/api/data/expenses", json={"title": f"Screen {TAG}", "amount": 1200, "managerNote": "n"})
    check(r.status_code == 201 and r.json().get("category") == "office",
          f"V  no category given: the table's 'office' satisfies the category rule ({r.status_code})")
    S.delete(f"{APP}/api/data/expenses/{r.json().get('id')}") if r.status_code == 201 else None
    B.delete(f"/api/projects/{EXPENSE_DESK}/business-rules/{made2.json()['rule']['rule']['id']}")

    # ---- off, and away --------------------------------------------------------------
    v = next(x for x in B.get(f"/api/projects/{EXPENSE_DESK}/business-rules").json()["rules"] if x["rule"]["id"] == gate_id)
    check(B.patch(f"/api/projects/{EXPENSE_DESK}/business-rules/{gate_id}/enabled",
                  json={"enabled": False, "revision": v["revision"]}).status_code == 200, "O  switched off")
    time.sleep(2.5)
    r = S.post(f"{APP}/api/data/expenses", json={"title": f"Chair {TAG}", "amount": 3500, "category": "office"})
    check(r.status_code == 201, "O  off, the app saves what it refused")
    a = S.post(f"{APP}/api/workflows/approve/execute", json={"input": {"expense": desk}})
    check(a.status_code == 200, f"O  off, its step in Approve lets the run through ({a.status_code})")
    for rid in (gate_id, table_id):
        B.delete(f"/api/projects/{EXPENSE_DESK}/business-rules/{rid}")
    approve = (out / "src" / "lib" / "workflows" / "definitions" / "approve.json").read_text()
    check(gate_id not in approve and key not in approve, "O  removed, it is out of Approve too")
    for rec in (lunch, r.json().get("id")):
        if rec:
            S.delete(f"{APP}/api/data/expenses/{rec}")
    left = [x["rule"]["id"] for x in B.get(f"/api/projects/{EXPENSE_DESK}/business-rules").json()["rules"] if TAG in x["rule"]["name"]]
    check(left == [], "O  everything this check made is gone")
    done()


if __name__ == "__main__":
    sys.exit(main())
