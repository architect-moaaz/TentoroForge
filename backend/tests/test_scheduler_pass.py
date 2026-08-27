"""Deterministic ResourceTimeline adoption: detect a schedulable domain from the
entity schema (item with date-range + resource FK) and build the timeline node."""
from services.scheduler_pass import detect_scheduler, build_resource_timeline

HOTEL = {
    "Room": {"fields": {"id": {"type": "uuid"}, "roomNumber": {"type": "varchar"},
                        "roomType": {"type": "varchar"}}},
    "Guest": {"fields": {"id": {"type": "uuid"}, "firstName": {"type": "varchar"}}},
    "Reservation": {"fields": {
        "id": {"type": "uuid"},
        "roomId": {"type": "uuid"}, "guestId": {"type": "uuid"},
        "checkInDate": {"type": "timestamp"}, "checkOutDate": {"type": "timestamp"},
        "status": {"type": "varchar"},
    }},
}

def test_detects_hotel_reservation_shape():
    m = detect_scheduler(HOTEL)
    assert m["itemEntity"] == "Reservation"
    assert m["resourceEntity"] == "Room"           # roomId → Room (a resource), not Guest
    assert m["itemResourceField"] == "roomId"
    assert {m["startField"], m["endField"]} == {"checkInDate", "checkOutDate"}
    assert m["statusField"] == "status"
    assert m["resourceLabelField"] == "roomNumber"
    assert m["resourceGroupField"] == "roomType"

def test_builds_bound_resource_timeline_node():
    node = build_resource_timeline(detect_scheduler(HOTEL))
    assert node["type"] == "ResourceTimeline"
    p = node["props"]
    assert p["resources"] == "{{rooms}}" and p["items"] == "{{reservations}}"
    assert p["itemResourceField"] == "roomId"
    assert p["startField"] == "checkInDate" and p["endField"] == "checkOutDate"
    assert p["statusField"] == "status" and p["resourceGroupField"] == "roomType"

def test_non_scheduler_domain_returns_none():
    # A plain blog: no date-range + resource FK.
    assert detect_scheduler({
        "Post": {"fields": {"id": {"type": "uuid"}, "title": {"type": "varchar"},
                            "publishedAt": {"type": "timestamp"}, "authorId": {"type": "uuid"}}},
        "Author": {"fields": {"id": {"type": "uuid"}, "name": {"type": "varchar"}}},
    }) is None

def test_list_shaped_fields_supported():
    plan = {"Reservation": {"fields": [
        {"name": "roomId", "type": "uuid"}, {"name": "startDate", "type": "date"},
        {"name": "endDate", "type": "date"}, {"name": "status", "type": "varchar"}]},
        "Room": {"fields": [{"name": "name", "type": "varchar"}]}}
    m = detect_scheduler(plan)
    assert m and m["itemResourceField"] == "roomId"


from services.scheduler_pass import ensure_scheduler_view, is_scheduler_route

def test_injects_timeline_when_absent_after_heading():
    node = build_resource_timeline(detect_scheduler(HOTEL))
    schema = {"root": {"type": "Stack", "children": [
        {"type": "Heading", "props": {"content": "Reservations"}},
        {"type": "Table", "props": {"rows": "{{reservations}}"}},
    ]}}
    out, injected = ensure_scheduler_view(schema, node)
    kids = out["root"]["children"]
    assert injected is True
    assert kids[0]["type"] == "Heading"            # heading stays first
    assert kids[1]["type"] == "ResourceTimeline"   # timeline is now the hero
    assert kids[2]["type"] == "Table"              # table kept below

def test_noop_when_timeline_already_present():
    node = build_resource_timeline(detect_scheduler(HOTEL))
    schema = {"root": {"type": "Stack", "children": [node]}}
    _, injected = ensure_scheduler_view(schema, dict(node))
    assert injected is False

def test_route_detection():
    assert is_scheduler_route("/calendar")
    assert is_scheduler_route("/reservations")
    assert is_scheduler_route("/guests", {"itemEntity": "Reservation"}) is False

def test_form_and_detail_routes_excluded():
    m = {"itemEntity": "Reservation"}
    assert is_scheduler_route("/reservations", m) is True
    assert is_scheduler_route("/reservations/new", m) is False
    assert is_scheduler_route("/reservations/[id]", m) is False
    assert is_scheduler_route("/reservations/{{id}}/edit", m) is False
