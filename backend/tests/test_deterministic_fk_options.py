"""Regression: deterministic FK Selects must emit `optionsFrom` in the OBJECT form
{source, value, label} — the renderer's expandOptionsFrom rejects a bare string,
which left "Add reservation" dropdowns empty."""
from services.deterministic_pages import build_crud_page, build_form_page


ENTITIES = {
    "Guest": {"fields": {
        "id": {"type": "uuid", "primaryKey": True},
        "firstName": {"type": "varchar"},
        "email": {"type": "varchar"},
    }},
    "Room": {"fields": {
        "id": {"type": "uuid", "primaryKey": True},
        "roomNumber": {"type": "varchar"},
    }},
    "Reservation": {"fields": {
        "id": {"type": "uuid", "primaryKey": True},
        "guestId": {"type": "uuid"},
        "roomId": {"type": "uuid"},
        "status": {"type": "varchar"},
    }},
}


def _selects(page):
    out = []
    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == "Select":
                out.append(n["props"])
            for c in n.get("children") or []:
                walk(c)
    walk(page["root"])
    return out


def test_fk_select_emits_object_optionsfrom_not_string():
    page = build_crud_page("form", "Reservation", ENTITIES["Reservation"]["fields"],
                           "/reservations/new", {}, entities=ENTITIES)
    selects = {s["name"]: s["optionsFrom"] for s in _selects(page)}
    assert set(selects) == {"guestId", "roomId"}
    for of in selects.values():
        assert isinstance(of, dict), "optionsFrom must be the object form, not a string"
        assert of["value"] == "id"
        assert isinstance(of.get("source"), str) and of["source"]


def test_label_field_resolved_from_target_entity():
    page = build_crud_page("form", "Reservation", ENTITIES["Reservation"]["fields"],
                           "/reservations/new", {}, entities=ENTITIES)
    selects = {s["name"]: s["optionsFrom"] for s in _selects(page)}
    assert selects["guestId"] == {"source": "guests", "value": "id", "label": "email"}
    assert selects["roomId"] == {"source": "rooms", "value": "id", "label": "roomNumber"}


def test_datasource_entity_resolved_for_each_fk_source():
    page = build_form_page("Reservation", ENTITIES["Reservation"]["fields"],
                           "/reservations/new", {}, op="create", entities=ENTITIES)
    ds = {d["name"]: d["entity"] for d in page.get("dataSources", [])}
    assert ds == {"guests": "Guest", "rooms": "Room"}


def test_object_form_even_without_registry():
    # No entities passed → still object form (graceful default label), never a bare string.
    page = build_crud_page("form", "Reservation", ENTITIES["Reservation"]["fields"],
                           "/reservations/new", {})
    for of in (s["optionsFrom"] for s in _selects(page)):
        assert isinstance(of, dict) and of["value"] == "id" and of.get("source")


def test_builder_never_throws_on_list_shaped_fields():
    """Regression: a plan may carry entity fields as a LIST; the builder must
    normalize (not crash → LLM fallback → stub pages during an LLM outage)."""
    page = build_crud_page(
        "form", "Reservation",
        [{"name": "guestId", "type": "uuid", "nullable": False},
         {"name": "checkInDate", "type": "timestamp", "nullable": False}],
        "/reservations/new", {},
        entities={"Guest": {"fields": [{"name": "email", "type": "varchar"}]},
                  "Reservation": {"fields": []}},
    )
    assert page and page["root"]["children"]
    # list-target still resolves the FK label field
    def sel(n, out=[]):
        if isinstance(n, dict):
            if n.get("type") == "Select": out.append(n["props"])
            for c in n.get("children") or []: sel(c, out)
        return out
    selects = {s["name"]: s.get("optionsFrom", {}).get("label") for s in sel(page["root"])}
    assert selects.get("guestId") == "email"
