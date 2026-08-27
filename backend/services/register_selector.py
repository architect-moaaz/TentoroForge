"""Domain × register selection intelligence.

Picks the most appropriate stylistic register for a project based on the
brief and inferred domain. Two paths:

  - `classify_register(brief, domain)` — sync, rule-based. Domain map +
    keyword hints. Always available, never fails. Used as the fallback for
    the LLM path and as the legacy contract for callers that can't await.

  - `classify_register_llm(brief, domain, plan=None)` — async, Sonnet-based.
    Reasons about the brief, domain, and (optionally) the entity/page plan
    against the documented register affinities; returns one of the six
    valid register names. Falls through to the rule-based classifier when:
      - `ANTHROPIC_API_KEY` is not set
      - the API call fails or times out
      - the response can't be coerced to a valid RegisterName

LLM classification meaningfully unlocks the more distinctive register
variants (Linear / Stripe / Notion / Figma) for apps where the keyword
heuristic falls back to "workday" — a real cost on apps that don't trip
specific keywords but do have a clear stylistic register if you read
the brief.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Literal

logger = logging.getLogger(__name__)

# Hard ceiling — Sonnet typically returns in 1-2s for a single-token-class
# decision. 10s gives auth/cold-start headroom while still bailing on
# stuck calls so the generation pipeline can move forward on the rule-based
# fallback rather than blocking the SSE stream.
_LLM_TIMEOUT_SECONDS = 10.0
_LLM_MODEL = "claude-sonnet-4-6"
_LLM_MAX_TOKENS = 64


RegisterName = Literal["default", "workday", "linear", "stripe", "notion", "figma"]


# Domain × register mapping table — primary affinity per domain.
DOMAIN_REGISTER_MAP: dict[str, RegisterName] = {
    "hr":          "workday",
    "healthcare":  "workday",
    "fintech":     "stripe",
    "finance":     "stripe",
    "payments":    "stripe",
    "saas":        "linear",
    "devtools":    "linear",
    "developer":   "linear",
    "infra":       "linear",
    "monitoring":  "linear",
    "docs":        "notion",
    "wiki":        "notion",
    "knowledge":   "notion",
    "content":     "notion",
    "blog":        "notion",
    "design":      "figma",
    "creative":    "figma",
    "studio":      "figma",
}


# Brief keyword → register hints. Keys are sets of keywords; if ANY keyword
# appears in the brief, the value is the register affinity. Earlier matches
# take precedence (more specific keywords listed first).
KEYWORD_REGISTER_HINTS: list[tuple[tuple[str, ...], RegisterName]] = [
    # HR / corporate admin → Workday
    (("leave management", "performance review", "compensation", "benefits enrollment",
      "human resources", "payroll", "headcount"), "workday"),

    # Finance / payments → Stripe
    (("invoice", "payment", "transaction", "ledger", "settlement", "treasury",
      "billing", "subscription", "revenue", "tax", "fraud"), "stripe"),

    # Dev tools / SaaS → Linear
    (("issue tracker", "bug tracking", "kanban", "sprint", "ci/cd", "deployment",
      "monitoring", "observability", "incident", "logs", "metrics dashboard",
      "kubernetes", "container"), "linear"),

    # Content / docs → Notion
    (("wiki", "documentation", "knowledge base", "blog", "publication", "article",
      "essay", "newsletter", "cms"), "notion"),

    # Design / creative → Figma
    (("design system", "brand guidelines", "moodboard", "asset library",
      "creative review", "portfolio"), "figma"),
]


def classify_register(brief: str, domain: str = "") -> RegisterName:
    """Pick a register from the brief + domain.

    Resolution order:
      1. Explicit domain match in DOMAIN_REGISTER_MAP
      2. Keyword hint in KEYWORD_REGISTER_HINTS
      3. Default to "workday" (broadest enterprise fallback)
    """
    brief_l = (brief or "").lower()
    domain_l = (domain or "").lower().strip()

    # Step 1: domain match
    if domain_l in DOMAIN_REGISTER_MAP:
        return DOMAIN_REGISTER_MAP[domain_l]

    # Step 2: keyword hints (most specific first)
    for keywords, register in KEYWORD_REGISTER_HINTS:
        if any(k in brief_l for k in keywords):
            return register

    # Step 3: default
    return "workday"


def list_registers() -> list[RegisterName]:
    """All available registers."""
    return ["default", "workday", "linear", "stripe", "notion", "figma"]


async def classify_register_llm(
    brief: str,
    domain: str = "",
    plan: dict | None = None,
) -> RegisterName:
    """Pick a register via Sonnet. Falls through to the rule-based classifier
    on any failure (no API key, parse error, timeout, invalid response).

    `plan` is optional; when present, the entity/page list is included in the
    prompt so the model can factor data-density and workflow shape into the
    decision.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not brief.strip():
        return classify_register(brief, domain)

    prompt = _build_register_prompt(brief, domain, plan)
    try:
        text = await asyncio.wait_for(
            _call_anthropic(api_key, prompt),
            timeout=_LLM_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("register_selector.llm: timeout after %.1fs — falling back to rules", _LLM_TIMEOUT_SECONDS)
        return classify_register(brief, domain)
    except Exception as e:  # noqa: BLE001 — auth, network, billing, etc.
        logger.warning("register_selector.llm: API failure (%s) — falling back to rules", e)
        return classify_register(brief, domain)

    chosen = _coerce_register_name(text)
    if chosen is None:
        logger.warning(
            "register_selector.llm: could not coerce response to a valid register "
            "(first 80 chars: %r) — falling back to rules",
            text[:80],
        )
        return classify_register(brief, domain)
    logger.info("register_selector.llm: chose '%s' for brief=%r domain=%r", chosen, brief[:60], domain)
    return chosen


def _build_register_prompt(brief: str, domain: str, plan: dict | None) -> str:
    """Render the user prompt. Pins the model to one of six valid names by
    listing them with brief stylistic descriptions, then asks for a single
    word answer."""
    plan_summary = ""
    if plan:
        entities = plan.get("entities") or {}
        if isinstance(entities, dict):
            entity_names = list(entities.keys())[:8]
        elif isinstance(entities, list):
            entity_names = [
                e.get("name", "?") if isinstance(e, dict) else str(e)
                for e in entities[:8]
            ]
        else:
            entity_names = []
        if entity_names:
            plan_summary = f"\nEntities: {', '.join(entity_names)}"

    return (
        "Choose the single best stylistic register for this application from "
        "these six options. Reply with ONLY the register name — no punctuation, "
        "no explanation, no markdown. Lowercase.\n\n"
        "Registers:\n"
        "  workday — corporate enterprise, dense data, navy primary, structured grays. "
        "HR, healthcare, ops, approval-heavy workflows.\n"
        "  linear  — monochrome neutral, sharp, single accent. SaaS / dev tools, "
        "issue tracking, command palettes, keyboard-driven.\n"
        "  stripe  — two-tone gradient hero, layered shadows. Fintech / payments / "
        "billing / treasury / fraud / reporting dashboards.\n"
        "  notion  — soft, airy, content-first. Wikis, docs, knowledge bases, blogs, "
        "CMS, internal handbooks.\n"
        "  figma   — vibrant, friendly, playful. Design tools, asset libraries, "
        "moodboards, brand systems, creative review.\n"
        "  default — neutral shadcn — only when none of the above fit and the app "
        "is genuinely generic.\n\n"
        f"Brief: {brief.strip()}\n"
        f"Domain: {domain or '(not specified)'}"
        f"{plan_summary}\n\n"
        "Register:"
    )


async def _call_anthropic(api_key: str, prompt: str) -> str:
    """Single Anthropic HTTP call. Same shape as `services/fixtures/llm_gen.py`
    — direct httpx-based SDK, no subprocess. Lazy import so this module
    stays loadable in environments without `anthropic` installed."""
    from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim

    client = llm_client.AsyncAnthropic(api_key=api_key)
    message = await client.messages.create(
        model=_LLM_MODEL,
        max_tokens=_LLM_MAX_TOKENS,
        system=(
            "You are a UI register classifier. You output exactly one word "
            "from a fixed list — no punctuation, no commentary."
        ),
        messages=[{"role": "user", "content": prompt}],
    )
    parts: list[str] = []
    for block in message.content:
        if hasattr(block, "text"):
            parts.append(block.text)
    return "".join(parts)


_VALID_REGISTERS: frozenset[str] = frozenset(
    ("default", "workday", "linear", "stripe", "notion", "figma")
)


def _coerce_register_name(text: str) -> RegisterName | None:
    """Extract a valid register name from the LLM response.

    Sonnet usually returns the bare word, but defensively we strip whitespace,
    punctuation, and surrounding markdown, then look for the first match
    against the valid set. Returns None if nothing matches.
    """
    if not text:
        return None
    cleaned = text.strip().lower()
    # Sometimes the model wraps the answer in quotes/backticks/period.
    cleaned = re.sub(r"^[`'\"\s]+|[`'\".\s]+$", "", cleaned)
    if cleaned in _VALID_REGISTERS:
        return cleaned  # type: ignore[return-value]
    # Fallback: scan tokens for the first valid register word.
    for token in re.findall(r"[a-z]+", cleaned):
        if token in _VALID_REGISTERS:
            return token  # type: ignore[return-value]
    return None


def describe_register(name: RegisterName) -> str:
    """Human-readable description for the editor / docs."""
    descriptions = {
        "default":  "neutral shadcn-default",
        "workday":  ("corporate enterprise — dense data, navy primary, structured grays. "
                     "Heavy use of DataGrid + ApprovalStepper + Timeline + KeyValueList. "
                     "Approval flows feature parallel approvers + delegation."),
        "linear":   ("monochrome neutral, sharp, single accent — SaaS / dev tools. "
                     "Heavy use of CommandPalette + DataGrid (compact) + Sparkline. "
                     "Workflows are lightweight; emphasis on keyboard navigation."),
        "stripe":   ("two-tone with gradient hero, layered shadows — fintech / payments. "
                     "Heavy use of Chart + DataGrid + InspectorPanel for transaction detail. "
                     "Reporting dashboards prominent."),
        "notion":   ("soft, airy, content-first — wikis / docs / knowledge bases. "
                     "Heavy use of Section/Card composition; minimal DataGrid; "
                     "TabPanelWithDeepLink common for sectioned content."),
        "figma":    ("vibrant, friendly, playful — design tools / creative apps. "
                     "Heavy use of FeatureCard + EmptyStateRich; minimal data tables."),
    }
    return descriptions.get(name, "unknown register")
