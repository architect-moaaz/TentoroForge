"""A native screen that does not compile goes back to the writer with the line, a mark under the spot, and what to do.

The first Cart Buddy shopping-list screen failed three rounds on errors the compiler named only by position:
`(2,79): … has no exported member 'toast'`, `(122,13): 'hasMore' does not exist in type 'ListLike<…>'`. The writer had to count to
find the place and guess where `toast` lives. Now it is shown the line, and told `toast` is in "@/sdk"."""
from __future__ import annotations

from pathlib import Path

from services.blueprint import native_engineer as ne
from services.blueprint.native_projection import TEMPLATE_DIR

ROOT = Path(TEMPLATE_DIR)

SCREEN = "\n".join([
    'import React, { useState } from "react";',
    'import { Screen as ScreenView, Text, Row, Stack, Button, ListView, toast } from "@/ui";',
    'import { useList } from "@/sdk";',
    "",
    "export default function Screen() {",
    "  const list = useList(\"ShoppingItem\", {});",
    "  return <ListView list={list} hasMore={true} keyExtractor={(i) => i.id} renderItem={(i) => <Text>{i.name}</Text>} />;",
    "}",
])

NO_MEMBER = "Screen.tsx(2,76): error TS2305: Module '\"@/ui\"' has no exported member 'toast'."
UNKNOWN_PROP = ("Screen.tsx(7,46): error TS2353: Object literal may only specify known properties, and 'hasMore' does not exist "
                "in type 'ListLike<ShoppingItem>'.")


def test_the_line_is_shown_with_a_mark_under_the_spot():
    text = ne.explain_error(NO_MEMBER, SCREEN, ROOT)
    assert text.startswith(NO_MEMBER)
    assert "line 2: import { Screen as ScreenView" in text
    caret = [l for l in text.splitlines() if l.strip() == "^"][0]
    shown = [l for l in text.splitlines() if "line 2:" in l][0]
    # the mark sits under column 76 of the line shown
    assert len(caret) - 1 == len(shown) - len(SCREEN.splitlines()[1]) + 75


def test_a_name_in_the_wrong_module_is_told_where_it_lives():
    text = ne.explain_error(NO_MEMBER, SCREEN, ROOT)
    assert 'hint: `toast` is exported from "@/sdk", not "@/ui".' in text


def test_a_name_that_exists_nowhere_is_said_so():
    text = ne.explain_error(NO_MEMBER.replace("'toast'", "'zzz'"), SCREEN, ROOT)
    assert "`zzz` is exported from neither" in text


def test_an_option_the_part_does_not_take_is_told_to_go():
    text = ne.explain_error(UNKNOWN_PROP, SCREEN, ROOT)
    assert "`hasMore` is not something ListLike<ShoppingItem> accepts: delete it" in text


def test_a_rule_without_a_line_is_passed_through_unchanged():
    rule = 'Screen.tsx: `as any` turns the compiler off for that line.'
    assert ne.explain_error(rule, SCREEN, ROOT) == rule


def test_a_line_past_the_end_is_not_a_crash():
    text = ne.explain_error("Screen.tsx(99,1): error TS2305: Module '\"@/ui\"' has no exported member 'toast'.", SCREEN, ROOT)
    assert "line 99" not in text and 'exported from "@/sdk"' in text


def test_the_exports_are_read_from_the_kit_not_listed_by_hand():
    assert "toast" in ne._exports_of(ROOT / "src" / "sdk" / "index.ts")
    assert "toast" not in ne._exports_of(ROOT / "src" / "ui" / "index.ts")
    assert "ListView" in ne._exports_of(ROOT / "src" / "ui" / "index.ts")
