"""Shape profile detector — deterministic keyword scorer that fills
axis fields when the LLM output is invalid or unavailable (M1-T6).

**Never runs on the hot path.** The LLM is always the primary
author. This module is a safety net for two cases:

1. LLM returns a value outside the closed vocabulary (per-field
   fill; other fields keep LLM output).
2. LLM unavailable entirely (API key missing, timeout, etc — whole
   profile fills from keyword signals + safe defaults).

Both cases log an ``LLM_UNAVAILABLE`` finding via
:class:`services.shape_profile.Finding` so the quality dashboard
can measure how often we degrade.

Scoring is intentionally simple — this is a rescue, not a classifier
we should tune obsessively. When the keyword signal is weak we fall
back to ``safe_defaults`` from ``vocabulary.json``.
"""
from __future__ import annotations

from typing import Any

from services.shape_profile import (
    Finding,
    safe_default_shape_profile,
    shape_primitive_values,
)


# ══════════════════════════════════════════════════════════════════
# Keyword signals per primitive value.
# Curated conservatively — misses are OK (safe defaults catch them);
# false positives are worse.
# ══════════════════════════════════════════════════════════════════

_KEYWORDS: dict[str, dict[str, tuple[str, ...]]] = {
    "layout.shell": {
        "none":         ("scanner", "camera", "single-page utility", "one-page", "no auth", "no sidebar", "landing"),
        "sidebar":      ("workspace", "admin", "crm", "erp", "portal", "internal tool"),
        "header":       ("marketplace", "storefront", "commerce", "ecommerce", "public app"),
        "three-pane":   ("chat", "email client", "slack-like", "discord-like", "messaging"),
        "bottom-tabs":  ("mobile app", "consumer app", "iphone", "ios", "android app", "social"),
        "map-canvas":   ("map", "delivery", "ride", "uber", "location tracking"),
    },
    "layout.hero": {
        "none":                    ("dashboard", "admin", "workspace", "crud"),
        "full-bleed-gradient":     ("scanner", "capture", "camera-first", "hero cta"),
        "media-hero":              ("marketplace", "storefront", "landing"),
        "metric-row":              ("dashboard", "analytics", "trading", "portfolio"),
        "player-bar":              ("music", "podcast", "player", "streaming audio", "streaming video"),
        "map-canvas":              ("map first", "map-based", "delivery"),
        "feed-header":             ("feed", "timeline", "social"),
        "now-playing":             ("music player", "video player"),
    },
    "layout.primaryInteraction": {
        "cta-button":  ("single button", "click-to-start"),
        "capture":     ("camera", "scan", "photo", "capture"),
        "search":      ("search-driven", "type-ahead"),
        "feed":        ("feed", "timeline", "posts", "stories"),
        "player":      ("play", "listen", "watch"),
        "map":         ("map", "location", "geospatial"),
        "chat":        ("chat", "conversation", "messaging"),
        "lesson":      ("lesson", "learn", "quiz", "flashcard"),
        "data-grid":   ("table", "grid", "spreadsheet", "records"),
        "card-grid":   ("browse", "gallery", "catalog"),
        "form":        ("wizard", "form", "checkout", "signup"),
        "chart":       ("chart", "trading", "graph"),
    },
    "layout.density": {
        "spacious":    ("hero", "consumer", "landing", "single-purpose"),
        "comfortable": ("workspace", "admin", "dashboard"),
        "dense":       ("trading", "spreadsheet", "power user", "trader"),
    },
    "auth.surface": {
        "none":     ("no login", "anonymous", "no auth"),
        "modal":    ("consumer app", "sign in modal", "guest checkout"),
        "route":    ("workspace", "admin", "team app", "enterprise"),
        "sso-only": ("sso", "saml", "oidc", "corporate"),
    },
    "auth.gating": {
        "none":       ("no auth", "anonymous"),
        "on-action":  ("guest browse", "sign in to buy", "sign in to save"),
        "on-load":    ("private app", "workspace", "admin"),
    },
    "nav.menu": {
        "none":              ("no menu", "single-page"),
        "sidebar-links":     ("workspace", "admin"),
        "header-links":      ("marketplace", "storefront"),
        "bottom-tabs":       ("mobile app", "consumer app"),
        "drawer":            ("hamburger menu", "drawer nav"),
        "command-palette":   ("power user", "cmd-k", "shortcut-first"),
    },
    "nav.back": {
        "history":     ("mobile", "consumer", "browsing"),
        "crumb":       ("workspace", "admin", "hierarchy"),
        "close-modal": ("modal-heavy", "sheet-based"),
        "none":        ("single page", "no navigation"),
    },
    "workflows.executionMode": {
        "fire-and-forget":              ("submit and move on", "background dispatch"),
        "await-with-progress":          ("wait for", "processing", "loading"),
        "streaming":                    ("real-time", "live updates", "streaming"),
        "background-with-notification": ("email me when done", "notify when"),
    },
    "data.readShape": {
        "single-record":  ("single object", "one record"),
        "list":           ("list of", "records"),
        "feed":           ("feed", "timeline", "chronological"),
        "grid":           ("gallery", "catalog", "browse grid"),
        "map-pins":       ("map with markers", "pins", "locations on map"),
        "board":          ("kanban", "board", "columns"),
        "timeline":       ("gantt", "schedule", "timeline"),
    },
    "data.denormalization": {
        "none":       ("normalized", "third normal form"),
        "moderate":   ("workspace", "admin"),
        "aggressive": ("consumer", "read-heavy", "denormalize"),
    },
    "identity.usageMode": {
        "single-session":       ("anonymous", "one-off", "single-use"),
        "returning-personal":   ("personal", "consumer app", "my account"),
        "multi-user-team":      ("team", "workspace", "collaboration"),
        "public-anonymous":     ("public", "no login", "content site"),
    },
}


# ══════════════════════════════════════════════════════════════════
# Scorer
# ══════════════════════════════════════════════════════════════════


def score_primitive(primitive: str, brief: str) -> str | None:
    """Return the highest-scoring value for a shape primitive.
    ``None`` when no keyword matches (caller should fall back to
    safe_defaults)."""
    lower = brief.lower()
    keywords = _KEYWORDS.get(primitive) or {}
    valid_values = set(shape_primitive_values(primitive))

    best_value: str | None = None
    best_score = 0
    for value, needles in keywords.items():
        if value not in valid_values:
            continue  # vocabulary drift; skip
        score = sum(1 for needle in needles if needle in lower)
        if score > best_score:
            best_score = score
            best_value = value
    return best_value if best_score > 0 else None


def detect_shape_profile(brief: str) -> tuple[dict[str, Any], list[Finding]]:
    """Fill the entire shape profile from keyword signals over
    ``brief``. Returns ``(profile_dict, findings)``.

    Findings always include ``LLM_UNAVAILABLE`` because this function
    ONLY runs when the LLM output was unusable. Additional findings
    per field marked ``degraded_fill``."""
    defaults = safe_default_shape_profile()
    findings: list[Finding] = [Finding(
        rule="LLM_UNAVAILABLE",
        message=(
            "Shape profile filled from keyword detector — LLM output "
            "was unusable or unavailable. Generation is marked "
            "'produced under degraded conditions'."
        ),
        severity="warning",
        axis="app_shape",
    )]

    for slice_name, fields in defaults.items():
        if slice_name.startswith("$"):
            continue
        if not isinstance(fields, dict):
            continue
        for field_name in list(fields.keys()):
            primitive = f"{slice_name}.{field_name}"
            scored = score_primitive(primitive, brief)
            if scored is not None:
                defaults[slice_name][field_name] = scored
                findings.append(Finding(
                    rule="shape_profile.degraded_fill",
                    message=f"{primitive}={scored!r} from keyword detector",
                    severity="info",
                    axis="app_shape",
                ))
    return (defaults, findings)


def repair_single_field(primitive: str, brief: str) -> tuple[Any, Finding]:
    """Recover one invalid field. Returns the safe-default value +
    a Finding when the keyword scorer finds nothing; otherwise
    returns the scored value + an info Finding."""
    scored = score_primitive(primitive, brief)
    if scored is not None:
        return (scored, Finding(
            rule="shape_profile.degraded_fill",
            message=f"{primitive}={scored!r} from keyword detector (LLM output invalid)",
            severity="info",
            axis="app_shape",
        ))
    defaults = safe_default_shape_profile()
    slice_name, _, field_name = primitive.partition(".")
    fallback = (defaults.get(slice_name) or {}).get(field_name)
    return (fallback, Finding(
        rule="shape_profile.safe_default_fill",
        message=(
            f"{primitive}={fallback!r} from safe defaults (LLM output "
            "invalid, no keyword signal). Generation is marked "
            "'produced under degraded conditions'."
        ),
        severity="warning",
        axis="app_shape",
    ))
