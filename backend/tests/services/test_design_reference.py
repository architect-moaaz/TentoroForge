"""A design reference has to be DESIGNATED, never inferred.

`brief_from_screenshot` can turn a montage into a locked palette + type
scale. Wiring it needs one more thing the pipeline did not have: a way to
know WHICH uploaded image is the design reference.

The tempting shortcut — "use every image attached to this project" — is
wrong in a way that would be hard to trace later. Users attach screenshots
to REPORT problems ("this table looks broken"), and those are far more
common than design references. Harvesting them would let a screenshot of a
bug set the app's brand colour, and the resulting palette would look like a
model hallucination rather than a plumbing mistake.

So designation is explicit and stored per project, and the loader returns
image blocks ONLY for ids the user pointed at.
"""
from __future__ import annotations

import base64
import json

import pytest

from services import chat_attachments
from services.design_reference import (
    load_design_reference_blocks,
    read_design_references,
    set_design_references,
)

# 1x1 PNG — real bytes so save_attachment classifies it as an image.
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture()
def root(tmp_path):
    return tmp_path / "_attachments"


def _upload(root, project_id: str, name: str) -> str:
    rec = chat_attachments.save_attachment(root, project_id, name, "image/png", _PNG)
    return rec["id"]


class TestDesignationRoundTrips:
    def test_set_then_read(self, root):
        a = _upload(root, "p1", "montage.png")
        set_design_references(root, "p1", [a])
        assert read_design_references(root, "p1") == [a]

    def test_unset_project_has_none(self, root):
        assert read_design_references(root, "p1") == []

    def test_set_replaces_rather_than_appends(self, root):
        a = _upload(root, "p1", "old.png")
        b = _upload(root, "p1", "new.png")
        set_design_references(root, "p1", [a])
        set_design_references(root, "p1", [b])
        assert read_design_references(root, "p1") == [b]

    def test_clearing_is_expressible(self, root):
        a = _upload(root, "p1", "montage.png")
        set_design_references(root, "p1", [a])
        set_design_references(root, "p1", [])
        assert read_design_references(root, "p1") == []


class TestOnlyDesignatedImagesLoad:
    def test_an_undesignated_attachment_is_not_a_reference(self, root):
        """The whole point: a bug screenshot must not reach the brief."""
        _upload(root, "p1", "broken-table-screenshot.png")
        assert load_design_reference_blocks(root, "p1") == []

    def test_designated_image_yields_an_image_block(self, root):
        a = _upload(root, "p1", "montage.png")
        set_design_references(root, "p1", [a])
        blocks = load_design_reference_blocks(root, "p1")
        assert any(b.get("type") == "image" for b in blocks)

    def test_designating_one_of_two_loads_only_that_one(self, root):
        a = _upload(root, "p1", "montage.png")
        _upload(root, "p1", "bug.png")
        set_design_references(root, "p1", [a])
        blocks = load_design_reference_blocks(root, "p1")
        assert len([b for b in blocks if b.get("type") == "image"]) == 1

    def test_projects_are_isolated(self, root):
        a = _upload(root, "p1", "montage.png")
        set_design_references(root, "p1", [a])
        assert load_design_reference_blocks(root, "p2") == []


class TestNeverBlocksGeneration:
    """Brief authoring is best-effort; a broken reference must not raise."""

    def test_a_deleted_attachment_is_skipped(self, root):
        a = _upload(root, "p1", "montage.png")
        set_design_references(root, "p1", [a])
        for f in (root / "p1").glob(f"{a}*"):
            f.unlink()
        assert load_design_reference_blocks(root, "p1") == []

    def test_corrupt_designation_file_reads_as_none(self, root):
        d = root / "p1"
        d.mkdir(parents=True, exist_ok=True)
        (d / "design-references.json").write_text("{not json", encoding="utf-8")
        assert read_design_references(root, "p1") == []

    def test_unsafe_project_id_does_not_escape(self, root):
        assert read_design_references(root, "../etc") == []
        assert load_design_reference_blocks(root, "../etc") == []

    def test_non_list_payload_reads_as_none(self, root):
        d = root / "p1"
        d.mkdir(parents=True, exist_ok=True)
        (d / "design-references.json").write_text(
            json.dumps({"ids": "not-a-list"}), encoding="utf-8")
        assert read_design_references(root, "p1") == []
