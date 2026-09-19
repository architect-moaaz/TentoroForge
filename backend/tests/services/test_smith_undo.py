"""Undo: the change goes back, the history keeps both, and it can be undone.

`revert_last_patch` reverses the last git commit and a Blueprint application's
repo has no commits, so on these projects there was no working undo at all —
every other change asked a nervous person to type into a machine they could
not back out of. The material was already there: §91 versions the document and
`commit` writes the pre-change state before every change.
"""

from __future__ import annotations

import pytest

from services.blueprint.ids import page_key
from services.blueprint.service import BlueprintService
from services.smith import revert as rv
from services.smith.section_change import SectionChangeError


@pytest.fixture()
def svc(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="Roster", domain="health")
    s.doc["data"] = {"entities": [{"id": "ENTITY-001", "name": "Nurse", "table": "nurses",
                                   "fields": [{"name": "id", "type": "uuid", "primaryKey": True},
                                              {"name": "fullName", "type": "string"}]}]}
    s.save()
    return s


def _change(svc, what: str, mutate) -> None:
    before = svc.snapshot()
    mutate(svc)
    svc.validate()
    svc.commit(user_request=what, smith_interpretation=what, before=before)


def test_the_last_change_goes_back_and_the_undo_is_recorded(svc):
    _change(svc, "add Nurse.phone",
            lambda s: s.doc["data"]["entities"][0]["fields"].append({"name": "phone", "type": "string"}))
    assert [f["name"] for f in svc.doc["data"]["entities"][0]["fields"]] == ["id", "fullName", "phone"]

    out = rv.revert(svc)
    fresh = BlueprintService.load(output_dir=str(svc.output_dir))
    assert [f["name"] for f in fresh.doc["data"]["entities"][0]["fields"]] == ["id", "fullName"]
    assert out["undone"] == "add Nurse.phone"
    # APPEND-ONLY: the change and its reversal both survive.
    asks = [h["userRequest"] for h in fresh.doc["changeHistory"]]
    assert asks[-2:] == ["add Nurse.phone", "undo: add Nurse.phone"]
    assert "Undone: **add Nurse.phone**" in rv.summary_of(out)


def test_said_twice_it_goes_back_two_changes(svc):
    _change(svc, "add Nurse.phone",
            lambda s: s.doc["data"]["entities"][0]["fields"].append({"name": "phone", "type": "string"}))
    _change(svc, "add Nurse.email",
            lambda s: s.doc["data"]["entities"][0]["fields"].append({"name": "email", "type": "string"}))

    rv.revert(svc)
    assert [f["name"] for f in svc.doc["data"]["entities"][0]["fields"]] == ["id", "fullName", "phone"]
    # The second undo steps PAST its own entry — it does not toggle back.
    second = rv.revert(svc)
    assert second["undone"] == "add Nurse.phone"
    assert [f["name"] for f in svc.doc["data"]["entities"][0]["fields"]] == ["id", "fullName"]


def test_an_undo_can_itself_be_undone(svc):
    _change(svc, "add Nurse.phone",
            lambda s: s.doc["data"]["entities"][0]["fields"].append({"name": "phone", "type": "string"}))
    rv.revert(svc)
    # "undo the undo" is asked for as a change, and the change it reverses is
    # the undo — whose own pre-state had the field.
    _change(svc, "put the phone back",
            lambda s: s.doc["data"]["entities"][0]["fields"].append({"name": "phone", "type": "string"}))
    assert rv.what_would_be_undone(svc.doc) == "put the phone back"


def test_the_next_undo_is_named_so_the_reply_can_offer_it(svc):
    _change(svc, "add Nurse.phone",
            lambda s: s.doc["data"]["entities"][0]["fields"].append({"name": "phone", "type": "string"}))
    _change(svc, "call the app Roster Plus",
            lambda s: s.doc.setdefault("product", {}).update({"objectives": ["x"]}))
    out = rv.revert(svc)
    assert out["next"] == "add Nurse.phone"
    assert "Say `undo` again to also reverse **add Nurse.phone**" in rv.summary_of(out)


def test_nothing_to_undo_is_said_plainly(svc):
    with pytest.raises(SectionChangeError, match="nothing to undo"):
        rv.revert(svc)
    assert rv.undoable(svc.doc) is None and rv.what_would_be_undone(svc.doc) == ""


def test_a_change_whose_before_state_was_not_kept_is_refused_not_guessed(svc):
    _change(svc, "add Nurse.phone",
            lambda s: s.doc["data"]["entities"][0]["fields"].append({"name": "phone", "type": "string"}))
    entry = rv.undoable(svc.doc)
    svc.version_path(int(entry["version"]) - 1).unlink()
    with pytest.raises(SectionChangeError, match="the state before it was not kept"):
        rv.revert(svc)
    # And nothing moved.
    assert [f["name"] for f in svc.doc["data"]["entities"][0]["fields"]][-1] == "phone"


def test_the_tool_entry_reports_a_refusal_rather_than_raising(tmp_path):
    out = rv.run(str(tmp_path))
    assert out["applied"] is False and "no Blueprint yet" in out["reason"]


def test_the_turn_undoes_and_says_what_it_undid(svc, monkeypatch):
    from services.smith_session import SmithSession

    _change(svc, "add Nurse.phone",
            lambda s: s.doc["data"]["entities"][0]["fields"].append({"name": "phone", "type": "string"}))
    session = SmithSession(project_id="p1", output_dir=str(svc.output_dir),
                           guards_fn=lambda *a, **kw: [],
                           understand_ask_fn=lambda m, ctx, **kw: {"verb": "revert"},
                           iteration_move_fn=lambda *a, **kw: None)
    result = session.run_iteration(user_message="undo that")
    assert result.status == "resolved"
    assert "Undone: **add Nurse.phone**" in result.answer
    assert [f["name"] for f in BlueprintService.load(output_dir=str(svc.output_dir))
            .doc["data"]["entities"][0]["fields"]] == ["id", "fullName"]


# ------------------------------------------------- the tool the agent can see

def test_the_undo_the_catalog_advertises_is_the_one_that_works(svc):
    """`services.smith.revert` was wired into the chat verb and into a handler
    named `revert` — which NO catalog entry advertised, so the agent could
    never choose it. The only undo it was offered was `revert_last_patch`,
    which reverses a git commit, and a Blueprint project's repo has none. So
    on exactly the applications this undo was written for, "undo that" was
    answered with a git error.
    """
    from services import smith_tools

    _change(svc, "add Nurse.phone",
            lambda s: s.doc["data"]["entities"][0]["fields"].append(
                {"name": "phone", "type": "string"}))

    out = smith_tools.READONLY_HANDLERS["revert_last_patch"](str(svc.output_dir), {})
    assert out["ok"] is True, out
    assert out["undone"] == "add Nurse.phone"
    assert [f["name"] for f in BlueprintService.load(output_dir=str(svc.output_dir))
            .doc["data"]["entities"][0]["fields"]] == ["id", "fullName"]


def test_both_names_are_one_handler(tmp_path, monkeypatch):
    """`revert` is the name `understand_ask`'s verb list teaches; the catalog
    says `revert_last_patch`. Two undos that could disagree about what "the
    last change" is would be the worst possible thing to have two of."""
    from services import smith_tools

    reached: list[str] = []
    monkeypatch.setattr(smith_tools, "_smith_revert_last_patch",
                        lambda out, args: reached.append(out) or {"ok": True})

    for name in ("revert", "revert_last_patch"):
        smith_tools.READONLY_HANDLERS[name](str(tmp_path), {})
    assert reached == [str(tmp_path), str(tmp_path)]


def test_the_catalog_no_longer_describes_a_mechanism_that_is_half_true(svc):
    """The entry said "reverse the most recent commit", which is what happens
    on a legacy project and not on a Blueprint one. A description that teaches
    the wrong mental model is how the working undo went unused."""
    from services import smith_tools

    entry = next(t for t in smith_tools.TOOL_CATALOG
                 if t["name"] == "revert_last_patch")
    assert "UNDO THE LAST CHANGE" in entry["desc"]
    assert "undo that" in entry["desc"]
    # And it names the other name, so the model is not left guessing whether
    # the verb it was taught reaches a tool.
    assert "`revert`" in entry["desc"]


def test_a_legacy_project_still_goes_to_git(tmp_path, monkeypatch):
    """The branch is on what the project KEEPS, not on a preference. A
    directory with no `.forge/blueprint/current.json` has its history in git
    and must keep using it."""
    from services import smith_tools

    seen: list[str] = []
    monkeypatch.setattr("services.patch_history.revert_last_patch",
                        lambda out: seen.append(out) or {"ok": True, "summary": "git"})

    out = smith_tools.READONLY_HANDLERS["revert_last_patch"](str(tmp_path), {})
    assert seen == [str(tmp_path)]
    assert out["summary"] == "git"


def test_a_blueprint_project_with_nothing_to_undo_says_so(svc):
    """Not a git error about a repo with no commits — the real reason."""
    from services import smith_tools

    out = smith_tools.READONLY_HANDLERS["revert"](str(svc.output_dir), {})
    assert out["ok"] is False
    assert "nothing to undo" in out["error"]
    assert out["summary"] == out["error"]


def test_the_alias_is_not_in_the_scoped_subsets():
    """A scoping subset is also what the CATALOG is filtered to, so it may
    only name tools the catalog carries. `revert` is dispatchable but not
    advertised: scoped, the model is shown `revert_last_patch` and calls it;
    the alias is for the unscoped turn, where there is no guard to get past.
    """
    from services.intent_classifier import TOOL_SUBSETS, TOOL_TAGS
    from services.smith_tools import TOOL_CATALOG

    advertised = {t["name"] for t in TOOL_CATALOG}
    assert "revert_last_patch" in TOOL_SUBSETS["undo"]
    assert "revert" not in TOOL_SUBSETS["undo"]
    assert "revert" not in TOOL_TAGS
    assert set(TOOL_SUBSETS["undo"]) <= advertised


def test_an_undo_writes_a_coded_page_back_too(tmp_path, monkeypatch):
    """036farqu: undoing a rewrite restored the page's code in the Blueprint,
    but the app kept serving the newer view.tsx — the re-projection never
    wrote React pages or their SDK."""
    from services.smith import reproject
    from services.blueprint import app_sdk, ui_engineer

    calls = []
    monkeypatch.setattr(ui_engineer, "ensure_sdk", lambda doc, root: calls.append("sdk"))
    monkeypatch.setattr(app_sdk, "project_code_pages", lambda doc, root: calls.append("pages") or ["src/app/x/view.tsx"])
    svc = type("S", (), {"doc": {"pageCode": []}})()
    assert reproject._code_pages(svc, str(tmp_path))["files"] == ["src/app/x/view.tsx"]
    assert calls == ["sdk", "pages"], "the SDK first, then the pages that compile against it"
