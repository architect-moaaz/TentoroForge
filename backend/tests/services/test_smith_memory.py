"""Layers 1 and 4: the transcript, and where concepts live in code.

§8's warning is *"Smith must not rely exclusively on conversation history"* —
which is a claim about the other three layers, not a licence to treat the
transcript as disposable. §14 cites messages by id, so these tests care most
that a citation still resolves: ids never move, history is never rewritten, and
a corrupt line fails loudly instead of shifting every id after it.
"""
import json

import pytest

from services.smith.code_intel import (
    coverage,
    dependencies,
    implements,
    serves,
    trace,
    where,
)
from services.smith.conversation import (
    Conversation,
    MalformedTranscript,
    Message,
)


@pytest.fixture()
def conv(tmp_path) -> Conversation:
    return Conversation(tmp_path)


# --- §14: citations must keep resolving ------------------------------------

def test_ids_are_monotonic_and_stable(conv):
    first = conv.append("user", "I need an ATS")
    second = conv.append("smith", "Three decisions first")
    assert (first.id, second.id) == ("MSG-001", "MSG-002")
    assert conv.get("MSG-001").text == "I need an ATS"


def test_a_reopened_conversation_continues_rather_than_restarting(conv, tmp_path):
    conv.append("user", "one")
    conv.append("user", "two")
    # A new process, the same application. §118's "persistent" means this.
    assert Conversation(tmp_path).append("user", "three").id == "MSG-003"


def test_message_renders_as_section_14_evidence(conv):
    m = conv.append("user", "Recruiters post open roles")
    assert m.as_evidence() == {
        "type": "conversation", "message": "MSG-001", "source": "user",
    }


def test_a_corrupt_line_raises_rather_than_shifting_every_id_after_it(conv):
    conv.append("user", "one")
    with conv.path.open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    # Skipping the bad line would renumber nothing but would let _next_id
    # under-count, and a reused MSG id makes a §14 citation point at the wrong
    # turn — silently, and years later.
    with pytest.raises(MalformedTranscript):
        conv.messages()


def test_history_is_append_only(conv):
    conv.append("user", "one")
    conv.append("smith", "two")
    assert [m.text for m in conv.messages()] == ["one", "two"]
    assert conv.path.read_text("utf-8").count("\n") == 2


def test_unknown_role_is_refused(conv):
    with pytest.raises(ValueError):
        conv.append("assistant", "wrong vocabulary")


def test_recent_is_a_window_not_the_whole_transcript(conv):
    for i in range(25):
        conv.append("user", f"m{i}")
    recent = conv.recent(10)
    assert len(recent) == 10 and recent[-1].text == "m24"


def test_messages_are_findable_by_the_artifact_they_concern(conv):
    conv.append("user", "make the table compact", refs=["CMP-033"])
    conv.append("user", "unrelated")
    assert [m.text for m in conv.about("CMP-033")] == ["make the table compact"]


# --- §21 / §18: code intelligence -------------------------------------------

def test_where_reads_the_code_map(ats):
    loc = where(ats, "ENTITY-001")
    assert loc.mapped and "src/db/schema/user.ts" in loc.service


def test_unmapped_is_not_the_same_as_unimplemented(ats):
    """A projection that has not run yet is not the artifact's fault."""
    loc = where(ats, "PAGE-001")
    assert not loc.mapped and loc.files == ()


def test_implements_is_the_reverse_of_where(ats):
    assert implements(ats, "src/db/schema/user.ts") == ["ENTITY-001"]
    assert implements(ats, "./src/db/schema/user.ts") == ["ENTITY-001"]
    assert implements(ats, "nothing/here.ts") == []


def test_a_trace_is_the_requirement_not_the_application(ats):
    """§18's chain is a path. Closing transitively over the graph reaches ~80%
    of the application from *any* requirement — the same answer for all
    eighteen, which distinguishes nothing."""
    reached = len(trace(ats, "REQ-017").artifacts)
    assert reached < len(ats["requirements"]) * 10
    assert reached < 120


def test_two_requirements_trace_to_different_things(ats):
    a = set(trace(ats, "REQ-001").artifacts)
    b = set(trace(ats, "REQ-017").artifacts)
    assert a != b
    assert a - b and b - a


def test_a_trace_contains_what_declares_it_serves_the_requirement(ats):
    t = trace(ats, "REQ-017")
    assert serves(ats, "REQ-017") <= set(t.artifacts)


def test_a_trace_does_not_drag_in_other_requirements(ats):
    """A page usually serves several requirements. Following that edge would
    merge every requirement's trace into one."""
    assert trace(ats, "REQ-017").chain["REQ"] == ["REQ-017"]


def test_trace_reaches_the_data_it_depends_on(ats):
    """§18 ends at ENTITY-008 — forward edges, not reverse."""
    assert trace(ats, "REQ-017").chain.get("ENTITY")


def test_trace_verdict_comes_from_verification_not_from_counting(ats):
    from services.blueprint.verification import requirement_verdict

    assert trace(ats, "REQ-001").verdict == requirement_verdict(ats, "REQ-001")["result"]


def test_dependencies_can_be_bounded(ats):
    """Unbounded is right for a trace; one hop is right for a prompt slice."""
    seeds = {"PAGE-009"}
    assert len(dependencies(ats, seeds, depth=1)) < len(dependencies(ats, seeds))


def test_coverage_reports_what_is_mapped_without_claiming_it_is_true(ats):
    c = coverage(ats)
    assert c["mapped"] == 8 and c["artifacts"] > 300
    assert 0.0 <= c["ratio"] <= 1.0
