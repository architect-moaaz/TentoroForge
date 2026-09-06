"""A designer draws a list as example rows; realizing the region as a Table
kept the records and threw the drawing away. The first drawn row becomes the
template of a Repeat over the entity's list source, its leaves bound to the
record's fields by a reading the model makes, and the other example rows go.
A row the model cannot read leaves the region to the Table."""
import json

from services.figma import rows
from services.figma.realize import realize


def _row(t, day, title, room, chip):
    return {"type": "Row", "props": {"className": "border-b"}, "children": [
        {"type": "Stack", "children": [{"type": "Text", "props": {"content": t}},
                                        {"type": "Text", "props": {"content": day}}]},
        {"type": "Stack", "children": [{"type": "Text", "props": {"content": title}},
                                        {"type": "Text", "props": {"content": room}}]},
        {"type": "Container", "props": {"className": "bg-[#e6f4ed]"},
         "children": [{"type": "Text", "props": {"content": chip}}]}]}


def _region():
    return {"type": "Container", "props": {"_figmaNodeId": "1:282", "className": "bg-white"}, "children": [
        {"type": "Row", "children": [{"type": "Text", "props": {"content": "الجلسات القادمة"}},
                                     {"type": "Text", "props": {"content": "عرض الكل ←"}}]},
        {"type": "Stack", "children": [
            _row("10:00", "الإثنين", "جلسة لجنة المالية", "قاعة المالية", "لجنة"),
            _row("14:00", "الثلاثاء", "جلسة عامة", "قاعة الجلسات", "عامة"),
            _row("09:30", "الأربعاء", "اجتماع لجنة التشريع", "قاعة لجنة التشريع", "لجنة")]}]}


SESSION = {"name": "Session", "fields": [{"name": "startsAt", "type": "timestamp"}, {"name": "title", "type": "string"},
                                          {"name": "location", "type": "string"}, {"name": "status", "type": "enum"}]}


def _stub_ask(system, user, schema):
    return json.dumps({"leaves": [
        {"index": 0, "field": "startsAt", "formatter": "time"}, {"index": 1, "field": "startsAt", "formatter": "weekday"},
        {"index": 2, "field": "title", "formatter": ""}, {"index": 3, "field": "location", "formatter": ""},
        {"index": 4, "field": "status", "formatter": ""}]})


def test_the_rows_are_the_run_of_siblings_that_share_a_shape():
    container, drawn = rows.row_blocks(_region())
    assert len(drawn) == 3 and container["type"] == "Stack"
    assert [l["props"]["content"] for l in rows._leaves(drawn[0], [])] == ["10:00", "الإثنين", "جلسة لجنة المالية", "قاعة المالية", "لجنة"]


def test_the_mapping_is_the_models_reading_kept_to_known_fields():
    mapping = rows.map_row(_stub_ask, ["10:00", "الإثنين", "جلسة لجنة المالية", "قاعة المالية", "لجنة"], SESSION)
    assert [m["field"] for m in mapping] == ["startsAt", "startsAt", "title", "location", "status"]
    assert mapping[0]["formatter"] == "time" and mapping[1]["formatter"] == "weekday"
    bad = lambda **k: json.dumps({"leaves": [{"index": 0, "field": "notAField"}]})
    assert rows.map_row(bad, ["x"], SESSION) == []


def test_the_region_becomes_a_repeat_of_the_first_row_as_drawn():
    root = {"type": "Stack", "children": [_region()]}
    out, sources, applied = realize(root, [
        {"nodeId": "1:282", "kind": "table", "entity": "Session", "columns": ["startsAt", "title"],
         "title": "الجلسات القادمة", "confidence": 0.9, "reason": ""}],
        row_mapper=lambda leaves, entity: rows.map_row(_stub_ask, leaves, SESSION))
    region = out["children"][0]
    assert region["props"]["className"] == "bg-white", "the card stays as drawn"
    header, lst = region["children"]
    assert header["children"][0]["props"]["content"] == "الجلسات القادمة"
    (repeat,) = lst["children"]
    assert repeat["type"] == "Repeat" and repeat["props"] == {"source": sources[0]["name"], "as": "item"}
    (template,) = repeat["children"]
    texts = [l["props"]["content"] for l in rows._leaves(template, [])]
    assert texts == ["{{item.startsAt|time}}", "{{item.startsAt|weekday}}", "{{item.title}}", "{{item.location}}", "{{item.status}}"]
    assert template["children"][2]["props"]["className"] == "bg-[#e6f4ed]", "the chip keeps its fill"
    assert sources[0]["op"] == "list" and sources[0]["entity"] == "Session"


def test_a_row_the_model_cannot_read_leaves_the_region_to_the_table():
    root = {"type": "Stack", "children": [_region()]}
    out, sources, applied = realize(root, [
        {"nodeId": "1:282", "kind": "table", "entity": "Session", "columns": ["startsAt", "title"],
         "title": "x", "confidence": 0.9, "reason": ""}],
        row_mapper=lambda leaves, entity: [])
    assert out["children"][0]["type"] == "Table"


def test_a_mapper_that_raises_leaves_the_page_whole_and_the_input_untouched():
    root = {"type": "Stack", "children": [
        {"type": "Container", "props": {"className": "bg-[#edf2ef]", "_figmaNodeId": "1:70"},
         "children": [{"type": "Text", "props": {"content": "أعضاء"}}, {"type": "Heading", "props": {"content": "132"}}]},
        _region()]}
    before = json.dumps(root, ensure_ascii=False)

    def boom(leaves, entity):
        raise RuntimeError("'ModelReply' object has no attribute 'get'")

    out, sources, applied = realize(root, [
        {"nodeId": "1:70", "kind": "metric", "entity": "Member", "fn": "count", "title": "أعضاء", "confidence": 0.9, "reason": ""},
        {"nodeId": "1:282", "kind": "table", "entity": "Session", "columns": ["title"], "title": "x", "confidence": 0.9, "reason": ""}],
        row_mapper=boom)
    assert json.dumps(root, ensure_ascii=False) == before, "the caller's tree is not touched"
    assert out["children"][1]["type"] == "Table"
    names = {s["name"] for s in sources}
    bound = out["children"][0]["children"][1]["props"]["content"]
    assert bound.startswith("{{") and bound[2:].split(".")[0] in names


def test_the_mapper_reads_a_reply_object_as_the_classifier_does():
    class Reply:
        text = json.dumps({"leaves": [{"index": 0, "field": "title", "formatter": ""}]})
    assert rows.map_row(lambda **k: Reply(), ["x"], SESSION) == [{"index": 0, "field": "title", "formatter": ""}]


def test_dates_in_a_bound_row_are_written_in_the_applications_language():
    root = {"type": "Stack", "children": [_region()]}
    out, sources, applied = realize(root, [
        {"nodeId": "1:282", "kind": "table", "entity": "Session", "columns": ["title"], "title": "x", "confidence": 0.9, "reason": ""}],
        row_mapper=lambda leaves, entity: rows.map_row(_stub_ask, leaves, SESSION), locale="ar")
    texts = [l["props"]["content"] for l in rows._leaves(out["children"][0]["children"][1]["children"][0]["children"][0], [])]
    assert texts[:2] == ["{{item.startsAt|time:ar}}", "{{item.startsAt|weekday:ar}}"] and texts[2] == "{{item.title}}"
