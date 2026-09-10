"""A filter value on the wrong field (membershipTier="Active" when Active is a
status) makes an aggregate always return 0. The guard remaps it to the right field."""
import json
from services.filter_field_guard import guard_filter_fields

def _subset(result: dict, expected: dict) -> dict:
    """Project a guard's return dict down to the keys the test asserts on.

    Whole-dict equality breaks every time a guard gains a counter (e.g.
    ``asserts_logged`` from the authority demotions) even though the
    behaviour under test is unchanged. Compare only what the test means.
    """
    return {k: result.get(k) for k in expected}



def _app(tmp_path):
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {"Member": {"fields": {"membershipTier": {}, "status": {}}}},
        "relations": [],
    }), encoding="utf-8")
    (tmp_path / "contracts").mkdir()
    (tmp_path / "contracts" / "seed-plan.json").write_text(json.dumps({
        "tables": [{"name": "members", "seed_data": [
            {"membershipTier": "Bronze", "status": "Active"},
            {"membershipTier": "Gold", "status": "Frozen"},
            {"membershipTier": "Silver", "status": "Cancelled"},
        ]}],
    }), encoding="utf-8")
    sdir = tmp_path / "src" / "schemas"
    sdir.mkdir(parents=True)
    return sdir


def test_remaps_metric_filter_to_correct_field(tmp_path):
    sdir = _app(tmp_path)
    (sdir / "dashboard.json").write_text(json.dumps({
        "route": "/dashboard",
        "dataSources": [{"name": "stats", "entity": "Member", "op": "aggregate", "metrics": {
            "activeMembers": {"fn": "count", "filter": {"membershipTier": "Active"}},
            "goldMembers": {"fn": "count", "filter": {"membershipTier": "Gold"}},
        }}],
        "root": {"type": "Stack", "children": []},
    }), encoding="utf-8")
    res = guard_filter_fields(str(tmp_path))
    assert res["remapped"] == 1
    m = json.loads((sdir / "dashboard.json").read_text(encoding="utf-8"))["dataSources"][0]["metrics"]
    assert m["activeMembers"]["filter"] == {"status": "Active"}   # remapped
    assert m["goldMembers"]["filter"] == {"membershipTier": "Gold"}  # already correct → untouched


def test_ambiguous_or_unknown_left_alone(tmp_path):
    sdir = _app(tmp_path)
    (sdir / "d.json").write_text(json.dumps({
        "route": "/d",
        "dataSources": [{"name": "s", "entity": "Member", "op": "list",
                         "filter": {"membershipTier": "Platinum"}}],  # value in no field
        "root": {"type": "Stack", "children": []},
    }), encoding="utf-8")
    assert guard_filter_fields(str(tmp_path))["remapped"] == 0


def test_idempotent_and_safe(tmp_path):
    _app(tmp_path)
    guard_filter_fields(str(tmp_path))
    # no seed-plan / dir
    assert _subset(guard_filter_fields(str(tmp_path / "nope")), {"remapped": 0, "files": 0}) == {"remapped": 0, "files": 0}
