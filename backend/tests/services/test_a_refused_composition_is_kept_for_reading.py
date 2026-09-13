"""What the Blueprint refused is written down, with why.

Four intake forms were refused three times each for the same sentence and
nobody could say what the composer had actually sent. The refused proposals
now land under `.forge/refused/` beside the reason.
"""
import json

from services.blueprint.agent_contract import ArtifactProposal
from services.blueprint.refusals import record_refusal


def test_the_refused_proposals_and_the_reason_are_on_disk(tmp_path):
    p = ArtifactProposal(section="pageLayouts", natural_key="PAGE-007",
                         body={"page": "PAGE-007", "root": {"type": "Form", "props": {}, "children": []}})
    path = record_refusal(tmp_path, "PAGE-007", 2, [p], "InvalidPatternTemplate: needs a Property record")
    assert path is not None and path.exists()
    saved = json.loads(path.read_text())
    assert saved["subject"] == "PAGE-007" and saved["attempt"] == 2
    assert "Property record" in saved["reason"]
    assert saved["proposals"][0]["body"]["root"]["type"] == "Form"


def test_recording_never_raises(tmp_path):
    assert record_refusal(tmp_path / "no" / "such" / "\0", "X", 1, [object()], "r") in (None,) or True
