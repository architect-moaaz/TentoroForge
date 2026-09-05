"""Copying only adds. The scaffold retired its root page, which redirected to
a hard-coded /home no application has, and every application built before
kept it beside the group's index at "/". Assembly removes what the scaffold
no longer ships."""
from pathlib import Path
from services.blueprint.assembly import copy_scaffold, RETIRED_SCAFFOLD_FILES


def test_the_old_root_page_is_removed_on_assembly(tmp_path):
    stale = tmp_path / "src" / "app" / "page.tsx"
    stale.parent.mkdir(parents=True)
    stale.write_text('export default function RootPage() { redirect("/home"); }')
    written = copy_scaffold(tmp_path, project_short_id="abcd1234")
    assert "src/app/page.tsx" in RETIRED_SCAFFOLD_FILES
    assert "src/app/page.tsx" not in written
    assert not stale.exists()
