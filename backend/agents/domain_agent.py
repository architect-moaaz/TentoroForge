"""Domain Agent — produces structured domain context for downstream agents.

Replaces the curated `backend/knowledge/<domain>/*` folder. Given a project
description (and optional plan), produces a dossier covering persona blocks
per agent role, design patterns with citations, visual language tendencies,
entity suggestions, compliance notes, and common pitfalls.

The output is a dict that `services.domain_context.build_domain_profile`
consumes to render the per-agent `[DOMAIN PROFILE]` block injected into
each downstream agent's system prompt.

Uses the direct `anthropic.AsyncAnthropic` SDK so the server-side
`web_search` tool can be attached for grounded research. The model decides
when to search; results flow back inline before the final JSON is emitted.

Naming: this lives at `agents/domain_agent.py` to avoid colliding with the
existing `agents/discovery.py` (which handles multi-turn requirements
gathering for vague user prompts — a different concern).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError


# ── Output schema ───────────────────────────────────────────────────────────


class DesignPattern(BaseModel):
    name: str = Field(..., description="Short name of the pattern.")
    description: str = Field(..., description="One-sentence description.")
    evidence: list[str] = Field(
        default_factory=list,
        description=(
            "URLs or named real-world examples supporting this pattern. "
            "Use 'training_data' as a marker if the model recalls the pattern "
            "from training but didn't web-search a specific source."
        ),
    )


class EntitySuggestion(BaseModel):
    name: str
    likelyFields: list[str] = Field(default_factory=list)


class FormPattern(BaseModel):
    pattern: str
    contexts: list[str] = Field(default_factory=list)


class ColorAnchors(BaseModel):
    """Concrete hex codes grounding the paletteCharacter description.

    The discovery agent picks these from its web research — typically by
    sampling colours of real brand examples in the researched domain. They
    become the anchor passed to `services.color_theory.derive_palette()`
    so the generated app's palette actually expresses the researched
    paletteCharacter instead of falling back to generic SaaS defaults.
    """
    primary: str = Field(
        default="",
        description="Hex (#RRGGBB) for the dominant brand colour. Grounded in researched examples.",
    )
    secondary: str = Field(
        default="",
        description="Hex (#RRGGBB) for the supporting/complementary colour.",
    )
    accent: str = Field(
        default="",
        description="Hex (#RRGGBB) for the accent/highlight colour used sparingly.",
    )


class VisualLanguage(BaseModel):
    paletteCharacter: str = Field(
        default="",
        description="warm | cool | neutral | bold (free-string but constrained by prompt).",
    )
    colorAnchors: ColorAnchors = Field(
        default_factory=ColorAnchors,
        description=(
            "Concrete hex codes grounding the paletteCharacter. The "
            "downstream design + industry-fallback paths read primary "
            "here BEFORE falling back to keyword-anchor tables, so two "
            "apps in the same domain with different paletteCharacters get "
            "visibly different palettes."
        ),
    )
    typographyTone: str = Field(
        default="",
        description="editorial | technical | playful | corporate.",
    )
    fontFamily: str = Field(
        default="",
        description=(
            "Concrete CSS font-family stack expressing typographyTone. "
            "Examples: 'Playfair Display, Georgia, serif' (editorial), "
            "'JetBrains Mono, monospace' (technical), 'Manrope, sans-serif' "
            "(modern SaaS). Empty string falls back to 'Inter, system-ui, "
            "sans-serif' downstream."
        ),
    )
    densityPreference: str = Field(
        default="",
        description="compact | comfortable | airy.",
    )


class Personas(BaseModel):
    """Per-agent persona strings. Keys MUST match the role parameter that
    `services.domain_context.build_domain_profile(domain_ctx, role)` is
    called with — those follow the *_agent / *_designer / *_writer /
    *_builder / *_assembler / *_tester suffix conventions established in
    services/domain_context.py. Adding new keys is safe; renaming or
    removing existing ones is not.

    Roles confirmed by grep over backend/agents/*.py:
      planner, contract_writer, schema_designer, auth_agent, api_generator,
      business_logic, component_builder, page_assembler, qa_tester.

    Plus a few keys added for symmetry with future consumers
    (design_agent, shell_layout_agent, default fallback).
    """
    planner: str = ""
    contract_writer: str = ""
    schema_designer: str = ""
    auth_agent: str = ""
    api_generator: str = ""
    business_logic: str = ""
    component_builder: str = ""
    page_assembler: str = ""
    qa_tester: str = ""
    # Forward-looking — added for design / shell / fallback symmetry.
    design: str = ""
    shell: str = ""
    default: str = ""


class DiscoveryOutput(BaseModel):
    """Strict output schema for the domain agent.

    Every downstream agent reads from this. Keep it stable — additive
    changes are fine, breaking renames cascade through every agent's
    prompt template.
    """
    domain: str = Field(..., description="Short canonical domain label (e.g., 'Hospitality').")
    domainAliases: list[str] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    description: str = ""

    personas: Personas = Field(default_factory=Personas)

    designPatterns: list[DesignPattern] = Field(default_factory=list)
    visualLanguage: VisualLanguage = Field(default_factory=VisualLanguage)
    entitySuggestions: list[EntitySuggestion] = Field(default_factory=list)
    formPatterns: list[FormPattern] = Field(default_factory=list)

    complianceNotes: list[str] = Field(
        default_factory=list,
        description=(
            "Compliance regimes that apply. Strict enum: none, hipaa, pci, "
            "gdpr, sox, fda, ferpa, ada-wcag. Values outside this set are "
            "rejected at validation time."
        ),
    )

    commonPitfalls: list[str] = Field(default_factory=list, max_length=8)
    uncertainAreas: list[str] = Field(default_factory=list)

    # Provenance — set by the agent, not the LLM. Helps debug post-hoc.
    source: str = "domain_agent"
    searchedWeb: bool = False
    model: str = ""
    elapsedSeconds: float = 0.0


_ALLOWED_COMPLIANCE = {
    "none", "hipaa", "pci", "gdpr", "sox", "fda", "ferpa", "ada-wcag",
}


# ── Prompt ──────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = r"""You are a domain research agent. Given a project description,
produce a structured dossier of domain knowledge that downstream code-generation
agents will use to bias their output.

You have access to a web_search tool. USE IT for unfamiliar or niche domains —
read 2-3 real product examples before emitting design patterns. Cite the URLs
in the `evidence` field. For well-known domains (e-commerce, HR, healthcare,
fintech), training-data knowledge is acceptable; mark `evidence: ["training_data"]`
on those patterns.

## Output format

Emit ONE JSON object that conforms to this schema. No prose before or after.
First char must be `{`, last char must be `}`. Do not wrap in code fences.

```jsonschema
{
  "domain":         "<short canonical label like 'Hospitality' or 'Healthcare'>",
  "domainAliases":  ["<synonyms — used for matching, e.g. 'hotel', 'travel'>"],
  "confidence":     0.85,   /* REPLACE — self-assess honestly, 0.0-1.0. See rubric below. Do NOT copy this literal 0.85. */
  "description":    "<one-line refined description of the app>",

  "personas": {
    "planner":           "<persona block for the planner agent — 2-3 sentences>",
    "contract_writer":   "<persona block for the contracts agent — entities + domain language>",
    "schema_designer":   "<persona block for the schema agent — DB relations + indexes>",
    "auth_agent":        "<persona block for the auth agent — flows + MFA + compliance>",
    "api_generator":     "<persona block for the API agent — endpoints + auth + filters>",
    "business_logic":    "<persona block for business logic / workflow handlers>",
    "component_builder": "<persona block for the component agent (LLM-TSX mode)>",
    "page_assembler":    "<persona block for the page-schema agent — layouts + UX>",
    "qa_tester":         "<persona block for the QA agent — what to check>",
    "design":            "<persona block for the design agent — visual / brand tone>",
    "shell":             "<persona block for the shell layout agent — nav patterns>",
    "default":           "<fallback persona used when no role-specific one matches>"
  },

  "designPatterns": [
    {"name": "...", "description": "...", "evidence": ["<url>" | "training_data"]}
  ],

  "visualLanguage": {
    "paletteCharacter":  "<short phrase: warm earth tones | clinical blue-whites | luxurious deep jewels | etc>",
    "colorAnchors": {
      "primary":   "#RRGGBB — dominant brand colour, grounded in researched examples",
      "secondary": "#RRGGBB — supporting/complementary colour",
      "accent":    "#RRGGBB — accent/highlight, used sparingly"
    },
    "typographyTone":    "<editorial | technical | playful | corporate>",
    "fontFamily":        "<concrete CSS font-family stack expressing the tone — see rule #6>",
    "densityPreference": "<compact | comfortable | airy>"
  },

  "entitySuggestions": [
    {"name": "EntityName", "likelyFields": ["field1", "field2"]}
  ],

  "formPatterns": [
    {"pattern": "<short name>", "contexts": ["<where this form appears>"]}
  ],

  "complianceNotes": ["<one of: none, hipaa, pci, gdpr, sox, fda, ferpa, ada-wcag>"],

  "commonPitfalls": ["<short pitfall description>", "..."],  // AT MOST 8, highest-signal first

  "uncertainAreas": ["<list things you weren't sure about — better to flag than invent>"]
}
```

## Rules

1. **Be precise about compliance.** complianceNotes is a STRICT ENUM. Do not
   invent regimes. If unsure, emit `["none"]` or list only regimes you can
   actually justify from the description.

2. **Cite evidence.** Every entry in designPatterns must have at least one
   evidence value. Use real URLs when web_search returned them; use
   "training_data" only when you couldn't search.

3. **Personas are SHORT.** 2-3 sentences each. They get concatenated into
   long agent system prompts; brevity matters.

4. **uncertainAreas is mandatory.** If you're 100% confident, emit an empty
   array. But it's better to list ambiguity than to fabricate confidence.

4a. **confidence is a REAL self-assessment**, not the placeholder from the
   example schema above. Rubric:
     - **0.9+**: well-known domain (e-commerce, ATS, CRM, PMS, EHR) and
       the user's brief is unambiguous. You've built dozens of these.
     - **0.7–0.9**: well-known domain, but the brief has a novel angle
       (e.g. "ATS but for cabin crew") — you know the general shape,
       have to research the domain-specific quirks.
     - **0.5–0.7**: adjacent to a domain you know, OR the brief leaves
       important structural questions open.
     - **0.3–0.5**: niche, ambiguous, mostly-guessed. Flag heavily in
       `uncertainAreas`.
     - **< 0.3**: don't emit — populate `uncertainAreas` densely and
       return a low-confidence dossier so downstream agents know to
       ask clarifying questions.
   Emitting `confidence: 0.0` when you have SOME grounding is dishonest;
   downstream agents throttle their creativity based on this number.

5. **colorAnchors must be concrete hex codes** (`#RRGGBB`) — not colour names,
   not CSS variables. Ground them in real examples from your research when
   possible (e.g. dominant hues from a researched brand's screenshots).
   When research is sparse, pick hex codes that VISIBLY express the
   `paletteCharacter` you wrote — do NOT default to generic SaaS blues
   (#3b82f6), emeralds (#10b981), or slates (#475569) unless the character
   explicitly calls for them. Two apps with different paletteCharacters in
   the same domain MUST get visibly different anchors.

6. **fontFamily must be a concrete CSS stack** expressing the
   `typographyTone` you wrote. Pick a real font (preferably a Google Font
   for downstream availability) and add a `system-ui, sans-serif` (or
   `serif`/`monospace`) fallback. Examples:
   - editorial / boutique → `"Playfair Display", Georgia, serif`
   - refined-serif → `"Cormorant Garamond", Georgia, serif`
   - humanist / friendly → `"Manrope", system-ui, sans-serif`
   - technical / dev-tool → `"JetBrains Mono", ui-monospace, monospace`
   - corporate / SaaS → `"Inter", system-ui, sans-serif`
   - playful → `"Quicksand", "Comic Sans MS", system-ui, sans-serif`
   Two apps with different typographyTones in the same domain MUST get
   visibly different fontFamily strings. Do NOT default to "Inter" unless
   the tone is genuinely corporate/SaaS.

7. **No prose around the JSON.** First char `{`, last char `}`. The output is
   machine-consumed.
"""


_USER_PROMPT_TEMPLATE = """App description:
{description}

{plan_section}

Search the web if needed, then emit the dossier JSON now."""


def _build_plan_section(plan: dict | None) -> str:
    if not plan:
        return ""
    pages = plan.get("pages") or []
    entities = plan.get("entities") or {}
    if not pages and not entities:
        return ""
    lines = ["The planner produced this plan (for context):"]
    if pages:
        lines.append(f"  Pages: {', '.join(p.get('id', '?') for p in pages[:10])}")
    if isinstance(entities, dict) and entities:
        lines.append(f"  Entities: {', '.join(list(entities.keys())[:10])}")
    elif isinstance(entities, list) and entities:
        names = [e.get("name", "?") for e in entities if isinstance(e, dict)][:10]
        lines.append(f"  Entities: {', '.join(names)}")
    return "\n".join(lines)


# ── JSON extraction ─────────────────────────────────────────────────────────

_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}")


def _extract_json_object(text: str) -> dict | None:
    """Extract the first balanced JSON object from a response.

    Tries strict parse first. Falls back to regex-find-and-parse for the case
    where the model emits leading/trailing whitespace or stray characters
    despite the prompt's "no prose" instruction.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _JSON_OBJECT_RE.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _coerce_compliance(values: list[Any]) -> list[str]:
    """Filter compliance notes to the allowed enum. Anything outside the
    enum is dropped (with a marker) rather than failing validation, so a
    single hallucinated value doesn't tank the whole pipeline."""
    out: list[str] = []
    for v in values or []:
        if isinstance(v, str) and v.lower() in _ALLOWED_COMPLIANCE:
            out.append(v.lower())
    if not out:
        out = ["none"]
    return out


# ── Public API ──────────────────────────────────────────────────────────────

# Output ceiling for the dossier call. 4096 truncated rich domains (HVAC field
# service, etc.) mid-JSON, so _extract_json_object never found a balanced object
# and discovery failed. claude-sonnet-4-6 supports far more; give generous headroom.
_DISCOVERY_MAX_TOKENS = 16000

logger = logging.getLogger(__name__)


def _fallback_dossier(description: str, model: str, reason: str) -> dict:
    """Build a minimal but valid dossier when the discovery LLM call fails
    (timeout, unparseable output, API/network error).

    Discovery is the FIRST pipeline step and used to raise on these failures,
    dead-ending the entire generation. Instead, degrade gracefully: use the
    deterministic keyword classifier for the domain label and return a valid
    DiscoveryOutput so planning can still proceed. The user can refine the
    (sparse) dossier at the approval gate.
    """
    from services.domain_context import detect_domain

    try:
        dc = detect_domain(description)
    except Exception:  # classifier must never be the thing that breaks the fallback
        dc = {}
    validated = DiscoveryOutput(
        domain=(dc.get("domain") or "Generic"),
        description=description.strip()[:500],
        confidence=0.3,
    )
    validated.source = "fallback_keyword_classifier"
    validated.searchedWeb = False
    validated.model = model
    logger.warning("run_domain_discovery: falling back to keyword classifier (%s)", reason)
    out = validated.model_dump()
    out["_fallbackReason"] = reason
    return out


def _clamp_capped_list_fields(raw: dict) -> list[str]:
    """Trim over-length list fields to their schema cap, in place.

    LLMs routinely overshoot list caps — e.g. a discovery pass returns 10
    commonPitfalls when the schema allows 8. `max_length` on the field would
    RAISE on that, dead-ending the whole generation (and the per-field salvage
    branch below copies the offending list verbatim, so it re-raises too).
    This module's whole contract is "degrade gracefully, never dead-end step
    one", so trim instead: the model emits these lists highest-signal-first,
    so keeping the first N is exactly the "trim to the 8 best" behaviour.

    Returns the names of fields that were trimmed, for logging.
    """
    trimmed: list[str] = []
    for name, field in DiscoveryOutput.model_fields.items():
        cap = next((getattr(m, "max_length", None) for m in field.metadata
                    if getattr(m, "max_length", None) is not None), None)
        if cap is None:
            continue
        v = raw.get(name)
        if isinstance(v, list) and len(v) > cap:
            raw[name] = v[:cap]
            trimmed.append(f"{name} {len(v)}->{cap}")
    return trimmed


async def run_domain_discovery(
    description: str,
    plan: dict | None = None,
    *,
    enable_web_search: bool = True,
    # 90s was tuned for a dossier that got cut off at 4096 tokens. With the higher
    # token ceiling the model now writes the full dossier AND runs up to 5 web
    # searches server-side, which overran 90s and raised TimeoutError. Give it room.
    timeout_seconds: float = 300.0,
    model: str = "claude-sonnet-4-6",
    max_search_uses: int = 5,
) -> dict:
    """Produce a domain discovery dossier as a dict.

    Returns a dict shaped like ``DiscoveryOutput.model_dump()``. The caller
    is responsible for persisting it (typically to
    ``src/contracts/discovery.json``).

    Web search runs server-side via Anthropic's tool; the model decides when
    to search. Cap on uses prevents runaway costs.

    Failure modes:
      - missing ANTHROPIC_API_KEY → raises RuntimeError
      - LLM returns garbage twice → raises RuntimeError with both heads
      - JSON parses but fails Pydantic validation → coerces what it can
        (drops invalid compliance values, fills defaults) rather than failing
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "run_domain_discovery requires ANTHROPIC_API_KEY. Set it in "
            "backend/.env or the environment before calling."
        )

    from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim

    client = llm_client.AsyncAnthropic(api_key=api_key)

    plan_section = _build_plan_section(plan)
    user_prompt = _USER_PROMPT_TEMPLATE.format(
        description=description.strip(),
        plan_section=plan_section,
    )

    tools: list[dict] = []
    if enable_web_search:
        tools.append({
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": max_search_uses,
        })

    started = time.monotonic()

    async def _call(prompt: str) -> str:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": _DISCOVERY_MAX_TOKENS,
            "system": _SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}],
        }
        if tools:
            kwargs["tools"] = tools
        msg = await asyncio.wait_for(
            client.messages.create(**kwargs),
            timeout=timeout_seconds,
        )
        # Pull just the text blocks from the final assistant message. Tool
        # blocks (web search calls) are interleaved server-side but we don't
        # need to look at them — Claude folds the results into its final text.
        parts = []
        for b in msg.content:
            if getattr(b, "type", None) == "text":
                parts.append(b.text)
        return "".join(parts)

    try:
        text = await _call(user_prompt)
    except Exception as exc:  # timeout / network / API error — degrade, don't halt
        return _fallback_dossier(description, model, f"discovery call failed: {type(exc).__name__}")
    raw = _extract_json_object(text)

    if raw is None:
        # One retry with a sharper fixup.
        fixup = (
            f"App description:\n{description.strip()}\n\n"
            "Your previous response did not contain a parseable JSON object. "
            "Output ONLY the dossier JSON now — first char `{`, last char `}`, "
            "no prose, no fences."
        )
        try:
            text2 = await _call(fixup)
        except Exception as exc:
            return _fallback_dossier(description, model, f"retry call failed: {type(exc).__name__}")
        raw = _extract_json_object(text2)
        if raw is None:
            # Both attempts unparseable — fall back instead of raising so the
            # pipeline isn't dead-ended at step 1.
            return _fallback_dossier(description, model, "model emitted no parseable JSON after retry")

    # Coerce compliance values before validation so a stray hallucinated
    # regime doesn't fail the whole call.
    if "complianceNotes" in raw:
        raw["complianceNotes"] = _coerce_compliance(raw["complianceNotes"])

    # Trim any list the LLM overshot to its schema cap BEFORE validation, so an
    # over-eager response (10 commonPitfalls vs a cap of 8) is silently trimmed
    # rather than raising and dead-ending generation. Also protects the salvage
    # branch below, which reads from this same `raw`.
    _clamped = _clamp_capped_list_fields(raw)
    if _clamped:
        logger.info("run_domain_discovery: clamped over-length fields (%s)",
                    ", ".join(_clamped))

    try:
        validated = DiscoveryOutput(**raw)
    except ValidationError as ve:
        # Last-resort: build a partial DiscoveryOutput from whatever fields
        # we can salvage — PER FIELD, so one bad persona doesn't nuke the
        # researched visualLanguage the design DNA depends on.
        logger.warning("discovery validation failed — per-field salvage: %s",
                       str(ve)[:500])
        salvage_kwargs: dict = {
            "domain": raw.get("domain") or "Generic",
            "description": raw.get("description") or description.strip()[:200],
        }
        for fld, model_cls in (("visualLanguage", VisualLanguage),):
            v = raw.get(fld)
            if isinstance(v, dict):
                try:
                    salvage_kwargs[fld] = model_cls(**v)
                except ValidationError:
                    pass
        for fld in ("domainAliases", "designPatterns", "commonPitfalls"):
            v = raw.get(fld)
            if isinstance(v, list) and all(isinstance(x, str) for x in v):
                salvage_kwargs[fld] = v
        validated = DiscoveryOutput(**salvage_kwargs)
        validated.source = "validation_salvage"

    if not getattr(validated, "source", ""):
        validated.source = "domain_agent"
    if validated.source != "validation_salvage":
        validated.source = "domain_agent"
    validated.searchedWeb = enable_web_search
    validated.model = model
    validated.elapsedSeconds = round(time.monotonic() - started, 2)

    # B-003 fix — LLM sometimes emits `confidence: 0.0` despite the rubric
    # in the prompt (Afroz's "Confidence shows 0%" symptom). If the dossier
    # is genuinely populated (real domain, patterns, or entities), a 0
    # confidence is dishonestly low — the model DID understand something.
    # Floor to 0.5 in that case. Fallback dossiers (validation_salvage,
    # keyword-classifier) keep their explicit lower confidence.
    if validated.source == "domain_agent" and validated.confidence < 0.2:
        dossier_has_content = (
            bool(validated.designPatterns)
            or bool(validated.entitySuggestions)
            or (
                validated.domain
                and validated.domain.lower() not in ("generic", "unknown", "")
            )
        )
        if dossier_has_content:
            logger.info(
                "confidence floor: LLM emitted %.2f but dossier has content; "
                "bumping to 0.5", validated.confidence,
            )
            validated.confidence = 0.5

    return validated.model_dump()


def persist_discovery(output_dir: str, discovery: dict) -> str:
    """Write discovery output to `src/contracts/discovery.json` and return
    the path. Called by the pipeline immediately after a successful
    `run_domain_discovery` so downstream agents (and future re-runs) can
    read the dossier from disk.

    Returns the absolute path written. Creates parent directories.
    """
    from pathlib import Path
    target = Path(output_dir) / "src" / "contracts" / "discovery.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(discovery, indent=2, sort_keys=True), encoding="utf-8")
    return str(target)
