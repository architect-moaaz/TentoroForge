"""Does an app need geofencing, and which zones: read from the brief (services/blueprint/geofence_plan.py).

What matters: the words "geofence" and "when the driver is within 300 m" make a plan; "live tracking" alone does NOT (a dot on
a map needs no zones); zones get coordinates only when the brief gives them; nothing ever finishes a job, takes payment or marks
someone present from a crossing; the plan reaches the blueprint (and the blueprint stays valid) and the built app."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from services.blueprint import geofence_plan as gp
from services.blueprint.service import BlueprintService

BACKEND = Path(__file__).resolve().parents[2]
RUNTIME = BACKEND / "templates" / "runtime"

DELIVERY = ("Food delivery app. Customers order from restaurants and drivers deliver the order. "
            "Alert the customer when the driver is within 300 m. Admin sees live tracking.")
TRACK_ONLY = "A live tracking app: customers see the driver on a map. Drivers share GPS."
RECIPES = "A recipe app where users save recipes, and when the user logs in they see their favourites."
GIVEN = "Field staff app. Auto clock-in when a nurse arrives at the site. Zone: Main Hospital - circle 200 m at 12.9716, 77.5946"


def test_a_brief_that_names_zones_or_a_distance_needs_geofencing():
    for brief in (DELIVERY, "Add a geofence around our depot; notify the manager when a truck leaves.", GIVEN):
        assert gp.analyse(brief).needed, brief


def test_following_a_dot_on_a_map_is_not_geofencing():
    for brief in (TRACK_ONLY, RECIPES, ""):
        plan = gp.analyse(brief)
        assert not plan.needed and plan.why_not and not plan.zones and not plan.rules, brief


@pytest.mark.parametrize("brief,scenario", [
    (DELIVERY, "delivery"),
    ("Taxi app. Notify the passenger when the driver arrives at the pickup point. Passengers book rides and trips.", "ride"),
    ("Fleet of trucks. Alert when a vehicle leaves the depot or enters the warehouse.", "fleet"),
    ("Nurses clock in when they arrive on site; attendance and shifts are tracked automatically on the field.", "attendance"),
])
def test_the_scenario_is_the_one_the_words_fit(brief, scenario):
    assert gp.analyse(brief).scenario == scenario


def test_the_plan_says_why():
    assert gp.analyse(DELIVERY).evidence


def test_a_zone_has_coordinates_only_when_the_brief_gave_them():
    plan = gp.analyse(GIVEN)
    given = [z for z in plan.zones if not z.needsDrawing]
    assert [(z.name, z.radiusM, z.lat, z.lng) for z in given] == [("Main Hospital", 200.0, 12.9716, 77.5946)]
    assert all(z.lat is None and z.lng is None for z in plan.zones if z.needsDrawing)
    assert any(z.needsDrawing for z in plan.zones), "a place the brief did not locate is left to be drawn, never guessed"


def test_units_and_impossible_places():
    km = gp.analyse("Add a geofence. Zone: Campus - 2 km at 10.5, 20.5 ").zones
    assert any(z.name == "Campus" and z.radiusM == 2000 for z in km)
    nowhere = gp.analyse("geofence. Zone: Moon - 100 m at 120.5, 20.5")
    assert not any(z.name == "Moon" for z in nowhere.zones)


def test_no_rule_finishes_a_job_takes_payment_or_marks_someone_present():
    """A crossing is where a phone SAYS it is. Rules only tell people or put a named event on the bus; none may name an action
    the runtime treats as sensitive (those would be held for ever, i.e. be dead rules)."""
    sensitive = re.compile(r"(paid|payment|charge|refund|payout|settle|deliver|complet|finish|fulfil|close|attend|present|clock|check(?:ed)?[-_. ]?(?:in|out)|sign[-_. ]?off|approve)", re.I)
    for name in gp._TEMPLATES:
        for _z, _ev, action, _note in gp._TEMPLATES[name]["rules"]:
            if action["kind"] == "emit_event":
                assert not sensitive.search(action["event"]), (name, action["event"])


def test_a_rule_is_bound_to_a_zone_of_the_plan_never_loose():
    for name, tpl in gp._TEMPLATES.items():
        zones = {z[0] for z in tpl["zones"]}
        assert all(r[0] in zones for r in tpl["rules"]), name
    plan = gp.analyse(DELIVERY)
    zones = {z.name.lower() for z in plan.zones}
    assert plan.rules and all(r["zone"] and r["zone"].lower() in zones for r in plan.rules)


def test_every_rule_event_is_one_the_runtime_accepts():
    ok = {"geofence.entered", "geofence.exited", "geofence.dwell", "geofence.approaching"}
    for tpl in gp._TEMPLATES.values():
        for _z, ev, action, _n in tpl["rules"]:
            assert ev in ok
            assert action["kind"] in ("emit_event", "notify")
            if action["kind"] == "notify":
                assert action.get("title") and action.get("role")


def test_the_plan_is_kept_read_back_and_forgotten_when_there_is_none(tmp_path):
    assert gp.read(tmp_path) is None
    gp.write(tmp_path, gp.analyse(DELIVERY))
    got = gp.read(tmp_path)
    assert got and got["scenario"] == "delivery"
    gp.write(tmp_path, gp.analyse(RECIPES))
    assert gp.read(tmp_path) is None, "a plan that says not needed is no plan"


def test_the_blueprint_takes_the_section_and_stays_valid(tmp_path):
    gp.write(tmp_path, gp.analyse(GIVEN))
    svc = BlueprintService.create(output_dir=tmp_path, app_id="a1", name="Care", domain="health", description="x")
    sec = svc.doc.get("geofencing")
    assert sec and sec["enabled"] and sec["scenario"] == "attendance"
    assert any(z["name"] == "Main Hospital" and z["lat"] == 12.9716 for z in sec["zones"])
    svc.validate()


def test_an_app_without_zones_has_no_section(tmp_path):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="a2", name="Recipes", domain="food", description="x")
    assert "geofencing" not in svc.doc
    svc.validate()


def test_a_bad_section_is_refused_by_the_contract(tmp_path):
    svc = BlueprintService.create(output_dir=tmp_path, app_id="a3", name="Recipes", domain="food", description="x")
    svc.doc["geofencing"] = {"zones": [{"name": "x", "radiusM": -5}]}
    with pytest.raises(Exception):
        svc.validate()
    svc.doc["geofencing"] = {"rules": [{"onEvent": "geofence.sneezed", "action": {}}]}
    with pytest.raises(Exception):
        svc.validate()


def test_the_question_names_what_was_understood_and_what_is_left():
    said = gp.question(gp.analyse(GIVEN))
    assert "Main Hospital" in said and "draw" in said.lower() and "check" in said.lower()
    assert gp.question(gp.analyse(RECIPES)) == ""


def test_the_definition_keeps_the_plan_and_never_fails_on_it(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from services.smith4 import definition

    ctx = SimpleNamespace(out=str(tmp_path))
    definition.note_geofencing(ctx, DELIVERY)
    assert gp.read(tmp_path)
    monkeypatch.setattr(gp, "analyse", lambda _b: (_ for _ in ()).throw(RuntimeError("boom")))
    definition.note_geofencing(ctx, "anything")  # does not raise


def test_the_built_app_gets_the_plan_and_its_seed_applies_it():
    src = (BACKEND / "services" / "runtime_injector.py").read_text(encoding="utf-8")
    assert "geofence-plan.json" in src and '"contracts" / "geofence-plan.json"' in src
    seed = (RUNTIME / "seed.ts").read_text(encoding="utf-8")
    assert "seedGeofencePlan" in seed and "await seedGeofencePlan();" in seed and "../lib/geofence/plan" in seed
    # before the skip gates: a reused database still gets its zones
    assert seed.index("await seedGeofencePlan();") < seed.index('FORGE_KEEP_DB_STATE === "1" && !forceSeed')
    assert (RUNTIME / "geofence" / "plan.ts").exists()


def test_a_zone_carries_the_settings_its_rules_need():
    """"The driver is near" needs an approach distance and "stayed a long time" a stay time: a zone made without them would
    leave those rules for ever silent."""
    delivery = {z.name: z.rules for z in gp.analyse(DELIVERY).zones}
    assert delivery["Customer drop-off"].get("approachM", 0) > 0
    fleet = {z.name: z.rules for z in gp.analyse("Add a geofence around our depot; notify the manager when a truck leaves or stays.").zones}
    assert fleet["Depot"].get("dwellSec", 0) > 0
    given = gp.analyse("Delivery app. Drivers deliver orders. Alert the customer when the driver is within 300 m. Zone: Customer drop-off - circle 150 m at 12.9, 77.6").zones
    assert next(z for z in given if z.name == "Customer drop-off" and not z.needsDrawing).rules.get("approachM")
    for tpl in gp._TEMPLATES.values():          # a rule that needs a setting has it
        for zone in tpl["zones"]:
            names = {r[1] for r in tpl["rules"] if r[0] == zone[0]}
            if "geofence.approaching" in names:
                assert zone[3].get("approachM")
            if "geofence.dwell" in names:
                assert zone[3].get("dwellSec")


def test_what_is_kept_about_a_person_is_limited_and_can_be_erased():
    """Retention, rounding of positions and erasing one record ship with every app, and only a zone manager may erase."""
    store = (RUNTIME / "geofence" / "store.ts").read_text(encoding="utf-8")
    assert "purgeOld" in store and "eraseEntity" in store and "coarsen(e.lat" in store
    route = (RUNTIME / "api-geofence-events" / "route.ts").read_text(encoding="utf-8")
    assert "export async function DELETE" in route
    delete = route[route.index("export async function DELETE"):]
    assert delete.index("me.manager") < delete.index("eraseEntity("), "the manager check comes before the erase"
    index = (RUNTIME / "geofence" / "index.ts").read_text(encoding="utf-8")
    assert "purgeOld" in index and "purgeDue" in index
    assert (RUNTIME / "geofence" / "privacy.ts").exists()


def test_the_plan_kept_beside_the_project_reaches_the_built_app(tmp_path):
    """The build runs the injector on the APP folder while the plan is kept one level up; reading it from the wrong place meant no
    real build ever carried its zones (found building an app end to end, 2026-11-17)."""
    from services.runtime_injector import inject_runtime

    app = tmp_path / "app"
    app.mkdir()
    gp.write(tmp_path, gp.analyse(DELIVERY))
    inject_runtime(str(app), app_name="T", domain="food", project_id="p1")
    got = app / "contracts" / "geofence-plan.json"
    assert got.is_file() and '"delivery"' in got.read_text(encoding="utf-8")


def test_an_app_with_no_plan_gets_no_plan_file(tmp_path):
    from services.runtime_injector import inject_runtime

    app = tmp_path / "app"
    app.mkdir()
    inject_runtime(str(app), app_name="T", domain="food", project_id="p2")
    assert not (app / "contracts" / "geofence-plan.json").exists()


def test_erasing_and_purging_also_clear_the_copy_on_the_event_bus():
    """Every crossing is announced on the bus with its exact position; a purge or an erase that left that copy kept the trail."""
    store = (RUNTIME / "geofence" / "store.ts").read_text(encoding="utf-8")
    assert "dropBusCopies" in store and "DELETE FROM forge_events WHERE type LIKE 'geofence.%'" in store
    erase = store[store.index("export async function eraseEntity"):]
    assert "dropBusCopies(sql`entity_id = ${entityId}`)" in erase
    purge = store[store.index("export async function purgeOld"):store.index("async function dropBusCopies")]
    assert "dropBusCopies(" in purge


def test_a_zone_never_widens_to_everyone_because_one_entry_was_misspelt():
    route = (RUNTIME / "api-geofence-zones" / "route.ts").read_text(encoding="utf-8")
    assert route.count("assign.length !== b.assign.length") == 2, "both adding and changing a zone refuse a dropped entry"
