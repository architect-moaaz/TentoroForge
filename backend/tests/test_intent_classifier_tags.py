"""Tests for Spec D Wave 3 (D3-C) — tag-based tool derivation on
intent_classifier. Additive: LLM emits needed_tags, tools_for_tags
computes the union; falls back to closed TOOL_SUBSETS[intent] when
tags are absent or unusable.
"""
from __future__ import annotations

import json

from services.intent_classifier import (
    KNOWN_TAGS,
    TOOL_TAGS,
    Intent,
    TOOL_SUBSETS,
    classify_intent,
    tools_for_tags,
)


class TestToolTagsIndex:
    def test_every_tool_has_at_least_one_tag(self):
        for name, tags in TOOL_TAGS.items():
            assert isinstance(tags, set) and tags, f"{name} has no tags"

    def test_every_tool_tag_is_in_known_tags(self):
        bad = {n: tags - KNOWN_TAGS for n, tags in TOOL_TAGS.items()
               if tags - KNOWN_TAGS}
        assert not bad, f"unknown tags: {bad}"

    def test_every_tool_in_TOOL_SUBSETS_is_indexed(self):
        # Every tool that a legacy intent scoping includes must have a
        # tag entry — otherwise the tag path silently drops tools the
        # intent path would have granted.
        for intent, subset in TOOL_SUBSETS.items():
            if subset is None:
                continue
            for tool in subset:
                assert tool in TOOL_TAGS, (
                    f"tool {tool!r} used by intent {intent!r} but missing "
                    "from TOOL_TAGS index"
                )


class TestToolsForTags:
    def test_none_or_empty_returns_none(self):
        assert tools_for_tags(None) is None  # type: ignore[arg-type]
        assert tools_for_tags([]) is None

    def test_all_unknown_tags_returns_none(self):
        assert tools_for_tags(["gibberish", "not-a-tag"]) is None

    def test_terminal_only_match_returns_none(self):
        # `chat` tag matches only answer + ask_user (terminals). The
        # helper returns None so the caller falls back to the closed
        # subset — otherwise Smith would be scoped to just the
        # terminals and unable to accomplish anything.
        result = tools_for_tags(["chat"])
        assert result is None

    def test_page_tag_returns_page_tools_plus_terminals(self):
        result = tools_for_tags(["page"])
        assert result is not None
        assert "list_pages" in result
        assert "read_page" in result
        assert "edit_page" in result
        assert "add_page" in result
        assert "remove_page" in result
        # Terminals always included.
        assert "answer" in result
        assert "ask_user" in result
        # Sorted for stable output.
        assert result == sorted(result)

    def test_multiple_tags_union(self):
        result = tools_for_tags(["read", "workflow"])
        assert result is not None
        # Both read-family AND workflow-family tools are in the union.
        assert "list_pages" in result       # read-only
        assert "add_workflow" in result     # workflow-only
        assert "read_workflow" in result    # both
        assert "answer" in result

    def test_unknown_tags_silently_dropped(self):
        # A mixed list of known + unknown returns the known-tag subset.
        result = tools_for_tags(["page", "hallucinated-tag"])
        assert result is not None
        assert "edit_page" in result

    def test_case_insensitive(self):
        result = tools_for_tags(["PAGE", "  Edit  "])
        assert result is not None
        assert "edit_page" in result

    def test_non_string_entries_ignored(self):
        result = tools_for_tags([42, None, "page"])  # type: ignore[list-item]
        assert result is not None
        assert "edit_page" in result


class TestClassifyIntentTagPath:
    def _fake(self, payload):
        def _q(_s, _u):
            return json.dumps(payload)
        return _q

    def test_no_tags_falls_back_to_closed_subset(self):
        # No needed_tags in LLM output → legacy TOOL_SUBSETS[intent] path.
        result = classify_intent(
            "add a Status column",
            query_fn=self._fake({"intent": "add_field", "confidence": 0.9}),
        )
        assert result.tools == TOOL_SUBSETS["add_field"]
        assert result.needed_tags is None

    def test_tags_present_wins_over_intent_subset(self):
        # LLM emits needed_tags; the derived subset overrides the closed
        # intent-based one.
        result = classify_intent(
            "edit the Save button on the Recipe page",
            query_fn=self._fake({
                "intent": "edit_page",
                "confidence": 0.9,
                "needed_tags": ["edit", "page"],
            }),
        )
        assert result.tools is not None
        assert "edit_page" in result.tools
        # Regression: MAY include tools the closed subset doesn't
        # (verify_promise carries tag "verify", not "edit"/"page", so
        # here we assert only the additive property — the tag subset
        # contains the intent-relevant tools).

    def test_low_confidence_still_falls_back_to_no_scoping(self):
        # Below the confidence floor, tools=None wins regardless of
        # tags — preserves the pre-existing safety property.
        result = classify_intent(
            "meh",
            query_fn=self._fake({
                "intent": "edit_page",
                "confidence": 0.3,
                "needed_tags": ["edit", "page"],
            }),
        )
        assert result.tools is None

    def test_unclear_intent_ignores_tags(self):
        result = classify_intent(
            "?",
            query_fn=self._fake({
                "intent": "unclear",
                "confidence": 0.9,
                "needed_tags": ["edit", "page"],
            }),
        )
        assert result.tools is None

    def test_all_unknown_tags_falls_back_to_closed_subset(self):
        # LLM emits garbage tags → treated as "no tag hint", fall
        # back to closed intent lookup.
        result = classify_intent(
            "add a workflow",
            query_fn=self._fake({
                "intent": "add_workflow",
                "confidence": 0.9,
                "needed_tags": ["nonsense-tag", "also-fake"],
            }),
        )
        assert result.tools == TOOL_SUBSETS["add_workflow"]

    def test_needed_tags_preserved_on_model(self):
        # Even when the tags don't win the derivation, the raw LLM
        # output is preserved on the model so callers can observe /
        # log the mismatch.
        result = classify_intent(
            "add",
            query_fn=self._fake({
                "intent": "add_page",
                "confidence": 0.9,
                "needed_tags": ["add", "page"],
            }),
        )
        assert result.needed_tags == ["add", "page"]

    def test_terminal_only_tag_input_falls_back(self):
        # `chat` alone maps to only terminals → falls back to closed
        # subset so Smith isn't scoped down to just answer/ask.
        result = classify_intent(
            "hi",
            query_fn=self._fake({
                "intent": "chat",
                "confidence": 0.9,
                "needed_tags": ["chat"],
            }),
        )
        assert result.tools == TOOL_SUBSETS["chat"]
