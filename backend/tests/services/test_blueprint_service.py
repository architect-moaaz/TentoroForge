"""The Blueprint is only a source of truth if it is hard to corrupt.

§115 makes the Blueprint the definition an application is generated *from*, so
the failure that matters is not a crash — it is the service accepting a
document that is subtly wrong, or quietly discarding one that was right. A
Blueprint that silently resets, renumbers, or repairs is worse than one that
refuses, because generation downstream will happily proceed from the damage.

So most of these tests are about refusal: invalid documents don't get versioned,
corrupt files don't become empty ones, and disagreement between Blueprint and
implementation is recorded rather than fixed (§76).
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from services.blueprint.ids import IdAllocator, entity_key, page_key, prose_key
from services.blueprint.service import (
    ARTIFACT_SECTIONS,
    CONTRACT_PATH,
    BlueprintInvalid,
    BlueprintService,
    ArtifactNotFound,
    empty_blueprint,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture()
def svc(tmp_path) -> BlueprintService:
    return BlueprintService.create(
        output_dir=tmp_path, app_id="app_1", name="Recruitment", domain="ATS"
    )


# --- contract --------------------------------------------------------------

def test_generated_contract_is_present_and_is_the_blueprint():
    assert CONTRACT_PATH.exists(), "run npm run emit:blueprint-schema"
    schema = json.loads(CONTRACT_PATH.read_text("utf-8"))
    assert schema["$schema"].startswith("http://json-schema.org/draft-07")
    assert set(schema["required"]) == {"schemaVersion", "application"}
    assert len(schema["properties"]) == 31


def test_minimal_blueprint_validates(svc):
    svc.validate()
    assert svc.doc["state"] == "DISCOVERY"
    assert svc.doc["version"] == 1


def test_invalid_document_is_refused(svc):
    svc.doc["requirements"] = [{"id": "REQUIREMENT-1", "description": "x"}]
    with pytest.raises(BlueprintInvalid) as exc:
        svc.validate()
    assert "requirements" in str(exc.value)


def test_corrupt_file_raises_instead_of_becoming_an_empty_blueprint(tmp_path):
    svc = BlueprintService.create(
        output_dir=tmp_path, app_id="a", name="n", domain="d"
    )
    svc.current_path.write_text("{ not json", "utf-8")
    with pytest.raises(BlueprintInvalid):
        BlueprintService.load(output_dir=tmp_path)


# --- identity --------------------------------------------------------------

def test_upsert_allocates_a_stable_id(svc):
    a = svc.upsert(
        "data.entities",
        {"name": "Candidate", "table": "candidates"},
        natural_key=entity_key("Candidate"),
    )
    assert a["id"] == "ENTITY-001"
    assert a["status"] == "PROPOSED"
    svc.validate()


def test_upserting_the_same_artifact_twice_updates_rather_than_duplicates(svc):
    key = entity_key("Candidate")
    first = svc.upsert("data.entities", {"name": "Candidate", "table": "candidates"}, natural_key=key)
    second = svc.upsert(
        "data.entities",
        {"name": "Candidate", "table": "candidates", "labelField": "fullName"},
        natural_key=key,
    )
    assert first["id"] == second["id"]
    assert len(svc.doc["data"]["entities"]) == 1
    assert svc.doc["data"]["entities"][0]["labelField"] == "fullName"


def test_ids_survive_a_reload(tmp_path):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="a", name="n", domain="d")
    svc.upsert("pages", {"name": "Candidates", "route": "/candidates",
                         "purpose": "Manage candidates."}, natural_key=page_key("/candidates"))
    svc.save()

    reloaded = BlueprintService.load(output_dir=tmp_path)
    again = reloaded.upsert(
        "pages",
        {"name": "Talent Pool", "route": "/candidates", "purpose": "Manage candidates."},
        natural_key=page_key("/candidates"),
    )
    assert again["id"] == "PAGE-001"
    assert len(reloaded.doc["pages"]) == 1


def test_find_locates_artifacts_across_sections(svc):
    svc.upsert("data.entities", {"name": "Candidate", "table": "candidates"},
               natural_key=entity_key("Candidate"))
    svc.upsert("requirements", {"description": "Recruiter can schedule interviews."},
               natural_key=prose_key("REQ", "Recruiter can schedule interviews."))
    assert svc.find("ENTITY-001")[0] == "data.entities"
    assert svc.find("REQ-001")[0] == "requirements"
    with pytest.raises(ArtifactNotFound):
        svc.find("REQ-999")


def test_every_artifact_section_maps_to_a_real_schema_property():
    schema = json.loads(CONTRACT_PATH.read_text("utf-8"))
    for section in ARTIFACT_SECTIONS:
        assert section in schema["properties"], section


# --- §76: record divergence, never repair it -------------------------------

def test_out_of_sync_is_recorded_not_fixed(svc):
    svc.upsert("data.entities", {"name": "Candidate", "table": "candidates"},
               natural_key=entity_key("Candidate"))
    svc.mark_out_of_sync("ENTITY-001", "table candidates has no column 'stage'")

    art = svc.find("ENTITY-001")[1]
    assert art["status"] == "OUT_OF_SYNC"
    assert "stage" in art["syncNote"]
    assert [a["id"] for a in svc.out_of_sync()] == ["ENTITY-001"]
    svc.validate()


def test_recovering_from_out_of_sync_clears_the_note(svc):
    svc.upsert("data.entities", {"name": "Candidate", "table": "candidates"},
               natural_key=entity_key("Candidate"))
    svc.mark_out_of_sync("ENTITY-001", "drifted")
    svc.set_status("ENTITY-001", "VERIFIED")
    art = svc.find("ENTITY-001")[1]
    assert art["status"] == "VERIFIED"
    assert "syncNote" not in art


def test_status_outside_section_22_is_refused(svc):
    svc.upsert("data.entities", {"name": "C", "table": "c"}, natural_key=entity_key("C"))
    with pytest.raises(ValueError):
        svc.set_status("ENTITY-001", "PROBABLY_FINE")


# --- §91 / §92: versioning and change history ------------------------------

def test_commit_bumps_the_version_and_records_a_diff(svc):
    before = svc.snapshot()
    svc.upsert("data.entities", {"name": "Candidate", "table": "candidates"},
               natural_key=entity_key("Candidate"))
    record = svc.commit(
        user_request="Add vehicle blacklist management.",
        smith_interpretation="New entity + admin page.",
        before=before,
        affected=["ENTITY-001"],
    )
    assert record["version"] == 2
    assert svc.doc["version"] == 2
    assert record["affectedArtifacts"] == ["ENTITY-001"]
    assert any(op["op"] == "add" for op in record["blueprintDiff"])
    assert svc.doc["changeHistory"][-1]["userRequest"].startswith("Add vehicle")


def test_commit_refuses_to_version_an_invalid_blueprint(svc):
    before = svc.snapshot()
    svc.doc["requirements"] = [{"id": "nope", "description": "x"}]
    with pytest.raises(BlueprintInvalid):
        svc.commit(user_request="break it", before=before)
    assert svc.doc["version"] == 1, "an invalid change must not advance the version"


def test_prior_version_is_snapshotted_for_rollback(svc):
    before = svc.snapshot()
    svc.upsert("data.entities", {"name": "Candidate", "table": "candidates"},
               natural_key=entity_key("Candidate"))
    svc.commit(user_request="add entity", before=before)
    assert svc.versions() == [1]
    assert svc.version_path(1).exists()


# --- §93: a failed change must not destroy the last good application -------

def test_rollback_restores_a_previous_version(svc):
    before = svc.snapshot()
    svc.upsert("data.entities", {"name": "Candidate", "table": "candidates"},
               natural_key=entity_key("Candidate"))
    svc.commit(user_request="add entity", before=before)
    assert len(svc.doc["data"]["entities"]) == 1

    svc.rollback(1)
    assert svc.doc["version"] == 1
    assert svc.doc.get("data", {}).get("entities", []) == []


def test_rollback_snapshots_what_it_replaces(svc):
    before = svc.snapshot()
    svc.upsert("data.entities", {"name": "Candidate", "table": "candidates"},
               natural_key=entity_key("Candidate"))
    svc.commit(user_request="add entity", before=before)
    svc.rollback(1)
    # v2 must still be recoverable — rollback is not deletion
    assert 2 in svc.versions()


def test_rollback_to_a_missing_version_raises(svc):
    with pytest.raises(FileNotFoundError):
        svc.rollback(99)


# --- §83: export -----------------------------------------------------------

def test_export_writes_blueprint_json_to_the_package_root(svc, tmp_path):
    pkg = tmp_path / "export"
    dest = svc.export_to(pkg)
    assert dest.name == "blueprint.json"
    assert json.loads(dest.read_text("utf-8"))["application"]["name"] == "Recruitment"


# --- coexistence with the legacy Blueprint ---------------------------------

def test_does_not_collide_with_legacy_smith_blueprint(tmp_path):
    """`services.smith_blueprint` owns `.forge/blueprint.json`. Until that is
    retired, both must be able to exist without overwriting each other."""
    from services.smith_blueprint import Blueprint as LegacyBlueprint

    legacy = LegacyBlueprint(project_id="p1", _output_dir=str(tmp_path))
    legacy.save()

    svc = BlueprintService.create(
        output_dir=tmp_path, app_id="p1", name="n", domain="d"
    )
    assert svc.current_path.exists()
    assert (tmp_path / ".forge" / "blueprint.json").exists()
    assert svc.current_path != (tmp_path / ".forge" / "blueprint.json")


# --- cross-language drift ---------------------------------------------------

def test_blueprint_schema_is_current():
    """Regenerate the contract and confirm it matches what is committed.

    The Zod source is authoritative (§11). If someone edits it and forgets to
    re-emit, Python validates against a stale contract and accepts documents
    the TypeScript side will reject.
    """
    pkg = REPO_ROOT / "packages" / "schema"
    if not (pkg / "node_modules").exists():
        pytest.skip("packages/schema dependencies not installed")

    committed = CONTRACT_PATH.read_bytes()
    try:
        out = subprocess.run(
            ["npm", "run", "--silent", "emit:blueprint-schema"],
            cwd=pkg, capture_output=True, text=True, timeout=300,
        )
        assert out.returncode == 0, out.stderr
        regenerated = CONTRACT_PATH.read_bytes()
    finally:
        # Never leave the tree mutated by a test run.
        CONTRACT_PATH.write_bytes(committed)

    assert regenerated == committed, (
        "blueprint.schema.json is stale — re-run "
        "`npm run emit:blueprint-schema --workspace=packages/schema`"
    )
