"""Second tester round on tasks 3-6: a shift is never mistaken for an ordinary
request, branches and other records' columns are left alone, stock photos go
only where the record's own picture belongs, a failing photo service is not
hammered, and a choice is named for what it is."""
import json

import pytest

from services.blueprint.service import BlueprintService
from services.smith import big_shift, field_change as fc, field_dependents as fd


# --- 5.1 a shift is not an ordinary request -------------------------------------------------------

ORDINARY = [
    "Only show orders from the UK", "Make the Dubai office address field required",
    "The user is based in Singapore, show their city", "make the buttons blue and india flag",
    "Add a field for the UK postcode", "show prices in USD on the product page", "Convert the price to a number field",
    "Total in INR column should be bold", "Show the Dubai store first in the list", "Add Dubai as a store location",
    "Only allow Indian phone numbers", "Make it Dubai centric and add a refund button", "Filter products by the UK market",
    "The currency column should be wider", "Translate the label to Arabic", "Make the header blue",
    "Hide the Singapore branch from the list", "Our customers are mostly in India, so add a phone field",
    "Make the Japan option the default in the country dropdown", "Use euro symbols in the export file",
]


@pytest.mark.parametrize("ask", ORDINARY)
def test_ordinary_requests_mentioning_places_or_currencies_are_not_shifts(ask):
    assert big_shift.detect(ask) is None, ask


@pytest.mark.parametrize("ask,market,cur", [("make it dubai-centric", "the UAE (Dubai)", "AED"), ("make the app Dubai centric", "the UAE (Dubai)", "AED"),
                                            ("go dubai", "the UAE (Dubai)", "AED"), ("ksa centric", "Saudi Arabia", "SAR"),
                                            ("localise the app for India", "India", "INR"), ("switch the market to Qatar", "Qatar", "QAR"),
                                            ("build this for Dubai", "the UAE (Dubai)", "AED"), ("change the currency to AED", None, "AED")])
def test_a_real_shift_is_still_recognised(ask, market, cur):
    s = big_shift.detect(ask)
    assert s and s["currency"] == cur and (market is None or s["market"] == market)


def test_a_turn_with_a_shift_phrase_and_another_change_runs_the_other_change(tmp_path, monkeypatch):
    import sys
    from services.smith4 import handle as handle_fn
    H = sys.modules["services.smith4.handle"]
    monkeypatch.setattr(H, "_in_step", lambda o, v, r: r, raising=False)
    seen = []
    handle_fn(project_id="p", output_dir=str(tmp_path), message="Only show orders from the UK",
              choose=lambda ask, page, obs, hist: (seen.append(ask), {"tool": "answer", "args": {"text": "ok"}})[1], move=None)
    assert seen and "orders from the UK" in seen[0]                                   # the real request reached the loop


# --- 5.2 / 5.3 ------------------------------------------------------------------------------------

def test_prose_next_to_a_comparison_is_swapped_and_the_comparison_is_not(tmp_path):
    s = BlueprintService.create(output_dir=tmp_path, app_id="t", name="X", domain="d")
    s.doc["requirements"] = [{"id": "REQ-001", "description": "Total over Rs. 500 needs approval; currency == 'INR' otherwise.",
                              "status": "APPROVED", "evidence": [{"message": "x", "type": "conversation"}]}]
    s.save()
    big_shift.apply_currency(s, "INR", "AED", output_dir=tmp_path)
    assert s.doc["requirements"][0]["description"] == "Total over AED 500 needs approval; currency == 'INR' otherwise."


def test_a_language_shift_and_a_currencyless_market_say_nothing_was_changed():
    lang = big_shift.proposal(big_shift.detect("make the app in Hindi") or {"kind": "language", "language": "hindi", "touches": ["x"]})
    assert "I have changed nothing" in lang
    market = big_shift.proposal(big_shift.detect("make it dubai centric"), {"total": 0, "blueprint": {}, "from": "AED", "to": "AED"})
    assert "I have changed nothing" in market


# --- 6 -------------------------------------------------------------------------------------------

from tests.services.test_removing_a_field_takes_everything_that_reads_it import _ent, _wf, svc  # noqa: E402,F401


def _wfn(s, name):
    return next(w for w in s.doc["workflows"] if w["name"] == name)


def test_a_two_way_branch_is_never_made_always_true(svc):
    wf = _wfn(svc, "Edit Medicine")
    wf["steps"].insert(1, {"key": "br", "name": "Is morning?", "type": "condition", "next": ["upd", "end"],
                           "config": {"expression": "preferredTime == 'AM'", "branches": {"true": "a", "false": "b"}}})
    out = fc.remove_field(svc, "Medicine", "preferredTime")
    assert _wfn(svc, "Edit Medicine")["steps"][1]["config"]["expression"] == "preferredTime == 'AM'"
    assert any("decides between" in x and "Is morning?" not in x or "decides between" in x for x in out["left"])
    assert "Nothing still refers to it" not in fc.summary_of("remove_field", out)


def test_another_records_same_named_column_is_not_popped(svc):
    s = svc
    s.doc["data"]["entities"].append({"id": "ENTITY-002", "name": "Patient", "table": "patients", "fields": [
        {"name": "id", "type": "uuid", "primaryKey": True}, {"name": "preferredTime", "type": "string"}]})
    wf = _wfn(s, "Add Medicine")
    wf["steps"].insert(-1, {"key": "ins_patient", "name": "Insert patient", "type": "action", "entity": "ENTITY-002", "next": ["end"],
                            "config": {"actionType": "db_insert", "table": "patients", "values": {"preferredTime": "{{preferredTime}}"}}})
    fc.remove_field(s, "Medicine", "preferredTime")
    steps = {st["key"]: st for st in _wfn(s, "Add Medicine")["steps"]}
    assert steps["ins_patient"]["config"]["values"] == {"preferredTime": "{{preferredTime}}"}
    assert "preferredTime" not in steps["insert"]["config"]["values"]


def test_a_decisions_only_row_is_named_not_emptied(svc):
    wf = _wfn(svc, "Edit Medicine")
    wf["steps"].insert(1, {"key": "route", "name": "Route", "type": "decision", "next": ["upd"],
                           "config": {"rules": [{"when": "preferredTime == 'AM'", "then": "a"}]}})
    out = fc.remove_field(svc, "Medicine", "preferredTime")
    assert len(_wfn(svc, "Edit Medicine")["steps"][1]["config"]["rules"]) == 1
    assert any("decides between" in x for x in out["left"])


def test_a_bare_name_in_a_multi_record_workflow_lists_what_is_left(svc):
    s = svc
    s.doc["data"]["entities"].append({"id": "ENTITY-002", "name": "Patient", "table": "patients", "fields": [
        {"name": "id", "type": "uuid", "primaryKey": True}, {"name": "preferredTime", "type": "string"}]})
    wf = _wfn(s, "Add Medicine")
    wf["steps"].insert(-1, {"key": "chk_patient", "name": "Check patient", "type": "action", "entity": "ENTITY-002", "next": ["end"],
                            "config": {"actionType": "db_update", "table": "patients", "expression": "preferredTime != ''",
                                       "values": {"x": "1"}, "where": {"id": "{{id}}"}}})
    deps = fd.scan(s.doc, _ent(s), "preferredTime")
    notes = [d for d in deps if d["class"] == "note"]
    assert notes and "Check patient" in notes[0]["what"] and "another record" in notes[0]["what"]
    assert any(d["class"] == "manual" and "validate_input" in d["what"] for d in deps)     # an unplaceable bare read is named, not hidden
    assert fd.needs_confirmation(deps)
    lines = fd.describe(deps)
    assert any("Check patient" in l for l in lines)
    assert not any("Check patient" in x for x in fc.remove_field(s, "Medicine", "preferredTime")["left"])   # a note is not 'still refers'


# --- 3.1 / 3.2 -------------------------------------------------------------------------------------

def test_avatars_and_logos_do_not_get_the_rows_stock_photo():
    from services.seed_photos import is_photo_column
    for col in ("avatarUrl", "logo_url", "cover_url", "thumb", "profile_image", "bannerImage", "iconUrl", "favicon", "headshot",
                "badge_image", "flagUrl", "qr_image"):
        assert not is_photo_column(col, ""), col
    for col in ("imageUrl", "photo", "pictureUrl", "thumbnailUrl", "image"):
        assert is_photo_column(col, ""), col


class Boom(Exception):
    def __init__(self, status=None, headers=None):
        super().__init__("boom")
        if status:
            self.response = type("R", (), {"status_code": status, "headers": headers or {}})()


def _plan(tmp_path, n=10):
    (tmp_path / "contracts").mkdir(exist_ok=True)
    rows = [{"id": str(i), "name": f"Dish {chr(97 + i)}", "imageUrl": ""} for i in range(n)]
    (tmp_path / "contracts/seed-plan.json").write_text(json.dumps({"tables": [{"name": "MenuItem", "seed_data": rows}]}))
    return tmp_path / "contracts/seed-plan.json"


def test_three_failures_in_a_row_stop_the_searching(tmp_path):
    from services.seed_photos import fill_seed_photos
    _plan(tmp_path)
    calls = []

    def get(path, params):
        calls.append(1)
        raise Boom()
    r = fill_seed_photos(tmp_path, get)
    assert len(calls) == 3 and r["empty"] == 10 and "3 times in a row" in r["why"]


def test_a_429_stops_at_once_and_the_next_build_does_not_ask_again(tmp_path):
    from services.seed_photos import fill_seed_photos
    p = _plan(tmp_path)
    calls = []

    def get(path, params):
        calls.append(1)
        raise Boom(429, {"Retry-After": "120"})
    r = fill_seed_photos(tmp_path, get)
    assert len(calls) == 1 and "429" in r["why"]
    assert json.loads(p.read_text())["seed_photos_blocked_until"] > 0
    again = fill_seed_photos(tmp_path, get)
    assert len(calls) == 1 and "rate limited" in again["why"]


# --- 4.1 ------------------------------------------------------------------------------------------

def _app(tmp_path, labels, schema_cols=None):
    from services.choice_control_guard import ensure_choices_are_controls
    page = {"route": "/x", "root": {"type": "Stack", "children": [
        {"type": "Row", "children": [{"type": "Button", "props": {"label": l}} for l in labels]},
        {"type": "Form", "props": {"workflow": "F", "fields": [{"kind": "text", "name": "note", "label": "Note"}]}}]}}
    p = tmp_path / "src/schemas/x.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(page, indent=2))
    w = tmp_path / "workflows/f.json"
    w.parent.mkdir(parents=True)
    w.write_text(json.dumps({"id": "F", "name": "F", "inputs": [], "requiredInputs": [],
                             "definition": {"nodes": [{"data": {"config": {"actionType": "db_insert", "table": "things", "values": {}}}}]}}))
    if schema_cols is not None:
        s = tmp_path / "src/db/schema/things.ts"
        s.parent.mkdir(parents=True)
        s.write_text('export const things = pgTable("things", {\n  id: uuid("id").primaryKey(),\n'
                     + "".join(f'  {c}: text("{c}"),\n' for c in schema_cols) + "});\n")
    r = ensure_choices_are_controls(str(tmp_path))
    return r, json.loads(p.read_text()), json.loads(w.read_text())


@pytest.mark.parametrize("labels,name,label", [(("Monthly", "Yearly"), "billingPeriod", "Billing period"),
                                               (("Male", "Female", "Other"), "gender", "Gender"),
                                               (("Dine-in", "Delivery"), "orderType", "Dine-in or Delivery"),
                                               (("Online", "In person"), "meetingMode", "Meeting mode")])
def test_a_choice_is_named_and_labelled_for_what_it_is(tmp_path, labels, name, label):
    r, page, _w = _app(tmp_path, labels, schema_cols=[name])
    field = next(n for n in page["root"]["children"] if n["type"] == "Form")["props"]["fields"][0]
    assert (field["name"], field["label"]) == (name, label)


def test_with_no_schema_the_choice_is_not_written_into_the_workflow_values(tmp_path):
    r, page, wf = _app(tmp_path, ("Monthly", "Yearly"), schema_cols=None)
    cfg = wf["definition"]["nodes"][0]["data"]["config"]
    assert "billingPeriod" not in cfg["values"]                                          # never a column that may not exist
    assert any("could not be confirmed" in f.get("detail", "") for f in r["findings"])
