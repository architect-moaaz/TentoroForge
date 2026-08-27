"""Industry Design System — maps detected domains to design decisions.

When no Figma design is provided, this module determines:
  - Theme (color palette, radius, spacing)
  - Layout archetype (sidebar, top-nav, dashboard-first, etc.)
  - Component density (compact, comfortable, spacious)
  - Recommended patterns per entity type

The goal: a healthcare app should LOOK like a healthcare app,
a logistics dashboard should LOOK like a logistics dashboard.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _map_figma_colors_to_tokens(colors: list[str]) -> dict[str, str]:
    """Intelligently map Figma-extracted colors to semantic design tokens.

    Instead of blindly taking the first N colors (which are sorted by hex
    and often start with black/white), this function categorizes colors by
    their hue/saturation/lightness to find the best semantic mapping.
    """
    if not colors:
        return {}

    def hex_to_hsl(hex_color: str) -> tuple[float, float, float]:
        h_str = hex_color.lstrip("#")
        r, g, b = int(h_str[0:2], 16) / 255, int(h_str[2:4], 16) / 255, int(h_str[4:6], 16) / 255
        mx, mn = max(r, g, b), min(r, g, b)
        l = (mx + mn) / 2
        if mx == mn:
            h = s = 0.0
        else:
            d = mx - mn
            s = d / (2.0 - mx - mn) if l > 0.5 else d / (mx + mn)
            if mx == r:
                h = (g - b) / d + (6 if g < b else 0)
            elif mx == g:
                h = (b - r) / d + 2
            else:
                h = (r - g) / d + 4
            h /= 6
        return h * 360, s, l

    # Categorize colors
    chromatic = []  # saturated colors (not near-black, near-white, or grey)
    for c in colors:
        if len(c) != 7 or not c.startswith("#"):
            continue
        h, s, l = hex_to_hsl(c)
        if s > 0.2 and 0.1 < l < 0.85:
            chromatic.append((c, h, s, l))

    if not chromatic:
        return {}

    # Sort by saturation (most vibrant first) — these are likely brand colors
    chromatic.sort(key=lambda x: -x[2])

    result: dict[str, str] = {}

    # Primary: most saturated color
    result["primary"] = chromatic[0][0]

    # Secondary: next most saturated color with a different hue
    for c, h, s, l in chromatic[1:]:
        hue_diff = abs(h - chromatic[0][1])
        if hue_diff > 30 or hue_diff < -30:  # different hue family
            result["secondary"] = c
            break
    if "secondary" not in result and len(chromatic) > 1:
        result["secondary"] = chromatic[1][0]

    # Danger: look for reds (hue 0-30 or 330-360)
    for c, h, s, l in chromatic:
        if c in (result.get("primary"), result.get("secondary")):
            continue
        if h < 30 or h > 330:
            result["danger"] = c
            break

    # Warning: look for yellows/oranges (hue 30-60)
    for c, h, s, l in chromatic:
        if c in result.values():
            continue
        if 30 <= h <= 60:
            result["warning"] = c
            break

    # Success: look for greens (hue 90-160)
    for c, h, s, l in chromatic:
        if c in result.values():
            continue
        if 90 <= h <= 160:
            result["success"] = c
            break

    # Background: lightest near-white
    for c in colors:
        if len(c) != 7:
            continue
        _, s, l = hex_to_hsl(c)
        if l > 0.95 and s < 0.1 and c != "#ffffff":
            result["background"] = c
            break

    # Surface: second lightest
    for c in colors:
        if len(c) != 7 or c == result.get("background"):
            continue
        _, s, l = hex_to_hsl(c)
        if l > 0.9 and s < 0.15:
            result["surface"] = c
            break

    logger.info("Mapped Figma colors → tokens: %s", result)
    return result


# ---------------------------------------------------------------------------
# Domain → Theme mapping (mirrors packages/ir/src/theme.ts DOMAIN_THEME_MAP)
# ---------------------------------------------------------------------------

DOMAIN_THEME: dict[str, str] = {
    "Healthcare": "healthcare",
    "Finance & Banking": "finance",
    "Logistics & Supply Chain": "logistics",
    "CRM": "crm",
    "Sales": "crm",
    "Education": "education",
    "Human Resources": "hr",
    "E-Commerce & Retail": "ecommerce",
    "Real Estate & Property": "realestate",
    "Manufacturing": "manufacturing",
    "Hospitality & Food": "sunset",
    "Legal": "finance",
    "Government": "sharp",
    "Non-Profit": "forest",
    "Media & Publishing": "ocean",
    "Agriculture": "forest",
    "Energy": "manufacturing",
    "Project Management": "ocean",
}

# ---------------------------------------------------------------------------
# Domain → Layout archetype
# ---------------------------------------------------------------------------

DOMAIN_LAYOUT: dict[str, dict[str, Any]] = {
    "Healthcare": {
        "navigation": "sidebar",
        "density": "comfortable",
        "dashboard_widgets": ["stat-cards", "recent-patients", "appointments-today", "alerts"],
        "priority_patterns": {"patient": "tabbed-detail", "appointment": "calendar"},
        "description": "Clean sidebar navigation, patient-centric detail views with tabs, status indicators, appointment calendar",
    },
    "Finance & Banking": {
        "navigation": "sidebar",
        "density": "compact",
        "dashboard_widgets": ["stat-cards", "portfolio-chart", "recent-transactions", "alerts"],
        "priority_patterns": {"transaction": "dense-table", "account": "tabbed-detail"},
        "description": "Dense data tables, number-heavy dashboards, chart-first analytics, conservative layout",
    },
    "Logistics & Supply Chain": {
        "navigation": "sidebar-dark",
        "density": "compact",
        "dashboard_widgets": ["stat-cards", "map-overview", "active-shipments", "alerts"],
        "priority_patterns": {"shipment": "timeline", "vehicle": "card-grid"},
        "description": "Dark sidebar, map-centric views, status-heavy dashboards, timeline tracking",
    },
    "CRM": {
        "navigation": "topbar",
        "density": "comfortable",
        "dashboard_widgets": ["pipeline-summary", "recent-deals", "activity-feed", "stat-cards"],
        "priority_patterns": {"deal": "kanban", "contact": "sidebar-detail"},
        "description": "Pipeline kanban boards, activity feeds, deal cards, metric-heavy dashboards",
    },
    "Sales": {
        "navigation": "topbar",
        "density": "comfortable",
        "dashboard_widgets": ["pipeline-summary", "recent-deals", "leaderboard", "stat-cards"],
        "priority_patterns": {"lead": "kanban", "opportunity": "sidebar-detail"},
        "description": "Pipeline views, deal progression, activity tracking, performance metrics",
    },
    "Education": {
        "navigation": "sidebar",
        "density": "spacious",
        "dashboard_widgets": ["stat-cards", "upcoming-classes", "announcements", "progress"],
        "priority_patterns": {"course": "card-grid", "student": "profile-detail"},
        "description": "Card-based course views, student profiles, progress tracking, spacious readable layout",
    },
    "Human Resources": {
        "navigation": "sidebar",
        "density": "comfortable",
        "dashboard_widgets": ["stat-cards", "new-hires", "leave-calendar", "announcements"],
        "priority_patterns": {"employee": "profile-detail", "leave": "calendar"},
        "description": "People directory, profile cards, leave calendar, onboarding flows, warm design",
    },
    "E-Commerce & Retail": {
        "navigation": "topbar",
        "density": "comfortable",
        "dashboard_widgets": ["stat-cards", "revenue-chart", "top-products", "recent-orders"],
        "priority_patterns": {"product": "card-grid", "order": "timeline"},
        "description": "Product grids, order timelines, revenue charts, conversion metrics",
    },
    "Real Estate & Property": {
        "navigation": "topbar",
        "density": "spacious",
        "dashboard_widgets": ["stat-cards", "listing-map", "recent-listings", "pipeline"],
        "priority_patterns": {"property": "card-grid", "listing": "sidebar-detail"},
        "description": "Property cards with images, map views, premium listing details, sophisticated layout",
    },
    "Manufacturing": {
        "navigation": "sidebar-dark",
        "density": "compact",
        "dashboard_widgets": ["stat-cards", "production-chart", "equipment-status", "alerts"],
        "priority_patterns": {"work_order": "dense-table", "equipment": "tabbed-detail"},
        "description": "Dense industrial dashboards, equipment status boards, work order tables, no-nonsense layout",
    },
    "Hospitality & Food": {
        "navigation": "sidebar",
        "density": "comfortable",
        "dashboard_widgets": ["stat-cards", "reservations-today", "table-map", "reviews"],
        "priority_patterns": {"reservation": "calendar", "menu_item": "card-grid"},
        "description": "Warm, welcoming design, reservation calendar, table layout, menu cards",
    },
    "Project Management": {
        "navigation": "sidebar",
        "density": "comfortable",
        "dashboard_widgets": ["stat-cards", "my-tasks", "project-timeline", "team-activity"],
        "priority_patterns": {"task": "kanban", "project": "tabbed-detail"},
        "description": "Kanban boards, Gantt-style timelines, task cards, team collaboration views",
    },
    "Government": {
        "navigation": "topbar",
        "density": "compact",
        "dashboard_widgets": ["stat-cards", "recent-activity", "alerts", "quick-actions"],
        "priority_patterns": {"subscription": "dense-table", "plan": "tabbed-detail", "user": "dense-table"},
        "description": "Top navigation, compact density, metric-first dashboards, usage stats and subscription management",
    },
}

# Default for unrecognized domains
_DEFAULT_LAYOUT: dict[str, Any] = {
    "navigation": "sidebar",
    "density": "comfortable",
    "dashboard_widgets": ["stat-cards", "recent-items", "activity"],
    "priority_patterns": {},
    "description": "Clean sidebar navigation, balanced data density, standard CRUD layout",
}


# Planner emits coarse lowercase domains; map them to the keys used by
# DOMAIN_THEME / DOMAIN_LAYOUT so theme + layout stop collapsing to the default.
_DOMAIN_ALIAS: dict[str, str] = {
    "hr": "Human Resources",
    "fintech": "Finance & Banking",
    "finance": "Finance & Banking",
    "healthcare": "Healthcare",
    "saas": "Government",           # "Government" → "sharp" theme
    "ecommerce": "E-Commerce & Retail",
    "logistics": "Logistics & Supply Chain",
    "education": "Education",
    "crm": "CRM",
    "sales": "Sales",
    # "general" intentionally has no alias → keeps the neutral "ocean" default.
}


def get_industry_design(domain: str) -> dict[str, Any]:
    """Get the complete design context for a domain.

    Returns a dict with theme, layout, density, and pattern recommendations
    that should be injected into the AppSpec for the IR compiler.
    """
    domain = _DOMAIN_ALIAS.get((domain or "").strip().lower(), domain)
    theme = DOMAIN_THEME.get(domain, "ocean")
    layout = DOMAIN_LAYOUT.get(domain, _DEFAULT_LAYOUT)

    return {
        "theme": theme,
        "navigation": layout["navigation"],
        "density": layout["density"],
        "dashboard_widgets": layout["dashboard_widgets"],
        "priority_patterns": layout["priority_patterns"],
        "layout_description": layout["description"],
    }


def inject_design_into_app_spec(
    app_spec: dict[str, Any],
    domain: str,
    figma_tokens: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Inject industry-specific design decisions into an AppSpec.

    If figma_tokens are provided (Figma import path), those override
    the industry defaults for colors/fonts.
    """
    design = get_industry_design(domain)

    # Set theme
    if "app" not in app_spec:
        app_spec["app"] = {}
    app_spec["app"]["theme"] = design["theme"]

    # Set user context for the pattern resolver
    if "userContext" not in app_spec:
        app_spec["userContext"] = {}
    app_spec["userContext"]["domain"] = domain
    app_spec["userContext"]["priority"] = (
        "density" if design["density"] == "compact"
        else "aesthetics" if design["density"] == "spacious"
        else "speed"
    )

    # Set layout hints
    app_spec["userContext"]["navigation"] = design["navigation"]
    app_spec["userContext"]["dashboardWidgets"] = design["dashboard_widgets"]

    # Override entity pattern preferences
    for entity in app_spec.get("entities", []):
        entity_lower = entity.get("name", "").lower()
        for pattern_key, pattern_name in design["priority_patterns"].items():
            if pattern_key in entity_lower:
                if "viewOverrides" not in entity:
                    entity["viewOverrides"] = {}
                entity["viewOverrides"]["browse"] = pattern_name

    # If Figma tokens provided, inject as custom token overrides
    if figma_tokens:
        if "tokenOverrides" not in app_spec:
            app_spec["tokenOverrides"] = {}
        if figma_tokens.get("colors"):
            mapped = _map_figma_colors_to_tokens(figma_tokens["colors"])
            app_spec["tokenOverrides"].update(mapped)
        if figma_tokens.get("fonts"):
            app_spec["tokenOverrides"]["fontFamily"] = figma_tokens["fonts"][0]

    logger.info(
        "Injected industry design: domain=%s, theme=%s, nav=%s, density=%s",
        domain, design["theme"], design["navigation"], design["density"],
    )

    return app_spec


# ---------------------------------------------------------------------------
# Full design-spec.json generation from industry defaults
# ---------------------------------------------------------------------------

# Theme → complete color palette
_THEME_COLORS: dict[str, dict[str, str]] = {
    "healthcare": {
        "primary": "#0EA5E9", "secondary": "#10B981", "accent": "#6366F1",
        "background": "#F8FAFC", "surface": "#FFFFFF", "muted": "#F1F5F9",
        "error": "#EF4444", "warning": "#F59E0B", "success": "#10B981",
    },
    "finance": {
        "primary": "#1E40AF", "secondary": "#7C3AED", "accent": "#0EA5E9",
        "background": "#F9FAFB", "surface": "#FFFFFF", "muted": "#F3F4F6",
        "error": "#DC2626", "warning": "#D97706", "success": "#059669",
    },
    "logistics": {
        "primary": "#F59E0B", "secondary": "#1E293B", "accent": "#0EA5E9",
        "background": "#0F172A", "surface": "#1E293B", "muted": "#334155",
        "error": "#EF4444", "warning": "#F59E0B", "success": "#22C55E",
    },
    "crm": {
        "primary": "#8B5CF6", "secondary": "#EC4899", "accent": "#06B6D4",
        "background": "#FAFAFA", "surface": "#FFFFFF", "muted": "#F4F4F5",
        "error": "#EF4444", "warning": "#F59E0B", "success": "#22C55E",
    },
    "education": {
        "primary": "#6366F1", "secondary": "#F59E0B", "accent": "#06B6D4",
        "background": "#FAFAFA", "surface": "#FFFFFF", "muted": "#F4F4F5",
        "error": "#EF4444", "warning": "#F59E0B", "success": "#22C55E",
    },
    "hr": {
        "primary": "#10B981", "secondary": "#6366F1", "accent": "#F59E0B",
        "background": "#F9FAF9", "surface": "#FFFFFF", "muted": "#ECFDF5",
        "error": "#EF4444", "warning": "#F59E0B", "success": "#10B981",
    },
    "ecommerce": {
        "primary": "#F97316", "secondary": "#8B5CF6", "accent": "#0EA5E9",
        "background": "#FAFAFA", "surface": "#FFFFFF", "muted": "#F4F4F5",
        "error": "#EF4444", "warning": "#F59E0B", "success": "#22C55E",
    },
    "realestate": {
        "primary": "#92400E", "secondary": "#1E293B", "accent": "#B45309",
        "background": "#FEFCE8", "surface": "#FFFBEB", "muted": "#FEF3C7",
        "error": "#EF4444", "warning": "#F59E0B", "success": "#22C55E",
    },
    "manufacturing": {
        "primary": "#4B5563", "secondary": "#EF4444", "accent": "#F59E0B",
        "background": "#111827", "surface": "#1F2937", "muted": "#374151",
        "error": "#EF4444", "warning": "#F59E0B", "success": "#22C55E",
    },
    "sunset": {
        "primary": "#F97316", "secondary": "#EC4899", "accent": "#FBBF24",
        "background": "#FFFAF7", "surface": "#FFFFFF", "muted": "#FEF3C7",
        "error": "#EF4444", "warning": "#F59E0B", "success": "#22C55E",
    },
    "forest": {
        "primary": "#16A34A", "secondary": "#92400E", "accent": "#0EA5E9",
        "background": "#F7FEF0", "surface": "#FFFFFF", "muted": "#DCFCE7",
        "error": "#EF4444", "warning": "#F59E0B", "success": "#16A34A",
    },
    "ocean": {
        "primary": "#0284C7", "secondary": "#0891B2", "accent": "#6366F1",
        "background": "#F0F9FF", "surface": "#FFFFFF", "muted": "#E0F2FE",
        "error": "#EF4444", "warning": "#F59E0B", "success": "#22C55E",
    },
    "sharp": {
        "primary": "#1E293B", "secondary": "#0EA5E9", "accent": "#F59E0B",
        "background": "#F8FAFC", "surface": "#FFFFFF", "muted": "#F1F5F9",
        "error": "#EF4444", "warning": "#F59E0B", "success": "#22C55E",
    },
}

# Domain → Unsplash login/hero images
_DOMAIN_IMAGES: dict[str, dict[str, str]] = {
    "Healthcare": {
        "loginBackground": "https://images.unsplash.com/photo-1576091160399-112ba8d25d1d?w=1920&q=80",
        "dashboardHero": "https://images.unsplash.com/photo-1505751172876-fa1923c5c528?w=1920&q=80",
    },
    "Finance & Banking": {
        "loginBackground": "https://images.unsplash.com/photo-1611974789855-9c2a0a7236a3?w=1920&q=80",
        "dashboardHero": "https://images.unsplash.com/photo-1460925895917-afdab827c52f?w=1920&q=80",
    },
    "Logistics & Supply Chain": {
        "loginBackground": "https://images.unsplash.com/photo-1586528116311-ad8dd3c8310d?w=1920&q=80",
        "dashboardHero": "https://images.unsplash.com/photo-1578575437130-527eed3abbec?w=1920&q=80",
    },
    "CRM": {
        "loginBackground": "https://images.unsplash.com/photo-1552664730-d307ca884978?w=1920&q=80",
        "dashboardHero": "https://images.unsplash.com/photo-1556761175-b413da4baf72?w=1920&q=80",
    },
    "Sales": {
        "loginBackground": "https://images.unsplash.com/photo-1552664730-d307ca884978?w=1920&q=80",
        "dashboardHero": "https://images.unsplash.com/photo-1556761175-b413da4baf72?w=1920&q=80",
    },
    "Education": {
        "loginBackground": "https://images.unsplash.com/photo-1503676260728-1c00da094a0b?w=1920&q=80",
        "dashboardHero": "https://images.unsplash.com/photo-1427504494785-3a9ca7044f45?w=1920&q=80",
    },
    "Human Resources": {
        "loginBackground": "https://images.unsplash.com/photo-1521737604893-d14cc237f11d?w=1920&q=80",
        "dashboardHero": "https://images.unsplash.com/photo-1522071820081-009f0129c71c?w=1920&q=80",
    },
    "E-Commerce & Retail": {
        "loginBackground": "https://images.unsplash.com/photo-1556742049-0cfed4f6a45d?w=1920&q=80",
        "dashboardHero": "https://images.unsplash.com/photo-1472851294608-062f824d29cc?w=1920&q=80",
    },
    "Real Estate & Property": {
        "loginBackground": "https://images.unsplash.com/photo-1560518883-ce09059eeffa?w=1920&q=80",
        "dashboardHero": "https://images.unsplash.com/photo-1582268611958-ebfd161ef9cf?w=1920&q=80",
    },
    "Manufacturing": {
        "loginBackground": "https://images.unsplash.com/photo-1565008447742-97f6f38c985c?w=1920&q=80",
        "dashboardHero": "https://images.unsplash.com/photo-1513828583688-c52646db42da?w=1920&q=80",
    },
    "Project Management": {
        "loginBackground": "https://images.unsplash.com/photo-1531545514256-b1400bc00f31?w=1920&q=80",
        "dashboardHero": "https://images.unsplash.com/photo-1507925921958-8a62f3d1a50d?w=1920&q=80",
    },
    "Hospitality & Food": {
        "loginBackground": "https://images.unsplash.com/photo-1414235077428-338989a2e8c0?w=1920&q=80",
        "dashboardHero": "https://images.unsplash.com/photo-1517248135467-4c7edcad34c4?w=1920&q=80",
    },
}

_DEFAULT_IMAGES = {
    "loginBackground": "https://images.unsplash.com/photo-1618005182384-a83a8bd57fbe?w=1920&q=80",
    "dashboardHero": None,
}


def get_login_background(domain: str | None) -> str:
    """Industry-relevant Unsplash login image for a domain, with a tasteful default."""
    imgs = _DOMAIN_IMAGES.get((domain or "").strip(), {})
    return imgs.get("loginBackground") or _DEFAULT_IMAGES["loginBackground"]


def _hex_to_hsl_values(hex_color: str) -> tuple[float, float, float]:
    """Convert hex color to (h°, s%, l%) tuple."""
    h_str = hex_color.lstrip("#")
    if len(h_str) != 6:
        return (0.0, 0.0, 0.0)
    r, g, b = int(h_str[0:2], 16) / 255, int(h_str[2:4], 16) / 255, int(h_str[4:6], 16) / 255
    mx, mn = max(r, g, b), min(r, g, b)
    ll = (mx + mn) / 2
    if mx == mn:
        h = s = 0.0
    else:
        d = mx - mn
        s = d / (2.0 - mx - mn) if ll > 0.5 else d / (mx + mn)
        if mx == r:
            h = (g - b) / d + (6 if g < b else 0)
        elif mx == g:
            h = (b - r) / d + 2
        else:
            h = (r - g) / d + 4
        h /= 6
    return round(h * 360, 1), round(s * 100, 1), round(ll * 100, 1)


def hex_to_hsl_var(hex_color: str) -> str:
    """Return HSL values as a CSS custom property value string, e.g. '221.2 83.2% 53.3%'."""
    h, s, l = _hex_to_hsl_values(hex_color)
    return f"{h} {s}% {l}%"


_PALETTE_CHARACTER_ANCHORS: list[tuple[tuple[str, ...], str]] = [
    # Ordered specific-before-general. The first tuple whose ANY keyword
    # appears in the lowercased paletteCharacter wins. Anchor hex is fed
    # into color_theory.derive_palette to build a full spec.
    (("neon", "cyber", "punchy", "electric"),                                  "#A855F7"),
    (("clinical", "medical", "healthcare", "sterile"),                         "#0E7AC0"),
    (("luxurious", "premium", "elegant", "boutique", "refined", "sophisticate"), "#2D1B3D"),
    (("warm earth", "terracotta", "rustic", "artisan", "earthen", "clay"),     "#B26B3B"),
    (("eco", "forest", "natural", "sustainable", "botanical", "verdant"),      "#2E7D32"),
    (("tropical", "hospitality", "sunset", "coral", "sun-drenched"),           "#E07A4D"),
    (("vibrant", "playful", "creative", "youthful", "fun"),                    "#D946EF"),
    (("tech", "futuristic", "digital-first", "saas-modern"),                   "#06B6D4"),
    (("minimal", "monochrome", "stripped", "spare"),                           "#0F172A"),
    (("soft", "pastel", "calm", "serene", "gentle"),                           "#A78BFA"),
    (("muted", "corporate", "professional", "trustworthy", "conservative"),    "#475569"),
    (("warm",),                                                                 "#B26B3B"),
    (("cool", "blue", "azure"),                                                "#1B2A40"),
]


def _palette_anchor_from_character(palette_character: str | None) -> str | None:
    """Map a researched paletteCharacter description to an anchor hex.

    Returns None when no keyword matches — caller falls back to the
    legacy `DOMAIN_THEME` lookup.
    """
    if not palette_character or not isinstance(palette_character, str):
        return None
    lowered = palette_character.lower()
    for keywords, anchor in _PALETTE_CHARACTER_ANCHORS:
        if any(kw in lowered for kw in keywords):
            return anchor
    return None


_HEX_RE = __import__("re").compile(r"^#[0-9A-Fa-f]{6}$")


def _valid_hex(value) -> str | None:
    """Return a normalised `#RRGGBB` if value is a valid hex, else None."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    return v if _HEX_RE.match(v) else None


def _colors_from_dossier_palette(
    visual_language: dict,
) -> dict[str, str] | None:
    """Build a `_THEME_COLORS`-shaped dict from the dossier's visualLanguage.

    Order of preference for the anchor hex:
      1. `colorAnchors.primary` from the discovery agent's output. This is
         the research-grounded path — preferred since the discovery agent
         can sample real brand examples during web search.
      2. Keyword match on `paletteCharacter` against `_PALETTE_CHARACTER_ANCHORS`.
         Fallback for legacy dossiers / when the agent didn't emit anchors.
      3. None — caller falls back to the legacy `DOMAIN_THEME` lookup.

    Once an anchor is chosen, `color_theory.derive_palette` fans it out
    into a full theme dict (background, surface, error/warning/success
    stay neutral). When the dossier provides secondary / accent anchors,
    those override the derived ones too.
    """
    if not isinstance(visual_language, dict):
        return None

    anchors = visual_language.get("colorAnchors")
    primary_hex = (
        _valid_hex((anchors or {}).get("primary")) if isinstance(anchors, dict) else None
    )
    if primary_hex is None:
        primary_hex = _palette_anchor_from_character(
            visual_language.get("paletteCharacter")
        )
    if primary_hex is None:
        return None

    from services.color_theory import derive_palette
    p = derive_palette(primary_hex)

    # Honour dossier-provided secondary/accent if they're valid hex.
    secondary = _valid_hex((anchors or {}).get("secondary")) if isinstance(anchors, dict) else None
    accent = _valid_hex((anchors or {}).get("accent")) if isinstance(anchors, dict) else None

    return {
        "primary": p.primary,
        "secondary": (secondary or p.secondary).upper(),
        "accent": (accent or p.accent).upper(),
        "background": p.background,
        "surface": p.surface,
        "muted": p.background,    # subtle tint of background
        "error": p.error,
        "warning": p.warning,
        "success": p.success,
    }


def generate_design_spec_from_industry(
    domain: str,
    description: str = "",
    plan: dict | None = None,
    domain_context: dict | None = None,
) -> dict[str, Any]:
    """Generate a complete design-spec.json dict from industry defaults.

    Used as a fallback when the LLM design agent fails to produce a spec.
    Returns a full spec compatible with design_agent.save_design_spec().

    `domain_context` is the research dossier from the discovery agent. When
    its `visualLanguage` carries `paletteCharacter` / `typographyTone` /
    `densityPreference`, those override the hardcoded per-domain defaults
    so two HR apps with different palette descriptions get different colours
    (instead of both falling back to the fixed `_THEME_COLORS["hr"]` map).
    """
    domain = _DOMAIN_ALIAS.get((domain or "").strip().lower(), domain)
    theme = DOMAIN_THEME.get(domain, "ocean")
    layout = dict(DOMAIN_LAYOUT.get(domain, _DEFAULT_LAYOUT))
    images = _DOMAIN_IMAGES.get(domain, _DEFAULT_IMAGES)

    # Dossier overrides (when provided + matching keyword found)
    visual_language: dict = {}
    if isinstance(domain_context, dict):
        vl = domain_context.get("visualLanguage")
        if isinstance(vl, dict):
            visual_language = vl

    dossier_colors = _colors_from_dossier_palette(visual_language) if visual_language else None
    colors = dossier_colors or _THEME_COLORS.get(theme, _THEME_COLORS["ocean"])

    # densityPreference may be "compact" / "comfortable" / "spacious" etc.
    density_pref = (visual_language.get("densityPreference") or "").strip().lower()
    if density_pref in ("compact", "comfortable", "spacious"):
        layout["density"] = density_pref

    # Detect dark theme
    bg = colors["background"]
    _, _, bg_l = _hex_to_hsl_values(bg)
    is_dark = bg_l < 30

    # Build entity patterns from plan
    entity_patterns: dict[str, str] = {}
    if plan:
        for entity in plan.get("data_models", []):
            name = entity.get("name", "")
            name_lower = name.lower()
            for key, pattern in layout["priority_patterns"].items():
                if key in name_lower:
                    entity_patterns[name] = pattern
                    break

    # Component style based on density (domain-aware heuristics were
    # dropped — they baked in stale opinions about which industries get
    # pill buttons / mobile-first / isometric empty states; the LLM
    # design agent or the dossier now drives these choices, and the
    # fallback path emits neutral defaults).
    density = layout["density"]
    nav = layout["navigation"]
    card_style = "shadow" if density == "spacious" else "bordered" if density == "compact" else "shadow"
    table_style = "striped" if density == "compact" else "clean"
    input_style = "filled" if density == "spacious" else "outlined"
    btn_style = "rounded"

    # Typography — prefer dossier-provided fontFamily (the new
    # discovery-agent-emits-it path), fall back to Inter only when the
    # dossier didn't supply one.
    dossier_font = str(visual_language.get("fontFamily", "")).strip()
    font_family = dossier_font or "Inter, system-ui, sans-serif"

    rationale = layout.get("description", f"Industry-standard design for {domain} applications.")

    return {
        "colorPalette": colors,
        "typography": {
            "fontFamily": font_family,
            "headingWeight": "700" if density == "spacious" else "600",
            "bodySize": "13px" if density == "compact" else "14px" if density == "comfortable" else "15px",
        },
        "layout": {
            "navigation": nav,
            "density": density,
            "borderRadius": "xl" if density == "spacious" else "md",
            "spacing": "tight" if density == "compact" else "relaxed" if density == "spacious" else "normal",
        },
        "responsive": {
            "strategy": "desktop-first",
            "mobileNav": "bottom-tabs",
            "breakpoints": {"sm": "640px", "md": "768px", "lg": "1024px", "xl": "1280px"},
        },
        "imagery": {
            "loginBackground": images.get("loginBackground"),
            "dashboardHero": images.get("dashboardHero"),
            "emptyStateStyle": "flat",
            "avatarStyle": "initials",
            "placeholderImages": {},
        },
        "dashboardWidgets": layout["dashboard_widgets"],
        "entityPatterns": entity_patterns,
        "componentStyle": {
            "buttons": btn_style,
            "cards": card_style,
            "tables": table_style,
            "inputs": input_style,
        },
        "designRationale": rationale,
        "_source": "industry-defaults",
    }


def generate_css_variables_from_spec(spec: dict[str, Any]) -> str:
    """Generate the complete CSS :root variable block from a design-spec.

    Returns a string ready to paste directly into globals.css.
    Converts hex colors to HSL format as required by shadcn/ui.
    """
    palette = spec.get("colorPalette", {})
    layout = spec.get("layout", {})
    typography = spec.get("typography", {})
    font_family = str(typography.get("fontFamily") or "").strip() or '"Inter", system-ui, -apple-system, sans-serif'

    primary = palette.get("primary", "#0284C7")
    secondary = palette.get("secondary", "#0891B2")
    accent = palette.get("accent", "#6366F1")
    background = palette.get("background", "#FFFFFF")
    surface = palette.get("surface", "#FFFFFF")
    muted = palette.get("muted", "#F1F5F9")
    error = palette.get("error", "#EF4444")
    warning = palette.get("warning", "#F59E0B")
    success = palette.get("success", "#22C55E")

    # Detect dark mode background
    _, _, bg_l = _hex_to_hsl_values(background)
    is_dark = bg_l < 30

    radius_map = {"none": "0rem", "sm": "0.25rem", "md": "0.375rem", "lg": "0.5rem", "xl": "0.75rem"}
    radius = radius_map.get(layout.get("borderRadius", "md"), "0.5rem")

    fg = palette.get("foreground", "#0F172A" if not is_dark else "#F8FAFC")
    _, _, fg_l = _hex_to_hsl_values(fg)

    # foreground should be opposite of background
    if is_dark:
        foreground_hsl = "210 40% 98%"
        card_hsl = hex_to_hsl_var(surface)
        border_hsl = "217 33% 25%"
        muted_hsl = hex_to_hsl_var(muted)
        muted_fg_hsl = "215 20% 65%"
    else:
        foreground_hsl = "222 47% 11%"
        card_hsl = "0 0% 100%"
        border_hsl = "214 32% 91%"
        muted_hsl = hex_to_hsl_var(muted)
        muted_fg_hsl = "215 16% 47%"

    return f"""@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {{
  :root {{
    --background: {hex_to_hsl_var(background)};
    --foreground: {foreground_hsl};

    --card: {card_hsl};
    --card-foreground: {foreground_hsl};

    --popover: {card_hsl};
    --popover-foreground: {foreground_hsl};

    --primary: {hex_to_hsl_var(primary)};
    --primary-foreground: {"0 0% 100%" if not is_dark else "222 47% 11%"};

    --secondary: {hex_to_hsl_var(secondary)};
    --secondary-foreground: {"0 0% 100%"};

    --muted: {muted_hsl};
    --muted-foreground: {muted_fg_hsl};

    --accent: {hex_to_hsl_var(accent)};
    --accent-foreground: {"0 0% 100%"};

    --destructive: {hex_to_hsl_var(error)};
    --destructive-foreground: 0 0% 100%;

    --border: {border_hsl};
    --input: {border_hsl};
    --ring: {hex_to_hsl_var(primary)};

    --radius: {radius};

    /* Semantic status colors */
    --color-success: {hex_to_hsl_var(success)};
    --color-warning: {hex_to_hsl_var(warning)};
    --color-error: {hex_to_hsl_var(error)};
  }}

  /* Dark mode overrides — kept consistent with light theme hues */
  .dark {{
    --background: 222 47% 8%;
    --foreground: 210 40% 98%;
    --card: 222 47% 11%;
    --card-foreground: 210 40% 98%;
    --border: 217 33% 18%;
    --muted: 217 33% 15%;
    --muted-foreground: 215 20% 60%;
  }}
}}

/* ── Global base styles ─────────────────────────────────────────── */

body {{
  font-family: {font_family};
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
  background-color: hsl(var(--background));
  color: hsl(var(--foreground));
}}

/* ── MICRO-INTERACTIONS (every interactive element must feel alive) ── */

/* All interactive elements get smooth transitions */
button, a, input, select, textarea, [role="button"], [role="tab"], [role="menuitem"] {{
  transition: all 150ms cubic-bezier(0.4, 0, 0.2, 1);
}}

/* Primary focus ring — consistent across all focusable elements */
:focus-visible {{
  outline: 2px solid hsl(var(--ring));
  outline-offset: 2px;
  border-radius: calc(var(--radius) - 2px);
}}

/* Buttons: press response */
button:active:not(:disabled), [role="button"]:active {{
  transform: scale(0.98);
}}

/* Links: color transition on hover */
a:hover {{
  opacity: 0.9;
}}

/* Inputs: glow on focus */
input:focus, select:focus, textarea:focus {{
  box-shadow: 0 0 0 3px hsl(var(--primary) / 0.1);
  border-color: hsl(var(--primary));
}}

/* ── CARDS — depth and lift ────────────────────────────────────── */

/* Every card gets hover lift by default via Tailwind's shadow utilities */
@layer utilities {{
  .card-interactive {{
    transition: box-shadow 200ms ease, transform 200ms ease;
  }}
  .card-interactive:hover {{
    box-shadow: 0 8px 25px -5px rgba(0, 0, 0, 0.08), 0 4px 10px -6px rgba(0, 0, 0, 0.04);
    transform: translateY(-2px);
  }}
}}

/* ── SCROLLBAR ─────────────────────────────────────────────────── */

::-webkit-scrollbar {{ width: 6px; height: 6px; }}
::-webkit-scrollbar-track {{ background: transparent; }}
::-webkit-scrollbar-thumb {{ background: hsl(var(--border)); border-radius: 3px; }}
::-webkit-scrollbar-thumb:hover {{ background: hsl(var(--muted-foreground)); }}

/* ── STAT CARDS — gradient backgrounds ─────────────────────────── */

.stat-card-primary {{
  background: linear-gradient(135deg, hsl(var(--primary) / 0.08), hsl(var(--primary) / 0.03));
  border-left: 3px solid hsl(var(--primary));
}}
.stat-card-secondary {{
  background: linear-gradient(135deg, hsl(var(--secondary) / 0.08), hsl(var(--secondary) / 0.03));
  border-left: 3px solid hsl(var(--secondary));
}}
.stat-card-success {{
  background: linear-gradient(135deg, hsl(var(--color-success) / 0.08), hsl(var(--color-success) / 0.03));
  border-left: 3px solid hsl(var(--color-success));
}}
.stat-card-warning {{
  background: linear-gradient(135deg, hsl(var(--color-warning) / 0.08), hsl(var(--color-warning) / 0.03));
  border-left: 3px solid hsl(var(--color-warning));
}}

/* ── HERO BANNER — for dashboards ──────────────────────────────── */

.hero-gradient {{
  background: linear-gradient(135deg, hsl(var(--primary)), hsl(var(--accent, var(--primary))));
  color: white;
}}

/* Gradient text utility */
.gradient-text {{
  background: linear-gradient(135deg, hsl(var(--primary)), hsl(var(--accent, var(--secondary))));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}}

/* ── TABLES — modern and readable ──────────────────────────────── */

/* Table rows hover highlight */
table tbody tr {{
  transition: background-color 150ms ease;
}}
table tbody tr:hover {{
  background-color: hsl(var(--muted) / 0.5);
}}

/* Sticky table header */
table thead {{
  position: sticky;
  top: 0;
  z-index: 1;
  background-color: hsl(var(--background));
}}

/* ── STATUS BADGES — colored dots ──────────────────────────────── */

.status-dot {{
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 6px;
}}
.status-dot-success {{ background-color: hsl(var(--color-success)); }}
.status-dot-warning {{ background-color: hsl(var(--color-warning)); }}
.status-dot-error {{ background-color: hsl(var(--color-error)); }}
.status-dot-info {{ background-color: hsl(var(--primary)); }}
.status-dot-muted {{ background-color: hsl(var(--muted-foreground)); }}

/* Pulsing status for active/critical items */
.status-dot-pulse {{
  animation: pulse-dot 2s infinite;
}}
@keyframes pulse-dot {{
  0%, 100% {{ opacity: 1; }}
  50% {{ opacity: 0.4; }}
}}

/* ── LOADING STATES ────────────────────────────────────────────── */

/* Shimmer skeleton */
@keyframes shimmer {{
  0% {{ background-position: -200% 0; }}
  100% {{ background-position: 200% 0; }}
}}
.skeleton {{
  background: linear-gradient(90deg, hsl(var(--muted)) 25%, hsl(var(--muted-foreground) / 0.08) 50%, hsl(var(--muted)) 75%);
  background-size: 200% 100%;
  animation: shimmer 1.5s ease-in-out infinite;
  border-radius: var(--radius);
}}

/* Spinner */
@keyframes spin {{
  to {{ transform: rotate(360deg); }}
}}
.spinner {{
  width: 1rem;
  height: 1rem;
  border: 2px solid hsl(var(--muted));
  border-top-color: hsl(var(--primary));
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}}

/* ── SIDEBAR — dark/light variants ─────────────────────────────── */

/* Sidebar active item */
.sidebar-active {{
  background-color: hsl(var(--primary) / 0.1);
  color: hsl(var(--primary));
  font-weight: 500;
  border-right: 2px solid hsl(var(--primary));
}}

/* Sidebar hover */
.sidebar-item:hover {{
  background-color: hsl(var(--muted) / 0.5);
}}

/* ── FORM ENHANCEMENTS ─────────────────────────────────────────── */

/* Form field labels */
label {{
  font-size: 0.875rem;
  font-weight: 500;
  color: hsl(var(--foreground));
}}

/* Required field indicator */
label.required::after {{
  content: " *";
  color: hsl(var(--destructive));
}}

/* Disabled state */
:disabled {{
  opacity: 0.5;
  cursor: not-allowed;
}}

/* ── TOAST / NOTIFICATION ──────────────────────────────────────── */

@keyframes slide-in-right {{
  from {{ transform: translateX(100%); opacity: 0; }}
  to {{ transform: translateX(0); opacity: 1; }}
}}
.toast-enter {{
  animation: slide-in-right 300ms ease-out;
}}

/* ── PAGE TRANSITIONS ──────────────────────────────────────────── */

@keyframes fade-in {{
  from {{ opacity: 0; transform: translateY(4px); }}
  to {{ opacity: 1; transform: translateY(0); }}
}}
.page-enter {{
  animation: fade-in 200ms ease-out;
}}

/* ── SECTION DIVIDER ───────────────────────────────────────────── */

.section-divider {{
  border-top: 1px solid hsl(var(--border));
  margin: 1.5rem 0;
}}

/* ── AVATAR ────────────────────────────────────────────────────── */

.avatar-fallback {{
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: hsl(var(--primary) / 0.1);
  color: hsl(var(--primary));
  font-weight: 600;
  font-size: 0.875rem;
}}

/* ── EMPTY STATE ───────────────────────────────────────────────── */

.empty-state {{
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 3rem 1rem;
  text-align: center;
  gap: 0.75rem;
}}
.empty-state svg {{
  width: 3rem;
  height: 3rem;
  color: hsl(var(--muted-foreground));
}}

/* ── BREADCRUMBS ───────────────────────────────────────────────── */

.breadcrumb {{
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.875rem;
  color: hsl(var(--muted-foreground));
}}
.breadcrumb a:hover {{
  color: hsl(var(--foreground));
}}
.breadcrumb-separator {{
  color: hsl(var(--border));
}}
"""
