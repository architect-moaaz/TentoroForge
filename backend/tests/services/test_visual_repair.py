"""The render critique must drive a re-compose, not just a report."""

from services.blueprint.visual_repair import repair_briefs_from_visual_qa

DOC = {
    "pages": [
        {"id": "PAGE-001", "route": "/master-data"},
        {"id": "PAGE-003", "route": "/records/[id]/edit"},
        {"id": "PAGE-002", "route": "/add-data"},
    ]
}


def test_actionable_findings_become_per_page_briefs():
    qa = {"findings": [
        {"route": "/master-data", "kind": "sparse", "severity": "warn",
         "note": "The page is mostly empty below the table."},
        {"route": "/master-data", "kind": "duplicate_control", "severity": "error",
         "note": "Two search boxes for the one records list."},
    ]}
    briefs = repair_briefs_from_visual_qa(qa, DOC)
    assert set(briefs) == {"PAGE-001"}
    b = briefs["PAGE-001"]
    assert "sparse" in b and "duplicate_control" in b
    assert "empty below the table" in b and "Two search boxes" in b
    assert "Re-compose" in b


def test_a_concrete_route_matches_a_dynamic_page_template():
    qa = {"findings": [
        {"route": "/records/42/edit", "kind": "missing_content", "severity": "warn",
         "note": "The edit form is missing the age field."},
    ]}
    briefs = repair_briefs_from_visual_qa(qa, DOC)
    assert set(briefs) == {"PAGE-003"}
    assert "age field" in briefs["PAGE-003"]


def test_info_severity_and_unknown_routes_drive_nothing():
    qa = {"findings": [
        {"route": "/master-data", "kind": "off_brief", "severity": "info",
         "note": "Could use a warmer accent."},                     # advisory
        {"route": "/nowhere", "kind": "sparse", "severity": "error",
         "note": "blank"},                                          # no page
        {"route": "/add-data", "kind": "", "severity": "warn", "note": "x"},  # no kind
        {"route": "/add-data", "kind": "sparse", "severity": "warn", "note": ""},  # no note
    ]}
    assert repair_briefs_from_visual_qa(qa, DOC) == {}


def test_empty_or_missing_report_is_empty():
    assert repair_briefs_from_visual_qa(None, DOC) == {}
    assert repair_briefs_from_visual_qa({}, DOC) == {}
    assert repair_briefs_from_visual_qa({"findings": []}, DOC) == {}
