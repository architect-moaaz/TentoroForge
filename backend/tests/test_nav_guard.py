"""Nav-target 404 guard: dead `navigate` targets are repointed (edit→detail,
naming drift) or neutralized so no button 404s. Cases mirror the real gaps found
in the Meridian run."""
from services.nav_guard import repoint, guard_nav_targets

KNOWN = [
    "/", "/dashboard", "/guests", "/guests/[id]", "/guests/new",
    "/reservations", "/reservations/[id]", "/reservations/new",
    "/rate-changes", "/rooms", "/rooms/[id]", "/timeline",
]


def test_resolvable_target_is_kept():
    assert repoint("/guests", KNOWN) == "/guests"
    assert repoint("/guests/[id]", KNOWN) == "/guests/[id]"


def test_templated_dynamic_target_resolves():
    # /guests/{{guest.id}} matches /guests/[id]
    assert repoint("/guests/{{guest.id}}", KNOWN) == "/guests/{{guest.id}}"


def test_edit_without_edit_page_repoints_to_detail():
    # no /guests/[id]/edit exists → view the record instead of 404
    assert repoint("/guests/{{guest.id}}/edit", KNOWN) == "/guests/{{guest.id}}"
    assert repoint("/reservations/{{r.id}}/edit", KNOWN) == "/reservations/{{r.id}}"


def test_naming_drift_repoints_to_close_match():
    # /rate-change-requests → /rate-changes (share the 'rate','change' tokens)
    assert repoint("/rate-change-requests", KNOWN) == "/rate-changes"


def test_unrelated_dead_target_is_neutralized():
    # /calendar has no token overlap with /timeline → drop it (inert, not 404)
    assert repoint("/calendar", KNOWN) is None
    # /users list page doesn't exist and /users/new is a create form, not a match
    assert repoint("/users", KNOWN) is None


def test_guard_rewrites_schema_files(tmp_path):
    root = tmp_path / "src" / "schemas"
    root.mkdir(parents=True)
    (root / "guests.json").write_text('{"root":{"type":"Stack","children":[' +
        '{"type":"Button","props":{"label":"Edit","navigate":"/guests/{{item.id}}/edit"}},' +
        '{"type":"Button","props":{"label":"Approvals","navigate":"/rate-change-requests"}},' +
        '{"type":"Button","props":{"label":"Calendar","navigate":"/calendar"}},' +
        '{"type":"Button","props":{"label":"Guests","navigate":"/guests"}}]}}', encoding="utf-8")
    (root / "guests/[id].json").parent.mkdir(parents=True, exist_ok=True)
    (root / "guests/[id].json").write_text('{"root":{"type":"Stack"}}', encoding="utf-8")
    (root / "rate-changes.json").write_text('{"root":{"type":"Stack"}}', encoding="utf-8")

    res = guard_nav_targets(tmp_path)
    import json
    out = json.loads((root / "guests.json").read_text(encoding="utf-8"))
    btns = out["root"]["children"]
    assert btns[0]["props"]["navigate"] == "/guests/{{item.id}}"   # edit→detail
    assert btns[1]["props"]["navigate"] == "/rate-changes"          # drift→repoint
    assert "navigate" not in btns[2]["props"]                       # /calendar neutralized
    assert btns[3]["props"]["navigate"] == "/guests"               # kept
    assert res["repointed"] == 2 and res["neutralized"] == 1


def test_new_action_drops_to_parent_not_another_entitys_new():
    # /rate-changes/new has no create page → go to the /rate-changes list, NOT
    # /reservations/new (the generic-'new'-token collision bug).
    assert repoint("/rate-changes/new", KNOWN) == "/rate-changes"


def test_new_action_with_no_parent_neutralizes():
    # /audit-log/new with neither /audit-log nor a good match → neutralize.
    assert repoint("/audit-log/new", KNOWN) is None
