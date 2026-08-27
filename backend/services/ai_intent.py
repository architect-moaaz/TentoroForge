"""Thin completeness guard for chatbot/assistant plans.

The PLANNER designs the conversational app (entities, workflow, chat page) — see
the planner prompt. This is only a safety net: when a plan clearly describes a
chatbot but the planner dropped an *essential* (a message-like entity, an
AI-generation workflow, or a chat page), we backfill a minimal default and LOG
it, so the gap is visible rather than silently papered over. Detection is
lenient — the planner's own naming (ChatMessage, /chat, "Assistant" workflow) is
recognized and left untouched. No chat intent, or planner did its job → no-op.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

_CHAT_KW = (
    "chatbot", "chat bot", "chat assistant", "assistant", "conversational",
    "ai chat", "chat interface", "gpt", "llm chat", "virtual assistant",
    "copilot", "q&a bot", "support bot", "ask ai",
)


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def plan_text(plan: dict) -> str:
    """All the free text in a plan, lowercased — for intent detection."""
    parts = [str(plan.get("module_name", "")), str(plan.get("description", ""))]
    for key in ("pages", "workflows"):
        for it in plan.get(key) or []:
            if isinstance(it, dict):
                parts += [str(it.get("name", "")), str(it.get("description", ""))]
    return " ".join(parts).lower()


def detect_chat_intent(plan: dict) -> bool:
    return isinstance(plan, dict) and any(k in plan_text(plan) for k in _CHAT_KW)


def _has_entity(plan: dict, name: str) -> bool:
    dm = plan.get("data_models")
    if isinstance(dm, list) and any(
        isinstance(m, dict) and str(m.get("name", "")).lower() == name.lower() for m in dm
    ):
        return True
    ent = plan.get("entities")
    return isinstance(ent, dict) and any(k.lower() == name.lower() for k in ent)


def _add_entity(plan: dict, name: str, fields: list[dict]) -> None:
    if _has_entity(plan, name):
        return
    dm = plan.get("data_models")
    if not isinstance(dm, list):
        dm = plan["data_models"] = []
    dm.append({"name": name, "fields": fields})
    ent = plan.get("entities")
    if isinstance(ent, dict):
        ent[name] = {"table": _snake(name) + "s", "fields": fields}


_MESSAGE_FIELDS = [
    {"name": "id", "type": "serial", "primaryKey": True},
    {"name": "conversation_id", "type": "integer", "nullable": False},
    {"name": "role", "type": "varchar(20)", "nullable": False},
    {"name": "content", "type": "text", "nullable": False},
    {"name": "created_at", "type": "timestamp", "nullable": False},
]
_CONVERSATION_FIELDS = [
    {"name": "id", "type": "serial", "primaryKey": True},
    {"name": "title", "type": "varchar(255)", "nullable": True},
    {"name": "user_id", "type": "integer", "nullable": True},
    {"name": "created_at", "type": "timestamp", "nullable": False},
]


def _iter_entities(plan: dict):
    """Yield (name, fields) for every entity, whichever representation is used."""
    for m in plan.get("data_models") or []:
        if isinstance(m, dict) and m.get("name"):
            yield m["name"], (m.get("fields") or [])
    ent = plan.get("entities")
    if isinstance(ent, dict):
        for name, spec in ent.items():
            yield name, ((spec or {}).get("fields") or []) if isinstance(spec, dict) else []


def has_message_entity(plan: dict) -> bool:
    """Lenient: any message/chat-named entity, or one with content + role/thread."""
    for name, fields in _iter_entities(plan):
        low = str(name).lower()
        if "message" in low or "chatmessage" in low or low in ("chat", "post", "turn"):
            return True
        fnames = {str(f.get("name", "")).lower() for f in fields if isinstance(f, dict)}
        if ({"content", "body", "text"} & fnames) and (
            {"role", "sender", "author"} & fnames
            or any("conversation" in n or "thread" in n or "chat" in n for n in fnames)
        ):
            return True
    return False


def has_ai_workflow(plan: dict) -> bool:
    """Any workflow that looks like it generates a reply (→ ai_generate node)."""
    for w in plan.get("workflows") or []:
        if not isinstance(w, dict):
            continue
        blob = (str(w.get("name", "")) + " " + str(w.get("description", "")) + " "
                + " ".join(str(s) for s in (w.get("steps") or []))).lower()
        if any(kw in blob for kw in ("assistant", "reply", "respond", "generate_reply",
                                     "ai_generate", "chat", "answer")):
            return True
    return False


def has_chat_page(plan: dict) -> bool:
    for p in plan.get("pages") or []:
        if not isinstance(p, dict):
            continue
        if str(p.get("route", "")) in ("/chat", "/assistant", "/conversation"):
            return True
        blob = (str(p.get("name", "")) + " " + str(p.get("description", ""))).lower()
        if any(kw in blob for kw in ("chat", "assistant", "conversation", "message thread")):
            return True
    return False


def ensure_assistant_app(plan: dict) -> dict:
    """Thin completeness guard. The planner owns chatbot design; this only
    backfills an ESSENTIAL the planner dropped and records it in the returned
    report. Returns {"intent": bool, "backfilled": [str, ...]}.
    """
    report: dict = {"intent": False, "backfilled": []}
    if not detect_chat_intent(plan):
        return report
    report["intent"] = True

    if not has_message_entity(plan):
        _add_entity(plan, "Conversation", _CONVERSATION_FIELDS)
        _add_entity(plan, "Message", _MESSAGE_FIELDS)
        report["backfilled"].append("entities:Conversation+Message")

    if not has_ai_workflow(plan):
        wf = plan.get("workflows")
        if not isinstance(wf, list):
            wf = plan["workflows"] = []
        wf.append({
            "name": "Assistant Reply",
            "description": "When a user message is created, generate an AI assistant "
                           "reply and save it back to the conversation.",
            "trigger": {"event": "message_created"},
            "steps": ["generate_reply", "insert_reply"],
        })
        report["backfilled"].append("workflow:Assistant Reply")

    if not has_chat_page(plan):
        pages = plan.get("pages")
        if not isinstance(pages, list):
            pages = plan["pages"] = []
        pages.append({
            "route": "/assistant",
            "name": "Assistant",
            "entity": "Message",
            "archetype": "list",
            "features": [],
            "description": "Conversational assistant: a scrolling list of chat messages "
                           "(user + assistant) with a text input pinned at the bottom. "
                           "Sending a message creates a Message and triggers the Assistant "
                           "Reply workflow; the AI response appears as an assistant message.",
        })
        report["backfilled"].append("page:/assistant")

    for item in report["backfilled"]:
        logger.warning(
            "[ai_intent] chatbot plan was missing %s — backfilled a minimal default "
            "(the planner should design this; see the app-design report)", item,
        )
    return report
