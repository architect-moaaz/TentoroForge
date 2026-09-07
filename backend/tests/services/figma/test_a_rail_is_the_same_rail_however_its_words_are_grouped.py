"""A subtree's fingerprint is its type and its words, not how a transform
grouped them into controls.

The shared chrome is fingerprinted from screens transformed without the
action classifier; each page is transformed with it, and the classifier folds
a rail item's icon, label and badge into one Button labelled "◉Notifications3"
where the plain transform had three texts. The words were the same and the
hashes were not, so the rail stayed on every page and its "+New Case" — bound
to a workflow no page could supply — had fifteen layouts refused.
"""
from services.figma.chrome import fingerprint


def _rail(item: dict) -> dict:
    return {"type": "Stack", "props": {}, "children": [
        {"type": "Text", "props": {"content": "Overview"}},
        {"type": "Text", "props": {"content": "⬡Dashboard"}},
        item,
    ]}


def test_three_texts_and_one_bound_button_are_the_same_rail():
    drawn = _rail({"type": "Stack", "props": {}, "children": [
        {"type": "Text", "props": {"content": "◉"}},
        {"type": "Text", "props": {"content": "Notifications"}},
        {"type": "Text", "props": {"content": "3"}},
    ]})
    bound = _rail({"type": "Stack", "props": {}, "children": [
        {"type": "Button", "props": {"label": "◉Notifications3", "workflow": "FLOW-011"}},
    ]})

    assert fingerprint(drawn) == fingerprint(bound)


def test_different_words_are_a_different_rail():
    one = _rail({"type": "Text", "props": {"content": "Notifications"}})
    other = _rail({"type": "Text", "props": {"content": "Audit Log"}})

    assert fingerprint(one) != fingerprint(other)
