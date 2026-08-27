"""MOBILE-E — brand-derived icons, splash, and store listing.

Runs after :func:`services.mobile_scaffold.scaffold_mobile` (which
writes solid-color placeholder PNGs) and replaces those placeholders
with:

  * ``assets/icon.png``           — 1024×1024 monogram tile
  * ``assets/adaptive-icon.png``  — 1024×1024 same monogram, sized so
                                    the Android adaptive-icon safe zone
                                    contains the whole glyph
  * ``assets/splash.png``         — 1242×2436 centered app name over the
                                    brand color
  * ``assets/favicon.png``        — 48×48 downscaled icon (for the
                                    Expo web target)
  * ``store-listing.md``          — copy-paste-ready listing draft for
                                    App Store + Play Store

The design is deliberately simple — brand-color background, a big
centered monogram (first 1–2 letters of the app name), one accent
color computed from the brand hue for legibility. This is not a
Figma-quality logo, but every generated app gets a coherent icon that
matches its brand color and is not the default "expo blob".

Every file write is idempotent; a second run overwrites with the same
bytes. If Pillow raises for any reason, we log and leave the MOBILE-A
placeholders in place — mobile scaffolding must never block web
generation.
"""
from __future__ import annotations

import io
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Public API                                                                   #
# --------------------------------------------------------------------------- #

def apply_mobile_branding(mobile_dir: str) -> dict:
    """Overwrite the placeholder assets + emit the store listing.

    Reads ``mobile/app.json`` for the resolved name / brand color so
    we honour whatever MOBILE-A produced (which in turn honours the
    caller override, then design_spec, then default).

    Returns a summary dict for logging / SSE. Never raises — every
    generator step is wrapped so a partial failure produces the best
    partial result rather than blocking the pipeline.
    """
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        logger.warning(
            "mobile_branding: Pillow not installed — leaving MOBILE-A "
            "placeholder assets in place."
        )
        return {"applied": False, "reason": "pillow_missing"}

    m_dir = Path(mobile_dir)
    if not (m_dir / "app.json").is_file():
        logger.warning("mobile_branding: %s/app.json missing", mobile_dir)
        return {"applied": False, "reason": "no_app_json"}

    try:
        spec = _read_app_spec(m_dir)
    except Exception as exc:  # noqa: BLE001
        logger.warning("mobile_branding: reading app.json failed: %s", exc)
        return {"applied": False, "reason": "unreadable_app_json"}

    assets = m_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    written: list[str] = []
    for name, size, kind in [
        ("icon.png",           (1024, 1024), "icon"),
        ("adaptive-icon.png",  (1024, 1024), "adaptive"),
        ("splash.png",         (1242, 2436), "splash"),
        ("favicon.png",        (48,   48),   "icon"),
    ]:
        try:
            _write_asset(assets / name, size, kind, spec)
            written.append(f"assets/{name}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "mobile_branding: %s failed: %s (leaving placeholder)",
                name, exc,
            )

    # Store listing
    try:
        _write_store_listing(m_dir, spec)
        written.append("store-listing.md")
    except Exception as exc:  # noqa: BLE001
        logger.warning("mobile_branding: store-listing.md failed: %s", exc)

    logger.info(
        "mobile_branding: wrote %d files to %s (name=%r, brand=%s)",
        len(written), assets, spec.name, spec.brand_hex,
    )
    return {
        "applied": True,
        "files_written": written,
        "name": spec.name,
        "brand_hex": spec.brand_hex,
        "monogram": spec.monogram,
    }


# --------------------------------------------------------------------------- #
# Types                                                                        #
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class MobileSpec:
    """The bits of app.json we care about for icon/splash rendering."""
    name: str
    slug: str
    brand_hex: str  # "#RRGGBB", uppercase, always 7 chars
    description: str = ""

    @property
    def monogram(self) -> str:
        """1–2 uppercase letters for the icon tile.

        For a two-word name we take the first letter of each ("Recipe
        Collection" → "RC"). Single-word gets one letter ("Planters"
        → "P"). Non-alpha names fall back to "A"."""
        words = [w for w in re.split(r"[^A-Za-z]+", self.name) if w]
        if not words:
            return "A"
        if len(words) == 1:
            return words[0][0].upper()
        return (words[0][0] + words[1][0]).upper()


# --------------------------------------------------------------------------- #
# Reading app.json                                                             #
# --------------------------------------------------------------------------- #

def _read_app_spec(mobile_dir: Path) -> MobileSpec:
    data = json.loads((mobile_dir / "app.json").read_text(encoding="utf-8"))
    expo = data.get("expo") or {}
    name = expo.get("name") or "App"
    slug = expo.get("slug") or "app"
    splash = expo.get("splash") or {}
    brand_hex = splash.get("backgroundColor") or "#4F46E5"
    # Description comes from the plan; not stored in app.json. We read
    # it out of expo.extra if the scaffolder ever stuffs it there.
    extra = expo.get("extra") or {}
    description = extra.get("description") or ""
    return MobileSpec(
        name=name,
        slug=slug,
        brand_hex=_normalize_hex(brand_hex),
        description=description,
    )


# --------------------------------------------------------------------------- #
# Icon / splash rendering                                                      #
# --------------------------------------------------------------------------- #

def _write_asset(path: Path, size: tuple[int, int], kind: str, spec: MobileSpec) -> None:
    """Render one asset into ``path``.

    ``kind`` = "icon"   → monogram tile, filling the whole square.
    ``kind`` = "adaptive" → monogram sized into the Android safe zone
                            (66% of canvas). Background extends to the
                            edges; the launcher clips it.
    ``kind`` = "splash" → app name centered over brand color.
    """
    from PIL import Image, ImageDraw

    W, H = size
    bg = _hex_to_rgb(spec.brand_hex)
    fg = _contrasting_color(bg)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    if kind == "splash":
        _draw_centered_text(
            draw, (W, H), spec.name, fg,
            target_fraction=0.55,  # width the text should span
        )
    else:
        safe_fraction = 0.66 if kind == "adaptive" else 0.72
        _draw_centered_text(
            draw, (W, H), spec.monogram, fg,
            target_fraction=safe_fraction,
        )

    # PNG output. Optimize for size — icons under 100 KB even at 1024²
    # for a solid-background image, so no separate compression tuning.
    img.save(path, format="PNG", optimize=True)


def _draw_centered_text(
    draw: "ImageDraw.ImageDraw",
    canvas: tuple[int, int],
    text: str,
    fill: tuple[int, int, int],
    *,
    target_fraction: float,
) -> None:
    """Render ``text`` centered on the canvas, sized so its rendered
    width is roughly ``target_fraction`` of the canvas width.

    We binary-search a font size that lands close to the target — this
    is more robust than a linear scale factor because glyph metrics
    vary a lot between a monogram (short + wide) and a full app name
    (long + narrow) and between fonts.
    """
    from PIL import ImageDraw as _  # noqa: F401 (typing hint)

    W, H = canvas
    target_w = int(W * target_fraction)

    font = _pick_font(size=max(24, min(H, W) // 4))
    # Binary search font size within [12, 900].
    lo, hi, best_font = 12, min(W, H), font
    for _ in range(12):  # log2(900) ≈ 10 — 12 is generous
        mid = (lo + hi) // 2
        f = _pick_font(size=mid)
        w = _text_width(draw, text, f)
        if w > target_w:
            hi = mid - 1
        else:
            best_font = f
            lo = mid + 1
    font = best_font

    tw, th = _text_size(draw, text, font)
    x = (W - tw) // 2
    # Slight optical bias — centering by baseline puts the text a hair
    # low, so nudge up by 6% of canvas height.
    y = (H - th) // 2 - int(H * 0.06)
    draw.text((x, y), text, fill=fill, font=font)


def _text_width(draw, text: str, font) -> int:
    return _text_size(draw, text, font)[0]


def _text_size(draw, text: str, font) -> tuple[int, int]:
    """PIL removed ``textsize`` in Pillow 10 — use textbbox and convert."""
    try:
        x0, y0, x1, y1 = draw.textbbox((0, 0), text, font=font)
        return (x1 - x0, y1 - y0)
    except AttributeError:
        # Very old Pillow — fall back to font.getsize.
        return font.getsize(text)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- #
# Font picker                                                                  #
# --------------------------------------------------------------------------- #

# Preferred font files, tried in order. DejaVuSans is bundled with
# Pillow itself so we always have a working fallback.
_FONT_CANDIDATES = (
    # macOS
    "/System/Library/Fonts/SFNS.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    # Common Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    # Docker default (Pillow bundled DejaVu — always present)
    "DejaVuSans-Bold.ttf",
)


def _pick_font(size: int):
    """Return an ImageFont at ``size``. Falls through platforms until
    something opens; last resort is Pillow's built-in default (not
    scalable but always present)."""
    from PIL import ImageFont

    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size=size)
        except (OSError, IOError):
            continue
    # Absolute fallback — bitmap default, non-scalable but always there.
    return ImageFont.load_default()


# --------------------------------------------------------------------------- #
# Color helpers                                                                #
# --------------------------------------------------------------------------- #

def _normalize_hex(value: str) -> str:
    m = re.match(r"^#?([0-9A-Fa-f]{6})$", value or "")
    if not m:
        return "#4F46E5"
    return "#" + m.group(1).upper()


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _contrasting_color(bg: tuple[int, int, int]) -> tuple[int, int, int]:
    """Pick white or near-black based on WCAG relative luminance so the
    monogram is always readable on the brand background."""
    r, g, b = (c / 255.0 for c in bg)
    # sRGB → linear
    def _lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    lum = 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)
    # Dark background → white text; light background → near-black.
    return (255, 255, 255) if lum < 0.45 else (17, 17, 17)


# --------------------------------------------------------------------------- #
# Store listing                                                                #
# --------------------------------------------------------------------------- #

_PLAY_STORE_SHORT_LIMIT = 80
_PLAY_STORE_LONG_LIMIT = 4000
_APP_STORE_SUBTITLE_LIMIT = 30
_APP_STORE_KEYWORDS_LIMIT = 100


def _write_store_listing(mobile_dir: Path, spec: MobileSpec) -> None:
    """Emit ``store-listing.md`` — a copy-paste-ready draft for both
    Play Store and App Store.

    Nothing here is submitted anywhere; the user copies the fields into
    Play Console / App Store Connect themselves. The generator's job is
    to save them from staring at a blank form.
    """
    short = _short_description(spec)
    long_ = _long_description(spec)
    keywords = _keywords(spec)
    category = _guess_category(spec)

    md = f"""# App Store & Play Store listing — {spec.name}

_This is a draft. Copy each field into Google Play Console / App Store
Connect. Adjust the tone before shipping — this file is a starting
point, not a submission._

## Common

**App name:** {spec.name}

**Bundle / package id:** _configured in app.json (`expo.ios.bundleIdentifier`
and `expo.android.package`)_

**Category (suggested):** {category}

**Content rating:** Everyone (adjust in each console based on real content)

**Support URL:** _https://your-support-page.example.com_ ← edit before submitting

**Privacy policy URL:** _required by both stores; must exist before you can submit._

## Google Play Store

**Short description ({_PLAY_STORE_SHORT_LIMIT} char max):**
```
{short}
```

**Full description ({_PLAY_STORE_LONG_LIMIT} char max):**
```
{long_}
```

## Apple App Store

**Subtitle ({_APP_STORE_SUBTITLE_LIMIT} char max):**
```
{short[:_APP_STORE_SUBTITLE_LIMIT].rstrip()}
```

**Promotional text (170 char max — updatable without a new build):**
```
{short}
```

**Description:**
```
{long_}
```

**Keywords ({_APP_STORE_KEYWORDS_LIMIT} char max, comma-separated):**
```
{keywords}
```

## Screenshots

Both stores require screenshots. For a first submission you can
capture the app running in the iOS Simulator / Android Emulator:

- iOS: 6.7" (1290×2796) and 6.5" (1284×2778 or 1242×2688). Three
  screenshots minimum.
- Play Store: 1080×1920 (portrait) or higher. Two screenshots minimum;
  eight recommended.

## Age & content rating

Fill out the age-rating questionnaire honestly in each console before
you submit. Both stores block a submission until it's complete.

## First submission checklist

- [ ] Bundle / package id decided and stable
- [ ] App icon + splash reviewed (see `assets/`)
- [ ] Privacy policy URL live
- [ ] Support URL live
- [ ] Screenshots captured for all required sizes
- [ ] Store listing text copied in and edited
- [ ] Test flight / internal-track upload succeeded
"""
    (mobile_dir / "store-listing.md").write_text(md, encoding="utf-8")


def _short_description(spec: MobileSpec) -> str:
    """Fit under Google Play's 80-char limit.

    Falls back to a generic tagline when the plan description is
    missing. Never returns something over 80 chars — Play Console
    rejects overlong values.
    """
    src = spec.description or f"{spec.name} — designed for teams."
    # Take first sentence; if that's too long, hard-truncate.
    first = re.split(r"[.!?]\s+", src.strip(), maxsplit=1)[0].strip()
    if len(first) > _PLAY_STORE_SHORT_LIMIT:
        first = first[: _PLAY_STORE_SHORT_LIMIT - 1].rstrip() + "…"
    return first or spec.name


def _long_description(spec: MobileSpec) -> str:
    """Full description — a lightly structured template combining the
    plan description with generic mobile-app benefit copy.

    Kept under the 4000-char Play limit by construction; templates are
    short so the interpolated description would need to be > 3600
    chars to overflow.
    """
    core = (
        spec.description
        or f"{spec.name} helps you track what matters."
    )
    body = f"""{core}

**Why {spec.name}?**

- Fast. Every action is one tap away.
- Focused. No feature you don't need.
- Yours. Your data, your team, your rules.

**On mobile you get:**

- Native install with app icon and splash screen
- Works over 4G / 5G with a live web connection
- Signed and store-distributed — no sideloading required
- The same up-to-date data you see on desktop

**Built with Tentoro Forge.**

Tentoro Forge is a no-code platform that lets you describe an app and
have it generated. If you want to change how {spec.name} works, edit
the plan on the platform and rebuild — the mobile app updates on the
next release.
"""
    return body.strip()


def _keywords(spec: MobileSpec) -> str:
    """Comma-separated App Store keywords, 100 char cap.

    Starts with keywords extracted from the plan description; falls
    back to a generic set based on the app name.
    """
    src = f"{spec.name} {spec.description}"
    words = [w.lower() for w in re.findall(r"[A-Za-z]{4,}", src)]
    stop = {"this", "that", "with", "from", "your", "make", "user",
            "team", "have", "into", "them", "will", "them", "each",
            "when", "which", "there", "their", "about"}
    # Preserve order, dedupe, drop stopwords, keep up to 10.
    seen: set[str] = set()
    picked: list[str] = []
    for w in words:
        if w in stop or w in seen:
            continue
        seen.add(w)
        picked.append(w)
        if len(picked) >= 10:
            break
    if not picked:
        picked = [spec.name.lower(), "app", "productivity", "tool"]
    joined = ",".join(picked)
    if len(joined) > _APP_STORE_KEYWORDS_LIMIT:
        # Drop from the tail until we fit — first keywords rank highest.
        while picked and len(",".join(picked)) > _APP_STORE_KEYWORDS_LIMIT:
            picked.pop()
        joined = ",".join(picked)
    return joined


def _guess_category(spec: MobileSpec) -> str:
    """Very light heuristic — matches a few obvious signals against
    common store categories. Returns the store-neutral name; the user
    picks the exact one in each console."""
    text = f"{spec.name} {spec.description}".lower()
    # Ordered most-specific → least-specific. "Book your next trip" must
    # match Travel via "trip"/"flight" before Books catches "book" —
    # travel-specific keywords take priority over the generic verb.
    catalog = [
        (["shop", "cart", "buy", "commerce", "store"], "Shopping"),
        (["health", "fitness", "workout", "exercise"], "Health & Fitness"),
        (["recipe", "food", "meal", "kitchen"], "Food & Drink"),
        (["travel", "trip", "flight", "hotel"], "Travel"),
        (["read", "library", "novel"], "Books"),
        (["photo", "camera", "gallery"], "Photo & Video"),
        (["finance", "invoice", "expense", "budget"], "Finance"),
        (["education", "course", "lesson", "learn"], "Education"),
        (["kid", "child", "family"], "Kids / Family"),
        (["game", "play", "puzzle"], "Games"),
        (["business", "crm", "sales", "team", "hr", "hire"], "Business"),
    ]
    for needles, category in catalog:
        if any(n in text for n in needles):
            return category
    return "Productivity"  # sensible default for internal-tool style apps
