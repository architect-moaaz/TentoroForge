"""Thin chatbot completeness guard: planner-led, only backfills missing essentials."""
from services.ai_intent import (
    detect_chat_intent, ensure_assistant_app,
    has_message_entity, has_ai_workflow, has_chat_page,
)


def test_detects_chat_intent_from_description():
    assert detect_chat_intent({"description": "A customer support chatbot"})
    assert detect_chat_intent({"module_name": "AI Assistant"})
    assert detect_chat_intent({"pages": [{"name": "Conversational helper"}]})


def test_no_chat_intent_for_plain_crud():
    assert not detect_chat_intent({"description": "An order management system", "pages": []})


# ── the guard backfills only what's missing, and reports it ─────────────────
def test_backfills_all_when_planner_dropped_everything():
    plan = {"module_name": "Support Chatbot", "data_models": [], "workflows": [], "pages": []}
    report = ensure_assistant_app(plan)
    assert report["intent"] is True
    assert set(report["backfilled"]) == {
        "entities:Conversation+Message", "workflow:Assistant Reply", "page:/assistant"}
    names = {m["name"] for m in plan["data_models"]}
    assert {"Conversation", "Message"} <= names


def test_noop_when_planner_designed_it_leniently():
    # Planner used its OWN names — the guard must recognise them and stay silent.
    plan = {
        "description": "a chatbot",
        "data_models": [{"name": "ChatMessage", "fields": [
            {"name": "content"}, {"name": "sender"}, {"name": "conversation_id"}]}],
        "workflows": [{"name": "Answer User", "steps": ["generate_reply"]}],
        "pages": [{"route": "/chat", "name": "Chat"}],
    }
    report = ensure_assistant_app(plan)
    assert report["intent"] is True
    assert report["backfilled"] == []                 # nothing imposed
    assert [m["name"] for m in plan["data_models"]] == ["ChatMessage"]


def test_partial_backfill_only_missing_piece():
    # Planner made the entity + page but forgot the AI workflow.
    plan = {
        "description": "virtual assistant",
        "data_models": [{"name": "Message", "fields": []}],
        "workflows": [],
        "pages": [{"route": "/assistant", "name": "Assistant"}],
    }
    report = ensure_assistant_app(plan)
    assert report["backfilled"] == ["workflow:Assistant Reply"]


def test_noop_and_empty_report_for_non_chat():
    plan = {"description": "inventory tracker", "data_models": [{"name": "Item", "fields": []}]}
    report = ensure_assistant_app(plan)
    assert report == {"intent": False, "backfilled": []}
    assert [m["name"] for m in plan["data_models"]] == ["Item"]


# ── lenient detectors ───────────────────────────────────────────────────────
def test_has_message_entity_recognizes_variants():
    assert has_message_entity({"data_models": [{"name": "ChatMessage", "fields": []}]})
    assert has_message_entity({"data_models": [{"name": "Post", "fields": [
        {"name": "body"}, {"name": "author"}]}]})
    assert not has_message_entity({"data_models": [{"name": "Invoice", "fields": []}]})


def test_has_ai_workflow_and_chat_page():
    assert has_ai_workflow({"workflows": [{"name": "Answer", "steps": ["generate_reply"]}]})
    assert not has_ai_workflow({"workflows": [{"name": "Approve Order", "steps": ["review"]}]})
    assert has_chat_page({"pages": [{"route": "/conversation"}]})
    assert has_chat_page({"pages": [{"name": "Assistant", "description": "chat thread"}]})
    assert not has_chat_page({"pages": [{"route": "/orders"}]})
