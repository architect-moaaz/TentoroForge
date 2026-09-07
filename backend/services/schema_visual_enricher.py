"""Post-pass that retrofits visual assets onto schema nodes the LLM left
blank — Avatar.photoUrl, Hero.backgroundImage, FeatureCard.icon.

The LLM-generated schemas often default Avatar to its initials-only state
(the "monogram" look), Hero to a text-only banner, and FeatureCard to a
plain header + body. None of that is wrong per the schema contract, but
it adds up to a visually thin app.

This enricher walks the produced schema tree once and fills in the
missing visual props from:
  1. The project's design-spec (loginBackground, dashboardHero, facePool)
  2. A curated default photo pool for face avatars
  3. A keyword-driven Lucide-icon picker for feature cards

Runs after page_schema_agent writes the schema so LLM-supplied values
always win — the enricher only fills BLANK fields, never overwrites.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


# Curated free-license Unsplash portrait pool. Used when design-spec.json
# doesn't supply a facePool. Diverse demographics, neutral expressions,
# small (200px) so they load quickly.
_DEFAULT_FACE_POOL: tuple[str, ...] = (
    "https://images.unsplash.com/photo-1494790108377-be9c29b29330?w=200&q=80",
    "https://images.unsplash.com/photo-1535713875002-d1d0cf377fde?w=200&q=80",
    "https://images.unsplash.com/photo-1438761681033-6461ffad8d80?w=200&q=80",
    "https://images.unsplash.com/photo-1500648767791-00dcc994a43e?w=200&q=80",
    "https://images.unsplash.com/photo-1544005313-94ddf0286df2?w=200&q=80",
    "https://images.unsplash.com/photo-1517841905240-472988babdf9?w=200&q=80",
    "https://images.unsplash.com/photo-1573497019940-1c28c88b4f3e?w=200&q=80",
    "https://images.unsplash.com/photo-1502685104226-ee32379fefbe?w=200&q=80",
    "https://images.unsplash.com/photo-1517365830460-955ce3ccd263?w=200&q=80",
    "https://images.unsplash.com/photo-1554151228-14d9def656e4?w=200&q=80",
)

# Fallback hero backgrounds — generic neutral photography that fits SaaS,
# marketing, or dashboard contexts. Picked when design-spec doesn't carry
# a per-page URL and the route doesn't match the auth-shaped routes.
_DEFAULT_HERO_BG: str = (
    "https://images.unsplash.com/photo-1557804506-669a67965ba0?w=1920&q=80"
)
_DEFAULT_LOGIN_BG: str = (
    "https://images.unsplash.com/photo-1497366811353-6870744d04b2?w=1920&q=80"
)

# Title keyword → Lucide icon name. Order matters: the first match wins,
# so the more specific phrases sit on top. Used to assign a sensible icon
# to FeatureCard nodes the LLM emitted without one.
_FEATURE_ICON_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("shield",         ("secure", "security", "privacy", "encrypt", "compliance", "auth")),
    ("zap",            ("fast", "speed", "instant", "quick", "real-time", "realtime")),
    ("trending-up",    ("growth", "trend", "improve", "increase", "boost")),
    ("bar-chart",      ("analytics", "metric", "report", "insight", "chart", "data")),
    ("users",          ("team", "collaboration", "people", "members", "community")),
    ("user",           ("profile", "user", "account", "identity")),
    ("clock",          ("schedule", "time", "deadline", "reminder", "calendar")),
    ("settings",       ("configure", "settings", "customize", "control", "manage")),
    ("globe",          ("global", "worldwide", "international", "anywhere", "cloud")),
    ("award",          ("quality", "premium", "best", "trusted", "certified", "award")),
    ("activity",       ("monitor", "track", "live", "activity", "health", "status")),
    ("check-circle",   ("verified", "approved", "validated", "complete", "done")),
    ("rocket",         ("launch", "deploy", "ship", "release", "accelerate")),
    ("search",         ("search", "find", "discover", "explore", "lookup")),
    ("message-circle", ("chat", "message", "conversation", "support", "talk", "comment")),
    ("bell",           ("notification", "alert", "remind", "update", "push")),
    ("heart",          ("favorite", "wellness", "care", "love", "saved")),
    ("file-text",      ("document", "file", "report", "form", "contract", "letter")),
    ("layers",         ("organize", "workflow", "process", "pipeline", "stage")),
    ("link",           ("integration", "connect", "sync", "api", "webhook")),
    ("credit-card",    ("payment", "billing", "invoice", "subscription", "charge")),
    ("inbox",          ("inbox", "incoming", "mail", "email")),
    ("target",         ("goal", "target", "objective", "kpi", "focus")),
)


def _hash_index(s: str, modulo: int) -> int:
    """Stable bucket from a string — same id always picks the same face,
    so re-running the enricher on a schema is idempotent."""
    if modulo <= 0:
        return 0
    h = hashlib.md5(s.encode("utf-8")).hexdigest()
    return int(h[:8], 16) % modulo


def _infer_feature_icon(title: str) -> str | None:
    """Pick a Lucide icon name by keyword-matching a FeatureCard title."""
    if not title:
        return None
    lower = title.lower()
    for icon, keywords in _FEATURE_ICON_KEYWORDS:
        if any(kw in lower for kw in keywords):
            return icon
    return None


def _walk(node: Any, fn) -> None:
    """Depth-first walk that calls fn on every dict-shaped node."""
    if isinstance(node, dict):
        fn(node)
        for c in node.get("children") or []:
            _walk(c, fn)


def _extract_pool(design_spec: dict, key: str, fallback: tuple[str, ...]) -> tuple[str, ...]:
    """Read a list of URLs from the design spec, falling back when absent
    or the type is wrong (LLMs sometimes return strings instead of arrays)."""
    val = (design_spec or {}).get(key)
    if isinstance(val, list) and all(isinstance(x, str) and x for x in val):
        return tuple(val)
    return fallback


def enrich_schema_visuals(
    schema: dict,
    design_spec: dict | None = None,
    route: str | None = None,
) -> int:
    """Walk the schema and fill in visual assets the LLM left blank.

    Avatar.photoUrl     → from design_spec.facePool[hash(id)] or default pool
    Hero.backgroundImage → from design_spec.{loginBackground|dashboardHero}
    FeatureCard.icon    → keyword-matched Lucide name from FeatureCard.title

    Only fills blank fields — any value the LLM already supplied is left
    untouched. Returns the number of nodes enriched (for SSE logging).
    """
    spec = design_spec or {}
    face_pool = _extract_pool(spec, "facePool", _DEFAULT_FACE_POOL)

    # Hero background — auth pages take precedence over the dashboard URL.
    page_route = (route or "").lower()
    is_auth = any(page_route.startswith(p) for p in ("/login", "/signin", "/signup", "/register"))
    auth_bg = (spec.get("loginBackground") if isinstance(spec.get("loginBackground"), str) else None) or _DEFAULT_LOGIN_BG
    page_bg = (spec.get("dashboardHero") if isinstance(spec.get("dashboardHero"), str) else None) or _DEFAULT_HERO_BG
    chosen_bg = auth_bg if is_auth else page_bg

    enriched = 0

    def visit(node: dict) -> None:
        nonlocal enriched
        t = node.get("type")
        if t not in {"Avatar", "Hero", "FeatureCard"}:
            return
        p = node.setdefault("props", {})

        if t == "Avatar":
            # photoUrl is the v2 prop; src is the legacy alias. Skip if
            # either is already set.
            if not p.get("photoUrl") and not p.get("src"):
                key = (node.get("id") or "") + str(p.get("name") or "")
                idx = _hash_index(key or "anon", len(face_pool))
                p["photoUrl"] = face_pool[idx]
                enriched += 1
            return

        if t == "Hero":
            # backgroundImage is the renderer-expected prop (object with .url
            # and optional .overlay). Skip if either backgroundImage OR media
            # is already populated.
            existing_bg = p.get("backgroundImage")
            if not existing_bg and not p.get("media"):
                p["backgroundImage"] = {"url": chosen_bg, "overlay": 0.4}
                enriched += 1
            return

        if t == "FeatureCard":
            if not p.get("icon"):
                icon = _infer_feature_icon(str(p.get("title") or ""))
                if icon:
                    p["icon"] = icon
                    enriched += 1

    for child in schema.get("children") or []:
        _walk(child, visit)
    return enriched


def enrich_schema_file(
    schema_path: str | Path,
    design_spec: dict | None = None,
    route: str | None = None,
) -> int:
    """Read a schema JSON file, enrich it in place, and write it back.

    Returns the number of nodes enriched (0 if nothing changed; in that
    case the file is left untouched to preserve mtime).
    """
    p = Path(schema_path)
    if not p.exists():
        return 0
    try:
        schema = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    n = enrich_schema_visuals(schema, design_spec=design_spec, route=route)
    if n > 0:
        p.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    return n
