"""Archetype classifier — pick the best-fit archetype for a prompt.

Deterministic keyword-scoring. Each registered archetype scores +1 for
every KEYWORDS entry that appears as a substring of the lowercased
prompt (case-insensitive; whole-substring match so "compare prices"
counts even inside "we compare prices across retailers").

The archetype with the highest score wins IF it clears the minimum
threshold (2 distinct keyword hits by default — one signal is too weak
and produces false positives on ambient words). Ties broken by the
order the archetype was registered in services/archetypes/__init__.py.

No LLM. Cheap. Safe to call on every generation.
"""
from __future__ import annotations

import logging

from services.archetypes import all_archetypes, get_archetype

logger = logging.getLogger(__name__)

_DEFAULT_THRESHOLD = 2


def detect_archetype(prompt: str, min_score: int = _DEFAULT_THRESHOLD) -> str | None:
    """Return the winning archetype's NAME or None.

    None is a real answer — many prompts don't fit any archetype and
    should flow through the freeform pipeline. Callers should NOT default
    to an archetype when the classifier declines.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    lp = prompt.lower()
    best_name: str | None = None
    best_score = 0
    for mod in all_archetypes():
        keywords = getattr(mod, "KEYWORDS", []) or []
        # Count each keyword at most once, even if it appears multiple times.
        hits = sum(1 for kw in keywords if kw.lower() in lp)
        if hits >= min_score and hits > best_score:
            best_score = hits
            best_name = getattr(mod, "NAME", None)
    if best_name:
        logger.info(
            "[archetype-detector] matched %s (score=%d) for prompt: %s",
            best_name, best_score, prompt[:80].replace("\n", " "),
        )
    return best_name


def apply_archetype_to_spec(
    spec,
    archetype_name: str,
    *,
    renames: dict[str, str] | None = None,
    extra_entities: list[dict] | None = None,
):
    """Union an archetype's defaults into a LockedSpec, applying LLM
    refinements when provided.

    Rules:
      - Actors, entities, features, externals from the archetype are added
        if not already present (dedup by name/role/provider).
      - Entities appearing in the archetype's ANTI_ENTITIES are REMOVED
        from the spec — this is how "user mentions product → forge_cart"
        gets suppressed for a comparison-only archetype.
      - The archetype's kind classification for an entity WINS over the
        extractor's guess (so "Scan" is guaranteed "event" even if the
        heuristic misfires).
      - `renames` (from classify_app_archetype's LLM pass) rewrite every
        archetype default AND every existing spec entry so a downstream
        pipeline that sees "ArtworkScan" instead of "Scan" produces
        domain-fitting names. Applied to entity names, feature target
        entities, and feature names embedded with the old name.
      - `extra_entities` are unioned into the spec after the archetype
        defaults — the LLM can propose entities the archetype didn't cover
        without breaking the closed catalog contract.

    Returns the mutated spec for chaining. Safe to call with an unknown
    archetype name (no-op) and safe to call twice (idempotent because
    every step dedups by name).
    """
    from services.locked_spec import Actor, Entity, ExternalDep, Feature

    mod = get_archetype(archetype_name)
    if mod is None:
        return spec

    # ANTI_ENTITIES first — never keep a rejected entity around.
    anti = {n.lower() for n in getattr(mod, "ANTI_ENTITIES", []) or []}
    if anti:
        spec.entities = [e for e in spec.entities if e.name.lower() not in anti]

    # Actors — union by role.
    have_roles = {a.role for a in spec.actors}
    for a in getattr(mod, "DEFAULT_ACTORS", []) or []:
        role = a.get("role")
        if role and role not in have_roles:
            spec.actors.append(Actor(
                role=role,
                permissions_hint=list(a.get("permissions_hint") or []),
            ))
            have_roles.add(role)

    # Entities — union by name, and archetype kind WINS if there's an overlap.
    by_name = {e.name.lower(): e for e in spec.entities}
    for e in getattr(mod, "DEFAULT_ENTITIES", []) or []:
        name = e.get("name")
        if not name:
            continue
        kind = e.get("kind", "entity")
        card = e.get("cardinality", "many")
        if name.lower() in by_name:
            # Archetype's kind overrides the extractor's guess.
            by_name[name.lower()].kind = kind
        else:
            new_e = Entity(name=name, kind=kind, cardinality=card)
            spec.entities.append(new_e)
            by_name[name.lower()] = new_e

    # Features — union by (actor, verb, target).
    have_features = {(f.actor, f.verb, f.target_entity) for f in spec.features}
    for f in getattr(mod, "DEFAULT_FEATURES", []) or []:
        key = (f.get("actor"), f.get("verb"), f.get("target_entity"))
        if key in have_features:
            continue
        spec.features.append(Feature(
            name=f.get("name") or f"{f.get('verb')}-{(f.get('target_entity') or 'x')}",
            actor=f.get("actor") or "user",
            verb=f.get("verb") or "view",
            target_entity=f.get("target_entity"),
        ))
        have_features.add(key)

    # Externals — union by provider.
    have_providers = {x.provider for x in spec.externals}
    for x in getattr(mod, "EXTERNALS", []) or []:
        provider = x.get("provider")
        if provider and provider not in have_providers:
            spec.externals.append(ExternalDep(
                type=x.get("type") or "api",
                provider=provider,
            ))
            have_providers.add(provider)

    # LLM renames — after everything else, so the archetype's defaults are
    # already in place. Rewrite entity names, feature target_entity refs,
    # and any feature.name that embedded the old name.
    if renames:
        # Entity renames (case-preserving via original casing in `renames`).
        for e in spec.entities:
            if e.name in renames:
                e.name = renames[e.name]
        # Rebuild by_name so extras below dedup against renamed entries.
        by_name = {e.name.lower(): e for e in spec.entities}
        # Feature target_entity + feature.name.
        for f in spec.features:
            if f.target_entity and f.target_entity in renames:
                new_target = renames[f.target_entity]
                # Rewrite embedded old name in the feature name.
                if f.target_entity.lower() in f.name.lower():
                    f.name = f.name.replace(
                        f.target_entity.lower(), new_target.lower()
                    )
                f.target_entity = new_target

    # LLM extra_entities — union onto the (now-renamed) entity set.
    if extra_entities:
        by_name = {e.name.lower(): e for e in spec.entities}
        for e in extra_entities:
            if not isinstance(e, dict):
                continue
            name = e.get("name")
            kind = e.get("kind", "entity")
            if not isinstance(name, str) or not name:
                continue
            if name.lower() in by_name:
                continue
            spec.entities.append(Entity(
                name=name,
                kind=kind if kind in {"event", "entity", "role", "external", "derived"} else "entity",
                cardinality=e.get("cardinality", "many"),
            ))
            by_name[name.lower()] = spec.entities[-1]

    return spec


def apply_archetype_match_to_spec(spec, match):
    """Convenience: unpack a classify_app_archetype ArchetypeMatch and call
    apply_archetype_to_spec with renames + extras threaded through. No-op
    when the match's archetype is None."""
    if match is None or getattr(match, "archetype", None) is None:
        return spec
    return apply_archetype_to_spec(
        spec,
        match.archetype,
        renames=match.renames or None,
        extra_entities=match.extra_entities or None,
    )
