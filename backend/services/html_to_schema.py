"""HTML → PageV2 schema, through the same transformer the Figma JSX takes.

:mod:`services.jsx_to_schema` classifies an element tree by tag, ``className``
and ``data-name`` (its ``_transform_node``). Figma's Dev Mode writes that
vocabulary directly; a UX Pilot design arrives as HTML with either Tailwind
utilities or plain CSS. This module builds the same :class:`JSXElement` tree
from HTML — mapping semantic tags onto the composites the transformer knows
(``<button>`` → ``data-name="Button"``, ``<h2>`` → ``Heading 2``) and
translating the layout declarations that matter (``display:flex``,
``flex-direction``, ``gap``, ``grid-template-columns``) into the utility
classes the transformer's layout branches read — so one element mapping
serves both providers.

Also measures the design's vocabulary (:func:`tokens_from_html`) and lists
the remote assets it references (:func:`extract_html_asset_urls`) for the
downloader.
"""
from __future__ import annotations

import re
import uuid as _uuid
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from services.jsx_to_schema import JSXElement, _rewrite_asset_paths, _state, _transform_node

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
         "meta", "param", "source", "track", "wbr"}
#: Dropped with their content.
_SKIP = {"script", "style", "head", "meta", "link", "title", "noscript", "template"}
#: Rendered as text (the transformer's <p> branch): descendant text becomes
#: one Text/Heading node.
_TEXT_TAGS = {"p", "span", "li", "td", "th", "strong", "em", "b", "i", "small",
              "blockquote", "figcaption", "dt", "dd", "pre", "code", "time"}
#: Kept as leaves — a vector icon is a box, not a subtree of Containers.
_LEAF = {"svg", "video", "canvas", "iframe"}
#: Opening one of these implicitly closes an open sibling of the listed kinds
#: (HTML lets authors omit the end tag; the tree must not nest them).
_AUTO_CLOSE = {"p": {"p"}, "li": {"li"}, "td": {"td", "th"}, "th": {"td", "th"},
               "tr": {"tr"}, "option": {"option"}, "dt": {"dt", "dd"}, "dd": {"dt", "dd"}}

_INPUT_NAME_BY_TYPE = {
    "email": "Email Input",
    "password": "Password Input",
    "search": "Search Input",
    "checkbox": "Checkbox",
}

_WS_RE = re.compile(r"\s+")


def _camel(prop: str) -> str:
    parts = prop.strip().lower().split("-")
    return parts[0] + "".join(p.capitalize() for p in parts[1:] if p)


def parse_style(style: str | None) -> dict[str, str]:
    """``"color: #fff; font-size: 14px"`` → ``{"color": "#fff", "fontSize": "14px"}``."""
    out: dict[str, str] = {}
    for decl in (style or "").split(";"):
        if ":" not in decl:
            continue
        k, v = decl.split(":", 1)
        k, v = k.strip(), v.strip()
        if k and v:
            out[_camel(k)] = v
    return out


_PX_RE = re.compile(r"^(-?\d+(?:\.\d+)?)px$")
_REPEAT_RE = re.compile(r"repeat\(\s*(\d+)\s*,")


def layout_classes(style: dict[str, str]) -> list[str]:
    """The Tailwind utilities the transformer's layout branches read, derived
    from plain-CSS declarations. Nothing else is translated: colours and
    type stay on ``style`` and pass through untouched."""
    classes: list[str] = []
    display = (style.get("display") or "").strip().lower()
    direction = (style.get("flexDirection") or "").strip().lower()
    if display in ("flex", "inline-flex"):
        classes.append("flex")
        if direction.startswith("column"):
            classes.append("flex-col")
    elif display in ("grid", "inline-grid"):
        classes.append("grid")
        cols = style.get("gridTemplateColumns") or ""
        m = _REPEAT_RE.search(cols)
        n = int(m.group(1)) if m else len([t for t in cols.split() if t]) if cols else 0
        if n:
            classes.append(f"grid-cols-{n}")
    gap = style.get("gap") or style.get("columnGap") or style.get("rowGap")
    if gap:
        first = gap.split()[0]
        if _PX_RE.match(first):
            classes.append(f"gap-[{first}]")
    return classes


class _Rule:
    __slots__ = ("cls", "decls")

    def __init__(self, cls: str, decls: dict[str, str]):
        self.cls = cls
        self.decls = decls


_RULE_RE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def parse_stylesheet(css: str) -> list[_Rule]:
    """Single-class rules only (``.card { ... }``). Compound and descendant
    selectors are ignored: this is a bridge for layout hints, not a CSS
    engine."""
    rules: list[_Rule] = []
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for sel, body in _RULE_RE.findall(css):
        for part in sel.split(","):
            part = part.strip()
            if re.fullmatch(r"\.[A-Za-z_][\w-]*", part):
                rules.append(_Rule(part[1:], parse_style(body)))
    return rules


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = JSXElement("div", {"className": "flex flex-col"}, [])
        self.body: JSXElement | None = None
        self._stack: list[JSXElement] = [self.root]
        self._skip_depth = 0
        self._skip_tag: str | None = None
        self.style_blocks: list[str] = []
        self._in_style = False

    # -- helpers --------------------------------------------------------
    def _top(self) -> JSXElement:
        return self._stack[-1]

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "style":
            # Collected wherever it sits — usually inside a skipped <head>.
            self._in_style = True
        if self._skip_depth:
            if tag == self._skip_tag and tag not in _VOID:
                self._skip_depth += 1
            return
        if tag in _SKIP:
            if tag not in _VOID:
                self._skip_depth = 1
                self._skip_tag = tag
            return
        if tag in ("html",):
            return
        closes = _AUTO_CLOSE.get(tag)
        if closes and len(self._stack) > 1 and self._top().attrs.get("data-tag") in closes:
            self._stack.pop()
        attrs = {k.lower(): (v if v is not None else "") for k, v in attrs_list}
        el = _element_for(tag, attrs)
        if tag == "body":
            self.body = el
        self._top().children.append(el)
        if tag in _VOID or tag == "br":
            return
        self._stack.append(el)
        if tag in _LEAF:
            # children of a leaf are dropped
            self._skip_depth = 1
            self._skip_tag = tag
            self._stack.pop()

    def handle_startendtag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs_list)
        if tag.lower() not in _VOID and tag.lower() not in _LEAF and not self._skip_depth:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "style":
            self._in_style = False
        if self._skip_depth:
            if tag == self._skip_tag:
                self._skip_depth -= 1
                if self._skip_depth == 0:
                    self._skip_tag = None
            return
        if tag in _VOID or tag in ("html", "br"):
            return
        # Pop to the matching open element, tolerating unclosed tags.
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].attrs.get("data-tag") == tag or self._stack[i].tag == tag:
                del self._stack[i:]
                return

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self.style_blocks.append(data)
            return
        if self._skip_depth:
            return
        text = _WS_RE.sub(" ", data)
        if text.strip():
            self._top().children.append(text.strip() if len(self._top().children) == 0 else text.strip())


def _element_for(tag: str, attrs: dict[str, str]) -> JSXElement:
    """Map one HTML start tag onto the vocabulary the JSX transformer reads."""
    out: dict[str, Any] = {}
    class_names = attrs.get("class", "").split()
    style = parse_style(attrs.get("style"))
    for k, v in attrs.items():
        if k.startswith("data-") or k in ("src", "alt", "href", "placeholder", "type", "name", "value"):
            out[k] = v
    out["data-tag"] = tag
    jsx_tag = "div"

    m = re.fullmatch(r"h([1-6])", tag)
    if m:
        out["data-name"] = f"Heading {m.group(1)}"
        # The transformer reads the heading's size classes off an inner <p>.
        el = JSXElement("div", out, [])
        inner = JSXElement("p", {"className": " ".join(class_names)} if class_names else {}, [])
        el.children.append(inner)
        _finish(el, class_names, style)
        el.children = [inner]
        inner_holder = el
        # Text will be appended to the outer element by the parser; move it
        # into the inner <p> at transform time (see _hoist_heading_text).
        return inner_holder
    if tag == "img":
        return _finish(JSXElement("img", out, []), class_names, style)
    if tag == "button" or (tag == "input" and attrs.get("type", "").lower() in ("submit", "button")):
        out["data-name"] = "Button"
        if tag == "input" and attrs.get("value"):
            return _finish(JSXElement("div", out, [attrs["value"]]), class_names, style)
    elif tag == "a":
        out["data-name"] = "Link"
    elif tag == "input":
        out["data-name"] = _INPUT_NAME_BY_TYPE.get(attrs.get("type", "text").lower(), "Input")
        ph = attrs.get("placeholder") or attrs.get("aria-label") or ""
        return _finish(JSXElement("div", out, [ph] if ph else []), class_names, style)
    elif tag in ("textarea", "select"):
        out["data-name"] = "Input"
        ph = attrs.get("placeholder") or ""
        el = JSXElement("div", out, [ph] if ph else [])
        return _finish(el, class_names, style)
    elif tag == "form":
        out["data-name"] = attrs.get("data-name") or "Form"
    elif tag == "label":
        out["data-name"] = "Primitive.label"
    elif tag in _TEXT_TAGS:
        jsx_tag = "p"
    elif tag in _LEAF:
        jsx_tag = tag
    return _finish(JSXElement(jsx_tag, out, []), class_names, style)


def _finish(el: JSXElement, class_names: list[str], style: dict[str, str]) -> JSXElement:
    classes = list(class_names) + [c for c in layout_classes(style) if c not in class_names]
    if classes:
        el.attrs["className"] = " ".join(classes)
    if style:
        el.attrs["style"] = style
    return el


def _apply_stylesheet(el: JSXElement, rules: list[_Rule]) -> None:
    """Merge single-class rule declarations into elements carrying the class,
    then derive layout utilities from the merged style. Inline style wins."""
    if not rules:
        return
    by_cls: dict[str, dict[str, str]] = {}
    for r in rules:
        by_cls.setdefault(r.cls, {}).update(r.decls)

    def _walk(node: Any) -> None:
        if not isinstance(node, JSXElement):
            return
        cn = node.attrs.get("className", "")
        names = cn.split() if cn else []
        merged: dict[str, str] = {}
        for n in names:
            if n in by_cls:
                merged.update(by_cls[n])
        if merged:
            inline = node.attrs.get("style") or {}
            merged.update(inline)
            node.attrs["style"] = merged
            for c in layout_classes(merged):
                if c not in names:
                    names.append(c)
            node.attrs["className"] = " ".join(names)
        for c in node.children:
            _walk(c)

    _walk(el)


def _hoist_heading_text(node: Any) -> None:
    """A heading's text lands on the wrapper; the transformer reads it from
    the inner <p>. Move it."""
    if not isinstance(node, JSXElement):
        return
    dn = node.attrs.get("data-name", "")
    if dn.startswith("Heading ") and node.children and isinstance(node.children[0], JSXElement) \
            and node.children[0].tag == "p":
        inner = node.children[0]
        rest = node.children[1:]
        inner.children.extend(c for c in rest if not (isinstance(c, JSXElement) and c is inner))
        node.children = [inner]
    for c in node.children:
        _hoist_heading_text(c)


def parse_html_tree(html: str) -> tuple[JSXElement, list[str]]:
    """Parse HTML into the JSXElement tree the transformer takes. Returns the
    root element and the raw <style> blocks (for token measurement)."""
    b = _Builder()
    b.feed(html)
    b.close()
    root = b.body if b.body is not None else b.root
    # Mirror the JSX convention: a single wrapper child is the root.
    kids = [c for c in root.children if isinstance(c, JSXElement)]
    texts = [c for c in root.children if not isinstance(c, JSXElement)]
    if len(kids) == 1 and not texts:
        root = kids[0]
    elif root is b.body:
        root = JSXElement("div", {"className": "flex flex-col", "data-tag": "body"}, root.children)
    rules = parse_stylesheet("\n".join(b.style_blocks))
    _apply_stylesheet(root, rules)
    _hoist_heading_text(root)
    return root, b.style_blocks


def transform_html_to_schema(
    html: str,
    asset_paths: dict[str, str] | None = None,
    *,
    title: str = "Design Import",
) -> dict:
    """HTML → PageV2 dict, the same shape ``transform_jsx_to_schema`` returns.
    When ``asset_paths`` maps remote URLs to local paths, every matching
    ``src`` is rewritten."""
    root_element, _ = parse_html_tree(html)
    # The transformer keeps per-call state (the page's first heading, the
    # section it is in, canvas mode) on a thread-local that
    # `transform_jsx_to_schema` initialises; the HTML front end has to set the
    # same fields, or the first `<p>` it meets raises on a missing attribute.
    _state.root = root_element
    _state.canvas_mode = False
    _state.canvas_fit = "scale"
    _state.in_drawing = False
    _state.heading = ""
    _state.section = ""
    try:
        root_node = _transform_node(root_element)
    finally:
        _state.canvas_mode = False
        _state.canvas_fit = "scale"
        _state.in_drawing = False
        _state.heading = ""
        _state.section = ""
        _state.root = None
    schema: dict = {
        "schemaVersion": "2.0",
        "id": str(_uuid.uuid4()),
        "title": title,
        "dataSources": [],
        "children": [root_node] if root_node is not None else [],
    }
    if asset_paths:
        for child in schema["children"]:
            _rewrite_asset_paths(child, asset_paths)
    return schema


# ---------------------------------------------------------------------------
# Assets + tokens
# ---------------------------------------------------------------------------

_SRC_RE = re.compile(r"""(?:src|href)\s*=\s*["'](https?://[^"'\s>]+)["']""", re.I)
_CSS_URL_RE = re.compile(r"""url\(\s*["']?(https?://[^"')\s]+)["']?\s*\)""", re.I)
_IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif")


def extract_html_asset_urls(html: str) -> list[str]:
    """Remote image URLs the markup references (img src, css url()). Sorted,
    deduplicated. Stylesheet and script hrefs are not assets."""
    found: set[str] = set()
    for m in _SRC_RE.finditer(html):
        url = m.group(1)
        path = url.split("?", 1)[0].lower()
        if path.endswith(_IMG_EXT) or "/image" in path or "/asset" in path or "/img" in path:
            found.add(url)
    for m in _CSS_URL_RE.finditer(html):
        found.add(m.group(1))
    return sorted(found)


_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b")
_FONT_FAMILY_RE = re.compile(r"""font-family\s*:\s*(?:"([^"]*)"|'([^']*)'|([^;}"']+))""", re.I)
_FONT_SIZE_RE = re.compile(r"font-size\s*:\s*(\d+(?:\.\d+)?)px", re.I)
_RADIUS_RE = re.compile(r"border(?:-[a-z-]+)?-radius\s*:\s*(\d+(?:\.\d+)?)px", re.I)
_SPACING_RE = re.compile(r"(?:gap|padding(?:-[a-z]+)?|margin(?:-[a-z]+)?)\s*:\s*((?:\d+(?:\.\d+)?px\s*){1,4})", re.I)
_TW_TEXT_PX_RE = re.compile(r"\btext-\[(\d+(?:\.\d+)?)px\]")
_TW_ROUNDED_PX_RE = re.compile(r"\brounded(?:-[a-z]+)?-\[(\d+(?:\.\d+)?)px\]")
_TW_SPACE_PX_RE = re.compile(r"\b(?:gap|p|px|py|pt|pb|pl|pr|m|mx|my|mt|mb|ml|mr|space-[xy])-\[(\d+(?:\.\d+)?)px\]")
_TW_FONT_RE = re.compile(r"\bfont-\[['\"]?([A-Za-z][A-Za-z0-9 _]*?)['\"]?\]")
_GENERIC_FONTS = {"sans-serif", "serif", "monospace", "system-ui", "inherit", "initial",
                  "ui-sans-serif", "ui-serif", "ui-monospace", "cursive", "fantasy"}


def _norm_hex(h: str) -> str:
    v = h[1:]
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    return "#" + v.upper()


def tokens_from_html(html: str) -> "MeasuredTokens":
    """Measure the design's vocabulary from its markup: every hex colour,
    font family, font size, radius and spacing declared inline, in <style>
    blocks, or as Tailwind arbitrary values."""
    colors = {_norm_hex(m.group(0)) for m in _HEX_RE.finditer(html)}
    fonts: set[str] = set()
    for m in _FONT_FAMILY_RE.finditer(html):
        raw = next((g for g in m.groups() if g), "")
        first = raw.split(",")[0].strip().strip("'\"")
        if first and first.lower() not in _GENERIC_FONTS and not first.startswith("var("):
            fonts.add(first)
    for m in _TW_FONT_RE.finditer(html):
        fonts.add(m.group(1).strip())
    sizes = {float(m.group(1)) for m in _FONT_SIZE_RE.finditer(html)}
    sizes |= {float(m.group(1)) for m in _TW_TEXT_PX_RE.finditer(html)}
    radii = {float(m.group(1)) for m in _RADIUS_RE.finditer(html) if float(m.group(1)) > 0}
    radii |= {float(m.group(1)) for m in _TW_ROUNDED_PX_RE.finditer(html) if float(m.group(1)) > 0}
    spacings: set[float] = set()
    for m in _SPACING_RE.finditer(html):
        for part in m.group(1).split():
            v = float(part[:-2])
            if v > 0:
                spacings.add(v)
    spacings |= {float(m.group(1)) for m in _TW_SPACE_PX_RE.finditer(html) if float(m.group(1)) > 0}
    return MeasuredTokens(
        colors=tuple(sorted(colors)),
        fonts=tuple(sorted(fonts)),
        font_sizes=tuple(sorted(sizes)),
        border_radii=tuple(sorted(radii)),
        spacings=tuple(sorted(spacings)),
    )


@dataclass(frozen=True)
class MeasuredTokens:
    """What :func:`tokens_from_html` counted. Raw values, no roles."""

    colors: tuple[str, ...] = ()
    fonts: tuple[str, ...] = ()
    font_sizes: tuple[float, ...] = ()
    border_radii: tuple[float, ...] = ()
    spacings: tuple[float, ...] = ()
