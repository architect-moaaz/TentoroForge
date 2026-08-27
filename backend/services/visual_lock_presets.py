"""Domain-preset picker for VisualLock — Slice A (2026-08-13).

DesignBrief's derived-tone fields historically produced too much
variance: a "warm/grounded_calm" register would still bounce between a
cream-forest-green wellness look and a beige-terracotta cafe look
depending on which downstream picker touched it. The lock cures that by
committing to EXACT tokens up front, driven by a small set of hand-tuned
domain presets that each occupy a distinct visual identity.

Presets shipping:

  * ``WELLNESS_WARM``    — cream + forest green + Fraunces (yoga, spa, wellness)
  * ``ADMIN_NEUTRAL``    — white + indigo + Inter        (generic CRUD, ops)
  * ``CREATIVE_BOLD``    — black + amber + Space Grotesk (agency, portfolio)
  * ``DATA_DENSE``       — off-white + azure + IBM Plex  (analytics, monitoring)
  * ``TRUST_NAVY``       — deep navy + gold + Source Serif (banking, fintech)
  * ``EDITORIAL_LIGHT``  — off-white + terracotta + Fraunces (cms, blog, editorial)
  * ``ACADEMIC_FRESH``   — sky-tint + blue + Merriweather (lms, e-learning)
  * ``CLINICAL_CALM``    — cool white + cyan + Source Sans (healthcare, clinical)
  * ``FIELD_UTILITY``    — cool white + safety orange + Inter (field service, dispatch)

The picker is deliberately conservative — it needs 2+ keyword hits to
snap to a specific preset, otherwise it falls back to ADMIN_NEUTRAL. A
mis-picked preset (data-dense on a yoga app) is worse than the safe
default. When telemetry lands the picker gets tuned; until then the
default is the boring one.

Pure module — no I/O, no LLM, deterministic in (domain, industry,
description). Consumed by design_brief_author to populate
``DesignBrief.visual_lock`` after the LLM authors the rest of the brief.
"""
from __future__ import annotations

from schemas.design_brief import VisualLock


# --------------------------------------------------------------------------- #
# Preset instances
# --------------------------------------------------------------------------- #

# Wellness / hospitality: warm cream ground, forest-green accent, editorial
# serif display over a legible sans body. The "yoga studio" reference look.
WELLNESS_WARM = VisualLock(
    palette={
        "bg":      "#F5F1E8",  # cream
        "fg":      "#2B2E28",  # near-black with a green whisper
        "accent":  "#5A6B4A",  # forest green
        "muted":   "#8B8578",  # warm grey
        "badge":   "#B8935A",  # amber
        "danger":  "#B85A4A",  # terracotta
        "success": "#5A6B4A",  # same as accent (monochromatic wellness)
        "subtle":  "#EBE5D6",  # cream-tint card surface
    },
    typography={
        "display": "Fraunces",
        "body":    "Inter",
        "mono":    "JetBrains Mono",
    },
    radius={"sm": 6, "md": 12, "lg": 24},
    shadow={
        "sm": "0 1px 2px rgba(43,46,40,0.06)",
        "md": "0 4px 12px rgba(43,46,40,0.08)",
    },
    preset_name="wellness-warm",
)


# Admin / CRUD: the safe fallback. White canvas, indigo primary, Inter.
# Neither loud nor bland — reads as "modern SaaS" without committing to
# any specific vertical identity. Every ambiguous domain lands here.
ADMIN_NEUTRAL = VisualLock(
    palette={
        "bg":      "#FFFFFF",
        "fg":      "#0F172A",  # slate-900
        "accent":  "#4F46E5",  # indigo-600
        "muted":   "#64748B",  # slate-500
        "badge":   "#F59E0B",  # amber-500
        "danger":  "#DC2626",  # red-600
        "success": "#059669",  # emerald-600
        "subtle":  "#F1F5F9",  # slate-100
    },
    typography={
        "display": "Inter",
        "body":    "Inter",
        "mono":    "JetBrains Mono",
    },
    radius={"sm": 4, "md": 8, "lg": 16},
    shadow={
        "sm": "0 1px 2px rgba(15,23,42,0.05)",
        "md": "0 4px 12px rgba(15,23,42,0.08)",
    },
    preset_name="admin-neutral",
)


# Creative / agency: dark canvas, warm amber accent, geometric display.
# The "portfolio site that isn't shy" look — deliberately loud.
CREATIVE_BOLD = VisualLock(
    palette={
        "bg":      "#0A0A0F",
        "fg":      "#FAFAFA",
        "accent":  "#F59E0B",  # amber-500
        "muted":   "#71717A",  # zinc-500
        "badge":   "#EC4899",  # pink-500
        "danger":  "#EF4444",  # red-500
        "success": "#10B981",  # emerald-500
        "subtle":  "#1F1F27",  # elevated dark surface
    },
    typography={
        "display": "Space Grotesk",
        "body":    "Inter",
        "mono":    "JetBrains Mono",
    },
    radius={"sm": 2, "md": 4, "lg": 8},
    shadow={
        "sm": "0 1px 2px rgba(0,0,0,0.4)",
        "md": "0 8px 24px rgba(0,0,0,0.5)",
    },
    preset_name="creative-bold",
)


# Data / analytics: near-white canvas, azure accent, IBM Plex through
# and through (its family covers sans/serif/mono coherently — critical
# for data density).
DATA_DENSE = VisualLock(
    palette={
        "bg":      "#FAFAFA",
        "fg":      "#171717",  # neutral-900
        "accent":  "#0EA5E9",  # sky-500
        "muted":   "#525252",  # neutral-600
        "badge":   "#F97316",  # orange-500
        "danger":  "#DC2626",  # red-600
        "success": "#16A34A",  # green-600
        "subtle":  "#E5E5E5",  # neutral-200
    },
    typography={
        "display": "IBM Plex Sans",
        "body":    "IBM Plex Sans",
        "mono":    "IBM Plex Mono",
    },
    radius={"sm": 2, "md": 4, "lg": 6},
    shadow={
        "sm": "0 1px 2px rgba(23,23,23,0.06)",
        "md": "0 4px 12px rgba(23,23,23,0.08)",
    },
    preset_name="data-dense",
)


# Banking / fintech / financial services: deep navy on a near-white cool
# ground, gold used sparingly for status highlights, Source Serif display
# over Source Sans body, JetBrains Mono for tabular-nums money columns.
# The "trust and restraint" look real banking apps commit to.
TRUST_NAVY = VisualLock(
    palette={
        "bg":      "#F5F6F8",  # near-white with a cool tint (not stark)
        "fg":      "#0B2545",  # deep navy — text on light bg
        "accent":  "#1D3557",  # primary brand — deeper navy
        "muted":   "#5A6B85",  # cool grey — supporting text
        "badge":   "#C9A961",  # gold — used sparingly for status highlights
        "danger":  "#B23A48",  # muted red — restrained, not alarming
        "success": "#2E7D5B",  # forest green — settled/cleared money
        "subtle":  "#FFFFFF",  # card surface (slightly higher than bg)
    },
    typography={
        # Source Serif 4 is the current Google Fonts family (2024+); older
        # names Source Serif Pro / Source Serif 3 point at the same font.
        "display": "Source Serif 4",
        "body":    "Source Sans 3",
        # Banking columns need tabular-nums; JetBrains Mono ships them by
        # default and pairs cleanly with a serif display.
        "mono":    "JetBrains Mono",
    },
    # Tighter corners than wellness — banking reads restrained, not playful.
    radius={"sm": 4, "md": 6, "lg": 10},
    shadow={
        # Subtle values on purpose — banking chrome should feel present
        # but not casual. Tinted with the navy fg so the elevation reads
        # cool, not neutral-grey.
        "sm": "0 1px 2px rgba(11,37,69,0.06)",
        "md": "0 4px 12px rgba(11,37,69,0.08)",
    },
    preset_name="trust-navy",
)


# Editorial / CMS / magazine / blog / publishing. Warm off-white ground,
# deep terracotta accent, Fraunces serif display over Inter body. The
# "magazine layout" look — restrained, editorial, still warm.
EDITORIAL_LIGHT = VisualLock(
    palette={
        "bg":      "#FAFAF8",  # near-white with a warm whisper
        "fg":      "#1A1A1A",  # editorial near-black
        "accent":  "#7C2D12",  # deep terracotta
        "muted":   "#78716C",  # stone-500 warm grey
        "badge":   "#B45309",  # amber-700 for status highlights
        "danger":  "#B91C1C",  # red-700 restrained
        "success": "#166534",  # green-800 editorial forest
        "subtle":  "#FFFFFF",  # card surface (higher than bg)
    },
    typography={
        # Fraunces for editorial serif headings, Inter for body legibility,
        # JetBrains Mono for any code / metadata blocks.
        "display": "Fraunces",
        "body":    "Inter",
        "mono":    "JetBrains Mono",
    },
    # Moderate corners — soft but restrained, magazine-appropriate.
    radius={"sm": 4, "md": 8, "lg": 12},
    shadow={
        # Mirror WELLNESS_WARM shape — subtle, tinted with the fg colour
        # so elevation reads warm-editorial.
        "sm": "0 1px 2px rgba(26,26,26,0.06)",
        "md": "0 4px 12px rgba(26,26,26,0.08)",
    },
    preset_name="editorial-light",
)


# Academic / LMS / e-learning. Calm sky-tint ground, sky blue accent,
# fresh teal for status highlights, Merriweather serif display over
# Inter body. Reads as "calm classroom" — approachable, uncluttered.
ACADEMIC_FRESH = VisualLock(
    palette={
        "bg":      "#F0F7FA",  # cool sky-tint
        "fg":      "#0F172A",  # slate-900
        "accent":  "#0369A1",  # sky-700 calm blue
        "muted":   "#64748B",  # slate-500
        "badge":   "#059669",  # emerald-600 fresh teal
        "danger":  "#DC2626",  # red-600
        "success": "#059669",  # same as badge for cohesion
        "subtle":  "#FFFFFF",  # card surface
    },
    typography={
        "display": "Merriweather",
        "body":    "Inter",
        "mono":    "JetBrains Mono",
    },
    # Rounded corners — softer / more approachable than editorial.
    radius={"sm": 6, "md": 10, "lg": 14},
    shadow={
        # Tinted with the fg for a cool-slate elevation.
        "sm": "0 1px 2px rgba(15,23,42,0.06)",
        "md": "0 4px 12px rgba(15,23,42,0.08)",
    },
    preset_name="academic-fresh",
)


# Clinical / healthcare. Neutral cool white ground, medical cyan accent,
# healthy green for status highlights. Source Sans throughout for the
# calm-utilitarian medical UX (no serif — clinical apps read professional
# not literary).
CLINICAL_CALM = VisualLock(
    palette={
        "bg":      "#F8FAFC",  # slate-50 neutral cool
        "fg":      "#0F172A",  # slate-900
        "accent":  "#0891B2",  # cyan-600 medical cyan
        "muted":   "#64748B",  # slate-500
        "badge":   "#059669",  # emerald-600 healthy green
        "danger":  "#DC2626",  # red-600
        "success": "#059669",  # same as badge — cohesive
        "subtle":  "#FFFFFF",  # card surface
    },
    typography={
        # Source Sans 3 for both display + body — clinical UX benefits
        # from typographic restraint (fewer families read calmer).
        "display": "Source Sans 3",
        "body":    "Source Sans 3",
        "mono":    "JetBrains Mono",
    },
    # Restrained corners — professional, not playful.
    radius={"sm": 4, "md": 6, "lg": 10},
    shadow={
        # Cool-tinted elevation matching the slate fg.
        "sm": "0 1px 2px rgba(15,23,42,0.06)",
        "md": "0 4px 12px rgba(15,23,42,0.08)",
    },
    preset_name="clinical-calm",
)


# Field service / dispatch / HVAC / plumbing / on-site. Safety-orange
# accent, dense mono-badge style, Inter throughout for utility (no
# serif — field techs read on trucks and job sites). Tight corners.
FIELD_UTILITY = VisualLock(
    palette={
        "bg":      "#F8FAFC",  # slate-50 neutral
        "fg":      "#0F172A",  # slate-900
        "accent":  "#EA580C",  # orange-600 safety orange
        "muted":   "#64748B",  # slate-500
        "badge":   "#0F172A",  # dense mono-badge — same as fg for high contrast
        "danger":  "#DC2626",  # red-600
        "success": "#16A34A",  # green-600
        "subtle":  "#FFFFFF",  # card surface
    },
    typography={
        # Inter through and through — no serif for utility surfaces.
        "display": "Inter",
        "body":    "Inter",
        "mono":    "JetBrains Mono",
    },
    # Tight corners — utility, not playful.
    radius={"sm": 4, "md": 6, "lg": 8},
    shadow={
        # Cool-slate elevation.
        "sm": "0 1px 2px rgba(15,23,42,0.06)",
        "md": "0 4px 12px rgba(15,23,42,0.08)",
    },
    preset_name="field-utility",
)


# --------------------------------------------------------------------------- #
# Keyword vocabularies for the picker.
#
# Ordered by which specific preset the picker snaps to. A domain has to
# match TWO OR MORE keywords in a bucket to trigger the specific preset;
# fewer than two → ADMIN_NEUTRAL. The order matters: WELLNESS first so
# "yoga studio booking" doesn't get pulled into CREATIVE by the "studio"
# keyword. Values are lowercased at compare time so the caller can pass
# raw fields.
# --------------------------------------------------------------------------- #

_WELLNESS_KEYWORDS: frozenset[str] = frozenset({
    "yoga", "wellness", "spa", "salon", "fitness", "meditation", "health",
    "therapy", "massage", "studio", "booking", "class", "session",
    "instructor", "member", "hospitality", "food", "retreat",
})

# Note: "studio" is intentionally NOT in CREATIVE — it collides with
# yoga/wellness. Creative apps get "agency", "portfolio", "gallery" and
# friends; a photography studio still needs the wellness/hospitality
# preset for the booking flows.
_CREATIVE_KEYWORDS: frozenset[str] = frozenset({
    "agency", "portfolio", "gallery", "art", "design", "creative",
    "music", "film", "media", "brand",
    # Messaging / realtime-chat products (Slack / Teams / Discord /
    # Mattermost) share the "bold identity, high-energy" register that
    # CREATIVE_BOLD is tuned for. Kept to the specific messaging nouns
    # so an unrelated app with a stray "chat" doesn't get pulled here
    # under the 2-hit threshold.
    "slack", "messaging", "chat", "channels", "dms", "threads",
})

_DATA_KEYWORDS: frozenset[str] = frozenset({
    "analytics", "monitoring", "dashboard", "metrics", "telemetry",
    "iot", "sensor", "gauge", "chart", "admin console", "ops", "sre",
    # Analytics / BI tooling — Metabase / Amplitude / Looker / Mixpanel
    # / Tableau. Same visual identity as the existing telemetry set.
    "bi", "business intelligence", "metabase", "amplitude", "looker",
    "mixpanel", "tableau", "queries", "datasets", "kpi", "reporting",
    # Dev-tools + observability / CI-CD — GitHub Actions / Sentry /
    # Grafana / Datadog / CircleCI / Jenkins. Same dense-utility read.
    "devtools", "dev tools", "ci/cd", "github actions", "circleci",
    "jenkins", "deployments", "sentry", "grafana", "datadog", "alerts",
    "incidents", "oncall", "observability", "build pipeline",
    # Document intelligence / doc-AI / extraction / OCR / searchable
    # knowledge base — same professional-utility read (analysts running
    # extraction pipelines want dense data views, not warm/wellness).
    "document intelligence", "ocr", "extraction", "docparser", "rossum",
    "nanonets", "textract", "document ai", "invoice extraction",
    "receipt scanner", "indexed search", "full-text search",
    "knowledge base", "doc search",
})

# Banking / fintech / financial services. Match order runs this BEFORE
# DATA (a bank always has "dashboard" too) but AFTER WELLNESS so a
# "credit union yoga class" doesn't get pulled into TRUST — the wellness
# concentration wins there. Two-hit threshold applies uniformly.
_BANKING_KEYWORDS: frozenset[str] = frozenset({
    "bank", "banking", "account", "loan", "credit", "compliance",
    "kyc", "ledger", "treasury", "fintech", "deposits", "mortgage",
    # Payment processing (Stripe / Adyen / Square / Braintree) shares
    # the fintech register — same restrained navy identity.
    "payments", "payment", "stripe", "checkout", "gateway", "merchant",
    "chargeback", "payout", "settlement", "refund",
    # Subscription billing (Recurly / Chargebee / Zuora / Stripe
    # Billing) — same money-tool restrained read.
    "subscription", "billing", "saas", "recurring", "dunning",
    "invoice", "mrr", "arr",
})

# Clinical / healthcare. Runs BEFORE DATA (medical dashboards exist) and
# BEFORE CREATIVE. Kept disjoint from wellness — wellness owns "health"
# and "therapy" so a spa/therapy app doesn't get pulled clinical; clinical
# owns "clinical / hospital / clinic / patient / medical / prescription".
_CLINICAL_KEYWORDS: frozenset[str] = frozenset({
    "healthcare", "patient", "clinical", "hospital", "clinic",
    "ehr", "emr", "doctor", "nurse", "medical", "prescription",
    "appointment", "vitals",
})

# Field service / dispatch / HVAC / plumbing / on-site repair. Runs
# BEFORE DATA (dispatch dashboards exist) and BEFORE CREATIVE.
_FIELD_KEYWORDS: frozenset[str] = frozenset({
    "field service", "technician", "dispatch", "work order",
    "hvac", "plumbing", "on-site", "repair", "service call",
    "field engineer",
})

# Academic / LMS / e-learning. Runs BEFORE DATA (learning analytics
# exist). Disjoint from wellness — no "class"/"session" here (those live
# on wellness for booking apps); academic owns "lms/course/cohort/quiz".
_ACADEMIC_KEYWORDS: frozenset[str] = frozenset({
    "lms", "learning", "course", "cohort", "training", "e-learning",
    "curriculum", "students", "learners", "quizzes",
})

# Editorial / CMS / publishing / blog / magazine / knowledge base.
# Runs BEFORE CREATIVE — a magazine layout is editorial-warm, not
# creative-loud. Disjoint from creative (which owns portfolio/gallery).
_EDITORIAL_KEYWORDS: frozenset[str] = frozenset({
    "cms", "blog", "editorial", "magazine", "publishing", "articles",
    "knowledge base", "docs site", "content",
})


# --------------------------------------------------------------------------- #
# Picker
# --------------------------------------------------------------------------- #


def _hit_count(text: str, vocab: frozenset[str]) -> int:
    """Case-insensitive substring hit count.

    Substring rather than word-boundary match on purpose: "yoga-studio"
    still hits both "yoga" and "studio". False positives are fine here
    — the two-hit threshold is what disambiguates.
    """
    lowered = text.lower()
    return sum(1 for kw in vocab if kw in lowered)


def _s(x) -> str:
    """Coerce anything to a safe string for keyword matching."""
    return x if isinstance(x, str) else ""


def pick_preset_from_plan(plan: dict | None) -> VisualLock:
    """Convenience wrapper — read domain/industry/description off a plan dict.

    Reads the fields most planners emit:
      * ``plan.domain`` or ``plan.domain_label``
      * ``plan.industry``
      * ``plan.description`` (falls back to ``plan.problem_statement``)

    Missing fields become empty strings so the picker always returns a
    preset. Never raises.
    """
    p = plan or {}
    domain = _s(p.get("domain") or p.get("domain_label"))
    industry = _s(p.get("industry"))
    description = _s(p.get("description") or p.get("problem_statement"))
    return pick_preset(domain, industry, description)


def pick_preset(domain: str, industry: str, description: str) -> VisualLock:
    """Choose a VisualLock preset from plan text.

    Match order is deliberate: WELLNESS → CREATIVE → DATA → ADMIN_NEUTRAL.
    Each specific preset needs ≥2 keyword hits to trigger; otherwise the
    safe admin default. Ambiguity resolves toward the neutral, never
    toward a loud identity.

    Args:
        domain:      canonical domain label (e.g. "wellness", "fintech").
        industry:    industry hint (e.g. "yoga studios", "SaaS").
        description: the plan's free-form description string.

    Returns:
        A VisualLock instance ready to stamp on ``DesignBrief.visual_lock``.
    """
    haystack = " ".join(x for x in (domain, industry, description) if isinstance(x, str))
    if _hit_count(haystack, _WELLNESS_KEYWORDS) >= 2:
        return WELLNESS_WARM
    # Banking BEFORE DATA — every bank also carries "dashboard" and
    # "metrics" language. Wellness still wins over banking because
    # keyword overlap between them is minimal.
    if _hit_count(haystack, _BANKING_KEYWORDS) >= 2:
        return TRUST_NAVY
    # Clinical / field-service / academic BEFORE DATA and CREATIVE —
    # domain-specific palettes should win over generic loud/dense looks
    # when the description carries enough domain vocabulary. Each still
    # loses to WELLNESS (the yoga case) and BANKING (the fintech case)
    # by ordering.
    if _hit_count(haystack, _CLINICAL_KEYWORDS) >= 2:
        return CLINICAL_CALM
    if _hit_count(haystack, _FIELD_KEYWORDS) >= 2:
        return FIELD_UTILITY
    if _hit_count(haystack, _ACADEMIC_KEYWORDS) >= 2:
        return ACADEMIC_FRESH
    # Editorial BEFORE CREATIVE — a magazine CMS is editorial-warm, not
    # creative-loud.
    if _hit_count(haystack, _EDITORIAL_KEYWORDS) >= 2:
        return EDITORIAL_LIGHT
    if _hit_count(haystack, _CREATIVE_KEYWORDS) >= 2:
        return CREATIVE_BOLD
    if _hit_count(haystack, _DATA_KEYWORDS) >= 2:
        return DATA_DENSE
    return ADMIN_NEUTRAL


__all__ = [
    "ACADEMIC_FRESH",
    "ADMIN_NEUTRAL",
    "CLINICAL_CALM",
    "CREATIVE_BOLD",
    "DATA_DENSE",
    "EDITORIAL_LIGHT",
    "FIELD_UTILITY",
    "TRUST_NAVY",
    "WELLNESS_WARM",
    "pick_preset",
    "pick_preset_from_plan",
]
