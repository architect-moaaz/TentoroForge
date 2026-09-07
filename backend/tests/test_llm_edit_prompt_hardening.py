"""NT-4 + NT-5 — prompt hardening for edit_page's LLM boundary.

The LLM was preserving Select-with-optionsFrom on the ``cvUploadId``
column even when the intent said 'change to FileUpload'. Two changes:

  NT-4: system prompt now states user-named component types beat any
        semantic inference, with a concrete cvUploadId example.
  NT-5: when the intent names a non-FK control (FileUpload,
        CameraCapture, ...) AND the target page has FK-valued fields
        (Select with optionsFrom), the user prompt is augmented with a
        coordination note explaining the workflow layer will be updated
        separately, so the LLM shouldn't preserve Select 'because the
        workflow expects a uuid'.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from services.llm_edit import (
    _build_system_prompt,
    _build_user_prompt,
    smart_edit_page,
)


_FIXTURE = Path("/Users/m/Work/code/poc/design2ui-forge-v3/output/bpxr6hsv")


@pytest.fixture
def app_root(tmp_path: Path) -> Path:
    if not _FIXTURE.exists():
        pytest.skip("bpxr6hsv fixture app not present")
    (tmp_path / "contracts").mkdir()
    for name in ("resource-registry.json", "action-contract.json",
                 "generation-dossier.json"):
        shutil.copy(_FIXTURE / "contracts" / name, tmp_path / "contracts" / name)
    shutil.copy(_FIXTURE / "registry.json", tmp_path / "registry.json")
    shutil.copytree(_FIXTURE / "src" / "schemas", tmp_path / "src" / "schemas")
    return tmp_path


# --------------------------------------------------------------------------- #
# NT-4: System prompt — user words > semantic inference
# --------------------------------------------------------------------------- #

def test_system_prompt_has_control_type_priority_rule():
    p = _build_system_prompt()
    assert "CONTROL-TYPE PRIORITY" in p
    # The core assertion — user wins over inference.
    lower = p.lower()
    assert "user" in lower and ("win" in lower or "trust" in lower or "beat" in lower)


def test_system_prompt_names_the_do_not_substitute_pattern():
    """The exact failure we hit — LLM kept Select on an FK column because
    FileUpload 'can't produce a uuid'. The prompt must name this pattern."""
    p = _build_system_prompt()
    assert "substitute" in p.lower() or "semantically" in p.lower() \
        or "inference" in p.lower()


def test_system_prompt_carries_concrete_cvupload_example():
    """A concrete before/after example anchors the LLM better than abstract
    prose — include cvUploadId Select → FileUpload verbatim."""
    p = _build_system_prompt()
    assert "cvUploadId" in p
    assert "FileUpload" in p
    assert "Select" in p


# --------------------------------------------------------------------------- #
# NT-5: Coordination note injection
# --------------------------------------------------------------------------- #

def test_coordination_note_appears_for_fileupload_on_fk_column(app_root):
    """User asks to switch an FK Select to FileUpload — the LLM prompt
    must include an explicit coordination note so it doesn't preserve
    the Select 'because the workflow expects a uuid'."""
    current = json.loads(
        (app_root / "src/schemas/candidates/new.json").read_text(encoding="utf-8")
    )
    intent = "Change the cvUploadId field from a Select to a FileUpload"
    user_prompt = _build_user_prompt(
        intent=intent,
        target_path="src/schemas/candidates/new.json",
        current_schema=current,
        output_dir=str(app_root),
    )
    assert "COORDINATION NOTE" in user_prompt
    # Names the specific FK field (or at least the FK source table).
    assert "cvUploadId" in user_prompt
    # Names the target (registry entity or optionsFrom source) for context.
    assert "cvUploads" in user_prompt


def test_coordination_note_lists_form_workflow(app_root):
    current = json.loads(
        (app_root / "src/schemas/candidates/new.json").read_text(encoding="utf-8")
    )
    user_prompt = _build_user_prompt(
        intent="make cvUploadId a FileUpload",
        target_path="src/schemas/candidates/new.json",
        current_schema=current,
        output_dir=str(app_root),
    )
    # The Form here declares workflow="CreateCandidate" in props.
    assert "CreateCandidate" in user_prompt


def test_coordination_note_absent_when_intent_has_no_fileupload(app_root):
    """A totally different edit (add a validator, add a text field) must
    NOT trigger the coordination note — it's a red herring for asks that
    aren't control-type changes on FK columns."""
    current = json.loads(
        (app_root / "src/schemas/candidates/new.json").read_text(encoding="utf-8")
    )
    user_prompt = _build_user_prompt(
        intent="Add a pattern validator on passportNumber",
        target_path="src/schemas/candidates/new.json",
        current_schema=current,
        output_dir=str(app_root),
    )
    assert "COORDINATION NOTE" not in user_prompt


def test_coordination_note_absent_when_no_fk_fields_present(tmp_path):
    """FileUpload intent against a page with no FK dropdowns — no
    coordination note needed. Verifies detection isn't fired by the
    intent alone."""
    # Minimal seed: just the contracts + a simple page with no FK fields.
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "resource-registry.json").write_text(
        json.dumps({"entities": {}, "relationships": []}), encoding="utf-8")
    (tmp_path / "contracts" / "action-contract.json").write_text(
        json.dumps({"actions": []}), encoding="utf-8")
    (tmp_path / "contracts" / "generation-dossier.json").write_text(
        json.dumps({"prompt": "x", "plan": {}}), encoding="utf-8")
    (tmp_path / "registry.json").write_text(json.dumps({}), encoding="utf-8")
    (tmp_path / "src" / "schemas").mkdir(parents=True)
    (tmp_path / "src" / "schemas" / "x.json").write_text(json.dumps({
        "route": "/x",
        "root": {"type": "Stack", "children": [
            {"type": "Input", "props": {"name": "name"}},
        ]},
    }), encoding="utf-8")
    current = json.loads((tmp_path / "src/schemas/x.json").read_text(encoding="utf-8"))
    user_prompt = _build_user_prompt(
        intent="change name to a FileUpload",
        target_path="src/schemas/x.json",
        current_schema=current,
        output_dir=str(tmp_path),
    )
    assert "COORDINATION NOTE" not in user_prompt


def test_coordination_note_triggers_for_camera_scanner_signature_too(app_root):
    """The pattern isn't specific to FileUpload — any non-FK control
    named on an FK-having page trips the detector."""
    current = json.loads(
        (app_root / "src/schemas/candidates/new.json").read_text(encoding="utf-8")
    )
    for control in ("CameraCapture", "Scanner", "Signature"):
        p = _build_user_prompt(
            intent=f"change cvUploadId to a {control}",
            target_path="src/schemas/candidates/new.json",
            current_schema=current,
            output_dir=str(app_root),
        )
        assert "COORDINATION NOTE" in p, (
            f"detector missed intent naming {control}"
        )


# --------------------------------------------------------------------------- #
# Stateful single-page detector — Smith knows the pattern
# --------------------------------------------------------------------------- #

_MINIMAL_SCHEMA = {
    "route": "/scan",
    "root": {"type": "Stack", "children": []},
}


@pytest.mark.parametrize("intent", [
    "keep the results on the same page",
    "convert this to a single-page flow",
    "stay on the scan page while it works",
    "show a loading state and then the results",
    "show the results inline",
    "make it auto-refresh",
    "make it one page with three states",
    "use a state machine here",
])
def test_stateful_single_page_note_fires_on_intent(tmp_path, intent):
    """A user phrasing that implies the stateful pattern injects the
    coordination note (with example schema + doc references) into the
    LLM prompt — Smith would otherwise not know the pattern exists."""
    p = _build_user_prompt(
        intent=intent,
        target_path="src/schemas/scan.json",
        current_schema=_MINIMAL_SCHEMA,
        output_dir=str(tmp_path),
    )
    assert "stateful single-page pattern" in p, f"detector missed: {intent!r}"
    assert "AutoRefresh" in p or "poll" in p
    assert "stateful_scan_page.json" in p
    assert "Conditional" in p


def test_stateful_single_page_note_absent_on_unrelated_intent(tmp_path):
    """Unrelated intents don't get the pattern spam."""
    p = _build_user_prompt(
        intent="rename the Submit button to Save",
        target_path="src/schemas/scan.json",
        current_schema=_MINIMAL_SCHEMA,
        output_dir=str(tmp_path),
    )
    assert "stateful single-page pattern" not in p


def test_stateful_single_page_note_absent_when_already_applied(tmp_path):
    """If the schema is ALREADY stateful (has top-level poll + Conditional
    root), don't re-prescribe the pattern — Smith should be refining, not
    re-emitting the shape."""
    already_stateful = {
        "route": "/scan",
        "poll": {"interval": 2500, "stopWhen": "scan.status IN ('completed','failed')"},
        "root": {"type": "Conditional", "branches": []},
    }
    p = _build_user_prompt(
        intent="keep the results on the same page and tweak the copy",
        target_path="src/schemas/scan.json",
        current_schema=already_stateful,
        output_dir=str(tmp_path),
    )
    assert "stateful single-page pattern" not in p
