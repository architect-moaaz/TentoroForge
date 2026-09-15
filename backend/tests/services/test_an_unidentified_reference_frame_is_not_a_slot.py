"""A reference frame the planner cannot tell from its siblings is not a slot.

Fifteen frames of one file, all named "Refund & Case Management Platform" and
recorded with no `shows`, were handed to `page_contracts` as fifteen slots that
"must" be answered. It answered them in file order: the Properties page was
built from the Write-off Approval drawing, the posting queue from the Front
Desk search — fifteen of fifteen wrong, each composed as the wrong screen. A
frame with no identity asks no question; the pages it might have been are
composed from components until `shows` or a name of its own says what it is.
"""
from services.blueprint.page_planner import (
    identified_frames, page_slots, reference_frames, specification_frames,
)


def _doc(frames, treat_as="evidence"):
    return {"designSources": [{"id": "FIGMA-001", "treatAs": treat_as, "frames": frames}],
            "data": {"entities": []}}


SAME = "Refund & Case Management Platform"


def test_frames_with_one_shared_name_and_no_heading_are_not_slots():
    frames = [{"nodeId": f"1:{i}", "name": SAME} for i in range(3)]
    assert reference_frames(_doc(frames)) == []
    assert [s for s in page_slots(_doc(frames)) if s.get("figmaFrame")] == []


def test_a_heading_gives_a_frame_its_identity_back():
    frames = [{"nodeId": "1:1", "name": SAME, "shows": "Ticket Queue"},
              {"nodeId": "1:2", "name": SAME},
              {"nodeId": "1:3", "name": SAME, "shows": "Approval Queue"}]
    assert [f["nodeId"] for f in reference_frames(_doc(frames))] == ["1:1", "1:3"]


def test_a_name_of_its_own_is_identity_enough():
    frames = [{"nodeId": "1:1", "name": "Dashboard"}, {"nodeId": "1:2", "name": "Front Desk"}]
    assert [f["nodeId"] for f in identified_frames(frames)] == ["1:1", "1:2"]


def test_a_specification_keeps_every_frame():
    """One page per frame is the contract of a specification; a frame there
    is a page whatever it is called, so the identity rule does not apply."""
    frames = [{"nodeId": f"1:{i}", "name": SAME} for i in range(3)]
    assert len(specification_frames(_doc(frames, "specification"))) == 3


def test_two_frames_showing_one_heading_are_one_slot():
    """Front Desk was drawn twice — the search and a result — in one real
    file. That is one screen in two states, not two pages."""
    frames = [{"nodeId": "1:1", "name": SAME, "shows": "Front Desk"},
              {"nodeId": "1:2", "name": SAME, "shows": "Front Desk"},
              {"nodeId": "1:3", "name": SAME, "shows": "Notifications"}]
    assert [f["nodeId"] for f in identified_frames(frames)] == ["1:1", "1:3"]
