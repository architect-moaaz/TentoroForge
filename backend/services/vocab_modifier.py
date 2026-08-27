"""Level 2 vocabulary modifier — LLM specializes the deterministic base
vocab per user ask.

The 15 archetype vocabularies in :mod:`services.archetype_vocabulary` are
STATIC: ``banking_platform`` fires the same section splits, personas, and
empty-state copy whether the app is a community credit union, a neobank,
or a corporate treasury tool. This module reads the base vocab AS A
REFERENCE and lets the LLM specialize section names, persona role slugs,
component preferences, empty-state copy, and status vocabulary to the
specific user ask.

Trust boundary. Every LLM-authored value passes a strict merge validator
before it enters the returned vocab:

  - ``component_preferences[*].shape`` must be in
    :data:`services.archetype_vocabulary.KNOWN_SHAPES`. Composers dispatch
    on shape string — an unrecognized shape crashes rendering. Invalid
    entries are dropped; the base's entry for that slug survives.

  - ``status_badges[*].variant`` must be one of the five badge variants
    the runtime knows how to render. Same drop-and-fallback.

  - Every section named in :attr:`ArchetypeVocabulary.section_recipes`
    values MUST have both a ``section_filters`` entry (may be ``{}``) AND
    a ``signature_states["empty_<key>"]`` entry — this mirrors the
    invariant already enforced by the per-vocab test suite. Sections
    missing either are dropped from ``section_recipes`` and a warning
    surfaces in provenance.

Fail-open. Any exception (network, timeout, unparseable JSON, missing
API key) returns ``(base, {source: "base_fallback", reason: str})``.
The modifier is best-effort — never throws — so a flaky LLM never blocks
generation.

Cache. In-process LRU keyed on the same hash the disk-cache layer uses
(see :func:`vocab_modifier_pipeline.load_and_modify_vocab`). Skip disk
cache here; project-scoped disk cache belongs to the pipeline wiring
slice.

Behind ``FORGE_VOCAB_MODIFIER=1`` flag (default OFF). Wired into the
pipeline by :mod:`services.vocab_modifier_pipeline`.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import asdict
from typing import Any

from services.archetype_vocabulary import (
    KNOWN_SHAPES,
    ArchetypeVocabulary,
    ComponentPreference,
)

logger = logging.getLogger(__name__)


# Badge variants the runtime knows how to render. Matches the values the
# existing vocab files author + what components/Badge tolerates. Any LLM
# emission outside this set is dropped.
_VALID_BADGE_VARIANTS = frozenset({"success", "warning", "danger", "neutral", "accent"})


# Bounded in-memory LRU. Same-plan-same-turn re-calls hit this and the
# LLM is called exactly once per unique input. Disk cache (project-scoped,
# survives across processes) lives in the pipeline wiring slice.
_MEMO_CACHE: "dict[str, tuple[ArchetypeVocabulary, dict[str, Any]]]" = {}
_MEMO_MAX = 64


def _reset_cache_for_tests() -> None:
    """Test hook — clear the in-process LRU between tests."""
    _MEMO_CACHE.clear()


# --------------------------------------------------------------------- #
# Cache key
# --------------------------------------------------------------------- #

def cache_key(
    base: ArchetypeVocabulary,
    plan: dict,
    brief: Any | None = None,
) -> str:
    """Deterministic hash of the modifier's inputs.

    Same shape used by the disk-cache layer in the pipeline wiring slice
    so an in-process hit and a disk hit resolve identically.

    Fields folded into the hash:
      - vocab id (drives which base vocab is being specialized)
      - plan.description (the user ask)
      - sorted entity names (what the plan actually contains)
      - sorted actor role slugs (which personas exist)
      - brief.identity (voice, register, domain — the specialization
        signal the LLM leans on to pick tone)
    """
    parts: list[str] = [base.id or ""]
    parts.append(str((plan or {}).get("description") or "").strip())

    entities = (plan or {}).get("entities") or []
    entity_names: list[str] = []
    if isinstance(entities, list):
        for e in entities:
            if isinstance(e, dict):
                n = e.get("name") or e.get("slug")
                if isinstance(n, str) and n.strip():
                    entity_names.append(n.strip())
            elif isinstance(e, str) and e.strip():
                entity_names.append(e.strip())
    parts.append(",".join(sorted(entity_names)))

    actors = (plan or {}).get("actors") or []
    role_slugs: list[str] = []
    if isinstance(actors, list):
        for a in actors:
            if isinstance(a, dict):
                r = a.get("role") or a.get("slug") or a.get("name")
                if isinstance(r, str) and r.strip():
                    role_slugs.append(r.strip())
            elif isinstance(a, str) and a.strip():
                role_slugs.append(a.strip())
    parts.append(",".join(sorted(role_slugs)))

    if brief is not None:
        identity = getattr(brief, "identity", None)
        if identity is not None:
            try:
                # Pydantic model or dataclass — take the compact JSON form.
                if hasattr(identity, "model_dump"):
                    ident_dict = identity.model_dump(mode="json", exclude_none=True)
                elif hasattr(identity, "dict"):
                    ident_dict = identity.dict(exclude_none=True)  # type: ignore[call-arg]
                else:
                    ident_dict = dict(identity)
                parts.append(json.dumps(ident_dict, sort_keys=True, default=str))
            except Exception:  # noqa: BLE001
                parts.append(repr(identity))

    raw = "\x1f".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------- #
# Prompt
# --------------------------------------------------------------------- #

def _summarize_plan(plan: dict) -> dict:
    """Compact plan slice for the prompt — names only, no full schema."""
    out: dict[str, Any] = {}
    out["description"] = str((plan or {}).get("description") or "").strip()
    ents_out: list[dict] = []
    for e in (plan or {}).get("entities") or []:
        if isinstance(e, dict):
            name = e.get("name") or e.get("slug") or ""
            cols_raw = e.get("columns") or e.get("fields") or []
            cols: list[str] = []
            if isinstance(cols_raw, list):
                for c in cols_raw:
                    if isinstance(c, dict):
                        cn = c.get("name") or c.get("slug")
                        if isinstance(cn, str):
                            cols.append(cn)
                    elif isinstance(c, str):
                        cols.append(c)
            if name:
                ents_out.append({"name": name, "columns": cols[:20]})
    out["entities"] = ents_out
    acts_out: list[str] = []
    for a in (plan or {}).get("actors") or []:
        if isinstance(a, dict):
            r = a.get("role") or a.get("slug") or a.get("name")
            if isinstance(r, str) and r.strip():
                acts_out.append(r.strip())
        elif isinstance(a, str) and a.strip():
            acts_out.append(a.strip())
    out["actors"] = acts_out
    return out


def _summarize_brief_identity(brief: Any | None) -> dict | None:
    if brief is None:
        return None
    identity = getattr(brief, "identity", None)
    if identity is None:
        return None
    try:
        if hasattr(identity, "model_dump"):
            data = identity.model_dump(mode="json", exclude_none=True)
        elif hasattr(identity, "dict"):
            data = identity.dict(exclude_none=True)  # type: ignore[call-arg]
        else:
            data = dict(identity)
    except Exception:  # noqa: BLE001
        return None
    # Keep only the specialization-driving fields; drop deep visual_stance
    # payloads that don't influence vocab.
    picked: dict[str, Any] = {}
    for k in ("domain", "register", "voice", "voice_free", "compliance_flags"):
        v = data.get(k)
        if v not in (None, "", [], {}):
            picked[k] = v
    return picked or None


def _serialize_base_vocab(base: ArchetypeVocabulary) -> dict:
    """Convert a frozen ArchetypeVocabulary to a JSON-safe dict."""
    return asdict(base)


def _build_prompt(
    base: ArchetypeVocabulary,
    plan: dict,
    brief: Any | None,
) -> str:
    plan_slice = _summarize_plan(plan)
    ident = _summarize_brief_identity(brief)
    base_json = json.dumps(_serialize_base_vocab(base), indent=2, sort_keys=True)

    parts: list[str] = []
    parts.append(
        "You are specializing an archetype vocabulary to a specific product ask.\n"
        "\n"
        "The base vocabulary below encodes the CONVENTIONS every product in "
        "this archetype follows (section splits, empty-state copy, component "
        "shapes, status vocabulary). Your job: read the product description, "
        "entities, and personas, then propose a PARTIAL modification that "
        "makes the vocab feel authored FOR THIS PRODUCT rather than the "
        "generic archetype template.\n"
    )
    parts.append(
        "\nHOW TO SPECIALIZE:\n"
        "  1. Persona role slugs. If the plan's actors use domain-specific "
        "role names (e.g. 'gig_borrower', 'chief_compliance_officer', "
        "'sre_oncall') that aren't in the base's primary_screens_per_persona, "
        "add them with the screens that persona actually needs.\n"
        "  2. Section splits. Rename or add sections when the domain has a "
        "cleaner mental model (e.g. 'chargeback_disputes' vs generic "
        "'disputed'). ALWAYS add matching section_filters and "
        "signature_states['empty_<key>'] entries — sections without both are "
        "dropped.\n"
        "  3. component_preferences. Add entries for entities in the plan "
        "that the base didn't cover. Never change shape to a string outside "
        "the KNOWN_SHAPES set (listed below) — the composer will reject it.\n"
        "  4. signature_states. Rewrite empty-state copy in the product's "
        "voice. Match the brief.identity.voice when provided — 'warm' briefs "
        "get warmer copy, 'terse' briefs get shorter copy. Keep the "
        "'empty_<key>' key convention.\n"
        "  5. status_badges. Add new statuses the domain uses. Variant MUST "
        "be one of: success, warning, danger, neutral, accent.\n"
    )
    parts.append(
        "\nHARD CONSTRAINTS (values violating these are dropped):\n"
        f"  - KNOWN_SHAPES = {sorted(KNOWN_SHAPES)!r}\n"
        "  - badge variant ∈ {'success', 'warning', 'danger', 'neutral', 'accent'}\n"
        "  - Every section in section_recipes needs a matching section_filters "
        "and signature_states['empty_<key>'] entry.\n"
    )
    parts.append(
        "\nRETURN a PARTIAL modification — include ONLY fields you're "
        "changing or adding. Keys you omit fall through to the base's value. "
        "Do not repeat the base verbatim.\n"
    )
    parts.append("\nPRODUCT ASK:\n" + json.dumps(plan_slice, indent=2))
    if ident is not None:
        parts.append("\nBRIEF IDENTITY:\n" + json.dumps(ident, indent=2))
    parts.append("\nBASE VOCABULARY (reference — do not repeat unchanged):\n" + base_json)
    parts.append(
        "\nOUTPUT: pure JSON, no prose, no code fences. Shape:\n"
        "{\n"
        '  "primary_screens_per_persona": { "<role>": ["<screen>", ...] },\n'
        '  "section_recipes":             { "<screen>": ["<section>", ...] },\n'
        '  "component_preferences":       { "<entity>": { "shape": "...", "primary_field": "...", "context": "..." } },\n'
        '  "signature_states":            { "empty_<key>": "<copy>" },\n'
        '  "status_badges":               { "<status>": { "variant": "...", "label": "..." } },\n'
        '  "section_filters":             { "<section>": { "<col>": ["<val>", ...] } }\n'
        "}\n"
        "Any subset is valid. All fields optional."
    )
    return "".join(parts)


# --------------------------------------------------------------------- #
# LLM call — mockable seam for tests
# --------------------------------------------------------------------- #

async def _call_llm(prompt: str, *, model: str, timeout_s: float) -> dict | None:
    """Return parsed JSON dict from the LLM, or raise on failure.

    Kept small so tests replace it with an async fake. Callers wrap this
    in the fail-open guard — they log warnings on exceptions and fall
    back to base.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    try:
        from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"anthropic SDK unavailable: {exc}") from exc

    client = llm_client.AsyncAnthropic(api_key=api_key)
    coro = client.messages.create(
        model=model,
        max_tokens=4096,
        temperature=0.4,
        messages=[{"role": "user", "content": prompt}],
    )
    response = await asyncio.wait_for(coro, timeout=timeout_s)
    text = "".join(
        getattr(b, "text", "") for b in response.content
        if getattr(b, "type", "") == "text"
    ).strip()
    if not text:
        raise RuntimeError("empty LLM response")
    # Strip code-fence if the model wrapped despite instructions.
    if text.startswith("```"):
        text = text.strip("`")
        # drop optional language tag on the first line
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        text = text.strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    return json.loads(text)


# --------------------------------------------------------------------- #
# Merge + validate
# --------------------------------------------------------------------- #

def _section_empty_key(section: str) -> str:
    """Section name → signature_states key. Mirrors the convention every
    vocab file uses (``pending-review`` → ``empty_pending_review``)."""
    if not isinstance(section, str):
        return ""
    return "empty_" + section.strip().lower().replace("-", "_").replace(" ", "_")


def _merge_and_validate(
    base: ArchetypeVocabulary,
    llm_data: dict,
) -> tuple[ArchetypeVocabulary, dict]:
    """Union LLM fields into base, drop invalid entries, and enforce
    section invariants. Returns ``(vocab, changes_dict)``.

    Merge policy per field:
      - Dicts: union — LLM entries take precedence for keys that appear in
        both; base keys the LLM omitted survive.
      - ComponentPreference.shape: if not in KNOWN_SHAPES, drop the entire
        entry (log in changes.shapes_rejected), fall back to base for that
        entity slug.
      - status_badges[*].variant: if invalid, drop the entry, base survives.
      - section_recipes sections without matching section_filters +
        signature_states['empty_<key>'] pair are dropped, warning logged.
    """
    changes: dict[str, Any] = {
        "sections_added": [],
        "personas_added": [],
        "shapes_rejected": [],
        "warnings": [],
    }
    if not isinstance(llm_data, dict):
        llm_data = {}

    # -- primary_screens_per_persona --------------------------------
    personas = dict(base.primary_screens_per_persona)
    llm_personas = llm_data.get("primary_screens_per_persona") or {}
    if isinstance(llm_personas, dict):
        for role, screens in llm_personas.items():
            if not isinstance(role, str) or not role.strip():
                continue
            if not isinstance(screens, list):
                continue
            clean = [s for s in screens if isinstance(s, str) and s.strip()]
            if not clean:
                continue
            role_key = role.strip()
            if role_key not in personas:
                changes["personas_added"].append(role_key)
            personas[role_key] = clean

    # -- signature_states --------------------------------------------
    signature_states = dict(base.signature_states)
    llm_states = llm_data.get("signature_states") or {}
    if isinstance(llm_states, dict):
        for k, v in llm_states.items():
            if isinstance(k, str) and isinstance(v, str) and v.strip():
                signature_states[k.strip()] = v.strip()

    # -- section_filters ---------------------------------------------
    section_filters = dict(base.section_filters)
    llm_filters = llm_data.get("section_filters") or {}
    if isinstance(llm_filters, dict):
        for k, v in llm_filters.items():
            if not isinstance(k, str) or not k.strip():
                continue
            if not isinstance(v, dict):
                continue
            # Values may be a str, list[str], or {col: str/list}. Keep as-is.
            section_filters[k.strip()] = v

    # -- section_recipes with invariant enforcement ------------------
    recipes = dict(base.section_recipes)
    llm_recipes = llm_data.get("section_recipes") or {}
    if isinstance(llm_recipes, dict):
        for screen, sections in llm_recipes.items():
            if not isinstance(screen, str) or not screen.strip():
                continue
            if not isinstance(sections, list):
                continue
            kept: list[str] = []
            for section in sections:
                if not isinstance(section, str) or not section.strip():
                    continue
                name = section.strip()
                has_filter = name in section_filters
                has_empty = _section_empty_key(name) in signature_states
                if has_filter and has_empty:
                    kept.append(name)
                    if screen not in base.section_recipes or (
                        name not in base.section_recipes.get(screen, [])
                    ):
                        changes["sections_added"].append(f"{screen}:{name}")
                else:
                    missing: list[str] = []
                    if not has_filter:
                        missing.append("section_filters")
                    if not has_empty:
                        missing.append(f"signature_states['{_section_empty_key(name)}']")
                    changes["warnings"].append(
                        f"section {screen!r}/{name!r} dropped — missing "
                        + ", ".join(missing)
                    )
            if kept:
                recipes[screen.strip()] = kept

    # -- component_preferences ---------------------------------------
    prefs = dict(base.component_preferences)
    llm_prefs = llm_data.get("component_preferences") or {}
    if isinstance(llm_prefs, dict):
        for entity, spec in llm_prefs.items():
            if not isinstance(entity, str) or not entity.strip():
                continue
            if not isinstance(spec, dict):
                continue
            shape = spec.get("shape") or "table"
            if not isinstance(shape, str) or shape not in KNOWN_SHAPES:
                changes["shapes_rejected"].append(
                    f"{entity}:{shape!r} not in KNOWN_SHAPES"
                )
                # Base's entry (if any) survives.
                continue
            primary = spec.get("primary_field") or ""
            context = spec.get("context") or ""
            prefs[entity.strip()] = ComponentPreference(
                shape=shape,
                primary_field=str(primary) if primary else "",
                context=str(context) if context else "",
            )

    # -- status_badges ------------------------------------------------
    badges = dict(base.status_badges)
    llm_badges = llm_data.get("status_badges") or {}
    if isinstance(llm_badges, dict):
        for status, meta in llm_badges.items():
            if not isinstance(status, str) or not status.strip():
                continue
            if not isinstance(meta, dict):
                continue
            variant = meta.get("variant")
            if variant not in _VALID_BADGE_VARIANTS:
                changes["warnings"].append(
                    f"badge {status!r} variant {variant!r} invalid — dropped"
                )
                continue
            label = meta.get("label") or ""
            entry: dict[str, str] = {"variant": str(variant)}
            if label:
                entry["label"] = str(label)
            badges[status.strip()] = entry

    modified = ArchetypeVocabulary(
        id=base.id,
        primary_screens_per_persona=personas,
        section_recipes=recipes,
        component_preferences=prefs,
        signature_states=signature_states,
        status_badges=badges,
        section_filters=section_filters,
        # The modifier has no opinion on these two, so they pass through
        # untouched — dropping them is not the same as not modifying them.
        dashboard_recipe=base.dashboard_recipe,
        page_recipes=base.page_recipes,
    )
    return modified, changes


# --------------------------------------------------------------------- #
# Public entrypoint
# --------------------------------------------------------------------- #

DEFAULT_MODEL = os.getenv("FORGE_VOCAB_MODIFIER_MODEL", "claude-sonnet-4-5-20250929")


async def modify_vocab(
    base: ArchetypeVocabulary,
    plan: dict,
    brief: Any | None = None,
    *,
    model: str = DEFAULT_MODEL,
    timeout_s: float = 30.0,
) -> tuple[ArchetypeVocabulary, dict]:
    """Return ``(modified_vocab, provenance)``.

    Fail-open: any exception returns ``(base, {source: "base_fallback",
    reason: str(err)})``. Never raises.

    Provenance shape:
        {
            "source": "modified" | "cached" | "base_fallback",
            "reason": str | None,     # populated on fallback
            "changes": {              # populated on modified
                "sections_added":  [...],
                "personas_added":  [...],
                "shapes_rejected": [...],
                "warnings":        [...],
            }
        }
    """
    key = cache_key(base, plan, brief)
    cached = _MEMO_CACHE.get(key)
    if cached is not None:
        vocab, prov = cached
        return vocab, {**prov, "source": "cached"}

    try:
        prompt = _build_prompt(base, plan, brief)
        llm_data = await _call_llm(prompt, model=model, timeout_s=timeout_s)
        if not isinstance(llm_data, dict):
            raise RuntimeError("LLM returned non-object JSON")
        modified, changes = _merge_and_validate(base, llm_data)
        prov = {"source": "modified", "reason": None, "changes": changes}
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[vocab-modifier] archetype=%s base_fallback reason=%s",
            base.id, exc,
        )
        return base, {"source": "base_fallback", "reason": str(exc)}

    # Bounded LRU — evict oldest if over cap.
    if len(_MEMO_CACHE) >= _MEMO_MAX:
        try:
            first_key = next(iter(_MEMO_CACHE))
            _MEMO_CACHE.pop(first_key, None)
        except StopIteration:
            pass
    _MEMO_CACHE[key] = (modified, prov)
    return modified, prov


__all__ = [
    "DEFAULT_MODEL",
    "cache_key",
    "modify_vocab",
]
