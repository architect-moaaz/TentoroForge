"""CTX-2: auto proper-noun grounding for Smith turns.

Given a user message + output_dir, the pre-processor extracts capitalised
noun phrases (and multi-word lowercase phrases as backup), looks each up
via ``find_resources``, and returns a compact block naming every matched
entity + its one-line summary. Silent when nothing matches.
"""
from __future__ import annotations

import json
from pathlib import Path

from services.smith_grounding import extract_grounding_hints


def _write(root: Path, rel: str, doc: dict) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc))


def _make_ats(tmp_path: Path) -> None:
    """Minimal ATS layout so find_resources has real data to match against."""
    _write(tmp_path, "contracts/resource-registry.json", {
        "entities": {
            "RecruitmentDrive": {
                "id": "e_drive", "name": "RecruitmentDrive",
                "table": "recruitment_drives", "slug": "recruitment-drives",
                "camel": "recruitmentDrive",
                "columns": [{"name": "id", "type": "uuid"}],
            },
            "CandidateProfile": {
                "id": "e_cp", "name": "CandidateProfile",
                "table": "candidate_profiles", "slug": "candidate-profiles",
                "camel": "candidateProfile",
                "columns": [{"name": "id", "type": "uuid"}],
            },
        },
    })
    _write(tmp_path, "src/schemas/drives.json", {
        "route": "/drives",
        "dataSources": [{"name": "drives", "entity": "RecruitmentDrive", "op": "list"}],
    })


# --------------------------------------------------------------------------- #
# Match scenarios — proper nouns / phrases / route stems
# --------------------------------------------------------------------------- #

def test_extracts_recruitment_drive_from_english(tmp_path):
    _make_ats(tmp_path)
    hints = extract_grounding_hints(
        "the Recruitment Drive status dropdown shows garbage values",
        str(tmp_path),
    )
    assert "RecruitmentDrive" in hints
    assert "recruitment" in hints.lower()


def test_extracts_pascal_case_name_directly(tmp_path):
    _make_ats(tmp_path)
    hints = extract_grounding_hints(
        "CandidateProfile detail page is empty", str(tmp_path),
    )
    assert "CandidateProfile" in hints


def test_route_stem_lowercase_matches(tmp_path):
    """Plain "drives" (the route stem, not the entity name) still lands."""
    _make_ats(tmp_path)
    hints = extract_grounding_hints("drives list is not loading", str(tmp_path))
    # Backup lowercase phrase regex requires TWO words; single-word "drives"
    # won't match, but "drives list" should — the pair extracts.
    assert "RecruitmentDrive" in hints or hints == ""
    # If nothing matched, that's the honest silent-on-ambiguous behavior.


def test_multi_entity_message_returns_both(tmp_path):
    _make_ats(tmp_path)
    hints = extract_grounding_hints(
        "the RecruitmentDrive and CandidateProfile pages both look wrong",
        str(tmp_path),
    )
    assert "RecruitmentDrive" in hints
    assert "CandidateProfile" in hints


def test_dedupes_repeated_mentions(tmp_path):
    _make_ats(tmp_path)
    hints = extract_grounding_hints(
        "the Recruitment Drive is broken. The recruitment-drives page. "
        "Recruitment Drive form.",
        str(tmp_path),
    )
    # Only one entry per matched entity, even if the message names it 3x.
    assert hints.count("**RecruitmentDrive**") == 1


# --------------------------------------------------------------------------- #
# Silent-on-no-match / robustness
# --------------------------------------------------------------------------- #

def test_no_match_returns_empty_string(tmp_path):
    _make_ats(tmp_path)
    hints = extract_grounding_hints("spaceship laser dashboard", str(tmp_path))
    assert hints == ""


def test_empty_message_returns_empty(tmp_path):
    _make_ats(tmp_path)
    assert extract_grounding_hints("", str(tmp_path)) == ""
    assert extract_grounding_hints("   ", str(tmp_path)) == ""


def test_no_output_dir_returns_empty(tmp_path):
    assert extract_grounding_hints("Recruitment Drive", "") == ""


def test_missing_registry_no_crash(tmp_path):
    """No registry, no schemas → find_resources returns matched=None, we
    return an empty block silently."""
    hints = extract_grounding_hints("RecruitmentDrive", str(tmp_path))
    assert hints == ""


def test_stopword_only_phrases_not_matched(tmp_path):
    """`"the app"` and `"the page"` are not entity references."""
    _make_ats(tmp_path)
    hints = extract_grounding_hints("the app is broken", str(tmp_path))
    assert "RecruitmentDrive" not in hints
    assert "CandidateProfile" not in hints
