"""Resume must not skip a fan-out that finished for some subjects and not others.

`completed_nodes` decides what a resumed run may leave alone, and its docstring
is right about why: re-running an agent node appends to its section rather than
replacing it, so a redo costs the same tokens again and leaves the Blueprint
larger each time. "The produced section already has content" is the correct
test for a node that writes once.

It is the wrong test for a node that writes once PER SUBJECT, and wrong by
exactly the failures. `page_layouts` fans out over pages. A real run ended with
4 of 15 pages composed and 11 rejected; the next run read `pageLayouts` as
non-empty, planned itself without `page_layouts` at all — nine nodes, none of
them the one with eleven failures — and built `frontend` from a four-page
application. The failed pages were never retried. Resume-not-redo had become
resume-not-finish, and nothing said so: the run reported nine completed nodes.

THE ROWS ARE CHECKED, NOT COUNTED. A deprecated page leaves its layout behind,
so `len(pageLayouts) == len(pages)` can be true of an incomplete section and
false of a complete one. Each live subject must have a row naming it.

ONLY FAN-OUTS WHOSE ROWS NAME THEIR SUBJECT ARE JUDGED THIS WAY. A design
source's requirements carry `evidence`, not a source id, so `figma_intelligence`
keeps the section-level rule — the behaviour every run had before.
"""
from services.blueprint.orchestrator import DAG, completed_nodes


def _doc(page_ids, layout_page_ids, deprecated=()):
    doc = {
        "pages": [{"id": pid, "status": "DEPRECATED" if pid in deprecated else "ACTIVE"}
                  for pid in page_ids],
        "pageLayouts": [{"page": pid, "root": {"type": "Container"}}
                        for pid in layout_page_ids],
    }
    # Every other produced section present, so only the fan-out decides.
    # `produces` paths are dotted (`data.entities`), and `_section` resolves
    # them by walking — so they must be NESTED here, not written as a literal
    # key with a dot in it.
    for node in DAG.values():
        if node.kind != "agent":
            continue
        for path in node.produces:
            if path in ("pages", "pageLayouts"):
                continue
            cursor = doc
            *parents, leaf = path.split(".")
            for part in parents:
                cursor = cursor.setdefault(part, {})
            cursor.setdefault(leaf, [{"id": "x"}])
    return doc


def test_a_partially_composed_fan_out_is_not_complete():
    """The bug: 4 of 15 pages composed read as done."""
    doc = _doc([f"PAGE-{i:03}" for i in range(1, 16)],
               ["PAGE-003", "PAGE-004", "PAGE-005", "PAGE-015"])
    assert "page_layouts" not in completed_nodes(doc)


def test_a_fully_composed_fan_out_is_complete():
    ids = [f"PAGE-{i:03}" for i in range(1, 16)]
    assert "page_layouts" in completed_nodes(_doc(ids, ids))


def test_an_empty_section_is_still_not_complete():
    """The original rule still holds at the bottom: nothing written, nothing done."""
    assert "page_layouts" not in completed_nodes(_doc(["PAGE-001"], []))


def test_a_deprecated_page_does_not_need_a_layout():
    """Rows, not counts: the retired page has no layout and the node is done."""
    doc = _doc(["PAGE-001", "PAGE-002"], ["PAGE-001"], deprecated=("PAGE-002",))
    assert "page_layouts" in completed_nodes(doc)


def test_a_layout_for_a_page_that_no_longer_exists_does_not_count():
    """Rows, not counts, the other way: two layouts, one of them orphaned, and
    a live page still uncomposed."""
    doc = _doc(["PAGE-001", "PAGE-002"], ["PAGE-001", "PAGE-999"])
    assert "page_layouts" not in completed_nodes(doc)


def test_no_pages_at_all_means_nothing_is_owed():
    """A fan-out with no subjects completes without invoking anything, so an
    application with no pages yet must not be held open by this rule."""
    doc = _doc([], [])
    doc["pageLayouts"] = [{"page": "PAGE-000", "root": {}}]  # section non-empty
    assert "page_layouts" in completed_nodes(doc)


def test_single_write_nodes_keep_the_section_rule():
    """`data_model` writes once; content in its section is completion."""
    doc = _doc(["PAGE-001"], ["PAGE-001"])
    assert "data_model" in completed_nodes(doc)
