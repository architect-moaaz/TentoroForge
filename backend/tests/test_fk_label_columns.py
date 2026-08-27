"""FK table columns should show the referenced record's label, not a raw UUID."""
import json
from services.fk_label_columns import relabel_fk_columns


def _app(tmp_path):
    (tmp_path / "registry.json").write_text(json.dumps({
        "entities": {
            "ClassBooking": {"fields": {"id": {"type": "uuid"}, "memberId": {"type": "uuid"},
                                        "fitnessClassId": {"type": "uuid"}, "status": {"type": "varchar"}}},
            "Member": {"fields": {"id": {"type": "uuid"}, "fullName": {"type": "varchar"}}},
            "FitnessClass": {"fields": {"id": {"type": "uuid"}, "title": {"type": "varchar"}}},
        },
        "relations": [
            {"from_entity": "ClassBooking", "to_entity": "Member", "type": "many-to-one"},
            {"from_entity": "ClassBooking", "to_entity": "FitnessClass", "type": "many-to-one"},
        ],
    }))
    sdir = tmp_path / "src" / "schemas"
    sdir.mkdir(parents=True)
    return sdir


def test_relabels_fk_columns_and_emits_metadata(tmp_path):
    sdir = _app(tmp_path)
    (sdir / "bookings.json").write_text(json.dumps({
        "route": "/bookings",
        "dataSources": [{"name": "bookings", "entity": "ClassBooking", "op": "list"}],
        "root": {"type": "Table", "props": {"columns": [
            {"key": "memberId", "label": "Member"},
            {"key": "fitnessClassId", "label": "Fitness Class"},
            {"key": "status", "label": "Status"},
        ]}},
    }))
    res = relabel_fk_columns(str(tmp_path))
    assert res["relabeled"] == 2
    cols = json.loads((sdir / "bookings.json").read_text())["root"]["props"]["columns"]
    keys = [c["key"] for c in cols]
    assert keys == ["memberIdLabel", "fitnessClassIdLabel", "status"]  # FKs relabeled, status left

    # fk-labels.json emitted with target + label field, keyed by a route alias.
    meta = json.loads((tmp_path / "src" / "lib" / "fk-labels.json").read_text())
    assert "classbookings" in meta or "classbooking" in meta
    m = meta.get("classbookings") or meta.get("classbooking")
    assert m["memberId"] == {"targetEntity": "Member", "labelField": "fullName"}
    assert m["fitnessClassId"]["labelField"] == "title"


def test_idempotent(tmp_path):
    sdir = _app(tmp_path)
    (sdir / "bookings.json").write_text(json.dumps({
        "route": "/bookings",
        "dataSources": [{"name": "bookings", "entity": "ClassBooking", "op": "list"}],
        "root": {"type": "Table", "props": {"columns": [{"key": "memberId", "label": "Member"}]}},
    }))
    relabel_fk_columns(str(tmp_path))
    res = relabel_fk_columns(str(tmp_path))
    assert res["relabeled"] == 0   # already ...Label


def test_no_entities_safe(tmp_path):
    (tmp_path / "src" / "schemas").mkdir(parents=True)
    assert relabel_fk_columns(str(tmp_path)) == {"relabeled": 0, "entities": 0, "files": 0}
