"""Table row-navigation guard: list tables open the row's detail overlay."""
import json

from services.table_row_nav_guard import guard_table_row_nav

def _subset(result: dict, expected: dict) -> dict:
    """Project a guard's return dict down to the keys the test asserts on.

    Whole-dict equality breaks every time a guard gains a counter (e.g.
    ``asserts_logged`` from the authority demotions) even though the
    behaviour under test is unchanged. Compare only what the test means.
    """
    return {k: result.get(k) for k in expected}



def _schema(rows="{{reservations}}", row_key="id", row_href=None):
    props = {"rows": rows, "rowKey": row_key}
    if row_href:
        props["rowHref"] = row_href
    return {"root": {"type": "Stack", "children": [{"type": "Table", "props": props}]}}


def _write(tmp, rel, obj):
    p = tmp / "src" / "schemas" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


def test_wires_rowhref_when_detail_route_exists(tmp_path):
    _write(tmp_path, "reservations.json", _schema())
    _write(tmp_path, "reservations/[id].json", {"root": {}})  # detail route exists
    res = guard_table_row_nav(str(tmp_path))
    assert _subset(res, {"wired": 1, "files": 1}) == {"wired": 1, "files": 1}
    out = json.loads((tmp_path / "src/schemas/reservations.json").read_text(encoding="utf-8"))
    assert out["root"]["children"][0]["props"]["rowHref"] == "/reservations/{{id}}"


def test_skips_when_no_detail_route(tmp_path):
    _write(tmp_path, "reservations.json", _schema())  # no [id].json
    assert _subset(guard_table_row_nav(str(tmp_path)), {"wired": 0, "files": 0}) == {"wired": 0, "files": 0}


def test_leaves_correct_existing_rowhref(tmp_path):
    # A rowHref that already targets a real detail route is left untouched.
    _write(tmp_path, "reservations.json", _schema(row_href="/reservations/{{id}}"))
    _write(tmp_path, "reservations/[id].json", {"root": {}})
    assert _subset(guard_table_row_nav(str(tmp_path)), {"wired": 0, "files": 0}) == {"wired": 0, "files": 0}
    out = json.loads((tmp_path / "src/schemas/reservations.json").read_text(encoding="utf-8"))
    assert out["root"]["children"][0]["props"]["rowHref"] == "/reservations/{{id}}"


def test_repoints_wrong_rowhref_to_data_entity(tmp_path):
    # overdue.json binds rows {{rentals}} but carries a page-slug rowHref
    # /overdue/{id} — there is no /overdue/[id] route, but /rentals/[id] exists,
    # so the guard repoints to the row's data entity (preserving the {id} brace).
    _write(tmp_path, "overdue.json", _schema(rows="{{rentals}}", row_href="/overdue/{id}"))
    _write(tmp_path, "rentals/[id].json", {"root": {}})
    res = guard_table_row_nav(str(tmp_path))
    assert _subset(res, {"wired": 1, "files": 1}) == {"wired": 1, "files": 1}
    out = json.loads((tmp_path / "src/schemas/overdue.json").read_text(encoding="utf-8"))
    assert out["root"]["children"][0]["props"]["rowHref"] == "/rentals/{id}"


def test_strips_wrong_rowhref_when_no_detail_route(tmp_path):
    # Same wrong rowHref but the data entity has no detail route either — strip it
    # so the rows render non-navigable rather than routing to a 404.
    _write(tmp_path, "overdue.json", _schema(rows="{{rentals}}", row_href="/overdue/{id}"))
    res = guard_table_row_nav(str(tmp_path))
    assert _subset(res, {"wired": 1, "files": 1}) == {"wired": 1, "files": 1}
    out = json.loads((tmp_path / "src/schemas/overdue.json").read_text(encoding="utf-8"))
    assert "rowHref" not in out["root"]["children"][0]["props"]


def test_does_not_wire_unrelated_entity_table(tmp_path):
    # A payments table on the reservations page must NOT point at /reservations/[id].
    _write(tmp_path, "reservations.json", _schema(rows="{{payments}}"))
    _write(tmp_path, "reservations/[id].json", {"root": {}})
    assert _subset(guard_table_row_nav(str(tmp_path)), {"wired": 0, "files": 0}) == {"wired": 0, "files": 0}


def test_wires_when_source_name_extends_route_slug(tmp_path):
    # Page /maintenance lists {{maintenanceOrders}} — route slug is a shorter stem
    # of the source name; the exact match missed it, leaving the drawer dead.
    _write(tmp_path, "maintenance.json", _schema(rows="{{maintenanceOrders}}"))
    _write(tmp_path, "maintenance/[id].json", {"root": {}})
    res = guard_table_row_nav(str(tmp_path))
    assert _subset(res, {"wired": 1, "files": 1}) == {"wired": 1, "files": 1}
    out = json.loads((tmp_path / "src/schemas/maintenance.json").read_text(encoding="utf-8"))
    assert out["root"]["children"][0]["props"]["rowHref"] == "/maintenance/{{id}}"


def test_singular_plural_match_and_rowkey(tmp_path):
    _write(tmp_path, "guests.json", _schema(rows="{{guest}}", row_key="guestId"))
    _write(tmp_path, "guests/[id].json", {"root": {}})
    guard_table_row_nav(str(tmp_path))
    out = json.loads((tmp_path / "src/schemas/guests.json").read_text(encoding="utf-8"))
    assert out["root"]["children"][0]["props"]["rowHref"] == "/guests/{{guestId}}"


def test_idempotent(tmp_path):
    _write(tmp_path, "reservations.json", _schema())
    _write(tmp_path, "reservations/[id].json", {"root": {}})
    assert guard_table_row_nav(str(tmp_path))["wired"] == 1
    assert guard_table_row_nav(str(tmp_path))["wired"] == 0
