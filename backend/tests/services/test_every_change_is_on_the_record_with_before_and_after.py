"""The audit policy is declared, projected for the runtime, and every
write path records: the engine in the write's transaction, a process's
own steps after theirs, a sign-in and an export when regulated
(2026-10-12). The chain itself runs in `run-audit-tests.sh`."""
from __future__ import annotations

from pathlib import Path

from services.blueprint.projection import audit_policy, project_audit

ROOT = Path(__file__).resolve().parents[2]
DOC = {
    "roles": [{"id": "ROLE-001", "name": "Compliance"}, {"id": "ROLE-002", "name": "Clerk"}],
    "data": {"entities": [{"id": "ENTITY-001", "name": "Invoice", "table": "invoices", "fields": []}]},
    "security": {"audit": {"level": "regulated", "reviewers": ["ROLE-001"], "retentionDays": 2555, "reasonRequired": ["ENTITY-001"]}},
    "pages": [{"id": "PAGE-009", "name": "Audit trail", "route": "/audit", "pattern": "audit_trail", "users": ["ROLE-001"]}],
}


def test_the_policy_is_projected_as_the_runtime_reads_it(tmp_path):
    assert audit_policy(DOC) == {"level": "regulated", "reviewers": ["Compliance"], "retentionDays": 2555,
                                 "reasonRequired": ["invoice", "invoices"]}
    assert audit_policy({}) == {"level": "none", "reviewers": [], "retentionDays": None, "reasonRequired": []}
    out = project_audit(DOC, tmp_path)
    policy = (tmp_path / "src/lib/audit-policy.ts").read_text()
    assert '"level": "regulated"' in policy and '"Compliance"' in policy
    assert "src/app/(dashboard)/audit/page.tsx" in out["files"]
    assert "Audit trail" in (tmp_path / "src/app/(dashboard)/audit/page.tsx").read_text()
    assert project_audit({}, tmp_path / "b")["files"] == ["src/lib/audit-policy.ts"], "no trail, no screen"


def test_every_write_path_records_in_the_writes_transaction():
    engine = (ROOT / "templates/runtime/data-engine.ts").read_text()
    assert engine.count("withAudit(") == 3, "create, update and remove"
    assert 'action: "create"' in engine and 'action: "update"' in engine and 'action: "delete"' in engine
    assert '_snapshotForAudit(entityName, existing)' in engine, "the row before, as the trail keeps it (masked)"
    assert 'action: "read_sensitive"' in engine, "looking is on the record"
    assert "A reason is required to change a" in engine
    audit = (ROOT / "templates/runtime/audit.ts").read_text()
    assert "db.transaction(async (tx: any) =>" in audit and "pg_advisory_xact_lock" in audit
    assert "forge_audit is append-only" in audit and "forge_audit_prune" in audit and "SECURITY DEFINER" in audit
    workflows = (ROOT / "templates/runtime/workflows/index.ts").read_text()
    assert workflows.count("await _trail(ctx,") == 4, "a process's inserts (both paths), updates and deletes"
    assert (ROOT / "templates/app-foundation/src/auth.ts").read_text().count("_signIn(") >= 4
    assert 'action: "export"' in (ROOT / "templates/runtime/api-export/route.ts").read_text()
    assert "pruneByPolicy(now)" in (ROOT / "templates/runtime/api-cron/route.ts").read_text()


def test_the_trail_ships_and_survives_a_republish():
    injector = (ROOT / "services/runtime_injector.py").read_text()
    assert "_forge_audit.ts" in injector and "audit/verify/route.ts" in injector and "audit-policy.ts" in injector
    reset = (ROOT / "templates/app-foundation/src/db/reset-schema.ts").read_text()
    assert 'name.startsWith("forge_")' in reset, "the runtime's tables are the scaffold's, not the person's work to wipe"
    data_route = (ROOT / "templates/data-api-route.ts").read_text()
    assert 'request.headers.get("x-change-reason")' in data_route and data_route.count("reason: reasonOf(request)") == 3
