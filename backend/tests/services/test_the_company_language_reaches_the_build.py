"""The company's design language, from the organisation to the application.

Two consumers and one condition. The tokens are merged over `designSystem` by
`brand_design_system`; the document is put in front of the agents that can act
on it. Both happen only when the owner answered `company` at the gate — an
application that inherits a palette nobody chose for it is the failure this
whole path is shaped to avoid.
"""
from __future__ import annotations

from services.blueprint import brand_language
from services.blueprint.service import BlueprintService

import pytest


DESIGN = {
    "colors": {"primary": "#1B7F5A", "accent": "#F59E0B", "background": "#FFFFFF"},
    "typography": {"fontFamilyBase": "Inter"},
    "radius": {"md": "8px"},
    "informationDensity": "spacious",
    "logo": {"file": "brand/deadbeefdeadbeef.png", "mediaType": "image/png",
             "alt": "Northwind logo"},
}

DOC_MD = "# Northwind — design language\n\nRead from https://northwind.test.\n"


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="a",
                                name="Deliveries", domain="Operations")
    s.doc["designSystem"] = {
        "visualPersonality": "Chosen from the domain: a calm operations tool.",
        "colors": {"primary": "#2563EB", "destructive": "#EF4444"},
        "accessibilityRules": ["Every control reachable by keyboard."],
        "navigationApproach": "A left rail.",
    }
    s.validate()
    s.save()
    return s


def test_nothing_adopted_is_nothing_read(tmp_path):
    assert brand_language.available(tmp_path) is False
    assert brand_language.tokens(tmp_path) == {}
    assert brand_language.document(tmp_path) == ""
    assert brand_language.addendum(tmp_path, "design_system",
                                   {"application": {"designLanguage": "company"}}) == ""


def test_adopting_writes_the_document_and_the_tokens_beside_the_blueprint(tmp_path):
    overlay = brand_language.adopt(tmp_path, design_md=DOC_MD, design=DESIGN,
                                   company_name="Northwind")
    assert brand_language.available(tmp_path) is True
    assert brand_language.document(tmp_path) == DOC_MD
    stored = brand_language.tokens(tmp_path)
    assert stored["colors"]["primary"] == "#1B7F5A"
    assert stored["_companyName"] == "Northwind"
    # The mark is NOT carried by reference: `designSystem.logo.file` is a path
    # relative to THIS application, and a path into the platform's brand store
    # is an application that cannot be exported or rebuilt elsewhere.
    assert "logo" not in overlay


def test_re_adopting_replaces_rather_than_layers(tmp_path):
    """A company that redesigns must not have yesterday's palette merged over
    today's."""
    brand_language.adopt(tmp_path, design_md=DOC_MD, design=DESIGN)
    brand_language.adopt(tmp_path, design_md="# New\n",
                         design={"colors": {"primary": "#7C3AED"}})
    stored = brand_language.tokens(tmp_path)
    assert stored["colors"] == {"primary": "#7C3AED"}
    assert "typography" not in stored
    assert brand_language.document(tmp_path) == "# New\n"


def test_clearing_takes_the_language_back_off(tmp_path):
    brand_language.adopt(tmp_path, design_md=DOC_MD, design=DESIGN)
    brand_language.clear(tmp_path)
    assert brand_language.available(tmp_path) is False
    brand_language.clear(tmp_path)  # safe when there is none


def test_a_malformed_tokens_file_is_a_build_without_a_language(tmp_path):
    brand_language.adopt(tmp_path, design_md=DOC_MD, design=DESIGN)
    (brand_language.directory(tmp_path) / brand_language.TOKENS).write_text("{oh no")
    assert brand_language.tokens(tmp_path) == {}


# --------------------------------------------------------------------------- #
# what the agents are shown
# --------------------------------------------------------------------------- #

def test_only_the_nodes_that_can_act_on_it_are_shown_it(tmp_path):
    brand_language.adopt(tmp_path, design_md=DOC_MD, design=DESIGN)
    doc = {"application": {"designLanguage": "company"}}
    for node in ("requirements", "application_model", "design_system"):
        assert DOC_MD.strip() in brand_language.addendum(tmp_path, node, doc)
    # A forty-page document on every call is paid for on every call.
    for node in ("page_contracts", "data_model", "workflows", "security"):
        assert brand_language.addendum(tmp_path, node, doc) == ""


def test_the_requirements_agent_is_told_this_is_not_a_specification():
    """"We bake sourdough" must not become a requirement that the application
    bake sourdough."""
    said = brand_language.READ_FOR["requirements"]
    assert "NOT a source of requirements" in said
    assert brand_language.READ_FOR["application_model"].count("not what this application does")

    # And the design agent is told the opposite: this one IS the answer.
    assert "the answer rather than" in brand_language.READ_FOR["design_system"]


def test_an_app_that_chose_its_own_look_is_never_shown_the_company_s(tmp_path):
    brand_language.adopt(tmp_path, design_md=DOC_MD, design=DESIGN)
    for doc in ({"application": {"designLanguage": "custom"}},
                {"application": {}}, {}, None):
        assert brand_language.addendum(tmp_path, "design_system", doc) == ""


# --------------------------------------------------------------------------- #
# the projection
# --------------------------------------------------------------------------- #

def _project(svc):
    from services.blueprint.orchestrator import _project_company_language

    _project_company_language(svc)
    return BlueprintService.load(output_dir=svc.output_dir).doc["designSystem"]


def test_the_company_outranks_what_the_platform_recommended_on_its_own(svc):
    brand_language.adopt(svc.output_dir, design_md=DOC_MD, design=DESIGN,
                         company_name="Northwind")
    svc.doc.setdefault("application", {})["designLanguage"] = "company"
    svc.save()

    design_system = _project(svc)
    assert design_system["colors"]["primary"] == "#1B7F5A"
    assert design_system["typography"]["fontFamilyBase"] == "Inter"
    assert design_system["informationDensity"] == "spacious"
    # The agent keeps every key the company has nothing to say about.
    assert design_system["accessibilityRules"] == ["Every control reachable by keyboard."]
    assert design_system["navigationApproach"] == "A left rail."
    # The personality names whose language this is, rather than leaving the
    # agent's explanation of a palette it no longer has.
    assert design_system["visualPersonality"].startswith("Northwind's own design language")
    # The company's NAME is not a design token.
    assert "_companyName" not in design_system


def test_choosing_a_custom_look_leaves_the_agent_s_design_standing(svc):
    brand_language.adopt(svc.output_dir, design_md=DOC_MD, design=DESIGN)
    svc.doc.setdefault("application", {})["designLanguage"] = "custom"
    svc.save()
    assert _project(svc)["colors"]["primary"] == "#2563EB"


def test_an_unasked_application_keeps_its_own_design(svc):
    """Absent is not `company`. This is the one that would quietly repaint
    every app built before the question existed."""
    brand_language.adopt(svc.output_dir, design_md=DOC_MD, design=DESIGN)
    assert _project(svc)["colors"]["primary"] == "#2563EB"


def test_choosing_the_company_with_nothing_adopted_is_not_a_failure(svc):
    """An organisation whose discovery was later deleted still builds."""
    svc.doc.setdefault("application", {})["designLanguage"] = "company"
    svc.save()
    assert _project(svc)["colors"]["primary"] == "#2563EB"


def test_the_node_runs_after_the_design_agent_and_before_the_figma_projection():
    """`designSystem` is a singleton, so the last writer of a key wins and the
    ordering IS the precedence: the company outranks the platform's own
    recommendation, and a design attached to THIS app outranks the company."""
    from services.blueprint.orchestrator import DAG, SERVICE_HANDLERS

    node = DAG["brand_design_system"]
    assert node.kind == "service"
    assert "design_system" in node.depends_on
    assert "designSystem" in node.produces
    assert "brand_design_system" in DAG["figma_design_system"].depends_on
    assert "brand_design_system" in SERVICE_HANDLERS
