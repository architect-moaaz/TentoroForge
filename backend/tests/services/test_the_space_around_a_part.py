"""The Editor's "Space around": a margin on a part of a phone screen, saved as the part's own `style`.

A style of margin numbers cannot break a type, so it is saved without the compiler (the fixture has none, and a change that
needed one would fail). Anything else in a style, or a part that takes no style, still has to pass the compiler."""
from __future__ import annotations

import pytest

from services.react_editor import phone_kit, phone_screens as ps, service
from services.react_editor.service import EditorError

from tests.services.test_the_phone_screen_parts import _file, _node, _opened, _set, p  # noqa: F401 - the fixture


def _expr(code: str) -> dict:
    return {"kind": "expr", "value": code}


def test_a_style_of_margin_numbers_is_saved_without_the_compiler(p):
    o = _opened(p)
    out = ps.apply(p, "PAGE-001", base_revision=o["revision"],
                   ops=[_set(_node(o, "Stack"), "style", _expr("{ marginTop: 16, paddingLeft: 8 }"))])
    assert "style={{ marginTop: 16, paddingLeft: 8 }}" in _file(p)
    assert out["revision"] != o["revision"]


def test_the_space_can_be_changed_again_and_emptied(p):
    o = _opened(p)
    first = ps.apply(p, "PAGE-001", base_revision=o["revision"], ops=[_set(_node(o, "Row"), "style", _expr("{ marginBottom: 24 }"))])
    ps.apply(p, "PAGE-001", base_revision=first["revision"], ops=[_set(_node(first, "Row"), "style", _expr("{}"))])
    assert "marginBottom" not in _file(p)


@pytest.mark.parametrize("code", [
    "{ marginTop: theme.space.md }",          # not a number
    "{ marginTop: 16, color: 'red' }",        # more than margins
    "{ marginTop: 9999 }",                    # not a margin a phone screen has
    "{ paddingTop: 16, flex: 1 }",           # padding beside something that is not spacing
    "[styles.a, { marginTop: 4 }]",           # not a plain object
])
def test_anything_but_plain_margins_still_needs_the_compiler(p, code):
    o = _opened(p)
    with pytest.raises(EditorError) as raised:
        ps.apply(p, "PAGE-001", base_revision=o["revision"], ops=[_set(_node(o, "Stack"), "style", _expr(code))])
    assert raised.value.code == "no-compiler"


def test_a_part_that_takes_no_style_is_not_given_one_without_the_compiler(p):
    o = _opened(p)
    with pytest.raises(EditorError) as raised:
        ps.apply(p, "PAGE-001", base_revision=o["revision"], ops=[_set(_node(o, "ScreenView"), "style", _expr("{ marginTop: 8 }"))])
    assert raised.value.code == "no-compiler"


def test_margins_only_reads_the_value_exactly():
    assert phone_kit.margins_only(_expr("{ marginTop: 16, marginRight: -4.5 }"))
    assert phone_kit.margins_only(_expr("{ paddingLeft: 12, paddingBottom: 0 }"))
    assert phone_kit.margins_only(_expr("{}"))
    assert not phone_kit.margins_only(_expr("{ marginTop: 16, padding: 4 }"))
    assert not phone_kit.margins_only({"kind": "string", "value": "{ marginTop: 16 }"})
    assert not phone_kit.margins_only(None)


def test_a_list_takes_a_margin_and_a_padding(p):
    assert "ListView" in phone_kit.STYLE_PARTS
