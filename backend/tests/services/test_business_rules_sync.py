"""Business rules have one record — the Blueprint — and every way in reaches it.

Found on a task board Kimi built (2026-10-14): five rules in the definition,
"No business rules yet" in the Business Rules tab, which wrote a table nothing
else read; the rules the build wrote ran nowhere. These hold the service the
tab uses (`services.business_rules`) to the files on disk: what it lists, what
it refuses and why, that a save is versioned and in the running app at once,
that an edit of a rule changed elsewhere is refused, that what the person asked
for is never lost, and that rules the tab saved to the old table are adopted.
No model is called.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import business_rules as br
from services.blueprint.service import BlueprintService

FIXTURE = Path(__file__).resolve().parents[2] / "fleet" / "blueprints" / "ats-live.json"


@pytest.fixture
def app(tmp_path) -> Path:
    out = tmp_path / "ats00001"
    (out / ".forge" / "blueprint").mkdir(parents=True)
    (out / "app").mkdir()
    doc = json.loads(FIXTURE.read_text())
    doc["application"]["id"] = "ats00001"
    (out / ".forge" / "blueprint" / "current.json").write_text(json.dumps(doc))
    return out


def _doc(out: Path) -> dict:
    return BlueprintService.load(output_dir=out).doc


def _app_rules(out: Path, rel: str = "rules") -> list[dict]:
    return json.loads((out / "app" / rel / "blueprint-rules.json").read_text())


ROLE = "ENTITY-002"   # Role: title, status, openingsCount, …

GOOD = {"name": "Openings must be positive", "kind": "condition_action", "entity": ROLE,
        "when": "openingsCount < 1", "then": [{"id": "act_1", "type": "show_error",
                                                "message": "A role needs at least one opening."}]}


# --------------------------------------------------------------------------- #
# Reading — every rule, as the person and Smith see it
# --------------------------------------------------------------------------- #

def test_the_tab_lists_every_rule_the_definition_holds(app):
    out = br.read(app)
    assert out["mode"] == "blueprint"
    assert len(out["rules"]) == len([r for r in _doc(app)["businessRules"] if r.get("status") != "DEPRECATED"])
    first = out["rules"][0]
    assert first["kind"] == "statement" and first["runs"] == "nowhere" and not first["enforced"]
    assert first["origin"] == "generated", "a rule with no origin was inferred by Forge"
    ent = next(e for e in out["catalogue"]["entities"] if e["id"] == ROLE)
    assert {"title", "status", "openingsCount"} <= {f["name"] for f in ent["fields"]}
    assert out["catalogue"]["workflows"][0]["id"].startswith("FLOW-")


def test_where_a_rule_runs_is_said_by_what_it_does():
    ca = {"kind": "condition_action", "entity": "E", "then": [{"type": "show_error", "message": "x"}]}
    assert br.where_it_runs({**ca, "scope": "form"}) == "everywhere", "a refusal is enforced on save"
    assert br.where_it_runs({**ca, "then": [{"type": "set_visibility", "field": "f"}], "scope": "form"}) == "form"
    assert br.where_it_runs({**ca, "scope": "server"}) == "save"
    assert br.where_it_runs({**ca, "enabled": False}) == "nowhere"
    assert br.where_it_runs({"kind": "statement"}) == "nowhere"
    assert br.where_it_runs({"kind": "prerequisite"}) == "before"
    assert br.where_it_runs({"kind": "condition_action", "then": []}) == "nowhere", "no entity, nothing runs"


# --------------------------------------------------------------------------- #
# Saving — checked as the build checks, versioned, in the app at once
# --------------------------------------------------------------------------- #

def test_a_rule_made_in_the_tab_is_versioned_and_in_force_at_once(app):
    out = br.create(app, GOOD, actor="Areeb")
    rid = out["rule"]["rule"]["id"]
    stored = next(r for r in _doc(app)["businessRules"] if r["id"] == rid)
    assert stored["origin"] == "editor" and stored["enabled"] is True and stored["scope"] == "entity"
    assert "id" not in stored["then"][0], "the editor's action ids are the editor's"
    assert stored["appliesTo"][0] == ROLE
    assert stored["statement"], "a rule made without a sentence is given one"
    history = _doc(app)["changeHistory"][-1]
    assert "Business Rules tab: add “Openings must be positive” (by Areeb)" == history["userRequest"]
    assert history["affectedArtifacts"] == [rid]
    for rel in ("rules", "src/rules"):
        row = next(r for r in _app_rules(app, rel) if r["id"] == rid)
        assert row["model_name"] == "Role" and row["config"]["whenFeel"] == "openingsCount < 1"
    assert out["rule"]["runs"] == "everywhere"


@pytest.mark.parametrize("bad, said", [
    ({**GOOD, "when": "nosuch > 3"}, "reads nosuch, which Role does not have"),
    ({**GOOD, "then": [{"type": "set_field", "value": "1"}]}, "needs a field"),
    ({**GOOD, "then": [{"type": "show_error"}]}, "needs the message"),
    ({**GOOD, "then": []}, "at least one thing the rule does"),
    ({**GOOD, "entity": "ENTITY-999"}, "Choose the record"),
    ({**GOOD, "name": ""}, "Give the rule a name"),
    ({**GOOD, "when": "openingsCount == 0"}, "openingsCount"),
    ({**GOOD, "then": [{"type": "trigger_workflow", "workflow": "FLOW-999"}]}, "not a workflow"),
    ({**GOOD, "then": [{"type": "show_error", "message": "x", "field": "nosuch"}]}, "does not have"),
])
def test_a_rule_the_app_could_not_run_is_refused_with_the_reason(app, bad, said):
    with pytest.raises(br.RuleError) as exc:
        br.create(app, bad)
    assert any(said in p for p in exc.value.problems), exc.value.problems
    assert exc.value.status == 400
    assert not (app / "app" / "rules" / "blueprint-rules.json").exists(), "nothing written"


def test_the_same_rule_twice_is_refused(app):
    br.create(app, {**GOOD, "statement": "A role needs an opening."})
    with pytest.raises(br.RuleError) as exc:
        br.create(app, {**GOOD, "name": "Again", "statement": "a role needs an opening."})
    assert exc.value.status == 409 and "already says that" in str(exc.value)


def test_an_edit_keeps_the_rule_and_its_id_and_refuses_a_stale_copy(app):
    made = br.create(app, GOOD)["rule"]
    rid, rev = made["rule"]["id"], made["revision"]
    edited = br.update(app, rid, {"when": "openingsCount < 2", "statement": "Two openings at least."},
                       expected=rev)["rule"]
    assert edited["rule"]["id"] == rid and edited["rule"]["when"] == "openingsCount < 2"
    assert edited["rule"]["origin"] == "editor"
    assert next(r for r in _app_rules(app) if r["id"] == rid)["config"]["whenFeel"] == "openingsCount < 2"
    with pytest.raises(br.RuleError) as exc:
        br.update(app, rid, {"name": "Lost edit"}, expected=rev)
    assert exc.value.status == 409
    assert next(r for r in _doc(app)["businessRules"] if r["id"] == rid)["name"] == GOOD["name"]
    # A reworded rule is the same rule: its id follows the new words.
    from services.blueprint.ids import IdAllocator, prose_key
    with IdAllocator.session(output_dir=app) as alloc:
        assert alloc.lookup(prose_key("RULE", "Two openings at least.")) == rid


def test_an_edit_that_changes_nothing_writes_nothing(app):
    made = br.create(app, GOOD)["rule"]
    v = _doc(app)["version"]
    out = br.update(app, made["rule"]["id"], {"name": GOOD["name"]}, expected=made["revision"])
    assert out.get("unchanged") and _doc(app)["version"] == v


def test_switched_off_a_rule_is_kept_but_out_of_the_app(app):
    made = br.create(app, GOOD)["rule"]
    rid = made["rule"]["id"]
    off = br.set_enabled(app, rid, False, expected=made["revision"])["rule"]
    assert off["runs"] == "nowhere" and off["enabled"] is False
    assert all(r["id"] != rid for r in _app_rules(app))
    assert any(v["rule"]["id"] == rid for v in br.read(app)["rules"]), "still listed"
    on = br.set_enabled(app, rid, True, expected=off["revision"])["rule"]
    assert on["runs"] == "everywhere" and any(r["id"] == rid for r in _app_rules(app))


def test_removed_a_rule_is_retired_in_history_and_gone_from_the_app(app):
    made = br.create(app, GOOD)["rule"]
    rid = made["rule"]["id"]
    br.remove(app, rid, expected=made["revision"])
    stored = next(r for r in _doc(app)["businessRules"] if r["id"] == rid)
    assert stored["status"] == "DEPRECATED" and stored["syncNote"] == "removed in the Business Rules tab"
    assert all(v["rule"]["id"] != rid for v in br.read(app)["rules"])
    assert all(r["id"] != rid for r in _app_rules(app))
    with pytest.raises(br.RuleError) as exc:
        br.remove(app, rid, expected=None)
    assert exc.value.status == 404


def test_a_written_down_rule_made_enforceable_keeps_its_id(app):
    view = br.read(app)["rules"][0]
    rid = view["rule"]["id"]
    out = br.update(app, rid, {**GOOD, "name": view["rule"]["name"]}, expected=view["revision"])["rule"]
    assert out["rule"]["id"] == rid and out["kind"] == "condition_action" and out["enforced"]
    assert out["rule"]["statement"] == view["rule"]["statement"], "its sentence is kept"
    assert any(r["id"] == rid for r in _app_rules(app))
    back = br.update(app, rid, {"kind": "statement"}, expected=out["revision"])["rule"]
    assert "when" not in back["rule"] and "then" not in back["rule"], "prose carries no effects"
    assert all(r["id"] != rid for r in _app_rules(app))


def test_a_decision_table_is_bound_to_its_record_and_runs(app):
    table = {"hitPolicy": "F",
             "inputs": [{"id": "in_1", "name": "openingsCount", "type": "number", "variableBinding": "openingsCount"}],
             "outputs": [{"id": "out_1", "name": "status", "type": "string"}],
             "rules": [{"id": "r1", "inputEntries": ["> 10"], "outputEntries": ['"hiring"']},
                       {"id": "r2", "inputEntries": ["-"], "outputEntries": ['"open"']}]}
    made = br.create(app, {"name": "Status by openings", "kind": "decision_table", "entity": ROLE,
                           "table": table})["rule"]
    assert made["runs"] == "everywhere"
    row = next(r for r in _app_rules(app) if r["id"] == made["rule"]["id"])
    assert row["rule_type"] == "decision_table" and row["model_name"] == "Role"
    assert row["config"]["table"]["rules"][0]["inputEntries"] == ["> 10"]
    with pytest.raises(br.RuleError) as exc:
        br.create(app, {"name": "Bad table", "kind": "decision_table", "entity": ROLE,
                        "table": {**table, "outputs": [{"name": "nosuch"}]}})
    assert any("not a field of Role" in p for p in exc.value.problems)


def test_a_prerequisite_is_only_switched_or_reworded_here(app):
    with pytest.raises(br.RuleError):
        br.create(app, {**GOOD, "kind": "prerequisite"})


def test_the_old_rules_tab_no_longer_lists_blueprint_rules():
    import inspect
    from routers import rules as old
    assert "rules_from_blueprint" not in inspect.getsource(old.list_rules)


# --------------------------------------------------------------------------- #
# Concurrency — a build and Smith never lose the person's change
# --------------------------------------------------------------------------- #

def test_a_rule_is_not_saved_while_a_build_writes_the_definition(app, monkeypatch):
    monkeypatch.setattr(br, "busy", lambda _out: "building")
    with pytest.raises(br.RuleError) as exc:
        br.create(app, GOOD)
    assert exc.value.status == 423 and "building" in str(exc.value)
    assert br.read.__module__  # reading is still allowed


def _ledger(out: Path, name: str, *, phase: str = "build", ended: bool = False) -> None:
    runs = out / ".forge" / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    lines = [{"event": "run:start", "phase": phase, "at": "2026-10-14T17:00:00Z", "runId": name},
             {"event": "node:start", "node": "x", "runId": name}]
    if ended:
        lines.append({"event": "run:end", "runId": name})
    (runs / f"{name}.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n")


@pytest.mark.parametrize("name,phase,said", [
    ("20261014-170000-aaaaaa", "build", "building"),
    ("20261014-170000-checks", "checking", "checking"),
    ("20261014-170000-bbbbbb-smith-turn", "", "smith"),
])
def test_what_is_changing_the_app_is_read_from_its_runs(app, name, phase, said):
    """A rule saved while a build, the checks after it, or a Smith turn has
    the definition open would be lost when that saves the whole of it."""
    assert br.busy(app) is None
    _ledger(app, name, phase=phase)
    assert br.busy(app) == said
    listed = br.read(app)
    assert listed["busy"] == said and listed["building"] is True, "the tab is read-only, and says why"
    _ledger(app, name, phase=phase, ended=True)
    assert br.busy(app) is None and br.read(app)["building"] is False


def test_a_run_that_went_quiet_does_not_lock_the_tab(app):
    """The laptop switched off mid-build: its ledger never ends."""
    import os, time as _t
    _ledger(app, "20261014-170000-cccccc")
    stale = _t.time() - 3600
    os.utime(app / ".forge" / "runs" / "20261014-170000-cccccc.jsonl", (stale, stale))
    assert br.busy(app) is None


def test_the_checks_after_a_build_refuse_with_their_own_reason(app, monkeypatch):
    monkeypatch.setattr(br, "busy", lambda _out: "checking")
    with pytest.raises(br.RuleError) as exc:
        br.create(app, GOOD)
    assert exc.value.status == 423 and "checking the app it just built" in str(exc.value)


def test_a_smith_turn_is_waited_for_then_the_rule_is_saved(app, monkeypatch):
    seen = iter(["smith", "smith", None])
    monkeypatch.setattr(br, "busy", lambda _out: next(seen, None))
    monkeypatch.setattr(br.time, "sleep", lambda _s: None)
    made = br.create(app, GOOD)
    assert made["rule"]["rule"]["id"]


def test_a_smith_turn_that_goes_on_is_said_not_raced(app, monkeypatch):
    monkeypatch.setattr(br, "busy", lambda _out: "smith")
    monkeypatch.setattr(br, "TAB_LOCK_WAIT", 0.01)
    with pytest.raises(br.RuleError) as exc:
        br.create(app, GOOD)
    assert exc.value.status == 423 and "Smith is working on this app" in str(exc.value)
    assert all(r.get("name") != GOOD["name"] for r in _doc(app)["businessRules"])


def test_the_tab_waits_for_smith_then_says_so(app):
    import threading, time
    held = threading.Event()
    release = threading.Event()

    def smith():
        with br.write_lock(app):
            held.set()
            release.wait(5)

    t = threading.Thread(target=smith)
    t.start()
    held.wait(5)
    start = time.monotonic()
    with pytest.raises(br.RuleError) as exc:
        with br.write_lock(app, timeout=0.5):
            pass
    assert exc.value.status == 423 and "Smith is changing" in str(exc.value)
    assert time.monotonic() - start < 2
    release.set()
    t.join()
    with br.write_lock(app, timeout=0.5):
        pass


# --------------------------------------------------------------------------- #
# What the person asked for is never lost
# --------------------------------------------------------------------------- #

def _uncited(doc: dict) -> list[dict]:
    """A requirement no rule cites — the fixture's are all cited, so one is added."""
    cited = {x for r in doc["businessRules"] for x in r.get("requirements") or []}
    free = [r for r in doc["requirements"] if r["id"] not in cited]
    if not free:
        fresh = {**doc["requirements"][0], "id": "REQ-900",
                 "description": "Roles with more than ten openings need a hiring manager's approval."}
        doc["requirements"].append(fresh)
        free = [fresh]
    return free


def test_a_stated_rule_the_build_did_not_cover_is_kept_and_listed(app):
    svc = BlueprintService.load(output_dir=app)
    req = _uncited(svc.doc)[0]
    req["owner"] = "businessRules"
    out = br.keep_stated_rules(svc)
    assert len(out["added"]) == 1
    rule = next(r for r in svc.doc["businessRules"] if r["id"] == out["added"][0])
    assert rule["origin"] == "brief" and rule["kind"] == "statement" and rule["requirements"] == [req["id"]]
    assert all(r.get("origin") for r in svc.doc["businessRules"]), "every rule says where it came from"
    again = br.keep_stated_rules(svc)
    assert again == {"added": [], "tagged": 0}, "idempotent"


def test_a_rule_citing_a_stated_requirement_is_from_the_request(app):
    svc = BlueprintService.load(output_dir=app)
    req = svc.doc["requirements"][1]
    req["owner"] = "businessRules"
    rule = svc.doc["businessRules"][0]
    rule.pop("origin", None)
    rule["requirements"] = [req["id"]]
    out = br.keep_stated_rules(svc)
    assert out["added"] == [] and rule["origin"] == "brief"


def test_before_the_build_the_tab_lists_what_was_asked_for(app):
    svc = BlueprintService.load(output_dir=app)
    req = _uncited(svc.doc)[0]
    req["owner"] = "businessRules"
    cited = svc.doc["requirements"][0]
    cited["owner"] = "businessRules"
    svc.save()
    planned = br.read(app)["planned"]
    assert [p["id"] for p in planned] == [req["id"]], "a stated rule already written is not 'planned'"


def test_a_rule_removed_takes_its_ask_with_it(app):
    """Removed in the tab, the rule came back at the next catch-up as a
    written-down rule "you asked for" (Task Board, 2026-10-14)."""
    svc = BlueprintService.load(output_dir=app)
    req = _uncited(svc.doc)[0]
    req["owner"] = "businessRules"
    svc.save()
    made = br.create(app, {**GOOD, "requirements": [req["id"]]})["rule"]
    rid = made["rule"]["id"]
    br.remove(app, rid, expected=made["revision"])
    svc = BlueprintService.load(output_dir=app)
    ask = next(r for r in svc.doc["requirements"] if r["id"] == req["id"])
    assert ask["status"] == "DEPRECATED" and rid in ask["syncNote"]
    assert br.keep_stated_rules(svc)["added"] == [], "not brought back"
    assert br.read(app)["planned"] == [], "not listed as still asked for"


def test_an_ask_another_rule_answers_is_kept(app):
    svc = BlueprintService.load(output_dir=app)
    req = _uncited(svc.doc)[0]
    req["owner"] = "businessRules"
    svc.save()
    a = br.create(app, {**GOOD, "requirements": [req["id"]]})["rule"]
    br.create(app, {**GOOD, "name": "Openings cap", "when": "openingsCount > 500",
                    "requirements": [req["id"]]})
    br.remove(app, a["rule"]["id"], expected=a["revision"])
    ask = next(r for r in _doc(app)["requirements"] if r["id"] == req["id"])
    assert ask["status"] != "DEPRECATED", "still answered by the other rule"


def test_a_written_down_rule_steps_aside_for_the_rule_that_enforces_it(app):
    svc = BlueprintService.load(output_dir=app)
    req = _uncited(svc.doc)[0]
    req["owner"] = "businessRules"
    kept = br.keep_stated_rules(svc)["added"][0]
    svc.save()
    br.create(app, {**GOOD, "requirements": [req["id"]]})
    svc = BlueprintService.load(output_dir=app)
    br.keep_stated_rules(svc)
    rule = next(r for r in svc.doc["businessRules"] if r["id"] == kept)
    assert rule["status"] == "DEPRECATED" and rule["syncNote"].startswith("enforced by RULE-")
    live = [r for r in svc.doc["businessRules"] if r.get("status") != "DEPRECATED"
            and req["id"] in (r.get("requirements") or [])]
    assert len(live) == 1 and live[0]["kind"] == "condition_action", "listed once, as enforced"


def test_the_same_ask_recorded_twice_is_one_written_down_rule(app):
    svc = BlueprintService.load(output_dir=app)
    a = _uncited(svc.doc)[0]
    b = {**a, "id": "REQ-901"}
    svc.doc["requirements"].append(b)
    for r in (a, b):
        r["owner"] = "businessRules"
    added = br.keep_stated_rules(svc)["added"]
    assert len(added) == 1
    rule = next(r for r in svc.doc["businessRules"] if r["id"] == added[0])
    assert sorted(rule["requirements"]) == sorted([a["id"], b["id"]])


def test_a_rule_made_again_after_it_was_removed_is_not_its_old_record(app):
    svc = BlueprintService.load(output_dir=app)
    req = _uncited(svc.doc)[0]
    svc.save()
    made = br.create(app, {**GOOD, "requirements": [req["id"]]})["rule"]
    off = br.set_enabled(app, made["rule"]["id"], False, expected=made["revision"])["rule"]
    br.remove(app, made["rule"]["id"], expected=off["revision"])
    again = br.create(app, GOOD)["rule"]
    assert again["rule"]["id"] == made["rule"]["id"]
    assert again["enabled"] and again["runs"] == "everywhere"
    assert "syncNote" not in again["rule"] and again["rule"]["requirements"] == []


def test_a_written_down_rule_made_enforceable_is_no_longer_marked_not_enforced(app):
    svc = BlueprintService.load(output_dir=app)
    req = _uncited(svc.doc)[0]
    req["owner"] = "businessRules"
    kept = br.keep_stated_rules(svc)["added"][0]
    svc.save()
    view = next(v for v in br.read(app)["rules"] if v["rule"]["id"] == kept)
    out = br.update(app, kept, {"kind": "condition_action", "entity": ROLE, "when": "openingsCount > 10",
                                "then": [{"type": "show_error", "message": "Ten at most."}]},
                    expected=view["revision"])["rule"]
    assert out["rule"]["id"] == kept and out["enforced"] and "syncNote" not in out["rule"]


def test_a_length_limit_reads_the_field_it_limits(app):
    assert br._condition_fields("string length(title) > 60") == {"title"}
    assert br._condition_fields('starts with(title, "A") and openingsCount > 1') == {"title", "openingsCount"}
    doc = _doc(app)
    assert br.check(doc, br.normalise({**GOOD, "when": "string length(title) > 60"}, doc)) == []


# --------------------------------------------------------------------------- #
# Rules the tab saved to the old table
# --------------------------------------------------------------------------- #

def test_rules_saved_to_the_old_table_are_adopted_once(app):
    rows = [
        {"id": "11111111-1111-1111-1111-111111111111", "name": "Old guard", "rule_type": "condition_action",
         "model_name": "roles", "is_active": True,
         "config": {"source": "manual", "whenFeel": "openingsCount > 50", "scope": "entity", "salience": 0,
                    "then": [{"id": "act_x", "type": "show_error", "message": "Too many openings."}],
                    "otherwise": []}},
        {"id": "22222222-2222-2222-2222-222222222222", "name": "Elsewhere", "rule_type": "condition_action",
         "model_name": "invoices", "is_active": True, "config": {"whenFeel": "true", "then": []}},
        {"id": "33333333-3333-3333-3333-333333333333", "name": "Validation", "rule_type": "validation",
         "model_name": "roles", "is_active": True, "config": {}},
    ]
    adopted = br.adopt(app, rows)
    assert adopted == ["11111111-1111-1111-1111-111111111111"], "only a rule of this app's records"
    rule = next(v for v in br.read(app)["rules"] if v["rule"]["name"] == "Old guard")
    assert rule["origin"] == "editor" and rule["enabled"] and rule["entityName"] == "Role"
    assert any(r["config"]["whenFeel"] == "openingsCount > 50" for r in _app_rules(app))
    assert br.adopt(app, rows[:1]) == ["11111111-1111-1111-1111-111111111111"], "a second pass finds it there"
    assert len([v for v in br.read(app)["rules"] if v["rule"]["name"] == "Old guard"]) == 1


def test_an_old_rule_that_no_longer_checks_is_adopted_switched_off(app):
    rows = [{"id": "44444444-4444-4444-4444-444444444444", "name": "Broken", "rule_type": "condition_action",
             "model_name": "Role", "is_active": True,
             "config": {"whenFeel": "nosuch > 1", "then": [{"type": "show_error", "message": "x"}]}}]
    assert br.adopt(app, rows)
    rule = next(v for v in br.read(app)["rules"] if v["rule"]["name"] == "Broken")
    assert rule["enabled"] is False and "switched off until fixed" in rule["rule"]["syncNote"]


# --------------------------------------------------------------------------- #
# The projection: what the running app reads
# --------------------------------------------------------------------------- #

def test_the_projection_leaves_out_what_is_off_or_retired_and_mirrors_for_serverless(app):
    from services.blueprint.projection import project_business_rules
    doc = _doc(app)
    doc["businessRules"] = [
        {"id": "RULE-901", "name": "on", "statement": "s1", "kind": "condition_action", "entity": ROLE,
         "when": "true", "then": [{"type": "show_error", "message": "m"}]},
        {"id": "RULE-902", "name": "off", "statement": "s2", "kind": "condition_action", "entity": ROLE,
         "when": "true", "then": [{"type": "show_error", "message": "m"}], "enabled": False},
        {"id": "RULE-903", "name": "gone", "statement": "s3", "kind": "condition_action", "entity": ROLE,
         "when": "true", "then": [{"type": "show_error", "message": "m"}], "status": "DEPRECATED"},
        {"id": "RULE-904", "name": "prose", "statement": "s4"},
    ]
    out = project_business_rules(doc, app / "app")
    assert out["rules"] == 1 and out["files"] == ["rules/blueprint-rules.json", "src/rules/blueprint-rules.json"]
    assert [r["id"] for r in _app_rules(app)] == ["RULE-901"] == [r["id"] for r in _app_rules(app, "src/rules")]


def test_the_contract_accepts_every_field_the_tab_writes(app):
    svc = BlueprintService.load(output_dir=app)
    svc.doc["businessRules"].append({
        "id": "RULE-950", "name": "t", "statement": "t", "kind": "decision_table", "entity": ROLE,
        "origin": "editor", "enabled": False,
        "table": {"hitPolicy": "F", "inputs": [{"name": "status", "type": "string"}],
                  "outputs": [{"name": "title", "type": "string"}],
                  "rules": [{"inputEntries": ["-"], "outputEntries": ['"x"']}]}})
    svc.validate()
    svc.doc["businessRules"][-1]["origin"] = "nobody"
    with pytest.raises(Exception):
        svc.validate()
