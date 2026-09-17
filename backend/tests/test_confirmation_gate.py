"""Tests for the destructive-action confirmation gate (Phase 1a)."""

from __future__ import annotations

import pytest

from services.confirmation_gate import (
    build_impact_summary,
    needs_confirmation_result,
    parse_confirmation_reply,
)


# --------------------------------------------------------------------------- #
# parse_confirmation_reply                                                    #
# --------------------------------------------------------------------------- #

class TestParseConfirmation:
    @pytest.mark.parametrize("msg", [
        "yes",
        "yes please",
        "Yes",
        "yep",
        "yeah go ahead",
        "confirm",
        "go ahead",
        "proceed",
        "do it",
        "remove it",
        "okay",
        "ok",
        "sure",
    ])
    def test_yes_variants(self, msg):
        assert parse_confirmation_reply(msg) == "yes"

    @pytest.mark.parametrize("msg", [
        "no",
        "nope",
        "nah",
        "cancel",
        "abort",
        "actually no",
        "don't remove that",
        "dont delete",
        "never mind",
        "forget it",
        "keep it",
    ])
    def test_no_variants(self, msg):
        assert parse_confirmation_reply(msg) == "no"

    def test_no_wins_over_yes_when_both_present(self):
        # "yes but no thanks" is ambiguous — NO wins for safety.
        assert parse_confirmation_reply("yes but actually no thanks") == "no"

    def test_unclear_prose(self):
        assert parse_confirmation_reply("hmm let me think") == "unclear"
        assert parse_confirmation_reply("what does that even mean") == "unclear"

    def test_empty_and_whitespace(self):
        assert parse_confirmation_reply("") == "unclear"
        assert parse_confirmation_reply("   ") == "unclear"

    def test_non_string_safe(self):
        assert parse_confirmation_reply(None) == "unclear"  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# build_impact_summary + needs_confirmation_result                            #
# --------------------------------------------------------------------------- #

class TestImpactSummary:
    def test_bare_target_no_dependents(self):
        s = build_impact_summary("page", "Pricing")
        assert "Pricing" in s
        assert "yes" in s.lower() and "no" in s.lower()

    def test_lists_dependents(self):
        s = build_impact_summary(
            "page", "Home",
            dependents=["nav edge Home→About", "form contact.submit"],
        )
        assert "2 thing" in s or "2 things" in s
        assert "nav edge Home→About" in s
        assert "form contact.submit" in s

    def test_truncates_long_dependent_list(self):
        deps = [f"dep-{i}" for i in range(25)]
        s = build_impact_summary("entity", "User", dependents=deps)
        assert "25 thing" in s
        assert "…and 15 more" in s


class TestNeedsConfirmationResult:
    def test_shape(self):
        r = needs_confirmation_result("page", "Pricing", dependents=["nav"])
        assert r["status"] == "needs_confirmation"
        assert r["kind"] == "page"
        assert r["target"] == "Pricing"
        assert r["dependents"] == ["nav"]
        assert "Pricing" in r["summary"]


# --------------------------------------------------------------------------- #
# The question has to reach the user                                          #
# --------------------------------------------------------------------------- #

class TestTheQuestionReachesTheUser:
    """A gate nobody can pass is not a safe gate; it is a broken feature that
    looks like one. S24-8 said that about a marker the model was never told to
    emit. The same thing was true of `remove_page` from the other side, and
    for longer: it is a mutating tool, so `answer` was refused as an unverified
    edit — on the turn where the tool deliberately wrote NOTHING and answering
    IS the question. The prompt never reached the user, the turn died at the
    iteration cap, and the permission could not be granted because it could not
    be asked for.

    These drive the real loop rather than the helpers, because every piece of
    it was individually correct while the thing they add up to did not work.
    """

    @staticmethod
    def _out(tmp_path):
        import json
        (tmp_path / "contracts").mkdir()
        (tmp_path / "contracts" / "resource-registry.json").write_text(json.dumps({
            "entities": [], "relationships": [], "roles": [], "interactions": [],
        }))
        return str(tmp_path)

    @staticmethod
    def _canned(*steps):
        def _fn(system_prompt, messages, tool_catalog):
            for step in steps:
                yield step
        return _fn

    @pytest.fixture()
    def asking_remove_page(self, monkeypatch):
        from services import smith_tools
        calls: list[dict] = []

        def _stub(output_dir, args):
            calls.append(dict(args))
            if args.get("_confirmed"):
                return {"applied": True, "edited_paths": ["src/app/x/page.tsx"],
                        "diff_summary": "/x is gone"}
            return needs_confirmation_result(
                "page", "/x", ["the Wards link in the sidebar"])

        monkeypatch.setitem(smith_tools.READONLY_HANDLERS, "remove_page", _stub)
        return calls

    def test_the_prompt_is_not_refused_as_an_unverified_edit(self, tmp_path, asking_remove_page):
        from agents import smith_agent
        from services.confirmation_gate import CONFIRMATION_PROMPT_MARKER

        asks = needs_confirmation_result("page", "/x", ["the Wards link in the sidebar"])
        result = smith_agent.run_smith_agent(
            "delete the /x page", self._out(tmp_path), recall_block="", memory_block="",
            query_fn=self._canned(
                {"tool": "understand_ask", "args": {"verb": "remove_page", "route": "/x"}},
                {"tool": "remove_page", "args": {"route": "/x"}},
                {"tool": "answer", "args": {"text": asks["summary"]}},
            ),
        )
        assert CONFIRMATION_PROMPT_MARKER in (result["answer"] or "")
        assert result["question"] is None          # NOT the forced ask_user
        assert not any("refused" in (t.get("result_summary") or "")
                       for t in result["trace"])
        assert result["pending_confirmation"] == {
            "tool": "remove_page", "kind": "page", "target": "/x", "cascade": False}

    def test_a_paraphrase_is_refused_because_the_yes_would_not_be_honoured(
            self, tmp_path, asking_remove_page):
        """The marker is matched verbatim, so a prompt that drops so much as a
        comma leaves the user's "yes" with nothing to attach to. Refusing the
        answer is what stops that turn from looking like it asked."""
        from agents import smith_agent

        result = smith_agent.run_smith_agent(
            "delete the /x page", self._out(tmp_path), recall_block="", memory_block="",
            query_fn=self._canned(
                {"tool": "understand_ask", "args": {"verb": "remove_page", "route": "/x"}},
                {"tool": "remove_page", "args": {"route": "/x"}},
                {"tool": "answer", "args": {
                    "text": "About to remove **page: /x**.\n\n"
                            "Reply **yes** to proceed or **no** to cancel."}},
                {"tool": "answer", "args": {
                    "text": needs_confirmation_result("page", "/x")["summary"]}},
            ),
        )
        refused = [t for t in result["trace"]
                   if "unrelayed confirmation" in (t.get("result_summary") or "")]
        assert len(refused) == 1

    def test_the_page_removal_is_granted_end_to_end(self, tmp_path, asking_remove_page):
        from agents import smith_agent

        asks = needs_confirmation_result("page", "/x", ["the Wards link in the sidebar"])
        result = smith_agent.run_smith_agent(
            "yes", self._out(tmp_path), recall_block="", memory_block="",
            prior_messages=[{"role": "assistant", "content": asks["summary"]}],
            pending_confirmation={"tool": "remove_page", "kind": "page",
                                  "target": "/x", "cascade": False},
            query_fn=self._canned(
                {"tool": "understand_ask", "args": {"verb": "remove_page", "route": "/x"}},
                {"tool": "remove_page", "args": {"route": "/x", "_confirmed": True}},
                {"tool": "run_guards", "args": {}},
                {"tool": "answer", "args": {"text": "Removed /x."}},
            ),
        )
        assert asking_remove_page[-1].get("_confirmed") is True
        assert result["answer"] == "Removed /x."
        assert result["edited_paths"] == ["src/app/x/page.tsx"]
