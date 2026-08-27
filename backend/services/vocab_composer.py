"""Multi-vocab COMPOSE stack — LLM composes ONE coherent vocab + visual
identity from N candidate vocabularies and N candidate visual-lock
presets.

Extends the single-vocab modifier (:mod:`services.vocab_modifier`) —
does NOT modify it. The modifier stays as the safety net; the composer
is the new production entry point when the flag is on.

WHY a separate module. The modifier's prompt shape assumes ONE base
vocab and asks the LLM to specialize a partial diff. The composer's
prompt shape is different: it presents N vocabularies + N presets and
asks the LLM to pick a dominant voice, harmonize, and cherry-pick.
Mixing them into one module blurs the two contracts.

TRUST BOUNDARY. Every LLM-authored value passes the same class of
merge-validator the modifier uses, extended with:

  - Palette hex values MUST come from the union of the candidate
    presets' palettes — no net-new hex values (Option A). Invalid
    entries fall back to the ``primary_preset``'s slot and log.

  - Typography families MUST come from the union of the candidate
    presets' typography — no net-new font families. Same fallback.

  - The composer keeps the modifier's shape/badge/section-invariant
    validations and adds a coherence heuristic on empty-state tone.

FAIL-OPEN CASCADE. Any exception during LLM/parse/merge:

  1. Fall back to :func:`services.vocab_modifier.modify_vocab` on the
     TOP candidate vocab (preserves single-vocab behavior).
  2. If ``modify_vocab`` also raises, return the base candidate +
     ``primary_preset`` untouched.

Never raises. The composer is best-effort — a flaky LLM never blocks
generation.

CACHE. In-process LRU keyed on the composer's own :func:`cache_key`.
Disk cache lives in :mod:`vocab_composer_pipeline`.

Behind ``FORGE_VOCAB_COMPOSER=1`` flag (default OFF). Wired in the
pipeline module.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from dataclasses import asdict
from typing import Any

from schemas.design_brief import VisualLock
from services.archetype_vocabulary import (
    KNOWN_SHAPES,
    ArchetypeVocabulary,
    ComponentPreference,
)
from services.color_contrast import (
    contrast_ratio,
    parse_hex,
    saturation,
    saturation_cap_for_register,
)
from services.vocab_modifier import (
    DEFAULT_MODEL,
    _VALID_BADGE_VARIANTS,
    _section_empty_key,
    modify_vocab,
)


# --------------------------------------------------------------------- #
# Palette-slot contrast thresholds (WCAG AA against the composite bg).
# --------------------------------------------------------------------- #

# fg carries text — WCAG AA body-text minimum is 4.5:1.
# accent/badge carry non-text UI (chips, buttons, bars) — AA for UI
# components is 3.0:1.
_PALETTE_CONTRAST_MIN: dict[str, float] = {
    "fg":     4.5,
    "accent": 3.0,
    "badge":  3.0,
}

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------- #
# CREATIVE-5b — primary_component compatibility
#
# Each `ComponentPreference.shape` string is a collection-shape hint.
# The LLM may nominate a specific library component to render that shape
# (e.g. shape="table" + primary_component="ResourceTimeline"); the
# validator drops nominations whose data_shape can't plausibly render
# the collection. All collection shapes accept components whose
# `data_shape` is one of `list` / `tabular` — scalars, series charts,
# and `none` don't render a list of records.
# --------------------------------------------------------------------- #

_COLLECTION_DATA_SHAPES: frozenset[str] = frozenset({"list", "tabular"})


def _shape_accepts_data_shape(shape: str, component_data_shape: str) -> bool:
    if shape not in KNOWN_SHAPES:
        return False
    return component_data_shape in _COLLECTION_DATA_SHAPES


def _validate_primary_component(
    composite_vocab: ArchetypeVocabulary,
    library_manifest_compact: dict | None,
    changes: dict,
) -> ArchetypeVocabulary:
    """Drop primary_component nominations the library can't satisfy.

    Never raises. When the manifest isn't provided the step is a no-op
    (backwards-compatible with callers who don't wire it yet). Rejected
    entries fall back to ``primary_component=""``; the caller then uses
    the shape's default component.
    """
    if not isinstance(library_manifest_compact, dict):
        return composite_vocab
    comps = library_manifest_compact.get("components")
    if not isinstance(comps, dict) or not comps:
        return composite_vocab

    prefs = composite_vocab.component_preferences
    rejected: list[dict] = changes.setdefault("primary_component_rejected", [])
    healed: dict[str, ComponentPreference] = {}
    changed = False
    for entity, pref in prefs.items():
        name = (pref.primary_component or "").strip()
        if not name:
            healed[entity] = pref
            continue
        entry = comps.get(name)
        if not isinstance(entry, dict):
            rejected.append({
                "entity": entity,
                "proposed_name": name,
                "reason": "not_in_library",
            })
            healed[entity] = ComponentPreference(
                shape=pref.shape,
                primary_field=pref.primary_field,
                context=pref.context,
                primary_component="",
            )
            changed = True
            continue
        component_shape = str(entry.get("data_shape") or "")
        if not _shape_accepts_data_shape(pref.shape, component_shape):
            rejected.append({
                "entity": entity,
                "proposed_name": name,
                "reason": "data_shape_mismatch",
            })
            healed[entity] = ComponentPreference(
                shape=pref.shape,
                primary_field=pref.primary_field,
                context=pref.context,
                primary_component="",
            )
            changed = True
            continue
        healed[entity] = pref

    if not changed:
        return composite_vocab
    return ArchetypeVocabulary(
        id=composite_vocab.id,
        primary_screens_per_persona=composite_vocab.primary_screens_per_persona,
        section_recipes=composite_vocab.section_recipes,
        component_preferences=healed,
        signature_states=composite_vocab.signature_states,
        status_badges=composite_vocab.status_badges,
        section_filters=composite_vocab.section_filters,
        dashboard_recipe=composite_vocab.dashboard_recipe,
        page_recipes=composite_vocab.page_recipes,
    )


# Bounded in-memory LRU — same pattern as vocab_modifier.
_MEMO_CACHE: "dict[str, tuple[ArchetypeVocabulary, VisualLock, dict[str, Any]]]" = {}
_MEMO_MAX = 64


def _reset_cache_for_tests() -> None:
    """Test hook — clear the in-process LRU between tests."""
    _MEMO_CACHE.clear()


# --------------------------------------------------------------------- #
# Cache key
# --------------------------------------------------------------------- #

def cache_key(
    candidates: list[ArchetypeVocabulary],
    candidate_presets: list[VisualLock],
    plan: dict,
    brief: Any | None = None,
    patterns: list[dict] | None = None,
    variance_seed: str | int | None = None,
    library_manifest_compact: dict | None = None,
    requirement: str = "",
) -> str:
    """Deterministic hash of the composer's inputs.

    Folded in:
      - the requirement text (the user's own statement of what the app
        must do — it now steers the merge, so two apps with the same
        plan but different requirements must not share a composition)
      - sorted candidate vocab ids
      - sorted candidate preset names
      - plan.description (the user ask)
      - sorted entity names
      - sorted actor role slugs
      - brief.identity (voice, register, domain)
      - sorted ``brief._locked_fields`` (dot-paths the user pinned; a
        different lock set changes the merged output so it must miss
        the cache — order-insensitive so ["a","b"] hashes as ["b","a"])
      - sorted pattern names/titles (user-selected design patterns)
      - variance_seed (per-generation variance token; same seed → cache hit)

    Sorted first so caller-provided ordering never causes a cache miss
    when the actual pool is the same.
    """
    parts: list[str] = []
    parts.append((requirement or "").strip())
    parts.append(",".join(sorted((c.id or "") for c in (candidates or []))))
    parts.append(",".join(sorted((p.preset_name or "") for p in (candidate_presets or []))))
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
                if hasattr(identity, "model_dump"):
                    ident_dict = identity.model_dump(mode="json", exclude_none=True)
                elif hasattr(identity, "dict"):
                    ident_dict = identity.dict(exclude_none=True)  # type: ignore[call-arg]
                else:
                    ident_dict = dict(identity)
                parts.append(json.dumps(ident_dict, sort_keys=True, default=str))
            except Exception:  # noqa: BLE001
                parts.append(repr(identity))

    # Locked visual-lock paths — sorted so key is order-insensitive.
    locked_paths = _get_locked_paths(brief)
    parts.append("locks=" + ",".join(sorted(locked_paths)))

    pattern_ids: list[str] = []
    if isinstance(patterns, list):
        for p in patterns:
            if isinstance(p, dict):
                v = p.get("id") or p.get("name") or p.get("title")
                if isinstance(v, str) and v.strip():
                    pattern_ids.append(v.strip())
            elif isinstance(p, str) and p.strip():
                pattern_ids.append(p.strip())
    parts.append(",".join(sorted(pattern_ids)))

    if variance_seed is not None:
        parts.append(f"seed={variance_seed}")

    # Library manifest keys — folded as a hash so a library rebuild that
    # adds/removes components invalidates the cache. Order-insensitive
    # (sorted) so the same library hashes the same across processes.
    if isinstance(library_manifest_compact, dict):
        comps = library_manifest_compact.get("components")
        if isinstance(comps, dict) and comps:
            names_sig = ",".join(sorted(comps.keys()))
            parts.append(
                "lib=" + hashlib.sha256(names_sig.encode("utf-8")).hexdigest()[:16]
            )

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
    picked: dict[str, Any] = {}
    for k in ("domain", "register", "voice", "voice_free", "compliance_flags"):
        v = data.get(k)
        if v not in (None, "", [], {}):
            picked[k] = v
    return picked or None


def _serialize_vocab(v: ArchetypeVocabulary) -> dict:
    return asdict(v)


def _serialize_preset(p: VisualLock) -> dict:
    try:
        return p.model_dump(mode="json", exclude_none=False)
    except AttributeError:
        return p.dict()  # type: ignore[attr-defined]


def _preset_hex_allowlist(presets: list[VisualLock]) -> set[str]:
    """Union of every hex value across every candidate preset's palette."""
    allowed: set[str] = set()
    for p in presets or []:
        for v in (p.palette or {}).values():
            if isinstance(v, str) and v.strip():
                allowed.add(v.strip().upper())
    return allowed


def _preset_font_allowlist(presets: list[VisualLock]) -> set[str]:
    """Union of every font-family across every candidate preset's typography."""
    allowed: set[str] = set()
    for p in presets or []:
        for v in (p.typography or {}).values():
            if isinstance(v, str) and v.strip():
                allowed.add(v.strip())
    return allowed


# --------------------------------------------------------------------- #
# Locked visual-lock paths (CREATIVE-4)
#
# The user pins dot-paths in ``brief._locked_fields`` — e.g.
# ``palette.accent``, ``typography.display``, ``radius.md``, ``shadow.sm``.
# Each path is 2-level: ``<visual_lock section>.<slot>``. Paths that don't
# match a VisualLock section are ignored (vocabulary-level locks are out
# of scope for this slice — the DesignBrief doesn't carry any today).
#
# The dot-path format is deliberate: the persistence layer stores locks
# as JSON strings, and the DesignBrief editor's ``_find_locked_violations``
# already emits ``"palette.accent"``-style diagnostics — reusing the same
# separator keeps error messages and pin markers aligned across layers.
# --------------------------------------------------------------------- #

_VISUAL_LOCK_SECTIONS: tuple[str, ...] = (
    "palette", "typography", "radius", "shadow",
)


def _get_locked_paths(brief: Any | None) -> list[str]:
    """Return the list of dot-paths the user pinned on the brief.

    Reads ``brief._locked_fields`` defensively — the attribute may not
    exist on older brief schemas, may be None, or may hold a non-iterable
    value. Any of those returns ``[]`` — a broken lock list must never
    take the composer down.

    Only string entries survive; each is stripped. Duplicates are
    preserved (the caller sorts + de-dups where needed).
    """
    if brief is None:
        return []
    raw = getattr(brief, "_locked_fields", None)
    if raw is None:
        return []
    try:
        seq = list(raw)
    except TypeError:
        return []
    out: list[str] = []
    for entry in seq:
        if isinstance(entry, str):
            s = entry.strip()
            if s:
                out.append(s)
    return out


def _lookup_lock_value(source: Any, path: str) -> Any:
    """Return the value at ``visual_lock.<path>`` on ``source``.

    ``source`` may be a :class:`VisualLock` (with attribute ``palette``
    et al.) or an object carrying a ``visual_lock`` attribute (a
    DesignBrief). Returns ``None`` when any leg of the lookup misses.
    """
    if source is None:
        return None
    parts = path.split(".")
    if not parts or len(parts) < 2:
        return None
    section, slot = parts[0], parts[1]
    if section not in _VISUAL_LOCK_SECTIONS:
        return None
    # DesignBrief-shaped: reach into .visual_lock first.
    container = getattr(source, "visual_lock", source)
    if container is None:
        return None
    section_val = getattr(container, section, None)
    if section_val is None and isinstance(container, dict):
        section_val = container.get(section)
    if not isinstance(section_val, dict):
        return None
    return section_val.get(slot)


def _apply_locked_fields(
    composite_lock: VisualLock,
    brief: Any | None,
    primary_preset: VisualLock,
    changes: dict,
) -> VisualLock:
    """Overwrite composite slots with user-pinned authoritative values.

    Runs strictly AFTER hex + font validation — a user's pinned hex is
    authoritative even if WCAG would nag about it. That's a considered
    trade-off (respect the user's aesthetic; log the tension).

    For each locked dot-path ``<section>.<slot>``:
      1. Read authoritative value from ``brief.visual_lock.<path>``.
      2. Fall back to ``primary_preset.<path>``.
      3. If still missing, skip (no crash on partial locks).
      4. Overwrite ``composite_lock`` at that path.
      5. Log to ``changes.locked_field_kept`` when the composite differed.
    """
    paths = _get_locked_paths(brief)
    if not paths:
        return composite_lock

    kept: list[dict] = changes.setdefault("locked_field_kept", [])

    # Mutable working copies keyed by section — we rebuild the lock at end.
    section_maps: dict[str, dict] = {
        "palette": dict(composite_lock.palette),
        "typography": dict(composite_lock.typography),
        "radius": dict(composite_lock.radius),
        "shadow": dict(composite_lock.shadow),
    }

    dirty = False
    for path in paths:
        parts = path.split(".")
        if len(parts) < 2:
            continue
        section, slot = parts[0], parts[1]
        if section not in _VISUAL_LOCK_SECTIONS:
            # Vocabulary-level or unknown-section lock — out of scope.
            continue

        source_used: str | None = None
        authoritative = _lookup_lock_value(brief, path)
        if authoritative is not None:
            source_used = "brief"
        else:
            authoritative = _lookup_lock_value(primary_preset, path)
            if authoritative is not None:
                source_used = "preset"
        if source_used is None or authoritative is None:
            continue

        current = section_maps[section].get(slot)
        if current != authoritative:
            kept.append({
                "path": path,
                "replaced_with": authoritative,
                "source": source_used,
            })
            logger.info(
                "[vocab-composer] lock kept path=%s source=%s replaced=%r",
                path, source_used, authoritative,
            )
            section_maps[section][slot] = authoritative
            dirty = True

    if not dirty:
        return composite_lock

    return VisualLock(
        palette=section_maps["palette"],
        typography=section_maps["typography"],
        radius=section_maps["radius"],
        shadow=section_maps["shadow"],
        preset_name=composite_lock.preset_name,
    )


def _format_patterns_block(patterns: list[dict] | None) -> str:
    """Render user-selected design patterns as a bulleted prompt block.

    Each pattern gets ``- <title>: <summary>`` plus an ``(implies: ...)``
    tail when the pattern JSON already carries a ``design_hint`` /
    ``implication`` — the LLM is otherwise left to infer the design
    reading itself.

    Empty / missing input returns an empty string so callers can just
    concatenate the result unconditionally.
    """
    if not isinstance(patterns, list) or not patterns:
        return ""
    lines: list[str] = [
        "\nUSER-SELECTED DESIGN PATTERNS. Reflect each one in your vocab "
        "decisions where it applies — pick section shapes, empty-state "
        "copy, and component preferences that make the pattern visible "
        "in the finished app:",
    ]
    for p in patterns:
        if isinstance(p, str):
            name = p.strip()
            if name:
                lines.append(f"  - {name}")
            continue
        if not isinstance(p, dict):
            continue
        name = str(
            p.get("title") or p.get("name") or p.get("id") or "",
        ).strip()
        if not name:
            continue
        summary = str(
            p.get("summary") or p.get("description") or "",
        ).strip()
        line = f"  - {name}"
        if summary:
            line += f": {summary}"
        lines.append(line)
        hint = p.get("design_hint") or p.get("implication") or p.get("implies")
        if isinstance(hint, str) and hint.strip():
            lines.append(f"    (implies: {hint.strip()})")
    if len(lines) == 1:
        return ""
    return "\n".join(lines) + "\n"


def _format_library_manifest_block(manifest: dict | None) -> str:
    """Render the compact library manifest as an LLM-friendly table.

    Empty / missing input returns an empty string so callers can just
    concatenate the result unconditionally. The rendered block lists
    every registered component so the LLM can point ``primary_component``
    at any real library name — no free-form invention.
    """
    if not isinstance(manifest, dict):
        return ""
    comps = manifest.get("components")
    if not isinstance(comps, dict) or not comps:
        return ""
    lines: list[str] = [
        "\nLIBRARY COMPONENTS AVAILABLE (name -> category / data_shape / summary):",
    ]
    for name in sorted(comps.keys()):
        entry = comps[name]
        if not isinstance(entry, dict):
            continue
        cat = entry.get("category", "")
        shape = entry.get("data_shape", "")
        summary = entry.get("summary", "")
        lines.append(f"  - {name} -> {cat} / {shape} / {summary}")
    lines.append(
        "\nFor any entity where the domain has a strong preference for a "
        "specific component (not just its shape), you MAY add "
        '`primary_component: "<ExactName>"` to that entity\'s '
        "ComponentPreference. It must be a name that appears in the table "
        "above. Otherwise leave `primary_component` empty and the composer "
        "will use the shape's default component.\n"
    )
    return "\n".join(lines) + "\n"


def _variance_line(variance_seed: str | int | None) -> str:
    """One-line prompt fragment describing the variance token."""
    if variance_seed is None:
        return ""
    seed_str = str(variance_seed).strip()
    if not seed_str:
        return ""
    return (
        f"\nVARIANCE TOKEN: {seed_str}. Use this seed to introduce "
        "controlled variability across otherwise-equivalent choices — "
        "section orderings, empty-state phrasings, secondary vocab picks. "
        "It never overrides a hard constraint (allowlists, contrast bars) "
        "or the primary_vocab / primary_preset selection.\n"
    )


def _build_prompt(
    candidates: list[ArchetypeVocabulary],
    candidate_presets: list[VisualLock],
    plan: dict,
    brief: Any | None,
    patterns: list[dict] | None = None,
    variance_seed: str | int | None = None,
    library_manifest_compact: dict | None = None,
    requirement: str = "",
) -> str:
    plan_slice = _summarize_plan(plan)
    ident = _summarize_brief_identity(brief)
    vocabs_json = json.dumps(
        [_serialize_vocab(v) for v in candidates], indent=2, sort_keys=True,
    )
    presets_json = json.dumps(
        [_serialize_preset(p) for p in candidate_presets], indent=2, sort_keys=True,
    )
    font_allow = sorted(_preset_font_allowlist(candidate_presets))

    parts: list[str] = []
    if requirement:
        parts.append(
            "## WHAT THIS APP MUST DO (the user's own words — authoritative)\n"
            + requirement[:4000].strip()
            + "\n\nCompose FOR THIS. The candidate pool below was assembled "
            "by keyword similarity, which is a coarse instrument — where a "
            "candidate's conventions serve the requirement above, take them; "
            "where they don't, drop them. If the requirement names a screen, "
            "a metric, a column or an action, the composed vocabulary must "
            "be able to express it. Do not blend candidates evenly just "
            "because they scored similarly.\n"
        )
    parts.append(
        "You are composing ONE coherent app-design vocabulary and visual "
        "identity from a pool of candidate vocabularies and visual-lock "
        "presets.\n"
        "\n"
        "Your job is to HARMONIZE, not concatenate. The product must feel "
        "like ONE app with ONE dominant voice — not a mashup. Pick ONE "
        "primary vocabulary and ONE primary preset as the anchor; let the "
        "other candidates contribute ONLY where they add domain-specific "
        "specialization the primary lacks.\n"
    )
    parts.append(
        "\nAUTHORITY — you may:\n"
        "  * ADD sections/personas/component_prefs/statuses/empty_states\n"
        "    the primary doesn't cover but the app actually needs.\n"
        "  * REMOVE candidate entries that don't fit the plan's real "
        "entities/actors (send an explicit `remove` block).\n"
        "  * RENAME sections and unify status vocabulary for consistency.\n"
        "  * CHERRY-PICK palette hexes AND typography families across "
        "candidate presets (e.g. primary's `bg`+`fg` + secondary's "
        "`accent` if it specializes better).\n"
    )
    parts.append(
        "\nHARD CONSTRAINTS (violations are dropped by the merge validator):\n"
        f"  - Component shapes MUST be one of: {sorted(KNOWN_SHAPES)!r}\n"
        f"  - Badge variants MUST be one of: {sorted(_VALID_BADGE_VARIANTS)!r}\n"
        "  - Palette: you MAY propose novel hex values (they are NOT "
        "restricted to the candidate preset palettes). Every hex you "
        "propose must clear WCAG AA contrast against the composite bg "
        "(fg >= 4.5:1; accent + badge >= 3.0:1) and stay within the "
        "app's tone — calm / professional / clinical briefs cap "
        "saturation at ~55%; bold / playful / energetic briefs may go "
        "up to ~95%; the default cap is ~75%. Hexes that fail the "
        "check are replaced with the primary preset's slot value.\n"
        "  - Typography families MUST come from this allowlist (DO NOT "
        f"name a novel font family):\n    {font_allow!r}\n"
        "  - Every section in section_recipes needs BOTH a matching "
        "section_filters entry AND a signature_states['empty_<key>'] "
        "entry — sections missing either are dropped.\n"
        "  - Empty-state copy must share ONE tone across the whole app. "
        "Pick professional / warm / clinical / playful / restrained — one, "
        "then hold it.\n"
    )
    parts.append("\nPRODUCT ASK:\n" + json.dumps(plan_slice, indent=2))
    if ident is not None:
        parts.append("\nBRIEF IDENTITY:\n" + json.dumps(ident, indent=2))
    locked_paths = sorted(set(_get_locked_paths(brief)))
    lock_desc = ", ".join(locked_paths) if locked_paths else "none"
    parts.append(
        "\nUSER-LOCKED VISUAL-LOCK FIELDS (must not be overridden): "
        f"{lock_desc}. You may propose values for other fields freely, "
        "but do not attempt to change locked ones — any proposal for a "
        "locked path will be discarded by the validator.\n"
    )
    patterns_block = _format_patterns_block(patterns)
    if patterns_block:
        parts.append(patterns_block)
    variance_block = _variance_line(variance_seed)
    if variance_block:
        parts.append(variance_block)
    library_block = _format_library_manifest_block(library_manifest_compact)
    if library_block:
        parts.append(library_block)
    parts.append("\nCANDIDATE VOCABULARIES:\n" + vocabs_json)
    parts.append("\nCANDIDATE PRESETS:\n" + presets_json)
    parts.append(
        "\nOUTPUT: pure JSON, no prose, no code fences. Shape:\n"
        "{\n"
        '  "primary_vocab": "<one of the candidate ids>",\n'
        '  "primary_preset": "<one of the candidate preset_names>",\n'
        '  "reasoning": "<one sentence — why this primary, what secondaries add>",\n'
        '  "vocab": {\n'
        '    "primary_screens_per_persona": { "<role>": ["<screen>", ...] },\n'
        '    "section_recipes":             { "<screen>": ["<section>", ...] },\n'
        '    "component_preferences":       { "<entity>": { "shape": "...", "primary_field": "...", "context": "...", "primary_component": "" } },\n'
        '    "signature_states":            { "empty_<key>": "<copy>" },\n'
        '    "status_badges":               { "<status>": { "variant": "...", "label": "..." } },\n'
        '    "section_filters":             { "<section>": { "<col>": ["<val>", ...] } },\n'
        '    "remove":                      { "personas": ["<role>", ...], "screens": ["<screen>", ...] }\n'
        '  },\n'
        '  "visual_lock": {\n'
        '    "palette":    { "bg": "#RRGGBB", "fg": "...", "accent": "...", "muted": "...", "badge": "...", "danger": "...", "success": "...", "subtle": "..." },\n'
        '    "typography": { "display": "...", "body": "...", "mono": "..." },\n'
        '    "radius":     { "sm": 4, "md": 8, "lg": 16 },\n'
        '    "shadow":     { "sm": "...", "md": "..." }\n'
        '  }\n'
        "}\n"
        "Any subset is valid. Omit fields to fall through to the primary's value."
    )
    return "".join(parts)


# --------------------------------------------------------------------- #
# LLM call — mockable seam for tests
# --------------------------------------------------------------------- #

async def _call_llm(prompt: str, *, model: str, timeout_s: float) -> dict | None:
    """Return parsed JSON dict from the LLM, or raise on failure.

    Kept small so tests replace it with an async fake. Callers wrap this
    in the fail-open guard — they log warnings on exceptions and fall
    back to the single-vocab modifier.
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
        max_tokens=6000,
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
    if text.startswith("```"):
        text = text.strip("`")
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

def _pick_primary_vocab(
    candidates: list[ArchetypeVocabulary],
    llm_primary_id: str | None,
) -> ArchetypeVocabulary:
    """Resolve the LLM's declared primary or default to candidates[0]."""
    if isinstance(llm_primary_id, str) and llm_primary_id.strip():
        want = llm_primary_id.strip().lower()
        for c in candidates:
            if (c.id or "").strip().lower() == want:
                return c
    return candidates[0]


def _pick_primary_preset(
    candidate_presets: list[VisualLock],
    llm_primary_name: str | None,
) -> VisualLock:
    """Resolve the LLM's declared primary preset or default to first."""
    if isinstance(llm_primary_name, str) and llm_primary_name.strip():
        want = llm_primary_name.strip().lower()
        for p in candidate_presets:
            if (p.preset_name or "").strip().lower() == want:
                return p
    return candidate_presets[0]


def _tone_warning(states: dict) -> str | None:
    """Very rough tone heuristic — flag when copy mixes exclamation-heavy
    and question-heavy tones across too many entries. Cheap and lossy —
    the composer treats this as a soft signal, not a hard reject."""
    exclaim = 0
    question = 0
    plain = 0
    for v in states.values():
        if not isinstance(v, str):
            continue
        if "!" in v:
            exclaim += 1
        elif "?" in v:
            question += 1
        else:
            plain += 1
    styles = sum(1 for x in (exclaim, question, plain) if x > 0)
    if styles > 2 and exclaim > 0 and question > 0 and plain > 0:
        return (
            f"empty-state tone mixed — {exclaim} exclamations, "
            f"{question} questions, {plain} plain across {len(states)} entries"
        )
    return None


def _merge_and_validate(
    candidates: list[ArchetypeVocabulary],
    candidate_presets: list[VisualLock],
    llm_data: dict,
    brief: Any | None = None,
    library_manifest_compact: dict | None = None,
) -> tuple[ArchetypeVocabulary, VisualLock, dict, str, str]:
    """Union + validate LLM payload against the candidate pool.

    Returns ``(composite_vocab, composite_visual_lock, changes,
    primary_vocab_id, primary_preset_name)``.

    Merge order (each step's output feeds the next):
      1. Resolve primary vocab + primary preset from the LLM's picks
         (or default to candidates[0] / candidate_presets[0]).
      2. Add: LLM entries union with the primary as base.
      3. Remove: honor explicit `remove` block but never drop the last
         persona/screen (guard).
      4. Shape validation: reject entries outside KNOWN_SHAPES.
      5. Badge validation: reject variants outside the allowlist.
      6. Section invariant: sections without filter + empty-state
         are dropped and warnings logged.
      7. Hex validation: reject palette hexes outside the candidate
         preset union; replace with the primary_preset's slot.
      8. Font validation: reject fonts outside the candidate preset
         union; replace with the primary_preset's slot.
      9. Coherence heuristic: soft warning on mixed empty-state tone.
    """
    changes: dict[str, Any] = {
        "sections_added": [],
        "sections_removed": [],
        "personas_added": [],
        "personas_removed": [],
        "shapes_rejected": [],
        "hexes_rejected": [],
        "fonts_rejected": [],
        "locked_field_kept": [],
        "primary_component_rejected": [],
        "warnings": [],
    }
    if not isinstance(llm_data, dict):
        llm_data = {}

    primary_vocab = _pick_primary_vocab(candidates, llm_data.get("primary_vocab"))
    primary_preset = _pick_primary_preset(candidate_presets, llm_data.get("primary_preset"))

    vocab_payload = llm_data.get("vocab") if isinstance(llm_data.get("vocab"), dict) else {}
    lock_payload = llm_data.get("visual_lock") if isinstance(llm_data.get("visual_lock"), dict) else {}

    # -- 2a. Personas: union of primary + LLM ------------------------
    personas = dict(primary_vocab.primary_screens_per_persona)
    llm_personas = vocab_payload.get("primary_screens_per_persona") or {}
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

    # -- 2b. signature_states union ----------------------------------
    signature_states = dict(primary_vocab.signature_states)
    llm_states = vocab_payload.get("signature_states") or {}
    if isinstance(llm_states, dict):
        for k, v in llm_states.items():
            if isinstance(k, str) and isinstance(v, str) and v.strip():
                signature_states[k.strip()] = v.strip()

    # -- 2c. section_filters union -----------------------------------
    section_filters = dict(primary_vocab.section_filters)
    llm_filters = vocab_payload.get("section_filters") or {}
    if isinstance(llm_filters, dict):
        for k, v in llm_filters.items():
            if not isinstance(k, str) or not k.strip():
                continue
            if not isinstance(v, dict):
                continue
            section_filters[k.strip()] = v

    # -- 2d. section_recipes + invariant enforcement -----------------
    recipes = dict(primary_vocab.section_recipes)
    llm_recipes = vocab_payload.get("section_recipes") or {}
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
                    if screen not in primary_vocab.section_recipes or (
                        name not in primary_vocab.section_recipes.get(screen, [])
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

    # -- 2e. component_preferences + shape validation ----------------
    prefs = dict(primary_vocab.component_preferences)
    llm_prefs = vocab_payload.get("component_preferences") or {}
    if isinstance(llm_prefs, dict):
        for entity, spec in llm_prefs.items():
            if not isinstance(entity, str) or not entity.strip():
                continue
            if not isinstance(spec, dict):
                continue
            shape = spec.get("shape") or "table"
            if not isinstance(shape, str) or shape not in KNOWN_SHAPES:
                changes["shapes_rejected"].append(f"{entity}:{shape!r}")
                continue
            primary = spec.get("primary_field") or ""
            context = spec.get("context") or ""
            primary_component = spec.get("primary_component") or ""
            prefs[entity.strip()] = ComponentPreference(
                shape=shape,
                primary_field=str(primary) if primary else "",
                context=str(context) if context else "",
                primary_component=str(primary_component) if primary_component else "",
            )

    # -- 2f. status_badges + variant validation ----------------------
    badges = dict(primary_vocab.status_badges)
    llm_badges = vocab_payload.get("status_badges") or {}
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

    # -- 3. Contribute from secondary candidates (fill gaps only) ----
    # For each secondary vocab: add personas/sections/states/prefs/badges
    # that the primary doesn't already have. Keeps the composite feeling
    # like the primary with domain-specific specializations bolted on.
    for sec in candidates[1:]:
        for role, screens in sec.primary_screens_per_persona.items():
            if role not in personas:
                personas[role] = list(screens)
                if role not in changes["personas_added"]:
                    changes["personas_added"].append(role)
        for k, v in sec.signature_states.items():
            signature_states.setdefault(k, v)
        for k, v in sec.section_filters.items():
            section_filters.setdefault(k, v)
        for k, v in sec.status_badges.items():
            badges.setdefault(k, v)
        for k, v in sec.component_preferences.items():
            prefs.setdefault(k, v)

    # -- 4. Remove block — LLM may prune entries that don't fit ------
    remove = vocab_payload.get("remove") if isinstance(vocab_payload.get("remove"), dict) else {}
    to_remove_personas = remove.get("personas") or []
    if isinstance(to_remove_personas, list) and personas:
        for r in to_remove_personas:
            if not isinstance(r, str):
                continue
            if r in personas and len(personas) > 1:
                del personas[r]
                changes["personas_removed"].append(r)
            elif r in personas:
                changes["warnings"].append(
                    f"refused to remove last persona {r!r}"
                )
    to_remove_screens = remove.get("screens") or []
    if isinstance(to_remove_screens, list) and recipes:
        for s in to_remove_screens:
            if not isinstance(s, str):
                continue
            if s in recipes and len(recipes) > 1:
                del recipes[s]
                changes["sections_removed"].append(s)
            elif s in recipes:
                changes["warnings"].append(
                    f"refused to remove last section-recipe {s!r}"
                )

    # -- 5. Composite vocab id ---------------------------------------
    if len(candidates) == 1:
        composite_id = primary_vocab.id
    else:
        others = [c.id for c in candidates if c.id != primary_vocab.id][:2]
        pieces = [primary_vocab.id] + others
        composite_id = "-".join(pieces) + "-composite"

    # Dashboard + page recipes merge the same way component_preferences
    # do: the primary archetype wins, secondaries fill gaps. Omitting
    # them here silently emptied both fields for every composed app.
    dashboard_recipe = dict(primary_vocab.dashboard_recipe or {})
    page_recipes = dict(primary_vocab.page_recipes or {})
    for cand in candidates:
        if cand is primary_vocab:
            continue
        for k, v in (cand.dashboard_recipe or {}).items():
            dashboard_recipe.setdefault(k, v)
        for k, v in (cand.page_recipes or {}).items():
            page_recipes.setdefault(k, v)

    composite_vocab = ArchetypeVocabulary(
        id=composite_id,
        primary_screens_per_persona=personas,
        section_recipes=recipes,
        component_preferences=prefs,
        signature_states=signature_states,
        status_badges=badges,
        section_filters=section_filters,
        dashboard_recipe=dashboard_recipe,
        page_recipes=page_recipes,
    )

    # -- 6. Visual lock: cherry-pick + validate ----------------------
    font_allow = _preset_font_allowlist(candidate_presets)

    palette = dict(primary_preset.palette)
    llm_palette = lock_payload.get("palette") if isinstance(lock_payload.get("palette"), dict) else {}

    # Composite bg is decided FIRST so downstream slots contrast-check
    # against the actual bg the app will render, not primary_preset.bg.
    if "bg" in llm_palette and isinstance(llm_palette.get("bg"), str):
        proposed_bg = llm_palette["bg"].strip()
        if parse_hex(proposed_bg) is not None:
            palette["bg"] = proposed_bg
        elif proposed_bg:
            changes["hexes_rejected"].append(
                f"bg:{proposed_bg} (invalid hex format)"
            )

    register_val = None
    if brief is not None:
        identity = getattr(brief, "identity", None)
        if identity is not None:
            register_val = getattr(identity, "register", None)
            if register_val is None and isinstance(identity, dict):
                register_val = identity.get("register")
    sat_cap = saturation_cap_for_register(register_val)

    composite_bg = palette.get("bg", "")

    for slot, hex_val in llm_palette.items():
        if slot == "bg":
            continue  # already handled above
        if not isinstance(slot, str) or not isinstance(hex_val, str):
            continue
        candidate_hex = hex_val.strip()
        if not candidate_hex:
            continue

        rgb = parse_hex(candidate_hex)
        if rgb is None:
            changes["hexes_rejected"].append(
                f"{slot}:{candidate_hex} (invalid hex format)"
            )
            continue

        # Contrast check — only for slots that participate in text or
        # UI-component contrast. subtle/muted/danger/success are
        # allowed to be near-bg or vivid respectively; the composer
        # does not police them.
        min_ratio = _PALETTE_CONTRAST_MIN.get(slot)
        if min_ratio is not None and composite_bg:
            ratio = contrast_ratio(candidate_hex, composite_bg)
            if ratio < min_ratio:
                changes["hexes_rejected"].append(
                    f"{slot}:{candidate_hex} (contrast {ratio:.2f}:1 "
                    f"< {min_ratio:.1f}:1 vs bg {composite_bg})"
                )
                continue

        # Saturation cap — only for accent-y slots (accent, badge).
        # bg/fg/muted/subtle are free-form; enforcing saturation there
        # would bar legitimate deep-text or neutral surfaces.
        if slot in ("accent", "badge"):
            sat = saturation(rgb)
            if sat > sat_cap:
                changes["hexes_rejected"].append(
                    f"{slot}:{candidate_hex} (saturation {sat:.2f} "
                    f"> cap {sat_cap:.2f} for register)"
                )
                continue

        palette[slot] = candidate_hex

    typography = dict(primary_preset.typography)
    llm_typography = lock_payload.get("typography") if isinstance(lock_payload.get("typography"), dict) else {}
    for slot, font in llm_typography.items():
        if not isinstance(slot, str) or not isinstance(font, str):
            continue
        candidate = font.strip()
        if not candidate:
            continue
        if candidate in font_allow:
            typography[slot] = candidate
        else:
            changes["fonts_rejected"].append(f"{slot}:{candidate}")

    # Radius / shadow: not on the allowlist (they're numeric / CSS
    # strings; the presets differ enough that a hard allowlist would
    # be too brittle). Prefer the primary_preset outright.
    radius = dict(primary_preset.radius)
    shadow = dict(primary_preset.shadow)

    # Composite preset name — if the palette matches a candidate preset
    # verbatim, keep that name; else synthesize.
    composite_preset_name = ""
    for p in candidate_presets:
        if p.palette == palette:
            composite_preset_name = p.preset_name
            break
    if not composite_preset_name:
        if len(candidate_presets) == 1:
            composite_preset_name = primary_preset.preset_name
        else:
            other_names = [
                p.preset_name for p in candidate_presets
                if p.preset_name and p.preset_name != primary_preset.preset_name
            ][:1]
            pieces = [primary_preset.preset_name] + other_names
            composite_preset_name = "-".join(p for p in pieces if p) + "-composite"

    composite_lock = VisualLock(
        palette=palette,
        typography=typography,
        radius=radius,
        shadow=shadow,
        preset_name=composite_preset_name,
    )

    # -- 6b. primary_component validation (CREATIVE-5b) --------------
    # Runs after component_preferences are assembled. Drops LLM
    # nominations of specific library components that either don't
    # exist or can't render the chosen collection shape.
    composite_vocab = _validate_primary_component(
        composite_vocab, library_manifest_compact, changes,
    )

    # -- 7. User-pinned lock enforcement (CREATIVE-4) ----------------
    # Runs AFTER hex + font validation: the user's chosen values are
    # the final authority on the composite even if WCAG would nag —
    # respect the aesthetic, log the tension.
    composite_lock = _apply_locked_fields(
        composite_lock, brief, primary_preset, changes,
    )

    # -- 8. Coherence heuristic on empty states ----------------------
    warn = _tone_warning(signature_states)
    if warn:
        changes["warnings"].append(warn)

    return (
        composite_vocab,
        composite_lock,
        changes,
        primary_vocab.id,
        primary_preset.preset_name,
    )


# --------------------------------------------------------------------- #
# Public entrypoint
# --------------------------------------------------------------------- #

async def compose_vocab_and_design(
    candidates: list[ArchetypeVocabulary],
    candidate_presets: list[VisualLock],
    plan: dict,
    brief: Any | None = None,
    *,
    patterns: list[dict] | None = None,
    variance_seed: str | int | None = None,
    library_manifest_compact: dict | None = None,
    requirement: str = "",
    model: str = DEFAULT_MODEL,
    timeout_s: float = 60.0,
) -> tuple[ArchetypeVocabulary, VisualLock, dict]:
    """Return ``(composite_vocab, composite_visual_lock, provenance)``.

    Fail-open cascade: any LLM/parse/merge exception falls back to the
    single-vocab modifier on ``candidates[0]``; if that also fails, the
    base candidate + primary_preset are returned untouched. Never raises.

    Provenance shape::

        {
            "source": "composed" | "cached" | "single_fallback" | "base_fallback",
            "candidates": [vocab_id, ...],
            "preset_source": "picked_wholesale" | "cherry_picked" | "single",
            "primary_vocab": str,
            "primary_preset": str,
            "changes": {
                "sections_added":  [...], "sections_removed": [...],
                "personas_added":  [...], "personas_removed": [...],
                "shapes_rejected": [...], "hexes_rejected": [...],
                "fonts_rejected":  [...], "warnings":        [...],
            },
            "reason": str | None,  # populated on fallback
            "reasoning": str | None,  # LLM's one-sentence rationale
        }
    """
    if not candidates:
        raise ValueError("compose_vocab_and_design requires ≥1 candidate vocab")
    if not candidate_presets:
        raise ValueError("compose_vocab_and_design requires ≥1 candidate preset")

    key = cache_key(
        candidates, candidate_presets, plan, brief,
        patterns=patterns, variance_seed=variance_seed,
        library_manifest_compact=library_manifest_compact,
    )
    cached = _MEMO_CACHE.get(key)
    if cached is not None:
        v, l, prov = cached
        return v, l, {**prov, "source": "cached"}

    try:
        prompt = _build_prompt(
            candidates, candidate_presets, plan, brief,
            patterns=patterns, variance_seed=variance_seed,
            library_manifest_compact=library_manifest_compact,
            requirement=requirement,
        )
        llm_data = await _call_llm(prompt, model=model, timeout_s=timeout_s)
        if not isinstance(llm_data, dict):
            raise RuntimeError("LLM returned non-object JSON")
        (
            vocab, lock, changes, primary_vocab_id, primary_preset_name,
        ) = _merge_and_validate(
            candidates, candidate_presets, llm_data, brief=brief,
            library_manifest_compact=library_manifest_compact,
        )
        # Decide preset_source: wholesale if the composite palette equals a
        # single candidate preset; cherry_picked otherwise; single if only
        # one preset was provided.
        if len(candidate_presets) == 1:
            preset_source = "single"
        elif any(p.palette == lock.palette for p in candidate_presets):
            preset_source = "picked_wholesale"
        else:
            preset_source = "cherry_picked"
        reasoning = llm_data.get("reasoning") if isinstance(llm_data.get("reasoning"), str) else None
        prov = {
            "source": "composed",
            "candidates": [c.id for c in candidates],
            "preset_source": preset_source,
            "primary_vocab": primary_vocab_id,
            "primary_preset": primary_preset_name,
            "changes": changes,
            "reason": None,
            "reasoning": reasoning,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[vocab-composer] candidates=%s single_fallback reason=%s",
            [c.id for c in candidates], exc,
        )
        # Cascade 1: single-vocab modifier on top candidate. ``modify_vocab``
        # is itself fail-open — a ``source: "base_fallback"`` result signals
        # that the modifier also couldn't produce a real modification, so
        # we escalate to Cascade 2 in that case.
        try:
            modified, mod_prov = await modify_vocab(candidates[0], plan, brief)
            if (mod_prov or {}).get("source") == "base_fallback":
                raise RuntimeError(
                    f"single-vocab modifier fell open: {mod_prov.get('reason')}"
                )
            prov = {
                "source": "single_fallback",
                "candidates": [c.id for c in candidates],
                "preset_source": "single",
                "primary_vocab": candidates[0].id,
                "primary_preset": candidate_presets[0].preset_name,
                "changes": mod_prov.get("changes") or {},
                "reason": str(exc),
                "reasoning": None,
            }
            return modified, candidate_presets[0], prov
        except Exception as exc2:  # noqa: BLE001
            # Cascade 2: return base untouched.
            logger.warning(
                "[vocab-composer] candidates=%s base_fallback reason=%s",
                [c.id for c in candidates], exc2,
            )
            prov = {
                "source": "base_fallback",
                "candidates": [c.id for c in candidates],
                "preset_source": "single",
                "primary_vocab": candidates[0].id,
                "primary_preset": candidate_presets[0].preset_name,
                "changes": {},
                "reason": f"{exc}; then {exc2}",
                "reasoning": None,
            }
            return candidates[0], candidate_presets[0], prov

    # Bounded LRU — evict oldest if over cap.
    if len(_MEMO_CACHE) >= _MEMO_MAX:
        try:
            first_key = next(iter(_MEMO_CACHE))
            _MEMO_CACHE.pop(first_key, None)
        except StopIteration:
            pass
    _MEMO_CACHE[key] = (vocab, lock, prov)
    return vocab, lock, prov


__all__ = [
    "cache_key",
    "compose_vocab_and_design",
]
