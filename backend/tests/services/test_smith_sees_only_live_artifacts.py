"""TCommerce (ihf6pjga, forge-v3, 2026-10-05): asked why only two pages were
built, Smith listed nineteen — sixteen of them retired (DEPRECATED) and
serving 404. Smith's view of the Blueprint skipped only SUPERSEDED."""
from services.smith import engine_blueprint_adapter as adapter


def test_a_retired_artifact_is_not_live():
    rows = [{"id": "PAGE-001", "status": "PROPOSED"}, {"id": "PAGE-002", "status": "DEPRECATED"},
            {"id": "PAGE-003", "status": "SUPERSEDED"}, {"id": "PAGE-004", "status": "OUT_OF_SYNC"},
            {"id": "PAGE-005"}]
    assert [r["id"] for r in adapter._live(rows)] == ["PAGE-001", "PAGE-004", "PAGE-005"]
