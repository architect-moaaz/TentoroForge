"""§8 layer 4 — the resolver over `codeMap`."""

import pytest

from services.smith.code_intelligence import (
    artifacts_for, context_for, files_for, unimplemented,
)

DOC = {
    "codeMap": [
        {"artifact": "PAGE-001", "service": ["src/schemas/plants.json"]},
        {"artifact": "ENTITY-001", "entity": "ENTITY-001",
         "service": ["src/db/schema/plant.ts"]},
        # One file, two artifacts — a route implements the page and its API.
        {"artifact": "API-001", "service": ["src/app/api/plants/route.ts"]},
        {"artifact": "PAGE-002", "service": ["src/app/api/plants/route.ts"],
         "frontend": ["src/schemas/plants/[id].json"]},
        {"artifact": "PAGE-009", "service": [], "status": "SUPERSEDED"},
    ],
    "pages": [{"id": "PAGE-001"}, {"id": "PAGE-002"}, {"id": "PAGE-003"}],
    "data": {"entities": [{"id": "ENTITY-001"}]},
}


def test_files_for_an_artifact():
    assert files_for(DOC, "PAGE-001") == ["src/schemas/plants.json"]


def test_every_path_key_counts_not_just_service():
    assert files_for(DOC, "PAGE-002") == [
        "src/app/api/plants/route.ts",
        "src/schemas/plants/[id].json",
    ]


def test_an_artifact_with_no_code_answers_empty_not_missing():
    """A page the projections have not reached has no files, which is a
    different fact from a page that does not exist."""
    assert files_for(DOC, "PAGE-003") == []


def test_the_identity_keys_are_not_paths():
    """`entity` names the artifact, not a file. Including it makes an id look
    like a path to everything downstream."""
    assert "ENTITY-001" not in files_for(DOC, "ENTITY-001")


def test_the_reverse_direction_is_what_the_forward_index_cannot_serve():
    """§113's preview→Blueprint link, §115's divergence check and §7's
    "understand the implementation" all ask this way round."""
    assert artifacts_for(DOC, "src/app/api/plants/route.ts") == [
        "API-001", "PAGE-002",
    ]


def test_a_path_nothing_implements_is_empty():
    assert artifacts_for(DOC, "src/lib/util.ts") == []


def test_superseded_entries_describe_code_that_moved():
    assert files_for(DOC, "PAGE-009") == []


def test_context_keeps_artifacts_that_have_no_code():
    ctx = context_for(DOC, ["PAGE-001", "PAGE-003"])
    assert ctx == {"PAGE-001": ["src/schemas/plants.json"], "PAGE-003": []}


def test_unimplemented_flags_what_the_blueprint_claims_and_code_lacks():
    """§115 — divergence is flagged, not silently resolved."""
    assert unimplemented(DOC) == ["PAGE-003"]


def test_apis_map_to_the_route_that_serves_them():
    """Endpoints are derived and served by one catch-all, so no file is written
    per API and nothing recorded them — `unimplemented` then read six live
    endpoints as unbuilt on every application."""
    from services.blueprint.projection import api_code_map

    doc = {"apis": [{"id": "API-001"}, {"id": "API-002"}]}
    entries = api_code_map(doc)
    assert [e["artifact"] for e in entries] == ["API-001", "API-002"]
    # One file, both artifacts — the many-to-one case the resolver expects.
    assert entries[0]["service"] == entries[1]["service"]

    doc["codeMap"] = entries
    assert artifacts_for(doc, entries[0]["service"][0]) == ["API-001", "API-002"]
    assert unimplemented(doc) == []


def test_requirements_are_not_expected_to_have_files():
    """A requirement is satisfied by the artifacts that claim it, not by a file
    of its own — §75's Requirement↔Code edge is what checks that. Counting them
    here reported ten divergences on a fully built application."""
    doc = {
        "requirements": [{"id": "REQ-001"}, {"id": "REQ-002"}],
        "pages": [{"id": "PAGE-001"}],
        "codeMap": [{"artifact": "PAGE-001", "service": ["src/p.json"]}],
    }
    assert unimplemented(doc) == []
