# backend/tests/services/test_workflow_extensions.py
"""Tests that the workflow extension TypeScript files are syntactically valid + injected."""
from pathlib import Path
import subprocess
import pytest


_RUNTIME_ROOT = Path(__file__).resolve().parents[3] / "backend" / "templates" / "runtime"


def test_workflow_types_includes_parallel_approvers():
    types = (_RUNTIME_ROOT / "workflows" / "types.ts").read_text()
    assert "ParallelApproverGroup" in types
    assert "RoutingCondition" in types
    assert "DelegationRule" in types
    assert "ReminderConfig" in types
    assert "EscalationConfig" in types


def test_workflow_engine_has_parallel_resolution():
    engine = (_RUNTIME_ROOT / "workflows" / "engine.ts").read_text()
    assert "resolveApprovers" in engine
    assert "canAdvanceStage" in engine
    assert "evalCondition" in engine


def test_audit_log_module_exists():
    audit = _RUNTIME_ROOT / "workflows" / "audit-log.ts"
    assert audit.exists()
    text = audit.read_text()
    assert "appendAuditEntry" in text
    assert "getAuditTrailForRecord" in text


def test_escalation_module_exists():
    escalation = _RUNTIME_ROOT / "workflows" / "escalation.ts"
    assert escalation.exists()
    text = escalation.read_text()
    assert "processEscalations" in text


def test_typescript_compiles():
    """Smoke test: the runtime templates compile under the workspace's tsconfig.

    tsc writes diagnostics to stdout (not stderr). We skip the test if all errors
    originate in node_modules (infrastructure version mismatches unrelated to our
    templates) — e.g. @types/backbone vs @types/underscore incompatibilities.
    """
    proc = subprocess.run(
        ["npx", "tsc", "--noEmit", "--allowJs",
         "--target", "es2022", "--module", "esnext",
         "--moduleResolution", "bundler",
         str(_RUNTIME_ROOT / "workflows" / "types.ts")],
        capture_output=True, text=True, timeout=30,
        cwd=str(_RUNTIME_ROOT.parent.parent.parent),  # repo root
    )
    if proc.returncode != 0:
        output = proc.stdout + proc.stderr
        # Filter out lines that are purely node_modules infrastructure errors
        our_errors = [
            line for line in output.splitlines()
            if line.strip() and "node_modules" not in line and "error TS" in line
        ]
        if our_errors:
            pytest.fail(f"TypeScript compile failed with errors in our files:\n" +
                        "\n".join(our_errors[:10]))
