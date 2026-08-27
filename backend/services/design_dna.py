"""design_dna — derives a distinct, premium, domain-appropriate design identity
for every generated app.

Why this exists
---------------
Every app the pipeline generated used to converge on one look: same shell, same
shapes, same density, near-default palette — because the LLM's design-spec was
(a) full of prose-polluted values the browser silently dropped, and (b) chosen
from an unconstrained space, so the model gravitated to its statistical center
(Inter + indigo + soft cards = the "AI look").

This module replaces guesswork with a *curated design space*:

* 14 domain **archetypes** — each a real art-directed stance (hue bands, neutral
  temperature, shape language, elevation style, density, motion, shell recipe)
  grounded in industry conventions (fintech = precision/cool/dense; petcare =
  warm/rounded/friendly; legal = editorial serif/paper; dev-tools = graphite +
  electric accent + mono numerals; …).
* 18 vetted **font pairings** — all on Google Fonts, all premium-grade, each
  with weights, letter-spacing and a numeric strategy (tabular for data apps).
* Deterministic **seeded variety** — the project id seeds hue jitter, pairing
  choice, radius, rail tone… so two apps in the same domain still differ, while
  regeneration of the same project is stable.
* **WCAG contrast enforcement** — anchors are adjusted until interactive color
  on white meets AA (≥ 4.5:1), rails meet ≥ 7:1 for their text.

The DNA feeds three consumers:
1. ``to_design_spec(dna)`` — a complete, machine-valid design-spec used as the
   merge-base under (and fallback for) the design agent's LLM output.
2. ``prompt_brief(dna)`` — a compact art-direction brief injected into the
   design/shell agent prompts so the LLM *refines* a distinct identity instead
   of reinventing the same one.
3. ``to_css_variables(dna)`` — the shadcn-style HSL variable block for
   globals.css when no LLM CSS is available.

Everything here is dependency-free, pure, and deterministic.
"""
from __future__ import annotations

import colorsys
import hashlib
import re

# ---------------------------------------------------------------------------
# Color math
# ---------------------------------------------------------------------------

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6})$")


def _hex_to_rgb(hex_str: str) -> tuple[float, float, float]:
    m = _HEX_RE.match(hex_str.strip())
    if not m:
        raise ValueError(f"invalid hex: {hex_str!r}")
    h = m.group(1)
    return int(h[0:2], 16) / 255, int(h[2:4], 16) / 255, int(h[4:6], 16) / 255


def _hsl_to_hex(h_deg: float, s: float, l: float) -> str:
    """HSL (hue in degrees, s/l in 0..1) → #rrggbb."""
    r, g, b = colorsys.hls_to_rgb((h_deg % 360) / 360.0,
                                  max(0.0, min(1.0, l)),
                                  max(0.0, min(1.0, s)))
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def _hex_to_hsl(hex_str: str) -> tuple[float, float, float]:
    r, g, b = _hex_to_rgb(hex_str)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return h * 360.0, s, l


def _rel_luminance(hex_str: str) -> float:
    def chan(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _hex_to_rgb(hex_str)
    return 0.2126 * chan(r) + 0.7152 * chan(g) + 0.0722 * chan(b)


def contrast_ratio(fg: str, bg: str) -> float:
    """WCAG contrast ratio between two hex colors."""
    l1, l2 = _rel_luminance(fg), _rel_luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def ensure_contrast(fg: str, bg: str, minimum: float = 4.5, *, darken: bool = True) -> str:
    """Nudge ``fg`` lightness until it reaches ``minimum`` contrast on ``bg``.

    Walks lightness in 2% steps (darker by default — right for colored
    controls on light surfaces). Returns the adjusted hex; gives up (returns
    the last attempt) after 30 steps so it can never loop forever.
    """
    h, s, l = _hex_to_hsl(fg)
    out = fg
    for _ in range(30):
        if contrast_ratio(out, bg) >= minimum:
            return out
        l = max(0.02, l - 0.02) if darken else min(0.98, l + 0.02)
        out = _hsl_to_hex(h, s, l)
    return out


def _hsl_triplet(hex_str: str) -> str:
    """#rrggbb → ``H S% L%`` (the shadcn CSS-variable channel format)."""
    h, s, l = _hex_to_hsl(hex_str)
    return f"{round(h) % 360} {round(s * 100)}% {round(l * 100)}%"


# ---------------------------------------------------------------------------
# Font pairing bank — every family verified on Google Fonts.
# ``import``: the css2 families param pieces; ``heading``/``body``: CSS stacks.
# ---------------------------------------------------------------------------

FONT_PAIRINGS: dict[str, dict] = {
    "inter-precision": {
        "heading": "'Inter', system-ui, sans-serif", "headingWeight": "650",
        "body": "'Inter', system-ui, sans-serif", "bodyWeight": "400",
        "letterSpacing": "-0.02em", "tabularNumbers": True,
        "import": ["Inter:wght@400;500;650;700"],
        "voice": "neutral precision — data-dense products",
    },
    "geist-clean": {
        "heading": "'Geist', system-ui, sans-serif", "headingWeight": "600",
        "body": "'Geist', system-ui, sans-serif", "bodyWeight": "400",
        "letterSpacing": "-0.015em", "tabularNumbers": True,
        "import": ["Geist:wght@400;500;600;700"],
        "voice": "engineered calm — modern dev/SaaS",
    },
    "sora-tech": {
        "heading": "'Sora', system-ui, sans-serif", "headingWeight": "600",
        "body": "'Albert Sans', system-ui, sans-serif", "bodyWeight": "400",
        "letterSpacing": "-0.02em", "tabularNumbers": False,
        "import": ["Sora:wght@500;600;700", "Albert+Sans:wght@400;500;600"],
        "voice": "geometric premium tech",
    },
    "space-grotesk-terminal": {
        "heading": "'Space Grotesk', system-ui, sans-serif", "headingWeight": "600",
        "body": "'IBM Plex Sans', system-ui, sans-serif", "bodyWeight": "400",
        "numeric": "'JetBrains Mono', monospace",
        "letterSpacing": "-0.01em", "tabularNumbers": True,
        "import": ["Space+Grotesk:wght@500;600;700", "IBM+Plex+Sans:wght@400;500;600", "JetBrains+Mono:wght@400;500"],
        "voice": "terminal soul — developer tools",
    },
    "bricolage-bold": {
        "heading": "'Bricolage Grotesque', system-ui, sans-serif", "headingWeight": "700",
        "body": "'Figtree', system-ui, sans-serif", "bodyWeight": "400",
        "letterSpacing": "-0.01em", "tabularNumbers": False,
        "import": ["Bricolage+Grotesque:wght@500;600;700;800", "Figtree:wght@400;500;600"],
        "voice": "characterful confidence — consumer/creative",
    },
    "fraunces-editorial": {
        "heading": "'Fraunces', Georgia, serif", "headingWeight": "600",
        "body": "'Libre Franklin', system-ui, sans-serif", "bodyWeight": "400",
        "letterSpacing": "0", "tabularNumbers": False,
        "import": ["Fraunces:opsz,wght@9..144,500;9..144,600;9..144,700", "Libre+Franklin:wght@400;500;600"],
        "voice": "editorial gravitas with warmth",
    },
    "newsreader-counsel": {
        "heading": "'Newsreader', Georgia, serif", "headingWeight": "500",
        "body": "'Source Sans 3', system-ui, sans-serif", "bodyWeight": "400",
        "letterSpacing": "0", "tabularNumbers": False,
        "import": ["Newsreader:opsz,wght@6..72,500;6..72,600", "Source+Sans+3:wght@400;500;600"],
        "voice": "quiet counsel — legal/professional",
    },
    "manrope-humanist": {
        "heading": "'Manrope', system-ui, sans-serif", "headingWeight": "700",
        "body": "'Manrope', system-ui, sans-serif", "bodyWeight": "400",
        "letterSpacing": "-0.02em", "tabularNumbers": True,
        "import": ["Manrope:wght@400;500;700;800"],
        "voice": "humanist modern SaaS",
    },
    "jakarta-warm": {
        "heading": "'Plus Jakarta Sans', system-ui, sans-serif", "headingWeight": "700",
        "body": "'Figtree', system-ui, sans-serif", "bodyWeight": "400",
        "letterSpacing": "-0.015em", "tabularNumbers": False,
        "import": ["Plus+Jakarta+Sans:wght@500;600;700", "Figtree:wght@400;500;600"],
        "voice": "warm professional — people products",
    },
    "nunito-round": {
        "heading": "'Nunito', system-ui, sans-serif", "headingWeight": "800",
        "body": "'Nunito', system-ui, sans-serif", "bodyWeight": "400",
        "letterSpacing": "-0.01em", "tabularNumbers": False,
        "import": ["Nunito:wght@400;600;700;800"],
        "voice": "rounded friendliness — consumer care",
    },
    "gabarito-fresh": {
        "heading": "'Gabarito', system-ui, sans-serif", "headingWeight": "700",
        "body": "'Hanken Grotesk', system-ui, sans-serif", "bodyWeight": "400",
        "letterSpacing": "-0.01em", "tabularNumbers": False,
        "import": ["Gabarito:wght@500;600;700", "Hanken+Grotesk:wght@400;500;600"],
        "voice": "fresh clarity — education/consumer",
    },
    "outfit-geometric": {
        "heading": "'Outfit', system-ui, sans-serif", "headingWeight": "600",
        "body": "'Karla', system-ui, sans-serif", "bodyWeight": "400",
        "letterSpacing": "-0.01em", "tabularNumbers": False,
        "import": ["Outfit:wght@500;600;700", "Karla:wght@400;500;600"],
        "voice": "geometric retail energy",
    },
    "archivo-industrial": {
        "heading": "'Archivo', system-ui, sans-serif", "headingWeight": "700",
        "body": "'Barlow', system-ui, sans-serif", "bodyWeight": "400",
        "letterSpacing": "0", "tabularNumbers": True,
        "import": ["Archivo:wght@500;600;700;800", "Barlow:wght@400;500;600"],
        "voice": "industrial utility — ops/logistics",
    },
    "schibsted-signal": {
        "heading": "'Schibsted Grotesk', system-ui, sans-serif", "headingWeight": "700",
        "body": "'Mulish', system-ui, sans-serif", "bodyWeight": "400",
        "letterSpacing": "-0.015em", "tabularNumbers": True,
        "import": ["Schibsted+Grotesk:wght@500;600;700", "Mulish:wght@400;500;600"],
        "voice": "news-desk signal — media/analytics",
    },
    "lora-hospitality": {
        "heading": "'Lora', Georgia, serif", "headingWeight": "600",
        "body": "'Karla', system-ui, sans-serif", "bodyWeight": "400",
        "letterSpacing": "0", "tabularNumbers": False,
        "import": ["Lora:wght@500;600;700", "Karla:wght@400;500;600"],
        "voice": "warm premium — hospitality/estate",
    },
    "instrument-quiet": {
        "heading": "'Instrument Sans', system-ui, sans-serif", "headingWeight": "600",
        "body": "'Instrument Sans', system-ui, sans-serif", "bodyWeight": "400",
        "letterSpacing": "-0.01em", "tabularNumbers": False,
        "import": ["Instrument+Sans:wght@400;500;600;700"],
        "voice": "quiet minimal premium",
    },
    "plex-institutional": {
        "heading": "'IBM Plex Sans', system-ui, sans-serif", "headingWeight": "600",
        "body": "'IBM Plex Sans', system-ui, sans-serif", "bodyWeight": "400",
        "numeric": "'IBM Plex Mono', monospace",
        "letterSpacing": "0", "tabularNumbers": True,
        "import": ["IBM+Plex+Sans:wght@400;500;600;700", "IBM+Plex+Mono:wght@400;500"],
        "voice": "institutional trust — enterprise/gov",
    },
    "work-sans-clear": {
        "heading": "'Work Sans', system-ui, sans-serif", "headingWeight": "600",
        "body": "'Work Sans', system-ui, sans-serif", "bodyWeight": "400",
        "letterSpacing": "-0.01em", "tabularNumbers": False,
        "import": ["Work+Sans:wght@400;500;600;700"],
        "voice": "plainspoken clarity",
    },
}


# ---------------------------------------------------------------------------
# Archetype bank — each entry is an art-directed stance, not a suggestion.
# hue bands are (lo, hi) degrees; sat/light bands are (lo, hi) in 0..1.
# ---------------------------------------------------------------------------

ARCHETYPES: dict[str, dict] = {
    "fintech": {
        "keywords": ["fintech", "finance", "bank", "payment", "invoice", "accounting",
                     "expense", "budget", "trading", "loan", "tax", "payroll", "billing",
                     "treasury", "wallet", "insurance"],
        "hues": [(158, 172), (210, 224), (248, 260)],
        "sat": (0.45, 0.60), "light": (0.32, 0.42),
        "neutral": "cool",
        "pairings": ["inter-precision", "geist-clean", "schibsted-signal", "plex-institutional"],
        "radius": ["sharp", "soft"], "elevation": ["bordered", "flat"],
        "density": ["compact", "comfortable"], "motion": "subtle", "scaleMode": "compact",
        "rail": ["dark", "light"], "frames": ["sidebar"], "iconStroke": 1.75, "surface": "plain",
        "principles": "Precision earns trust. Dense tabular data, hairline borders, "
                      "restrained single accent, tabular numerals. Nothing decorative.",
    },
    "healthcare": {
        "keywords": ["health", "healthcare", "medical", "clinic", "patient", "doctor", "hospital",
                     "care", "therapy", "wellness", "pharmacy", "dental", "vet",
                     "appointment", "telemedicine"],
        "hues": [(172, 196), (202, 226), (150, 172)],
        "sat": (0.35, 0.50), "light": (0.38, 0.46),
        "neutral": "cool",
        "pairings": ["jakarta-warm", "work-sans-clear", "manrope-humanist", "gabarito-fresh"],
        "radius": ["soft", "round"], "elevation": ["layered"],
        "density": ["comfortable", "spacious"], "motion": "subtle", "scaleMode": "balanced",
        "rail": ["light"], "frames": ["sidebar"], "iconStroke": 1.75, "surface": "plain",
        "principles": "Calm and legible above all. Airy spacing, soft depth, cool mist "
                      "palette, generous type. Never alarming except true alerts.",
    },
    "consumer-warm": {
        "keywords": ["pet", "cat", "dog", "food", "recipe", "family", "kids", "baby",
                     "garden", "plant", "hobby", "craft", "community", "social", "care"],
        "hues": [(14, 30), (28, 40), (2, 12)],
        "sat": (0.58, 0.75), "light": (0.42, 0.50),
        "neutral": "warm",
        "pairings": ["nunito-round", "bricolage-bold", "gabarito-fresh", "jakarta-warm"],
        "radius": ["round", "soft"], "elevation": ["layered"],
        "density": ["comfortable"], "motion": "subtle", "scaleMode": "balanced",
        "rail": ["light", "tinted"], "frames": ["sidebar"], "iconStroke": 2.25, "surface": "tinted",
        "principles": "Warmth is the brand. Cream-tinted surfaces, rounded shapes, "
                      "terracotta/amber palette, friendly rounded type.",
    },
    "legal": {
        "keywords": ["legal", "law", "attorney", "contract", "compliance", "court",
                     "counsel", "case", "firm", "notary", "audit", "policy", "governance"],
        "hues": [(215, 235), (345, 356), (158, 170)],
        "sat": (0.25, 0.45), "light": (0.24, 0.34),
        "neutral": "warm",
        "pairings": ["fraunces-editorial", "newsreader-counsel", "plex-institutional"],
        "radius": ["sharp", "soft"], "elevation": ["flat", "bordered"],
        "density": ["comfortable"], "motion": "none", "scaleMode": "balanced",
        "rail": ["dark", "light"], "frames": ["sidebar"], "iconStroke": 1.5, "surface": "tinted",
        "principles": "Editorial gravitas: serif display on warm paper neutrals, ink "
                      "palette, hairline rules, square corners, zero ornament.",
    },
    "creative": {
        "keywords": ["design", "creative", "agency", "studio", "portfolio", "media",
                     "marketing", "brand", "content", "video", "photo", "art", "music",
                     "campaign", "event"],
        "hues": [(262, 280), (328, 344), (12, 24)],
        "sat": (0.60, 0.80), "light": (0.44, 0.54),
        "neutral": "neutral-ink",
        "pairings": ["bricolage-bold", "sora-tech", "space-grotesk-terminal"],
        "radius": ["sharp", "round"], "elevation": ["floating"],
        "density": ["comfortable"], "motion": "expressive", "scaleMode": "display",
        "rail": ["dark", "brand"], "frames": ["sidebar", "topbar"], "iconStroke": 2.0, "surface": "plain",
        "principles": "Confident and expressive: big display type, high-contrast "
                      "ink/white with one electric accent, dramatic scale jumps.",
    },
    "developer": {
        "keywords": ["developer", "api", "devops", "code", "deploy", "infrastructure",
                     "monitoring", "logs", "logging", "database", "cloud", "sdk", "cli", "git",
                     "pipeline", "observability"],
        "hues": [(150, 166), (186, 200), (258, 270)],
        "sat": (0.50, 0.68), "light": (0.40, 0.48),
        "neutral": "cool-graphite",
        "pairings": ["space-grotesk-terminal", "geist-clean", "inter-precision"],
        "radius": ["sharp", "soft"], "elevation": ["bordered"],
        "density": ["compact"], "motion": "subtle", "scaleMode": "compact",
        "rail": ["dark"], "frames": ["sidebar"], "iconStroke": 1.75, "surface": "plain",
        "modes": ["light", "dark"],
        "principles": "Terminal heritage: graphite neutrals, one electric accent, mono "
                      "numerals, square corners, information density as a feature.",
    },
    "logistics": {
        "keywords": ["logistics", "fleet", "shipping", "delivery", "warehouse",
                     "inventory", "supply", "tracking", "dispatch", "freight", "field",
                     "inspection", "maintenance", "asset"],
        "hues": [(14, 34), (200, 224), (36, 48)],
        "sat": (0.55, 0.72), "light": (0.42, 0.48),
        "neutral": "cool-steel",
        "pairings": ["archivo-industrial", "inter-precision", "plex-institutional"],
        "radius": ["sharp", "soft"], "elevation": ["bordered"],
        "density": ["compact"], "motion": "none", "scaleMode": "compact",
        "rail": ["dark"], "frames": ["sidebar"], "iconStroke": 2.25, "surface": "plain",
        "principles": "Built for gloves and glare: high contrast, safety-orange or "
                      "steel accents, big touch targets, square utilitarian shapes.",
    },
    "education": {
        "keywords": ["education", "school", "course", "learning", "student", "teacher",
                     "training", "quiz", "curriculum", "tutor", "class", "lesson"],
        "hues": [(190, 214), (36, 52), (262, 278)],
        "sat": (0.50, 0.65), "light": (0.42, 0.50),
        "neutral": "warm",
        "pairings": ["gabarito-fresh", "work-sans-clear", "jakarta-warm", "nunito-round"],
        "radius": ["soft", "round"], "elevation": ["layered"],
        "density": ["comfortable"], "motion": "subtle", "scaleMode": "balanced",
        "rail": ["light"], "frames": ["sidebar", "topbar"], "iconStroke": 2.0, "surface": "tinted",
        "principles": "Optimistic clarity: sky/marigold palette, friendly rounded "
                      "shapes, encouraging progress states.",
    },
    "hospitality": {
        "keywords": ["hotel", "restaurant", "booking", "travel", "real estate",
                     "property", "rental", "venue", "reservation", "estate", "resort",
                     "airbnb", "tenant", "lease"],
        "hues": [(150, 165), (24, 36), (215, 230)],
        "sat": (0.30, 0.50), "light": (0.30, 0.42),
        "neutral": "warm",
        "pairings": ["lora-hospitality", "fraunces-editorial", "instrument-quiet"],
        "radius": ["soft", "round"], "elevation": ["layered"],
        "density": ["spacious", "comfortable"], "motion": "subtle", "scaleMode": "display",
        "rail": ["dark", "light"], "frames": ["sidebar", "topbar"], "iconStroke": 1.5, "surface": "tinted",
        "principles": "Quiet luxury: serif display, champagne/forest/midnight palette, "
                      "generous whitespace, soft deep shadows.",
    },
    "hr-people": {
        "keywords": ["hr", "employee", "recruiting", "hiring", "onboarding", "people",
                     "team", "workforce", "talent", "leave", "attendance", "org"],
        "hues": [(6, 18), (288, 305), (168, 180)],
        "sat": (0.50, 0.65), "light": (0.44, 0.52),
        "neutral": "warm",
        "pairings": ["jakarta-warm", "manrope-humanist", "gabarito-fresh"],
        "radius": ["round", "soft"], "elevation": ["layered"],
        "density": ["comfortable"], "motion": "subtle", "scaleMode": "balanced",
        "rail": ["light", "tinted"], "frames": ["sidebar"], "iconStroke": 2.0, "surface": "plain",
        "principles": "Human first: coral/plum warmth, rounded avatars everywhere, "
                      "approachable density, celebratory moments.",
    },
    "commerce": {
        "keywords": ["shop", "store", "commerce", "retail", "product", "order", "cart",
                     "catalog", "sales", "point of sale", "merchant", "customer", "crm"],
        "hues": [(200, 214), (338, 352), (145, 158)],
        "sat": (0.55, 0.70), "light": (0.42, 0.50),
        "neutral": "neutral",
        "pairings": ["outfit-geometric", "manrope-humanist", "bricolage-bold"],
        "radius": ["soft", "sharp"], "elevation": ["layered"],
        "density": ["comfortable", "compact"], "motion": "subtle", "scaleMode": "balanced",
        "rail": ["dark", "light"], "frames": ["sidebar", "topbar"], "iconStroke": 2.0, "surface": "plain",
        "principles": "Merchandising energy with operational calm: crisp geometry, "
                      "one decisive CTA color, strong price/number typography.",
    },
    "industrial": {
        "keywords": ["manufacturing", "factory", "energy", "utility", "construction",
                     "equipment", "plant", "production", "quality", "safety", "iot"],
        "hues": [(200, 224), (32, 48), (166, 180)],
        "sat": (0.35, 0.50), "light": (0.36, 0.44),
        "neutral": "cool-steel",
        "pairings": ["archivo-industrial", "plex-institutional", "inter-precision"],
        "radius": ["sharp", "soft"], "elevation": ["bordered"],
        "density": ["compact"], "motion": "none", "scaleMode": "compact",
        "rail": ["dark"], "frames": ["sidebar"], "iconStroke": 2.25, "surface": "plain",
        "principles": "Control-room clarity: slate + amber signal palette, square "
                      "everything, status color discipline.",
    },
    "analytics": {
        "keywords": ["analytics", "dashboard", "metrics", "report", "bi", "insight",
                     "data", "kpi", "chart", "statistics", "monitor"],
        "hues": [(218, 242), (182, 202), (262, 278)],
        "sat": (0.50, 0.68), "light": (0.38, 0.46),
        "neutral": "cool",
        "pairings": ["schibsted-signal", "inter-precision", "geist-clean", "sora-tech"],
        "radius": ["sharp", "soft"], "elevation": ["bordered"],
        "density": ["compact"], "motion": "subtle", "scaleMode": "compact",
        "rail": ["dark"], "frames": ["sidebar"], "iconStroke": 1.75, "surface": "plain",
        "modes": ["light", "dark"],
        "principles": "The data is the hero: quiet chrome, electric-blue accents "
                      "reserved for signal, tabular numerals, dense grids.",
    },
    "fitness": {
        "keywords": ["fitness", "workout", "gym", "exercise", "training", "strength",
                     "run", "cycling", "yoga", "nutrition", "athlete", "sport", "coach",
                     "muscle", "rep", "set", "cardio", "wellness tracker"],
        "hues": [(96, 112), (150, 165), (24, 38)],
        "sat": (0.62, 0.85), "light": (0.44, 0.54),
        "neutral": "cool-graphite",
        "pairings": ["space-grotesk-terminal", "sora-tech", "archivo-industrial", "bricolage-bold"],
        "radius": ["sharp", "soft"], "elevation": ["flat", "bordered"],
        "density": ["compact"], "motion": "expressive", "scaleMode": "display",
        "rail": ["dark"], "surface": "plain",
        "frames": ["sidebar", "topbar"], "iconStroke": 2.25,
        "mode": "dark",
        "principles": "High-energy athletic: dark charcoal canvas, ONE electric accent "
                      "(neon lime/green) reserved for progress + PRs, technical type, "
                      "compact data-dense logging rows, big numerals.",
    },
    "default-saas": {
        "keywords": [],
        "hues": [(168, 184), (206, 222), (244, 258), (286, 300)],
        "sat": (0.45, 0.62), "light": (0.38, 0.46),
        "neutral": "cool",
        "pairings": ["manrope-humanist", "inter-precision", "sora-tech",
                     "instrument-quiet", "geist-clean"],
        "radius": ["soft", "sharp"], "elevation": ["layered", "bordered"],
        "density": ["comfortable"], "motion": "subtle", "scaleMode": "balanced",
        "rail": ["dark", "light"], "frames": ["sidebar"], "iconStroke": 2.0, "surface": "plain",
        "principles": "Modern professional SaaS: sharp-but-humane, restrained palette, "
                      "confident type, premium without decoration.",
    },
}

# Neutral temperature recipes: hue + saturation used for tinted grays/surfaces.
_NEUTRAL_RECIPES: dict[str, dict] = {
    "warm":          {"hue": 38,  "sat": 0.14, "bg_l": 0.975, "tint_l": 0.955},
    "cool":          {"hue": 218, "sat": 0.10, "bg_l": 0.978, "tint_l": 0.958},
    "cool-graphite": {"hue": 224, "sat": 0.08, "bg_l": 0.972, "tint_l": 0.950},
    "cool-steel":    {"hue": 210, "sat": 0.09, "bg_l": 0.973, "tint_l": 0.952},
    "neutral":       {"hue": 240, "sat": 0.03, "bg_l": 0.977, "tint_l": 0.958},
    "neutral-ink":   {"hue": 250, "sat": 0.04, "bg_l": 0.975, "tint_l": 0.952},
}

_RADIUS_SETS = {
    "sharp": {"sm": "0.125rem", "md": "0.25rem",  "lg": "0.375rem", "xl": "0.5rem",  "full": "9999px"},
    "soft":  {"sm": "0.25rem",  "md": "0.5rem",   "lg": "0.75rem",  "xl": "1rem",    "full": "9999px"},
    "round": {"sm": "0.5rem",   "md": "0.75rem",  "lg": "1rem",     "xl": "1.5rem",  "full": "9999px"},
}

_TYPE_SCALES = {  # ratio-derived rem scales (body baseline 0.875rem/14px)
    "compact":  {"h1": "1.5rem",   "h2": "1.25rem",  "h3": "1rem",      "body": "0.875rem", "caption": "0.75rem"},
    "balanced": {"h1": "1.875rem", "h2": "1.5rem",   "h3": "1.125rem",  "body": "0.875rem", "caption": "0.75rem"},
    "display":  {"h1": "2.25rem",  "h2": "1.625rem", "h3": "1.1875rem", "body": "0.9375rem", "caption": "0.75rem"},
}

_MOTION = {
    "none":       {"fast": "0ms",   "normal": "0ms",   "easing": "linear"},
    "subtle":     {"fast": "150ms", "normal": "250ms", "easing": "cubic-bezier(0.4, 0, 0.2, 1)"},
    "expressive": {"fast": "180ms", "normal": "320ms", "easing": "cubic-bezier(0.34, 1.3, 0.64, 1)"},
}


# ---------------------------------------------------------------------------
# Seeded selection
# ---------------------------------------------------------------------------

def _seed_bytes(*parts: str) -> bytes:
    return hashlib.sha256("::".join(p or "" for p in parts).encode("utf-8")).digest()


def _pick(seq, seed: bytes, salt: int):
    """Deterministic choice from a sequence using one byte of the seed."""
    if not seq:
        raise ValueError("empty choice sequence")
    return seq[seed[salt % len(seed)] % len(seq)]


def _lerp_band(band: tuple[float, float], seed: bytes, salt: int) -> float:
    lo, hi = band
    t = seed[salt % len(seed)] / 255.0
    return lo + (hi - lo) * t


def match_archetype(domain: str | None, context: str | None = None) -> str:
    """Score archetypes by keyword hits over the domain + context text."""
    hay = f"{domain or ''} {context or ''}".lower()
    best, best_score = "default-saas", 0
    for name, arch in ARCHETYPES.items():
        # PREFIX-boundary matching: the keyword must start a word, but may
        # continue into one. Bare substring scoring mis-binned domains
        # ("blog"/"catalog" -> developer via "log"); full word-boundary
        # matching over-corrected and broke compounds and plurals
        # ("healthcare" no longer matched "health", so a doctor-appointment
        # app fell through to default-saas). Prefix-boundary keeps
        # health->healthcare and patient->patients while still rejecting
        # blog/catalog/chrome.
        score = sum(1 for kw in arch["keywords"]
                    if re.search(rf"\b{re.escape(kw)}", hay))
        if score > best_score:
            best, best_score = name, score
    return best


# ---------------------------------------------------------------------------
# DNA derivation
# ---------------------------------------------------------------------------


# --- Discovery-dossier ingestion -------------------------------------------
# The pipeline's discovery step already researches the domain's real visual
# language ("dark charcoal + electric neon-green, technical type, compact").
# Ignoring it was the single biggest miss: the right answer was already known.

_PALETTE_WORD_HUES = {
    "neon": (96, 112), "lime": (78, 98), "green": (140, 160), "emerald": (150, 165),
    "teal": (168, 184), "cyan": (185, 195), "blue": (208, 224), "navy": (215, 232),
    "indigo": (240, 255), "violet": (262, 278), "purple": (270, 288), "magenta": (300, 318),
    "pink": (330, 345), "rose": (345, 358), "red": (0, 10), "crimson": (348, 358),
    "orange": (20, 34), "amber": (36, 46), "gold": (40, 50), "yellow": (48, 56),
    "terracotta": (14, 24), "rust": (12, 22), "brown": (24, 34), "earth": (28, 40),
    "sage": (95, 115), "olive": (70, 90), "forest": (140, 155), "mint": (150, 168),
    "charcoal": (215, 235), "slate": (210, 225), "graphite": (220, 240),
}

def _dossier_signals(dossier: dict | None) -> dict:
    """Extract hard design signals from the discovery dossier's visualLanguage."""
    out: dict = {}
    if not isinstance(dossier, dict):
        return out
    vl = dossier.get("visualLanguage")
    if not isinstance(vl, dict):
        return out
    palette = str(vl.get("paletteCharacter") or "").lower()
    typo = str(vl.get("typographyTone") or "").lower()
    density = str(vl.get("densityPreference") or "").lower()

    # Dark-mode intent stated in plain language.
    if any(w in palette for w in ("dark", "charcoal", "midnight", "black", "noir")):
        out["mode"] = "dark"
    elif any(w in palette for w in ("light", "airy", "bright", "white", "paper")):
        out["mode"] = "light"

    # Hue family from named colors (first match wins — the dossier leads with it).
    for word, band in _PALETTE_WORD_HUES.items():
        if word in palette:
            out["hue_band"] = band
            break

    # Saturation intent.
    if any(w in palette for w in ("electric", "neon", "vivid", "bold", "high-energy", "vibrant")):
        out["sat_boost"] = 0.18
    elif any(w in palette for w in ("muted", "soft", "subtle", "pastel", "understated", "neutral")):
        out["sat_boost"] = -0.12

    # Density is a direct token.
    for d in ("compact", "comfortable", "spacious"):
        if d in density:
            out["density"] = d
            break

    # Typography tone → preferred pairing families.
    if any(w in typo for w in ("technical", "mono", "engineer")):
        out["pairing_hint"] = ["space-grotesk-terminal", "geist-clean", "inter-precision"]
    elif any(w in typo for w in ("editorial", "serif", "classic", "traditional")):
        out["pairing_hint"] = ["fraunces-editorial", "newsreader-counsel", "lora-hospitality"]
    elif any(w in typo for w in ("friendly", "rounded", "playful", "approachable")):
        out["pairing_hint"] = ["nunito-round", "gabarito-fresh", "jakarta-warm"]
    elif any(w in typo for w in ("corporate", "professional", "institutional")):
        out["pairing_hint"] = ["plex-institutional", "inter-precision", "manrope-humanist"]
    elif any(w in typo for w in ("bold", "expressive", "characterful", "distinct")):
        out["pairing_hint"] = ["bricolage-bold", "sora-tech", "archivo-industrial"]

    # Explicit hex anchors always win.
    anchors = vl.get("colorAnchors")
    if isinstance(anchors, dict):
        for key in ("primary", "brand", "accent"):
            v = anchors.get(key)
            if isinstance(v, str) and re.match(r"^#?[0-9a-fA-F]{6}$", v.strip()):
                out["anchor"] = v.strip() if v.strip().startswith("#") else "#" + v.strip()
                break
    return out


# Per-archetype auth-screen voice. The form previously said "Welcome back /
# Sign in to {app}" verbatim in EVERY app — the fastest same-generator tell a
# user can hit. Two seeded options per archetype; {app} is substituted by the
# runtime injector.
AUTH_COPY: dict[str, list[dict]] = {
    "fintech":       [{"title": "Sign in to {app}", "sub": "Your books are waiting."},
                      {"title": "Welcome back", "sub": "Secure access to {app}."}],
    "healthcare":    [{"title": "Welcome back", "sub": "Care starts with a sign-in."},
                      {"title": "Sign in", "sub": "Your patients, your schedule — all in {app}."}],
    "consumer-warm": [{"title": "Good to see you!", "sub": "Pick up right where you left off."},
                      {"title": "Welcome back", "sub": "Everything at {app} missed you."}],
    "legal":         [{"title": "Counsel, welcome back", "sub": "Your matters are in order."},
                      {"title": "Sign in to {app}", "sub": "Privileged access. Your practice awaits."}],
    "creative":      [{"title": "Back to work?", "sub": "The canvas is where you left it."},
                      {"title": "Hey, you", "sub": "Let's make something today."}],
    "developer":     [{"title": "Authenticate", "sub": "Session required for {app}."},
                      {"title": "Welcome back", "sub": "Your stack is running fine without you. Mostly."}],
    "logistics":     [{"title": "Clock in", "sub": "Fleet status on the other side."},
                      {"title": "Sign in to {app}", "sub": "Shipments do not track themselves."}],
    "education":     [{"title": "Welcome back!", "sub": "Ready to pick up where you left off?"},
                      {"title": "Sign in", "sub": "Your classroom is waiting."}],
    "hospitality":   [{"title": "Welcome back", "sub": "Your guests are in good hands."},
                      {"title": "Sign in to {app}", "sub": "Tonight's bookings are ready for you."}],
    "hr-people":     [{"title": "Welcome back", "sub": "Your team is glad you are here."},
                      {"title": "Sign in", "sub": "People first — starting with you."}],
    "commerce":      [{"title": "Welcome back", "sub": "Orders came in while you were away."},
                      {"title": "Sign in to {app}", "sub": "Your storefront is live."}],
    "industrial":    [{"title": "Operator sign-in", "sub": "Systems nominal. Authenticate to proceed."},
                      {"title": "Sign in to {app}", "sub": "The floor reports are in."}],
    "analytics":     [{"title": "Welcome back", "sub": "The numbers moved while you were out."},
                      {"title": "Sign in", "sub": "Your dashboards are refreshed and ready."}],
    "fitness":       [{"title": "Ready to train?", "sub": "Your streak is on the line."},
                      {"title": "Back at it", "sub": "The bar does not lift itself."}],
    "default-saas":  [{"title": "Welcome back", "sub": "Sign in to {app} to continue."},
                      {"title": "Sign in", "sub": "Good to have you back at {app}."}],
}

# Per-app action verb voice — kills the identical "New X / View details"
# formula on every collection page of every app.
_VOICE_CREATE = ("New", "Add", "Create")
_VOICE_VIEW = ("View details", "Open", "View")


# Per-archetype brand-name fragments. The pipeline had NO product-name step —
# every app shipped literally named after its vertical ("Legaltech",
# "Fitness"), the single loudest generated-app tell. Seeded composition gives
# each project a plausible product identity with zero LLM. A user-supplied
# appName always wins over this.
_BRAND_FRAGMENTS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "fintech":       (("Ledger", "Vault", "Tally", "Numera", "Apex", "Clearline"),
                      ("Books", "Pay", "Desk", "Metric", "HQ", "Flow")),
    "healthcare":    (("Vital", "Mend", "Luma", "Pulse", "Haven", "Cura"),
                      ("Chart", "Path", "Well", "Desk", "Loop", "Care")),
    "consumer-warm": (("Cozy", "Bloom", "Nest", "Willow", "Amber", "Fable"),
                      ("Care", "Club", "Box", "Loop", "Nook", "Kin")),
    "legal":         (("Lex", "Brief", "Docket", "Counsel", "Verdict", "Clause"),
                      ("Flow", "Desk", "Ward", "Craft", "Point", "Works")),
    "creative":      (("Studio", "Canvas", "Muse", "Prism", "Atelier", "Frame"),
                      ("Lab", "Works", "Deck", "Flow", "Field", "Press")),
    "developer":     (("Deploy", "Stack", "Branch", "Kernel", "Pipe", "Hex"),
                      ("Hub", "Ops", "Base", "Kit", "Forge", "Rail")),
    "logistics":     (("Fleet", "Cargo", "Route", "Haul", "Depot", "Lane"),
                      ("Line", "Grid", "Ops", "Track", "Base", "Port")),
    "education":     (("Learn", "Scholar", "Mentor", "Bright", "Campus", "Lumen"),
                      ("Path", "Nest", "Desk", "Loop", "Hub", "Craft")),
    "hospitality":   (("Suite", "Haven", "Villa", "Solstice", "Harbor", "Fern"),
                      ("Stay", "Desk", "Book", "Host", "Key", "House")),
    "hr-people":     (("Team", "Talent", "Crew", "Thrive", "Kindred", "Anchor"),
                      ("Base", "Loop", "Desk", "Path", "Works", "HQ")),
    "commerce":      (("Merch", "Stock", "Market", "Storefront", "Basket", "Vend"),
                      ("Line", "Hub", "Desk", "Pilot", "Post", "Works")),
    "industrial":    (("Plant", "Forge", "Grid", "Machina", "Steel", "Turbine"),
                      ("Ops", "Watch", "Line", "Core", "Works", "Guard")),
    "analytics":     (("Metric", "Insight", "Signal", "Quant", "Datum", "Scope"),
                      ("Deck", "Lab", "Board", "IQ", "Lens", "Grid")),
    "fitness":       (("Iron", "Rep", "Forge", "Stride", "Grit", "Tempo"),
                      ("Log", "Lab", "Peak", "Zone", "Set", "Club")),
    "default-saas":  (("Nova", "Atlas", "Orbit", "Vertex", "Northstar", "Keel"),
                      ("Desk", "Base", "Flow", "Hub", "Works", "Deck")),
}


def brand_name(archetype: str, seed: bytes) -> str:
    """A seeded two-fragment product name (e.g. LexFlow, IronLog, VitalChart)."""
    pre_pool, suf_pool = _BRAND_FRAGMENTS.get(archetype, _BRAND_FRAGMENTS["default-saas"])
    pre = _pick(pre_pool, seed, 23)
    suf = _pick(suf_pool, seed, 24)
    if suf.lower() in pre.lower() or pre.lower() in suf.lower():
        suf = suf_pool[(suf_pool.index(suf) + 1) % len(suf_pool)]
    return f"{pre}{suf}"


def _archetype_mode(arch: dict, seed: bytes) -> str:
    """Light or dark canvas.

    An archetype may fix it ("mode": "dark") or offer a seeded choice
    ("modes": ["light", "dark"]) so two same-domain apps can diverge on the
    single most visible identity axis. Default stays light.
    """
    if arch.get("mode") == "dark":
        return "dark"
    modes = arch.get("modes")
    if modes:
        return _pick(list(modes), seed, 19)
    return "light"


def derive_design_dna(
    *,
    project_id: str,
    domain: str | None = None,
    context: str | None = None,
    dossier: dict | None = None,
    brief: object | None = None,
) -> dict:
    """Derive the complete design identity for a project.

    Deterministic in (project_id, domain, context, brief-tone). Returns a
    dict with every decision made concrete (hex colors, font stacks, rem
    values) plus the archetype's design principles for prompt injection.

    ``brief`` is optional — when supplied and it reads warm/calm/soft
    (via ``services.aesthetic_profile_picker._brief_stance_words``), the
    composed language vetoes brutalist moves (hard-offset shadows,
    grid-paper / dot-grid / crosshatch grounds, JetBrains-Mono headings,
    3px chunky borders). When absent, the composer behaves exactly as
    before — backward compatible for tests + old callers.
    """
    archetype_name = match_archetype(domain, context)
    arch = ARCHETYPES[archetype_name]
    seed = _seed_bytes(project_id, domain or "", archetype_name)

    # --- typography -------------------------------------------------------
    pairing_id = _pick(arch["pairings"], seed, 0)
    # The dossier's researched typography tone overrides the archetype default
    # when it names a family the bank carries.
    _sig_pre = _dossier_signals(dossier)
    _hint = [p for p in (_sig_pre.get("pairing_hint") or []) if p in FONT_PAIRINGS]
    if _hint:
        pairing_id = _pick(_hint, seed, 16)
    pairing = FONT_PAIRINGS[pairing_id]

    # --- color ------------------------------------------------------------
    # The discovery dossier's researched visual language OVERRIDES archetype
    # defaults — it studied this exact product's real-world aesthetic.
    sig = _dossier_signals(dossier)
    hue_band = sig.get("hue_band") or _pick(arch["hues"], seed, 1)
    hue = _lerp_band(hue_band, seed, 2)
    sat = _lerp_band(arch["sat"], seed, 3) + float(sig.get("sat_boost", 0.0))
    sat = max(0.10, min(0.92, sat))
    light = _lerp_band(arch["light"], seed, 4)
    if sig.get("anchor"):
        try:
            hue, sat, light = _hex_to_hsl(sig["anchor"])
        except ValueError:
            pass
    # Warm hues (amber→orange) turn muddy-olive when darkened for contrast;
    # keep them rich instead: high saturation, capped lightness.
    if 25 <= (hue % 360) <= 60:
        sat = max(sat, 0.60)
        light = min(light, 0.44)
    # The contrast that matters for a FILLED control is its white label:
    # darken the primary until white-on-primary ≥ 4.0 (AA-large / semibold UI
    # text). Text-on-white usages go through the ramp's darker stops anyway.
    primary = _hsl_to_hex(hue, sat, light)
    for _ in range(30):
        if contrast_ratio("#ffffff", primary) >= 4.0:
            break
        h_, s_, l_ = _hex_to_hsl(primary)
        primary = _hsl_to_hex(h_, s_, max(0.02, l_ - 0.02))

    # Secondary: softened analogous (+24°); accent: contrast pop.
    secondary = _hsl_to_hex(hue + 24, max(0.12, sat * 0.45), min(0.88, light + 0.42))
    accent_hue = (hue + _pick([150, 165, 180, 195, 210], seed, 5)) % 360
    accent = ensure_contrast(_hsl_to_hex(accent_hue, min(0.75, sat + 0.08), light + 0.04),
                             "#ffffff", 3.0)

    # Neutrals: temperature recipe tinted toward the archetype's register.
    ntr = _NEUTRAL_RECIPES[arch["neutral"]]
    n_hue, n_sat = ntr["hue"], ntr["sat"]
    surface_treatment = arch["surface"]
    # LIGHT vs DARK canvas — dossier intent wins, else the archetype's stance.
    mode = sig.get("mode") or _archetype_mode(arch, seed)

    if mode == "dark":
        # Dark canvas: near-black tinted toward the neutral hue, elevated
        # surfaces LIGHTER than the page (depth by luminance, not shadow),
        # and a bright accent that pops against it. Contrast is enforced the
        # other direction (light text on dark).
        background = _hsl_to_hex(n_hue, min(0.20, n_sat + 0.10), 0.075)
        surface = _hsl_to_hex(n_hue, min(0.18, n_sat + 0.08), 0.115)
        surface_hover = _hsl_to_hex(n_hue, min(0.18, n_sat + 0.08), 0.155)
        border = _hsl_to_hex(n_hue, min(0.16, n_sat + 0.06), 0.22)
        muted = _hsl_to_hex(n_hue, 0.10, 0.52)
        text_primary = _hsl_to_hex(n_hue, 0.08, 0.96)
        text_secondary = _hsl_to_hex(n_hue, 0.07, 0.72)
        text_tertiary = _hsl_to_hex(n_hue, 0.06, 0.55)
        # On dark, the brand must be BRIGHT — lighten until it reads on the canvas.
        primary = ensure_contrast(_hsl_to_hex(hue, min(0.95, sat + 0.10), max(light, 0.55)),
                                  background, 4.5, darken=False)
        accent = ensure_contrast(_hsl_to_hex(accent_hue, min(0.95, sat + 0.12), 0.62),
                                 background, 4.5, darken=False)
        secondary = _hsl_to_hex(hue + 24, min(0.30, sat * 0.4), 0.24)
    else:
        background = _hsl_to_hex(n_hue, n_sat, ntr["tint_l" if surface_treatment == "tinted" else "bg_l"])
        surface = "#ffffff"
        surface_hover = _hsl_to_hex(n_hue, n_sat, 0.965)
        border = _hsl_to_hex(n_hue, min(0.22, n_sat + 0.06), 0.885)
        muted = _hsl_to_hex(n_hue, min(0.14, n_sat + 0.02), 0.58)
        text_primary = _hsl_to_hex(n_hue, min(0.30, n_sat + 0.12), 0.13)
        text_secondary = _hsl_to_hex(n_hue, min(0.16, n_sat + 0.04), 0.36)
        text_tertiary = _hsl_to_hex(n_hue, min(0.12, n_sat + 0.02), 0.56)

    # Semantic status colors, harmonized to the palette's saturation register
    # and to the CANVAS (on dark they must be light enough to read).
    sem_sat = max(0.45, min(0.62, sat))
    _dark = mode == "dark"
    _canvas = background if _dark else "#ffffff"
    _up = _dark  # lighten on dark, darken on light

    def _status(h: float, s: float, l: float, minimum: float = 4.5) -> str:
        return ensure_contrast(_hsl_to_hex(h, s, 0.58 if _dark else l), _canvas,
                               minimum, darken=not _up)

    success = _status(145, sem_sat, 0.34)
    warning = _status(38, min(0.80, sem_sat + 0.18), 0.42, 3.0)
    error = _status(2, min(0.72, sem_sat + 0.10), 0.44)
    info = _status(212, sem_sat, 0.42)

    # --- shell frame + icon voice ----------------------------------------
    # Structure varies too, not just paint: archetypes that suit a horizontal
    # header can get a TOPBAR app frame instead of the sidebar rail.
    frame = _pick(arch.get("frames", ["sidebar"]), seed, 10)
    # Icon stroke weight is a quiet but powerful voice: thin = elegant
    # editorial, regular = neutral SaaS, bold = friendly/industrial.
    # Seeded jitter so two same-domain apps do not share the exact stroke.
    icon_stroke = round(min(2.5, max(1.25,
        arch.get("iconStroke", 2.0) + _pick([-0.25, 0.0, 0.25], seed, 17))), 2)

    rail = "dark" if _dark else _pick(arch["rail"], seed, 6)
    if rail == "dark":
        # On a dark canvas the rail must differ from the page, not match it —
        # slightly deeper than the page so the content plane reads as elevated.
        sidebar_bg = _hsl_to_hex(n_hue, min(0.32, n_sat + 0.16), 0.045 if _dark else 0.11)
        sidebar_text = _hsl_to_hex(n_hue, 0.10, 0.78)
        sidebar_active = _hsl_to_hex(hue, min(0.5, sat), 0.22)
    elif rail == "brand":
        sidebar_bg = ensure_contrast(_hsl_to_hex(hue, min(0.62, sat + 0.06), 0.16), "#ffffff", 7.0, darken=True)
        sidebar_text = _hsl_to_hex(hue, 0.18, 0.86)
        sidebar_active = _hsl_to_hex(hue, min(0.55, sat), 0.28)
    elif rail == "tinted":
        sidebar_bg = _hsl_to_hex(n_hue, min(0.20, n_sat + 0.06), 0.945)
        sidebar_text = text_secondary
        sidebar_active = _hsl_to_hex(hue, 0.30, 0.90)
    else:  # light
        sidebar_bg = "#ffffff"
        sidebar_text = text_secondary
        sidebar_active = _hsl_to_hex(hue, 0.32, 0.93)

    # --- COMPOSITION: what each page is actually MADE OF -------------------
    # This is the layer that makes two apps different *products* rather than
    # the same product repainted. Each choice is seeded (so same project =
    # same design) but drawn from the archetype's tasteful subset.
    recipe = LAYOUT_RECIPES.get(archetype_name, LAYOUT_RECIPES["default-saas"])
    layout = {
        "auth": _pick(recipe["auth"], seed, 11),
        "dashboard": _pick(recipe["dashboard"], seed, 12),
        "list": _pick(recipe["list"], seed, 13),
        "detail": _pick(recipe["detail"], seed, 14),
        "chrome": _pick(recipe["chrome"], seed, 15),  # overridden below by the language
        "form": _pick(recipe.get("form", ("two-column", "single-column")), seed, 18),
    }

    # --- shape / depth / rhythm ------------------------------------------
    radius_scale = _pick(arch["radius"], seed, 7)
    elevation = _pick(arch["elevation"], seed, 8)
    density = sig.get("density") or _pick(arch["density"], seed, 9)
    motion_level = arch["motion"]
    scale_mode = arch["scaleMode"]

    # Compose this app's visual language before the return dict — several
    # keys below read it. The composer honours ``brief`` (when supplied) so
    # a warm/calm/soft brief can never draw brutalist picks (grid-paper,
    # hard-offset, mono headings). See ``services.design_language`` for
    # the veto details.
    _lang = _compose(archetype_name, seed, brief=brief)

    # Slice A (2026-08-13) — VisualLock override.
    # An active lock is an explicit commitment; downstream reads DNA
    # colours in places outside brief_to_design_spec's reach (auth
    # emitters, skin CSS scopes). Snap DNA colours to the lock now so
    # everything downstream sees one truth. Typography families are also
    # snapped so the DNA-driven pairing hint can never fight the lock.
    _lock = getattr(brief, "visual_lock", None) if brief is not None else None
    _lock_typography_override: dict | None = None
    try:
        if _lock is not None and _lock.is_active():
            lp = _lock.palette
            # Typography — build a shim pairing that echoes the lock's
            # display/body/mono families. Keeps weights + letterspacing
            # from the seeded pairing (so hints don't disappear) and only
            # swaps the family strings.
            _lt = _lock.typography
            if _lt:
                _pairing_snap = dict(pairing)  # shallow copy
                if _lt.get("display"):
                    _pairing_snap["heading"] = f"'{_lt['display']}', system-ui, sans-serif"
                if _lt.get("body"):
                    _pairing_snap["body"] = f"'{_lt['body']}', system-ui, sans-serif"
                if _lt.get("mono"):
                    _pairing_snap["numeric"] = f"'{_lt['mono']}', monospace"
                # Rebuild googleImports so the app actually fetches the
                # lock's families rather than the seeded pairing's.
                _imports: list[str] = []
                if _lt.get("display"):
                    _imports.append(f"{_lt['display'].replace(' ', '+')}:wght@400;500;700")
                if _lt.get("body") and _lt.get("body") != _lt.get("display"):
                    _imports.append(f"{_lt['body'].replace(' ', '+')}:wght@400;500;600")
                if _lt.get("mono"):
                    _imports.append(f"{_lt['mono'].replace(' ', '+')}:wght@400;500")
                if _imports:
                    _pairing_snap["import"] = _imports
                _lock_typography_override = _pairing_snap
            # Colours: prefer lock hex for each slot.
            if lp.get("bg"):      background = lp["bg"]
            if lp.get("subtle"):
                surface = lp["subtle"]
                surface_hover = lp["subtle"]
            if lp.get("fg"):
                text_primary = lp["fg"]
                text_secondary = lp.get("muted") or text_secondary
            if lp.get("muted"):
                muted = lp["muted"]
                text_tertiary = lp["muted"]
            if lp.get("accent"):
                primary = lp["accent"]
                sidebar_active = lp["accent"]
            if lp.get("badge"):
                accent = lp["badge"]
            if lp.get("danger"):
                error = lp["danger"]
            if lp.get("success"):
                success = lp["success"]
            # Border stays a neutral hairline; snap to the muted colour
            # so it reads as a warm hairline on wellness / dark hairline
            # on creative, not a stock slate line.
            if lp.get("muted"):
                border = lp["muted"]
    except Exception:  # noqa: BLE001 — malformed lock never breaks DNA derivation
        pass

    # Apply typography override AFTER the color block so the shim pairing
    # is the one the return-dict reads.
    if _lock_typography_override is not None:
        pairing = _lock_typography_override

    shadow_alpha = {"flat": 0.0, "bordered": 0.04, "layered": 0.08, "floating": 0.14}[elevation]
    sh = f"{round(shadow_alpha, 2)}"
    shadows = {
        "sm": f"0 1px 2px 0 rgb(15 18 20 / {sh})" if shadow_alpha else "none",
        "md": f"0 4px 10px -2px rgb(15 18 20 / {sh})" if shadow_alpha else "none",
        "lg": f"0 12px 24px -6px rgb(15 18 20 / {round(min(0.2, shadow_alpha + 0.04), 2)})" if shadow_alpha else "none",
        "xl": f"0 24px 48px -12px rgb(15 18 20 / {round(min(0.26, shadow_alpha + 0.08), 2)})" if shadow_alpha else "none",
    }

    return {
        "version": 1,
        "archetype": archetype_name,
        "principles": arch["principles"],
        "seed": seed[:8].hex(),
        "typography": {
            "pairing": pairing_id,
            "heading": pairing["heading"],
            "headingWeight": pairing["headingWeight"],
            "body": pairing["body"],
            "bodyWeight": pairing["bodyWeight"],
            "numeric": pairing.get("numeric", pairing["body"]),
            "tabularNumbers": pairing["tabularNumbers"],
            "letterSpacing": pairing["letterSpacing"],
            "googleImports": pairing["import"],
            "scaleMode": scale_mode,
            "scale": dict(_TYPE_SCALES[scale_mode]),
        },
        "color": {
            "primary": primary, "secondary": secondary, "accent": accent,
            "background": background, "surface": surface, "surfaceHover": surface_hover,
            "border": border, "muted": muted,
            "textPrimary": text_primary, "textSecondary": text_secondary,
            "textTertiary": text_tertiary,
            "success": success, "warning": warning, "error": error, "info": info,
            "sidebarBg": sidebar_bg, "sidebarText": sidebar_text,
            "sidebarActive": sidebar_active,
            "neutralTemperature": arch["neutral"],
        },
        "shape": {
            "radiusScale": radius_scale,
            "radius": dict(_RADIUS_SETS[radius_scale]),
            "elevation": elevation,
            "shadows": shadows,
        },
        "rhythm": {"density": density, "motionLevel": motion_level,
                   "motion": dict(_MOTION[motion_level])},
        "shell": {"rail": rail, "frame": frame,
                  "surfaceTreatment": surface_treatment,
                  "chrome": _lang["chrome"]},
        "icon": {"stroke": icon_stroke},
        # COMPOSITION — consumed by the auth-page emitter and the deterministic
        # page builders so structure (not just paint) differs per app.
        "layout": {**layout, "chrome": _lang["chrome"]},
        "mode": mode,
        # LANGUAGE — composed per app from independent axes (nav shape,
        # active mark, page header, KPI anatomy, card treatment, radius,
        # type class, density) under a taste model. A fixed skin list caps
        # out at ~10 looks; the composer keeps producing coherent, distinct
        # languages indefinitely. `skin` is its stable scope key.
        "language": _lang,
        "skin": _lang["skinKey"],
        "register": _lang["register"],
        # BRAND — a seeded product name for apps whose plan carries none
        # (most plans name the app after its vertical, e.g. "legaltech").
        "brand": {"name": brand_name(archetype_name, seed)},
        # VOICE — per-app microcopy so no two apps share the same tics.
        "authCopy": dict(_pick(AUTH_COPY.get(archetype_name, AUTH_COPY["default-saas"]),
                               seed, 20)),
        "voice": {"create": _pick(_VOICE_CREATE, seed, 21),
                  "view": _pick(_VOICE_VIEW, seed, 22)},
    }


# ---------------------------------------------------------------------------
# Consumers
# ---------------------------------------------------------------------------

def to_design_spec(dna: dict) -> dict:
    """A complete, machine-valid design-spec in the pipeline's expected shape.

    Used as the deterministic fallback when the design agent produced nothing
    usable, and as the merge-base underneath the agent's spec (agent values win
    where valid; DNA fills every gap).
    """
    c, t, s, r = dna["color"], dna["typography"], dna["shape"], dna["rhythm"]
    return {
        "designDnaVersion": dna["version"],
        "archetype": dna["archetype"],
        # The component-variant set (EngineProvider reads spec.register) and
        # the design-language skin that chose it.
        "register": dna.get("register", "default"),
        "skin": dna.get("skin", "inkwell"),
        "colorPalette": {
            "primary": c["primary"], "secondary": c["secondary"], "accent": c["accent"],
            "background": c["background"], "surface": c["surface"],
            "surfaceHover": c["surfaceHover"], "border": c["border"], "muted": c["muted"],
            "textPrimary": c["textPrimary"], "textSecondary": c["textSecondary"],
            "textTertiary": c["textTertiary"],
            "success": c["success"], "warning": c["warning"],
            "error": c["error"], "info": c["info"],
            "sidebarBg": c["sidebarBg"], "sidebarText": c["sidebarText"],
            "sidebarActiveItem": c["sidebarActive"],
        },
        "typography": {
            "fontFamily": t["body"],
            "headingFontFamily": t["heading"],
            "bodyWeight": t["bodyWeight"],
            "headingWeight": t["headingWeight"],
            "letterSpacing": t["letterSpacing"],
            "scale": dict(t["scale"]),
            "googleFontImports": list(t["googleImports"]),
            "tabularNumbers": t["tabularNumbers"],
        },
        "spacing": {},  # numeric scale is derived from density by the compiler
        "borderRadius": {**s["radius"], "scale": s["radiusScale"]},
        "radiusScale": s["radiusScale"],
        "shadows": dict(s["shadows"]),
        "animation": {
            "duration": f"{r['motion']['fast']} fast, {r['motion']['normal']} normal",
            "easing": r["motion"]["easing"],
        },
        "layout": {"navigation": dna["shell"].get("frame", "sidebar"),
                   "density": r["density"],
                   # COMPOSITION — read by deterministic_pages to vary the
                   # dashboard/list/detail SHAPE per app (not just its paint).
                   "dashboard": dna.get("layout", {}).get("dashboard", "stat-grid"),
                   "list": dna.get("layout", {}).get("list", "table"),
                   "detail": dna.get("layout", {}).get("detail", "tabbed-hero"),
                   "auth": dna.get("layout", {}).get("auth", "split-editorial"),
                   "chrome": dna.get("layout", {}).get("chrome", "standard-rail"),
                   "form": dna.get("layout", {}).get("form", "two-column")},
        # VOICE — per-app action-verb microcopy for the deterministic builders.
        "voice": dict(dna.get("voice") or {}),
        "iconStroke": dna.get("icon", {}).get("stroke", 2.0),
        "elevation": s["elevation"],
        "motionLevel": r["motionLevel"],
        "scaleMode": t["scaleMode"],
    }


def _fg_for(fill_hex: str) -> str:
    """Label color for a FILLED control: white when it reads, else near-black.

    Light-mode primaries are darkened until white-on-primary >= 4.0, so they
    keep white labels. Dark-mode primaries are BRIGHTENED for canvas contrast
    (neon lime, electric cyan) — a hardcoded white label on those is
    unreadable; they need ink.
    """
    return "0 0% 100%" if contrast_ratio("#ffffff", fill_hex) >= 3.5 else "224 30% 8%"


def to_css_variables(dna: dict) -> dict[str, str]:
    """The shadcn-style HSL variable map for globals.css (light theme)."""
    c = dna["color"]
    return {
        "--background": _hsl_triplet(c["background"]),
        "--foreground": _hsl_triplet(c["textPrimary"]),
        "--card": _hsl_triplet(c["surface"]),
        "--card-foreground": _hsl_triplet(c["textPrimary"]),
        "--primary": _hsl_triplet(c["primary"]),
        "--primary-foreground": _fg_for(c["primary"]),
        "--secondary": _hsl_triplet(c["secondary"]),
        "--secondary-foreground": _hsl_triplet(c["textPrimary"]),
        "--accent": _hsl_triplet(c["accent"]),
        "--accent-foreground": _fg_for(c["accent"]),
        "--muted": _hsl_triplet(c["surfaceHover"]),
        "--muted-foreground": _hsl_triplet(c["textSecondary"]),
        "--border": _hsl_triplet(c["border"]),
        "--input": _hsl_triplet(c["border"]),
        "--ring": _hsl_triplet(c["primary"]),
        "--destructive": _hsl_triplet(c["error"]),
        "--destructive-foreground": _fg_for(c["error"]),
        "--color-success": _hsl_triplet(c["success"]),
        "--color-warning": _hsl_triplet(c["warning"]),
        "--color-info": _hsl_triplet(c["info"]),
        "--sidebar-background": _hsl_triplet(c["sidebarBg"]),
        "--sidebar-foreground": _hsl_triplet(c["sidebarText"]),
        "--sidebar-accent": _hsl_triplet(c["sidebarActive"]),
        "--radius": dna["shape"]["radius"]["md"],
    }


def google_fonts_import(dna: dict) -> str:
    """The @import line loading the DNA's font pairing from Google Fonts."""
    families = "&".join(f"family={f}" for f in dna["typography"]["googleImports"])
    return f"@import url('https://fonts.googleapis.com/css2?{families}&display=swap');"


def prompt_brief(dna: dict) -> str:
    """Compact art-direction brief for the design/shell agent prompts."""
    c, t, s, r = dna["color"], dna["typography"], dna["shape"], dna["rhythm"]
    pairing = FONT_PAIRINGS[t["pairing"]]
    return (
        f"DESIGN DNA (committed identity for THIS app — refine, never replace):\n"
        f"- Archetype: {dna['archetype']} — {dna['principles']}\n"
        f"- Type: headings {t['heading']} w{t['headingWeight']}, body {t['body']} "
        f"w{t['bodyWeight']}, letter-spacing {t['letterSpacing']}"
        f"{', TABULAR numerals for data' if t['tabularNumbers'] else ''} "
        f"({pairing['voice']}). Type scale mode: {t['scaleMode']}.\n"
        f"- Color: primary {c['primary']}, accent {c['accent']}, background "
        f"{c['background']}, borders {c['border']}, ink {c['textPrimary']} "
        f"(neutral temperature: {c['neutralTemperature']}). Status: success "
        f"{c['success']} / warning {c['warning']} / error {c['error']}.\n"
        f"- Shape: {s['radiusScale']} radii (md {s['radius']['md']}), elevation "
        f"style '{s['elevation']}'.\n"
        f"- Rhythm: {r['density']} density, {r['motionLevel']} motion.\n"
        f"- Shell: {dna['shell']['rail']} navigation rail, "
        f"{dna['shell']['surfaceTreatment']} page surface.\n"
        + (
            f"- Composition (this app's committed page shapes): "
            f"dashboard={dna['layout'].get('dashboard')}, "
            f"list={dna['layout'].get('list')}, "
            f"detail={dna['layout'].get('detail')}, "
            f"form={dna['layout'].get('form')}, "
            f"chrome={dna['layout'].get('chrome')}, "
            f"auth={dna['layout'].get('auth')}.\n"
            if dna.get("layout") else ""
        )
        + f"Every value you output MUST be a bare machine-readable CSS value "
        f"(hex, rem, px, ms, font stack). NO prose, NO parentheses, NO "
        f"explanations inside values — a strict validator rejects them."
    )


# ===========================================================================
# COMPOSITION LAYER — the part that makes apps *structurally* different.
#
# Paint (color/type/radius) alone still yields "the same app in a new coat".
# These recipes decide WHAT EACH PAGE IS MADE OF: the auth layout, the
# dashboard's component order, the list pattern, the shell chrome. Two apps
# with different compositions are unmistakably different products.
# ===========================================================================

# --- Auth page layouts (the most-seen screen; was byte-identical everywhere) ---
AUTH_LAYOUTS = (
    "split-editorial",    # 50/50: brand panel with oversized wordmark + form
    "centered-minimal",   # single centered card on a tinted canvas
    "brand-wash",         # full-bleed brand gradient, glass form card
    "side-panel",         # narrow brand strip (38%) + generous form area
    "top-anchored",       # centered logo above a borderless form, lots of air
    "split-reversed",     # form LEFT, brand panel RIGHT (mirrors the norm)
)

# --- Dashboard compositions (component ORDER, not just contents) ---
DASHBOARD_LAYOUTS = (
    "stat-strip",    # thin full-width KPI strip → wide primary chart → table
    "stat-grid",     # 2x2 tile grid + side chart → table
    "hero-led",      # greeting/hero band → tiles → single focus chart
    "feed-led",      # activity feed as the hero, KPIs demoted to a sidebar
    "split-focus",   # 60/40: primary work surface | rail of KPIs + activity
    "board-first",   # kanban/board hero → compact metrics underneath
)

# --- List page patterns ---
LIST_LAYOUTS = ("table", "card-grid", "board", "timeline")
FORM_LAYOUTS = ("single-column", "two-column", "sectioned", "side-summary")

# --- Detail page patterns ---
DETAIL_LAYOUTS = ("tabbed-hero", "split-detail", "profile-detail", "timeline-detail")

# --- Shell chrome ---
SHELL_CHROME = ("standard-rail", "icon-rail", "wide-rail", "topbar", "floating-rail", "right-rail", "dock")

# Per-archetype composition taste. Each archetype draws only from layouts that
# genuinely fit its domain — a law firm gets docket-like tables and editorial
# auth; a fitness app gets board/feed energy and full-bleed auth.
LAYOUT_RECIPES: dict[str, dict] = {
    "fintech":       {"auth": ("split-editorial", "side-panel", "centered-minimal"),
                      "dashboard": ("stat-strip", "stat-grid", "split-focus"),
                      "list": ("table", "timeline"), "detail": ("split-detail", "tabbed-hero"),
                      "form": ("two-column", "sectioned"),
                      "chrome": ("standard-rail", "icon-rail")},
    "healthcare":    {"auth": ("centered-minimal", "side-panel", "top-anchored"),
                      "dashboard": ("hero-led", "stat-grid", "feed-led"),
                      "list": ("table", "card-grid"), "detail": ("profile-detail", "tabbed-hero"),
                      "form": ("sectioned", "single-column"),
                      "chrome": ("standard-rail", "wide-rail")},
    "consumer-warm": {"auth": ("brand-wash", "top-anchored", "split-reversed"),
                      "dashboard": ("hero-led", "feed-led", "stat-grid"),
                      "list": ("card-grid", "timeline"), "detail": ("profile-detail", "tabbed-hero"),
                      "form": ("single-column", "two-column"),
                      "chrome": ("standard-rail", "topbar", "right-rail", "dock")},
    "legal":         {"auth": ("split-editorial", "side-panel"),
                      "dashboard": ("stat-strip", "split-focus", "stat-grid"),
                      "list": ("table", "timeline"), "detail": ("tabbed-hero", "split-detail"),
                      "form": ("sectioned", "single-column"),
                      "chrome": ("standard-rail", "wide-rail")},
    "creative":      {"auth": ("brand-wash", "split-reversed", "top-anchored"),
                      "dashboard": ("board-first", "feed-led", "hero-led"),
                      "list": ("card-grid", "board"), "detail": ("tabbed-hero", "profile-detail"),
                      "form": ("single-column", "side-summary"),
                      "chrome": ("topbar", "floating-rail", "icon-rail", "right-rail")},
    "developer":     {"auth": ("centered-minimal", "split-editorial"),
                      "dashboard": ("split-focus", "feed-led", "board-first"),
                      "list": ("table", "timeline"), "detail": ("split-detail", "timeline-detail"),
                      "form": ("two-column", "single-column"),
                      "chrome": ("icon-rail", "topbar")},
    "logistics":     {"auth": ("side-panel", "centered-minimal"),
                      "dashboard": ("stat-grid", "board-first", "split-focus"),
                      "list": ("table", "board"), "detail": ("split-detail", "timeline-detail"),
                      "form": ("two-column", "sectioned"),
                      "chrome": ("standard-rail", "icon-rail")},
    "education":     {"auth": ("brand-wash", "top-anchored", "centered-minimal"),
                      "dashboard": ("hero-led", "stat-grid", "board-first"),
                      "list": ("card-grid", "table"), "detail": ("tabbed-hero", "profile-detail"),
                      "form": ("single-column", "sectioned"),
                      "chrome": ("standard-rail", "topbar", "dock")},
    "hospitality":   {"auth": ("split-editorial", "brand-wash", "split-reversed"),
                      "dashboard": ("hero-led", "split-focus", "stat-grid"),
                      "list": ("card-grid", "timeline"), "detail": ("profile-detail", "tabbed-hero"),
                      "form": ("side-summary", "single-column"),
                      "chrome": ("wide-rail", "topbar", "right-rail")},
    "hr-people":     {"auth": ("side-panel", "centered-minimal", "brand-wash"),
                      "dashboard": ("feed-led", "hero-led", "stat-grid"),
                      "list": ("card-grid", "table"), "detail": ("profile-detail", "tabbed-hero"),
                      "form": ("sectioned", "two-column"),
                      "chrome": ("standard-rail", "wide-rail")},
    "commerce":      {"auth": ("split-reversed", "brand-wash", "centered-minimal"),
                      "dashboard": ("stat-strip", "stat-grid", "board-first"),
                      "list": ("card-grid", "table"), "detail": ("tabbed-hero", "split-detail"),
                      "form": ("two-column", "side-summary"),
                      "chrome": ("topbar", "standard-rail")},
    "industrial":    {"auth": ("centered-minimal", "side-panel"),
                      "dashboard": ("stat-grid", "split-focus", "stat-strip"),
                      "list": ("table", "board"), "detail": ("split-detail", "timeline-detail"),
                      "form": ("sectioned", "two-column"),
                      "chrome": ("icon-rail", "standard-rail")},
    "analytics":     {"auth": ("centered-minimal", "split-editorial"),
                      "dashboard": ("stat-strip", "split-focus", "stat-grid"),
                      "list": ("table", "timeline"), "detail": ("split-detail", "tabbed-hero"),
                      "form": ("two-column", "single-column"),
                      "chrome": ("icon-rail", "standard-rail")},
    "fitness":       {"auth": ("brand-wash", "split-reversed", "top-anchored"),
                      "dashboard": ("hero-led", "board-first", "feed-led"),
                      "list": ("card-grid", "board", "timeline"), "detail": ("tabbed-hero", "profile-detail"),
                      "form": ("single-column", "two-column"),
                      "chrome": ("topbar", "floating-rail", "standard-rail", "dock")},
    "default-saas":  {"auth": ("split-editorial", "centered-minimal", "side-panel", "brand-wash"),
                      "dashboard": ("stat-grid", "stat-strip", "hero-led", "split-focus"),
                      "list": ("table", "card-grid"), "detail": ("tabbed-hero", "split-detail"),
                      "form": ("two-column", "single-column", "sectioned"),
                      "chrome": ("standard-rail", "icon-rail", "topbar")},
}


# ---------------------------------------------------------------------------
# Personality CSS — the "feel" layer.
#
# Structure (shell/layouts) + paint (palette/type) still leave micro-signals
# that betray a shared generator: identical flat page background, identical
# table rows, identical heading treatment, default selection blue. This block
# emits a small, deterministic, per-app stylesheet for those signals.
# ---------------------------------------------------------------------------

_PERSONALITY: dict[str, dict] = {
    "fintech":       {"texture": "top-wash",   "heading": "none",      "table": "lined"},
    "healthcare":    {"texture": "radial",     "heading": "none",      "table": "airy"},
    "consumer-warm": {"texture": "radial",     "heading": "rounded-bar", "table": "airy"},
    "legal":         {"texture": "grid-paper", "heading": "rule",      "table": "lined"},
    "creative":      {"texture": "flat",       "heading": "accent-bar", "table": "airy"},
    "developer":     {"texture": "flat",       "heading": "none",      "table": "striped"},
    "logistics":     {"texture": "flat",       "heading": "none",      "table": "striped"},
    "education":     {"texture": "radial",     "heading": "rounded-bar", "table": "airy"},
    "hospitality":   {"texture": "top-wash",   "heading": "rule",      "table": "airy"},
    "hr-people":     {"texture": "radial",     "heading": "rounded-bar", "table": "airy"},
    "commerce":      {"texture": "top-wash",   "heading": "accent-bar", "table": "lined"},
    "industrial":    {"texture": "grid-paper", "heading": "none",      "table": "striped"},
    "analytics":     {"texture": "flat",       "heading": "none",      "table": "striped"},
    "fitness":       {"texture": "top-wash",   "heading": "accent-bar", "table": "striped"},
    "default-saas":  {"texture": "top-wash",   "heading": "none",      "table": "lined"},
}


def to_personality_css(dna: dict) -> str:
    """A per-app stylesheet for the micro-signals of identity.

    Deterministic from the DNA; wrapped in tentoro:personality markers so
    re-runs replace rather than duplicate.
    """
    arch = dna.get("archetype", "default-saas")
    p = _PERSONALITY.get(arch, _PERSONALITY["default-saas"])
    c = dna["color"]
    dark = dna.get("mode") == "dark"
    primary, accent = c["primary"], c["accent"]
    ink = c["textPrimary"]
    rules: list[str] = []

    # Page texture — the canvas itself carries the identity.
    if p["texture"] == "top-wash":
        rules.append(
            "body { background-image: linear-gradient(180deg, "
            f"{primary}{'14' if dark else '0d'} 0%, transparent 340px); }}".replace("}}", "}"))
    elif p["texture"] == "radial":
        rules.append(
            "body { background-image: radial-gradient(90% 40% at 50% 0%, "
            f"{accent}{'12' if dark else '0a'}, transparent 70%); }}".replace("}}", "}"))
    elif p["texture"] == "grid-paper":
        line = "rgba(255,255,255,0.030)" if dark else "rgba(0,0,0,0.028)"
        rules.append(
            f"body {{ background-image: linear-gradient({line} 1px, transparent 1px), "
            f"linear-gradient(90deg, {line} 1px, transparent 1px); "
            "background-size: 42px 42px; }")

    # Heading accent — the strongest single 'brand voice' cue on every page.
    if p["heading"] == "accent-bar":
        rules.append(
            "main h1::after { content: \"\"; display: block; width: 2.25rem; "
            f"height: 3px; margin-top: 0.45rem; background: {accent}; }}".replace("}}", "}"))
    elif p["heading"] == "rounded-bar":
        rules.append(
            "main h1::after { content: \"\"; display: block; width: 2.5rem; "
            f"height: 5px; border-radius: 999px; margin-top: 0.5rem; background: {accent}; }}".replace("}}", "}"))
    elif p["heading"] == "rule":
        sep = "rgba(255,255,255,0.14)" if dark else f"{ink}26"
        rules.append(
            "main h1 { padding-bottom: 0.55rem; "
            f"border-bottom: 1px solid {sep}; }}".replace("}}", "}"))

    # Table voice — striped / hairline-lined / airy.
    if p["table"] == "striped":
        stripe = "rgba(255,255,255,0.035)" if dark else "rgba(0,0,0,0.027)"
        rules.append(f"tbody tr:nth-child(even) {{ background: {stripe}; }}")
    elif p["table"] == "lined":
        line = "rgba(255,255,255,0.09)" if dark else "rgba(0,0,0,0.07)"
        rules.append(f"tbody tr {{ border-bottom: 1px solid {line}; }}")
    elif p["table"] == "airy":
        rules.append("tbody tr td { padding-top: 0.8rem; padding-bottom: 0.8rem; }")

    # Hero headlines opt out of the page-title accent — a hero band carries
    # its own presence, and the ::after bar floats oddly on centered text.
    if p["heading"] != "none":
        rules.append("[data-hero-content] h1 { border-bottom: none; padding-bottom: 0; }")
        rules.append("[data-hero-content] h1::after { content: none; }")

    # Text selection + focus — tiny, but no two apps share them now.
    rules.append(f"::selection {{ background: {primary}40; }}")
    rules.append(f":focus-visible {{ outline-color: {accent}; }}")

    body = "\n".join(rules)
    return f"/* tentoro:personality */\n{body}\n/* /tentoro:personality */"


# ===========================================================================
# COMPONENT SKINS — the design-language layer.
#
# Shells, palettes, fonts and page composition varied per app, but every app
# still DREW its components one way: bordered cards, left-accent KPI tiles,
# one button shape. Users read them as one product (verified across four
# real generations). A SKIN is a named, coherent design language — grounded
# in reference research (Mercury, Linear/Vercel, Notion, Ramp, Airtable,
# Retool/neo-brutalism, Stripe/Arc, print-ledger editorial) — that restyles
# HOW components are drawn.
#
# Two channels, both already wired end-to-end:
#   1. the register (component VARIANT set: default|workday|linear|stripe|
#      notion|figma) — swaps Card/MetricTile/Hero DOM per app;
#   2. a per-app stylesheet emitted by to_component_css(), appended to
#      globals.css and scoped under [data-tentoro-engine] so it beats every
#      Tailwind utility (0,2,0 specificity; Tailwind v3 emits no layers).
# ===========================================================================

_MONO_STACK = "ui-monospace, 'SF Mono', SFMono-Regular, Menlo, Consolas, monospace"
_SERIF_STACK = "'Fraunces', Georgia, 'Times New Roman', serif"

_DISPLAY_SERIF = "'Fraunces', 'Source Serif 4', Georgia, serif"
_COND_STACK = "'Archivo', 'Oswald', 'Arial Narrow', sans-serif"
_ROUND_STACK = "'Plus Jakarta Sans', 'Nunito Sans', ui-rounded, system-ui, sans-serif"

# ===========================================================================
# COMPONENT SKINS — ten design LANGUAGES that differ at SILHOUETTE level.
#
# The previous cut varied only paint (radius/shadow/border) because every
# silhouette lever — KPI column count, nav width, page gutter, card gap,
# radius — lived on the ARCHETYPE axis. Two apps therefore differed by "4px
# of radius, a blur and a hue" (measured live; the user's complaint was
# exactly right). Those levers now live HERE, on the skin, and are emitted as
# CSS custom properties + grid-template overrides scoped under [data-skin].
#
# Acceptance bar: two skins must be tellable apart in a 200x150 thumbnail
# with the colour removed. Each therefore owns a unique tuple of
# (nav silhouette, KPI anatomy, card treatment, radius regime, type class).
# ===========================================================================

SKINS: dict[str, dict] = {
    # GRID — Swiss / International Typographic. Boxless, hairlines, no icons.
    "monoline": {
        "register": "linear", "mood": "Swiss grid — hairlines, no boxes",
        "nav": "swiss-index", "kpi": "hairline-boxless",
        "navWidth": 264, "navInset": 0, "gutter": 64, "contentMax": 1360,
        "cardGap": 32, "cardPad": 0, "sectionGap": 48,
        "kpiTemplate": "repeat(4, 1fr)", "kpiGap": "0px",
        "chartTemplate": "2fr 1fr",
        "radius": "0px", "cardBorder": "0", "cardShadow": "none",
        "btnRadius": "0px", "btnCase": "uppercase", "btnTracking": ".08em",
        "h1": ("32px", "600", "none", "-0.025em"), "display": None,
        "labelCase": "uppercase", "labelTrack": ".14em", "labelSize": "10px",
        "numSize": "40px", "numWeight": "500", "numFamily": None,
    },
    # STACK — Neo-brutalist. 3px borders, hard offset shadows, compartments.
    "gridwork": {
        "register": "workday", "mood": "neo-brutalist compartments",
        "nav": "compartments", "kpi": "compartment-strip",
        "navWidth": 248, "navInset": 0, "gutter": 32, "contentMax": 1400,
        "cardGap": 16, "cardPad": 20, "sectionGap": 28,
        "kpiTemplate": "repeat(4, 1fr)", "kpiGap": "16px",
        "chartTemplate": "1fr 1fr",
        "radius": "10px", "cardBorder": "3px", "cardShadow": "6px 6px 0 0 var(--sk-ink)",
        "btnRadius": "8px", "btnCase": "none", "btnTracking": "0",
        "h1": ("34px", "900", "none", "-0.02em"), "display": None,
        "labelCase": "uppercase", "labelTrack": ".08em", "labelSize": "11px",
        "numSize": "44px", "numWeight": "800", "numFamily": None,
    },
    # PRESS — Editorial. Serif, numbered index, ruled sections, no boxes.
    "broadsheet": {
        "register": "default", "mood": "editorial press — rules and serifs",
        "nav": "numbered-index", "kpi": "ledger-leaders",
        "navWidth": 240, "navInset": 0, "gutter": 72, "contentMax": 1180,
        "cardGap": 32, "cardPad": 0, "sectionGap": 56,
        "kpiTemplate": "repeat(2, 1fr)", "kpiGap": "0px",
        "chartTemplate": "1.618fr 1fr",
        "radius": "2px", "cardBorder": "0", "cardShadow": "none",
        "btnRadius": "2px", "btnCase": "none", "btnTracking": ".02em",
        "h1": ("30px", "400", "none", "-0.01em"), "display": _DISPLAY_SERIF,
        "labelCase": "uppercase", "labelTrack": ".1em", "labelSize": "11px",
        "numSize": "34px", "numWeight": "500", "numFamily": _DISPLAY_SERIF,
    },
    # LINEN — Japandi. Detached soft rail, nothing enclosed, nothing bold.
    "manuscript": {
        "register": "notion", "mood": "japandi calm — no boxes, no bold",
        "nav": "floating-quiet", "kpi": "hero-asymmetric",
        "navWidth": 232, "navInset": 16, "gutter": 40, "contentMax": 1280,
        "cardGap": 24, "cardPad": 28, "sectionGap": 40,
        "kpiTemplate": "2fr 1fr 1fr 1fr", "kpiGap": "24px",
        "chartTemplate": "1fr 1fr",
        "radius": "20px", "cardBorder": "0", "cardShadow": "none",
        "btnRadius": "999px", "btnCase": "none", "btnTracking": "0",
        "h1": ("28px", "400", "none", "-0.015em"), "display": None,
        "labelCase": "none", "labelTrack": "0", "labelSize": "12px",
        "numSize": "56px", "numWeight": "300", "numFamily": None,
    },
    # BENTO — modular tiles, icon-only rail, zero borders anywhere.
    "inkwell": {
        "register": "default", "mood": "bento tiles — icon rail, no borders",
        "nav": "icon-tiles", "kpi": "bento-mixed",
        "navWidth": 68, "navInset": 0, "gutter": 28, "contentMax": 1440,
        "cardGap": 12, "cardPad": 20, "sectionGap": 12,
        "kpiTemplate": "repeat(4, 1fr)", "kpiGap": "12px",
        "chartTemplate": "2fr 1fr",
        "radius": "22px", "cardBorder": "0", "cardShadow": "0 1px 2px rgba(0,0,0,.05)",
        "btnRadius": "14px", "btnCase": "none", "btnTracking": "0",
        "h1": ("26px", "700", "none", "-0.02em"), "display": _ROUND_STACK,
        "labelCase": "none", "labelTrack": "0", "labelSize": "12px",
        "numSize": "46px", "numWeight": "600", "numFamily": _ROUND_STACK,
    },
    # TERMINAL — Bloomberg density. Mono everywhere, 1px grid, 6-cell strip.
    "terminal": {
        "register": "linear", "mood": "terminal density — mono, 1px grid",
        "nav": "terminal-dense", "kpi": "shared-strip",
        "navWidth": 216, "navInset": 0, "gutter": 16, "contentMax": None,
        "cardGap": 8, "cardPad": 12, "sectionGap": 8,
        "kpiTemplate": "repeat(6, 1fr)", "kpiGap": "0px",
        "chartTemplate": "1fr 1fr 1fr",
        "radius": "0px", "cardBorder": "1px", "cardShadow": "none",
        "btnRadius": "0px", "btnCase": "uppercase", "btnTracking": ".06em",
        "h1": ("16px", "500", "uppercase", ".08em"), "display": _MONO_STACK,
        "labelCase": "uppercase", "labelTrack": ".06em", "labelSize": "10px",
        "numSize": "22px", "numWeight": "500", "numFamily": _MONO_STACK,
    },
    # DECO — Art Deco. Centered symmetry, chamfers, double rules, 3-up.
    "deco": {
        "register": "default", "mood": "art deco — centered, chamfered",
        "nav": "deco-centered", "kpi": "deco-plaques",
        "navWidth": 256, "navInset": 0, "gutter": 48, "contentMax": 1240,
        "cardGap": 24, "cardPad": 24, "sectionGap": 40,
        "kpiTemplate": "repeat(3, 1fr)", "kpiGap": "24px",
        "chartTemplate": "1fr 1.2fr 1fr",
        "radius": "0px", "cardBorder": "1px", "cardShadow": "none",
        "btnRadius": "0px", "btnCase": "uppercase", "btnTracking": ".14em",
        "h1": ("26px", "600", "uppercase", ".16em"), "display": _COND_STACK,
        "labelCase": "uppercase", "labelTrack": ".18em", "labelSize": "10px",
        "numSize": "42px", "numWeight": "500", "numFamily": _COND_STACK,
    },
    # BLOCK — Memphis / Pop. Full-bleed colour bars, tint blocks, pills.
    "signal": {
        "register": "stripe", "mood": "memphis blocks — colour bars, pills",
        "nav": "color-bars", "kpi": "tint-blocks",
        "navWidth": 260, "navInset": 0, "gutter": 32, "contentMax": 1400,
        "cardGap": 14, "cardPad": 20, "sectionGap": 32,
        "kpiTemplate": "repeat(4, 1fr)", "kpiGap": "14px",
        "chartTemplate": "1.5fr 1fr",
        "radius": "0px", "cardBorder": "0", "cardShadow": "none",
        "btnRadius": "999px", "btnCase": "none", "btnTracking": "0",
        "h1": ("36px", "900", "none", "-0.03em"), "display": None,
        "labelCase": "uppercase", "labelTrack": ".08em", "labelSize": "10px",
        "numSize": "46px", "numWeight": "900", "numFamily": None,
    },
    # ATOMIC — Mid-century soft-UI. Pill nav with discs, stats beside chart.
    "meadow": {
        "register": "figma", "mood": "mid-century soft — discs and pills",
        "nav": "pill-discs", "kpi": "stat-column",
        "navWidth": 244, "navInset": 0, "gutter": 36, "contentMax": 1320,
        "cardGap": 20, "cardPad": 22, "sectionGap": 32,
        "kpiTemplate": "repeat(2, 1fr)", "kpiGap": "20px",
        "chartTemplate": "1fr 1fr",
        "radius": "18px", "cardBorder": "0",
        "cardShadow": "0 2px 8px rgba(60,50,35,.07), inset 0 1px 0 rgba(255,255,255,.7)",
        "btnRadius": "999px", "btnCase": "none", "btnTracking": "0",
        "h1": ("28px", "600", "none", "-0.01em"), "display": None,
        "labelCase": "none", "labelTrack": ".07em", "labelSize": "11px",
        "numSize": "30px", "numWeight": "600", "numFamily": None,
    },
    # AERO — Glass. Floating glass rail, one KPI ribbon, gradient hairlines.
    "aurora": {
        "register": "default", "mood": "glass aero — ribbon and blur",
        "nav": "glass-float", "kpi": "glass-ribbon",
        "navWidth": 236, "navInset": 14, "gutter": 24, "contentMax": 1400,
        "cardGap": 18, "cardPad": 22, "sectionGap": 24,
        "kpiTemplate": "repeat(5, 1fr)", "kpiGap": "0px",
        "chartTemplate": "repeat(3, 1fr)",
        "radius": "20px", "cardBorder": "1px",
        "cardShadow": "0 4px 16px rgba(31,38,135,.10), inset 0 1px 0 rgba(255,255,255,.7)",
        "btnRadius": "999px", "btnCase": "none", "btnTracking": "0",
        "h1": ("30px", "600", "none", "-0.02em"), "display": _ROUND_STACK,
        "labelCase": "none", "labelTrack": "0", "labelSize": "11px",
        "numSize": "28px", "numWeight": "600", "numFamily": None,
    },
}

_ARCHETYPE_SKINS: dict[str, tuple[str, ...]] = {
    "fintech":       ("terminal", "monoline", "signal", "deco"),
    "healthcare":    ("meadow", "manuscript", "inkwell", "aurora"),
    "consumer-warm": ("meadow", "manuscript", "signal", "inkwell"),
    "legal":         ("broadsheet", "deco", "monoline"),
    "creative":      ("aurora", "gridwork", "signal", "deco"),
    "developer":     ("terminal", "monoline", "gridwork"),
    "logistics":     ("gridwork", "terminal", "signal"),
    "education":     ("signal", "meadow", "inkwell", "manuscript"),
    "hospitality":   ("deco", "broadsheet", "manuscript", "aurora"),
    "hr-people":     ("manuscript", "meadow", "inkwell"),
    "commerce":      ("signal", "aurora", "inkwell", "deco"),
    "industrial":    ("terminal", "gridwork", "monoline"),
    "analytics":     ("monoline", "terminal", "broadsheet"),
    "fitness":       ("signal", "gridwork", "aurora"),
    "default-saas":  ("inkwell", "monoline", "meadow", "aurora",
                      "manuscript", "broadsheet", "terminal"),
}


def pick_skin(archetype: str, seed: bytes) -> str:
    return _pick(_ARCHETYPE_SKINS.get(archetype, _ARCHETYPE_SKINS["default-saas"]),
                 seed, 25)


def _skin_of(dna: dict) -> tuple[str, dict]:
    name = dna.get("skin") or "inkwell"
    return name, SKINS.get(name, SKINS["inkwell"])


# ── compositional engine bridge ───────────────────────────────────────────
# The named SKINS above remain as presets (back-compat + tests); a fresh
# generation composes its own language instead.

def _compose(archetype: str, seed: bytes, brief: object | None = None) -> dict:
    from services.design_language import compose_language, design_signature
    lang = compose_language(archetype, seed, brief=brief)
    key = "lang" + hashlib.sha256(lang["signature"].encode()).hexdigest()[:8]
    lang["skinKey"] = key
    # The register (Card/MetricTile/Hero variant set) follows the card
    # treatment so component DOM and CSS agree.
    lang["register"] = {
        "thick": "workday", "hard-offset": "workday",
        "hairline": "linear", "rules-only": "default",
        "none": "notion", "tint-fill": "figma",
        "soft-shadow": "default", "layered": "default", "glass": "stripe",
    }.get(lang["cardTreatment"], "default")
    return lang

def to_component_css(dna: dict) -> str:
    """The per-app component-language stylesheet.

    Composed-language apps delegate to design_language.language_css; the
    named-skin path below remains for presets and older projects.

    Emits (a) silhouette CSS custom properties the app shell reads
    (--sk-nav-w, --sk-gutter, --sk-content-max…), and (b) scoped rules that
    restructure the KPI band, cards, buttons, tables and type.

    Selector contract: everything is scoped under [data-skin="<skin>"], which
    the generated (dashboard)/layout.tsx stamps on a div wrapping the whole
    shell. That is (0,2,0)+ specificity — it beats every Tailwind utility
    (Tailwind v3 emits no cascade layers) without !important, except for the
    audited inline-style / !-utility hazards which are flagged inline below.
    """
    if dna.get("language"):
        from services.design_language import language_css
        return language_css(dna["language"], dna["color"],
                            dark=dna.get("mode") == "dark",
                            scope='[data-skin="%s"]' % dna["skin"])
    name, s = _skin_of(dna)
    c = dna["color"]
    dark = dna.get("mode") == "dark"
    S = '[data-skin="%s"]' % name
    ink = c["textPrimary"]
    surf = c["surface"]
    line = "rgba(255,255,255,0.12)" if dark else "rgba(20,20,30,0.12)"
    hair = "rgba(255,255,255,0.08)" if dark else "rgba(20,20,30,0.08)"
    prim, acc = c["primary"], c["accent"]
    h1_size, h1_weight, h1_case, h1_track = s["h1"]

    # KPI band + chart row live inside Tailwind `.grid` wrappers; :has() lets
    # the skin restructure them without touching any page schema.
    KPI = f"{S} .grid:has([data-metric-tile]), {S} .grid:has([data-importance])"
    TILE = f"{S} :where([data-metric-tile], [data-importance])"
    LABEL = f"{TILE} :where(p:first-of-type)"
    VALUE = f"{TILE} :where(p:nth-of-type(2))"
    CARD = f"{S} :where([data-card])"

    r: list[str] = [f"/* skin: {name} — {s['mood']} */"]

    # ── silhouette variables the shell reads ──────────────────────────────
    r.append(
        f"{S} {{ --sk-ink: {ink}; --sk-line: {line}; --sk-hair: {hair};"
        f" --sk-primary: {prim}; --sk-accent: {acc}; --sk-surface: {surf};"
        f" --sk-nav-w: {s['navWidth']}px; --sk-nav-inset: {s['navInset']}px;"
        f" --sk-gutter: {s['gutter']}px;"
        f" --sk-content-max: {s['contentMax'] and str(s['contentMax']) + 'px' or '100%'};"
        f" --sk-card-gap: {s['cardGap']}px; --sk-card-pad: {s['cardPad']}px;"
        f" --sk-radius: {s['radius']}; }}")

    # ── page rhythm: gutter + measure (beats frameClass utilities) ────────
    # Responsive: on mobile the design's full gutter (often 48–72px) crushes
    # content into a narrow strip; step it up 12 → 24 → full at sm/lg
    # breakpoints. Same mobile-compat bug as design_language.py.
    _gut = s['gutter']
    _gut_sm = min(_gut, 24)
    _gut_xs = min(_gut, 12)
    _sg = s['sectionGap']
    _sg_sm = min(_sg, 24)
    _sg_xs = min(_sg, 16)
    r.append(f"{S} main > div {{ padding: {_gut_xs}px;"
             " max-width: var(--sk-content-max); }")
    r.append(f"@media (min-width: 640px) {{ {S} main > div {{ padding: {_gut_sm}px; }} }}")
    r.append(f"@media (min-width: 1024px) {{ {S} main > div {{ padding: var(--sk-gutter); }} }}")
    r.append(f"{S} main > div > * {{ margin-bottom: {_sg_xs}px; }}")
    r.append(f"@media (min-width: 640px) {{ {S} main > div > * {{ margin-bottom: {_sg_sm}px; }} }}")
    r.append(f"@media (min-width: 1024px) {{ {S} main > div > * {{ margin-bottom: {_sg}px; }} }}")

    # ── type voice ────────────────────────────────────────────────────────
    if s["display"]:
        r.append(f"{S} :where(h1, h2, [data-slot='header']) {{ font-family: {s['display']}; }}")
    r.append(f"{S} :where(main h1) {{ font-size: {h1_size}; font-weight: {h1_weight};"
             f" text-transform: {h1_case}; letter-spacing: {h1_track}; }}")

    # ── KPI BAND — the loudest silhouette. Each skin gets a real anatomy. ──
    # Column count belongs to the composer (schema Grid columns=N) — see
    # design_language.py's KPI band for the live failure this caused. The
    # skin keeps gap only, floored so 0-gap anatomies can't fuse tiles.
    r.append(f"{KPI} {{ gap: max({s['kpiGap']}, 8px); }}")
    r.append(f"{LABEL} {{ font-size: {s['labelSize']}; text-transform: {s['labelCase']};"
             f" letter-spacing: {s['labelTrack']}; }}")
    r.append(f"{VALUE} {{ font-size: {s['numSize']}; font-weight: {s['numWeight']} !important;"
             + (f" font-family: {s['numFamily']} !important;" if s["numFamily"] else "")
             + " line-height: 1.05; }")

    kpi = s["kpi"]
    if kpi == "hairline-boxless":
        # Swiss: no box at all; cells divided by hairlines, band bracketed.
        r += [f"{TILE} {{ border: 0; border-radius: 0; box-shadow: none;"
              f" background: transparent; padding: 18px 24px; }}",
              f"{TILE}:not(:first-child) {{ border-left: 1px solid {line}; }}",
              f"{KPI} {{ border-top: 1px solid {ink}; border-bottom: 1px solid {line};"
              " padding: 4px 0; }"]
    elif kpi == "compartment-strip":
        # Brutalist: bordered compartment, label strip over a rule.
        r += [f"{TILE} {{ border: 3px solid {ink}; border-radius: 10px;"
              f" box-shadow: 5px 5px 0 0 {ink}; background: {surf}; padding: 0; overflow: hidden; }}",
              f"{LABEL} {{ background: {prim}1f; border-bottom: 3px solid {ink};"
              " margin: 0; padding: 8px 14px; font-weight: 800; }",
              f"{VALUE} {{ padding: 12px 14px 16px; margin: 0; }}"]
    elif kpi == "ledger-leaders":
        # Editorial: ruled ledger rows, no boxes, dotted leaders.
        r += [f"{TILE} {{ border: 0; border-radius: 0; box-shadow: none; background: transparent;"
              f" border-bottom: 1px dotted {line}; padding: 10px 0;"
              " display: flex; align-items: baseline; justify-content: space-between; }",
              f"{LABEL} {{ font-variant: small-caps; text-transform: none; }}",
              f"{VALUE} {{ text-align: right; }}"]
    elif kpi == "hero-asymmetric":
        # Japandi: one giant light numeral, label BELOW, nothing enclosed.
        r += [f"{TILE} {{ border: 0; border-radius: 0; box-shadow: none; background: transparent;"
              " padding: 8px 0; display: flex; flex-direction: column-reverse;"
              " justify-content: flex-end; }",
              f"{LABEL} {{ border-top: 1px solid {hair}; padding-top: 8px; margin-top: 10px;"
              " opacity: .7; }",
              f"{TILE}:not(:first-child) :where(p:nth-of-type(2)) {{ font-size: 30px; }}"]
    elif kpi == "bento-mixed":
        # Bento: unequal rounded tiles, filled tints, zero borders.
        r += [f"{TILE} {{ border: 0; border-radius: 22px; box-shadow: 0 1px 2px rgba(0,0,0,.05);"
              f" background: {prim}12; padding: 20px; }}",
              f"{KPI} {{ grid-auto-rows: 104px; }}",
              f"{TILE}:first-child {{ grid-column: span 2; grid-row: span 2; }}",
              f"{TILE}:nth-child(4) {{ grid-column: span 2; }}"]
    elif kpi == "shared-strip":
        # Terminal: ONE bordered strip, six cells, zero gap, mono.
        r += [f"{KPI} {{ border: 1px solid {line}; }}",
              f"{TILE} {{ border: 0; border-radius: 0; box-shadow: none; background: transparent;"
              " padding: 10px 12px; }",
              f"{TILE}:not(:first-child) {{ border-left: 1px solid {line}; }}"]
    elif kpi == "deco-plaques":
        # Deco: 3-up centred plaques, chamfered, capped by an accent band.
        r += [f"{TILE} {{ border: 1px solid {ink}; border-radius: 0; box-shadow: none;"
              f" background: {surf}; padding: 20px; text-align: center;"
              " clip-path: polygon(10px 0, 100% 0, 100% calc(100% - 10px),"
              " calc(100% - 10px) 100%, 0 100%, 0 10px);"
              f" border-top: 3px solid {acc}; }}",
              f"{LABEL} {{ text-align: center; }}",
              f"{VALUE} {{ text-align: center; }}"]
    elif kpi == "tint-blocks":
        # Memphis: saturated tint blocks, ink label chip, huge bottom numeral.
        r += [f"{TILE} {{ border: 0; border-radius: 0; box-shadow: none; padding: 18px;"
              " min-height: 128px; display: flex; flex-direction: column;"
              f" justify-content: space-between; background: {prim}1a; }}",
              f"{TILE}:nth-child(2) {{ background: {acc}1a; }}",
              f"{TILE}:nth-child(3) {{ background: {prim}26; }}",
              f"{TILE}:nth-child(4) {{ background: {acc}26; }}",
              f"{LABEL} {{ align-self: flex-start; background: {ink};"
              f" color: {surf}; border-radius: 999px; padding: 3px 10px; font-weight: 800; }}"]
    elif kpi == "stat-column":
        # Mid-century: soft capsules with an inset highlight, 2-up.
        r += [f"{TILE} {{ border: 0; border-radius: 18px;"
              " box-shadow: 0 2px 6px rgba(60,50,35,.06), inset 0 1px 0 rgba(255,255,255,.7);"
              f" background: {surf}; padding: 16px 18px; }}",
              f"{LABEL} {{ font-variant: small-caps; text-transform: none; }}"]
    elif kpi == "glass-ribbon":
        # Aero: ONE glass ribbon, inline pairs, fading vertical hairlines.
        glass = "rgba(23,23,33,.55)" if dark else "rgba(255,255,255,.62)"
        r += [f"{KPI} {{ background: {glass}; backdrop-filter: blur(18px);"
              f" border: 1px solid {'rgba(255,255,255,.14)' if dark else 'rgba(255,255,255,.6)'};"
              " border-radius: 20px; padding: 6px; }",
              f"{TILE} {{ border: 0; border-radius: 0; box-shadow: none; background: transparent;"
              " padding: 14px 16px; text-align: center; }",
              f"{TILE}:not(:first-child) {{ border-left: 1px solid {hair}; }}"]

    # ── CARD silhouette ───────────────────────────────────────────────────
    card_bg = "transparent" if s["cardBorder"] == "0" and s["cardShadow"] == "none" else surf
    r.append(f"{CARD}, {S} :where([data-table], [data-activity-feed])"
             f" {{ border-width: {s['cardBorder']}; border-color: {ink if s['cardBorder'] == '3px' else line};"
             f" border-radius: {s['radius']}; box-shadow: {s['cardShadow']};"
             f" background: {card_bg}; }}")
    if s["cardPad"]:
        r.append(f"{CARD} > :where([data-slot='body']) {{ padding: {s['cardPad']}px; }}")

    # Header treatment differs per language family.
    HEAD = f"{CARD} > :where([data-slot='header'])"
    if name in ("monoline", "broadsheet", "deco"):
        r.append(f"{HEAD} {{ background: transparent; border-bottom: 1px solid {ink};"
                 f" text-transform: {s['labelCase']}; letter-spacing: {s['labelTrack']};"
                 " font-size: 13px; }")
    elif name == "gridwork":
        r.append(f"{HEAD} {{ background: {prim}1f; border-bottom: 3px solid {ink};"
                 " text-transform: uppercase; letter-spacing: .06em; font-weight: 800; }")
    elif name == "terminal":
        r.append(f"{HEAD} {{ background: {hair}; border-bottom: 1px solid {line};"
                 f" font-family: {_MONO_STACK}; text-transform: uppercase;"
                 " letter-spacing: .06em; font-size: 11px; padding: 5px 12px; }")
    else:  # manuscript / inkwell / signal / meadow / aurora — no band at all
        r.append(f"{HEAD} {{ background: transparent; border-bottom: none;"
                 " text-transform: none; letter-spacing: 0; font-size: 15px; }")
    if name == "signal":
        r.append(f"{CARD} {{ border-top: 6px solid {acc}; }}")

    # ── BUTTON silhouette ─────────────────────────────────────────────────
    r.append(f"{S} :where(button) {{ border-radius: {s['btnRadius']};"
             f" text-transform: {s['btnCase']}; letter-spacing: {s['btnTracking']}; }}")
    if name == "gridwork":
        r += [f"{S} :where(button) {{ border: 3px solid {ink}; box-shadow: 4px 4px 0 0 {ink};"
              " font-weight: 800; transition: transform 80ms, box-shadow 80ms; }",
              f"{S} :where(button:hover) {{ transform: translate(-2px,-2px);"
              f" box-shadow: 6px 6px 0 0 {ink}; }}",
              f"{S} :where(button:active) {{ transform: translate(2px,2px); box-shadow: none; }}"]
    elif name == "terminal":
        r.append(f"{S} :where(button) {{ border: 1px solid {line}; box-shadow: none;"
                 f" font-family: {_MONO_STACK}; font-size: 11px; }}")
    elif name == "aurora":
        r.append(f"{S} :where(button.bg-primary, button[data-variant='primary'])"
                 f" {{ background: linear-gradient(180deg, {prim}, {acc});"
                 f" box-shadow: 0 2px 8px {prim}4d, inset 0 1px 0 rgba(255,255,255,.35); }}")
    elif name in ("manuscript", "meadow"):
        r.append(f"{S} :where(button.bg-secondary, button[data-variant='secondary'])"
                 f" {{ background: {prim}1f; border-color: transparent; }}")
    elif name == "signal":
        r.append(f"{S} :where(button) {{ font-weight: 800; box-shadow: none; }}")
    elif name in ("monoline", "broadsheet", "deco"):
        r.append(f"{S} :where(button) {{ box-shadow: none; }}")

    # ── TABLE voice ───────────────────────────────────────────────────────
    T = f"{S} [data-table]"
    if name == "terminal":
        r += [f"{T} :where(thead) {{ background: {hair}; }}",
              f"{T} :where(th, td) {{ border: 1px solid {line}; font-family: {_MONO_STACK};"
              " font-size: 11px; padding: 4px 8px; }"]
    elif name in ("monoline", "broadsheet"):
        r += [f"{T} :where(thead) {{ background: transparent; }}",
              f"{T} :where(thead th) {{ border-bottom: {'2px' if name == 'broadsheet' else '1px'}"
              f" solid {ink}; letter-spacing: {s['labelTrack']}; }}",
              f"{T} :where(tbody tr) {{ border-bottom: 1px solid {hair}; }}"]
    elif name == "gridwork":
        r += [f"{T} :where(thead) {{ background: {ink}; }}",
              f"{T} :where(thead th) {{ color: {surf}; font-weight: 800; }}",
              f"{T} :where(tbody tr) {{ border-bottom: 2px solid {line}; }}"]
    elif name == "signal":
        r += [f"{T} :where(thead) {{ background: {ink}; }}",
              f"{T} :where(thead th) {{ color: {surf}; font-weight: 800; }}",
              f"{T} :where(tbody tr:nth-child(even)) {{ background: {prim}0f; }}"]
    else:  # soft families — rules dissolve
        r += [f"{T} :where(thead) {{ background: transparent; }}",
              f"{T} :where(thead th) {{ text-transform: none; letter-spacing: 0; font-size: 12px; }}",
              f"{T} :where(tbody tr) {{ border-bottom: 1px solid {hair}; }}",
              f"{T} :where(tbody td) {{ padding-top: .85rem; padding-bottom: .85rem; }}"]

    # ── chart row rhythm ──────────────────────────────────────────────────
    r.append(f"{S} .grid:has(> * [data-card]):not(:has([data-metric-tile]))"
             f" {{ grid-template-columns: {s['chartTemplate']} !important;"
             f" gap: {s['cardGap']}px !important; }}")

    return "/* tentoro:skin */\n" + "\n".join(r) + "\n/* /tentoro:skin */"

_SKIN_NAV_STYLE: dict[str, str] = {
    "inkwell": "icon-tiles", "monoline": "swiss-index", "manuscript": "floating-quiet",
    "signal": "color-bars", "meadow": "pill-discs", "gridwork": "compartments",
    "aurora": "glass-float", "broadsheet": "numbered-index",
    "terminal": "terminal-dense", "deco": "deco-centered",
}


def nav_style_for(skin: str) -> str:
    return _SKIN_NAV_STYLE.get(skin, "quiet")


def to_nav_css(dna: dict) -> str:
    """Per-skin navigation identity stylesheet (marker-wrapped, idempotent).

    Targets the app-layout rails via [data-skin="<skin>"] scoping and the
    template's data-nav-item / data-nav-icon / data-nav-label hooks. Every
    pattern below changes the PRESENTATION GRAMMAR of the menu, not just its
    paint — an index, an outline, a set of compartments, a dock of pills.
    """
    if dna.get("language"):
        from services.design_language import nav_language_css
        return nav_language_css(dna["language"], dna["color"],
                                dark=dna.get("mode") == "dark",
                                scope='[data-skin="%s"]' % dna["skin"])
    skin = dna.get("skin") or "inkwell"
    c = dna["color"]
    dark = dna.get("mode") == "dark"
    S = f'[data-skin="{skin}"]'
    N = f"{S} [data-shell-nav]"
    line = "rgba(255,255,255,0.12)" if dark else "rgba(20,20,30,0.12)"
    r: list[str] = [f"/* nav: {_SKIN_NAV_STYLE.get(skin, 'quiet')} */"]

    if skin == "broadsheet":
        r += [
            # NUMBERED INDEX — a typeset table of contents. Icons vanish;
            # two-digit indices thread the menu (pure CSS counters).
            f"{N} {{ counter-reset: navidx; }}",
            f"{N} [data-nav-icon] {{ display: none; }}",
            f"{N} [data-nav-item] {{ counter-increment: navidx; border-radius: 0;"
            " padding-top: .55rem; padding-bottom: .55rem; }",
            f"{N} [data-nav-item]::before {{ content: counter(navidx, decimal-leading-zero);"
            f" font-family: {_SERIF_STACK}; font-size: 12px; opacity: .55;"
            " margin-right: .8rem; letter-spacing: .08em; }",
            f"{N} [data-nav-item][data-active='true'] {{ background: transparent;"
            f" border-top: 2px solid currentColor; font-weight: 600; }}",
            f"{N} [data-nav-label] {{ letter-spacing: .02em; }}",
            f"{N} [data-nav-group-label] {{ font-family: {_SERIF_STACK};"
            " text-transform: none; font-style: italic; letter-spacing: .04em; opacity: .6; }",
        ]
    elif skin == "manuscript":
        r += [
            # DOCUMENT OUTLINE — text-only, indented under dotted guides,
            # lowercase; reads as a page tree, not an app menu.
            f"{N} [data-nav-icon] {{ display: none; }}",
            f"{N} [data-nav-item] {{ border-radius: 6px; padding-left: 1rem;"
            f" border-left: 1px dotted {line}; margin-left: .5rem; }}",
            f"{N} [data-nav-label] {{ text-transform: lowercase; font-size: 13.5px; }}",
            f"{N} [data-nav-item][data-active='true']"
            " { background: rgba(255,255,255,.07); font-weight: 600; }",
            f"{N} [data-nav-group-label] {{ text-transform: lowercase;"
            " letter-spacing: 0; font-style: italic; opacity: .55; }",
        ]
    elif skin == "gridwork":
        b = "rgba(255,255,255,.5)" if dark else "rgba(20,20,30,.6)"
        r += [
            # COMPARTMENTS — every destination is a bordered cell; the active
            # cell inverts. The menu reads as a printed form.
            f"{N} [data-nav-item] {{ border: 1px solid {b}; border-radius: 0;"
            " margin-bottom: 4px; text-transform: uppercase; font-size: 11px;"
            " letter-spacing: .07em; font-weight: 700; }",
            f"{N} [data-nav-item][data-active='true'] {{ background: {'#e8fca8' if dark else '#101014'};"
            f" color: {'#101014' if dark else '#ffffff'}; border-color: transparent; }}",
            f"{N} [data-nav-item]:hover {{ transform: translate(-1px,-1px);"
            f" box-shadow: 2px 2px 0 0 {b}; }}",
            f"{N} [data-nav-group-label] {{ letter-spacing: .14em; font-weight: 800;"
            f" border-bottom: 2px solid {b}; padding-bottom: .3rem; }}",
        ]
    elif skin == "meadow":
        r += [
            # PILL CHIPS + ICON DISCS — friendly, color-indexed.
            f"{N} [data-nav-item] {{ border-radius: 9999px; }}",
            f"{N} [data-nav-icon] {{ background: {c['primary']}22; border-radius: 9999px;"
            " padding: .3rem; }",
            f"{N} [data-nav-item][data-active='true'] {{ background: {c['primary']}2b;"
            " font-weight: 600; }",
            f"{N} [data-nav-item] {{ transition: transform 160ms cubic-bezier(.34,1.3,.64,1); }}",
            f"{N} [data-nav-item]:hover {{ transform: translateX(3px); }}",
            f"{N} [data-nav-group-label] {{ text-transform: none; letter-spacing: 0;"
            " font-weight: 600; opacity: .55; }",
        ]
    elif skin == "aurora":
        grad = f"linear-gradient(120deg, {c['primary']}, {c['accent']})"
        r += [
            # GLASS CAPSULES — active item wears a gradient hairline + glow.
            f"{N} [data-nav-item] {{ border-radius: 10px; border: 1px solid transparent; }}",
            f"{N} [data-nav-item][data-active='true'] {{"
            " background: linear-gradient(rgba(255,255,255,.06), rgba(255,255,255,.06)) padding-box,"
            f" {grad} border-box; border: 1px solid transparent;"
            f" box-shadow: 0 0 14px {c['primary']}44; }}",
            f"{N} [data-nav-item] {{ transition: box-shadow 200ms ease, background 200ms ease; }}",
            f"{N} [data-nav-item]:hover {{ box-shadow: 0 0 10px {c['primary']}33; }}",
            f"{N} [data-nav-group-label] {{ letter-spacing: .12em; opacity: .5; }}",
        ]
    elif skin == "monoline":
        r += [
            # DENSE INSTRUMENT LIST — tight rows, right-aligned mono index
            # chips (keyboard-shortcut grammar), instant state changes.
            f"{N} {{ counter-reset: navidx; }}",
            f"{N} [data-nav-item] {{ counter-increment: navidx; border-radius: 5px;"
            " padding-top: .32rem; padding-bottom: .32rem; font-size: 13px;"
            " transition: none; }",
            f"{N} [data-nav-item]::after {{ content: counter(navidx);"
            f" font-family: {_MONO_STACK}; font-size: 10px; margin-left: auto;"
            f" border: 1px solid {line}; border-bottom-width: 2px; border-radius: 4px;"
            " padding: 0 .35rem; opacity: .55; }",
            f"{N} [data-nav-item][data-active='true'] {{ background: rgba(255,255,255,.08);"
            f" box-shadow: inset 2px 0 0 {c['accent']}; }}",
            f"{N} [data-nav-group-label] {{ letter-spacing: .1em; font-size: 10px; }}",
        ]
    elif skin == "signal":
        r += [
            # BOLD BLOCKS — the active destination is a solid statement.
            f"{N} [data-nav-item] {{ border-radius: 8px; font-weight: 600; }}",
            f"{N} [data-nav-item][data-active='true'] {{"
            f" background: {c['accent']}; color: #101014; font-weight: 700; }}",
            f"{N} [data-nav-icon] {{ display: none; }}",
            f"{N} [data-nav-label] {{ font-size: 14px; letter-spacing: -0.01em; }}",
            f"{N} [data-nav-group-label] {{ font-weight: 800; font-size: 11px;"
            " letter-spacing: .05em; }",
        ]
    elif skin == "terminal":
        # TERMINAL — full-bleed inverted active bar, mono caps, caret prefix.
        r += [
            f"{N} [data-nav-item] {{ border-radius: 0; padding-top: .18rem;"
            f" padding-bottom: .18rem; font-family: {_MONO_STACK}; font-size: 12px;"
            " text-transform: uppercase; letter-spacing: .02em; transition: none; }",
            f"{N} [data-nav-item]::before {{ content: \"\\203A\"; opacity: .45;"
            " margin-right: .45rem; }",
            f"{N} [data-nav-item][data-active='true'] {{ background: {c['accent']};"
            f" color: {c['background']}; border-radius: 0; }}",
            f"{N} [data-nav-group-label] {{ font-family: {_MONO_STACK}; font-size: 10px;"
            f" letter-spacing: .06em; border-bottom: 1px dashed {line}; }}",
        ]
    elif skin == "deco":
        # DECO — centred symmetric text, flanking rules, no icons.
        r += [
            f"{N} [data-nav-icon] {{ display: none; }}",
            f"{N} [data-nav-item] {{ justify-content: center; text-align: center;"
            " border-radius: 0; text-transform: uppercase; font-size: 12px;"
            " letter-spacing: .16em; }",
            f"{N} [data-nav-item][data-active='true'] {{ background: transparent;"
            f" color: {c['accent']}; border-top: 1px solid {line};"
            f" border-bottom: 1px solid {line}; }}",
            f"{N} [data-nav-group-label] {{ justify-content: center; text-align: center;"
            " letter-spacing: .2em; font-size: 10px; }",
        ]
    else:  # inkwell — QUIET FLOATING: shadow-card active, small-caps labels
        r += [
            f"{N} [data-nav-item] {{ border-radius: 10px;"
            " transition: background 180ms ease, box-shadow 180ms ease; }",
            f"{N} [data-nav-item][data-active='true'] {{ background: {'rgba(255,255,255,.07)' if dark else '#ffffff'};"
            " box-shadow: 0 1px 2px rgba(20,20,30,.08), 0 4px 12px rgba(20,20,30,.07); }",
            f"{N} [data-nav-label] {{ font-variant: small-caps; letter-spacing: .03em;"
            " font-size: 13.5px; }",
            f"{N} [data-nav-group-label] {{ font-variant: small-caps;"
            " text-transform: none; letter-spacing: .06em; opacity: .5; }",
        ]

    return ("/* tentoro:nav */\n" + "\n".join(r) + "\n/* /tentoro:nav */")
