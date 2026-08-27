"""Tests for the deploy-intent guard on the ``answer`` terminal.

Failure mode this fixes:
  User: "deploy the app"
  Smith: "the publish call hit a transient server-side loop error.
          Please click the Publish button in the toolbar..."

Smith fabricates the error message and punts to the human. The guard
refuses ``answer`` when the user asked to deploy but no ``publish`` tool
call landed in the trace.
"""

from __future__ import annotations

from agents.smith_agent import (
    _EFFECT_TOOLS,
    _is_deploy_intent,
)


class TestDeployIntent:
    def test_bare_deploy_the_app(self):
        assert _is_deploy_intent("deploy the app") is True

    def test_publish_synonym(self):
        assert _is_deploy_intent("publish it to vercel") is True

    def test_ship_synonym(self):
        assert _is_deploy_intent("ship the current version") is True

    def test_release_synonym(self):
        assert _is_deploy_intent("release the app to prod") is True

    def test_question_about_prior_deploy_is_not_intent(self):
        # "did you deploy it?" refers to a prior turn — asking, not asking-for.
        assert _is_deploy_intent("did you deploy it?") is False

    def test_unrelated_edit_ask_is_not_deploy(self):
        assert _is_deploy_intent("remove the Department field") is False

    def test_empty_string(self):
        assert _is_deploy_intent("") is False

    def test_none_type_safe(self):
        assert _is_deploy_intent(None) is False  # type: ignore[arg-type]


class TestEffectToolSet:
    def test_publish_is_effect_tool(self):
        assert "publish" in _EFFECT_TOOLS

    def test_edit_page_is_not_effect_tool(self):
        # edit_page belongs to _MUTATING_TOOLS, not _EFFECT_TOOLS.
        assert "edit_page" not in _EFFECT_TOOLS
