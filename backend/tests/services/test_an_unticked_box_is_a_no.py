"""A box nobody ticked is sent as a no.

kkb5mzo3's Create refund (2026-11-03) refused every case a desk left the
flags unticked on: "Create Refund Case needs isVulnerableGuest,
isRepeatComplainant, isSocialMediaPosting, evidenceComplete, isDraft —
nothing was changed." WorkflowForm left an untouched checkbox out of the
input, and the runtime counts a left-out required input as missing; a
`false` it accepts.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "templates" / "app-foundation" / "src" / "sdk" / "client.tsx"
REQUIRED = ROOT / "templates" / "runtime" / "workflows" / "required-inputs.ts"


def test_the_form_sends_false_for_a_box_left_unticked():
    src = CLIENT.read_text("utf-8")
    submit = src[src.index("const submit = async"):src.index("const field = (name: string)")]
    assert '["checkbox", "switch"].includes(String(spec?.kind))' in submit
    assert "input[name] = false" in submit
    assert "!spec?.render" in submit, "a field drawn by the page keeps what the page gave it"


def test_the_runtime_takes_false_as_given():
    src = REQUIRED.read_text("utf-8")
    assert 'value === undefined || value === null || value === ""' in src
    assert "false" not in src.split("export function missingRequiredInputs", 1)[1]


def test_every_app_gets_the_form_on_its_next_turn():
    from services.smith.sync_app import RUNTIME_FILES  # noqa: F401  (import proves the module)
    assert "src/sdk/client.tsx" in (ROOT / "services" / "smith" / "sync_app.py").read_text("utf-8")
