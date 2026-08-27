"""Tests for the semantic-prefix decoder used by the read-binding contract.

Pure functions: `strip_prefix` splits a leading camelCase semantic prefix, and
`decode_view` turns a prefix + the entity's real columns into an
only-applicable {filter, sort, limit} view spec.
"""
from services.read_binding_semantics import strip_prefix, decode_view


# --- prefix stripping → (prefix, base_token) -------------------------------
def test_strip_prefix():
    assert strip_prefix("activeRecruitmentDrives") == ("active", "recruitmentDrives")
    assert strip_prefix("recentApplicants") == ("recent", "applicants")
    assert strip_prefix("upcomingInterviews") == ("upcoming", "interviews")
    assert strip_prefix("recruitmentDrives") == ("", "recruitmentDrives")  # no prefix


def test_strip_prefix_edge_cases():
    # "news" starts with "new" but the next char is lowercase 's' → NOT a prefix.
    assert strip_prefix("newsFeed") == ("", "newsFeed")
    # "completed" is a known prefix followed by an uppercase letter.
    assert strip_prefix("completedTasks") == ("completed", "tasks")
    # case-insensitive prefix match, remainder leading char lowercased.
    assert strip_prefix("TopPerformers") == ("top", "performers")
    # bare prefix with no uppercase remainder does not count.
    assert strip_prefix("active") == ("", "active")


# --- decode uses REAL columns: status enum values + date-ish fields --------
COLS = {"status": {"type": "varchar", "enum": ["Active", "Closed"]},
        "createdAt": {"type": "timestamp"}, "startsAt": {"type": "timestamp"}}


def test_decode_active_maps_to_status_filter():
    v = decode_view("active", COLS)
    assert v["filter"] == {"status": "Active"}


def test_decode_recent_sorts_desc_limits():
    v = decode_view("recent", COLS)
    assert v["sort"] == {"field": "createdAt", "direction": "desc"}
    assert v["limit"] == 5
    assert "filter" not in v


def test_decode_upcoming_sorts_asc_on_future_date():
    v = decode_view("upcoming", COLS)
    assert v["sort"]["direction"] == "asc"
    assert v["sort"]["field"] == "startsAt"
    assert v["limit"] == 5


def test_decode_no_status_column_omits_filter():
    v = decode_view("active", {"createdAt": {"type": "timestamp"}})
    assert "filter" not in v  # no status column → do not invent one


def test_decode_empty_prefix_is_plain_list():
    assert decode_view("", COLS) == {}


# --- missing-column omission ------------------------------------------------
def test_decode_recent_missing_date_column_omits_sort():
    assert "sort" not in decode_view("recent", {})
    assert decode_view("recent", {}).get("limit") == 5


def test_decode_upcoming_missing_future_date_omits_sort():
    # only a createdAt-like col exists, no future-date col → no sort for upcoming.
    assert "sort" not in decode_view("upcoming", {"createdAt": {"type": "timestamp"}})


def test_decode_completed_maps_status_value():
    cols = {"state": {"type": "varchar", "enum": ["Open", "Done"]}}
    v = decode_view("completed", cols)
    assert v["filter"] == {"state": "Done"}


def test_decode_closed_maps_status_value():
    v = decode_view("closed", COLS)
    assert v["filter"] == {"status": "Closed"}


def test_decode_pending_no_matching_enum_omits_filter():
    # no enum member matches "pending" → do not invent a filter.
    v = decode_view("pending", COLS)
    assert "filter" not in v


def test_decode_top_sorts_desc_on_numeric_column():
    cols = {"score": {"type": "integer"}, "createdAt": {"type": "timestamp"}}
    v = decode_view("top", cols)
    assert v["sort"] == {"field": "score", "direction": "desc"}
    assert v["limit"] == 5


def test_decode_top_falls_back_to_date_when_no_numeric():
    v = decode_view("top", {"createdAt": {"type": "timestamp"}})
    assert v["sort"] == {"field": "createdAt", "direction": "desc"}
    assert v["limit"] == 5


def test_decode_open_maps_to_active_like_value():
    cols = {"status": {"type": "varchar", "enum": ["Open", "Closed"]}}
    v = decode_view("open", cols)
    assert v["filter"] == {"status": "Open"}


def test_decode_new_uses_created_at_desc():
    v = decode_view("new", COLS)
    assert v["sort"] == {"field": "createdAt", "direction": "desc"}
    assert v["limit"] == 5


def test_decode_unknown_prefix_is_empty():
    assert decode_view("bogus", COLS) == {}
