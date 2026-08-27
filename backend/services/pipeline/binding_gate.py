"""Binding + registry validation gate — runs after post-generate fixes to
report bindings that still reference resources the backend doesn't have
(phantom workflow, non-existent dataSource, uuid-FK Input, etc.).

Extracted verbatim from :mod:`routers.generate` (Phase 1b of the pipeline
cleanup). See :mod:`services.pipeline.phases` for the extraction map.

Two exports:

- :func:`binding_gate_is_strict` — the mode-decision helper (pure).
- :func:`stream_binding_gate` — the async generator that emits SSE
  events. Both call sites in `routers.generate` delegate to it.
"""
from __future__ import annotations

import os
from typing import AsyncIterator

from sse_helpers import sse_event


def binding_gate_is_strict(env_value: str | None) -> bool:
    """Decide whether the binding+registry gate should FAIL generation.

    Strict-by-default: any error fails the build UNLESS the gate is explicitly
    disabled. The escape hatch is `FORGE_BINDING_GATE=warn` (also off/0/false/
    advisory), which downgrades the gate to advisory logging only.
      * unset / "strict" / "on" / "1" / "hard" → STRICT (True)
      * "warn" / "off" / "0" / "false" / "advisory" → warn-only (False)
    Unrecognized values default to STRICT (fail-safe: don't ship silently)."""
    mode = (env_value or "").strip().lower()
    if mode in ("warn", "off", "0", "false", "advisory"):
        return False
    return True


async def stream_binding_gate(output_dir: str) -> AsyncIterator[dict]:
    """Validate every UI binding against the real registries (Slice 1 gate).

    Runs AFTER the repair guards, so it reports what is STILL broken: a button
    dispatching a phantom workflow, a list bound to a non-existent dataSource, a
    free-text Input feeding a uuid FK column. Behind FORGE_BINDING_GATE
    (strict-by-default; escape hatch FORGE_BINDING_GATE=warn):
      * default / unset / "strict" / "on" → STRICT: any unresolved reference
        emits an error status and FAILS the generation.
      * "warn" (also off/0/false/advisory) → WARN-only: every unresolved
        reference is an SSE log line + a one-line summary (build still succeeds).
    Never crashes the pipeline (a validator bug degrades to a skip log line)."""
    try:
        from services.binding_validator import validate_bindings
        res = validate_bindings(output_dir)
    except Exception as _bg_ex:  # noqa: BLE001 — the gate must never fail the build
        yield sse_event("log", {"text": f"[BindingGate] skipped: {_bg_ex}"})
        return

    errors = res.get("errors") or []
    warnings = res.get("warnings") or []
    strict = binding_gate_is_strict(os.environ.get("FORGE_BINDING_GATE"))
    mode_label = "strict" if strict else "warn"

    # ── REGISTRY GATE (P5) — the canonical registry must be internally consistent.
    # Runs alongside the binding gate (same point, both pipelines) and behind the
    # same flag: its errors contribute to the strict-mode failure below. Never
    # lets a validator bug break generation.
    reg_errors: list = []
    try:
        from services.resource_registry_validator import validate_registry
        reg_res = validate_registry(output_dir)
        reg_errors = reg_res.get("errors") or []
        reg_warnings = reg_res.get("warnings") or []
        if reg_errors:
            yield sse_event("log", {
                "text": f"[RegistryGate] {len(reg_errors)} registry inconsistency(ies) "
                        f"({mode_label} mode):"
            })
            for e in reg_errors[:25]:
                yield sse_event("log", {
                    "text": f"[RegistryGate] ⚠ [{e.get('kind')}] {e.get('detail')}"
                })
            if len(reg_errors) > 25:
                yield sse_event("log", {"text": f"[RegistryGate] … +{len(reg_errors) - 25} more"})
        else:
            yield sse_event("log", {
                "text": f"[RegistryGate] ✓ registry references resolve "
                        f"({len(reg_warnings)} advisory warning(s))"
            })
    except Exception as _rg_ex:  # noqa: BLE001 — the gate must never fail the build
        yield sse_event("log", {"text": f"[RegistryGate] skipped: {_rg_ex}"})
        reg_errors = []

    if not errors and not reg_errors:
        yield sse_event("log", {
            "text": f"[BindingGate] ✓ all UI bindings resolve "
                    f"({len(warnings)} advisory warning(s))"
        })
        return

    if errors:
        yield sse_event("log", {
            "text": f"[BindingGate] {len(errors)} unresolved binding(s) "
                    f"({mode_label} mode):"
        })
        for e in errors[:25]:
            yield sse_event("log", {
                "text": f"[BindingGate] ⚠ {e.get('file')} [{e.get('kind')}] "
                        f"{e.get('ref')}: {e.get('detail')}"
            })
        if len(errors) > 25:
            yield sse_event("log", {"text": f"[BindingGate] … +{len(errors) - 25} more"})

    if strict:
        total = len(errors) + len(reg_errors)
        yield sse_event("status", {
            "message": f"Generation failed: {len(errors)} UI binding(s) + "
                       f"{len(reg_errors)} registry inconsistency(ies) reference "
                       f"resources the backend doesn't have (binding gate is "
                       f"strict-by-default; set FORGE_BINDING_GATE=warn to bypass)."
        })
        yield sse_event("error", {
            "message": f"binding_gate: {total} unresolved reference(s) "
                       f"({len(errors)} binding, {len(reg_errors)} registry)",
            "errors": (errors + reg_errors)[:25],
        })
