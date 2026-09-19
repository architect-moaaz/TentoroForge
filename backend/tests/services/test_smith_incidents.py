"""“it crashed” and “it's really slow” reach something.

Two sentences on the owner's phrasebook reached nothing at all, and they
differed from every other gap on it: the answer was not a verb an owner drives
but a signal the running application had to send. These tests cover the three
pieces of that — what the app may send, where it lands, and what Smith says
back.
"""

import json

import pytest

from services import incident_ledger
from services.smith import incidents


# --------------------------------------------------------------------------- #
# The ledger: what lands, and what must not
# --------------------------------------------------------------------------- #

def test_it_lands_beside_the_run_ledger_one_line_at_a_time(tmp_path):
    incident_ledger.record(tmp_path, {"kind": "crash", "message": "boom"})
    incident_ledger.record(tmp_path, {"kind": "crash", "message": "bang"})
    written = (tmp_path / ".forge" / "incidents.jsonl").read_text().splitlines()
    assert [json.loads(l)["message"] for l in written] == ["boom", "bang"]


def test_a_field_the_ledger_does_not_declare_is_never_written(tmp_path):
    """The rule that keeps a customer's record out of the platform is that
    nothing undeclared is kept — not a filter that inspects a value and
    decides, because a filter is a list of exceptions waiting to be wrong."""
    line = incident_ledger.record(tmp_path, {
        "kind": "crash", "message": "boom",
        "request_body": {"email": "jane@example.com", "total": 4200},
        "user_context": {"id": "u-7", "email": "jane@example.com"},
    })
    assert "request_body" not in line and "user_context" not in line
    assert "jane@example.com" not in (tmp_path / ".forge" / "incidents.jsonl").read_text()


def test_the_keys_a_control_sent_are_kept_and_the_values_never_arrive(tmp_path):
    line = incident_ledger.record(tmp_path, {
        "kind": "crash", "message": "boom", "payloadKeys": ["amount", "email"]})
    assert line["payloadKeys"] == ["amount", "email"]


def test_an_unknown_kind_is_not_recorded(tmp_path):
    assert incident_ledger.record(tmp_path, {"kind": "hunch", "message": "x"}) is None
    assert not (tmp_path / ".forge" / "incidents.jsonl").exists()


def test_a_truncated_last_line_does_not_lose_the_ones_before_it(tmp_path):
    """The failure this exists to describe is a process that stops without
    warning, so a half-written final line is the expected state, not a bug."""
    incident_ledger.record(tmp_path, {"kind": "crash", "message": "boom"})
    with (tmp_path / ".forge" / "incidents.jsonl").open("a") as fh:
        fh.write('{"kind": "crash", "mess')
    assert [c["message"] for c in incident_ledger.crashes(tmp_path)] == ["boom"]


def test_a_directory_that_cannot_be_written_never_raises(tmp_path):
    blocked = tmp_path / "file-not-a-dir"
    blocked.write_text("x")
    assert incident_ledger.record(blocked, {"kind": "crash", "message": "boom"}) is None


# --------------------------------------------------------------------------- #
# Reading it back
# --------------------------------------------------------------------------- #

def _crash(tmp_path, **over):
    base = {"kind": "crash", "where": "workflow", "route": "/cases/[id]",
            "control": "Button", "label": "Approve", "workflow": "FLOW-A",
            "step": "notify", "actionType": "send_email",
            "message": "recipient is empty", "at": "2026-09-16T10:00:00Z"}
    return incident_ledger.record(tmp_path, {**base, **over})


def test_the_same_crash_four_hundred_times_is_one_thing_to_fix(tmp_path):
    _crash(tmp_path, at="2026-09-16T10:00:00Z")
    _crash(tmp_path, at="2026-09-16T11:00:00Z", occurrences=399)
    found = incident_ledger.crashes(tmp_path)
    assert len(found) == 1
    assert found[0]["count"] == 400
    assert found[0]["firstSeen"] == "2026-09-16T10:00:00Z"
    assert found[0]["lastSeen"] == "2026-09-16T11:00:00Z"


def test_an_ephemeral_stack_does_not_split_one_crash_into_many(tmp_path):
    _crash(tmp_path, stack="at run (req-1)")
    _crash(tmp_path, stack="at run (req-2)")
    assert len(incident_ledger.crashes(tmp_path)) == 1


def test_slow_observations_are_never_collapsed_because_they_are_the_measurement(tmp_path):
    for ms in (2100, 4300, 3200):
        incident_ledger.record(tmp_path, {"kind": "slow", "operation": "FLOW-A",
                                          "workflow": "FLOW-A", "ms": ms,
                                          "thresholdMs": 2000})
    (one,) = incident_ledger.slow(tmp_path)
    assert one["count"] == 3
    assert one["worstMs"] == 4300
    assert one["averageMs"] == 3200


def test_a_crash_is_described_the_way_the_build_names_a_bad_wire(tmp_path):
    """`verify_dispatches` fails a build with route, control, workflow and
    step. The same wire breaking at run time reads the same way."""
    line = _crash(tmp_path)
    said = incident_ledger.describe(line)
    assert said == ("/cases/[id]: Button 'Approve' runs FLOW-A — step 'notify' "
                    "(send_email): recipient is empty")


def test_the_frames_shown_are_the_ones_a_change_could_move(tmp_path):
    line = _crash(tmp_path, stack="Error: x\n  at node:internal/foo\n"
                                  "  at Object.run (src/lib/workflows/index.ts:42:3)")
    assert incident_ledger.stack_frames(line) == [
        "at Object.run (src/lib/workflows/index.ts:42:3)"]


# --------------------------------------------------------------------------- #
# What Smith says back
# --------------------------------------------------------------------------- #

DOC = {
    "workflows": [{"id": "FLOW-A", "name": "Approve Case"}],
    "pages": [{"id": "PAGE-1", "route": "/cases/[id]", "name": "Case"}],
    "changeHistory": [],
}


def test_nothing_reported_says_so_and_says_why_it_might_not_have_arrived(tmp_path):
    answer, options = incidents.crash_answer(str(tmp_path), DOC)
    assert "Nothing has been reported as crashing" in answer
    assert "built and running" in answer
    # Not a dead end: wrong behaviour is not a crash, and there is a next step.
    assert "tell me what you expected" in answer
    assert options == ["Verify & fix"]


def test_the_answer_names_the_screen_and_the_process_in_the_owners_words(tmp_path):
    _crash(tmp_path)
    answer, _options = incidents.crash_answer(str(tmp_path), DOC)
    assert "**Approve**" in answer          # the control's own label
    assert "on **Case**" in answer          # the page's name, not the route
    assert "**Approve Case**" in answer     # the workflow's name, not its id
    assert "`notify`" in answer
    assert "recipient is empty" in answer


def test_the_repair_offered_is_the_one_the_crash_itself_names(tmp_path):
    _crash(tmp_path)
    _answer, options = incidents.crash_answer(str(tmp_path), DOC)
    assert "Change the Approve Case process so the notify step stops failing" in options


def test_a_crash_that_names_nothing_offers_nothing(tmp_path):
    """The alternative is offering a change to whatever was nearest, which is
    how a wrong edit gets made on the strength of a complaint."""
    incident_ledger.record(tmp_path, {"kind": "crash", "where": "unhandled",
                                      "message": "Cannot read properties of undefined"})
    _answer, options = incidents.crash_answer(str(tmp_path), DOC)
    assert options == []


def test_the_change_before_it_is_stated_as_order_not_as_cause(tmp_path):
    _crash(tmp_path, at="2026-09-16T10:00:00Z")
    doc = {**DOC, "changeHistory": [
        {"version": 4, "at": "2026-09-15T09:00:00Z", "userRequest": "add a Notify step"}]}
    answer, options = incidents.crash_answer(str(tmp_path), doc)
    assert "after you asked for “add a Notify step”" in answer
    assert "not a claim that one caused the other" in answer
    assert "Undo “add a Notify step”" in options


def test_no_undo_is_offered_for_a_change_an_undo_would_not_reverse(tmp_path):
    """`undo` reverses the MOST RECENT change. Offering it against an older
    one would put back something nobody asked about."""
    # The crash first appeared between the two changes, so the one it followed
    # is not the one `undo` would take back.
    _crash(tmp_path, at="2026-09-15T09:30:00Z")
    doc = {**DOC, "changeHistory": [
        {"version": 4, "at": "2026-09-15T09:00:00Z", "userRequest": "add a Notify step"},
        {"version": 5, "at": "2026-09-15T10:00:00Z", "userRequest": "rename the button"}]}
    answer, options = incidents.crash_answer(str(tmp_path), doc)
    assert "after you asked for “add a Notify step”" in answer
    assert not any(o.startswith("Undo") for o in options)


def test_a_change_made_after_the_crash_first_appeared_is_not_blamed_for_it(tmp_path):
    _crash(tmp_path, at="2026-09-16T10:00:00Z")
    doc = {**DOC, "changeHistory": [
        {"version": 4, "at": "2026-09-17T09:00:00Z", "userRequest": "add a Notify step"}]}
    answer, _options = incidents.crash_answer(str(tmp_path), doc)
    assert "after you asked for" not in answer


# ── slowness ───────────────────────────────────────────────────────────────

def test_slowness_says_what_was_measured_and_what_was_not(tmp_path):
    incident_ledger.record(tmp_path, {"kind": "slow", "operation": "FLOW-A",
                                      "workflow": "FLOW-A", "ms": 8400,
                                      "thresholdMs": 2000})
    answer, options = incidents.slow_answer(str(tmp_path), DOC)
    assert "**Approve Case**" in answer and "8.4s" in answer
    assert "not how long the page takes to paint" in answer
    assert "cannot make it faster on its own" in answer
    assert options == ["Simplify the Approve Case process so it does less"]


def test_nothing_slow_does_not_claim_the_application_is_fast(tmp_path):
    answer, options = incidents.slow_answer(str(tmp_path), DOC)
    assert "slow somewhere I am not looking" in answer
    assert "not how long the page takes to paint" in answer
    assert options == []


def test_plain_reads_and_writes_are_reported_but_offer_no_repair(tmp_path):
    incident_ledger.record(tmp_path, {"kind": "slow", "operation": "list",
                                      "entity": "cases", "ms": 3000,
                                      "thresholdMs": 2000})
    answer, options = incidents.slow_answer(str(tmp_path), DOC)
    assert "`list` on **cases**" in answer
    assert options == []
    assert "already the smallest version of themselves" in answer


# --------------------------------------------------------------------------- #
# The verbs
# --------------------------------------------------------------------------- #

def test_both_verbs_need_nothing_from_the_ask():
    from services.smith.verbs import REQUIRED_BY_VERB, is_known, missing_fields

    for verb in ("explain_crash", "explain_slowness"):
        assert verb in REQUIRED_BY_VERB
        assert is_known({"verb": verb})
        assert missing_fields({"verb": verb}) == []


def test_the_classifier_is_taught_both_sentences():
    from services.smith.understand_ask import _PROMPT

    assert '"it crashed"' in _PROMPT and '"explain_crash"' in _PROMPT
    assert "\"it's really slow\"" in _PROMPT and '"explain_slowness"' in _PROMPT


def test_the_run_shape_is_the_one_a_tool_handler_needs(tmp_path):
    out = incidents.run(str(tmp_path), kind="slow")
    assert out["applied"] is False and out["edited_paths"] == []
    assert out["kind"] == "slow" and out["answer"]


@pytest.mark.parametrize("verb", ["explain_crash", "explain_slowness"])
def test_the_tool_catalogue_can_run_them(tmp_path, verb):
    from services.smith_tools import READONLY_HANDLERS

    out = READONLY_HANDLERS[verb](str(tmp_path), {})
    assert out["applied"] is False and out["answer"]


# --------------------------------------------------------------------------- #
# The wire the application reports over
# --------------------------------------------------------------------------- #

def test_the_ingest_body_refuses_the_two_fields_that_carried_a_customer():
    """`request_body` and `user_context` were free dicts the generated app
    filled with the whole POST body and the whole session user. The body now
    declares what it takes and rejects everything else — a payload we did not
    design is one we cannot promise anything about."""
    from pydantic import ValidationError
    from routers.runtime_exceptions import RuntimeExceptionIn

    with pytest.raises(ValidationError):
        RuntimeExceptionIn(message="boom", request_body={"email": "jane@example.com"})
    with pytest.raises(ValidationError):
        RuntimeExceptionIn(message="boom", user_context={"id": "u-7"})


def test_a_crash_reaches_the_file_beside_the_application(tmp_path):
    from routers.runtime_exceptions import RuntimeExceptionIn, _append_to_ledger

    class _Project:
        output_dir = str(tmp_path)

    _append_to_ledger(_Project(), RuntimeExceptionIn(
        kind="workflow", message="recipient is empty", workflow_id="FLOW-A",
        node_id="notify", action_type="send_email", page_route="/cases/[id]",
        control="Button", control_label="Approve",
        payload_keys=["caseId"], role="Case Worker", occurrences=7))
    (line,) = incident_ledger.read(tmp_path)
    assert line["workflow"] == "FLOW-A" and line["step"] == "notify"
    assert line["label"] == "Approve" and line["occurrences"] == 7
    assert line["payloadKeys"] == ["caseId"]


def test_a_project_that_was_never_built_has_nowhere_to_write(tmp_path):
    from routers.runtime_exceptions import RuntimeExceptionIn, _append_to_ledger

    class _Unbuilt:
        output_dir = None

    _append_to_ledger(_Unbuilt(), RuntimeExceptionIn(message="boom"))  # no raise


def test_the_slow_endpoint_takes_a_measurement_and_nothing_else():
    from pydantic import ValidationError
    from routers.incidents import SlowResponseIn

    body = SlowResponseIn(operation="FLOW-A", ms=4200, thresholdMs=2000)
    assert body.ms == 4200
    with pytest.raises(ValidationError):
        SlowResponseIn(operation="FLOW-A", ms=4200, request_body={"email": "x"})
    with pytest.raises(ValidationError):
        SlowResponseIn(operation="FLOW-A", ms=-1)


def test_the_table_has_nowhere_left_to_put_a_customers_record():
    """The columns are dropped, not merely unwritten (`rx0918_drop_crash_payload`).

    The endpoint refusing the fields is one guard; this is the other. A column
    that still exists is a column something can start filling again, and the
    row that filled it would look exactly like every other row.
    """
    from models.runtime_exception import RuntimeException

    columns = set(RuntimeException.__table__.columns.keys())
    assert "request_body" not in columns
    assert "user_context" not in columns
    # The locators stay — they are what makes a crash findable, and none of
    # them is anybody's record.
    assert {"workflow_id", "node_id", "page_route", "source_file"} <= columns


def test_the_drop_is_chained_to_the_revision_that_created_the_columns():
    """Ten heads in the graph, and only one of them has the table in its
    ancestry. Chaining the drop anywhere else would fail on exactly the
    environments that have something to drop."""
    import pathlib
    import re

    versions = pathlib.Path(__file__).resolve().parents[2] / "alembic" / "versions"
    drop = (versions / "rx0918_drop_crash_payload_columns.py").read_text("utf-8")
    assert re.search(r'^down_revision = "svst5_faults"', drop, re.M)
    # And it can be stepped back down, or it traps whatever it is run against.
    assert "def downgrade()" in drop and "add_column" in drop
