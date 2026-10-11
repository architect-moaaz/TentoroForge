"""The audit check proves the trail on a copy: a change lands with its actor,
SQL cannot change or erase a row, the chain verifies, reviewers read it and
others are kept out, the export is on the record. No trail declared: nothing
to prove, 0 of 0 — and the card says so (2026-10-12)."""
from __future__ import annotations

import json

from services.blueprint import audit_check as ac
from services.blueprint import scorecard as sc

DOC = {
    "roles": [{"id": "ROLE-001", "name": "Compliance"}, {"id": "ROLE-002", "name": "Clerk"}],
    "data": {"entities": [{"id": "ENTITY-001", "name": "Invoice", "table": "invoices", "labelField": "number", "fields": []}]},
    "security": {"audit": {"level": "regulated", "reviewers": ["ROLE-001"], "reasonRequired": []}},
}


def test_no_trail_is_nothing_to_prove():
    assert ac.check_audit(object(), {"security": {"audit": {"level": "none"}}}) == {"total": 0, "green": [], "red": [], "untried": []}
    card = sc.empty({"security": {"audit": {"level": "none"}}})
    assert card["criteria"]["audit"] == {"total": 0, "green": 0, "red": [], "untried": []}
    assert "audit" in sc.CRITERIA and sc.LABELS["audit"] == "Every change is on the record"


def test_the_check_changes_a_record_attacks_the_trail_and_reads_it_back(monkeypatch):
    sqls = []

    def rows(app, sql):
        sqls.append(sql)
        if sql.startswith("update forge_audit") or sql.startswith("delete from forge_audit"):
            return []                                          # refused by the guard
        if "from forge_audit where entity" in sql:
            return [["u-admin", "update"]]
        if "action = 'export'" in sql:
            return [["1"]]
        return []
    monkeypatch.setattr(ac, "_rows", rows)
    monkeypatch.setattr(ac, "_first_record", lambda app, doc: (DOC["data"]["entities"][0], "invoice", "i-1", {"id": "i-1", "number": "INV-1"}))
    monkeypatch.setattr("services.smith.trials._session", lambda app, doc, role, guest=None: (role or "admin", [{"role": role}]))

    def http(app, method, path, body, cookies):
        role = cookies[0]["role"]
        if path.startswith("/api/data/"):
            return 200, "", "{}"
        if path == "/api/audit/verify":
            return 200, "", json.dumps({"ok": True, "checked": 3})
        if path.startswith("/api/audit"):
            return (200, "", "{}") if role == "Compliance" else (403, "", "{}")
        return 404, "", ""
    monkeypatch.setattr("services.smith.trials._http", http)
    out = ac.check_audit(object(), DOC)
    assert [g["id"] for g in out["green"]] == ["audit::recorded", "audit::immutable", "audit::verify", "audit::reviewers",
                                               "audit::export", "audit::others"]
    assert out["red"] == [] and out["untried"] == []
    assert any(s.startswith("update forge_audit") for s in sqls) and any(s.startswith("delete from forge_audit") for s in sqls)


def test_a_trail_that_can_be_tampered_with_is_red(monkeypatch):
    monkeypatch.setattr(ac, "_rows", lambda app, sql: [["1"]] if sql.startswith("update forge_audit") else [])
    monkeypatch.setattr(ac, "_first_record", lambda app, doc: None)
    monkeypatch.setattr("services.smith.trials._session", lambda app, doc, role, guest=None: (role, []))
    monkeypatch.setattr("services.smith.trials._http", lambda *a: (200, "", "{}"))
    out = ac.check_audit(object(), DOC)
    assert any(r["id"] == "audit::immutable" and "changed" in r["why"] for r in out["red"])
