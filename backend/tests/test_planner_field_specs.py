# backend/tests/test_planner_field_specs.py
"""A1: the planner authors a per-field form spec (`fields`) carrying only JUDGMENT the
registry can't derive (semanticType/enum/required/label/order) — MERGED over the
registry-derived default. The CONTROL TYPE is never authored by the planner; it is
always DERIVED by the shared `resolve_control` authority, so a planner `control` key is
ignored.

THE BACKSTOP IS GONE, AND THAT IS THE POINT. This used to say "omitted columns are
backfilled from the registry", and `build_form_page` used to do it. The backstop let
another entity's columns into a form whenever the caller passed a wider editable set —
auth columns (email/password/isActive) turned up on a rent-payment form. So the plan is
authoritative for the FIELD SET now: a page's `fields` emits exactly those fields, and a
spec naming a column the entity does not have is dropped. Nothing is appended."""

from services.deterministic_pages import build_form_page
from agents.planner import _sanitize_page_fields

_COLS = {
    "id": {"type": "uuid", "primaryKey": True},
    "name": {"type": "varchar(255)", "nullable": False},
    "amount": {"type": "integer", "nullable": False},
    "status": {"type": "varchar", "nullable": True},
    "notes": {"type": "text", "nullable": True},
}


def _fields_of(page):
    """All form-field nodes (name/label/type) in document order."""
    out = []
    stack = [page["root"]]
    while stack:
        cur = stack.pop(0)
        if isinstance(cur, dict):
            if isinstance(cur.get("props"), dict) and cur["props"].get("name"):
                out.append(cur)
            stack[:0] = [c for c in cur.get("children", []) if isinstance(c, (dict, list))]
        elif isinstance(cur, list):
            stack[:0] = list(cur)
    return out


def _by_name(page):
    return {n["props"]["name"]: n for n in _fields_of(page)}


# --- merge + precedence + backstop -----------------------------------------

def test_field_specs_merge_over_registry_with_backstop():
    specs = [
        {"name": "amount", "semanticType": "currency"},
        {"name": "status", "enum": ["Open", "Closed"]},   # enum → Select (control derived)
        {"name": "name", "label": "Full Name", "order": 1},
    ]
    page = build_form_page("Deal", _COLS, "/deals/new", None, op="create",
                           entities={}, field_specs=specs)
    byname = _by_name(page)

    # amount → MoneyInput: the amount and its currency together, not a bare
    # number with a `$` stuck on the front.
    amt = byname["amount"]
    assert amt["type"] == "MoneyInput"

    # status → Select with the planner's literal options.
    status = byname["status"]
    assert status["type"] == "Select"
    assert [o["value"] for o in status["props"]["options"]] == ["Open", "Closed"]

    # name → label override + ordered first.
    assert byname["name"]["props"]["label"] == "Full Name"
    assert _fields_of(page)[0]["props"]["name"] == "name"

    # `notes` is a real column and is NOT here: the plan did not name it, and
    # the plan is the field set. Backfilling it is the bleed this replaced.
    assert "notes" not in byname


def test_field_spec_for_nonexistent_column_is_dropped():
    specs = [{"name": "foo", "control": "Input"}]
    page = build_form_page("Deal", _COLS, "/deals/new", None, op="create",
                           entities={}, field_specs=specs)
    names = set(_by_name(page))
    assert "foo" not in names                     # never invented
    # AND NOTHING IS PUT IN ITS PLACE. A plan that names one column this
    # entity does not have gets a form with no inputs — the honest reading of
    # "the plan is the field set", and worth knowing: a single typo in
    # `page.fields` costs the whole form, not just that field.
    assert names == set()


def test_a_real_column_beside_a_bogus_one_still_builds():
    """The drop is per-spec, not per-page: the bad name goes, the good one
    stays. Without this the test above could pass on a form builder that gave
    up entirely on the first unknown column."""
    specs = [{"name": "foo"}, {"name": "amount"}]
    page = build_form_page("Deal", _COLS, "/deals/new", None, op="create",
                           entities={}, field_specs=specs)
    assert set(_by_name(page)) == {"amount"}


def test_planner_control_is_ignored_control_is_derived():
    # The control type is DERIVED, never taken from the spec. A planner `control` key
    # (here a wrong Select on a plain varchar) is IGNORED → the column renders as the
    # registry-derived Input, proving the planner can't force a wrong control.
    specs = [{"name": "name", "control": "Select"}]
    page = build_form_page("Deal", _COLS, "/deals/new", None, op="create",
                           entities={}, field_specs=specs)
    node = _by_name(page)["name"]
    assert node["type"] == "Input"           # derived from the varchar column, not "Select"
    assert "options" not in node["props"]     # no phantom Select options


def test_planner_control_cannot_override_semantic_derivation():
    # Even a "correct-looking" control is ignored: amount is currency (semanticType),
    # so it derives a MoneyInput regardless of the bogus control the planner sent.
    specs = [{"name": "amount", "semanticType": "currency", "control": "Input"}]
    page = build_form_page("Deal", _COLS, "/deals/new", None, op="create",
                           entities={}, field_specs=specs)
    node = _by_name(page)["amount"]
    assert node["type"] == "MoneyInput"


def test_no_field_specs_is_identical_to_today():
    plain = build_form_page("Deal", _COLS, "/deals/new", None, op="create", entities={})
    none = build_form_page("Deal", _COLS, "/deals/new", None, op="create",
                           entities={}, field_specs=None)
    assert plain == none


def test_required_override_from_spec():
    # status is nullable in the registry; planner marks it required.
    specs = [{"name": "status", "required": True}]
    page = build_form_page("Deal", _COLS, "/deals/new", None, op="create",
                           entities={}, field_specs=specs)
    assert _by_name(page)["status"]["props"].get("validators", {}).get("required") is True


# --- _sanitize_page_fields --------------------------------------------------

def test_sanitize_page_fields_keeps_wellformed_drops_malformed():
    plan = {"pages": [{
        "route": "/deals/new",
        "fields": [
            {"name": "amount", "semanticType": "currency", "order": 2},
            {"name": "status", "control": "Select", "enum": ["Open", "Closed", 3]},
            {"name": "name", "label": "Full Name", "required": True, "order": 1},
            {"name": "bad", "control": "Slider", "semanticType": "bogus", "order": True},
            {"name": "   "},          # blank name → dropped
            {"control": "Input"},     # no name → dropped
            "not-a-dict",             # not a dict → dropped
        ],
    }]}
    out = _sanitize_page_fields(plan)
    fields = out["pages"][0]["fields"]
    by = {f["name"]: f for f in fields}

    assert set(by) == {"amount", "status", "name", "bad"}   # 3 malformed dropped

    assert by["amount"] == {"name": "amount", "semanticType": "currency", "order": 2}
    # `control` is DROPPED (control is derived downstream, never authored); enum coerced
    # to strings, non-stringable kept as str.
    assert "control" not in by["status"]
    assert by["status"] == {"name": "status", "enum": ["Open", "Closed", "3"]}
    assert by["name"] == {"name": "name", "label": "Full Name", "required": True, "order": 1}
    # invalid control/semanticType/order(bool) stripped, but the valid `name` keeps it.
    assert by["bad"] == {"name": "bad"}


def test_sanitize_page_fields_no_pages_is_noop():
    assert _sanitize_page_fields({}) == {}
    assert _sanitize_page_fields({"pages": "x"}) == {"pages": "x"}
