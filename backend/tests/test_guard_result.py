"""Structured GuardResult from the post-generate guard suite.

The parser translates raw log records into a machine-readable verdict
the orchestrator loop can act on. False-negative bias: only WARNING /
ERROR count as failures — an INFO record ("guard ran, all clean") is not
a failure. Green iff no failures were captured."""
from __future__ import annotations

import logging

import pytest

from services.guard_result import (
    GuardFailure,
    GuardResult,
    capture_guard_logs,
)


# =========================================================================
# from_log_records — pure parsing
# =========================================================================

def test_green_when_no_warnings_or_errors():
    r = GuardResult.from_log_records([
        {"name": "services.post_generate_fixes",
         "level": "info",
         "message": "action_contract_guard: resolved 5, unresolved 0"},
    ])
    assert r.green is True
    assert r.failures == []


def test_captures_warning_as_failure():
    r = GuardResult.from_log_records([
        {"name": "services.post_generate_fixes",
         "level": "warning",
         "message": "workflow_mutation_guard: 11 mutation value(s) still need a trigger input"},
    ])
    assert r.green is False
    assert len(r.failures) == 1
    f = r.failures[0]
    assert f.guard == "workflow_mutation_guard"
    assert f.kind == "warning"
    assert "trigger input" in f.message


def test_captures_error_as_failure():
    r = GuardResult.from_log_records([
        {"name": "services.registry",
         "level": "error",
         "message": "Registry validation failed"},
    ])
    assert r.green is False
    assert r.failures[0].kind == "error"


def test_mixed_records_only_warning_and_error_count():
    r = GuardResult.from_log_records([
        {"name": "services.post_generate_fixes", "level": "info",
         "message": "seed_synthesizer: 60 rows"},
        {"name": "services.post_generate_fixes", "level": "warning",
         "message": "workflow_mutation_guard: 11 unfilled"},
        {"name": "services.post_generate_fixes", "level": "info",
         "message": "nav_transitions: wrote 24"},
        {"name": "services.registry_validator", "level": "warning",
         "message": "registry_validator: 1 issue"},
    ])
    assert r.green is False
    assert len(r.failures) == 2
    assert {f.guard for f in r.failures} == {"workflow_mutation_guard", "registry_validator"}


def test_guard_name_falls_back_to_logger_last_segment():
    """When the message has no `guard_name:` prefix, use the logger's
    last dot segment (e.g. `services.foo.bar` → `bar`)."""
    r = GuardResult.from_log_records([
        {"name": "services.foo.custom_guard",
         "level": "warning",
         "message": "something drifted"},
    ])
    assert r.failures[0].guard == "custom_guard"


def test_prompt_renders_readable_for_smith():
    r = GuardResult.from_log_records([
        {"name": "services.post_generate_fixes", "level": "warning",
         "message": "workflow_mutation_guard: 3 mutation value(s) unfilled"},
        {"name": "services.post_generate_fixes", "level": "warning",
         "message": "action_contract_guard: 2 unresolved"},
    ])
    prompt = r.to_prompt()
    # Header names the count.
    assert "2 failure(s)" in prompt
    # Numbered list, guard names present.
    assert "1." in prompt and "2." in prompt
    assert "workflow_mutation_guard" in prompt
    assert "action_contract_guard" in prompt
    # Directive telling Smith what to do next.
    assert "do not answer" in prompt.lower() or "route each" in prompt.lower()


def test_prompt_when_green_is_encouraging_not_empty():
    r = GuardResult(green=True, failures=[], raw_lines=[])
    p = r.to_prompt()
    assert "all green" in p.lower()


def test_to_dict_roundtrip_shape():
    r = GuardResult.from_log_records([
        {"name": "services.post_generate_fixes", "level": "warning",
         "message": "workflow_mutation_guard: 3"},
    ])
    d = r.to_dict()
    assert d["green"] is False
    assert d["failures"][0]["guard"] == "workflow_mutation_guard"


# =========================================================================
# diff_against — regression-only filter for the orchestrator
# =========================================================================

def _mkfail(guard: str, msg: str) -> GuardFailure:
    return GuardFailure(guard=guard, kind="warning", message=msg)


def test_diff_against_none_baseline_is_noop():
    r = GuardResult(green=False, failures=[_mkfail("g1", "a")], raw_lines=[])
    d = r.diff_against(None)
    assert d.failures == r.failures
    assert d.green is False


def test_diff_against_empty_baseline_is_noop():
    r = GuardResult(green=False, failures=[_mkfail("g1", "a")], raw_lines=[])
    d = r.diff_against(GuardResult(green=True, failures=[], raw_lines=[]))
    assert d.failures == r.failures


def test_diff_filters_pre_existing_failures():
    """The whole point: warnings that were red BEFORE Smith are excluded
    from the delta so Smith isn't blamed for the pre-existing app state."""
    baseline = GuardResult(green=False, raw_lines=[], failures=[
        _mkfail("workflow_mutation_guard", "19 mutations need input"),
    ])
    after = GuardResult(green=False, raw_lines=[], failures=[
        _mkfail("workflow_mutation_guard", "19 mutations need input"),
    ])
    delta = after.diff_against(baseline)
    assert delta.failures == []
    assert delta.green is True


def test_diff_surfaces_new_regressions():
    """If Smith INTRODUCED a new warning, the delta must catch it."""
    baseline = GuardResult(green=False, raw_lines=[], failures=[
        _mkfail("workflow_mutation_guard", "19 mutations need input"),
    ])
    after = GuardResult(green=False, raw_lines=[], failures=[
        _mkfail("workflow_mutation_guard", "19 mutations need input"),
        _mkfail("workflow_mutation_guard", "30 mutations need input"),
        _mkfail("read_binding_guard", "1 unresolved binding"),
    ])
    delta = after.diff_against(baseline)
    assert delta.green is False
    msgs = {f.message for f in delta.failures}
    assert msgs == {"30 mutations need input", "1 unresolved binding"}


def test_diff_matches_on_guard_and_message_together():
    """Same message, different guard → still a NEW failure. Coupling both
    fields prevents cross-guard message collisions from being suppressed."""
    baseline = GuardResult(green=False, raw_lines=[], failures=[
        _mkfail("guard_a", "shared text"),
    ])
    after = GuardResult(green=False, raw_lines=[], failures=[
        _mkfail("guard_a", "shared text"),  # pre-existing → filtered
        _mkfail("guard_b", "shared text"),  # NEW guard → surfaces
    ])
    delta = after.diff_against(baseline)
    assert len(delta.failures) == 1
    assert delta.failures[0].guard == "guard_b"


# =========================================================================
# capture_guard_logs — the runtime hook
# =========================================================================

def test_capture_scoped_to_prefix_and_level():
    """Only services.* WARNING+ is captured; other loggers/levels bypass."""
    with capture_guard_logs(logger_prefix="services.", min_level=logging.WARNING) as bag:
        logging.getLogger("services.post_generate_fixes").warning("workflow_mutation_guard: 3")
        logging.getLogger("services.post_generate_fixes").info("seed_synthesizer: 60 rows")
        logging.getLogger("routers.generate").warning("something else")
        logging.getLogger("services.registry").error("bad")
    names = {r["name"] for r in bag}
    assert "services.post_generate_fixes" in names
    assert "services.registry" in names
    assert "routers.generate" not in names
    # info was skipped even though it was inside the prefix.
    levels = [r["level"] for r in bag]
    assert "info" not in levels


def test_capture_isolates_scope():
    """Records emitted after the ``with`` block do NOT leak into the bag."""
    with capture_guard_logs() as bag:
        logging.getLogger("services.foo").warning("inside")
    logging.getLogger("services.foo").warning("outside")
    assert len(bag) == 1
    assert bag[0]["message"] == "inside"


def test_apply_post_generate_fixes_with_result_returns_shape(tmp_path):
    """Wrapper survives a minimal (empty) output dir and returns a
    well-shaped GuardResult. No guard should ERROR on a mostly-empty
    dir; they may WARN, so we only assert the shape, not the verdict."""
    from services.post_generate_fixes import apply_post_generate_fixes_with_result
    (tmp_path / "src").mkdir()
    r = apply_post_generate_fixes_with_result(str(tmp_path))
    assert isinstance(r.green, bool)
    assert isinstance(r.failures, list)


def test_capture_then_build_result_end_to_end():
    with capture_guard_logs() as bag:
        logging.getLogger("services.post_generate_fixes").warning(
            "workflow_mutation_guard: 3 mutation value(s) unfilled"
        )
        logging.getLogger("services.post_generate_fixes").info(
            "action_contract_guard: reconciled 15"
        )
    r = GuardResult.from_log_records(bag)
    assert r.green is False
    assert r.failures[0].guard == "workflow_mutation_guard"
