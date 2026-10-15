"""The native writer is told what the web's words mean on a phone, is shown the web page itself when there is one,
and is refused nested scrollers; the guide names the values a writer guessed wrong."""
from __future__ import annotations

from pathlib import Path

import pytest

from services.blueprint import native_engineer as ne



def test_the_webs_words_are_translated_for_the_phone():
    prompt = ne.system_prompt({"application": {"name": "Shop"}, "designSystem": {}})
    assert "WRITTEN FOR THE WEB" in prompt and "`header: band`" in prompt and "`lists: cards`" in prompt
    assert "tone=\"inverse\"" in prompt and "the screen's own margin" in prompt


def test_nested_scrollers_are_refused():
    bad = 'import { ScrollView } from "react-native";\nexport default function S() { return null; }\n'
    assert any("two scrollers nested" in f for f in ne._native_findings(bad))
    assert not [f for f in ne._native_findings('import { View } from "react-native";\nexport default function S() { return null; }\n')
                if "scroller" in f]


def test_the_web_page_is_shown_for_what_it_says_when_it_exists():
    page = {"id": "PAGE-002", "name": "Appointments", "route": "/appointments", "pattern": "entity_list"}
    doc = {"application": {"name": "Paws"}, "pages": [page],
           "pageCode": [{"page": "PAGE-002", "view": "<h1>Appointments</h1> Check in"}]}
    shown = ne.user_prompt(doc, page)
    assert "The web page as it is written now" in shown and "Check in" in shown
    unwritten = ne.user_prompt({**doc, "pageCode": []}, page)
    assert "The web page as it is written now" not in unwritten, "a first build writes both at once: nothing to show yet"


def test_the_guide_names_the_values_a_writer_guessed_wrong():
    guide = ne.sdk_guide()
    assert "neutral|info|success|warning|danger|accent" in guide, "Badge tones (a writer used `primary`)"
    assert "justify: start|center|end|between|around" in guide and "xs|sm|md|lg|xl|xxl" in guide


def test_a_screen_that_switches_scrolling_off_must_have_a_list_that_scrolls():
    """The real model's Plants screen had `scroll={false}` over a hand-made stack of cards: nothing scrolled."""
    stack = ('import { Screen } from "@/ui";\nexport default function S() {\n'
             '  return <Screen scroll={false}>{items.map((i) => <Card key={i} />)}</Screen>;\n}\n')
    assert any("nothing on this screen scrolls" in f for f in ne._native_findings(stack))
    listed = stack.replace("{items.map((i) => <Card key={i} />)}", "<ListView list={list} renderItem={() => null} />")
    assert not [f for f in ne._native_findings(listed) if "scrolls" in f]
    assert not [f for f in ne._native_findings(stack.replace(" scroll={false}", "")) if "scrolls" in f]


def test_the_writer_is_told_the_two_rules_the_first_real_screen_broke():
    prompt = ne.system_prompt({"application": {"name": "Shop"}, "designSystem": {}})
    assert "ONE FILLED ACTION PER SCREEN" in prompt and "`due - today` is NEGATIVE when the" in prompt


def test_a_gradient_band_is_finished_by_default_and_only_a_bleeding_frame_styles_itself():
    kit = Path(__file__).resolve().parents[2] / "templates" / "native" / "src" / "ui" / "Auth.tsx"
    code = kit.read_text("utf-8")
    assert "bleed = false" in code and "borderRadius: theme.radii.lg, padding: theme.space.xl" in code
    assert "<GradientBand bleed" in code, "the sign-in frame runs edge to edge and styles itself"


def test_leaving_a_form_without_looking_at_the_result_is_refused():
    """The real model's Add Plant form navigated away in `onDone` even when a rule had refused the plant."""
    blind = 'export default function S() { return <WorkflowForm onDone={() => nav.replace("/x")} />; }\n'
    assert any("ignores the result" in f for f in ne._native_findings(blind))
    for fine in ('onDone={(r) => { if (r.ok) nav.replace("/x"); }}', 'onDone={(r) => r.ok && close()}', 'redirectTo="/x"'):
        assert not [f for f in ne._native_findings(f"export default function S() {{ return <WorkflowForm {fine} />; }}\n") if "ignores the result" in f]
    assert "test `result.ok`" in ne.sdk_guide()


def test_a_list_of_cards_can_be_spaced_and_the_writer_is_told_to():
    """The real model's cards touched: the list gave hairlines and the writer did not know it could give space."""
    kit = Path(__file__).resolve().parents[2] / "templates" / "native" / "src" / "ui" / "ListView.tsx"
    code = kit.read_text("utf-8")
    assert "spaced?: boolean" in code and "spaced ? () => <View style={{ height: theme.space.md }} />" in code
    assert "spaced?" in ne.sdk_guide() and "ListView spaced" in ne.system_prompt({"application": {"name": "S"}, "designSystem": {}})
