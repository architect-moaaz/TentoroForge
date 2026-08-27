"""Plan coherence checks — cross-field validators over the four axes
(M1-T9).

The per-axis validators in ``shape_profile.py`` check each field in
isolation (is ``layout.shell`` a valid value?). This module checks
**combinations** — the suspicious combos the spec calls out as
"planner probably made a mistake":

- ``layout.shell == "none"`` + ``nav.menu == "sidebar-links"`` — no
  shell to hold the menu.
- ``identity.usageMode == "single-session"`` + ``auth.gating ==
  "on-load"`` — asking anonymous users to log in before they see
  anything.
- ``workflows.executionMode == "fire-and-forget"`` +
  ``data.readShape == "single-record"`` — writing without reading
  back what we wrote (usually a mismatch).
- Archetype instance recipe/capabilities that clearly disagree with
  the outer shape (kanban module inside a hero-only shape).

Findings are ``warning`` by default — the LLM might have a valid
reason. The planner's REVISE loop (M1-T10) gets one chance to
either reconcile or restate the reason; if it stands its ground, we
trust it and proceed.

Pure functions, no I/O. Same ``Finding`` type as
``shape_profile.py`` for easy interop.
"""
from __future__ import annotations

from typing import Any

from services.shape_profile import Finding


# ══════════════════════════════════════════════════════════════════
# Public entry point
# ══════════════════════════════════════════════════════════════════


def check_plan_coherence(plan: dict[str, Any]) -> list[Finding]:
    """Run every coherence rule against a plan; return all findings.
    Never mutates the plan. Never raises. Order matters only for
    display; every rule runs independently."""
    findings: list[Finding] = []
    shape = plan.get("app_shape") or {}
    archetypes = plan.get("archetypes") or []

    findings.extend(_shell_vs_menu(shape))
    findings.extend(_single_session_vs_on_load_auth(shape))
    findings.extend(_fire_and_forget_vs_single_record(shape))
    findings.extend(_streaming_no_realtime_module(shape, archetypes))
    findings.extend(_hero_but_workspace_identity(shape))
    findings.extend(_module_shape_conflicts(shape, archetypes))
    findings.extend(_no_modules(archetypes))
    return findings


# ══════════════════════════════════════════════════════════════════
# Individual rules
# ══════════════════════════════════════════════════════════════════


def _shell_vs_menu(shape: dict[str, Any]) -> list[Finding]:
    """Shell-shaped menu on a shell-less layout is a mismatch — the
    menu has no chrome to render into. LLM should either add a shell
    or drop the menu."""
    layout = shape.get("layout") or {}
    nav = shape.get("nav") or {}
    shell = layout.get("shell")
    menu = nav.get("menu")
    if shell == "none" and menu in ("sidebar-links", "header-links"):
        return [Finding(
            rule="coherence.shell_none_with_chrome_menu",
            message=(
                f"layout.shell=none but nav.menu={menu!r}. A shell-less "
                "app has no chrome to render menu links into. Either "
                "add a shell (sidebar / header) or set nav.menu to "
                "'none', 'bottom-tabs', 'drawer', or 'command-palette'."
            ),
            severity="warning",
            axis="app_shape",
        )]
    return []


def _single_session_vs_on_load_auth(shape: dict[str, Any]) -> list[Finding]:
    """Single-session identity + on-load auth = a login wall in front
    of a consumer utility. Almost always wrong."""
    auth = shape.get("auth") or {}
    identity = shape.get("identity") or {}
    if identity.get("usageMode") == "single-session" and auth.get("gating") == "on-load":
        return [Finding(
            rule="coherence.single_session_gated_on_load",
            message=(
                "identity.usageMode=single-session + auth.gating=on-load: "
                "asking anonymous users to authenticate before seeing "
                "anything defeats the purpose of a single-session utility. "
                "Prefer auth.gating=on-action or auth.surface=none."
            ),
            severity="warning",
            axis="app_shape",
        )]
    return []


def _fire_and_forget_vs_single_record(shape: dict[str, Any]) -> list[Finding]:
    """Fire-and-forget workflow + single-record read = the user
    submits and immediately views a page that hasn't got its record
    yet. Suspicious. Streaming or await-with-progress is the usual
    fit."""
    workflows = shape.get("workflows") or {}
    data = shape.get("data") or {}
    if workflows.get("executionMode") == "fire-and-forget" and data.get("readShape") == "single-record":
        return [Finding(
            rule="coherence.fire_and_forget_single_record",
            message=(
                "workflows.executionMode=fire-and-forget + "
                "data.readShape=single-record: writing and then reading "
                "the same record without awaiting completion usually "
                "shows a stale/empty state. Prefer streaming (poll) or "
                "await-with-progress, or set data.readShape to list/feed."
            ),
            severity="warning",
            axis="app_shape",
        )]
    return []


def _streaming_no_realtime_module(shape: dict[str, Any], archetypes: list) -> list[Finding]:
    """workflows.executionMode=streaming but no module declares
    state.realtime=stream — the streaming mode has no producer."""
    workflows = shape.get("workflows") or {}
    if workflows.get("executionMode") != "streaming":
        return []
    for inst in archetypes:
        if not isinstance(inst, dict):
            continue
        caps = inst.get("capabilities") or {}
        state = caps.get("state") or {}
        if state.get("realtime") == "stream":
            return []
        # Recipe might resolve to streaming too — the guard here is
        # advisory; the fuller check happens post-recipe-resolution
        # in signature_moves_guard's downstream consumer.
    return [Finding(
        rule="coherence.streaming_no_realtime_module",
        message=(
            "workflows.executionMode=streaming but no archetype instance "
            "declares state.realtime=stream. Streaming mode requires a "
            "real-time module to produce the stream, otherwise the UI "
            "sits waiting on data that never arrives."
        ),
        severity="warning",
        axis="app_shape",
    )]


def _hero_but_workspace_identity(shape: dict[str, Any]) -> list[Finding]:
    """Full-bleed hero + multi-user workspace identity is unusual.
    Hero pages are consumer-facing surfaces; a team workspace
    typically leads with a data-grid or dashboard, not a hero."""
    layout = shape.get("layout") or {}
    identity = shape.get("identity") or {}
    hero = layout.get("hero")
    usage = identity.get("usageMode")
    if hero == "full-bleed-gradient" and usage == "multi-user-team":
        return [Finding(
            rule="coherence.hero_on_workspace",
            message=(
                "layout.hero=full-bleed-gradient + identity.usageMode="
                "multi-user-team: workspace apps usually lead with a "
                "data-grid or dashboard, not a consumer-style hero. "
                "Consider layout.hero=none or metric-row for workspaces."
            ),
            severity="warning",
            axis="app_shape",
        )]
    return []


def _module_shape_conflicts(shape: dict[str, Any], archetypes: list) -> list[Finding]:
    """A module whose capabilities suggest a shape opposite to the
    outer — e.g. a kanban module (drag+board) inside an outer shape
    with layout.primaryInteraction=cta-button. Usually the module
    needs a local_shape override the LLM forgot to add.

    Emits a warning per suspicious module."""
    findings: list[Finding] = []
    layout = shape.get("layout") or {}
    primary = layout.get("primaryInteraction")
    if not primary:
        return findings
    for idx, inst in enumerate(archetypes):
        if not isinstance(inst, dict):
            continue
        caps = inst.get("capabilities") or {}
        read = caps.get("read") or {}
        write = caps.get("write") or {}
        pattern = read.get("pattern")
        if not pattern:
            continue
        # Missing local_shape override on a strong mismatch.
        conflicts = (
            (pattern == "board" and primary in ("cta-button", "capture", "player")),
            (pattern == "map-pins" and primary in ("data-grid", "form", "cta-button")),
            (pattern == "feed" and primary in ("form", "cta-button")),
        )
        if not any(conflicts):
            continue
        if inst.get("local_shape"):
            continue  # LLM already accounted for it
        findings.append(Finding(
            rule=f"coherence.archetypes[{idx}].shape_conflict",
            message=(
                f"module {inst.get('name')!r}: capabilities read.pattern="
                f"{pattern!r} conflicts with outer layout.primaryInteraction="
                f"{primary!r} and no local_shape override is declared. "
                "Either the module needs a local_shape override or the "
                "outer shape is wrong."
            ),
            severity="warning",
            axis="archetypes",
        ))
    return findings


def _no_modules(archetypes: list) -> list[Finding]:
    """Zero archetype instances is almost always wrong — every app
    has at least one module."""
    if not archetypes:
        return [Finding(
            rule="coherence.no_modules",
            message="plan.archetypes is empty; every app needs at least one module.",
            severity="warning",
            axis="archetypes",
        )]
    return []
