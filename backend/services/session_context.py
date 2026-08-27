"""SessionContext — the shared substrate for pipeline stages and Smith.

Spec P2 (M5-T1): one Python object with seven fields that every
generation stage and every Smith tool call reads from. Same data
source, same names, same interpretation. No stage re-derives
``industry`` from ``brief.text``; no tool re-derives ``app_shape``
from filesystem shape — the context is authoritative.

This module owns the dataclass and its loader. It does NOT own:
- Stage integrations (each stage adopts the context argument as a
  separate M5-T2 PR).
- ``smith_memory`` (becomes a view onto this in M5-T3, but stays in
  its own module).
- Verify history (verify_stack.py writes to
  ``session_context.verify_history`` — see M5-T5).

Cheap to construct — reads plan.json + registry.json + vocabulary
JSONs (cached). Pass the same context object to every stage of a
single generation; recreate per generation.
"""
from __future__ import annotations

import contextvars
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional


# ══════════════════════════════════════════════════════════════════
# Types
# ══════════════════════════════════════════════════════════════════


@dataclass
class VerifyRecord:
    """One entry in the verify_history rolling buffer.
    See verify_stack.py (M5-T5) for the producer."""
    stage: str            # e.g. "page_schema_agent", "schema_builder"
    check: str            # e.g. "static", "structural", "domain_conformance"
    passed: bool
    findings: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: int = 0


@dataclass
class EditRecord:
    """One mutation entry. Written by Smith tools and by pipeline
    stages that mutate schemas (via recover_ladder wrap)."""
    stage: str
    intent: str
    files_touched: list[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class SessionContext:
    """Substrate shared by pipeline stages and Smith turns.

    Seven fields matching the spec:
    - ``plan`` — the current plan.json dict (source of truth)
    - ``shape_profile`` — resolved from plan.app_shape (loaded once)
    - ``industry_profile`` — resolved from plan.industry
    - ``archetype_profiles`` — resolved profiles for each
      ArchetypeInstance (recipe expansions)
    - ``registry`` — canonical resource registry (opaque dict; the
      SessionContext doesn't inspect it, only carries)
    - ``app_map`` — Smith's file-structure snapshot (opaque dict)
    - ``verify_history`` / ``edit_history`` — rolling buffers, most
      recent first
    """
    plan: dict[str, Any]
    shape_profile: dict[str, Any] = field(default_factory=dict)
    industry_profile: dict[str, Any] = field(default_factory=dict)
    archetype_profiles: dict[str, dict[str, Any]] = field(default_factory=dict)
    registry: dict[str, Any] = field(default_factory=dict)
    app_map: dict[str, Any] = field(default_factory=dict)
    verify_history: list[VerifyRecord] = field(default_factory=list)
    edit_history: list[EditRecord] = field(default_factory=list)

    # ────────────────────────────────────────────────────────────
    # Convenience accessors — thin wrappers that keep stages from
    # reaching into raw plan dict.
    # ────────────────────────────────────────────────────────────

    @property
    def industry(self) -> str:
        return str(self.plan.get("industry") or "")

    @property
    def archetypes(self) -> list[dict[str, Any]]:
        val = self.plan.get("archetypes")
        return list(val) if isinstance(val, list) else []

    @property
    def runtime_context(self) -> list[str]:
        val = self.plan.get("runtime_context")
        return [str(v) for v in val] if isinstance(val, list) else []

    def record_verify(self, entry: VerifyRecord, *, max_history: int = 50) -> None:
        """Prepend a verify entry. Rolling buffer bounded to max_history."""
        self.verify_history.insert(0, entry)
        if len(self.verify_history) > max_history:
            del self.verify_history[max_history:]

    def record_edit(self, entry: EditRecord, *, max_history: int = 50) -> None:
        """Prepend an edit entry. Rolling buffer bounded to max_history."""
        self.edit_history.insert(0, entry)
        if len(self.edit_history) > max_history:
            del self.edit_history[max_history:]

    def last_verify(self, stage: str | None = None) -> VerifyRecord | None:
        """Return the most recent verify entry (optionally filtered by
        stage name). Used by Smith to know current health before
        mutating."""
        if stage is None:
            return self.verify_history[0] if self.verify_history else None
        for entry in self.verify_history:
            if entry.stage == stage:
                return entry
        return None


# ══════════════════════════════════════════════════════════════════
# Loaders
# ══════════════════════════════════════════════════════════════════


def load_from_output_dir(output_dir: str | Path) -> SessionContext:
    """Build a SessionContext by reading plan.json + registry.json
    from a generated app's output directory.

    Missing files yield empty subtrees — the context stays usable, and
    downstream stages/tools that need a specific field can detect its
    absence and skip. Never raises on filesystem hiccups (best-effort).

    ``shape_profile``, ``industry_profile``, and ``archetype_profiles``
    are lazily resolved from the plan; the loader does not inject
    stub profiles — that's the vocabulary loader's job.
    """
    root = Path(output_dir)
    plan = _read_json(root / "plan.json") or _read_json(root / "contracts" / "plan.json") or {}
    registry = _read_json(root / "registry.json") or _read_json(root / "contracts" / "registry.json") or {}

    ctx = SessionContext(plan=plan, registry=registry)
    if isinstance(plan.get("app_shape"), dict):
        ctx.shape_profile = _deep_copy(plan["app_shape"])
    ctx.archetype_profiles = _resolve_archetype_profiles(plan)
    return ctx


def _resolve_archetype_profiles(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """For each ArchetypeInstance in plan, resolve its capabilities
    (recipe expansion + composed overrides) into a name-keyed dict.
    Uses the signature_moves_guard.resolve_effective_capabilities
    helper so we don't duplicate the resolution logic."""
    # Local import to avoid circular dependency on module import
    # (signature_moves_guard imports nothing from here).
    from services.signature_moves_guard import resolve_effective_capabilities

    out: dict[str, dict[str, Any]] = {}
    for instance in plan.get("archetypes") or []:
        if not isinstance(instance, dict):
            continue
        name = instance.get("name")
        if not name:
            continue
        caps = resolve_effective_capabilities(instance)
        out[str(name)] = caps
    return out


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _deep_copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _deep_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_copy(v) for v in value]
    return value


# ══════════════════════════════════════════════════════════════════
# Test-only constructor — build a context from raw data
# (production always goes through load_from_output_dir).
# ══════════════════════════════════════════════════════════════════


def from_plan(plan: dict[str, Any], *, registry: dict[str, Any] | None = None) -> SessionContext:
    """Convenience for tests + Smith warmup — build a context from a
    plan dict without needing a filesystem output directory."""
    ctx = SessionContext(plan=plan, registry=registry or {})
    if isinstance(plan.get("app_shape"), dict):
        ctx.shape_profile = _deep_copy(plan["app_shape"])
    ctx.archetype_profiles = _resolve_archetype_profiles(plan)
    return ctx


# ══════════════════════════════════════════════════════════════════
# T2-lite — ambient current-context accessor (ContextVar)
#
# Avoids threading `session_context` through 20 pipeline call sites.
# Any stage / guard / Smith tool that WANTS the current context calls
# ``current()`` and gets ``SessionContext | None``. The entry point
# (``_run_relay_pipeline`` or a Smith turn handler) calls ``set_current(ctx)``
# once. Uses ``contextvars`` so async pipeline concurrency stays correct
# per-request.
# ══════════════════════════════════════════════════════════════════


_CURRENT: contextvars.ContextVar[SessionContext | None] = contextvars.ContextVar(
    "forge_session_context", default=None,
)


def current() -> SessionContext | None:
    """Return the ambient SessionContext for the current
    request / pipeline run, or None when none has been set.

    Callers should treat ``None`` as "no ambient context available" and
    fall back to their pre-substrate behavior — never raise."""
    return _CURRENT.get()


def set_current(ctx: SessionContext | None) -> contextvars.Token:
    """Set the ambient SessionContext. Returns a token the caller can
    pass to ``reset_current`` to restore the previous value (useful for
    nested contexts or tests). In a pipeline run, set once at the top
    and don't reset — the async task naturally scopes it."""
    return _CURRENT.set(ctx)


def reset_current(token: contextvars.Token) -> None:
    """Restore the previous ambient SessionContext (from ``set_current``)."""
    _CURRENT.reset(token)


# ══════════════════════════════════════════════════════════════════
# T2-lite — persistence
#
# verify_history + edit_history live in memory during a run. To let
# Smith read them across turns (M5-T9 acceptance) we snapshot them to
# disk at the pipeline's end. Not the plan.json — a sibling file the
# pipeline owns.
# ══════════════════════════════════════════════════════════════════


HISTORY_FILENAME = "session_history.json"


def _history_path(output_dir: str | Path) -> Path:
    return Path(output_dir) / "src" / "contracts" / HISTORY_FILENAME


def persist_history(ctx: SessionContext, output_dir: str | Path) -> Path | None:
    """Snapshot verify_history + edit_history to disk.

    Returns the written path, or ``None`` when the contracts dir doesn't
    exist and can't be created (test-tolerant; never raises)."""
    try:
        p = _history_path(output_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "verify_history": [asdict(v) for v in ctx.verify_history],
            "edit_history": [asdict(e) for e in ctx.edit_history],
        }
        p.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                     encoding="utf-8")
        return p
    except OSError:
        return None


def load_history(output_dir: str | Path) -> dict[str, Any] | None:
    """Read the persisted history file back, or ``None`` when absent /
    malformed. Kept simple — returns a raw dict, not typed records, so
    Smith can render it without needing our dataclasses."""
    p = _history_path(output_dir)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None
