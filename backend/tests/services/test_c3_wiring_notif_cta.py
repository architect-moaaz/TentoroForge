"""Tests for Spec C Slice 3 (part 3) — content_bank wiring into
task_notification_defaults + form_scaffold submit CTA.

Additive: bank=None reproduces the pre-C3 defaults exactly. When bank
is supplied, voice-tuned copy replaces the generic strings.
"""
from __future__ import annotations

from schemas.design_brief import ContentBank
from services.task_notification_defaults import (
    _default_notification_for,
    inject_missing_notifications,
)


HUMAN_STEP = {
    "name": "reviewApplication",
    "node_type": "user_task",
    "config": {"assigneeRole": "reviewer"},
}


class TestDefaultNotificationNoBank:
    def test_generic_subject_and_message(self):
        n = _default_notification_for(HUMAN_STEP, bank=None)
        assert n["config"]["subject"].startswith("Action required:")
        assert "review Application" in n["config"]["subject"]
        assert n["config"]["message"].startswith("A ")
        assert "waiting for you" in n["config"]["message"]
        assert n["config"]["recipientRole"] == "reviewer"


class TestDefaultNotificationWithBank:
    def test_bank_subject_wins(self):
        bank = ContentBank(notifications={
            "task_assigned": "Your queue has a new {task_kind}",
        })
        n = _default_notification_for(HUMAN_STEP, bank=bank)
        assert n["config"]["subject"] == "Your queue has a new review Application"
        # message falls back because approval_needed not set
        assert n["config"]["message"].startswith("A ")

    def test_bank_message_from_approval_key(self):
        bank = ContentBank(notifications={
            "approval_needed": "{entity_singular} awaits your decision",
        })
        n = _default_notification_for(HUMAN_STEP, bank=bank)
        assert n["config"]["message"] == "review Application awaits your decision"

    def test_both_keys_take_precedence(self):
        bank = ContentBank(notifications={
            "task_assigned": "New {task_kind} in queue",
            "approval_needed": "{task_kind} awaiting review",
        })
        n = _default_notification_for(HUMAN_STEP, bank=bank)
        assert "review Application" in n["config"]["subject"]
        assert "review Application" in n["config"]["message"]

    def test_empty_bank_falls_through(self):
        bank = ContentBank()  # no notifications section
        n = _default_notification_for(HUMAN_STEP, bank=bank)
        assert n["config"]["subject"].startswith("Action required:")


class TestInjectMissingNotificationsThreadsBank:
    def test_bank_threads_into_inserted_notification(self):
        bank = ContentBank(notifications={
            "task_assigned": "Voice: {task_kind}",
        })
        plan = {
            "workflows": [{
                "name": "wf",
                "steps": [HUMAN_STEP],
            }],
        }
        result, stats = inject_missing_notifications(plan, return_stats=True, bank=bank)
        assert stats["inserted"] == 1
        # The inserted step (before the human task) carries the voice subject.
        first_step = result["workflows"][0]["steps"][0]
        assert first_step["node_type"] == "send_notification"
        assert first_step["config"]["subject"] == "Voice: review Application"

    def test_no_bank_reproduces_default(self):
        plan = {
            "workflows": [{
                "name": "wf",
                "steps": [HUMAN_STEP],
            }],
        }
        result, _ = inject_missing_notifications(plan, return_stats=True, bank=None)
        first_step = result["workflows"][0]["steps"][0]
        assert first_step["config"]["subject"].startswith("Action required:")


# ─── form_scaffold / build_form_page CTA verb precedence ─────────────

class TestBuildFormPageCtaVerb:
    """Exercise the submit_label branch inside build_form_page. We
    can't run the full form-page build without a lot of fixture state,
    so this test targets a tiny happy path: a minimal columns dict +
    output_dir pointing at a temp brief.json."""

    def test_create_form_uses_cta_verb_when_bank_present(self, tmp_path):
        # Write a minimal brief.json with a create verb.
        import json
        contracts = tmp_path / "contracts"
        contracts.mkdir(parents=True)
        brief = {
            "identity": {"domain": "Test", "register": ["structured"], "voice": "warm_precise"},
            "palette": {
                "brand": "#2D5A8E", "accent": "#E8A020",
                "neutrals_base": "#F5F5F5", "neutrals_tint": "cool",
                "surface_bg": "#FFFFFF", "surface_elevated": "#FFFFFF",
                "foreground_primary": "#111111", "foreground_muted": "#666666",
            },
            "typography": {"display_family": "X", "body_family": "X"},
            "layout": {"density": "compact", "radius": "soft_8"},
            "signature_moves": [{"kind": "warm_serif_h1", "detail": "x"}],
            "content_bank": {"cta_verbs": {"create": "Post"}},
        }
        (contracts / "brief.json").write_text(json.dumps(brief), encoding="utf-8")

        from services.deterministic_pages import build_form_page
        page = build_form_page(
            entity="Article",
            columns={"title": {"type": "text"}},
            route="/articles/new",
            design_spec=None,
            op="create",
            output_dir=str(tmp_path),
        )
        # Find the submit label buried in the root — look at the Form or
        # trailing Button. The label should now be "Post Article".
        root_str = json.dumps(page)
        assert "Post Article" in root_str

    def test_edit_form_uses_save_verb_when_bank_present(self, tmp_path):
        import json
        contracts = tmp_path / "contracts"
        contracts.mkdir(parents=True)
        brief = {
            "identity": {"domain": "Test", "register": ["structured"], "voice": "warm_precise"},
            "palette": {
                "brand": "#2D5A8E", "accent": "#E8A020",
                "neutrals_base": "#F5F5F5", "neutrals_tint": "cool",
                "surface_bg": "#FFFFFF", "surface_elevated": "#FFFFFF",
                "foreground_primary": "#111111", "foreground_muted": "#666666",
            },
            "typography": {"display_family": "X", "body_family": "X"},
            "layout": {"density": "compact", "radius": "soft_8"},
            "signature_moves": [{"kind": "warm_serif_h1", "detail": "x"}],
            "content_bank": {"cta_verbs": {"save": "Publish updates"}},
        }
        (contracts / "brief.json").write_text(json.dumps(brief), encoding="utf-8")

        from services.deterministic_pages import build_form_page
        page = build_form_page(
            entity="Article",
            columns={"title": {"type": "text"}},
            route="/articles/1/edit",
            design_spec=None,
            op="edit",
            output_dir=str(tmp_path),
        )
        assert "Publish updates" in json.dumps(page)

    def test_no_bank_keeps_generic_label(self, tmp_path):
        # No brief.json — should keep the pre-C3 default label.
        import json
        from services.deterministic_pages import build_form_page
        page = build_form_page(
            entity="Article",
            columns={"title": {"type": "text"}},
            route="/articles/new",
            design_spec=None,
            op="create",
            output_dir=str(tmp_path),
        )
        # Generic default: "Create Article"
        assert "Create Article" in json.dumps(page)
