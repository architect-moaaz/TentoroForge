"""Resume must not skip a fan-out that finished for some subjects and not others.

`completed_nodes` decides what a resumed run may leave alone, and its docstring
is right about why: re-running an agent node appends to its section rather than
replacing it, so a redo costs the same tokens again and leaves the Blueprint
larger each time. "The produced section already has content" is the correct
test for a node that writes once.

It is the wrong test for a node that writes once PER SUBJECT, and wrong by
exactly the failures. `page_layouts` fanned out over pages. A real run ended with
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

# `entity_fields` fans out over entities: `data_model` names them, one call per
# entity details it, and an entity is detailed once it carries fields. (This
# was written against `page_layouts`, which no longer calls a model.)


def _doc(entity_ids, detailed_ids, deprecated=()):
    doc = {
        "data": {"entities": [
            {"id": eid, "status": "DEPRECATED" if eid in deprecated else "ACTIVE",
             **({"fields": [{"name": "name"}]} if eid in detailed_ids else {})}
            for eid in entity_ids]},
    }
    # Every other produced section present, so only the fan-out decides.
    # `produces` paths are dotted (`data.entities`), and `_section` resolves
    # them by walking — so they must be NESTED here, not written as a literal
    # key with a dot in it.
    for node in DAG.values():
        if node.kind != "agent":
            continue
        for path in node.produces:
            if path == "data.entities":
                continue
            cursor = doc
            *parents, leaf = path.split(".")
            for part in parents:
                cursor = cursor.setdefault(part, {})
            cursor.setdefault(leaf, [{"id": "x"}])
    return doc


def test_a_partially_detailed_fan_out_is_not_complete():
    """The bug: 4 of 15 subjects authored read as done."""
    doc = _doc([f"ENTITY-{i:03}" for i in range(1, 16)],
               ["ENTITY-003", "ENTITY-004", "ENTITY-005", "ENTITY-015"])
    assert "entity_fields" not in completed_nodes(doc)


def test_a_fully_detailed_fan_out_is_complete():
    ids = [f"ENTITY-{i:03}" for i in range(1, 16)]
    assert "entity_fields" in completed_nodes(_doc(ids, ids))


def test_a_deprecated_subject_is_not_owed():
    """Rows, not counts: the retired entity has no fields and the node is done."""
    doc = _doc(["ENTITY-001", "ENTITY-002"], ["ENTITY-001"], deprecated=("ENTITY-002",))
    assert "entity_fields" in completed_nodes(doc)


def test_single_write_nodes_keep_the_section_rule():
    """`security` writes once; content in its section is completion."""
    doc = _doc(["ENTITY-001"], ["ENTITY-001"])
    assert "security" in completed_nodes(doc)
