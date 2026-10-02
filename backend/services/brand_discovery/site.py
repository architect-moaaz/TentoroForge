"""Read a company's website: what it looks like, and what it says it is.

WHY A BROWSER AND NOT A REGEX. `services.url_brand_scraper` already reads a
URL — it pulls `og:image` and clusters that one picture into two colours. That
is a good answer to "what colour is their logo" and a poor one to "what is
their design language", because a design language is stated by the *rendered
page*: which colour a button is, which one a link is, what the ground is, what
the type is set in, how round the corners are. None of that is in the HTML
source; it is in the computed styles, behind whatever CSS the site ships.

So the primary read is a real Chromium render, and what comes back is a
CENSUS rather than a judgement: every visible element's computed colours,
fonts, radii and weights, counted, with the role each value was playing. The
reading of that census into a palette is `design.py`'s job and it is
deterministic — a model asked to "extract the brand colours" from a page
returns a plausible palette, which is not the same as theirs.

THE FALLBACK IS NOT THE SAME ANSWER, AND SAYS SO. Playwright is not installed
everywhere the backend runs, and some sites refuse a headless browser. Rather
than fail the onboarding, a plain HTTP fetch reads what the markup states
outright — theme-color, inline hex literals, font-family declarations, the
og tags. `Reading.rendered` records which of the two produced the numbers, so
Settings can show "read from the page source" and offer to try again, and so
nobody mistakes a thin read for a thorough one.

NOTHING HERE DECIDES ANYTHING. This module returns evidence. `design.py` turns
it into tokens, `identity.py` asks a model what the words mean, and
`run.py` assembles both into a profile. Kept apart so the expensive, flaky
part (the network) is testable against a fixture and the rest needs no network
at all.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger(__name__)

#: How long the whole read may take. A company site that has not painted in
#: twenty seconds is a company site the person is better off being told about
#: than waited on — onboarding is a few screens, not a job queue.
TIMEOUT_MS = 20_000
HTTP_TIMEOUT = 10.0

#: Desktop, because that is where a marketing site states its design most
#: fully; a mobile viewport hides the navigation and half the type scale.
VIEWPORT = {"width": 1440, "height": 900}

#: A browser's own identity. Sent because a default Playwright UA is refused
#: by enough CDNs to make the fallback the common path rather than the rare
#: one, and being refused is not a fact about the company's design.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


class SiteUnreadable(Exception):
    """The site could not be read. The message is shown to the person."""


@dataclass
class ColorUse:
    """One colour and the jobs the page was using it for.

    The role matters more than the count. `#1B7F5A` seen 400 times as text is
    a body colour; seen 6 times as a button's background it is the brand, and
    a frequency-only reading picks the wrong one every time.
    """

    hex: str
    #: role -> how many elements used it that way. Roles are the ones
    #: `design.py` knows how to read: `text`, `background`, `border`,
    #: `action_bg`, `action_text`, `link`, `heading`.
    roles: Counter = field(default_factory=Counter)

    @property
    def total(self) -> int:
        return sum(self.roles.values())


@dataclass
class Reading:
    """Everything one read of one site produced."""

    url: str
    #: False when the fallback produced this — a thinner read, and the
    #: profile says so rather than presenting it as the same thing.
    rendered: bool = False
    title: str = ""
    description: str = ""
    site_name: str = ""
    #: The visible words, trimmed. What `identity.py` reads.
    text: str = ""
    colors: dict[str, ColorUse] = field(default_factory=dict)
    #: font-family declaration -> element count, most used first when read.
    fonts: Counter = field(default_factory=Counter)
    #: The same, restricted to headings — a site often sets display type
    #: separately, and a single "body font" answer loses that.
    heading_fonts: Counter = field(default_factory=Counter)
    radii: Counter = field(default_factory=Counter)
    font_sizes: Counter = field(default_factory=Counter)
    shadows: Counter = field(default_factory=Counter)
    #: Absolute URLs, best candidate first.
    logo_candidates: list[str] = field(default_factory=list)
    #: PNG bytes of the top of the page, when a browser produced this. Handed
    #: to the identity pass so a model can see what the words are wrapped in.
    screenshot: bytes | None = None

    def note(self, value: str, role: str) -> None:
        """Record one element using one colour for one job."""
        norm = _normalise_color(value)
        if norm is None:
            return
        self.colors.setdefault(norm, ColorUse(hex=norm)).roles[role] += 1


# --------------------------------------------------------------------------- #
# colour normalisation
# --------------------------------------------------------------------------- #

_RGB = re.compile(
    r"rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)\s*(?:[,/]\s*([\d.]+)\s*)?\)")
_HEX = re.compile(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b")


def _normalise_color(value: str) -> str | None:
    """`rgb(27, 127, 90)` / `#1b7f5a` / `#1B7` -> `#1B7F5A`, else None.

    Transparent and near-transparent values are dropped rather than recorded
    as black: `rgba(0,0,0,0)` is the computed background of most elements on
    most pages, and counting it would make black the ground of every site on
    the internet.
    """
    v = (value or "").strip()
    if not v or v in ("transparent", "none", "currentcolor", "inherit"):
        return None
    m = _RGB.match(v)
    if m:
        alpha = float(m.group(4)) if m.group(4) is not None else 1.0
        if alpha < 0.5:
            return None
        r, g, b = (int(round(float(m.group(i)))) for i in (1, 2, 3))
        return f"#{r:02X}{g:02X}{b:02X}"
    m = _HEX.match(v)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return f"#{h.upper()}"
    return None


# --------------------------------------------------------------------------- #
# the rendered read
# --------------------------------------------------------------------------- #

#: Runs inside the page. Returns a census rather than a conclusion; keeping
#: the judgement out of the browser is what makes `design.py` testable from a
#: fixture with no network in the process.
#:
#: Bounded at 1,500 elements: a census is a distribution, and the distribution
#: of a marketing page is settled long before its footer link list.
_CENSUS_JS = """
() => {
  const out = { colors: [], fonts: [], headingFonts: [], radii: [],
                fontSizes: [], shadows: [], logos: [], text: '' };
  const seen = new Set();
  const nodes = Array.from(document.body.querySelectorAll('*')).slice(0, 1500);

  const visible = (el, cs) => {
    if (cs.visibility === 'hidden' || cs.display === 'none') return false;
    if (parseFloat(cs.opacity || '1') < 0.1) return false;
    const r = el.getBoundingClientRect();
    return r.width > 2 && r.height > 2;
  };

  for (const el of nodes) {
    const cs = getComputedStyle(el);
    if (!visible(el, cs)) continue;
    const tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role') || '';
    const heading = /^h[1-3]$/.test(tag);
    // A "call to action" is the element whose background states the brand.
    // Buttons and anything the page itself calls a button; a bare link is
    // recorded separately because its COLOUR, not its background, is brand.
    const action = tag === 'button' || role === 'button' ||
                   (el.getAttribute('type') || '') === 'submit' ||
                   /\\b(btn|button|cta)\\b/i.test(el.className || '');

    out.colors.push([cs.backgroundColor, action ? 'action_bg' : 'background']);
    out.colors.push([cs.color, action ? 'action_text'
                               : heading ? 'heading'
                               : tag === 'a' ? 'link' : 'text']);
    if (parseFloat(cs.borderTopWidth || '0') > 0)
      out.colors.push([cs.borderTopColor, 'border']);

    out.fonts.push(cs.fontFamily);
    if (heading) out.headingFonts.push(cs.fontFamily);
    if (action || tag === 'input' || /\\bcard\\b/i.test(el.className || ''))
      out.radii.push(cs.borderRadius);
    if (heading || tag === 'p') out.fontSizes.push(cs.fontSize);
    if (cs.boxShadow && cs.boxShadow !== 'none') out.shadows.push(cs.boxShadow);
  }

  // The mark, best candidate first. A file whose name says logo beats one
  // sitting in the header, which beats the social preview image — og:image
  // is very often a screenshot of the product rather than the mark.
  const abs = (u) => { try { return new URL(u, location.href).href; } catch { return null; } };
  const push = (u) => { const a = u && abs(u); if (a && !seen.has(a)) { seen.add(a); out.logos.push(a); } };
  for (const img of document.querySelectorAll('img, svg image')) {
    const src = img.getAttribute('src') || '';
    const alt = (img.getAttribute('alt') || '') + ' ' + (img.className || '');
    if (/logo|wordmark|brandmark/i.test(src) || /logo|wordmark/i.test(alt)) push(src);
  }
  for (const img of document.querySelectorAll('header img, nav img, [class*=header] img, [class*=navbar] img'))
    push(img.getAttribute('src'));
  const og = document.querySelector('meta[property="og:image"]');
  if (og) push(og.getAttribute('content'));
  for (const sel of ['link[rel="apple-touch-icon"]', 'link[rel="icon"]', 'link[rel="shortcut icon"]'])
    for (const l of document.querySelectorAll(sel)) push(l.getAttribute('href'));

  out.text = (document.body.innerText || '').replace(/\\n{3,}/g, '\\n\\n').slice(0, 12000);
  return out;
}
"""


async def _read_rendered(url: str) -> Reading:
    from playwright.async_api import async_playwright

    reading = Reading(url=url, rendered=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        try:
            context = await browser.new_context(
                viewport=VIEWPORT, user_agent=USER_AGENT)
            page = await context.new_page()
            try:
                # `domcontentloaded` rather than `networkidle`: a marketing
                # site with a chat widget or an analytics beacon never goes
                # idle, and the design is painted long before it would.
                await page.goto(url, wait_until="domcontentloaded",
                                timeout=TIMEOUT_MS)
                # Webfonts and above-the-fold images decide half the census,
                # and neither has landed at DOMContentLoaded.
                await page.wait_for_timeout(2500)

                reading.title = (await page.title()) or ""
                reading.description = await _meta(page, "description")
                reading.site_name = await _meta(page, "og:site_name")

                census = await page.evaluate(_CENSUS_JS)
                _absorb(reading, census)

                try:
                    reading.screenshot = await page.screenshot(
                        type="png", clip={"x": 0, "y": 0, **VIEWPORT})
                except Exception:  # noqa: BLE001 — a picture is a bonus
                    logger.debug("[brand] screenshot failed for %s", url)
            finally:
                await context.close()
        finally:
            await browser.close()
    return reading


async def _meta(page, name: str) -> str:
    """A meta tag's content by `property` or `name`, or ""."""
    try:
        return (await page.evaluate(
            """(n) => {
                const el = document.querySelector(
                    `meta[property="${n}"]`) || document.querySelector(`meta[name="${n}"]`);
                return el ? (el.getAttribute('content') || '') : '';
            }""", name)) or ""
    except Exception:  # noqa: BLE001
        return ""


def _absorb(reading: Reading, census: dict) -> None:
    for value, role in census.get("colors") or []:
        reading.note(value, role)
    for family in census.get("fonts") or []:
        reading.fonts[_first_family(family)] += 1
    for family in census.get("headingFonts") or []:
        reading.heading_fonts[_first_family(family)] += 1
    for r in census.get("radii") or []:
        reading.radii[str(r).split()[0] if str(r).strip() else "0px"] += 1
    for s in census.get("fontSizes") or []:
        reading.font_sizes[str(s)] += 1
    for s in census.get("shadows") or []:
        reading.shadows[str(s)] += 1
    reading.logo_candidates = [u for u in (census.get("logos") or []) if u][:6]
    reading.text = str(census.get("text") or "")


#: `var(--x)` or `var(--x, Inter)` where a family should be.
_VAR_REF = re.compile(r"^var\(\s*--[^,)]+(?:,\s*(?P<fallback>[^)]+))?\)$", re.I)


def _first_family(declaration: str) -> str:
    """`"Inter", -apple-system, sans-serif` -> `Inter`.

    The first name is the one the site chose; the rest is the stack it falls
    back to, which is the same on every site and says nothing about anyone.

    A NAME, NEVER A REFERENCE TO ONE. A page built with Elementor (or any
    theme that keeps its type in custom properties) can hand back
    `var( --e-global-typography-text-font-family )` — the site pointing at
    its own token, which does not resolve for a reader who never loaded that
    stylesheet. Recorded as a family, it was shown to a new customer during
    onboarding as the font their company uses. The fallback inside the
    reference IS a name and is taken (`var(--brand, Inter)` -> `Inter`);
    a reference with nothing behind it means this page told us no typeface,
    which is what "sans-serif" says here.
    """
    text = str(declaration or "").strip()
    reference = _VAR_REF.match(text)
    if reference:
        text = (reference.group("fallback") or "").strip()
    first = text.split(",")[0].strip().strip("\"'")
    if first.startswith("--") or "var(" in first.lower():
        return "sans-serif"
    return first or "sans-serif"


# --------------------------------------------------------------------------- #
# the fallback read
# --------------------------------------------------------------------------- #

_TAG = re.compile(r"<(script|style|noscript|svg)\b.*?</\1>", re.S | re.I)
_ANY_TAG = re.compile(r"<[^>]+>")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_FONT_FAMILY = re.compile(r"font-family\s*:\s*([^;}\"']+)", re.I)
_THEME_COLOR = re.compile(
    r'<meta[^>]+name=["\']theme-color["\'][^>]+content=["\']([^"\']+)', re.I)
_RADIUS = re.compile(r"border-radius\s*:\s*([\d.]+(?:px|rem|em))", re.I)


def _meta_content(html: str, key: str) -> str:
    for attr in ("property", "name"):
        m = re.search(
            rf'<meta[^>]+{attr}=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']*)',
            html, re.I)
        if m:
            return m.group(1).strip()
        m = re.search(
            rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+{attr}=["\']{re.escape(key)}["\']',
            html, re.I)
        if m:
            return m.group(1).strip()
    return ""


def _read_source(url: str) -> Reading:
    """What the markup states outright, when no browser could run.

    Honest about being less: colours found here are recorded under the
    `background` role only when the site declared a `theme-color` (which is a
    statement of brand), and otherwise counted as unroled literals. `design.py`
    reads them accordingly.
    """
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=True,
                          headers={"User-Agent": USER_AGENT}) as client:
            resp = client.get(url)
            if resp.status_code >= 400:
                raise SiteUnreadable(
                    f"{url} answered {resp.status_code}. Check the address, "
                    f"or skip this for now and add it later from Settings.")
            html = resp.text
    except httpx.RequestError as exc:
        raise SiteUnreadable(
            f"Could not reach {url} ({exc.__class__.__name__}). Check the "
            f"address, or skip this for now and add it later from Settings."
        ) from exc

    reading = Reading(url=url, rendered=False)
    m = _TITLE.search(html)
    reading.title = _ANY_TAG.sub("", m.group(1)).strip() if m else ""
    reading.description = (_meta_content(html, "description")
                           or _meta_content(html, "og:description"))
    reading.site_name = _meta_content(html, "og:site_name")

    theme = _THEME_COLOR.search(html)
    if theme:
        # A theme-color is the one colour a site declares ABOUT ITSELF, so it
        # is the strongest single signal the source carries.
        reading.note(theme.group(1), "action_bg")
    for value in _HEX.findall(html)[:400]:
        reading.note(f"#{value}", "background")
    for decl in _FONT_FAMILY.findall(html)[:200]:
        reading.fonts[_first_family(decl)] += 1
    for radius in _RADIUS.findall(html)[:200]:
        reading.radii[radius] += 1

    og = _meta_content(html, "og:image")
    candidates = []
    for pattern in (r'<link[^>]+rel=["\'](?:apple-touch-icon|icon|shortcut icon)["\'][^>]+href=["\']([^"\']+)',
                    r'<img[^>]+src=["\']([^"\']*logo[^"\']*)["\']'):
        candidates.extend(re.findall(pattern, html, re.I))
    if og:
        candidates.append(og)
    reading.logo_candidates = [urljoin(url, c) for c in candidates if c][:6]

    body = _TAG.sub(" ", html)
    reading.text = re.sub(r"\s{2,}", " ", _ANY_TAG.sub(" ", body)).strip()[:12000]
    return reading


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #

def normalise_url(raw: str) -> str:
    """`acme.com` -> `https://acme.com`. Raises on anything that is not a site.

    Refuses non-HTTP schemes and bare hostnames that resolve to the machine
    this runs on: the URL comes from a form, and a form that will fetch
    whatever it is given is a way to read the platform's own network from
    outside it.
    """
    value = (raw or "").strip()
    if not value:
        raise SiteUnreadable("Enter your company's web address first.")
    if "://" not in value:
        value = "https://" + value
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        raise SiteUnreadable("That needs to be a web address starting http or https.")
    host = (parsed.hostname or "").lower()
    if not host or "." not in host:
        raise SiteUnreadable(f"{raw!r} does not look like a web address.")
    if host in ("localhost", "0.0.0.0", "127.0.0.1", "::1") \
            or host.endswith(".localhost") or host.endswith(".internal"):
        raise SiteUnreadable("That address points back at this machine, not at a website.")
    if re.match(r"^(10|127)\.|^192\.168\.|^169\.254\.|^172\.(1[6-9]|2\d|3[01])\.", host):
        raise SiteUnreadable("That address is on a private network, not a website.")
    return value


async def read(url: str) -> Reading:
    """Read the site, preferring a real render. Raises `SiteUnreadable`.

    The fallback runs on any browser failure, not only on a missing install: a
    site that refuses headless Chromium, a navigation timeout and a crashed
    browser all leave the person in the same position, and the source read
    still produces something worth showing them.
    """
    target = normalise_url(url)
    try:
        reading = await _read_rendered(target)
        if reading.colors:
            return reading
        logger.info("[brand] %s rendered with no colours; reading the source", target)
    except ImportError:
        logger.info("[brand] playwright not installed; reading the source of %s", target)
    except Exception as exc:  # noqa: BLE001 — every browser failure falls back
        logger.info("[brand] render failed for %s (%s); reading the source",
                    target, exc.__class__.__name__)
    return await asyncio.to_thread(_read_source, target)


async def fetch_logo(candidates: list[str], *, limit: int = 4
                     ) -> tuple[bytes, str, str] | None:
    """`(bytes, media_type, url)` for the first candidate that is an image.

    Tried in the order `site.py` ranked them, so a file named `logo.svg`
    beats the social preview card. A candidate that is not an image, is
    enormous, or cannot be fetched is skipped rather than fatal — a company
    with no readable mark still has a design language.
    """
    from services import brand_logo

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True,
                                 headers={"User-Agent": USER_AGENT}) as client:
        for url in (candidates or [])[:limit]:
            try:
                resp = await client.get(url)
            except httpx.RequestError:
                continue
            if resp.status_code >= 400 or not resp.content:
                continue
            media = (resp.headers.get("content-type") or "").split(";")[0].strip()
            try:
                media = brand_logo.media_type(urlparse(url).path, media)
            except Exception:  # noqa: BLE001 — not an image we can ship
                continue
            if len(resp.content) > brand_logo.MAX_BYTES:
                continue
            return resp.content, media, url
    return None
