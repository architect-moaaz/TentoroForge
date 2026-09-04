"""§24 — the Application Definition, derived rather than restated."""
import json

import pytest

from services.blueprint.service import BlueprintService
from services.smith import definition as d


@pytest.fixture()
def svc(tmp_path):
    return BlueprintService.create(
        output_dir=tmp_path, app_id="a", name="Recruitment", domain="ATS"
    )


# --- derivation (§24, §116) ------------------------------------------------

def test_derives_the_seventeen_items_from_the_blueprint(ats):
    defined = d.derive(ats)
    assert defined.name and defined.domain
    counts = defined.counts()
    assert counts["pages"] == len(ats["pages"])
    assert counts["entities"] == len(ats["data"]["entities"])
    assert counts["workflows"] == len(ats["workflows"])
    assert counts["roles"] == len(ats["roles"])


def test_deprecated_artifacts_are_not_counted(ats):
    before = d.derive(ats).counts()["pages"]
    ats["pages"][0]["status"] = "DEPRECATED"
    assert d.derive(ats).counts()["pages"] == before - 1


def test_empty_application_derives_without_inventing(svc):
    defined = d.derive(svc.doc)
    assert defined.name == "Recruitment"
    assert defined.counts() == {
        k: 0 for k in defined.counts()
    }, "nothing is conjured from an empty Blueprint"


def test_evidence_is_rolled_up_by_source(svc):
    """§14 — a definition built from Smith's own inference is a different
    thing to approve than one built from a document the user wrote."""
    svc.doc["requirements"] = [
        {"id": "REQ-001", "description": "a",
         "evidence": [{"type": "figma", "source": "FIGMA-001", "node": "1:2"}]},
        {"id": "REQ-002", "description": "b",
         "evidence": [{"type": "conversation", "message": "MSG-003"}]},
        {"id": "REQ-003", "description": "c"},
    ]
    assert d.derive(svc.doc).evidence == {
        "conversation": 1, "figma": 1, "none": 1,
    }


def test_thin_dimensions_are_named(svc):
    """A definition that stays quiet about having no security model reads as
    complete (§15, §102)."""
    thin = d.derive(svc.doc).thin
    assert "security" in thin and "workflows" in thin


def test_design_direction_records_figma_provenance(svc):
    svc.doc["designSystem"] = {"derivedFromFigma": True, "visualPersonality": "calm"}
    svc.doc["designSources"] = [{"id": "FIGMA-001", "type": "figma",
                                 "fileKey": "k", "frames": []}]
    direction = d.derive(svc.doc).design_direction
    assert direction["derivedFromFigma"] is True
    assert direction["sources"] == ["FIGMA-001"]


# --- digest (§25, §76) -----------------------------------------------------

def test_digest_is_stable_across_identical_derivations(ats):
    assert d.digest(d.derive(ats)) == d.digest(d.derive(ats))


def test_digest_ignores_generated_prose(ats):
    """The summary paragraph varies between runs; a digest that moved with it
    would mark every approval stale for no reason."""
    a = d.derive(ats)
    b = d.derive(ats)
    b.description = "A completely different paragraph."
    b.open_questions = ["and a different question"]
    assert d.digest(a) == d.digest(b)


def test_digest_changes_when_a_page_appears(ats):
    before = d.digest(d.derive(ats))
    ats["pages"].append({
        "id": "PAGE-900", "name": "Settings", "route": "/settings",
        "purpose": "Configure the workspace",
    })
    assert d.digest(d.derive(ats)) != before


def test_digest_changes_when_an_artifact_is_renamed(ats):
    before = d.digest(d.derive(ats))
    ats["roles"][0]["name"] = "Talent Partner"
    assert d.digest(d.derive(ats)) != before


def test_digest_survives_a_reworded_purpose(ats):
    """Rewording a page's purpose has not changed the application the user
    agreed to; a page appearing or being renamed has."""
    before = d.digest(d.derive(ats))
    ats["pages"][0]["purpose"] = "Reworded, same page, same job."
    assert d.digest(d.derive(ats)) == before


# --- rendering -------------------------------------------------------------

def test_render_is_readable_and_leads_with_identity(ats):
    text = d.render(d.derive(ats))
    assert text.splitlines()[0] == ats["application"]["name"]
    for heading in ("Roles", "Pages", "Workflows", "Data"):
        assert heading in text


def test_render_always_shows_what_is_missing(svc):
    text = d.render(d.derive(svc.doc))
    assert "Not yet established" in text
    assert "security" in text


def test_render_truncates_long_lists_without_hiding_the_count(ats):
    text = d.render(d.derive(ats))
    assert f"Pages ({len(ats['pages'])})" in text
    if len(ats["pages"]) > 12:
        assert "and " in text and "more" in text


# --- no model call at all (§116) --------------------------------------------

def test_definition_module_calls_no_model():
    """Every one of §24's items here is counted from the Blueprint. The prose
    paragraph a definition might also carry is `smith.domain_summary`'s job,
    not a second summariser living in this module."""
    import pathlib as _p
    source = (_p.Path(__file__).resolve().parents[2]
              / "services" / "smith" / "definition.py").read_text("utf-8")
    assert "client(" not in source
