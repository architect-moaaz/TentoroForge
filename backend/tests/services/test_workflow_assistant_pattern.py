"""The workflow generator authors an ai_generate node for assistant/chatbot flows."""
import json

from services.workflow_generator import (
    _classify_step,
    _build_step_config,
    _infer_steps_from_name,
    generate_workflow_definitions,
)


# ── classification ──────────────────────────────────────────────────────────
def test_generate_reply_classifies_as_ai_generate():
    assert _classify_step("generate_reply") == "ai_generate"
    assert _classify_step("Generate AI Response") == "ai_generate"
    assert _classify_step("assistant_reply") == "ai_generate"


def test_save_step_is_not_ai_generate():
    # The persistence step must stay a db action, not another LLM call.
    assert _classify_step("insert_reply") != "ai_generate"
    assert _classify_step("save_assistant_message") != "ai_generate"


def test_ordinary_generate_step_unaffected():
    # A non-conversational "generate invoice" must not become an LLM call.
    assert _classify_step("generate_invoice") == "action"


def test_intelligent_steps_map_to_the_right_ai_node():
    assert _classify_step("classify_ticket") == "ai_classify"
    assert _classify_step("categorize_feedback") == "ai_classify"
    assert _classify_step("detect_sentiment") == "ai_classify"
    assert _classify_step("extract_invoice_fields") == "ai_extract"
    assert _classify_step("summarize_document") == "ai_generate"
    assert _classify_step("ai_decide_routing") == "ai_decide"


def test_ai_node_configs_are_well_formed():
    c = _build_step_config("classify_ticket", "ai_classify", {}, {})
    assert "aiLabels" in c and c["aiInput"] == "{{input.content}}"
    e = _build_step_config("extract_fields", "ai_extract", {}, {})
    assert "aiExtractFields" in e
    d = _build_step_config("ai_decide_routing", "ai_decide", {}, {})
    assert d["aiOptions"] == ["approve", "reject"]


# ── config ──────────────────────────────────────────────────────────────────
def test_ai_generate_config_feeds_user_message():
    cfg = _build_step_config("generate_reply", "ai_generate", {"name": "Chatbot"}, {})
    assert cfg["aiInput"] == "{{input.content}}"
    assert "aiPrompt" in cfg and cfg["aiTone"]


# ── step inference ──────────────────────────────────────────────────────────
def test_assistant_workflow_infers_generate_then_save():
    assert _infer_steps_from_name("Chatbot Assistant", "") == ["generate_reply", "insert_reply"]
    assert _infer_steps_from_name("Conversational Reply", "")[0] == "generate_reply"


# ── end-to-end: a plan workflow → a definition with an ai_generate node ──────
def test_generate_definitions_emits_ai_generate_node(tmp_path):
    plan = {
        "data_models": [{"name": "Message"}, {"name": "Conversation"}],
        "workflows": [{
            "name": "Assistant Reply",
            "description": "Generate an assistant reply to the user's message",
            "trigger": {"event": "message_created"},
            "steps": ["generate_reply", "insert_reply"],
        }],
    }
    n = generate_workflow_definitions(str(tmp_path), plan)
    assert n == 1
    wf = json.loads(next((tmp_path / "workflows").glob("*.json")).read_text(encoding="utf-8"))
    nodes = wf["definition"]["nodes"]
    ai = [x for x in nodes if x["type"] == "ai_generate"]
    assert len(ai) == 1
    assert ai[0]["data"]["config"]["aiInput"] == "{{input.content}}"
    # trigger fires on a new message
    assert wf["definition"]["trigger"]["event"] == "message_created"
