"""A card drawn as a large number with a label, classified `metric` over an
entity, is realized as a Stat whose value the data layer computes — a count
of the entity, or a sum or average of a field. Before this, `metric` was an
actionable kind the realizer could not bind, so every dashboard number
stayed the drawn text."""
from services.figma.realize import realize, _bindable


def _root():
    return {"type": "Stack", "children": [
        {"type": "Container", "props": {"className": "bg-[#edf2ef]", "_figmaNodeId": "1:70"},
         "children": [{"type": "Text", "props": {"content": "أعضاء المجلس"}}, {"type": "Heading", "props": {"content": "132"}}]},
        {"type": "Text", "props": {"content": "something else"}}]}


def test_a_count_needs_only_its_entity_and_a_sum_needs_its_field():
    assert _bindable({"kind": "metric", "entity": "Member", "fn": "count"})
    assert _bindable({"kind": "metric", "entity": "Member"})
    assert not _bindable({"kind": "metric", "entity": "Bill", "fn": "sum"})
    assert _bindable({"kind": "metric", "entity": "Bill", "fn": "sum", "valueField": "amount"})
    assert not _bindable({"kind": "metric", "fn": "count"})


def test_the_number_is_replaced_by_a_stat_over_an_aggregate_source():
    root, sources, applied = realize(_root(), [
        {"nodeId": "1:70", "kind": "metric", "entity": "Member", "fn": "count", "title": "أعضاء المجلس", "confidence": 0.9, "reason": ""}])
    stat = next(n for n in root["children"] if n.get("type") == "Stat")
    assert stat["props"]["label"] == "أعضاء المجلس"
    (src,) = sources
    assert src["op"] == "aggregate" and src["entity"] == "Member" and src["metrics"] == {"value": {"fn": "count"}}
    assert stat["props"]["value"] == "{{" + src["name"] + ".value}}"
    assert applied[0]["kind"] == "metric"


def test_a_source_named_from_a_node_id_is_a_valid_template_name():
    from services.figma.realize import _source_name
    name = _source_name("أعضاء المجلس", "Member", "1:205")
    assert ":" not in name and name == "member1205"
    assert _source_name("Total Product Sales", "Order", "1:9") == "totalProductSales"
