"""The figma_intelligence nodes in the §28 DAG.

Two nodes, one agent, because one node cannot be in two places in the graph.
§51 puts design extraction upstream of requirement inference; §40/§53 put the
extracted design system downstream of everything that could overwrite it. The
codebase already splits `page_design` and `data_model` across nodes for the
same reason.
"""
import pytest

from services.blueprint.agent_contract import AgentResult, ArtifactProposal
from services.blueprint.orchestrator import (
    DAG, FANOUT, levels, run, subjects_for,
)
from services.blueprint.service import BlueprintService
from services.figma.reference import (
    ComponentRef, DesignReference, DesignTokens, ScreenRef,
)
from services.figma.url import FigmaTarget
from services.figma import store


@pytest.fixture()
def svc(tmp_path):
    return BlueprintService.create(
        output_dir=tmp_path, app_id="a", name="Recruitment", domain="ATS"
    )


def a_reference(source_id="FIGMA-001"):
    ref = DesignReference(
        target=FigmaTarget(file_key="AbcDef123456", source_url="https://figma.com/x"),
        source_id=source_id,
        tokens=DesignTokens(
            colors={"color/brand/primary": "#3B5BDB"},
            spacing={"spacing/md": 16},
            typography={"font/heading": {"size": 32}},
        ),
    )
    ref.screens = [
        ScreenRef(node_id="1:2", name="Candidate List", canvas="Screens",
                  width=1440, height=900,
                  structure={"source": "design_context_code",
                             "labels": ["Candidates", "Schedule Interview"]}),
        ScreenRef(node_id="1:9", name="Cover", looks_like_screen=False),
    ]
    ref.components = [ComponentRef(node_id="5:1", name="PrimaryButton")]
    ref.gaps = ["prototype interactions unavailable"]
    return ref


# --- placement (§28, §51) --------------------------------------------------

def test_both_nodes_exist_and_use_the_registered_agent():
    assert DAG["figma_intelligence"].agent == "figma_intelligence"
    assert DAG["figma_design_system"].agent == "figma_intelligence"


def test_extraction_runs_before_the_application_model():
    """§51 — Figma Intelligence feeds requirement and entity inference."""
    order = [k for lvl in levels() for k in lvl]
    assert order.index("figma_intelligence") < order.index("application_model")


def test_design_system_projection_runs_after_the_agent_and_before_composition():
    """§40/§53 — an explicit user design outranks a generic recommendation, and
    `designSystem` is a singleton where the last writer of a key wins."""
    order = [k for lvl in levels() for k in lvl]
    assert order.index("design_system") < order.index("figma_design_system")
    assert order.index("figma_design_system") < order.index("page_layouts")


def test_the_node_never_authors_pages():
    """§31 — the Figma Intelligence Agent contributes evidence, not design."""
    assert "pages" not in DAG["figma_intelligence"].produces
    assert "pages" not in DAG["figma_design_system"].produces


def test_the_projection_does_not_resurrect_the_ui_registry():
    """`uiRegistry` was removed from the pipeline on purpose — it named
    components that were never code. The agent's §30 capability says so too,
    so writing one would be refused anyway."""
    from services.blueprint.agent_contract import capability_for

    assert "uiRegistry" not in DAG["figma_design_system"].produces
    assert "uiRegistry" not in capability_for("figma_intelligence").writes


# --- conditionality without a flag ----------------------------------------

def test_no_connected_design_means_no_subjects(svc):
    assert subjects_for(DAG["figma_intelligence"], svc.doc) == []


def test_a_connected_design_is_one_subject(svc):
    store.connect(svc, a_reference())
    assert subjects_for(DAG["figma_intelligence"], svc.doc) == ["FIGMA-001"]


def test_two_designs_are_two_subjects(svc):
    store.connect(svc, a_reference("FIGMA-001"))
    store.connect(svc, a_reference("FIGMA-002"))
    assert subjects_for(DAG["figma_intelligence"], svc.doc) == ["FIGMA-001", "FIGMA-002"]


def test_prompt_only_app_completes_the_node_without_calling_a_model(svc):
    """The Figma stage is conditional by being absent work, not by a flag."""
    called = []

    def executor(spec):
        called.append(spec.node)
        raise AssertionError("no model call should happen without a design")

    report = run(svc, executor, plan=["figma_intelligence"])
    assert report.completed == ["figma_intelligence"]
    assert called == []


def test_connected_design_does_invoke_the_agent(svc):
    store.connect(svc, a_reference())
    seen = []

    def executor(spec):
        seen.append((spec.node, spec.subject))
        return AgentResult(task_id=spec.task_id, agent=spec.agent,
                           status="completed", confidence=0.9, proposals=[])

    report = run(svc, executor, plan=["figma_intelligence"])
    assert report.completed == ["figma_intelligence"]
    assert seen == [("figma_intelligence", "FIGMA-001")]


# --- the deterministic projection (§47, §116) ------------------------------

def test_projection_writes_the_files_own_tokens(svc):
    store.connect(svc, a_reference())
    run(svc, lambda spec: None, plan=["figma_design_system"])

    ds = svc.doc["designSystem"]
    assert ds["derivedFromFigma"] is True
    assert ds["colors"] == {"color/brand/primary": "#3B5BDB"}
    assert ds["spacing"] == {"spacing/md": "16"}, "16, not 16.0"


def test_projection_outranks_what_the_design_system_agent_wrote(svc):
    """§40 precedence, as a property of merge order rather than an instruction."""
    svc.doc["designSystem"] = {
        "colors": {"primary": "#111111"},
        "accessibilityRules": ["contrast >= 4.5:1"],
        "informationDensity": "compact",
    }
    store.connect(svc, a_reference())
    run(svc, lambda spec: None, plan=["figma_design_system"])

    ds = svc.doc["designSystem"]
    assert ds["colors"] == {"color/brand/primary": "#3B5BDB"}, "Figma wins"
    # What Figma has nothing to say about survives untouched.
    assert ds["accessibilityRules"] == ["contrast >= 4.5:1"]
    assert ds["informationDensity"] == "compact"


def test_projection_does_not_empty_a_bucket_the_file_is_silent_on(svc):
    """An empty extraction overwriting a considered palette would be a
    regression disguised as an extraction."""
    svc.doc["designSystem"] = {"colors": {"primary": "#111111"}}
    ref = a_reference()
    ref.tokens = DesignTokens(spacing={"spacing/md": 8})
    store.connect(svc, ref)
    run(svc, lambda spec: None, plan=["figma_design_system"])

    assert svc.doc["designSystem"]["colors"] == {"primary": "#111111"}
    assert svc.doc["designSystem"]["spacing"] == {"spacing/md": "8"}


def test_projection_is_a_no_op_without_a_design(svc):
    before = dict(svc.doc.get("designSystem") or {})
    report = run(svc, lambda spec: None, plan=["figma_design_system"])
    assert report.completed == ["figma_design_system"]
    assert (svc.doc.get("designSystem") or {}) == before


def test_projection_is_idempotent(svc):
    store.connect(svc, a_reference())
    run(svc, lambda spec: None, plan=["figma_design_system"])
    first = dict(svc.doc["designSystem"])
    run(svc, lambda spec: None, plan=["figma_design_system"])
    assert svc.doc["designSystem"] == first


def test_missing_payload_is_recorded_not_invented(svc):
    """§93 — a restored Blueprint may name a source whose extraction is gone."""
    store.connect(svc, a_reference())
    (store.store_dir(svc.output_dir) / "FIGMA-001.json").unlink()
    run(svc, lambda spec: None, plan=["figma_design_system"])

    assert not (svc.doc.get("designSystem") or {}).get("colors")
    assert any("missing" in g for g in svc.doc["designSources"][0]["gaps"])


# --- store and brief (§14, §48, §91) ---------------------------------------

def test_the_design_payload_stays_out_of_the_blueprint(svc):
    """§91 snapshots the whole Blueprint per version; TSX and renders in the
    document would be copied into every one of them."""
    store.connect(svc, a_reference())
    record = svc.doc["designSources"][0]
    assert record["fileKey"] == "AbcDef123456"
    assert [f["name"] for f in record["frames"]] == ["Candidate List", "Cover"]
    serialised = __import__("json").dumps(svc.doc)
    assert "design_context_code" not in serialised
    assert "Schedule Interview" not in serialised


def test_reconnecting_the_same_file_updates_rather_than_duplicates(svc):
    store.connect(svc, a_reference())
    store.connect(svc, a_reference())
    assert len(svc.doc["designSources"]) == 1


def test_stored_reference_round_trips(svc):
    store.connect(svc, a_reference())
    back = store.load("FIGMA-001", svc.output_dir)
    assert back.source_id == "FIGMA-001"
    assert [s.name for s in back.screens] == ["Candidate List", "Cover"]
    assert back.tokens.colors == {"color/brand/primary": "#3B5BDB"}
    assert back.components[0].name == "PrimaryButton"


def test_next_source_id_follows_the_document(svc):
    assert store.next_source_id(svc.doc) == "FIGMA-001"
    store.connect(svc, a_reference("FIGMA-001"))
    assert store.next_source_id(svc.doc) == "FIGMA-002"


def test_the_prompt_carries_vocabulary_and_gaps_not_source(svc):
    """§48/§49 — labels are the evidence; TSX is layout noise that would crowd
    them out, and the gaps are what stops the agent filling them in."""
    from services.blueprint.executors import build_prompt

    store.connect(svc, a_reference())
    system, user = build_prompt(
        svc.doc, "figma_intelligence",
        subject="FIGMA-001", output_dir=svc.output_dir,
    )
    assert "Schedule Interview" in user
    assert "prototype interactions unavailable" in user
    assert "design_context_code" not in user
    assert '"type": "figma"' in user, "the §14 evidence shape is stated"
    assert "Cover" in user, "non-screens are shown, not hidden (§49)"


def test_the_brief_says_so_when_the_payload_is_gone(svc):
    from services.figma.brief import brief_for

    store.connect(svc, a_reference())
    (store.store_dir(svc.output_dir) / "FIGMA-001.json").unlink()
    brief = brief_for(svc.doc, "FIGMA-001", svc.output_dir)
    assert [s["name"] for s in brief["screens"]] == ["Candidate List"]
    assert any("no longer stored" in g for g in brief["gaps"])
