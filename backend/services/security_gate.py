"""Security gate — deterministic security checks for generated apps.

Sibling to :mod:`services.delivery_gate`: pure filesystem reads, no LLM
calls, never fatal. Two halves:

**A. Static checks** (always run — filesystem only):

1. ``secret_leak`` (critical / error) — scan the emitted source
   (``src/``, ``workflows/``, ``contracts/``, ``next.config.*``,
   ``package.json``; node_modules/.next/.git skipped) for
   high-confidence secret patterns: Anthropic ``sk-ant-`` keys, live
   ``sk-live`` keys, AWS ``AKIA…`` access keys, ``vercel_`` tokens, PEM
   private-key blocks, and password-bearing ``postgres://`` connection
   strings outside ``.env*`` files. Matches are always REDACTED in the
   report (first 6 chars + ellipsis) — the report must never itself
   become a secret leak.
2. ``env_hygiene`` (error) — no ``import``/``fetch`` of ``.env`` /
   ``.env.local`` from client components; ``NEXTAUTH_SECRET`` must not
   be hardcoded to a string literal in source.
3. ``authz_*`` (error) — registry-driven: when
   ``contracts/resource-registry.json`` (or ``src/contracts/``)
   declares a non-public access model, the enforcement chain must be
   present: ``src/middleware.ts``, ``src/auth.ts``, and the vendored
   rules runtime ``src/lib/rules/`` (what
   :mod:`services.runtime_injector` copies from
   ``templates/runtime/rules``).
4. ``npm_audit_*`` (error / warning) — ``npm audit --omit=dev --json``
   with a 60s timeout when a lockfile exists; audit infra problems
   (no lockfile, no npm, no network, timeout) degrade to a ``skipped``
   note — the gate never hangs or fails on audit plumbing.
5. ``config_*`` (warning) — next.config must not silently disable BOTH
   eslint and typescript build checks; ``poweredByHeader: false``
   recommended.

**B. Live authz probes** (:func:`run_live_authz_probes` — only when a
``base_url`` is given): every registry entity's ``/api/data/<slug>``
collection endpoint is probed UNAUTHENTICATED; anything other than
401/403/302/307 is suspect, and a 200 that returns rows is a critical
``anon_read`` finding (strongest when the access model marks the
entity admin-only). No logins are ever attempted — no credentials are
handled. The static gate never requires a running server.

Report: ``<output_dir>/security-report.json`` —
``{"passed", "errors", "warnings", "skipped", ...}`` where each error
is ``{"rule", "file"?, "line"?, "detail", "severity"}`` and severity is
``"critical"`` (secrets, anon_read) or ``"error"``.

The delivery gate folds these static results in as its ``security``
rule family (see :func:`services.delivery_gate.run_delivery_gate`).
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

REPORT_NAME = "security-report.json"

# ── scan surface ─────────────────────────────────────────────────────

_SCAN_DIRS = ("src", "workflows", "contracts")
_SKIP_DIRS = {"node_modules", ".next", ".git", ".turbo", "dist"}
_TEXT_EXTS = {
    ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json",
    ".yml", ".yaml", ".sql", ".css", ".md", ".txt",
}
_MAX_FILE_BYTES = 2 * 1024 * 1024  # skip anything bigger — not source

# (rule-detail label, pattern, severity). Postgres URLs are "error"
# (often local/dummy creds); the rest are unambiguous live-secret
# shapes → "critical".
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("anthropic_api_key", re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}"), "critical"),
    ("live_secret_key", re.compile(r"sk[-_]live[-_]?[A-Za-z0-9]{8,}"), "critical"),
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}"), "critical"),
    ("vercel_token", re.compile(r"vercel_[A-Za-z0-9]{16,}"), "critical"),
    ("private_key_block",
     re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "critical"),
    ("postgres_url_with_password",
     re.compile(r"postgres(?:ql)?://[^\s\"'`]+:[^\s\"'`@]+@[^\s\"'`]+"),
     "error"),
]

_ENV_FILE_IMPORT = re.compile(
    r"""(?:import\s+[^;\n]*['"][^'"]*\.env(?:\.local)?['"]"""
    r"""|fetch\(\s*['"][^'"]*\.env(?:\.local)?['"])"""
)
_NEXTAUTH_HARDCODED = re.compile(
    r"""NEXTAUTH_SECRET['"]?\s*[:=]\s*['"][^'"]+['"]"""
)

_PUBLIC_ROLES = {"public", "anonymous", "anon", "guest", "everyone"}
_ADMIN_ROLES = {"admin", "administrator", "superadmin", "owner"}

# Live-probe statuses that prove the endpoint rejects anonymous access.
_AUTH_REJECT_STATUSES = (401, 403, 302, 307)


# ── small helpers ────────────────────────────────────────────────────

def _redact(value: str) -> str:
    """First 6 chars + ellipsis — the report must never contain the
    secret itself."""
    return value[:6] + "…"


def _load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _read_text(path: Path) -> str:
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:  # noqa: BLE001
        return ""


def _iter_source_files(root: Path) -> list[Path]:
    """Every scannable source file: src/, workflows/, contracts/ plus
    root-level next.config.* and package.json. Skips node_modules,
    .next, .git and all ``.env*`` files (env files are the sanctioned
    home for connection strings)."""
    out: list[Path] = []
    for d in _SCAN_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            if any(part in _SKIP_DIRS for part in p.relative_to(root).parts):
                continue
            if p.name.startswith(".env"):
                continue
            if p.suffix.lower() not in _TEXT_EXTS:
                continue
            out.append(p)
    for pattern in ("next.config.*", "package.json"):
        for p in sorted(root.glob(pattern)):
            if p.is_file() and not p.name.startswith(".env"):
                out.append(p)
    return out


def _rel(root: Path, p: Path) -> str:
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


# ── A1: secret-leakage scan ──────────────────────────────────────────

def scan_secrets(root: Path) -> list[dict]:
    """High-confidence secret patterns in emitted source, redacted."""
    findings: list[dict] = []
    for path in _iter_source_files(root):
        text = _read_text(path)
        if not text:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for label, pattern, severity in _SECRET_PATTERNS:
                for m in pattern.finditer(line):
                    match = m.group(0)
                    # Env-var indirection is the CORRECT pattern —
                    # `postgres://u:${DB_PASSWORD}@…` is not a leak.
                    if "${" in match or "process.env" in match:
                        continue
                    findings.append({
                        "rule": "secret_leak",
                        "file": _rel(root, path),
                        "line": lineno,
                        "detail": f"{label}: {_redact(match)}",
                        "severity": severity,
                    })
    return findings


# ── A2: env hygiene ──────────────────────────────────────────────────

def check_env_hygiene(root: Path) -> list[dict]:
    """No .env imports/fetches from client components; no hardcoded
    NEXTAUTH_SECRET string literal anywhere in source."""
    findings: list[dict] = []
    for path in _iter_source_files(root):
        text = _read_text(path)
        if not text:
            continue
        is_client = '"use client"' in text[:500] or "'use client'" in text[:500]
        for lineno, line in enumerate(text.splitlines(), start=1):
            if is_client and _ENV_FILE_IMPORT.search(line):
                findings.append({
                    "rule": "env_hygiene",
                    "file": _rel(root, path),
                    "line": lineno,
                    "detail": "client component references a .env file "
                              "directly — env files must never reach the "
                              "client bundle",
                    "severity": "error",
                })
            if _NEXTAUTH_HARDCODED.search(line):
                findings.append({
                    "rule": "env_hygiene",
                    "file": _rel(root, path),
                    "line": lineno,
                    "detail": "NEXTAUTH_SECRET hardcoded in source — must "
                              "come from the environment",
                    "severity": "error",
                })
    return findings


# ── A3: registry-driven authz coverage ───────────────────────────────

def _load_registry(root: Path) -> dict:
    """resource-registry.json — apps historically wrote it under
    contracts/; check src/contracts/ first for forward-compat."""
    for rel in (("src", "contracts"), ("contracts",)):
        doc = _load_json(root.joinpath(*rel, "resource-registry.json"))
        if isinstance(doc, dict):
            return doc
    return {}


def _role_names(registry: dict) -> list[str]:
    am = registry.get("accessModel") or {}
    raw = (am.get("roles") or []) or (registry.get("roles") or [])
    names: list[str] = []
    for r in raw:
        name = r.get("name") if isinstance(r, dict) else r
        if isinstance(name, str) and name.strip():
            names.append(name.strip().lower())
    return names


def _requires_authz(registry: dict) -> bool:
    """True when the registry declares an access model that actually
    needs enforcement: any non-public role, or structured role rules."""
    if not registry:
        return False
    nonpublic = [r for r in _role_names(registry) if r not in _PUBLIC_ROLES]
    am = registry.get("accessModel") or {}
    structured_rules = [r for r in (am.get("rules") or []) if isinstance(r, dict)]
    return bool(nonpublic or structured_rules)


def check_authz_coverage(root: Path) -> list[dict]:
    """When the access model has teeth, the enforcement chain must
    exist: middleware (route gating), auth (identity), rules runtime
    (field/row ACLs — vendored by runtime_injector to src/lib/rules)."""
    registry = _load_registry(root)
    if not _requires_authz(registry):
        return []

    findings: list[dict] = []
    if not (root / "src" / "middleware.ts").is_file():
        findings.append({
            "rule": "authz_middleware_missing",
            "file": "src/middleware.ts",
            "detail": "registry declares role-based access but "
                      "src/middleware.ts is absent — no route gating",
            "severity": "error",
        })
    if not (root / "src" / "auth.ts").is_file():
        findings.append({
            "rule": "authz_auth_missing",
            "file": "src/auth.ts",
            "detail": "registry declares role-based access but src/auth.ts "
                      "is absent — no identity provider",
            "severity": "error",
        })
    rules_dir = root / "src" / "lib" / "rules"
    has_runtime = rules_dir.is_dir() and any(rules_dir.glob("*.ts"))
    if not has_runtime:
        findings.append({
            "rule": "authz_rules_runtime_missing",
            "file": "src/lib/rules/",
            "detail": "registry declares role-based access but the vendored "
                      "rules runtime (src/lib/rules/) is absent — ACL rules "
                      "cannot evaluate",
            "severity": "error",
        })
    return findings


# ── A4: dependency audit ─────────────────────────────────────────────

def run_npm_audit(root: Path) -> tuple[list[dict], list[dict], list[dict]]:
    """(errors, warnings, skipped). Audit infra failures always land in
    ``skipped`` — the gate must never hang or fail on npm plumbing."""
    if not (root / "package.json").is_file():
        return [], [], [{"rule": "npm_audit",
                         "detail": "skipped: no package.json"}]
    if not any((root / n).is_file()
               for n in ("package-lock.json", "npm-shrinkwrap.json")):
        return [], [], [{"rule": "npm_audit",
                         "detail": "skipped: no lockfile"}]
    try:
        proc = subprocess.run(
            ["npm", "audit", "--omit=dev", "--json"],
            cwd=str(root), capture_output=True, text=True, timeout=60,
        )
        data = json.loads(proc.stdout or "{}")
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError,
            json.JSONDecodeError) as exc:
        return [], [], [{"rule": "npm_audit",
                         "detail": f"skipped: audit unavailable ({type(exc).__name__})"}]
    if not isinstance(data, dict) or "error" in data:
        return [], [], [{"rule": "npm_audit",
                         "detail": "skipped: npm audit errored (registry/network)"}]

    vulns = (data.get("metadata") or {}).get("vulnerabilities") or {}
    critical = int(vulns.get("critical") or 0)
    high = int(vulns.get("high") or 0)
    errors: list[dict] = []
    warnings: list[dict] = []
    if critical:
        errors.append({
            "rule": "npm_audit_critical",
            "detail": f"{critical} critical advisory(ies) in production "
                      "dependencies",
            "severity": "error",
        })
    if high:
        warnings.append({
            "rule": "npm_audit_high",
            "detail": f"{high} high advisory(ies) in production dependencies",
            "severity": "warning",
        })
    return errors, warnings, []


# ── A5: next.config checks ───────────────────────────────────────────

def check_next_config(root: Path) -> list[dict]:
    warnings: list[dict] = []
    for path in sorted(root.glob("next.config.*")):
        text = _read_text(path)
        if not text:
            continue
        rel = _rel(root, path)
        if (re.search(r"ignoreDuringBuilds\s*:\s*true", text)
                and re.search(r"ignoreBuildErrors\s*:\s*true", text)):
            warnings.append({
                "rule": "config_build_checks_disabled",
                "file": rel,
                "detail": "eslint.ignoreDuringBuilds AND "
                          "typescript.ignoreBuildErrors are both true — the "
                          "build silently skips every static check",
                "severity": "warning",
            })
        if not re.search(r"poweredByHeader\s*:\s*false", text):
            warnings.append({
                "rule": "config_powered_by_header",
                "file": rel,
                "detail": "poweredByHeader: false recommended — avoid "
                          "advertising the framework version",
                "severity": "warning",
            })
    return warnings


# ── B: live authz probes ─────────────────────────────────────────────

def _entity_slugs(registry: dict) -> list[str]:
    ents = registry.get("entities")
    items: list[Any]
    if isinstance(ents, dict):
        items = list(ents.values())
    elif isinstance(ents, list):
        items = ents
    else:
        return []
    slugs: list[str] = []
    for e in items:
        if not isinstance(e, dict):
            continue
        slug = e.get("slug") or e.get("id")
        if isinstance(slug, str) and slug.strip():
            slugs.append(slug.strip())
    return slugs


def _admin_only_slugs(registry: dict) -> set[str]:
    """Best-effort: entities the access model restricts to admin-ish
    roles only (the strongest anon_read class)."""
    out: set[str] = set()
    am = registry.get("accessModel") or {}
    for rule in am.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        ent = rule.get("entity") or rule.get("resource") or rule.get("entityId")
        roles = rule.get("roles") or []
        if not isinstance(ent, str) or not isinstance(roles, list) or not roles:
            continue
        names = {str(r.get("name") if isinstance(r, dict) else r).lower()
                 for r in roles}
        if names and names <= _ADMIN_ROLES:
            out.add(ent)
    return out


def _response_rows(resp: Any) -> list:
    """Rows out of a data-engine collection response, tolerant of the
    common envelope shapes."""
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        return []
    if isinstance(body, list):
        return body
    if isinstance(body, dict):
        for key in ("rows", "data", "items", "results"):
            v = body.get(key)
            if isinstance(v, list):
                return v
    return []


def run_live_authz_probes(output_dir: str | Path, base_url: str) -> list[dict]:
    """Probe every registry entity's ``/api/data/<slug>`` collection
    endpoint UNAUTHENTICATED. 401/403/302/307 = correctly rejected;
    200 with rows = critical ``anon_read``. Never attempts a login.
    Standalone — the static gate does not require a server."""
    root = Path(output_dir)
    registry = _load_registry(root)
    admin_only = _admin_only_slugs(registry)
    base = base_url.rstrip("/")

    findings: list[dict] = []
    for slug in _entity_slugs(registry):
        url = f"{base}/api/data/{slug}"
        try:
            resp = httpx.get(url, timeout=10.0, follow_redirects=False)
        except Exception as exc:  # noqa: BLE001 — network is untrusted
            findings.append({
                "rule": "probe_unreachable", "slug": slug, "url": url,
                "detail": f"probe failed: {type(exc).__name__}", "ok": False,
            })
            continue
        status = resp.status_code
        if status in _AUTH_REJECT_STATUSES:
            findings.append({
                "rule": "authz_probe", "slug": slug, "url": url,
                "status": status, "ok": True,
                "detail": f"anonymous GET rejected ({status})",
            })
        elif status == 200:
            rows = _response_rows(resp)
            if rows:
                findings.append({
                    "rule": "anon_read", "slug": slug, "url": url,
                    "status": 200, "ok": False, "severity": "critical",
                    "admin_only": slug in admin_only,
                    "detail": f"anonymous GET returned {len(rows)} row(s)"
                              + (" on an ADMIN-ONLY entity"
                                 if slug in admin_only else ""),
                })
            else:
                findings.append({
                    "rule": "anon_read", "slug": slug, "url": url,
                    "status": 200, "ok": False, "severity": "error",
                    "admin_only": slug in admin_only,
                    "detail": "anonymous GET returned 200 (no rows) — "
                              "endpoint is open to unauthenticated access",
                })
        else:
            findings.append({
                "rule": "authz_probe_unexpected_status", "slug": slug,
                "url": url, "status": status, "ok": False,
                "severity": "warning",
                "detail": f"expected 401/403/302/307, got {status}",
            })
    return findings


# ── gate entry point ─────────────────────────────────────────────────

def run_security_gate(output_dir: str, base_url: str | None = None) -> dict:
    """Run every static check (plus live probes when ``base_url`` is
    given), write ``security-report.json`` into ``output_dir``, return
    the report. Never raises — a broken gate must not break generation.
    """
    root = Path(output_dir)
    errors: list[dict] = []
    warnings: list[dict] = []
    skipped: list[dict] = []

    checks: list[tuple[str, Any]] = [
        ("secret_scan", lambda: scan_secrets(root)),
        ("env_hygiene", lambda: check_env_hygiene(root)),
        ("authz_coverage", lambda: check_authz_coverage(root)),
        ("next_config", lambda: check_next_config(root)),
    ]
    for name, fn in checks:
        try:
            for f in fn():
                (errors if f.get("severity") in ("critical", "error")
                 else warnings).append(f)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[security-gate] %s check crashed", name)
            skipped.append({"rule": name,
                            "detail": f"skipped: check crashed ({exc})"})

    try:
        a_errs, a_warns, a_skips = run_npm_audit(root)
        errors += a_errs
        warnings += a_warns
        skipped += a_skips
    except Exception as exc:  # noqa: BLE001
        logger.exception("[security-gate] npm audit crashed")
        skipped.append({"rule": "npm_audit",
                        "detail": f"skipped: check crashed ({exc})"})

    live_probes: list[dict] | None = None
    if base_url:
        try:
            live_probes = run_live_authz_probes(output_dir, base_url)
            for f in live_probes:
                sev = f.get("severity")
                if sev in ("critical", "error"):
                    errors.append(f)
                elif sev == "warning":
                    warnings.append(f)
        except Exception as exc:  # noqa: BLE001
            logger.exception("[security-gate] live probes crashed")
            skipped.append({"rule": "live_authz_probes",
                            "detail": f"skipped: probes crashed ({exc})"})

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "skipped": skipped,
    }
    if live_probes is not None:
        report["live_probes"] = live_probes

    try:
        root.mkdir(parents=True, exist_ok=True)
        (root / REPORT_NAME).write_text(
            json.dumps(report, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[security-gate] report write failed: %s", exc)

    if errors:
        logger.warning(
            "[security-gate] %d error(s), %d warning(s) — see %s",
            len(errors), len(warnings), REPORT_NAME,
        )
    return report


__all__ = [
    "check_authz_coverage",
    "check_env_hygiene",
    "check_next_config",
    "run_live_authz_probes",
    "run_npm_audit",
    "run_security_gate",
    "scan_secrets",
]
