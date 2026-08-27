"""`direction: rtl` must be conditional on the document actually being RTL.

The design agent, seeing an Arabic app name, writes an "Arabic-first (RTL)"
stylesheet: `html { direction: rtl }`, `body { direction: rtl }`, and the
same on textarea/table/label. But layout.tsx emits `<html lang="en">` with
no `dir`, and every generated string is English. CSS wins, so English renders
right-to-left — ".The numbers moved while you were out", labels flush to the
wrong edge, the whole shell mirrored.

The document's direction belongs to the `dir` attribute. Scoping the rules to
`[dir="rtl"]` keeps the intent and makes it conditional on the premise it
always depended on.
"""
from __future__ import annotations

from services.rtl_scope_guard import scope_rtl_rules


class TestDocumentWideRulesGetScoped:
    def test_html_rule_is_scoped(self):
        out, n = scope_rtl_rules("html {\n  direction: rtl;\n}")
        assert n == 1 and '[dir="rtl"] {' in out and "direction: rtl" in out

    def test_body_rule_is_scoped(self):
        out, _ = scope_rtl_rules("body { color: red; direction: rtl; }")
        assert '[dir="rtl"]' in out and "color: red" in out

    def test_element_rules_are_scoped_as_descendants(self):
        out, _ = scope_rtl_rules("textarea {\n  font-size: 14px;\n  direction: rtl;\n}")
        assert '[dir="rtl"] textarea' in out

    def test_a_selector_list_scopes_every_part(self):
        out, _ = scope_rtl_rules("input, textarea { direction: rtl; }")
        assert '[dir="rtl"] input' in out and '[dir="rtl"] textarea' in out


class TestOptInAndAlreadyScopedRulesAreLeftAlone:
    def test_a_helper_class_is_untouched(self):
        """`.arabic-text` is opt-in — the author already made it conditional."""
        css = ".arabic-text { direction: rtl; }"
        assert scope_rtl_rules(css) == (css, 0)

    def test_an_already_scoped_rule_is_untouched(self):
        css = '[dir="rtl"] .x { direction: rtl; }'
        assert scope_rtl_rules(css) == (css, 0)

    def test_ltr_declarations_are_not_touched(self):
        css = "html { direction: ltr; }"
        assert scope_rtl_rules(css) == (css, 0)

    def test_css_without_direction_is_returned_unchanged(self):
        css = ".a { color: red; }"
        assert scope_rtl_rules(css) == (css, 0)


class TestSafety:
    def test_running_twice_changes_nothing_the_second_time(self):
        once, n1 = scope_rtl_rules("html { direction: rtl; }\nbody { direction: rtl; }")
        twice, n2 = scope_rtl_rules(once)
        assert n1 == 2 and n2 == 0 and once == twice

    def test_surrounding_css_survives(self):
        css = ".keep { margin: 0 }\nhtml { direction: rtl; }\n.also { padding: 2px }"
        out, _ = scope_rtl_rules(css)
        assert ".keep { margin: 0 }" in out and ".also { padding: 2px }" in out

    def test_an_rtl_document_still_gets_the_styling(self):
        """Scoping is not deletion — dir="rtl" apps are unaffected in effect."""
        out, _ = scope_rtl_rules("body { direction: rtl; }")
        assert '[dir="rtl"]' in out and "direction: rtl" in out
