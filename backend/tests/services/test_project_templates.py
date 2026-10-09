"""Templates made from an organisation's own applications.

A template is the application's definition, taken whole and kept per
organisation. Used "exactly", it becomes a new project's definition and the
build authors nothing; used "like it, but different", it is reference evidence
for a new definition. These tests hold each of those promises to the files on
disk, with a real Blueprint (the ATS fleet fixture) — no model is called.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from services import project_templates as templates
from services.blueprint import documents as documents_mod
from services.blueprint.service import BlueprintService
from services.smith import gates

FIXTURE = Path(__file__).resolve().parents[2] / "fleet" / "blueprints" / "ats-live.json"
ORG = "11111111-1111-1111-1111-111111111111"
OTHER_ORG = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def output_base(tmp_path, monkeypatch):
    import services.project_service as project_service
    monkeypatch.setattr(project_service, "OUTPUT_BASE", tmp_path)
    return tmp_path


def _project(base: Path, short_id: str, *, defined: bool = True) -> Path:
    out = base / short_id
    (out / ".forge" / "blueprint").mkdir(parents=True)
    if defined:
        doc = json.loads(FIXTURE.read_text())
        (out / ".forge" / "blueprint" / "current.json").write_text(json.dumps(doc))
        (out / ".forge" / "ids.json").write_text(json.dumps({"page:jobs": "p_1"}))
        (out / "brand").mkdir()
        (out / "brand" / "logo.svg").write_text("<svg/>")
    return out


@pytest.fixture
def source(output_base):
    return _project(output_base, "src00001")


@pytest.fixture
def saved(source):
    return templates.save(output_dir=source, org_id=ORG, created_by="u1",
                          created_by_name="Areeb", source_project_id="p1", name="Hiring desk")


# --------------------------------------------------------------------------- #
# Taking a template
# --------------------------------------------------------------------------- #

def test_a_snapshot_drops_what_belongs_to_one_deployment_and_still_loads():
    doc = json.loads(FIXTURE.read_text())
    snap = templates.snapshot(doc)
    for section in templates.PER_PROJECT_SECTIONS:
        assert section not in snap
    assert snap["version"] == 1
    assert snap["pages"] == doc["pages"] and snap["data"] == doc["data"]
    assert "changeHistory" in doc, "the source is never touched"


def test_saving_keeps_the_definition_ids_and_brand_beside_its_meta(saved, output_base):
    root = output_base / "_templates" / saved["id"]
    assert sorted(p.name for p in root.iterdir()) == ["blueprint.json", "brand", "ids.json",
                                                      "meta.json"]
    assert (root / "brand" / "logo.svg").read_text() == "<svg/>"
    assert saved["name"] == "Hiring desk" and saved["org_id"] == ORG
    s = saved["summary"]
    assert s["counts"]["pages"] >= len(s["pages"]) > 0
    assert s["counts"]["requirements"] > 0


def test_a_template_needs_a_definition_to_be_taken_from(output_base):
    empty = _project(output_base, "empty001", defined=False)
    with pytest.raises(templates.TemplateError, match="no definition"):
        templates.save(output_dir=empty, org_id=ORG)
    assert not (output_base / "_templates").exists() or not any((output_base / "_templates").iterdir())


def test_an_unnamed_template_is_named_after_its_application(source):
    meta = templates.save(output_dir=source, org_id=ORG)
    assert meta["name"].endswith(" template")


def test_a_failed_save_leaves_nothing_behind(source, output_base, monkeypatch):
    def boom(_doc):
        raise RuntimeError("disk")
    monkeypatch.setattr(templates, "summary", boom)
    with pytest.raises(RuntimeError):
        templates.save(output_dir=source, org_id=ORG)
    root = output_base / "_templates"
    assert not root.exists() or not any(root.iterdir())


# --------------------------------------------------------------------------- #
# Finding, renaming, deleting — per organisation, ids checked
# --------------------------------------------------------------------------- #

def test_listing_is_per_organisation_newest_first(source, monkeypatch):
    stamps = iter(["2026-01-01T00:00:00", "2026-01-01T00:00:00",
                   "2026-02-01T00:00:00", "2026-02-01T00:00:00",
                   "2026-03-01T00:00:00", "2026-03-01T00:00:00"])
    monkeypatch.setattr(templates, "_now", lambda: next(stamps))
    a = templates.save(output_dir=source, org_id=ORG, name="A")
    b = templates.save(output_dir=source, org_id=ORG, name="B")
    templates.save(output_dir=source, org_id=OTHER_ORG, name="Theirs")
    assert [m["id"] for m in templates.list_for_org(ORG)] == [b["id"], a["id"]]
    assert [m["name"] for m in templates.list_for_org(OTHER_ORG)] == ["Theirs"]


@pytest.mark.parametrize("bad", ["../src00001", "..", "x" * 32, "", "A" * 32, "/etc/passwd"])
def test_an_id_that_is_not_one_names_no_path(output_base, bad):
    assert templates.get(bad) is None
    with pytest.raises(templates.TemplateError):
        templates.stage(bad, output_base / "p")


def test_rename_and_delete(saved, output_base):
    meta = templates.update(saved["id"], name="  Recruiting  ", description="For agencies")
    assert meta["name"] == "Recruiting" and meta["description"] == "For agencies"
    with pytest.raises(templates.TemplateError):
        templates.update(saved["id"], name="   ")
    assert templates.delete(saved["id"]) is True
    assert templates.get(saved["id"]) is None
    assert templates.delete(saved["id"]) is False


# --------------------------------------------------------------------------- #
# Using it exactly
# --------------------------------------------------------------------------- #

@pytest.fixture
def staged(saved, output_base):
    out = _project(output_base, "new00001", defined=False)
    templates.stage(saved["id"], out)
    return out


def test_staging_waits_for_smith(staged, saved):
    src = templates.pending(staged)
    assert src["template_id"] == saved["id"] and src["status"] == templates.PENDING
    assert not (staged / ".forge" / "blueprint" / "current.json").exists()


def test_exact_makes_the_template_this_projects_definition_at_the_build_review(staged):
    out = templates.use_exact(staged, app_name="Acme Hiring")
    doc = BlueprintService.load(output_dir=staged).doc
    tdoc = json.loads(FIXTURE.read_text())
    assert doc["application"]["id"] == "new00001"
    assert doc["application"]["name"] == "Acme Hiring"
    assert doc["pages"] == tdoc["pages"] and doc["workflows"] == tdoc["workflows"]
    assert doc["state"] == "PLAN_REVIEW"
    assert gates.current(doc, staged) == gates.PRODUCT_MODEL
    assert json.loads((staged / ".forge" / "ids.json").read_text()) == {"page:jobs": "p_1"}
    assert (staged / "brand" / "logo.svg").is_file()
    assert templates.pending(staged) is None
    assert templates.exact_build_pending(staged)
    assert out["summary"]["counts"]["pages"] == len(tdoc["pages"])


def test_exact_never_replaces_a_definition(staged):
    templates.use_exact(staged)
    templates._mark(staged, status=templates.PENDING)  # even if asked twice
    with pytest.raises(templates.TemplateError, match="already has a definition"):
        templates.use_exact(staged)


def test_an_exact_copy_carries_the_sources_direct_edits_and_only_the_live_ones(output_base):
    src = _project(output_base, "edited01")
    (src / ".forge" / "patches.json").write_text(json.dumps([
        {"id": "a", "status": "active", "kind": "app", "path": "src/x.ts", "find": "1",
         "replace": "2"},
        {"id": "b", "status": "retired", "kind": "app", "path": "src/y.ts", "find": "1",
         "replace": "2"}]))
    meta = templates.save(output_dir=src, org_id=ORG)
    new = _project(output_base, "edited02", defined=False)
    templates.stage(meta["id"], new)
    templates.use_exact(new)
    from services.smith.file_edit import load_patches
    assert [p["id"] for p in load_patches(new)] == ["a"]


def test_the_exact_build_is_marked_once_built(staged):
    templates.use_exact(staged)
    assert templates.exact_build_pending(staged)
    templates.mark_built(staged)
    assert not templates.exact_build_pending(staged)


def test_what_the_template_holds_is_not_authored_again(staged):
    """`completed_nodes` is what keeps an exact copy from re-authoring: every
    agent whose sections came with the template is done; only what the source
    never got to (here, the fixture's uncoded pages) is left."""
    from services.blueprint.orchestrator import DAG, completed_nodes
    templates.use_exact(staged)
    doc = BlueprintService.load(output_dir=staged).doc
    done = completed_nodes(doc)
    left = {k for k, n in DAG.items() if n.kind == "agent"} - done
    assert {"requirements", "data_model", "page_contracts", "workflows"} <= done
    assert "page_code" in left


# --------------------------------------------------------------------------- #
# Something like it, but different
# --------------------------------------------------------------------------- #

def test_adapt_writes_a_new_definition_from_the_changes_with_the_template_as_reference(staged):
    tdoc = json.loads(FIXTURE.read_text())
    prepared = templates.prepare_adapt(staged, app_name="Clinic", changes="For a dental clinic's "
                                       "patient intake instead of hiring")
    doc = BlueprintService.load(output_dir=staged).doc
    assert not templates.is_defined(doc), "the definition is the agents' to write"
    assert doc["designSystem"] == tdoc["designSystem"], "the look is kept"
    assert "dental clinic" in prepared["brief"]
    text = prepared["document"]["text"]
    assert text.startswith(documents_mod.TEMPLATE_MARK)
    assert tdoc["pages"][0]["route"] in text
    src = templates.source_of(staged)
    assert src["mode"] == templates.MODE_ADAPT and templates.pending(staged) is None
    assert not templates.exact_build_pending(staged)


def test_adapt_with_a_new_look_carries_no_design(staged):
    templates.prepare_adapt(staged, changes="A gym membership app", keep_look=False)
    doc = BlueprintService.load(output_dir=staged).doc
    assert doc.get("designSystem") != json.loads(FIXTURE.read_text())["designSystem"]
    assert not (staged / "brand").exists()


def test_adapt_needs_to_know_what_is_different(staged):
    with pytest.raises(templates.TemplateError, match="different"):
        templates.prepare_adapt(staged, changes="  ")
    assert templates.pending(staged), "nothing used up by a refusal"


def test_the_reference_reaches_the_model_design_agents_and_no_other_document_does(tmp_path):
    documents_mod.store(tmp_path, ["# Reference application: Hiring\n\nPurpose: hire\n",
                                   "Our leave policy: 20 days a year."])
    assert "Reference application" in documents_mod.addendum(tmp_path, "data_model")
    assert "leave policy" not in documents_mod.addendum(tmp_path, "data_model")
    assert documents_mod.addendum(tmp_path, "theme") == ""


# --------------------------------------------------------------------------- #
# Smith: asks, then uses it the way the person said
# --------------------------------------------------------------------------- #

def _ctx(out: Path, message: str = ""):
    from services.smith4.verbs import Ctx
    return Ctx(output_dir=str(out), project_id="p2", message=message, ask=message,
               app_name="Acme Hiring")


def test_smith_sees_the_template_and_is_told_to_ask(staged):
    from services.smith4 import context
    page = context.opening("p2", str(staged), "hi")
    assert "Hiring desk" in page
    assert "The exact same app" in page and "Something like it, but different" in page
    assert "use_template" in page


def test_smith_never_picks_the_way_for_the_person(staged):
    from services.smith4 import definition
    out = definition.use_template(_ctx(staged), {"mode": "whatever"})
    assert not out["applied"] and "exact same app" in out["finding"]
    assert templates.pending(staged)


def test_smith_uses_it_exactly_once(staged):
    from services.smith4 import definition
    out = definition.use_template(_ctx(staged), {"mode": "exact"})
    assert out["applied"] and not out["finding"]
    assert "Build app" in out["said"]
    again = definition.use_template(_ctx(staged), {"mode": "exact"})
    assert not again["applied"] and "already used" in again["finding"]


def test_without_a_template_smith_defines_from_what_was_said(output_base):
    from services.smith4 import definition
    out = definition.use_template(_ctx(_project(output_base, "plain001", defined=False)),
                                  {"mode": "exact"})
    assert not out["applied"] and "define_application" in out["finding"]


def test_adapt_through_smith_defines_with_the_reference_stored(staged, monkeypatch):
    from services.smith4 import definition
    seen = {}

    def fake_define(ctx, args):
        seen.update(args)
        return {"applied": True, "said": "defined", "finding": "", "touched": [], "version": 1}

    monkeypatch.setattr(definition, "define_application", fake_define)
    out = definition.use_template(_ctx(staged, "the same but for a law firm"), {"mode": "adapt"})
    assert out["applied"] and "law firm" in seen["brief"]
    assert "Reference application" in documents_mod.addendum(staged, "page_contracts")


def test_save_as_template_is_a_verb_smith_can_route():
    from services.smith.verbs import REQUIRED_BY_VERB
    from services.smith4.verbs import PERFORM
    assert "save_as_template" in REQUIRED_BY_VERB and "save_as_template" in PERFORM


def test_the_save_verb_takes_the_template_for_the_projects_organisation(source, monkeypatch):
    from services.smith4 import verbs
    monkeypatch.setattr(templates, "project_facts", lambda _pid: {
        "org_id": ORG, "owner_id": "u1", "name": "ATS", "owner_name": "Areeb"})
    ctx = verbs.Ctx(output_dir=str(source), project_id="p1", message="save as template",
                    ask="save as template")
    outcome = verbs.save_as_template(ctx, {"new_value": "Hiring v2"})
    assert outcome.status == "resolved" and "Hiring v2" in outcome.said
    assert [m["name"] for m in templates.list_for_org(ORG)] == ["Hiring v2"]


def test_an_exact_copy_of_a_template_saved_at_the_requirements_review_is_authored_onward(
        output_base):
    src = _project(output_base, "reqonly1")
    doc = json.loads(FIXTURE.read_text())
    doc["pages"], doc["data"]["entities"], doc["state"] = [], [], "BLUEPRINT_REVIEW"
    (src / ".forge" / "blueprint" / "current.json").write_text(json.dumps(doc))
    meta = templates.save(output_dir=src, org_id=ORG)
    new = _project(output_base, "reqcopy1", defined=False)
    templates.stage(meta["id"], new)
    out = templates.use_exact(new)
    copied = BlueprintService.load(output_dir=new).doc
    assert out["complete"] is False and copied["state"] == "BLUEPRINT_REVIEW"
    assert gates.current(copied, new) == gates.REQUIREMENTS
    assert not templates.exact_build_pending(new), "the rest must be authored, not skipped"
