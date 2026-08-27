"""Pydantic schema for the design brief.

Every design brief in Forge — hand-authored anchor, LLM-authored, or
user-tweaked — conforms to this shape. Downstream (page/component/figma
agents, critic, token compiler) consumes the same object.

Enum-heavy on purpose: prose in a design brief is the enemy of the
critic and the token compiler. Palette hexes are strings, densities are
enums, signature moves are structured. See
docs/superpowers/specs/2026-08-07-design-brief.md for rationale.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# --------------------------------------------------------------------------- #
# Enums — closed vocabularies
# --------------------------------------------------------------------------- #

class NeutralTint(str, Enum):
    warm = "warm"
    cool = "cool"
    neutral = "neutral"


class Density(str, Enum):
    compact = "compact"
    comfortable = "comfortable"
    spacious = "spacious"
    spacious_for_touch = "spacious_for_touch"


class Radius(str, Enum):
    sharp_2 = "sharp_2"      # 2px — precise, technical
    soft_8 = "soft_8"        # 8px — warm, comfortable
    pill = "pill"            # 999px — bold, playful


class Mode(str, Enum):
    light = "light"
    dark = "dark"


class Voice(str, Enum):
    warm_precise = "warm_precise"
    formal_technical = "formal_technical"
    casual_direct = "casual_direct"
    editorial_quiet = "editorial_quiet"
    bold_fast = "bold_fast"


# --------------------------------------------------------------------------- #
# Spec D Wave 4 — Constrained-enum liberation.
#
# Additive companions to Voice / Radius / Density / NeutralTint. Old code
# reads the enums; new code (Spec C/D) may read the free-form + numeric
# fields when present, fall back to the enum otherwise. Deterministic
# snap-to-nearest helpers live in `brief_to_design_spec` — the LLM
# authors continuous values, the renderer snaps them to renderable
# tokens without discarding the semantic authoring.
#
# Ships behind FORGE_CLEANUP_WAVE_4 gate at the AUTHORING layer (brief
# author populates these when the flag is on); the schema accepts them
# either way so old serialized briefs keep loading. This keeps the
# migration a two-step (schema first, then flip the author) which is
# how every other multi-file rollout has been safe.
# --------------------------------------------------------------------------- #

_VOICE_MAX = 40
_TINT_MAX = 20
_RADIUS_PX_MAX = 32
_DENSITY_PT_MAX = 32


# --------------------------------------------------------------------------- #
# Sub-shapes
# --------------------------------------------------------------------------- #

class Palette(BaseModel):
    brand: str = Field(..., description="Primary action color as #RRGGBB")
    accent: str = Field(..., description="Attention-moments color as #RRGGBB")
    neutrals_base: str = Field(..., description="Base neutral (background) as #RRGGBB")
    neutrals_tint: NeutralTint
    # Spec D Wave 4 — free-form companion (up to 20 chars). Lets the LLM
    # say "cool with green undertone" without lying about the bucket.
    # When present, downstream may prefer it; enum stays the fallback.
    neutrals_tint_free: str | None = Field(None, max_length=_TINT_MAX)
    surface_bg: str = Field(..., description="App background as #RRGGBB")
    surface_elevated: str = Field(..., description="Card/elevated surface as #RRGGBB")
    foreground_primary: str = Field(..., description="Primary text as #RRGGBB")
    foreground_muted: str = Field(..., description="Muted text as #RRGGBB")
    # Spec D Wave 1 (round 2) — optional override for the contrast
    # guardrail's `_fg_for` calc. When the brand+background contrast is
    # ambiguous (e.g. mid-tone brand with a coloured filled button),
    # brief-author may set this to lock the on-brand label colour to
    # a specific hex. Callers prefer it verbatim when set; otherwise
    # `_fg_for` computes from the fill.
    foreground_hint: str | None = Field(
        None,
        description=(
            "Optional #RRGGBB override for the on-brand foreground/label "
            "colour. When set, the contrast guardrail uses it verbatim."
        ),
    )
    # Spec A Slice 6b: fields listed here refuse edits from Smith/editor
    # without an explicit unlock. Populated by brief_from_figma to enforce
    # byte-exact Figma palette fidelity; empty for LLM-authored briefs.
    locked_fields: set[str] = Field(default_factory=set)

    @field_validator(
        "brand", "accent", "neutrals_base", "surface_bg",
        "surface_elevated", "foreground_primary", "foreground_muted",
    )
    @classmethod
    def _hex(cls, v: str) -> str:
        v = v.strip()
        if not (v.startswith("#") and len(v) == 7):
            raise ValueError(f"expected #RRGGBB hex, got {v!r}")
        int(v[1:], 16)  # raises ValueError if not hex digits
        return v.upper()

    @field_validator("foreground_hint")
    @classmethod
    def _fg_hint_hex(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if not (v.startswith("#") and len(v) == 7):
            raise ValueError(f"foreground_hint must be #RRGGBB hex, got {v!r}")
        int(v[1:], 16)
        return v.upper()


class Typography(BaseModel):
    display_family: str
    display_weights: list[int] = Field(default_factory=lambda: [500, 700])
    body_family: str
    body_weights: list[int] = Field(default_factory=lambda: [400, 500, 600])
    utility_family: str | None = None
    scale: str = Field("conservative_1.20", description="Named scale")
    # Spec A Slice 6b — same semantics as Palette.locked_fields.
    locked_fields: set[str] = Field(default_factory=set)

    @field_validator("display_weights", "body_weights")
    @classmethod
    def _weights_valid(cls, v: list[int]) -> list[int]:
        if not v:
            raise ValueError("at least one weight required")
        for w in v:
            if not 100 <= w <= 900 or w % 100 != 0:
                raise ValueError(f"weight {w} not a valid CSS weight (100-900, step 100)")
        return v


class NavLanguage(str, Enum):
    """Spec D Wave 1 (round 2) — the nav-language enum the design_agent
    nav-CSS injection consumes. A brief-authored choice about how loudly
    the app's navigation asserts itself.

      - ``chrome_heavy``  : bold rails, active indicators, visible chrome
      - ``chrome_light``  : quiet rails, subtle active state
      - ``invisible``     : minimize chrome — no per-skin nav CSS block

    When absent from the brief, nav-CSS emission falls back to the
    skin/DNA-driven default (services.design_dna.to_nav_css).
    """
    chrome_heavy = "chrome_heavy"
    chrome_light = "chrome_light"
    invisible = "invisible"


class Layout(BaseModel):
    density: Density
    radius: Radius
    grid: str = "12col"
    whitespace: str = "comfortable"
    # Spec A Slice 6b — same semantics as Palette.locked_fields.
    locked_fields: set[str] = Field(default_factory=set)
    # Spec D Wave 4 — continuous numeric companions to the enum buckets.
    # Optional; when present, downstream renderers prefer them and snap
    # to the nearest CSS token via brief_to_design_spec's snap helpers.
    # When absent, existing density + radius enums drive the mapping.
    radius_px: int | None = Field(None, ge=0, le=_RADIUS_PX_MAX)
    density_pt: int | None = Field(None, ge=0, le=_DENSITY_PT_MAX)
    # Spec D Wave 1 (round 2) — brief-authored nav-language selection.
    # Consumed by design_agent's nav-CSS injection: "invisible" suppresses
    # the per-skin nav block entirely (shell default takes over). Values
    # other than the enum still let the DNA-driven nav CSS run.
    nav_language: NavLanguage | None = None


class SignatureMove(BaseModel):
    kind: str = Field(..., description='Named kind, e.g. "warm_serif_h1"')
    detail: str = Field(..., description="One-line specific detail")


class VisualStance(BaseModel):
    """Spec D Wave 1 — brief-author's structured replacement for the
    ARCHETYPES lookup in ``services/design_dna.py``.

    Every field optional so partial authoring is safe — a brief that
    only knows its hue temperature can populate ``temperature`` and
    leave the rest for later loops. Downstream renderers keep reading
    the ARCHETYPES dict when a field is absent; when present, they
    prefer the brief-authored value.
    """
    hue_range: str | None = Field(
        None, max_length=40,
        description='Free-form hue band, e.g. "cool blues" or "warm earth".',
    )
    temperature: Literal["warm", "cool", "neutral"] | None = None
    shape_vocab: str | None = Field(
        None, max_length=40,
        description='"geometric" | "organic" | "hybrid" | free descriptor.',
    )
    principles: list[str] = Field(
        default_factory=list, max_length=4,
        description='Short design principles, e.g. ["restraint", "precision"].',
    )


class Identity(BaseModel):
    model_config = {"protected_namespaces": ()}

    domain: str = Field(..., description="Classified domain label")
    register: list[str] = Field(..., description="1-2 emotional adjectives")
    voice: Voice
    # Spec D Wave 4 — free-form voice (up to 40 chars). Enum stays as
    # the guaranteed field for old readers; new readers may prefer this
    # when present. Example: "warm and precise, quietly editorial".
    voice_free: str | None = Field(None, max_length=_VOICE_MAX)
    modes: list[Mode] = Field(default_factory=lambda: [Mode.light, Mode.dark])
    # Spec A Slice 6b: where this brief's fields came from. "authored" =
    # LLM synthesis (fields freely editable). "figma" = extracted from a
    # Figma source (locked fields refuse edits without explicit unlock).
    source: Literal["authored", "figma", "screenshot"] = "authored"

    # Spec D Wave 1 — LLM-authored companions to the ARCHETYPES / AUTH_COPY /
    # _BRAND_FRAGMENTS per-industry dicts in services/design_dna.py.
    # All optional so old serialized briefs load unchanged; readers fall
    # back to the archetype/auth-copy dicts when a field is absent.
    visual_stance: VisualStance | None = None
    auth_taglines: list[str] = Field(default_factory=list, max_length=2)
    product_name_candidates: list[str] = Field(default_factory=list, max_length=6)

    # Spec D Wave 1 (round 2) — brief-authored intensity gate for the
    # design_agent's personality-CSS injection. 0.0 suppresses the
    # personality block entirely (quietest possible app); 1.0 emits the
    # loudest variant. When None, the archetype-driven default runs.
    # Numeric so the LLM can author a spectrum, not a bucket.
    tone_intensity: float | None = Field(
        None, ge=0.0, le=1.0,
        description=(
            "0.0 = suppress personality CSS entirely (quiet app); "
            "1.0 = strongest personality; None = archetype default."
        ),
    )

    # Spec D Wave 1 (round 2) — a subset of the compliance regimes the
    # domain_ux_specs' compliance block enumerates. Product designer
    # authors the ones the app actually needs to meet. Downstream
    # (ux_spec_generator, phase_gates) uses this to filter / augment
    # the domain's default requirements set. Common values:
    # ``hipaa`` | ``sox`` | ``gdpr`` | ``pci`` | ``soc2`` | ``ferpa``
    # Free-form list so the vocabulary can grow without a schema bump.
    compliance_flags: list[str] = Field(
        default_factory=list, max_length=8,
        description=(
            "Regulatory regimes the app must observe; supplements or "
            "narrows the domain UX spec's compliance block."
        ),
    )

    @field_validator("register")
    @classmethod
    def _register_len(cls, v: list[str]) -> list[str]:
        if not 1 <= len(v) <= 2:
            raise ValueError("register must have 1 or 2 entries")
        return v

    @field_validator("compliance_flags")
    @classmethod
    def _flags_lowercase(cls, v: list[str]) -> list[str]:
        """Normalize to lowercase, strip whitespace, drop empties/dupes."""
        seen: set[str] = set()
        out: list[str] = []
        for raw in v:
            if raw is None:
                continue
            s = str(raw).strip().lower()
            if not s or s in seen:
                continue
            seen.add(s)
            out.append(s)
        return out


# --------------------------------------------------------------------------- #
# Motion — Spec C4
# --------------------------------------------------------------------------- #

class Motion(BaseModel):
    """Concrete motion values authored by brief-author from identity +
    register. Not an enum bucket — the LLM picks the numbers. A
    formal-technical enterprise brief lands 120/240/480; a playful
    consumer brief might pick 180/320/600 with springier eases.

    brief_to_design_spec copies these verbatim into --motion-* and
    --ease-* CSS variables.
    """
    duration_fast_ms: int = Field(120, ge=40, le=1200)
    duration_medium_ms: int = Field(240, ge=80, le=2000)
    duration_slow_ms: int = Field(480, ge=120, le=4000)
    ease_out: str = "cubic-bezier(0.2, 0.0, 0.0, 1.0)"
    ease_in_out: str = "cubic-bezier(0.4, 0.0, 0.2, 1.0)"
    # Every generated app respects prefers-reduced-motion by default.
    # Setting to false is an explicit opt-out (rare — some data-viz
    # apps depend on their animations to be legible).
    reduce_motion_respect: bool = True


# --------------------------------------------------------------------------- #
# Responsive — Spec C8
# --------------------------------------------------------------------------- #

class Responsive(BaseModel):
    """Concrete responsive-priority intent authored by brief-author from
    discovery signals — field workers get mobile-first, office workers
    get desktop-first, mixed apps get tablet-first.

    layout_variants is an open list; unknown values are validated +
    rejected by the shell composer before they reach the emitted code.
    """
    primary_form_factor: Literal["mobile", "tablet", "desktop"] = "desktop"
    breakpoints_priority: list[Literal["mobile", "tablet", "desktop"]] = Field(
        default_factory=lambda: ["desktop", "tablet", "mobile"],
    )
    # Open list — accepted values (grown one at a time as shell_templates
    # gains variants): bottom_tabs | sidebar_collapse | sidebar_persistent
    # | topbar_persistent | rail_persistent
    layout_variants: list[str] = Field(default_factory=list)

    @field_validator("breakpoints_priority")
    @classmethod
    def _priority_covers_three(cls, v):
        if len(v) != 3 or len(set(v)) != 3:
            raise ValueError("breakpoints_priority must list all 3 form factors, no dupes")
        return v


# --------------------------------------------------------------------------- #
# CTA hierarchy — Spec D Wave 3 (rule-table retirement)
#
# Replaces `services/cta_defaults.py`'s closed `RegisterName` Literal +
# `_PER_REGISTER` lookup with a brief-authored structure. Downstream
# readers (schema_prompt.py, generate.py, design_agent.py) prefer this
# field when present; when absent, they fall back to defaults_for_register.
# Additive: existing briefs without cta_hierarchy load unchanged.
# --------------------------------------------------------------------------- #

class CtaRule(BaseModel):
    """One row of the primary/secondary/tertiary hierarchy."""
    variant: str = Field(..., description="Button variant: primary | secondary | ghost | ...")
    max_per_page: int | None = Field(None, description="Cap on this variant per page; null = unlimited")
    min_per_page: int = Field(0, ge=0, description="Floor for this variant per page")


class CtaHierarchy(BaseModel):
    """Project-wide CTA rhythm. Authored by brief-author from
    identity.voice + register + domain; consumers read it verbatim."""
    primary: CtaRule
    secondary: CtaRule
    tertiary: CtaRule


# --------------------------------------------------------------------------- #
# Content bank — Spec C3
# --------------------------------------------------------------------------- #

class ContentBank(BaseModel):
    """Voice-tuned copy the brief-author generates once from
    identity.voice + register + domain. Deterministic emitters
    (empty states, toast messages, notification templates, CTA labels)
    read from here so the whole app speaks in one voice.

    Every string may contain templates the reader substitutes:
      ``{entity_singular}``, ``{entity_plural}``, ``{query}``,
      ``{task_kind}``, ``{app_name}``.
    Callers pass a substitutions dict; unknown tokens are left in place.
    """
    empty_states: dict[str, str] = Field(default_factory=dict)
    toasts: dict[str, str] = Field(default_factory=dict)
    notifications: dict[str, str] = Field(default_factory=dict)
    cta_verbs: dict[str, str] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Visual Lock — Slice A (2026-08-13)
#
# The problem the lock cures: DesignBrief historically named vague fields
# ("register: grounded_calm", "temperature: warm") that downstream pickers
# (design_language.compose_language, design_dna.derive_design_dna,
# design_compiler.derive_structural_tokens) each re-decided independently.
# Every fix has been symptomatic.
#
# Fix: when the brief carries a VisualLock, downstream readers use its
# EXACT hex/font values instead of re-deriving. Domain-preset picker
# populates the lock at brief-authoring time (visual_lock_presets.py).
#
# Additive + backward compat: an empty VisualLock (default) means "no
# lock" and every existing consumer keeps its current behaviour.
# --------------------------------------------------------------------------- #


class VisualLock(BaseModel):
    """Concrete visual tokens that override downstream derivation.

    An empty lock (default — every field zero-length) means the app is
    NOT locked; readers fall back to today's derivation. When populated,
    downstream consumers must prefer these values verbatim.
    """
    # Palette hex map. Keys (all optional): bg, fg, accent, muted, badge,
    # danger, success, subtle. Values are ``#RRGGBB`` strings — validated
    # at the preset boundary, not here (a partial lock is allowed).
    palette: dict[str, str] = Field(default_factory=dict)
    # Typography map. Keys: display, body, mono. Values are Google Fonts
    # family names (no fallback stack — downstream appends its own).
    typography: dict[str, str] = Field(default_factory=dict)
    # Corner radius in px. Keys: sm, md, lg.
    radius: dict[str, int] = Field(default_factory=dict)
    # Shadow CSS box-shadow strings. Keys: sm, md.
    shadow: dict[str, str] = Field(default_factory=dict)
    # Preset identifier for telemetry ("wellness-warm", "admin-neutral",
    # "creative-bold", "data-dense"). Empty when no preset applied.
    preset_name: str = ""

    def is_active(self) -> bool:
        """True when the lock carries actionable palette values."""
        return bool(self.palette)


# --------------------------------------------------------------------------- #
# Root
# --------------------------------------------------------------------------- #

class DesignBrief(BaseModel):
    """The full design brief. Locked at Planning approval; mutable only
    via the brief-loop (Phase 3). Authors read it as a contract."""
    identity: Identity
    palette: Palette
    typography: Typography
    layout: Layout
    signature_moves: list[SignatureMove] = Field(..., min_length=1, max_length=2)
    anti_patterns: list[str] = Field(default_factory=list)
    # Spec C3 — optional; empty bank is fine (readers fall back to
    # deterministic_strings' existing generic copy).
    content_bank: ContentBank = Field(default_factory=ContentBank)
    # Spec C4 — motion tokens, brief-authored values (concrete ms + eases).
    motion: Motion = Field(default_factory=Motion)
    # Spec C8 — responsive priority + layout variants, brief-authored.
    responsive: Responsive = Field(default_factory=Responsive)
    # Spec D Wave 3 — CTA hierarchy, brief-authored. Optional; when
    # absent, readers fall back to services.cta_defaults.defaults_for_register.
    cta_hierarchy: CtaHierarchy | None = None
    # Composition Recipe Library (behind FORGE_COMPOSITION_RECIPES).
    # Maps a plan page slug/name to a recipe key from recipes.json
    # (e.g. "member_home" → "member_home"). Discovery chooses; the deterministic
    # page builder composes anchors accordingly. Empty = classic path.
    page_recipes: dict[str, str] = Field(default_factory=dict)
    # Slice A (2026-08-13) — concrete visual tokens that lock down colors,
    # fonts, radius and shadows. When populated, downstream consumers
    # (brief_to_design_spec, design_compiler, design_language, design_dna)
    # prefer these verbatim instead of re-deriving. Empty = classic path.
    visual_lock: VisualLock = Field(default_factory=VisualLock)

    def summary_line(self) -> str:
        """One-line summary for Smith's memory block."""
        p = self.palette
        t = self.typography
        return (
            f"{self.identity.voice.value}, brand {p.brand}, "
            f"display '{t.display_family}', density {self.layout.density.value}"
        )


__all__ = [
    "ContentBank",
    "CtaHierarchy",
    "CtaRule",
    "DesignBrief",
    "Motion",
    "Responsive",
    "Identity",
    "Palette",
    "Typography",
    "Layout",
    "SignatureMove",
    "VisualLock",
    "VisualStance",
    "NavLanguage",
    "NeutralTint",
    "Density",
    "Radius",
    "Mode",
    "Voice",
]
