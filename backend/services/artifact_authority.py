"""Artifact Authority — Phase 6 of the pipeline cleanup.

Extends Phase 3's "one writer per artifact" pattern from dashboards to
collections + records. The Phase-3 module :mod:`services.dashboard_authority`
holds the dashboard-only shape (kept as-is for back-compat); this
module holds the generic version so downstream sites (LLM skip, composer
bootstrap, guard assertions) can key off a single vocabulary.

Four artifact kinds today:
- ``dashboard`` — Phase 3 (already shipped; delegates to
  :mod:`services.dashboard_authority`)
- ``collection`` — Phase 6a: sole writer is
  :mod:`services.apply_collection_maquette`
- ``record`` — Phase 6b: sole writer is
  :mod:`services.apply_record_maquette`
- ``shell`` — Phase 6c: sole writer is
  :func:`services.shell_templates.build_shell_deterministic` (or the
  brief-driven bridge :func:`services.shell_from_brief.build_shell_from_brief`).
  Marker: ``shell_deterministic_composed`` stamped on the shell schema.

Each artifact gets its own env gate (four flags, staged rollout):

- ``FORGE_DASHBOARD_AUTHORITY``  (Phase 3)
- ``FORGE_COLLECTION_AUTHORITY`` (Phase 6a)
- ``FORGE_RECORD_AUTHORITY``     (Phase 6b)
- ``FORGE_SHELL_AUTHORITY``      (Phase 6c)

All four are ON by default. ``dashboard`` follows
:mod:`services.dashboard_authority`; the other three read their own env var
and treat only an explicit 0/false/no/off as opt-out. They defaulted OFF
until the composers were proven; a permanently-off feature gate is just
dead code with a switch on it.
"""
from __future__ import annotations

import os
from typing import Any, Literal


# ─────────────────────────── vocabulary ────────────────────────────────


ArtifactKind = Literal["dashboard", "collection", "record", "shell"]

_ARTIFACT_KINDS: frozenset[str] = frozenset({"dashboard", "collection", "record", "shell"})

# Env gate per artifact. Kept in one dict so tests + docs have a single
# reference and adding a fifth artifact is a single-line change.
_FLAG_ENV: dict[str, str] = {
    "dashboard": "FORGE_DASHBOARD_AUTHORITY",
    "collection": "FORGE_COLLECTION_AUTHORITY",
    "record": "FORGE_RECORD_AUTHORITY",
    "shell": "FORGE_SHELL_AUTHORITY",
}

# Composer marker per artifact. Kept in sync with each composer's
# marker constant:
# - services/apply_dashboard_maquette.py:  "maquette_composed"
# - services/apply_collection_maquette.py: "collection_maquette_composed"
# - services/apply_record_maquette.py:     "record_maquette_composed"
# - services/shell_templates.py (via generate_shell_to_file): "shell_deterministic_composed"
_MARKER_KEY: dict[str, str] = {
    "dashboard": "maquette_composed",
    "collection": "collection_maquette_composed",
    "record": "record_maquette_composed",
    "shell": "shell_deterministic_composed",
}

# Page-type strings the planner emits per artifact. Kept as sets so a
# new synonym (e.g. planner emits "board" instead of "kanban") is a
# single-line change. Values are matched case-insensitively and after
# stripping.
#
# ``shell`` intentionally has no page-type entries — the shell isn't a
# ``plan.pages`` row; it's a top-level ``shell.json`` file authored by
# ``generate_shell_to_file``. The flag still enables + the marker
# still lets guards recognise composer-authored shells.
_PAGE_TYPES: dict[str, frozenset[str]] = {
    "dashboard": frozenset({"dashboard", "overview", "home"}),
    "collection": frozenset({
        "list", "kanban", "calendar", "cards", "timeline", "board", "grid",
    }),
    "record": frozenset({
        "form", "detail", "create", "edit", "record", "new",
    }),
    "shell": frozenset(),  # shell is a singleton, not a page-typed row
}


# ─────────────────────────── env gate ──────────────────────────────────


_OFF_VALUES: frozenset[str] = frozenset({"0", "false", "no", "off"})


def _truthy(raw: str) -> bool:
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def is_authority_enabled(artifact: ArtifactKind | str) -> bool:
    """Return True when the Phase-3/6 authority is on for ``artifact``.

    Off by default. Unknown ``artifact`` returns False. Reads the env
    per-call so tests can flip mid-flight.
    """
    key = str(artifact)
    if key not in _ARTIFACT_KINDS:
        return False
    if key == "dashboard":
        # Delegate, don't re-read. ``dashboard_authority`` is Phase 3's
        # module and owns the dashboard flag's default; duplicating the
        # env read here let the two disagree once that default changed
        # (dashboard_authority defaults ON, a bare os.environ.get()
        # defaults OFF) — so every guard keyed off THIS module stayed in
        # rewrite mode against composer-authored dashboards.
        from services.dashboard_authority import is_dashboard_authority_enabled
        return is_dashboard_authority_enabled()
    env_name = _FLAG_ENV.get(key)
    if env_name is None:
        return False
    # ON unless explicitly opted out. A blank default meant these composers
    # were sole writer in code and never once on a real build — the flag
    # gated the feature into non-existence rather than gating its risk.
    # Opt out per artifact with FORGE_<KIND>_AUTHORITY=0.
    raw = os.environ.get(env_name, "").strip().lower()
    if raw in _OFF_VALUES:
        return False
    return True


# ─────────────────────────── page-type test ────────────────────────────


def is_page_of_kind(page: dict[str, Any] | None, artifact: ArtifactKind | str) -> bool:
    """Return True when ``page`` is of the given artifact kind.

    Reads ``page.type`` first, falling back to ``page.archetype``.
    Case-insensitive, trimmed. ``None`` / missing / non-dict safely
    returns False.
    """
    if not isinstance(page, dict):
        return False
    types = _PAGE_TYPES.get(str(artifact))
    if not types:
        return False
    for key in ("type", "archetype"):
        v = page.get(key)
        if isinstance(v, str) and v.strip().lower() in types:
            return True
    return False


# ─────────────────────────── composed marker ──────────────────────────


def is_composer_authored(
    schema: dict[str, Any] | None,
    artifact: ArtifactKind | str,
) -> bool:
    """Return True when ``schema`` was written by the composer for ``artifact``.

    Each composer stamps a distinct meta key (see :data:`_MARKER_KEY`) so
    a collection maquette-composed schema isn't confused with a dashboard.
    """
    if not isinstance(schema, dict):
        return False
    meta = schema.get("meta")
    if not isinstance(meta, dict):
        return False
    marker = _MARKER_KEY.get(str(artifact))
    if marker is None:
        return False
    return meta.get(marker) is True


def should_assert_only(
    schema: dict[str, Any] | None,
    artifact: ArtifactKind | str,
) -> bool:
    """Return True when a guard should ASSERT drift (not rewrite) for
    ``artifact`` on ``schema``.

    Combines the authority flag + composer marker into ONE call the
    guards can make before their mutation loop. Kept here so a follow-up
    (per-guard opt-out, per-page override, etc.) has a single place to
    change.
    """
    return is_authority_enabled(artifact) and is_composer_authored(schema, artifact)


def is_composer_authored_any(schema: dict[str, Any] | None) -> tuple[bool, str | None]:
    """Return ``(True, artifact)`` if ``schema`` was composed by ANY known
    composer, else ``(False, None)``.

    Useful for guards that touch multiple artifact kinds (e.g.
    :mod:`services.surface_wrap_guard` runs on every schema) — they can
    call this once and take the assert path when any artifact's flag is
    on for a schema they touched.
    """
    if not isinstance(schema, dict):
        return (False, None)
    meta = schema.get("meta")
    if not isinstance(meta, dict):
        return (False, None)
    for artifact, marker in _MARKER_KEY.items():
        if meta.get(marker) is True:
            return (True, artifact)
    return (False, None)


def should_assert_only_any(schema: dict[str, Any] | None) -> bool:
    """Return True if this schema was written by ANY composer whose
    authority flag is currently on. Cross-artifact guards use this.

    Semantics: assert-only mode kicks in when the SAME artifact's flag
    is on for the schema's marker. A collection composer's marker
    doesn't trigger assert-mode under the dashboard flag.
    """
    composed, artifact = is_composer_authored_any(schema)
    if not composed or artifact is None:
        return False
    return is_authority_enabled(artifact)
