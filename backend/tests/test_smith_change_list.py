"""Tests for the concrete change-list + overclaim guard.

Failure mode this fixes: Smith says "Done! I did 5 things" when only 2
of the 5 claimed changes actually appear in the new schema.

Two moving parts:
  1. compute_change_list() must produce a truthful diff of pre/post
     schemas — only entries backed by real value differences.
  2. _answer_overclaims_edit() must refuse "Done! 1, 2, 3, 4, 5" when
     the change_list has fewer real entries.
"""

from __future__ import annotations

import pytest

from services.llm_edit import compute_change_list, summarize_change_list
from agents.smith_agent import (
    _count_answer_claims,
    _last_edit_page_changes,
    _answer_overclaims_edit,
)


# --------------------------------------------------------------------------- #
# compute_change_list                                                          #
# --------------------------------------------------------------------------- #

class TestComputeChangeList:
    def test_identical_yields_empty(self):
        s = {"a": 1, "b": [1, 2]}
        assert compute_change_list(s, s) == []

    def test_detects_text_change_on_content_prop(self):
        pre = {"root": {"props": {"content": "Users"}}}
        post = {"root": {"props": {"content": "Recruiters"}}}
        changes = compute_change_list(pre, post)
        assert len(changes) == 1
        c = changes[0]
        assert c["kind"] == "text-changed"
        assert c["from"] == "Users"
        assert c["to"] == "Recruiters"

    def test_detects_added_key(self):
        pre = {"dataSources": [{"name": "users"}]}
        post = {"dataSources": [{"name": "users", "filter": {"role": "recruiter"}}]}
        changes = compute_change_list(pre, post)
        assert any(
            c["kind"] == "added" and c["value"] == {"role": "recruiter"}
            for c in changes
        )

    def test_detects_removed_key(self):
        pre = {"a": {"legacy": True, "keep": 1}}
        post = {"a": {"keep": 1}}
        changes = compute_change_list(pre, post)
        assert any(c["kind"] == "removed" for c in changes)

    def test_five_intended_but_two_actual_produces_two(self):
        # Simulates the live recruitment app failure:
        # tester asked for 5 things, only 2 landed.
        pre = {
            "root": {
                "children": [
                    {"type": "Heading", "props": {"content": "Users"}},
                    {"type": "Button",  "props": {"label": "Create User",
                                                    "navigate": "/recruiters/new"}},
                    {"type": "Link",    "props": {"label": "View details",
                                                    "navigate": "/recruiters"}},
                ],
            },
            "dataSources": [
                {"name": "users", "entity": "User", "op": "list"},
            ],
        }
        # Two changes applied: dataSource name + filter.
        post = {
            "root": {
                "children": [
                    {"type": "Heading", "props": {"content": "Users"}},  # unchanged
                    {"type": "Button",  "props": {"label": "Create User",
                                                    "navigate": "/recruiters/new"}},  # unchanged
                    {"type": "Link",    "props": {"label": "View details",
                                                    "navigate": "/recruiters"}},  # unchanged
                ],
            },
            "dataSources": [
                {"name": "recruiters", "entity": "User", "op": "list",
                 "filter": {"role": "recruiter"}},
            ],
        }
        changes = compute_change_list(pre, post)
        concrete = [c for c in changes if c["kind"] != "truncated"]
        # 2 real changes: name text-changed + filter added.
        assert len(concrete) == 2
        assert sum(1 for c in concrete if c["kind"] == "text-changed") == 1
        assert sum(1 for c in concrete if c["kind"] == "added") == 1

    def test_summary_reads_naturally(self):
        changes = [
            {"kind": "text-changed", "at": "x"},
            {"kind": "text-changed", "at": "y"},
            {"kind": "added", "at": "z"},
        ]
        s = summarize_change_list(changes)
        assert "text change" in s
        assert "addition" in s

    def test_truncation_marker(self):
        # 60+ node changes → truncated marker appears.
        pre = {f"k{i}": i for i in range(80)}
        post = {f"k{i}": i * 2 for i in range(80)}
        changes = compute_change_list(pre, post)
        assert changes[-1]["kind"] == "truncated"


# --------------------------------------------------------------------------- #
# _count_answer_claims                                                        #
# --------------------------------------------------------------------------- #

class TestCountAnswerClaims:
    def test_numbered_list_counts_items(self):
        text = (
            "Done! Here's what was fixed:\n"
            "1. Renamed the heading\n"
            "2. Added a filter\n"
            "3. Fixed the button label\n"
            "4. Fixed the link"
        )
        assert _count_answer_claims(text) == 4

    def test_bulleted_list_counts(self):
        text = "- one\n- two\n- three"
        assert _count_answer_claims(text) == 3

    def test_prose_reply_counts_as_one(self):
        text = "Done. I renamed the heading to Recruiters."
        assert _count_answer_claims(text) == 1

    def test_empty_zero(self):
        assert _count_answer_claims("") == 0
        assert _count_answer_claims("   ") == 0


# --------------------------------------------------------------------------- #
# _answer_overclaims_edit                                                     #
# --------------------------------------------------------------------------- #

class TestAnswerOverclaimsEdit:
    def _trace_with_edit(self, changes: list[dict]) -> list[dict]:
        return [
            {"tool": "understand_ask", "result_summary": "..."},
            {
                "tool": "edit_page",
                "result_summary": "edit_page applied",
                "changes": changes,
            },
            {"tool": "verify_promise", "result_summary": "verified"},
        ]

    def test_overclaim_five_vs_two_flagged(self):
        # Answer enumerates 5 claims; last edit_page produced 2 concrete
        # changes. Guard fires.
        trace = self._trace_with_edit([
            {"kind": "text-changed", "at": "root.dataSources[0].name",
             "from": "users", "to": "recruiters"},
            {"kind": "added", "at": "root.dataSources[0].filter",
             "value": {"role": "recruiter"}},
        ])
        answer = (
            "Done! I fixed:\n"
            "1. Heading text\n"
            "2. Filter\n"
            "3. dataSource name\n"
            "4. Button label\n"
            "5. Link"
        )
        result = _answer_overclaims_edit(trace, answer)
        assert result is not None
        claim_count, change_count, changes = result
        assert claim_count == 5
        assert change_count == 2

    def test_exact_match_ok(self):
        # Answer enumerates 3 claims, edit_page produced 3 changes.
        # No overclaim → guard silent.
        trace = self._trace_with_edit([
            {"kind": "text-changed", "at": "a"},
            {"kind": "text-changed", "at": "b"},
            {"kind": "added", "at": "c"},
        ])
        answer = (
            "Done!\n"
            "1. Fixed a\n"
            "2. Fixed b\n"
            "3. Added c"
        )
        assert _answer_overclaims_edit(trace, answer) is None

    def test_short_prose_answer_falls_through(self):
        # Prose "Done!" reply — one implicit claim. Not caught by this
        # guard (it targets the numbered-list overclaim class).
        trace = self._trace_with_edit([])
        answer = "Done!"
        assert _answer_overclaims_edit(trace, answer) is None

    def test_no_edit_page_returns_none(self):
        # If Smith never called edit_page, this guard doesn't apply.
        # (Different guard — the mutation-intent one — handles that.)
        trace = [{"tool": "read_page", "result_summary": "..."}]
        answer = "1. one\n2. two\n3. three"
        assert _answer_overclaims_edit(trace, answer) is None
