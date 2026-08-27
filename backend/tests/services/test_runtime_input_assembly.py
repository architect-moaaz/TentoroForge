"""Structural check on the runtime input-assembly template.

Slice A T9. The TypeScript file ships as a template — copied into
newly-generated apps by services.runtime_injector. This test asserts
the file exists with the required exports so runtime_injector.py can
rely on it. Full TypeScript behaviour is tested inside the generated
app's own test suite (out of scope here)."""
from __future__ import annotations

from pathlib import Path


_TEMPLATE = (
    Path(__file__).parent.parent.parent
    / "templates" / "runtime" / "workflows" / "input-assembly.ts"
)


def test_input_assembly_file_exists():
    assert _TEMPLATE.is_file(), (
        f"expected runtime template at {_TEMPLATE}"
    )


def test_input_assembly_exports_pure_function():
    text = _TEMPLATE.read_text(encoding="utf-8")
    # The runtime dispatcher + generated Form submit handlers import
    # this specific function; keep the name stable.
    assert "export function assembleWorkflowInputs(" in text
    # Types the caller uses:
    assert "WorkflowInputDef" in text
    assert "AssemblyContext" in text
    assert "AssemblyResult" in text
    # Source kinds mentioned:
    for kind in ("form_field", "route", "auth", "static", "computed"):
        assert kind in text, f"missing source kind {kind!r} in template"


def test_input_assembly_handles_missing_required_source():
    # The template should include the missing_source error kind so the
    # runtime dispatcher can surface it consistently with the plan
    # validator's error taxonomy (services.submit_authority).
    text = _TEMPLATE.read_text(encoding="utf-8")
    assert "missing_source" in text
    assert "form_field_missing" in text
    assert "route_param_missing" in text
    assert "auth_claim_missing" in text


def test_input_assembly_feel_lite_integration():
    """Slice E — computed source kind now uses FEEL-lite. The template
    imports from the shipped runtime/feel-lite/ module (sibling to
    runtime/workflows/, so the relative path is ../feel-lite) and
    evaluates expressions instead of erroring out on the `computed`
    kind."""
    text = _TEMPLATE.read_text(encoding="utf-8")
    assert 'from "../feel-lite"' in text
    assert "evaluateExpression" in text
    assert "evaluateComputedSource" in text
    # The v1 "computed_unsupported" error is replaced by "computed_failed"
    # (only fires on actual evaluation failure now).
    assert "computed_failed" in text


def test_feel_lite_module_ships_to_generated_apps():
    """FEEL-lite already ships to every generated app via
    services.runtime_injector — the shipped copy lives at
    backend/templates/runtime/feel-lite/ (sibling to
    runtime/workflows/). This is the module input-assembly imports."""
    feel_dir = _TEMPLATE.parent.parent / "feel-lite"
    assert feel_dir.is_dir(), (
        f"expected FEEL-lite module at {feel_dir}"
    )
    # Public API surface — evaluator + parser + tokenizer + index barrel.
    for f in ("index.ts", "evaluator.ts", "parser.ts", "tokenizer.ts", "ast.ts"):
        assert (feel_dir / f).is_file(), f"missing {f}"
    # evaluateExpression must be exported from the barrel.
    barrel = (feel_dir / "index.ts").read_text(encoding="utf-8")
    assert "export function evaluateExpression" in barrel or \
           "export { evaluateExpression" in barrel
