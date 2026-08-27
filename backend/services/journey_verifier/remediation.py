"""Turn a failed JourneyResult into a structured remediation hint.

The purpose is decoupling — the gate produces *what broke and probably
why*, and lets a caller (pipeline, SV harness, Smith) decide what to do
about it. We don't try to fix anything here; we categorize.

Mapping is heuristic on `failing_step.kind` + the failure message, tuned
to the recurring failure shapes we've seen in gklk8txo/vps generations:

  login_as failed         →  auth/seed issue    (seed users, credentials)
  upload timed out        →  FileUpload seam    (component/renderer)
  wait_for_workflow ...   →  workflow definition (archetype workflow emitter)
  wait_for_entity  ...    →  insert path        (workflow output mapping)
  click could not find    →  page schema        (button not emitted / mis-labeled)
  assert_element  ...     →  page schema        (widget not emitted)
  assert_no_console_errors→  runtime (renderer/binding)

Downstream consumers can either surface this to a human or feed it back
into the responsible agent.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RemediationHint:
    journey_slug: str
    failing_step: str | None
    likely_cause: str
    # One of: "auth-seed", "form-scaffold", "component-wiring",
    # "workflow-definition", "workflow-output-mapping", "page-schema",
    # "runtime-binding", "unknown".
    target_seam: str
    # Free-text guidance, phrased as a prompt fragment so a downstream
    # agent can ingest it directly. Kept short — no repeated context.
    hint: str
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def classify_failure(
    journey_slug: str,
    failing_step: str | None,
    failure: str | None,
    step_kind: str | None = None,
) -> RemediationHint:
    """Map a failed step → a structured hint. Pure. Never raises."""
    fs = (failing_step or "").lower()
    fm = (failure or "")[:600]
    fm_low = fm.lower()
    kind = (step_kind or _infer_kind(fs, fm_low)).lower()

    if kind == "login_as" or "sign in" in fs or "invalid email or password" in fm_low:
        return RemediationHint(
            journey_slug=journey_slug,
            failing_step=failing_step,
            likely_cause="Signed-in flow can't get past the login page.",
            target_seam="auth-seed",
            hint=(
                "The journey couldn't sign in with admin@example.com / admin1234. "
                "Verify seed.ts writes at least one user with a real "
                "password_hash before the gate runs, and that the login route "
                "accepts credentials-provider auth."
            ),
            tags=["auth", "seed"],
        )

    if kind == "upload" or "upload" in fs:
        return RemediationHint(
            journey_slug=journey_slug,
            failing_step=failing_step,
            likely_cause="File-upload UI didn't complete before the next step.",
            target_seam="component-wiring",
            hint=(
                "FileUpload/CameraCapture didn't populate a hidden input or "
                "didn't POST /api/files within the timeout. Check that "
                "CameraCapture only renders its hidden input when uploadedId "
                "is truthy, and that FileUpload's onUpload writes the id to "
                "the form's imageUrl field."
            ),
            tags=["upload", "file"],
        )

    if kind == "wait_for_workflow" or "workflow" in fs:
        return RemediationHint(
            journey_slug=journey_slug,
            failing_step=failing_step,
            likely_cause="Workflow never reached a terminal status.",
            target_seam="workflow-definition",
            hint=(
                "The workflow either had no path from start to a terminal "
                "node, hung on a specific action_type, or crashed silently. "
                "Inspect the workflow JSON (workflows/*.json) — every node "
                "should have a `next` (or complete `branches`), AI/HTTP "
                "actions should have their required config, and side-effect "
                "nodes should emit outputs into ctx.variables."
            ),
            tags=["workflow", "runtime"],
        )

    if kind == "assert_entity" or "row" in fs or "inserted" in fs or "at least one" in fs:
        return RemediationHint(
            journey_slug=journey_slug,
            failing_step=failing_step,
            likely_cause="Expected DB row never landed.",
            target_seam="workflow-output-mapping",
            hint=(
                "The workflow ran but no row appeared in the target table. "
                "Usually a db_insert node with an unbound (or wrong-named) "
                "input, or an ai_extract → db_insert mapping that isn't "
                "wired. Verify the workflow's insert nodes read from the "
                "correct step outputs and that required NOT NULL columns "
                "have values."
            ),
            tags=["persistence", "workflow-output"],
        )

    if kind == "click" or "button" in fs or "click" in fs:
        return RemediationHint(
            journey_slug=journey_slug,
            failing_step=failing_step,
            likely_cause="Primary CTA button not found on the page.",
            target_seam="page-schema",
            hint=(
                "The page schema doesn't emit the expected button, or the "
                "label drifted from what the extractor looked for. Rebuild "
                "the affected page via the deterministic page emitter and "
                "ensure the primary CTA carries a stable label."
            ),
            tags=["page", "cta"],
        )

    if kind == "assert_element" or kind == "wait_for_element" or "visible" in fs:
        return RemediationHint(
            journey_slug=journey_slug,
            failing_step=failing_step,
            likely_cause="Expected UI element didn't render.",
            target_seam="page-schema",
            hint=(
                "A widget the journey expects isn't in the schema, or the "
                "surrounding container short-circuited (empty data source, "
                "auth gate). Regenerate the page and inspect its emitted "
                "schema JSON."
            ),
            tags=["page", "render"],
        )

    if kind == "assert_no_console_errors" or "console" in fs:
        return RemediationHint(
            journey_slug=journey_slug,
            failing_step=failing_step,
            likely_cause="Runtime threw in the browser.",
            target_seam="runtime-binding",
            hint=(
                "React/renderer error at page load. Common causes: an "
                "unresolved {{binding}}, missing data source, or a schema "
                "node with an invalid discriminator (component not in "
                "registry). Check the browser console output in the failure "
                "text and follow it back to the source node."
            ),
            tags=["runtime", "console"],
        )

    return RemediationHint(
        journey_slug=journey_slug,
        failing_step=failing_step,
        likely_cause="Uncategorized journey failure.",
        target_seam="unknown",
        hint=(
            "The failure didn't match any of the known heuristic buckets. "
            "Inspect the Playwright trace + failure text manually."
        ),
        tags=["unclassified"],
    )


def build_hints(journey_results: list[dict[str, Any]]) -> list[RemediationHint]:
    """Convenience wrapper — take the shape emitted by the gate and
    return one hint per non-passed journey."""
    out: list[RemediationHint] = []
    for j in journey_results or []:
        if (j.get("status") or "passed") == "passed":
            continue
        out.append(classify_failure(
            journey_slug=j.get("slug") or "unknown",
            failing_step=j.get("failing_step"),
            failure=j.get("failure"),
            step_kind=j.get("step_kind"),
        ))
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _infer_kind(fs: str, fm_low: str) -> str:
    """Guess the JourneySpec step kind from the failing_step label the
    driver produces. Extractors format steps as `Step(kind=..., name=...)`
    and Playwright reports the *name*, not the kind, so we recover it
    heuristically. Cheap and forgiving — the classifier degrades to
    "unknown" gracefully if we miss."""
    if not fs:
        return ""
    if "sign in" in fs or "log in" in fs:
        return "login_as"
    if "upload" in fs:
        return "upload"
    if "workflow" in fs and ("terminal" in fs or "runs" in fs or "complete" in fs):
        return "wait_for_workflow"
    if "row" in fs or "insert" in fs or "session recorded" in fs or "at least" in fs:
        return "assert_entity"
    if "click" in fs or "submit" in fs or "scan" in fs:
        return "click"
    if "visible" in fs or "renders" in fs or "loaded" in fs:
        return "assert_element"
    if "console" in fs:
        return "assert_no_console_errors"
    return ""
