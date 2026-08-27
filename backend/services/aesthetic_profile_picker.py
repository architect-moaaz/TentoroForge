"""IRF-M6-T3 — pick an aesthetic profile from plan.app_shape + industry.

Reads the 6 profile JSON files in ``backend/design/aesthetic_profiles/``
and scores each against ``plan.app_shape`` primitives + ``plan.industry``.
Deterministic — same plan → same profile. Never raises: unknown plans
fall back to ``fluent-2`` (neutral enterprise-friendly).

The scoring is intentionally shallow (M6 wires the picker; M6-T9 tunes
rubrics). Each profile declares a ``when_to_use`` block naming the
shape/industry values that favor it; a match on any dimension adds one
point. Highest score wins. Ties break in a stable declared order
(glass-dark → carbon → polaris → material-3 → fluent-2 → clean-editorial).

User override wins: ``plan.aesthetic_profile`` (string) short-circuits
the picker.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_PROFILES_DIR = Path(__file__).resolve().parent.parent / "design" / "aesthetic_profiles"

# Deterministic tie-break order. Carbon was previously 2nd — that caused
# tied-score wins (a yoga app whose density=comfortable matched carbon
# on one dimension AND matched material-3/fluent-2 on one dimension
# would silently land on the industrial IBM-Carbon skin). Demoted to
# last-resort so calm/warm briefs no longer inherit it by tie-break.
# Explicit intent wins via ``plan.aesthetic_profile`` override.
_TIE_BREAK_ORDER = (
    "polaris", "material-3", "fluent-2",
    "clean-editorial", "glass-dark", "carbon",
)

_DEFAULT_PROFILE = "fluent-2"

# Profiles whose skin is sharp / monochrome / high-density / industrial.
# These carry a "workspace/data-grid" aesthetic that reads as brutalist
# on calm-tone briefs. Vetoed when the brief signals warm/soft/friendly
# personality (see :func:`_is_vetoed_by_brief`). Kept as a frozenset so
# new profiles that fit the class can be added without changing logic.
_BRUTALIST_PROFILE_NAMES = frozenset({"carbon"})

# Words on ``brief.identity.visual_stance.principles`` (or on
# ``brief.identity.register``) that signal a warm/calm aesthetic — one
# match plus ``temperature != "cool"`` triggers the brutalist veto.
_CALM_STANCE_WORDS = frozenset({
    "calm", "soft", "warm", "friendly", "playful", "gentle",
    "welcoming", "cozy", "inviting", "organic", "human",
    "wellness", "editorial", "restraint",
})


# ── loaders ─────────────────────────────────────────────────────────


@lru_cache(maxsize=1)
def _load_all_profiles() -> dict[str, dict[str, Any]]:
    """Read every JSON in the profiles dir once. Cached."""
    out: dict[str, dict[str, Any]] = {}
    if not _PROFILES_DIR.is_dir():
        return out
    for p in sorted(_PROFILES_DIR.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.debug("[aesthetic_profile_picker] skip malformed %s", p.name)
            continue
        name = data.get("name") or p.stem
        out[str(name)] = data
    return out


def clear_cache() -> None:
    """Test hook."""
    _load_all_profiles.cache_clear()


def known_profiles() -> tuple[str, ...]:
    """Return every profile name loaded from disk (declared order)."""
    profiles = _load_all_profiles()
    ordered = [n for n in _TIE_BREAK_ORDER if n in profiles]
    # Include any profiles on disk not in the tie-break list
    extras = sorted(set(profiles.keys()) - set(_TIE_BREAK_ORDER))
    return tuple(ordered + extras)


def get_profile(name: str) -> dict[str, Any] | None:
    """Return the profile dict for a given name, or None."""
    return _load_all_profiles().get(name)


# ── scoring ─────────────────────────────────────────────────────────


def _shape_val(plan: Any, *path: str) -> Any:
    """Read plan.app_shape.<path[0]>.<path[1]>... — None on any miss."""
    if not isinstance(plan, dict):
        return None
    node: Any = plan.get("app_shape")
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


def _score_profile(profile: dict, plan: dict) -> int:
    """Add one point per matched dimension in the profile's when_to_use.

    Supported when_to_use keys (all optional):
      - ``identity.usageMode``: list — matches plan.app_shape.identity.usageMode
      - ``layout.hero_any_of``: list — matches layout.hero
      - ``layout.density_any_of``: list — matches layout.density
      - ``layout.shell_any_of``: list — matches layout.shell
      - ``layout.primaryInteraction_any_of``: list — matches
        layout.primaryInteraction
      - ``industry_any_of``: list — matches plan.industry (case-insensitive
        substring)
    """
    when = profile.get("when_to_use") or {}
    if not isinstance(when, dict):
        return 0
    score = 0

    usage = _shape_val(plan, "identity", "usageMode")
    if isinstance(when.get("identity.usageMode"), list) and usage in when["identity.usageMode"]:
        score += 1

    for key, path in (
        ("layout.hero_any_of", ("layout", "hero")),
        ("layout.density_any_of", ("layout", "density")),
        ("layout.shell_any_of", ("layout", "shell")),
        ("layout.primaryInteraction_any_of", ("layout", "primaryInteraction")),
    ):
        val = _shape_val(plan, *path)
        if isinstance(when.get(key), list) and val in when[key]:
            score += 1

    if isinstance(when.get("industry_any_of"), list):
        industry = (plan.get("industry") if isinstance(plan, dict) else "") or ""
        industry_l = str(industry).lower()
        if any(str(cand).lower() in industry_l for cand in when["industry_any_of"]):
            score += 1

    return score


# ── veto (brief-aware exclusion) ─────────────────────────────────────


def _brief_stance_words(brief: Any) -> tuple[frozenset[str], str | None]:
    """Return (principles+register words, temperature) from the brief.

    Reads ``brief.identity.visual_stance.principles`` +
    ``brief.identity.register`` as a lowercase word set, and
    ``brief.identity.visual_stance.temperature`` as ``warm|cool|neutral|None``.
    Safe on any shape (None / non-dict / missing keys → empty set + None).
    Accepts both dict and pydantic-model briefs by walking attributes /
    keys uniformly.
    """
    def _read(node: Any, key: str) -> Any:
        if isinstance(node, dict):
            return node.get(key)
        return getattr(node, key, None)

    ident = _read(brief, "identity")
    if ident is None:
        return frozenset(), None
    stance = _read(ident, "visual_stance") or {}
    principles = _read(stance, "principles") or []
    register = _read(ident, "register") or []
    temperature = _read(stance, "temperature")
    if isinstance(temperature, str):
        temperature = temperature.strip().lower() or None
    words: set[str] = set()
    for lst in (principles, register):
        if isinstance(lst, (list, tuple)):
            for item in lst:
                if isinstance(item, str):
                    # Split so multi-word / snake_case / hyphen-joined
                    # register values expose their component words.
                    # Real briefs use tokens like ``grounded_calm``,
                    # ``purposeful_clear``, ``warm_precise`` — a plain
                    # whitespace split misses ``calm`` / ``warm``, which
                    # is exactly what the veto is trying to catch.
                    normalized = (
                        item.lower()
                        .replace(",", " ")
                        .replace("_", " ")
                        .replace("-", " ")
                        .replace("/", " ")
                    )
                    for w in normalized.split():
                        if w:
                            words.add(w)
    return frozenset(words), temperature


def _is_vetoed_by_brief(profile_name: str, brief: Any) -> bool:
    """Return True when ``profile_name`` clashes with the brief's tone.

    Currently the only vetoed class is BRUTALIST (carbon-like) profiles
    on briefs that read as calm / warm / friendly. Two ways a brief
    triggers the veto:

    - ``visual_stance.temperature == "warm"`` (any calm-word support
      is optional)
    - ``visual_stance.temperature != "cool"`` AND at least one
      calm/warm word appears in ``principles`` or ``identity.register``

    Cool-tempered briefs never trigger the veto (a "cool minimalist"
    brief may legitimately want carbon). Missing brief → no veto (the
    picker stays permissive when it has no signal to reject on).
    """
    if not brief or profile_name not in _BRUTALIST_PROFILE_NAMES:
        return False
    words, temperature = _brief_stance_words(brief)
    if temperature == "warm":
        return True
    if temperature == "cool":
        return False
    return bool(words & _CALM_STANCE_WORDS)


# ── public API ──────────────────────────────────────────────────────


def pick(plan: Any, brief: Any = None) -> str:
    """Return the name of the aesthetic profile best matching ``plan``.

    Priority order:
    1. ``plan.aesthetic_profile`` explicit override (if known — the
       override bypasses the veto by design: an author asking for
       carbon on a wellness app gets carbon).
    2. Highest ``when_to_use`` score across loaded profiles, MINUS
       any profile vetoed by the brief (see :func:`_is_vetoed_by_brief`).
    3. Tie-break via ``_TIE_BREAK_ORDER``.
    4. Fallback: ``fluent-2`` (or the first known profile when
       fluent-2 isn't loaded).

    ``brief`` is optional — callers with output_dir should load it
    via ``design_brief_to_prompt.load_brief_from_disk`` and pass it
    in. When absent, the picker behaves as before (no veto).
    """
    profiles = _load_all_profiles()
    if not profiles:
        return _DEFAULT_PROFILE

    # 1. Explicit override — bypasses the veto (author intent wins).
    if isinstance(plan, dict):
        override = plan.get("aesthetic_profile")
        if isinstance(override, str) and override.strip() in profiles:
            return override.strip()

    # 2. Score every profile, then drop vetoed ones from the candidate
    #    pool. Vetoed profiles are logged so we can tune the rules from
    #    real regen output later.
    scored: list[tuple[str, int]] = []
    vetoed: list[str] = []
    for name, profile in profiles.items():
        if _is_vetoed_by_brief(name, brief):
            vetoed.append(name)
            continue
        scored.append((name, _score_profile(profile, plan if isinstance(plan, dict) else {})))
    if vetoed:
        logger.info("[aesthetic_profile_picker] veto (brief tone): %s", vetoed)

    # If the veto emptied the pool (shouldn't happen with current rules
    # but stays safe), fall back to the default profile.
    if not scored:
        return _DEFAULT_PROFILE if _DEFAULT_PROFILE in profiles else next(iter(profiles.keys()))

    # 3. Highest score; stable tie-break by _TIE_BREAK_ORDER
    max_score = max((s for _, s in scored), default=0)
    if max_score == 0:
        # No signal — return default
        if _DEFAULT_PROFILE in profiles:
            return _DEFAULT_PROFILE
        return next(iter(profiles.keys()))

    winners = {name for name, s in scored if s == max_score}
    for candidate in _TIE_BREAK_ORDER:
        if candidate in winners:
            return candidate
    return sorted(winners)[0]


def pick_profile(plan: Any, brief: Any = None) -> dict[str, Any]:
    """Return the full profile dict for ``pick(plan, brief)``.

    Never None — always returns a dict, even for empty plans (fallback
    profile). Callers that need just the name should call ``pick()``.
    """
    name = pick(plan, brief=brief)
    return get_profile(name) or {}


__all__ = [
    "pick",
    "pick_profile",
    "known_profiles",
    "get_profile",
    "clear_cache",
]
