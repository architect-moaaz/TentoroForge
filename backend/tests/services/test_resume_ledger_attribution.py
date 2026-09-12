"""QA D-07: a build killed between two INDEPENDENT writers of one section must
resume correctly — the writer that had not run is re-run, not read as done
because the other writer had filled the shared section.

`requirements` and `figma_intelligence` both write `requirements` and neither
depends on the other; on resume, the run ledger is the authority on which
actually ran. The core pairs (data_model/entity_fields, ...) are unaffected —
the downstream node depends on the upstream one and carries an authored-check.
"""
import json

from services.blueprint.orchestrator import (
    DAG, completed_nodes, nodes_recorded_done, _ledger_gated_nodes,
)


def _doc(with_design=True):
    d = {"requirements": [{"id": "REQ-001"}]}
    if with_design:
        d["designSources"] = [{"id": "DS-1"}]
    return d


def test_only_the_independent_co_writers_are_ledger_gated():
    # Precisely requirements <-> figma_intelligence; NOT the dependency-ordered,
    # authored-checked core pairs.
    assert _ledger_gated_nodes(DAG) == {"requirements", "figma_intelligence"}


def test_no_confirmed_set_keeps_the_old_behaviour():
    done = completed_nodes(_doc(), confirmed=None)
    assert "requirements" in done and "figma_intelligence" in done


def test_the_writer_the_ledger_did_not_record_is_re_run():
    # figma_intelligence committed first (recorded), the run died before
    # requirements. Resume must re-run requirements, not skip it — the D-07 bug.
    done = completed_nodes(_doc(with_design=True), confirmed={"figma_intelligence"})
    assert "figma_intelligence" in done
    assert "requirements" not in done


def test_the_writer_the_ledger_recorded_is_done():
    done = completed_nodes(_doc(with_design=True), confirmed={"requirements"})
    assert "requirements" in done
    assert "figma_intelligence" not in done   # it had design work and did not run


def test_figma_with_no_design_sources_is_vacuously_done():
    # Nothing to author -> complete even though the ledger never recorded it.
    done = completed_nodes(_doc(with_design=False), confirmed={"requirements"})
    assert "figma_intelligence" in done


def test_a_primary_author_is_never_ledger_gated():
    # data_model shares data.entities with entity_fields, but entity_fields
    # DEPENDS on it + has an authored-check, so data_model is judged by its
    # section as before — a ledger set must not make a primary re-run.
    doc = {"data": {"entities": [{"id": "ENTITY-001", "name": "Offer",
                                  "fields": [{"name": "id"}]}]}}
    done = completed_nodes(doc, confirmed={"requirements"})
    assert "data_model" in done


def test_nodes_recorded_done_reads_the_ledger(tmp_path):
    from services.blueprint.run_ledger import LEDGER_DIR
    d = tmp_path / LEDGER_DIR
    d.mkdir(parents=True)
    (d / "run1.jsonl").write_text("\n".join(json.dumps(o) for o in [
        {"event": "run:start"},
        {"event": "node:done", "node": "requirements"},
        {"event": "node:start", "node": "data_model"},
        {"event": "node:done", "node": "data_model"},
    ]) + "\n")
    assert nodes_recorded_done(tmp_path) == {"requirements", "data_model"}
    assert nodes_recorded_done(tmp_path / "nope") == set()
