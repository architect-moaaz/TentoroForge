"""Renderer↔schema contract-drift guard (Pipeline Cleanup, Phase 4).

The generator writes JSON artifacts (shell.json first — pages next in a
follow-up slice) and the frontend renderer reads them. The gap between
"authored" and "actually consumed" is where silent authoring bugs breed:
the generator computes a value that the renderer never looks at, so the
authoring effort is a no-op the pipeline still spends time on.

This test locks the shell.json contract by exercising the sole writer
(``services.shell_templates.build_shell_deterministic`` — Phase 6-6C
made it the only path) across a spread of information architectures,
collecting the top-level keys it emits, and asserting each one is
either:

  * on the ``READ_BY_RENDERER`` whitelist — the generated-app template
    that consumes shell.json is known to read this field, or
  * on the ``DEAD_CODE_ALLOWLIST`` — a short-term acceptance list for
    keys that are still written but not yet honored, each with a
    follow-up task id.

A new key on shell.json that is not in either list fails the test with
a clear "add to whitelist after renderer-honor, or add to dead-code
list with a follow-up task id" message. This is the failsafe the plan
doc (``docs/superpowers/plans/2026-08-12-pipeline-cleanup.md``, Phase
4) asks for.

The two known offenders named in the plan doc:

  * ``shell.json.frame`` — resolved renderer-honor in Phase 4.
    ``backend/templates/app-foundation/src/app/(dashboard)/layout.tsx``
    now reads it in ``shellIdentity()``. On the whitelist.
  * ``shell.json.layout.navigation`` — investigated and confirmed
    NOT WRITTEN by any current generator path (``layout`` never
    appears at the shell.json top level in any of the deterministic
    outputs — checked against every ``output/*/src/schemas/shell.json``
    plus a synthetic sweep here). No fix needed; documented for the
    record.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from services.shell_templates import build_shell_deterministic


# ----------------------------------------------------------------------
# The contract lists — the whole point of this test file.
# ----------------------------------------------------------------------

# Top-level shell.json keys the generated-app template
# (``backend/templates/app-foundation/src/app/(dashboard)/layout.tsx``)
# is known to consume when rendering the app shell. Update this list
# whenever the renderer starts honouring a new field — that action is
# what promotes a key OUT of the dead-code list and into the contract.
READ_BY_RENDERER: frozenset[str] = frozenset({
    # v2 schema envelope. Kept for renderer version-negotiation and for
    # the DesignBriefCard / ShellState provider to identify the file.
    "schemaVersion",
    "id",
    "title",
    # Phase 4 renderer-honor: `shellIdentity()` reads this and maps
    # sidebar/rail/none → sidebar frame, topbar → topbar frame.
    "frame",
    # The layout.tsx `loadNavProps` walks children to find the SideNav
    # component and pulls its `props.groups`. The rest of the tree is
    # currently unread but the children ARRAY itself is definitely
    # traversed, so we keep it on the whitelist.
    "children",
    # 2026-08-13 — layout.tsx `readShellAppName` reads this to feed the
    # top-bar wordmark for every frame (persona-pills has no SideNav to
    # dig it out of, so the placeholder "__APP_NAME__" used to leak).
    "appName",
})

# Fields the generator still writes but the renderer does NOT yet read.
# Each entry MUST have a follow-up task or spec reference in the
# comment so the debt is visible. Empty right now — Phase 4 cleared it
# by moving `frame` into READ_BY_RENDERER via a template edit.
DEAD_CODE_ALLOWLIST: dict[str, str] = {
    # example format if we accumulate debt in the future:
    # "someField": "TODO: renderer-honor in Phase N (task #XXX)",
}

# Fields the plan doc named as offenders that we investigated and
# confirmed are NOT emitted by any current writer. Recorded here so a
# future regression that starts writing them fails loud.
PHANTOM_OFFENDERS: frozenset[str] = frozenset({
    # Named in plan 2026-08-12-pipeline-cleanup.md. Never appears at
    # the shell.json top level under any tested IA. If a future
    # generator starts writing shell.json.layout, the guard fires.
    "layout",
})


# ----------------------------------------------------------------------
# Fixtures exercising the sole-writer across information architectures.
# Each IA below is meant to trigger a distinct branch of
# ``build_shell_deterministic`` (frame=sidebar / topbar / rail / split /
# none) so the collected key set covers every emitter path.
# ----------------------------------------------------------------------


def _nav_flow(routes: list[str]) -> dict[str, Any]:
    return {"pages": [
        {"id": r.strip("/") or "home", "route": r,
         "title": f"{(r.strip('/').title() or 'Dashboard')}Page",
         "params": [], "shell": True}
        for r in routes
    ]}


_BRAND = {"appName": "TestApp", "primaryColor": "#2E4A6E"}


_FIXTURES: list[tuple[str, dict | None, dict, dict | None, dict | None]] = [
    # (label, plan, nav_flow, brand, design_spec)
    ("sidebar_admin", {"pages": [{"archetype": "list"}]},
     _nav_flow(["/", "/a", "/b", "/c", "/d", "/e", "/f", "/g", "/h", "/i", "/j"]),
     _BRAND, None),
    ("topbar_marketing", None,
     _nav_flow(["/", "/about", "/pricing"]), _BRAND, None),
    ("rail_canvas", {"pages": [{"archetype": "kanban"}]},
     _nav_flow(["/", "/board", "/inbox", "/tasks", "/reports", "/team"]),
     _BRAND, None),
    ("split_inbox", {"pages": [{"archetype": "inbox"}]},
     _nav_flow(["/", "/inbox", "/messages", "/contacts", "/settings", "/labels"]),
     _BRAND, None),
    ("frame_none_passthrough",
     {"pages": [{"archetype": "hero"}]},
     _nav_flow(["/"]),
     _BRAND,
     {"layout": {"shell": "none"}}),
]


@pytest.mark.parametrize("label,plan,nav_flow,brand,spec",
                         _FIXTURES, ids=[f[0] for f in _FIXTURES])
def test_shell_json_only_writes_whitelisted_keys(label, plan, nav_flow, brand, spec):
    """Every top-level key the sole writer emits must be either
    readable by the renderer or on the dead-code allowlist.

    A new key on shell.json that lands without renderer support fails
    here with an explicit remediation message — this is the "install a
    contract-drift test that asserts every field written by the
    generator has a corresponding reader in the renderer" step from
    the Phase 4 plan doc.
    """
    shell = build_shell_deterministic(plan, nav_flow, brand, spec)
    written = set(shell.keys())

    known = READ_BY_RENDERER | set(DEAD_CODE_ALLOWLIST.keys())
    surprises = written - known

    assert not surprises, (
        f"[{label}] build_shell_deterministic emitted top-level shell.json "
        f"key(s) that are neither read by the renderer nor on the dead-code "
        f"allowlist: {sorted(surprises)}.\n\n"
        f"Do ONE of the following:\n"
        f"  (a) Renderer-honor: teach "
        f"backend/templates/app-foundation/src/app/(dashboard)/layout.tsx "
        f"to read this field, then add it to READ_BY_RENDERER in this "
        f"file.\n"
        f"  (b) Generator-remove: delete the write from "
        f"services/shell_templates.py (or services/shell_from_brief.py).\n"
        f"  (c) Short-term accept: add the key to DEAD_CODE_ALLOWLIST "
        f"with a task id in the comment — the debt then shows up in "
        f"this file as documented follow-up work."
    )


def test_no_phantom_offender_regression():
    """The two offenders named in the plan doc: ``frame`` (resolved by
    renderer-honor in Phase 4, now on the whitelist) and
    ``layout.navigation`` (confirmed never written). This test guards
    the second — if a future generator starts writing a ``layout`` key
    at the shell.json top level, fail here so the drift is caught
    before it silently becomes dead code again."""
    for label, plan, nav_flow, brand, spec in _FIXTURES:
        shell = build_shell_deterministic(plan, nav_flow, brand, spec)
        for phantom in PHANTOM_OFFENDERS:
            assert phantom not in shell, (
                f"[{label}] shell.json now writes a '{phantom}' key. "
                f"This key was documented in the Phase 4 plan doc as a "
                f"'known offender' and confirmed never-written at the "
                f"time. If a real writer is landing this, either wire "
                f"the renderer to honor it and move it to "
                f"READ_BY_RENDERER, or remove the write."
            )


def test_frame_is_actually_read_by_generated_app_template():
    """Renderer-honor claim check: the Phase 4 fix landed a read of
    ``shell.json.frame`` in
    ``backend/templates/app-foundation/src/app/(dashboard)/layout.tsx``.
    If that read gets deleted or refactored away, the ``frame`` entry
    on READ_BY_RENDERER becomes a lie — this test breaks first."""
    template = (Path(__file__).resolve().parents[3]
                / "backend" / "templates" / "app-foundation"
                / "src" / "app" / "(dashboard)" / "layout.tsx")
    assert template.exists(), (
        f"expected generated-app shell template at {template} — has it "
        f"been moved? Update this test's path or restore the file.")
    body = template.read_text(encoding="utf-8")

    # Must load shell.json.
    assert "src/schemas/shell.json" in body or 'schemas", "shell.json"' in body, (
        "generated-app layout.tsx no longer loads src/schemas/shell.json — "
        "if this is intentional, remove 'frame' + 'children' from "
        "READ_BY_RENDERER and move them to DEAD_CODE_ALLOWLIST with a "
        "follow-up task id.")

    # Must actually read the top-level `frame` field.
    read_frame = re.search(r"shell\w*\.\s*frame\b|\?\.frame\b", body)
    assert read_frame, (
        "generated-app layout.tsx no longer reads shell.json.frame — the "
        "Phase 4 renderer-honor fix has been reverted. Either restore "
        "the read or move 'frame' from READ_BY_RENDERER to "
        "DEAD_CODE_ALLOWLIST with a task id.")


def test_dead_code_allowlist_entries_carry_a_task_reference():
    """Any entry on DEAD_CODE_ALLOWLIST must document a follow-up.
    The rule keeps the list from turning into a permanent parking lot
    for silent bugs — every acceptance carries a plan to close it out."""
    for key, note in DEAD_CODE_ALLOWLIST.items():
        assert note and note.strip(), (
            f"DEAD_CODE_ALLOWLIST['{key}'] has an empty note — every "
            f"entry must reference a follow-up task or spec.")
        assert re.search(r"#\d+|task|spec|TODO|Phase", note, re.IGNORECASE), (
            f"DEAD_CODE_ALLOWLIST['{key}'] note '{note}' should mention "
            f"a task id (e.g. '#607'), a Phase, or a spec reference so "
            f"the debt is trackable.")
