"""Tests for services.security_gate — deterministic security checks.

Fixtures model the real leak classes: a planted AWS key (must be
reported redacted, never verbatim), a password-bearing postgres URL in
src (error) vs .env.local (allowed), a role-declaring registry missing
its enforcement chain, the no-lockfile npm-audit skip, and live authz
probes against a monkeypatched httpx (no real network).
"""
from __future__ import annotations

import json
from pathlib import Path

import services.security_gate as security_gate
from services.security_gate import (
    check_authz_coverage,
    run_live_authz_probes,
    run_npm_audit,
    run_security_gate,
    scan_secrets,
)


# ── fixture builders ─────────────────────────────────────────────────

def _write(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _registry_with_roles() -> str:
    return json.dumps({
        "version": 1,
        "accessModel": {
            "ownership": "role-based",
            "roles": ["admin", "member"],
            "rules": [
                {"entity": "audit-logs", "roles": ["admin"]},
            ],
            "userEntityId": "user",
        },
        "roles": ["admin", "member"],
        "entities": {
            "document": {"id": "document", "slug": "documents"},
            "audit-log": {"id": "audit-log", "slug": "audit-logs"},
        },
    })


_FAKE_AWS_KEY = "AKIAIOSFODNN7EXAMPLE"  # canonical AWS docs example key
_PG_URL = "postgresql://forge:s3cretpw@db.internal:5432/app"


# ── A1: secret scan ──────────────────────────────────────────────────

def test_planted_aws_key_is_critical_and_redacted(tmp_path: Path):
    root = tmp_path / "app"
    _write(root, "src/lib/config.ts",
           f'export const key = "{_FAKE_AWS_KEY}";\n')
    report = run_security_gate(str(root))

    hits = [e for e in report["errors"] if e["rule"] == "secret_leak"]
    assert len(hits) == 1
    assert hits[0]["severity"] == "critical"
    assert hits[0]["file"] == "src/lib/config.ts"
    assert hits[0]["line"] == 1
    assert report["passed"] is False
    # The report must NEVER contain the secret itself — anywhere.
    assert _FAKE_AWS_KEY not in json.dumps(report)
    assert _FAKE_AWS_KEY[:6] in hits[0]["detail"]  # redacted prefix survives
    # And the on-disk artifact is equally clean.
    on_disk = (root / "security-report.json").read_text(encoding="utf-8")
    assert _FAKE_AWS_KEY not in on_disk


def test_postgres_url_in_src_errors(tmp_path: Path):
    root = tmp_path / "app"
    _write(root, "src/db/client.ts",
           f'const url = "{_PG_URL}";\n')
    report = run_security_gate(str(root))
    hits = [e for e in report["errors"] if e["rule"] == "secret_leak"]
    assert len(hits) == 1
    assert hits[0]["severity"] == "error"
    assert "postgres_url_with_password" in hits[0]["detail"]
    assert "s3cretpw" not in json.dumps(report)


def test_postgres_url_in_env_local_is_allowed(tmp_path: Path):
    root = tmp_path / "app"
    _write(root, ".env.local", f"DATABASE_URL={_PG_URL}\n")
    _write(root, "src/db/client.ts",
           "const url = process.env.DATABASE_URL!;\n")
    report = run_security_gate(str(root))
    assert report["errors"] == []
    assert report["passed"] is True


def test_env_var_indirected_postgres_url_not_flagged(tmp_path: Path):
    root = tmp_path / "app"
    _write(root, "src/db/client.ts",
           'const url = `postgresql://forge:${process.env.DB_PASSWORD}@db:5432/app`;\n')
    assert scan_secrets(root) == []


def test_node_modules_skipped(tmp_path: Path):
    root = tmp_path / "app"
    _write(root, "src/node_modules/evil/index.js",
           f'module.exports = "{_FAKE_AWS_KEY}";\n')
    assert scan_secrets(root) == []


# ── A2: env hygiene ──────────────────────────────────────────────────

def test_hardcoded_nextauth_secret_errors(tmp_path: Path):
    root = tmp_path / "app"
    _write(root, "src/auth.ts",
           'export const config = { NEXTAUTH_SECRET: "hunter2hunter2" };\n')
    report = run_security_gate(str(root))
    hits = [e for e in report["errors"] if e["rule"] == "env_hygiene"]
    assert len(hits) == 1
    assert "NEXTAUTH_SECRET" in hits[0]["detail"]


def test_process_env_nextauth_secret_is_fine(tmp_path: Path):
    root = tmp_path / "app"
    _write(root, "src/auth.ts",
           "export const secret = process.env.NEXTAUTH_SECRET;\n")
    report = run_security_gate(str(root))
    assert report["errors"] == []


def test_client_component_env_import_errors(tmp_path: Path):
    root = tmp_path / "app"
    _write(root, "src/components/Widget.tsx",
           '"use client";\nimport env from "../../.env.local";\n')
    report = run_security_gate(str(root))
    hits = [e for e in report["errors"] if e["rule"] == "env_hygiene"]
    assert len(hits) == 1


# ── A3: authz coverage ───────────────────────────────────────────────

def test_registry_with_roles_missing_middleware_errors(tmp_path: Path):
    root = tmp_path / "app"
    _write(root, "contracts/resource-registry.json", _registry_with_roles())
    report = run_security_gate(str(root))
    rules = {e["rule"] for e in report["errors"]}
    assert "authz_middleware_missing" in rules
    assert "authz_auth_missing" in rules
    assert "authz_rules_runtime_missing" in rules
    assert report["passed"] is False


def test_registry_with_roles_and_full_chain_passes(tmp_path: Path):
    root = tmp_path / "app"
    _write(root, "contracts/resource-registry.json", _registry_with_roles())
    _write(root, "src/middleware.ts", "export function middleware() {}\n")
    _write(root, "src/auth.ts", "export const auth = {};\n")
    _write(root, "src/lib/rules/engine.ts", "export function evaluate() {}\n")
    report = run_security_gate(str(root))
    assert [e for e in report["errors"] if e["rule"].startswith("authz_")] == []
    assert report["passed"] is True


def test_public_only_registry_needs_no_enforcement(tmp_path: Path):
    root = tmp_path / "app"
    _write(root, "contracts/resource-registry.json", json.dumps({
        "accessModel": {"ownership": "role-based", "roles": ["Public"],
                        "rules": [], "userEntityId": "user"},
        "roles": ["Public"], "entities": {},
    }))
    assert check_authz_coverage(root) == []


# ── A4: npm audit ────────────────────────────────────────────────────

def test_npm_audit_skips_without_lockfile(tmp_path: Path):
    root = tmp_path / "app"
    _write(root, "package.json", '{"name": "app", "dependencies": {}}\n')
    errors, warnings, skipped = run_npm_audit(root)
    assert errors == [] and warnings == []
    assert len(skipped) == 1
    assert skipped[0]["rule"] == "npm_audit"
    assert "no lockfile" in skipped[0]["detail"]

    report = run_security_gate(str(root))
    assert any(s["rule"] == "npm_audit" for s in report["skipped"])
    assert report["passed"] is True


def test_npm_audit_skips_without_package_json(tmp_path: Path):
    errors, warnings, skipped = run_npm_audit(tmp_path)
    assert errors == [] and warnings == []
    assert "no package.json" in skipped[0]["detail"]


# ── A5: next.config ──────────────────────────────────────────────────

def test_both_build_checks_disabled_warns(tmp_path: Path):
    root = tmp_path / "app"
    _write(root, "next.config.mjs",
           "export default { eslint: { ignoreDuringBuilds: true }, "
           "typescript: { ignoreBuildErrors: true } };\n")
    report = run_security_gate(str(root))
    rules = {w["rule"] for w in report["warnings"]}
    assert "config_build_checks_disabled" in rules
    assert "config_powered_by_header" in rules
    assert report["passed"] is True  # warnings never fail the gate


# ── B: live authz probes (monkeypatched httpx — no real network) ─────

class _FakeResponse:
    def __init__(self, status_code: int, body=None):
        self.status_code = status_code
        self._body = body

    def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


class _FakeHttpx:
    def __init__(self, responses: dict[str, _FakeResponse]):
        self._responses = responses
        self.calls: list[str] = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        slug = url.rsplit("/", 1)[-1]
        return self._responses[slug]


def _probe_app(tmp_path: Path) -> Path:
    root = tmp_path / "app"
    _write(root, "contracts/resource-registry.json", _registry_with_roles())
    return root


def test_probe_200_with_rows_is_critical_anon_read(tmp_path: Path, monkeypatch):
    root = _probe_app(tmp_path)
    fake = _FakeHttpx({
        "documents": _FakeResponse(200, [{"id": "d1"}, {"id": "d2"}]),
        "audit-logs": _FakeResponse(200, {"rows": [{"id": "a1"}]}),
    })
    monkeypatch.setattr(security_gate, "httpx", fake)
    findings = run_live_authz_probes(str(root), "http://localhost:3000/")

    anon = {f["slug"]: f for f in findings if f["rule"] == "anon_read"}
    assert set(anon) == {"documents", "audit-logs"}
    assert all(f["severity"] == "critical" for f in anon.values())
    # audit-logs is admin-only in the access model — strongest class.
    assert anon["audit-logs"]["admin_only"] is True
    assert anon["documents"]["admin_only"] is False
    assert fake.calls[0].startswith("http://localhost:3000/api/data/")


def test_probe_401_passes(tmp_path: Path, monkeypatch):
    root = _probe_app(tmp_path)
    fake = _FakeHttpx({
        "documents": _FakeResponse(401),
        "audit-logs": _FakeResponse(403),
    })
    monkeypatch.setattr(security_gate, "httpx", fake)
    findings = run_live_authz_probes(str(root), "http://localhost:3000")
    assert all(f["ok"] is True for f in findings)
    assert all(f["rule"] == "authz_probe" for f in findings)


def test_gate_folds_probe_criticals_when_base_url_given(
        tmp_path: Path, monkeypatch):
    root = _probe_app(tmp_path)
    _write(root, "src/middleware.ts", "export function middleware() {}\n")
    _write(root, "src/auth.ts", "export const auth = {};\n")
    _write(root, "src/lib/rules/engine.ts", "export const e = 1;\n")
    fake = _FakeHttpx({
        "documents": _FakeResponse(200, [{"id": "d1"}]),
        "audit-logs": _FakeResponse(401),
    })
    monkeypatch.setattr(security_gate, "httpx", fake)
    report = run_security_gate(str(root), base_url="http://localhost:3000")
    assert report["passed"] is False
    assert any(e["rule"] == "anon_read" and e["severity"] == "critical"
               for e in report["errors"])
    assert "live_probes" in report


def test_static_gate_never_probes_network(tmp_path: Path, monkeypatch):
    """No base_url → httpx must never be touched."""
    root = _probe_app(tmp_path)

    class _Boom:
        def get(self, *a, **k):  # pragma: no cover — must not run
            raise AssertionError("static gate must not touch the network")

    monkeypatch.setattr(security_gate, "httpx", _Boom())
    report = run_security_gate(str(root))
    assert "live_probes" not in report


# ── gate robustness + report shape ───────────────────────────────────

def test_gate_never_raises_on_missing_dir(tmp_path: Path):
    report = run_security_gate(str(tmp_path / "nothing"))
    assert report["passed"] is True
    assert report["errors"] == []


def test_report_written_to_output_dir(tmp_path: Path):
    root = tmp_path / "app"
    _write(root, "src/lib/config.ts", "export const x = 1;\n")
    report = run_security_gate(str(root))
    on_disk = json.loads((root / "security-report.json").read_text(encoding="utf-8"))
    assert on_disk["passed"] == report["passed"]
    assert set(on_disk) >= {"generated_at", "passed", "errors",
                            "warnings", "skipped"}


# ── delivery-gate wiring: "security" rule family ─────────────────────

def test_delivery_gate_folds_security_family(tmp_path: Path):
    from services.delivery_gate import run_delivery_gate

    root = tmp_path / "app"
    _write(root, "src/contracts/plan.json", json.dumps(
        {"pages": [{"route": "/", "kind": "form"}], "workflows": []}))
    _write(root, "src/contracts/nav-flow.json", json.dumps(
        {"pages": [{"id": "home", "route": "/"}], "transitions": []}))
    _write(root, "src/schemas/registry.ts",
           'export const schemas = {\n  "/": () => import("./x.json")\n};\n')
    _write(root, "src/schemas/index.json", json.dumps(
        {"route": "/", "root": {"type": "Form", "children": []}}))
    _write(root, "src/app/globals.css", "")
    _write(root, "src/lib/config.ts",
           f'export const key = "{_FAKE_AWS_KEY}";\n')

    report = run_delivery_gate(root, mode="warn")
    sec = [v for v in report["violations"] if v["rule"].startswith("security_")]
    assert any(v["rule"] == "security_secret_leak" and v["severity"] == "error"
               for v in sec)
    # Redaction holds through the fold too.
    assert _FAKE_AWS_KEY not in json.dumps(report)
    # And the security gate's own artifact was written alongside.
    assert (root / "security-report.json").is_file()
