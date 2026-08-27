"""AM-2 — render_app_map_skeleton: turn the dict into Smith's prompt block."""
from __future__ import annotations

from services.app_map import build_app_map
from services.app_map_render import render_app_map_skeleton


def _sample_map() -> dict:
    """A hand-authored map so this test doesn't depend on the fixture app.

    Deliberately small so the assertions can be verbatim, but shaped like
    a real app (entities with FKs, pages of every archetype, workflows of
    both kinds)."""
    return {
        "intent": "Applicant Tracking System for aviation cabin crew recruitment.",
        "entities": {
            "Candidate": {
                "table": "candidates", "slug": "candidates",
                "columns_count": 24,
                "fks_out": [{"col": "cvUploadId", "target_entity": "CVUpload", "target_slug": "c-v-upload"}],
                "fks_in":  [{"from_entity": "Application", "col": "candidateId"}],
            },
            "User": {
                "table": "users", "slug": "users",
                "columns_count": 8, "fks_out": [], "fks_in": [],
            },
        },
        "pages": [
            {"route": "/candidates", "path": "src/schemas/candidates.json",
             "archetype": "list", "entity": "Candidate",
             "form_submit_workflow": None},
            {"route": "/candidates/new", "path": "src/schemas/candidates/new.json",
             "archetype": "form", "entity": "Candidate",
             "form_submit_workflow": "create-candidate"},
            {"route": "/candidates/[id]", "path": "src/schemas/candidates/[id].json",
             "archetype": "detail", "entity": "Candidate",
             "form_submit_workflow": None},
            {"route": "/pipeline", "path": "src/schemas/pipeline.json",
             "archetype": "dashboard", "entity": None,
             "form_submit_workflow": None},
        ],
        "workflows": {
            "create-candidate":     {"kind": "auto-crud", "op": "create", "target": "Candidate"},
            "update-candidate":     {"kind": "auto-crud", "op": "update", "target": "Candidate"},
            "ShortlistingWorkflow": {"kind": "domain", "target": "Application"},
        },
    }


# --------------------------------------------------------------------------- #
# Header + intent
# --------------------------------------------------------------------------- #

def test_skeleton_starts_with_header_and_intent():
    s = render_app_map_skeleton(_sample_map())
    assert s.startswith("# APP MAP")
    assert "intent:" in s
    assert "aviation cabin crew" in s


# --------------------------------------------------------------------------- #
# Entities
# --------------------------------------------------------------------------- #

def test_entities_section_lists_every_entity(_map=_sample_map()):
    s = render_app_map_skeleton(_map)
    for name in _map["entities"]:
        assert name in s


def test_entity_lines_show_column_count_and_fk_targets():
    s = render_app_map_skeleton(_sample_map())
    # Candidate has 24 cols and one FK out to CVUpload
    assert "Candidate (24 cols)" in s
    assert "cvUploadId→CVUpload" in s


def test_entity_lines_do_not_leak_full_column_lists():
    """The skeleton is a summary; per-column detail is behind read_entity."""
    m = _sample_map()
    m["entities"]["Candidate"]["columns_count"] = 24
    s = render_app_map_skeleton(m)
    # Not the shape of a column list: no "firstName" or "email" leaks in.
    assert "firstName" not in s
    assert "email" not in s


def test_user_shown_as_sink_when_no_fks_out():
    s = render_app_map_skeleton(_sample_map())
    # User has fks_out == []; should render explicit "sink" marker so Smith
    # doesn't wonder if the FK list was truncated.
    assert "User" in s
    lines = [ln for ln in s.splitlines() if ln.strip().startswith("User")]
    assert lines, "User line missing"
    assert "sink" in lines[0].lower() or "no fks out" in lines[0].lower()


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #

def test_pages_section_lists_every_route():
    m = _sample_map()
    s = render_app_map_skeleton(m)
    for p in m["pages"]:
        assert p["route"] in s


def test_page_lines_show_archetype_and_workflow():
    s = render_app_map_skeleton(_sample_map())
    # The Add Candidate page should surface both the archetype and the
    # workflow — that's the whole reason for the map.
    assert "/candidates/new" in s
    assert "form" in s
    assert "create-candidate" in s


# --------------------------------------------------------------------------- #
# Workflows
# --------------------------------------------------------------------------- #

def test_workflows_section_names_kind_and_target():
    s = render_app_map_skeleton(_sample_map())
    assert "create-candidate" in s
    assert "Candidate" in s
    assert "ShortlistingWorkflow" in s
    assert "Application" in s


# --------------------------------------------------------------------------- #
# Size budget
# --------------------------------------------------------------------------- #

def test_skeleton_under_4kb_for_realistic_app():
    """Real app-map for bpxr6hsv (7 entities, 18 pages, 15 workflows) must
    fit under ~4 KB — the whole point is 'cheap enough to inject every turn'.
    """
    from pathlib import Path
    src = Path("/Users/m/Work/code/poc/design2ui-forge-v3/output/bpxr6hsv")
    if not src.exists():
        return  # skip in CI without fixture
    m = build_app_map(str(src))
    s = render_app_map_skeleton(m)
    # Budget: ~4 KB is the design target; leave a little headroom for
    # apps that add a few features (refine-added Recruiters etc).
    assert len(s) < 5120, f"skeleton too fat: {len(s)} bytes"


# --------------------------------------------------------------------------- #
# Empty degrades cleanly
# --------------------------------------------------------------------------- #

def test_empty_map_renders_without_crashing():
    s = render_app_map_skeleton({"intent": "", "entities": {}, "pages": [], "workflows": {}})
    assert "# APP MAP" in s
    # Explicit "not known yet" markers rather than blank sections, so Smith
    # doesn't hallucinate structure that isn't there.
    assert "no entities" in s.lower() or "(none)" in s.lower()
