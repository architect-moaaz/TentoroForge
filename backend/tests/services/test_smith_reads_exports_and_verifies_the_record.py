"""Smith answers from the trail, exports it, verifies it, and changes the
policy through the security agent; without a trail it says so and offers
to keep one (2026-10-12)."""
from __future__ import annotations

from services.blueprint.service import BlueprintService
from services.smith import audit_change as au


def _svc(tmp_path, level="regulated"):
    s = BlueprintService.create(output_dir=tmp_path, app_id="a", name="Books", domain="finance")
    s.doc["roles"] = [{"id": "ROLE-001", "name": "Compliance"}]
    s.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Invoice", "table": "invoices", "fields": []}]}
    s.doc["security"] = {"audit": {"level": level, "reviewers": ["ROLE-001"]}}
    s.save()
    return s


class _Bench:
    def __init__(self, *a, **k):
        pass

    def app(self):
        return object()

    def close(self):
        return None


def test_without_a_trail_smith_offers_to_keep_one(tmp_path):
    svc = _svc(tmp_path, level="none")
    out = au.show_audit(svc, str(tmp_path), change="who deleted invoices")
    assert not out["applied"] and "keeps no audit trail" in out["reason"] and out["options"]


def test_smith_answers_from_the_record(tmp_path, monkeypatch):
    svc = _svc(tmp_path)
    monkeypatch.setattr("services.smith.trials.Bench", _Bench)
    seen = []

    def query(app, sql):
        seen.append(sql)
        if sql.startswith("select count"):
            return [["2"]]
        return [["2026-10-12 09:00", "Clerk", "delete", "Invoice", "abc12345", "", "duplicate"],
                ["2026-10-11 17:30", "Clerk", "delete", "Invoice", "def67890", "", ""]]
    monkeypatch.setattr("services.blueprint.page_review._query", query)
    out = au.show_audit(svc, str(tmp_path), change="who deleted invoices yesterday")
    assert out["applied"] and "2 on the record" in out["diff_summary"] and "Clerk delete Invoice abc12345" in out["diff_summary"]
    assert "action = 'delete'" in seen[0] and "lower(entity) = 'invoice'" in seen[0] and "current_date - 1" in seen[0]


def test_smith_exports_and_verifies(tmp_path, monkeypatch):
    svc = _svc(tmp_path)
    monkeypatch.setattr("services.smith.trials.Bench", _Bench)
    monkeypatch.setattr("services.blueprint.page_review._query", lambda app, sql: [["1", "2026-10-12", "u", "Clerk", "user", "api", "create", "Invoice", "i", "{}", "{}", "", "", "", "h"]])
    out = au.export_audit(svc, str(tmp_path))
    assert out["applied"] and out["file"].endswith(".csv") and "Exported 1 entries" in out["diff_summary"]
    monkeypatch.setattr("services.smith.trials._session", lambda app, doc, role, guest=None: (role, []))
    monkeypatch.setattr("services.smith.trials._http", lambda *a: (200, "", '{"ok": true, "checked": 7}'))
    out = au.verify_audit(svc, str(tmp_path))
    assert out["applied"] and "intact: 7 entries" in out["diff_summary"]
    monkeypatch.setattr("services.smith.trials._http", lambda *a: (200, "", '{"ok": false, "checked": 3, "brokenAt": 4}'))
    assert "BROKEN at entry 4" in au.verify_audit(svc, str(tmp_path))["diff_summary"]


def test_the_verbs_are_smiths():
    from services.smith.verbs import REQUIRED_BY_VERB, VERB_EXAMPLES, VERB_HELP
    from services.smith4.verbs import PERFORM
    for v in au.VERBS:
        assert v in REQUIRED_BY_VERB and v in VERB_HELP and v in VERB_EXAMPLES and v in PERFORM
