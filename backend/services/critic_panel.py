"""IRF-M5-T8 — multi-perspective critic panel.

Runs all three critic personas (``design`` / ``ux`` / ``correctness``)
against a single page schema and returns an aggregated verdict.

M5 wires the plumbing; the hard-threshold REVISE loop is a follow-up
(M6-T8 promotes the design critic from shadow → enforcement + tunes
rubrics). This module provides:

- ``run_panel(page_schema, plan, route)`` — invoke every persona,
  return a ``PanelReport`` naming which personas passed vs. failed
  and the aggregated finding list.
- ``PanelReport.needs_revise`` — True when any persona reported an
  ``error``-severity finding. A caller wire-up can consult this to
  fire a REVISE turn.
- Records one ``VerifyRecord`` per persona to the ambient
  ``SessionContext`` so Smith sees the trace via ``session_history``.

Flag: ``FORGE_CRITIC_PANEL`` (default off). When off, ``run_panel``
runs record-only (findings computed + recorded, but ``needs_revise``
is always False so callers don't act on it). Lets stages call the
panel unconditionally today and flip the flag later.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from services.critic_personas import PERSONA_REGISTRY
from services.session_context import VerifyRecord, current

logger = logging.getLogger(__name__)


# ── flag ────────────────────────────────────────────────────────────


def is_enabled() -> bool:
    return os.getenv("FORGE_CRITIC_PANEL", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _shape_triggers_enforcement(plan: Any) -> bool:
    """IRF-M6-T8 — enforcement trigger derived from effective shape.

    The design critic promotes from shadow → enforcement when the app's
    ``identity.usageMode`` is consumer-facing (single-session /
    public-anonymous) OR ``layout.hero`` is not ``none`` (heroic pages
    demand a distinctive look). Multi-user-team internal tools stay in
    shadow so a data-heavy workspace isn't penalised for looking sober.
    """
    if not isinstance(plan, dict):
        return False
    shape = plan.get("app_shape")
    if not isinstance(shape, dict):
        return False
    identity = shape.get("identity") or {}
    layout = shape.get("layout") or {}
    if isinstance(identity, dict) and identity.get("usageMode") in (
        "single-session", "public-anonymous",
    ):
        return True
    if isinstance(layout, dict):
        hero = layout.get("hero")
        if hero and hero != "none":
            return True
    return False


def enforcement_active(plan: Any) -> bool:
    """Whether the critic panel should promote to enforcement mode for
    this plan. Flag OR shape-trigger — either one flips it on."""
    return is_enabled() or _shape_triggers_enforcement(plan)


# ── types ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PersonaResult:
    """One critic persona's run."""
    persona: str
    passed: bool
    findings: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: int = 0


@dataclass(frozen=True)
class PanelReport:
    """Aggregate of all persona runs on one page."""
    stage: str
    route: str
    results: tuple[PersonaResult, ...]
    findings: list[dict[str, Any]] = field(default_factory=list)
    enforced: bool = False   # True when the flag was on for this run

    @property
    def passed(self) -> bool:
        """All personas passed (no error-severity findings)."""
        return all(r.passed for r in self.results)

    @property
    def failed_personas(self) -> tuple[str, ...]:
        return tuple(r.persona for r in self.results if not r.passed)

    @property
    def needs_revise(self) -> bool:
        """Caller consults this to decide whether to fire a REVISE
        loop. Only True when enforcement is active AND at least one
        persona failed — record-only mode never asks for revise."""
        return self.enforced and not self.passed

    def revise_notes(self) -> str:
        """Prescriptive-errors block a caller can prepend to the LLM
        re-authoring prompt (mirrors the DUR-1 pattern used by
        llm_edit). Empty when the panel passed."""
        if self.passed:
            return ""
        lines = ["## Design critic findings — please fix before re-emitting", ""]
        for r in self.results:
            if r.passed:
                continue
            lines.append(f"### {r.persona} critic — {len(r.findings)} finding(s)")
            for f in r.findings:
                if (f.get("severity") or "warning") != "error":
                    continue
                rule = f.get("rule") or "unknown"
                msg = f.get("message") or ""
                lines.append(f"- **{rule}**: {msg}")
            lines.append("")
        return "\n".join(lines).rstrip()


# ── revise loop cap ────────────────────────────────────────────────


MAX_REVISE_ATTEMPTS = 2
"""Design critic REVISE cap per M6-T8 spec (up to 2 revisions before
falling to the surface-treatment-pass fix). Callers thread their own
attempt counter and stop calling ``run_panel`` after this many."""


# ── public API ──────────────────────────────────────────────────────


def run_panel(
    page_schema: dict[str, Any],
    plan: dict[str, Any],
    route: str,
    *,
    stage: str = "page_schema_agent",
) -> PanelReport:
    """Run every critic persona and return an aggregated PanelReport.

    Records one ``VerifyRecord`` per persona to the ambient
    SessionContext (check name = ``critic:{persona}``) so Smith
    sees the per-persona trace.

    Never raises — persona callables are wrapped; a crashed critic
    becomes a `critic.crashed` finding rather than aborting the panel.
    """
    enforced = enforcement_active(plan)
    per_persona: list[PersonaResult] = []
    all_findings: list[dict[str, Any]] = []
    ctx = current()

    for name, fn in PERSONA_REGISTRY.items():
        started = time.monotonic()
        try:
            findings = fn(page_schema, plan, route) or []
        except Exception as exc:  # noqa: BLE001
            findings = [{
                "rule": f"critic.{name}.crashed",
                "message": f"{name} critic raised: {type(exc).__name__}: {exc}",
                "severity": "warning",   # crashed critic ≠ page failure
            }]
        elapsed = int((time.monotonic() - started) * 1000)
        for f in findings:
            f.setdefault("persona", name)
        passed = not any((f.get("severity") or "error") == "error" for f in findings)
        result = PersonaResult(
            persona=name, passed=passed,
            findings=list(findings), duration_ms=elapsed,
        )
        per_persona.append(result)
        all_findings.extend(findings)

        # Record to ambient session context
        if ctx is not None:
            try:
                ctx.record_verify(VerifyRecord(
                    stage=stage,
                    check=f"critic:{name}",
                    passed=passed,
                    findings=list(findings),
                    duration_ms=elapsed,
                ))
            except Exception:  # noqa: BLE001
                logger.debug("[critic_panel] record failed", exc_info=True)

    return PanelReport(
        stage=stage,
        route=route,
        results=tuple(per_persona),
        findings=all_findings,
        enforced=enforced,
    )


__all__ = [
    "PanelReport", "PersonaResult",
    "MAX_REVISE_ATTEMPTS",
    "enforcement_active", "is_enabled", "run_panel",
]
