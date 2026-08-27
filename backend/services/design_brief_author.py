"""Author a design brief for a domain, either from cache or via LLM.

Behavior:
  - Cache hit  → return the cached brief (anchors + previously-authored).
  - Cache miss → LLM authors one under strict schema + antipattern
    guardrails, we validate, cache, return.

Deterministic where possible: any known anchor domain never touches the
LLM. Novel domains fall through to the LLM boundary. Errors bubble as
:class:`BriefAuthorError` — callers decide whether to fall back to a
neighbor anchor or surface to the user.

Pure module. Testable without hitting the wire via ``author(...,
query_fn=fake)``.

See docs/superpowers/specs/2026-08-07-design-brief.md.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Awaitable, Callable

from pydantic import ValidationError

from schemas.design_brief import DesignBrief
from services.design_brief_antipatterns import BASE_ANTI_PATTERNS
from services import design_brief_cache

logger = logging.getLogger(__name__)


class BriefAuthorError(RuntimeError):
    """Raised when the LLM path fails and no fallback is possible."""


QueryFn = Callable[[str, str], Awaitable[str]]


# --------------------------------------------------------------------------- #
# System prompt — see spec doc for the "why" behind each section.
# --------------------------------------------------------------------------- #

_SYSTEM_PROMPT = """You are a design director. Given a domain and a functional
plan summary, you author ONE design brief that steers downstream page
generation away from generic AI aesthetics.

Emit ONE JSON object matching the schema. No prose, no explanation, no
markdown fences. The brief is a STARTING POINT — the user will tweak. Your
job is to propose something SPECIFIC and DISTINCTIVE, not safe.

## Principles (non-negotiable)

1. GROUND IT IN THE SUBJECT. Every choice — palette hue, type pairing,
   density, signature moves — must be defensible from the domain's own
   world. A vet clinic's warmth is not the same warmth as a bakery's.

2. NEUTRALS ARE CHOSEN, NOT DEFAULTED. Pure mid-grey reads as
   unconsidered. Bias the neutral hue toward the accent — a green brand
   needs a slightly-green neutral, not stock grey.

3. TYPE PAIRING IS THE PERSONALITY. Two typefaces (or one, deliberately)
   picked for character AND function. Not both defaults.

4. ONE OR TWO SIGNATURE MOVES. Pick one memorable visual gesture per
   brief. Everything else stays quiet.

5. COMMIT TO A REGISTER. Warm/trustworthy, precise/authoritative,
   bold/fast, editorial/quiet — pick one and every choice serves it.

## Hard blocklist (NEVER produce)

If your first instinct is one of these, REJECT IT and try again:

  - Warm cream + serif display + terracotta accent (the AI default)
  - Purple-to-blue gradient hero on white
  - Inter or Söhne as the "safe" everything-face without a display pair
  - Emoji as section markers
  - Everything centered
  - rounded-lg (8-12px) uniformly across every surface
  - Cream-serif-over-beige for anything not editorial
  - Dashboard-dark-blue as the default primary

## Output schema

{
  "identity": {
    "domain": "<the domain label you were given, verbatim>",
    "register": [<1-2 lowercase_snake_case adjectives>],
    "voice": "warm_precise|formal_technical|casual_direct|editorial_quiet|bold_fast",
    "modes": ["light", "dark"]
  },
  "palette": {
    "brand": "#RRGGBB", "accent": "#RRGGBB",
    "neutrals_base": "#RRGGBB", "neutrals_tint": "warm|cool|neutral",
    "surface_bg": "#RRGGBB", "surface_elevated": "#RRGGBB",
    "foreground_primary": "#RRGGBB", "foreground_muted": "#RRGGBB"
  },
  "typography": {
    "display_family": "<name>", "display_weights": [500, 700],
    "body_family": "<name>", "body_weights": [400, 500, 600],
    "utility_family": null | "<name>",
    "scale": "conservative_1.20|tight_1.15|expressive_1.333|editorial_1.414"
  },
  "layout": {
    "density": "compact|comfortable|spacious|spacious_for_touch",
    "radius": "sharp_2|soft_8|pill",
    "grid": "<short label>", "whitespace": "<short label>"
  },
  "signature_moves": [
    {"kind": "<snake_case_name>", "detail": "<one specific line>"}
  ],
  "anti_patterns": [<snake_case labels of things to avoid for this domain>],
  "content_bank": {
    "empty_states": {
      "list": "<voice-consistent message when a list has zero rows; may include {entity_plural}>",
      "search": "<zero search results; may include {entity_plural}, {query}>",
      "filtered": "<zero after filter; may include {entity_plural}>",
      "first_use": "<first-run copy inviting the user to add their first item; may include {entity_singular}>"
    },
    "toasts": {
      "created": "<success toast after creating; may include {entity_singular}>",
      "updated": "<success toast after saving edits; may include {entity_singular}>",
      "deleted": "<success toast after delete; may include {entity_singular}>",
      "error_generic": "<generic error>",
      "error_permission": "<permission denied>"
    },
    "notifications": {
      "task_assigned": "<subject for task-assignment notification; may include {task_kind}>",
      "approval_needed": "<subject when approval requested; may include {entity_singular}>"
    },
    "cta_verbs": {
      "primary": "<verb on the main action button — Record | Post | Log | Create | ...>",
      "create": "<verb for 'new item' buttons — Add | New | Draft | ...>",
      "delete": "<verb for destructive action — Remove | Archive | Delete | ...>",
      "save": "<verb on form submit — Save | Record | Update | ...>"
    }
  }
}

## Content bank — voice matters here more than anywhere else

The content bank is the voice made concrete. Every empty state, toast,
notification, and CTA verb in the generated app reads from this bank.
Same generic bank across two apps = same generic app.

Principles:
  - Match your identity.voice + register + domain. A vet clinic's
    "created" toast might be "Patient recorded" or "Chart started";
    a fintech app's is "Transaction posted"; a design tool's is
    "Draft saved". Never "Item created".
  - Substitution tokens the runtime fills in: {entity_singular},
    {entity_plural}, {query}, {task_kind}, {app_name}. Use them; the
    reader replaces per-page. Do NOT hard-code the entity name.
  - CTA verbs are DOMAIN nouns. A clinic doesn't "create a patient" —
    it "admits" one. A ticket system "opens" a ticket. Pick the verb
    the user of THIS domain would actually say.
  - Keep it short. Empty state = one sentence. Toast = 3-6 words.
  - No emoji. No exclamation marks unless the register is "bold_fast"
    or "casual_direct".

Now: given a new domain, propose a distinctive brief. Emit JSON only.
"""


# --------------------------------------------------------------------------- #
# Spec D Wave 4 — constrained-enum liberation prompt extension.
#
# Appended to the base prompt when FORGE_CLEANUP_WAVE_4=1. Teaches the
# model the optional free-form / numeric companions to the enum buckets,
# and tells it to emit them ALONGSIDE (not instead of) the enums. The
# schema accepts both; downstream renderers snap the numerics to
# renderable CSS tokens via brief_to_design_spec's snap_* helpers.
# --------------------------------------------------------------------------- #
_WAVE_4_PROMPT_EXTENSION = """
## Wave 4 — continuous companions (optional but preferred when they say something)

The schema now accepts free-form + numeric companions alongside the
enum buckets. Emit BOTH when you have real intent — the enum stays as
the guaranteed field for old readers, and the companion carries the
nuance a bucket can't. Skip the companion when the enum already fully
captures your intent — noise beats detail.

  identity.voice_free       : str ≤ 40 chars — HARD CAP, count carefully.
                              One specific phrase in your own words.
                              e.g. "warm and precise, quietly editorial"
                              (36 chars ✓). AVOID em-dashes / semicolons /
                              parenthetical clauses that push you over 40.
                              If your phrase runs >40, cut it or OMIT the
                              field (leave enum only). NEVER emit >40.

  palette.neutrals_tint_free: str ≤ 20 chars — HARD CAP. e.g. "cool with
                              green" (15 chars ✓). Skip when the tint is
                              a plain enum value. NEVER emit >20.

  typography.display_family_free / body_family_free : str ≤ 40 chars each.
                              Font family name only, no fallback stack.
                              NEVER emit >40 chars per field.

  layout.radius_px          : int 0..32 — the SPECIFIC corner radius you
                              want. 0-3 reads as sharp, 4-15 as soft,
                              16+ snaps to pill. Emit when you have a
                              specific px (e.g. 6, 10, 14) that the
                              3-bucket enum can't hit precisely.

  layout.density_pt         : int 0..32 — the SPECIFIC row/gap height
                              in points. ≤5 compact, ≤10 comfortable,
                              ≤16 spacious, 17+ spacious_for_touch.
                              Emit when the enum's boundary is wrong for
                              this domain (e.g. touch-first apps often
                              want 20, not the enum's default 24).

These are ADDITIVE — never omit the enum in favor of the companion.
Both, or enum-only. Never companion-only.
"""


def _wave_4_enabled() -> bool:
    """Wave 4 authoring gate. Schema always accepts the fields; this
    only controls whether the prompt actively solicits them."""
    return os.getenv("FORGE_CLEANUP_WAVE_4", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _system_prompt() -> str:
    """The base system prompt, with the Wave 4 extension appended when
    the flag is on. Keeps the base prompt untouched for callers on the
    old path."""
    if _wave_4_enabled():
        return _SYSTEM_PROMPT + _WAVE_4_PROMPT_EXTENSION
    return _SYSTEM_PROMPT


def _build_user_prompt(domain: str, plan_summary: str) -> str:
    """Build the user-side prompt for brief authoring.

    Note (Spec A Slice 7): removed per-domain anchor few-shot examples.
    Anchors were hand-authored briefs for 6 domains used as prompt
    examples — they constrained the LLM toward my guess at what each
    domain should look like, and every domain outside the 6 got no
    signal. The system prompt + BASE_ANTI_PATTERNS + the schema shape
    are enough grounding; the LLM can reason from the domain name +
    plan summary directly.
    """
    return (
        f"Domain: {domain}\n"
        f"Plan summary: {plan_summary or '(no plan summary provided)'}\n\n"
        "Author a distinctive brief for this domain. Emit JSON only."
    )


_JSON_OBJ = re.compile(r"\{[\s\S]*\}")
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def _repair_common_json_errors(s: str) -> str:
    """Best-effort repair of the JSON mistakes LLMs make most often:
    trailing commas before ``}`` / ``]``, and code-fence residue."""
    # Strip ```json fences if the greedy match swallowed them.
    s = s.replace("```json", "").replace("```", "").strip()
    # Trailing commas: {"a": 1,} → {"a": 1}
    s = _TRAILING_COMMA.sub(r"\1", s)
    return s


def _extract_json(raw: str) -> dict:
    """Peel a JSON object out of the LLM's response.

    Model sometimes wraps output in prose or fences even when told not
    to — grab the first {...} block. Tries a permissive repair pass on
    the top LLM-JSON failure modes before giving up.
    """
    m = _JSON_OBJ.search(raw)
    if not m:
        raise BriefAuthorError(f"no JSON object found in response: {raw[:200]!r}")
    candidate = m.group(0)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        try:
            return json.loads(_repair_common_json_errors(candidate))
        except json.JSONDecodeError as exc:
            raise BriefAuthorError(f"invalid JSON: {exc!s}") from exc


async def _self_heal_json(qf: "QueryFn", raw: str, parse_error: str) -> dict:
    """Ask the model to fix its own broken JSON. One call, low
    temperature, focused system prompt. Runs only when the primary
    parse (with local repair) has already failed."""
    system = (
        "You emitted JSON that failed to parse. Return ONLY the corrected "
        "JSON object — no prose, no code fences. Preserve every field's "
        "content; only fix syntax."
    )
    user = f"Parse error: {parse_error}\n\nOriginal output:\n{raw}"
    healed = await qf(system, user)
    return _extract_json(healed)


def _truncate_string_too_long(payload: dict, exc: ValidationError) -> tuple[dict, int]:
    """Deterministically fix `string_too_long` violations by truncating the
    offending values in-place at their `max_length`. Returns (payload, fixed_count).

    Rationale: the LLM occasionally emits an extra 3-9 chars over a
    max_length cap (voice_free ≤40, neutrals_tint_free ≤20, family_free
    ≤40). Instead of round-tripping to the LLM for a re-write that often
    still misses the count, snip the string. This is safe for free-form
    fields — the extra prose is noise, and truncation preserves the
    important first N chars. Non-string_too_long violations pass through
    unchanged; the caller still falls back to LLM self-heal for those.

    Cuts on word boundary within the last 10 chars when possible; otherwise
    hard-truncates. Never returns a value longer than max_length.
    """
    fixed = 0
    for err in exc.errors():
        if err.get("type") != "string_too_long":
            continue
        ctx = err.get("ctx") or {}
        max_len = ctx.get("max_length")
        if not isinstance(max_len, int) or max_len <= 0:
            continue
        loc = err.get("loc") or ()
        if not loc:
            continue
        # Walk to the parent so we can rewrite the leaf.
        node = payload
        try:
            for seg in loc[:-1]:
                node = node[seg]
        except (KeyError, TypeError, IndexError):
            continue
        leaf = loc[-1]
        try:
            cur = node[leaf]
        except (KeyError, TypeError, IndexError):
            continue
        if not isinstance(cur, str) or len(cur) <= max_len:
            continue
        # Try to snip on a word boundary within the last 10 chars.
        snip = cur[:max_len]
        _tail = snip[-10:] if max_len > 10 else snip
        space = _tail.rfind(" ")
        if space > 0:
            snip = snip[: (max_len - len(_tail) + space)].rstrip(" ,.—-;:")
        node[leaf] = snip
        fixed += 1
    return payload, fixed


async def _self_heal_schema(qf: "QueryFn", payload: dict, validation_error: str) -> dict:
    """Ask the model to fix its own schema-violating brief. Different
    from JSON self-heal: the JSON is valid but the field VALUES violate
    the DesignBrief schema (e.g. string too long, wrong enum). We hand
    the model the exact Pydantic errors so it can shorten / restate.
    """
    system = (
        "Your brief JSON parsed but failed schema validation. Return ONLY "
        "the corrected JSON object — no prose, no code fences. Fix the "
        "field VALUES to satisfy the constraints listed. Keep the same "
        "keys and same overall content; only shorten / reword the values "
        "the errors flagged."
    )
    user = (
        f"Validation errors:\n{validation_error}\n\n"
        f"Your original brief:\n{json.dumps(payload, indent=2)}"
    )
    healed = await qf(system, user)
    return _extract_json(healed)


async def _default_query(system: str, user: str) -> str:
    """Real LLM call. Behind an env boundary so tests never hit the wire."""
    from services.llm_client import AsyncAnthropic  # LangGraph migration (LG-1)

    client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    msg = await client.messages.create(
        model=os.environ.get("FORGE_BRIEF_AUTHOR_MODEL", "claude-sonnet-4-6"),
        max_tokens=2048,
        system=system,
        messages=[{"role": "user", "content": user}],
        temperature=0.7,  # some variance so briefs feel distinct
    )
    return "".join(
        block.text for block in msg.content if getattr(block, "type", "") == "text"
    )


async def author(
    domain: str,
    *,
    plan_summary: str = "",
    query_fn: QueryFn | None = None,
    force_llm: bool = False,
) -> DesignBrief:
    """Author (or fetch) a design brief for a domain.

    Args:
        domain: canonical domain label (see services.domain_context).
        plan_summary: optional short prose describing the plan
            (entities, journeys). Fed to the LLM for grounding.
        query_fn: test seam — inject a canned (system, user) → str
            function to avoid hitting the wire.
        force_llm: bypass cache; re-author via LLM. For debug/dev use.

    Returns:
        A validated :class:`DesignBrief`.

    Raises:
        BriefAuthorError: LLM path failed and no anchor fallback exists.
    """
    if not domain or not isinstance(domain, str):
        raise BriefAuthorError("domain must be a non-empty string")

    if not force_llm:
        cached = design_brief_cache.get(domain)
        if cached is not None:
            logger.info("[brief] cache hit for %s", domain)
            return cached

    # LLM path — required for novel domains.
    qf = query_fn or _default_query
    system = _system_prompt()
    # UI/UX Pro Max knowledge base (behind FORGE_UI_UX_PRO_MAX). Appends a
    # domain-matched reference block (curated palettes, type pairings, style
    # recommendations, anti-patterns from the vendored ui-ux-pro-max-skill)
    # to the brief author's system prompt. Without this, the brief author
    # picks palettes + fonts from scratch and regresses to the same 5
    # AI-safe defaults every generation. With it, wellness briefs get
    # actual wellness palette recipes, finance briefs get finance recipes,
    # etc. Off by default; opt in with FORGE_UI_UX_PRO_MAX=on.
    try:
        from services.design_knowledge import compose_prompt as _ux_prompt
        _ux_block = _ux_prompt(domain)
        if _ux_block:
            system = system + "\n\n" + _ux_block
    except Exception as _ux_exc:  # noqa: BLE001 — never break brief authoring
        logger.warning("[brief] ui-ux-pro-max injection failed: %s", _ux_exc)
    user = _build_user_prompt(domain, plan_summary)
    logger.info("[brief] LLM author for %s (plan_summary=%d chars)", domain, len(plan_summary))

    try:
        raw = await qf(system, user)
    except Exception as exc:  # noqa: BLE001
        raise BriefAuthorError(f"LLM call failed: {exc!s}") from exc

    try:
        payload = _extract_json(raw)
    except BriefAuthorError as parse_exc:
        # LLM authored a valid brief but emitted invalid JSON (unescaped
        # quote, malformed comma, etc.). Ask the model to fix its own
        # output rather than losing the brief entirely.
        logger.warning(
            "[brief] first-parse failed for %s (%s) — trying self-heal",
            domain, parse_exc,
        )
        try:
            payload = await _self_heal_json(qf, raw, str(parse_exc))
            logger.info("[brief] self-heal succeeded for %s", domain)
        except Exception as heal_exc:  # noqa: BLE001
            raise BriefAuthorError(
                f"invalid JSON, self-heal also failed: {heal_exc!s}"
            ) from heal_exc

    # Merge the base blocklist onto whatever the model produced. The
    # model can add domain-specific antipatterns; it can't override the
    # base list.
    model_ap = payload.get("anti_patterns") or []
    payload["anti_patterns"] = sorted({*BASE_ANTI_PATTERNS, *model_ap})

    try:
        brief = DesignBrief.model_validate(payload)
    except ValidationError as exc:
        # LLM emitted valid JSON but the field values violate the
        # DesignBrief schema. Two-stage self-heal:
        #   1. DETERMINISTIC — truncate any string_too_long violations
        #      at the schema's max_length. Free-form fields (voice_free,
        #      neutrals_tint_free, family_free) trip this most often;
        #      the extra prose is noise and truncation is safe.
        #   2. LLM RE-WRITE — for any remaining violations (wrong enum,
        #      wrong shape, etc.) that truncation can't fix, hand the
        #      Pydantic errors to the model for a targeted rewrite.
        try:
            payload, fixed = _truncate_string_too_long(payload, exc)
        except Exception:  # noqa: BLE001 — never break on a truncation edge case
            fixed = 0
        if fixed:
            try:
                brief = DesignBrief.model_validate(payload)
                logger.info(
                    "[brief] deterministic truncation fixed %d field(s) for %s",
                    fixed, domain,
                )
                design_brief_cache.put(domain, brief)
                return brief
            except ValidationError as re_exc:
                # Truncation cured some violations but not all — fall
                # through to LLM self-heal with the residual errors.
                exc = re_exc
        logger.warning(
            "[brief] schema validation failed for %s — trying LLM self-heal (%s)",
            domain, str(exc)[:200],
        )
        try:
            healed_payload = await _self_heal_schema(qf, payload, str(exc))
            # Re-merge base blocklist on the healed payload (model may
            # not have echoed it back).
            _hp_ap = healed_payload.get("anti_patterns") or []
            healed_payload["anti_patterns"] = sorted({*BASE_ANTI_PATTERNS, *_hp_ap})
            brief = DesignBrief.model_validate(healed_payload)
            logger.info("[brief] schema self-heal succeeded for %s", domain)
        except (BriefAuthorError, ValidationError) as heal_exc:
            raise BriefAuthorError(
                f"schema validation failed, self-heal also failed: {heal_exc!s}"
            ) from heal_exc

    design_brief_cache.put(domain, brief)
    return brief


__all__ = ["author", "BriefAuthorError"]
