"""A fault in what Forge writes is reported to Forge (2026-10-31)."""
from __future__ import annotations

from services.smith import writes
from services.smith.platform_faults import open_faults, writer_of


def test_the_file_names_the_part_of_forge_that_writes_it():
    assert "drawing converter" in writer_of("app/src/components/drawn/DhChip.tsx")
    assert "page_module" in writer_of("src/app/(dashboard)/jobs/page.tsx")
    assert "drawn shell projector" in writer_of("src/components/DrawnShell.tsx")
    assert writer_of("src/app/(dashboard)/jobs/view.tsx") == ""          # the app's own page code


def test_a_fault_is_filed_once_and_counted_after(tmp_path):
    out_dir = tmp_path / "abc123"
    out_dir.mkdir()
    args = {"summary": "Drawn controls with a press handler show the arrow cursor",
            "path": "app/src/components/drawn/DhChip.tsx", "evidence": "open_page look: 14 show the arrow",
            "proposal": "params._with adds cursor-pointer wherever it adds onClick", "app_fix": "edit_pages, 40 screens"}
    first = writes.run("report_platform_fault", args, output_dir=str(out_dir))
    assert first["applied"] and "Reported to the platform team: Drawn controls" in first["said"]
    assert "drawing converter" in first["said"] and not first["touched"]
    again = writes.run("report_platform_fault", args, output_dir=str(out_dir))
    assert "again" in again["said"]
    faults = open_faults(tmp_path)
    assert len(faults) == 1 and faults[0]["times"] == 2 and faults[0]["app"] == "abc123"
    refused = writes.run("report_platform_fault", {"summary": "x"}, output_dir=str(out_dir))
    assert not refused["applied"] and "`proposal`" in refused["finding"]
