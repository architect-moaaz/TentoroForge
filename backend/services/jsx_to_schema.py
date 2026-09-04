"""Minimal JSX parser tailored to Figma MCP get_design_context output.

The output format is restricted: regular HTML-like tags, className strings,
inline style={{...}} objects, no JSX expressions other than {imgVar} src
interpolations. A recursive-descent tokenizer handles it without needing
a full JS AST parser.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class JSXElement:
    tag: str
    attrs: dict[str, Any] = field(default_factory=dict)
    children: list[Any] = field(default_factory=list)

    def find_descendant(self, predicate: Callable) -> "JSXElement | None":
        if predicate(self):
            return self
        for c in self.children:
            if isinstance(c, JSXElement):
                hit = c.find_descendant(predicate)
                if hit:
                    return hit
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_jsx_tree(source: str) -> JSXElement:
    """Parse the FIRST JSX expression in `source`.

    Resolves {varName} src interpolations against module-level const
    declarations.
    """
    consts = _extract_consts(source)
    jsx_src = _find_jsx_root(source)
    parser = _Parser(jsx_src, consts)
    return parser.parse_element()


# ---------------------------------------------------------------------------
# Pass 1: extract module-level const declarations
# ---------------------------------------------------------------------------

_CONST_RE = re.compile(
    r'^\s*const\s+(\w+)\s*=\s*"([^"]*)"',
    re.MULTILINE,
)


def _extract_consts(source: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in _CONST_RE.finditer(source)}


# ---------------------------------------------------------------------------
# Pass 2: locate the JSX root (first '<' after 'return (' or 'return <')
# ---------------------------------------------------------------------------

def _find_jsx_root(source: str) -> str:
    # Look for `return (` or `return<` patterns
    match = re.search(r'\breturn\s*\(?\s*(<)', source)
    if match:
        start = match.start(1)
        return source[start:]
    # Fallback: just find the first '<' that looks like a tag opening
    match = re.search(r'<[a-zA-Z]', source)
    if match:
        return source[match.start():]
    raise ValueError("No JSX root found in source")


# ---------------------------------------------------------------------------
# Pass 3: recursive-descent parser
# ---------------------------------------------------------------------------

class _Parser:
    def __init__(self, src: str, consts: dict[str, str]):
        self.src = src
        self.pos = 0
        self.consts = consts

    # ── character-level helpers ─────────────────────────────────────────────

    def _peek(self) -> str:
        return self.src[self.pos] if self.pos < len(self.src) else ""

    def _eof(self) -> bool:
        return self.pos >= len(self.src)

    def _skip_whitespace(self) -> None:
        while not self._eof() and self.src[self.pos] in " \t\n\r":
            self.pos += 1

    def _expect(self, ch: str) -> None:
        if self._eof() or self.src[self.pos] != ch:
            ctx = self.src[max(0, self.pos - 30): self.pos + 30]
            raise ValueError(f"Expected {ch!r} at pos {self.pos}, context: {ctx!r}")
        self.pos += 1

    # ── top-level element parser ────────────────────────────────────────────

    def parse_element(self) -> JSXElement:
        self._skip_whitespace()
        self._expect("<")

        # Read tag name: letters, digits, hyphens, dots
        tag = self._read_tag_name()

        # Read attributes
        attrs = self._read_attrs()

        self._skip_whitespace()

        # Self-closing?
        if self.src[self.pos: self.pos + 2] == "/>":
            self.pos += 2
            return JSXElement(tag=tag, attrs=attrs, children=[])

        # Opening tag close
        self._expect(">")

        # Read children until closing tag
        children = self._read_children(tag)

        return JSXElement(tag=tag, attrs=attrs, children=children)

    # ── tag name ────────────────────────────────────────────────────────────

    def _read_tag_name(self) -> str:
        start = self.pos
        while not self._eof() and self.src[self.pos] not in " \t\n\r/>":
            self.pos += 1
        return self.src[start: self.pos]

    # ── attributes ──────────────────────────────────────────────────────────

    def _read_attrs(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {}
        while True:
            self._skip_whitespace()
            # End of opening tag?
            if self._eof():
                break
            if self.src[self.pos: self.pos + 2] == "/>":
                break
            if self.src[self.pos] == ">":
                break

            # Read attribute name (may contain letters, digits, hyphens, dots, colons)
            name = self._read_attr_name()
            if not name:
                break

            self._skip_whitespace()
            if self._eof() or self.src[self.pos] != "=":
                # Boolean attribute (no value)
                attrs[name] = True
                continue

            self._expect("=")
            self._skip_whitespace()

            value = self._read_attr_value(name)
            attrs[name] = value

        return attrs

    def _read_attr_name(self) -> str:
        start = self.pos
        while not self._eof() and self.src[self.pos] not in " \t\n\r=/>":
            self.pos += 1
        return self.src[start: self.pos]

    def _read_attr_value(self, attr_name: str) -> Any:
        if self._eof():
            return ""
        ch = self.src[self.pos]

        if ch == '"':
            # Plain string value
            return self._read_quoted_string('"')
        elif ch == "'":
            return self._read_quoted_string("'")
        elif ch == "{":
            # JSX expression: could be {{ style object }} or { varName } or { `template` }
            return self._read_jsx_expr(attr_name)
        else:
            # Unquoted value (rare) — read until whitespace or >
            start = self.pos
            while not self._eof() and self.src[self.pos] not in " \t\n\r/>":
                self.pos += 1
            return self.src[start: self.pos]

    def _read_quoted_string(self, quote: str) -> str:
        self._expect(quote)
        start = self.pos
        while not self._eof() and self.src[self.pos] != quote:
            self.pos += 1
        value = self.src[start: self.pos]
        self._expect(quote)
        return value

    def _read_jsx_expr(self, attr_name: str) -> Any:
        """Read a JSX { ... } expression.

        Cases:
          {{ key: "val", ... }}  → style dict
          {varName}              → const lookup
          {`template`}           → template literal string
          {otherExpr}            → keep as marker string
        """
        self._expect("{")
        self._skip_whitespace()

        # Double-brace: style object {{ ... }}
        if not self._eof() and self.src[self.pos] == "{":
            return self._read_style_object()

        # Template literal
        if not self._eof() and self.src[self.pos] == "`":
            return self._read_template_literal_expr()

        # Plain identifier or other expression — read until balanced }
        start = self.pos
        depth = 1
        while not self._eof() and depth > 0:
            c = self.src[self.pos]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            self.pos += 1
        inner = self.src[start: self.pos].strip()
        self._expect("}")

        # Resolve identifier against consts
        if re.match(r'^\w+$', inner):
            return self.consts.get(inner, "")

        # Unknown expression: return as marker
        return "{" + inner + "}"

    def _read_style_object(self) -> dict[str, Any]:
        """Read {{ key: value, ... }} style object. pos is at the inner {."""
        self._expect("{")
        result: dict[str, Any] = {}

        while True:
            self._skip_whitespace()
            if self._eof():
                break
            if self.src[self.pos] == "}":
                break

            # Read key (camelCase identifier)
            key_start = self.pos
            while not self._eof() and self.src[self.pos] not in " \t\n\r:}":
                self.pos += 1
            key = self.src[key_start: self.pos].strip()
            if not key:
                break

            self._skip_whitespace()
            if self._eof() or self.src[self.pos] != ":":
                break
            self._expect(":")
            self._skip_whitespace()

            # Read value: string literal (may contain parens, commas, etc.)
            value = self._read_style_value()
            result[key] = value

            self._skip_whitespace()
            if not self._eof() and self.src[self.pos] == ",":
                self.pos += 1  # consume comma

        # Closing }} — inner } then outer }
        self._skip_whitespace()
        if not self._eof() and self.src[self.pos] == "}":
            self.pos += 1
        self._skip_whitespace()
        if not self._eof() and self.src[self.pos] == "}":
            self.pos += 1

        return result

    def _read_style_value(self) -> str:
        """Read a style property value. Handles quoted strings with nested parens."""
        if self._eof():
            return ""
        ch = self.src[self.pos]
        if ch in ('"', "'"):
            return self._read_quoted_string(ch)
        if ch == "`":
            return self._read_style_template()
        # Numeric or unquoted value — read until comma or }
        start = self.pos
        while not self._eof() and self.src[self.pos] not in ",}":
            self.pos += 1
        return self.src[start: self.pos].strip()

    def _read_style_template(self) -> str:
        """A `...` value inside a style object, with ${vars} resolved.

        `maskImage: `url("${imgGroup1}")`` was read by the unquoted branch,
        which stops at the first `,` or `}` — and the first `}` it meets is the
        one closing `${imgGroup1}`. The value stored was the fragment
        '`url("${imgGroup1' : not a URL, not valid CSS, and as a mask-image it
        hides the element it is applied to.

        That is why inline styles looked like something to strip. Eighty masks
        on one real dashboard, every one of them truncated, and applying them
        collapsed the page. Resolved against the same const table `src` already
        uses, they are what clips the design's shapes correctly.
        """
        self._expect("`")
        start = self.pos
        while not self._eof() and self.src[self.pos] != "`":
            self.pos += 1
        raw = self.src[start:self.pos]
        if not self._eof():
            self._expect("`")
        # ${name} -> the const's value, leaving an unknown name in place rather
        # than emitting an empty url() that would mask everything away.
        def sub(match):
            name = match.group(1).strip()
            return self.consts.get(name, match.group(0))

        return re.sub(r"\$\{([^}]*)\}", sub, raw)

    def _read_template_literal_expr(self) -> str:
        """Read a `...` template literal inside {}. pos is at the backtick."""
        self._expect("`")
        start = self.pos
        while not self._eof() and self.src[self.pos] != "`":
            self.pos += 1
        value = self.src[start: self.pos]
        self._expect("`")
        self._skip_whitespace()
        # consume closing }
        if not self._eof() and self.src[self.pos] == "}":
            self.pos += 1
        return value

    # ── children ────────────────────────────────────────────────────────────

    def _read_children(self, parent_tag: str) -> list[Any]:
        children: list[Any] = []

        while not self._eof():
            # Check for closing tag
            if self.src[self.pos: self.pos + 2] == "</":
                # Consume closing tag
                self.pos += 2
                # Skip tag name
                while not self._eof() and self.src[self.pos] not in " \t\n\r>":
                    self.pos += 1
                self._skip_whitespace()
                if not self._eof() and self.src[self.pos] == ">":
                    self.pos += 1
                break

            # Child element?
            if self.src[self.pos] == "<":
                # Check it's not a comment <!-- ... -->
                if self.src[self.pos: self.pos + 4] == "<!--":
                    # Skip HTML comment
                    end = self.src.find("-->", self.pos + 4)
                    if end == -1:
                        break
                    self.pos = end + 3
                    continue
                child = self.parse_element()
                children.append(child)
                continue

            # JSX expression child: {`template`} or {expr}
            if self.src[self.pos] == "{":
                text = self._read_child_expr()
                if text:
                    children.append(text)
                continue

            # Text content
            text = self._read_text()
            if text:
                children.append(text)

        return children

    def _read_text(self) -> str:
        """Read text until '<' or '{'."""
        start = self.pos
        while not self._eof() and self.src[self.pos] not in "<{":
            self.pos += 1
        return self.src[start: self.pos].strip()

    def _read_child_expr(self) -> str:
        """Read a JSX child expression {`...`} or {someExpr}."""
        self._expect("{")
        self._skip_whitespace()

        if not self._eof() and self.src[self.pos] == "`":
            # Template literal
            self._expect("`")
            start = self.pos
            while not self._eof() and self.src[self.pos] != "`":
                self.pos += 1
            value = self.src[start: self.pos]
            self._expect("`")
            self._skip_whitespace()
            if not self._eof() and self.src[self.pos] == "}":
                self.pos += 1
            return value

        # Generic expression: read until balanced }
        depth = 1
        start = self.pos
        while not self._eof() and depth > 0:
            c = self.src[self.pos]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    break
            self.pos += 1
        inner = self.src[start: self.pos].strip()
        if not self._eof() and self.src[self.pos] == "}":
            self.pos += 1
        # Don't emit empty or whitespace-only expressions
        return inner if inner else ""


# ---------------------------------------------------------------------------
# Transformer: JSXElement tree → PageV2 schema dict
# ---------------------------------------------------------------------------

import uuid as _uuid
from .figma_action_classifier import classify_button_action, infer_input_name
from .figma_llm_ctx import (
    figma_llm_enabled as _figma_llm_enabled,
    get_action_query_fn as _get_action_query_fn,
    get_routes as _get_routes,
    get_workflows as _get_workflows,
    reset_figma_llm_context,
    set_figma_llm_context,
)

# Back-compat alias so external callers can still read/write the raw dict.
from .figma_llm_ctx import _CTX as _FIGMA_LLM_CTX  # noqa: F401


def _classify_button_action_with_llm(
    label: str, data_name: str, class_name: str,
) -> dict:
    """Try the Wave 5 LLM classifier when enabled + context populated;
    fall back to the keyword classifier on ``none`` / disabled / empty.
    Registry-safety is enforced inside classify_figma_action_llm — the
    LLM cannot invent a target that isn't in the supplied lists.
    """
    if _figma_llm_enabled():
        routes = _get_routes()
        workflows = _get_workflows()
        if routes or workflows:
            try:
                from .figma_action_llm import classify_figma_action_llm
                binding = classify_figma_action_llm(
                    label,
                    surrounding_text=data_name,
                    available_routes=routes,
                    available_workflows=workflows,
                    query_fn=_get_action_query_fn(),
                )
                if binding.kind == "workflow" and binding.target:
                    return {"workflow": binding.target}
                if binding.kind == "navigate" and binding.target:
                    return {"navigate": binding.target}
                if binding.kind == "external" and binding.target:
                    # Button schema has no `href` prop; skip and let the
                    # keyword classifier handle it as a workflow name.
                    pass
            except Exception:  # noqa: BLE001
                # LLM path is best-effort — never break the transform.
                pass
    return classify_button_action(label, data_name=data_name, className=class_name)

# ---------------------------------------------------------------------------
# Position-class filter
# ---------------------------------------------------------------------------

# Patterns matching Tailwind utilities that encode absolute positioning.
# Split on whitespace then test each token individually.
_POSITION_PATTERNS: list[re.Pattern] = [
    # Position keywords
    re.compile(r'^(absolute|relative|fixed|sticky)$'),
    # Directional offsets: left-*, top-*, right-*, bottom-* (including arbitrary values)
    re.compile(r'^(left|top|right|bottom)-'),
    # Inset shorthands
    re.compile(r'^inset(-[xy])?-'),
    # Translate utilities
    re.compile(r'^translate-[xy]-'),
    re.compile(r'^translate-'),
    # Transform helpers
    re.compile(r'^transform(-|$)'),
    # Z-index
    re.compile(r'^z-'),
]

# Matches w-[Npx] or h-[Npx] — explicit pixel sizing used only for absolute layout.
_PX_SIZE_RE = re.compile(r'^[wh]-\[\d+px\]$')

# A retained explicit pixel WIDTH, which must be capped at the viewport.
_WIDTH_PX_RE = re.compile(r'(?:^| )w-\[\d+(?:\.\d+)?px\](?: |$)')

# Matches size-[Npx], w-[Npx], h-[Npx], w-[N.Mpx] — fixed pixel sizes that
# indicate a "decorative" node whose absolute children compose into a shape.
_FIXED_PX_SIZE_RE = re.compile(r'^(size|w|h)-\[\d+(\.\d+)?px\]$')

# Matches percentage-based offset / inset values used in Figma icon SVG layers:
#   inset-[8.33%], inset-[-5%], inset-[37.5%_37.5%_45.83%_37.5%], bottom-1/4, left-1/2 ...
# These are the telltale sign that absolute-positioning is composing overlapping layers.
_PCT_OFFSET_RE = re.compile(r'^(inset(-[xy])?|left|top|right|bottom)-(\[.*%|1/[234]|3/4|full)')

# leading-[0] collapses line-height to zero — a Figma Dev Mode artifact that
# causes text to overlap.  The child Text nodes already carry their own
# correct leading-[Npx] values so we can safely drop this from any wrapper.
_LEADING_ZERO_RE = re.compile(r'^leading-\[0(px)?\]$')


#: Canvas mode. A page built FROM a Figma frame is a fixed-size drawing, not a
#: flowed document: its nodes say `absolute inset-0 size-full` inside boxes that
#: the frame's own dimensions bound. Reflowing it has nothing to work with — one
#: real dashboard export carried 534 absolute nodes and five pixel offsets — so
#: in this mode every node keeps its composition and the root is given the
#: frame's true size. Set only by `transform_jsx_to_schema`, always restored.
_CANVAS_MODE = False


def _is_decorative_positioned(cn: str) -> bool:
    """Return True when a node is an absolutely-positioned COMPOSITION layer
    rather than a node abusing absolute for flow layout.

    Two shapes qualify: percentage-based offsets (inset-[%], left-1/2,
    top-[8.33%]) — Figma icon SVG layers — and fill-parent layers (inset-0,
    size-full), which is how Dev Mode expresses most of a frame.

    Percentage offsets are the hallmark of Figma icon SVG layers that compose
    overlapping vector shapes — they must be preserved or the icon fragments
    will no longer overlay correctly.  Pixel-offset absolute nodes (top-[74px],
    left-0) are flow-layout abuse and should still be stripped.
    """
    tokens = cn.split() if cn else []
    if not any(t in ("absolute", "fixed") for t in tokens):
        return False
    # On a sized canvas every absolute node is composition, because there is a
    # box for it to resolve against. That box is the whole difference: the same
    # `inset-0` that fills a frame fills nothing in a reflowed page, which is
    # why this is a mode and not a new default.
    #
    # EXCEPT A `contents` WRAPPER, WHICH HAS NO BOX TO BE. Figma wraps each
    # card in `absolute contents left-[x] top-[y]`, and `display: contents`
    # generates no box at all — so it cannot be the containing block its
    # percentage-inset children need, and they resolve against zero. Measured
    # in the browser: 625 of 632 elements were 0x0 with the canvas itself
    # correctly 3902x1975. Such a wrapper must become transparent instead
    # (see `_filter_position_classes`), letting its children resolve against
    # the frame, which is the coordinate space their percentages are in.
    if _CANVAS_MODE:
        return "contents" not in tokens
    # TRIED AND REVERTED: also treating `inset-0` / `size-full` as composition.
    # It is true that Dev Mode writes most of a frame that way — one real
    # dashboard had 534 absolute nodes, 251 `size-full`, 160 `inset-0` and only
    # 5 pixel offsets — but preserving them made the page WORSE, not better:
    # every layer left the flow, so its ancestors had no height for `inset-0`
    # to fill, and a page that rendered three cards rendered none.
    #
    # `inset-0` only means something inside a box with a size. In a reflowed
    # layout there is no such box, which is the honest limit of reflowing this
    # kind of frame at all — see the note in `_filter_position_classes`.
    return any(_PCT_OFFSET_RE.match(t) for t in tokens)


def _filter_position_classes(cn: str, preserve_absolute: bool = False) -> str:
    """Strip Figma Dev Mode absolute-positioning utilities from a className string.

    When preserve_absolute=True (decorative SVG layers with fixed pixel size),
    the absolute + offset classes are kept so the SVG layers compose correctly.

    Removes:
    - absolute / relative / fixed / sticky
    - left-*, top-*, right-*, bottom-*, inset-*, translate-*, transform*, z-*
    - leading-[0] / leading-[0px] — collapses line-height causing text overlap

    NOT removed: w-[Npx] / h-[Npx]. It used to strip those whenever the node
    also carried `absolute`, and that is what emptied a design of its content.
    Figma positions a card with `absolute left-[x] top-[y] w-[w] h-[h]`; drop
    the offsets AND the size and an absolutely-positioned image layer has
    neither position nor dimensions left, so it renders as nothing. A real
    dashboard frame of ~30 cards came out as three: the header, one ring and
    one chart, with the rest of the page blank.

    The size is the half worth keeping. Offsets are re-inferred as a flex flow
    by `_infer_absolute_flow`; dimensions cannot be re-inferred from anything,
    because the content is images. `_attach_style_passthrough` caps a retained
    pixel width with `max-w-full` so a 3902px frame cannot force the viewport
    sideways.

    Preserves flex/grid/bg/border/text/padding/margin/sizing utilities.
    """
    if not cn:
        return cn

    tokens = cn.split()

    # A `contents` wrapper is dissolved on a canvas: the class goes, and so do
    # the offsets it carried, which `display: contents` was already ignoring.
    # What remains is a static div — it establishes no containing block, so an
    # absolutely-positioned descendant resolves against the frame itself.
    if _CANVAS_MODE and "contents" in tokens:
        tokens = [t for t in tokens if t != "contents"]
        return " ".join(
            t for t in tokens
            if t not in ("absolute", "fixed", "relative")
            and not any(pat.search(t) for pat in _POSITION_PATTERNS)
            and not _LEADING_ZERO_RE.match(t)
        )

    if preserve_absolute:
        # Only strip leading-[0] — keep all positioning intact
        result = [t for t in tokens if not _LEADING_ZERO_RE.match(t)]
        return " ".join(result)

    result = []
    for t in tokens:
        # Check all position patterns
        if any(p.search(t) for p in _POSITION_PATTERNS):
            continue
        # Strip leading-[0] / leading-[0px] — Figma Dev Mode artifact
        if _LEADING_ZERO_RE.match(t):
            continue
        result.append(t)

    return " ".join(result)


def _children_have_absolute(children: list) -> bool:
    """Return True if any immediate JSXElement child has 'absolute' in its className."""
    for child in children:
        if isinstance(child, JSXElement):
            cn = child.attrs.get("className", "")
            tokens = cn.split() if cn else []
            if any(t in ("absolute", "fixed") for t in tokens):
                return True
    return False


# Regex patterns for detecting absolute-flow offsets on child elements.
_ABS_TOP_RE = re.compile(r'\btop-\[(\-?\d+(?:\.\d+)?)px\]')
_ABS_LEFT_RE = re.compile(r'\bleft-\[(\-?\d+(?:\.\d+)?)px\]')


def _infer_absolute_flow(children: list) -> tuple:
    """Examine immediate JSX children's className for absolute-flow signals.

    Returns ("col", gap_px) if children are stacked vertically via
    ``absolute top-[Npx]`` with monotonically increasing top values,
    ("row", gap_px) if horizontally via ``absolute left-[Npx]``,
    ("wrap", gap_px) if they spread on BOTH axes — a 2D grid of cards, which
    is what a dashboard frame is — or (None, 0) if the children weren't laid
    out by absolute offsets at all.

    Heuristic:
    - Need at least 2 absolute-positioned children
    - All absolute children share the same flow axis (top OR left, not both)
    - Tops/lefts are monotonically increasing (after sort: 0, N1, N2, …)
    - gap_px = 16 (sensible mid-point; we don't know child heights so we
      cannot compute the true gap precisely)
    """
    tops = []
    lefts = []
    abs_count = 0
    for c in children:
        if not isinstance(c, JSXElement):
            continue
        cn = c.attrs.get("className", "")
        if "absolute" not in cn.split():
            continue
        abs_count += 1
        t = _ABS_TOP_RE.search(cn)
        l = _ABS_LEFT_RE.search(cn)
        if t:
            tops.append(float(t.group(1)))
        if l:
            lefts.append(float(l.group(1)))

    if abs_count < 2:
        return (None, 0)

    # Real Figma always emits BOTH top-[Npx] and left-[Npx] for absolute children —
    # counting the two axes always ties, so we look at variance instead. Whichever
    # axis actually spreads the children out is the flow direction; the other
    # (near-constant) axis is just alignment.
    def _spread(vals):
        return (max(vals) - min(vals)) if vals else 0.0

    top_spread = _spread(tops)
    left_spread = _spread(lefts)

    # A meaningful spread needs at least ~8px on one axis (below that it's
    # rounding noise, not a real layout signal).
    THRESH = 8.0
    top_flowing = len(tops) >= 2 and top_spread >= THRESH
    left_flowing = len(lefts) >= 2 and left_spread >= THRESH

    # HOW MANY DISTINCT POSITIONS, NOT HOW FAR APART.
    #
    # Comparing spreads cannot tell a grid from a row: a 2x2 of cards 500px
    # apart across and 300px down has a WIDER left-spread than top-spread, so a
    # "left dominates" rule calls it one row and puts four cards in a line.
    #
    # What actually separates the three cases is how many distinct offsets an
    # axis has. A row has one top and many lefts. A column has one left and
    # many tops. A grid has several of both — that is what being a grid means.
    # Values are clustered at the same 8px tolerance used above, because Figma
    # rounds and two cards in a row are rarely at the identical pixel.
    def _clusters(vals):
        out = []
        for v in sorted(vals):
            if not out or v - out[-1] > THRESH:
                out.append(v)
        return len(out)

    rows_of = _clusters(tops)
    cols_of = _clusters(lefts)

    if rows_of <= 1 and left_flowing:
        return ("row", 16)
    if cols_of <= 1 and top_flowing:
        return ("col", 16)

    # SEVERAL OF BOTH IS A GRID, AND IT USED TO BE THE DEAD BRANCH.
    #
    # This said "treat as grid-ish, let className win" and returned no flow —
    # but by the time a browser sees the node, `_filter_position_classes` has
    # taken `absolute`, `left-` and `top-` out of that very className. There
    # was nothing left for it to win with, so a page whose cards are laid out
    # on a 2D grid got neither positions nor a flow, and stacked or vanished.
    #
    # A dashboard frame is precisely this case: ~30 cards over several rows and
    # several columns. Wrapping is the honest reflow — cards keep their own
    # size (see `_filter_position_classes`) and fill rows in reading order,
    # which is the arrangement the design had, minus its exact coordinates.
    if rows_of >= 2 and cols_of >= 2:
        return ("wrap", 16)
    return (None, 0)


# Arbitrary hex color in Tailwind: text-[#RRGGBB] or text-[#RGB] or
# text-[rgba(...)] etc.  Figma emits these for on-brand color choices that
# are correct in the design but wrong for semantic rendering in our system
# (e.g. the login subtitle is purple in Figma because it's brand-colored,
# but the design system should render it as the foreground color).
_ARBITRARY_COLOR_RE = re.compile(
    r'^(?:text|bg|border|ring|fill|stroke)-\[(?:#[0-9a-fA-F]{3,8}|rgba?\([^)]+\))\]$'
)

# Neutral colors that should be kept even from Figma arbitrary values
_KEEP_NEUTRAL_RE = re.compile(
    r'^(?:text|bg|border)-\[(?:white|black|transparent|rgba\(0,0,0,0\)|rgba\(255,255,255)\b'
)


def _sanitize_body_text_classname(cn: str) -> str:
    """Strip arbitrary hex/rgba color tokens from body Text nodes' className.

    Figma Dev Mode emits text-[#6e2574] (and similar) for branded text colors.
    These cause body text to render in off-brand colors. Our design system
    already provides semantic color tokens, so we drop the Figma hex overrides
    on Text nodes (but preserve white/black/transparent which are intentional).

    Heading nodes keep their color tokens because they may be on colored
    backgrounds (e.g. white text on the brand-gradient panel).
    """
    if not cn:
        return cn
    tokens = cn.split()
    result = []
    for t in tokens:
        # Strip arbitrary hex/rgba color if it's not a neutral
        if _ARBITRARY_COLOR_RE.match(t) and not _KEEP_NEUTRAL_RE.match(t):
            continue
        result.append(t)
    return " ".join(result)


_FIGMA_COLLAPSE_HINTS = {
    "min-h-px",   # Figma's "minimum 1px" hint — collapses content in flexbox
    "min-w-px",
    "flex-[1_0_0]",  # flex: 1 0 0 — collapses to 0 when parent has no height
    "flex-[1_0_0%]",
}


def _filter_container_height(cn: str) -> str:
    """Strip h-[Npx] from Stack/Row/Grid/Form className strings.

    Flex-column and grid containers with explicit Figma heights clip their
    children when the content exceeds the designed height.  Stack/Row/Form
    nodes are flex containers that should grow to fit their content; dropping
    the fixed height lets them do so.

    Heights on leaf nodes (Image, Input, Button, Heading, Text) are preserved
    by NOT passing this filter for those node types.

    Also strips Figma "collapse hints" (min-h-px, min-w-px, flex-[1_0_0]) —
    these encode "stretch within Figma's coordinate-positioned parent" and
    collapse content to zero when our flowed-flex parents don't carry an
    explicit pixel height/width.
    """
    if not cn:
        return cn
    tokens = cn.split()
    return " ".join(
        t for t in tokens
        if not re.match(r'^h-\[(\d+(?:\.\d+)?px)\]$', t)
        and t not in _FIGMA_COLLAPSE_HINTS
    )


def _strip_overflow_clip(cn: str) -> str:
    """Remove overflow-clip from Container className strings.

    Figma Dev Mode emits overflow-clip on frames that have 'clip content' on.
    This causes fixed-height Container boxes to clip Stack children that expand
    beyond the Figma-designed height.  Removing it lets children overflow
    visually while keeping the Container's own sizing intact.
    """
    if not cn:
        return cn
    tokens = cn.split()
    return " ".join(t for t in tokens if t not in ("overflow-clip", "overflow-hidden"))


# ---------------------------------------------------------------------------
# Schema transformer
# ---------------------------------------------------------------------------

_DATA_NAME_TO_TYPE: dict[str, tuple[str, dict]] = {
    "Email Input": ("Input", {"type": "email"}),
    "Password Input": ("Input", {"type": "password"}),
    "Search Input": ("Input", {"type": "text"}),
    "Input": ("Input", {"type": "text"}),
    "Button": ("Button", {}),
    "Checkbox": ("Checkbox", {}),
    "Link": ("Link", {}),
    "Form": ("Form", {}),
    "Sign in Form": ("Form", {}),
    "Logo Image": ("Image", {"alt": "Logo"}),
    "Primitive.label": ("Text", {"role": "label"}),
}

_HEADING_NAME_RE = re.compile(r"^Heading\s+(\d)$", re.I)

# Composite types where descendant text becomes a prop (don't recurse children)
_TEXT_CONSUMING = {"Input", "Button", "Link"}

_BIG_FONT_RE = re.compile(r"text-\[(\d+)px\]")

# Regex for bare flex (flex but NOT flex-col)
_FLEX_ROW_RE = re.compile(r"(^|\s)flex(\s|$)")


def _descendant_text(node) -> str:
    """Concatenate all descendant text strings."""
    if isinstance(node, str):
        return node.strip()
    if isinstance(node, JSXElement):
        return "".join(_descendant_text(c) for c in node.children).strip()
    return ""


def _has_visual_children(node: "JSXElement") -> bool:
    """True when the element has any non-text descendant that renders visuals
    (image, svg, or an element whose class carries a bg/fill/gradient).

    Used to decide whether a text-consuming component (Button/Link/Input) can
    safely flatten its descendants into a `label` prop. When it has icons,
    image tiles, or filled shapes, collapsing to a label alone loses them —
    keep the children instead so the tree can render as authored.
    """
    if not isinstance(node, JSXElement):
        return False
    for c in node.children:
        if not isinstance(c, JSXElement):
            continue
        if c.tag in ("img", "svg"):
            return True
        cn = c.attrs.get("className", "") if hasattr(c, "attrs") else ""
        if cn:
            toks = cn.split()
            for t in toks:
                # bg-[color], bg-color-N, fill-*, or a background-image style
                # class all indicate the child carries its own visual — don't
                # throw it away by collapsing the parent to a label.
                if t.startswith(("bg-[", "bg-", "fill-")) and t not in ("bg-transparent", "bg-none"):
                    return True
        if _has_visual_children(c):
            return True
    return False


def _find_first_img(node: JSXElement) -> "JSXElement | None":
    """Find the first descendant <img> element."""
    return node.find_descendant(lambda n: isinstance(n, JSXElement) and n.tag == "img")


def _make_node(node_type: str, props: dict, children: list | None = None) -> dict:
    return {
        "id": str(_uuid.uuid4()),
        "type": node_type,
        "props": props,
        "children": children if children is not None else [],
    }


def _attach_style_passthrough(props: dict, attrs: dict, preserve_absolute: bool = False) -> None:
    """Copy className, style, and data-node-id onto the props dict."""
    cn = _filter_position_classes(attrs.get("className", ""), preserve_absolute=preserve_absolute)
    # Always strip Figma "collapse hints" — min-h-px, flex-[1_0_0], etc.
    # collapse content to zero in our flowed-flex layout regardless of
    # whether the surrounding container is Stack / Row / Container.
    if cn:
        tokens = [t for t in cn.split() if t not in _FIGMA_COLLAPSE_HINTS]
        cn = " ".join(tokens)
    # A KEPT PIXEL WIDTH IS CAPPED, NOT DROPPED. Figma frames are authored far
    # wider than any viewport (3902px here), so a bare `w-[3902px]` would put
    # the page on a horizontal scrollbar. `max-w-full` keeps the design size as
    # the intent and the viewport as the limit.
    if cn and _WIDTH_PX_RE.search(cn) and "max-w-" not in cn:
        cn = cn + " max-w-full"
    if cn:
        props["className"] = cn
    style = attrs.get("style")
    if isinstance(style, dict):
        props["style"] = style
    nid = attrs.get("data-node-id")
    if nid:
        props["_figmaNodeId"] = str(nid)


def _transform_node(element: JSXElement) -> dict | None:
    """Convert a single JSXElement (and recursively its children) to a schema node."""
    tag = element.tag
    attrs = element.attrs

    # ── 1. <img> → Image ────────────────────────────────────────────────────
    if tag == "img":
        props: dict = {}
        src = attrs.get("src", "")
        if src:
            props["src"] = src
        # ALWAYS PRESENT, EVEN WHEN EMPTY. Figma writes `alt=""` on every
        # decorative vector, and dropping the attribute is not the same fact:
        # an absent `alt` is an image nobody described, an empty one is an
        # image deliberately hidden from assistive technology. The component
        # catalog requires the prop for exactly that reason, so omitting it
        # refused every Figma page carrying an icon — 249 of them on one real
        # dashboard.
        props["alt"] = attrs.get("alt", "") or ""
        _attach_style_passthrough(
            props, attrs,
            preserve_absolute=_is_decorative_positioned(attrs.get("className", "")))
        return _make_node("Image", props)

    # ── 2. <p> → Heading or Text ─────────────────────────────────────────────
    if tag == "p":
        cn = attrs.get("className", "")
        text_content = _descendant_text(element)
        props = {}

        # Check for big font size: text-[Npx] with N >= 18
        m = _BIG_FONT_RE.search(cn)
        if m and int(m.group(1)) >= 18:
            px = int(m.group(1))
            level = 2 if px >= 30 else 4
            props["level"] = level
            props["content"] = text_content
            _attach_style_passthrough(props, attrs)
            return _make_node("Heading", props)

        # Check for font-bold or font-semibold (but no big text class)
        if "font-bold" in cn or "font-semibold" in cn:
            props["level"] = 3
            props["content"] = text_content
            _attach_style_passthrough(props, attrs)
            return _make_node("Heading", props)

        # Otherwise → Text; strip Figma hex colors from body text
        props["content"] = text_content
        _attach_style_passthrough(props, attrs)
        if "className" in props:
            props["className"] = _sanitize_body_text_classname(props["className"])
            if not props["className"]:
                del props["className"]
        return _make_node("Text", props)

    # ── 3. <div ...> — classify via data-name first, then className ──────────
    data_name = attrs.get("data-name", "")

    # 3a. Heading N via data-name
    hn_match = _HEADING_NAME_RE.match(data_name)
    if hn_match:
        level = int(hn_match.group(1))
        text_content = _descendant_text(element)

        # Merge the leaf <p>'s text-size / font-weight / tracking classes into the
        # Heading's className so the renderer respects the Figma-specified size.
        # This is needed when the wrapper <div data-name="Heading N"> carries no
        # text-[Npx] cue itself — the actual size lives on the inner <p>.
        leaf_style_cn = ""
        leaf_p = element.find_descendant(
            lambda n: isinstance(n, JSXElement) and n.tag == "p"
        )
        if leaf_p:
            leaf_cn = leaf_p.attrs.get("className", "")
            # Extract text-size, font-weight, tracking, and color tokens
            leaf_tokens = leaf_cn.split() if leaf_cn else []
            style_tokens = [
                t for t in leaf_tokens
                if (
                    t.startswith("text-[")
                    or t.startswith("font-")
                    or t.startswith("tracking-")
                    or (t.startswith("text-") and t not in ("text-left", "text-right", "text-center", "text-justify"))
                )
            ]
            leaf_style_cn = " ".join(style_tokens)

            # If leaf has a big enough text-[Npx], override the data-name level
            lm = _BIG_FONT_RE.search(leaf_cn)
            if lm:
                px = int(lm.group(1))
                if px >= 30:
                    level = 2
                elif px >= 20:
                    level = 3
                # else keep the original level from data-name

        props = {"level": level, "content": text_content}
        _attach_style_passthrough(props, attrs)
        # Merge leaf style tokens into the Heading's className
        if leaf_style_cn:
            existing_cn = props.get("className", "")
            merged = (existing_cn + " " + leaf_style_cn).strip() if existing_cn else leaf_style_cn
            props["className"] = merged
        return _make_node("Heading", props)

    # 3b. Logo Image via data-name
    if data_name == "Logo Image":
        img_el = _find_first_img(element)
        props = {"alt": "Logo"}
        if img_el:
            src = img_el.attrs.get("src", "")
            if src:
                props["src"] = src
        _attach_style_passthrough(
            props, attrs,
            preserve_absolute=_is_decorative_positioned(attrs.get("className", "")))
        return _make_node("Image", props)

    # 3c. Primitive.label via data-name
    if data_name == "Primitive.label":
        text_content = _descendant_text(element)
        props = {"role": "label", "content": text_content}
        _attach_style_passthrough(props, attrs)
        return _make_node("Text", props)

    # 3d. Known data-name composites
    if data_name in _DATA_NAME_TO_TYPE:
        schema_type, extra_props = _DATA_NAME_TO_TYPE[data_name]
        props = dict(extra_props)
        _attach_style_passthrough(props, attrs)

        if schema_type == "Form":
            # Form recurses — strip fixed heights so the form expands to its content.
            # Forms in Figma Dev Mode are typically expressed via absolute-positioned
            # children (each row at top-[Npx]); once C.4 strips those positions, the
            # rows collapse with zero gap. Default Forms without a gap utility to
            # gap-[16px] so rows breathe.
            cn = props.get("className", "")
            cn = _filter_container_height(cn)
            tokens = cn.split() if cn else []
            has_gap = any(t.startswith("gap-") or t.startswith("flex-col") and False for t in tokens) or any(t.startswith("gap-") for t in tokens)
            if not has_gap:
                tokens.append("gap-[16px]")
            if "flex" not in tokens:
                tokens = ["flex", "flex-col"] + tokens
            props["className"] = " ".join(tokens).strip()
            # Infer form workflow from data-name (e.g. "Sign in Form" → auth.signIn)
            form_workflow = None
            dn = data_name.lower().strip()
            if "sign in" in dn or "log in" in dn or "login" in dn:
                form_workflow = "auth.signIn"
            elif "sign up" in dn or "register" in dn:
                form_workflow = "auth.signUp"
            elif "search" in dn:
                form_workflow = "search.submit"
            if form_workflow:
                props["workflow"] = form_workflow
            children = _transform_children(element.children)
            return _make_node("Form", props, children)

        if schema_type in _TEXT_CONSUMING:
            # Consume descendant text into label/placeholder
            text_content = _descendant_text(element)
            # Fix A — when the element has visual children (img, svg, or a
            # child with its own bg/fill class), we CANNOT flatten to a
            # label-only node without throwing them away. Figma authors
            # product-image tiles as <button><img/><span>Sneakers</span></button>;
            # the old collapse dropped the <img>. Keep the children in that
            # case, and still expose the text as label/placeholder so
            # workflow/navigate inference and accessible names still work.
            keep_children = _has_visual_children(element) and schema_type != "Input"
            if schema_type == "Input":
                props["placeholder"] = text_content
                # Infer `name` from Figma data-name + input type + placeholder
                input_name = infer_input_name(
                    data_name,
                    props.get("type", "text"),
                    text_content,
                )
                if input_name:
                    props["name"] = input_name
            elif schema_type == "Button":
                props["label"] = text_content
                # Infer workflow / navigate from label text.
                # Spec D W5: LLM classifier runs first when
                # FORGE_FIGMA_LLM is set AND a caller has populated the
                # LLM context; keyword classifier is the fallback.
                action = _classify_button_action_with_llm(
                    text_content,
                    data_name,
                    attrs.get("className", ""),
                )
                if "workflow" in action:
                    props["workflow"] = action["workflow"]
                if "navigate" in action:
                    props["navigate"] = action["navigate"]
            elif schema_type == "Link":
                props["label"] = text_content
            children = _transform_children(element.children) if keep_children else []
            return _make_node(schema_type, props, children)

        if schema_type == "Checkbox":
            return _make_node("Checkbox", props, [])

        # Fallback: just emit the node
        return _make_node(schema_type, props, [])

    # 3e. className-based layout classification
    cn = attrs.get("className", "")

    # Decorative positioned node: absolute + fixed pixel size.
    # These are SVG vector layers that compose into an icon shape — the
    # absolute offsets must be preserved so the layers overlay correctly.
    preserve_abs = _is_decorative_positioned(cn)

    # Detect if children were Figma-laid-out via absolute top-[Npx] / left-[Npx]
    # offsets BEFORE we recurse — the existing position filter will strip those
    # offsets from children, but we need to inject the replacement flex flow now.
    # Skip if the node already carries grid layout (Grid handles its own flow).
    is_grid = "grid grid-cols-" in cn or "grid-cols-" in cn
    inferred_flow, inferred_gap = (None, 0)
    if not is_grid:
        inferred_flow, inferred_gap = _infer_absolute_flow(element.children)

    props = {}
    _attach_style_passthrough(props, attrs, preserve_absolute=preserve_abs)

    # If this node has any absolutely-positioned immediate children, add
    # `relative` to its own className so the children resolve against it.
    # Only add when not already carrying a position keyword.
    # A DISSOLVED `contents` WRAPPER MUST NOT BECOME THE CONTAINING BLOCK.
    #
    # Making a parent of absolute children `relative` is right in a flowed
    # page: the children's offsets are meant to be read against it. On a
    # canvas they are not — the percentages Figma wrote are in FRAME
    # coordinates, and the wrapper carried `display: contents` precisely so it
    # would never be anyone's reference box.
    #
    # Adding `relative` here made each dissolved wrapper a 3902x48 box, and a
    # card asking for `inset-[6.23%_93.93%_88%_3.08%]` against 48px of height
    # computed `inset: 0px 3902px 48px 0px` — zero by zero. Left static, the
    # wrapper establishes nothing and the frame stays the reference.
    _was_contents = _CANVAS_MODE and "contents" in (cn or "").split()
    if _children_have_absolute(element.children) and not _was_contents:
        existing_cn = props.get("className", "")
        existing_tokens = existing_cn.split() if existing_cn else []
        position_keywords = {"absolute", "relative", "fixed", "sticky"}
        if not any(t in position_keywords for t in existing_tokens):
            props["className"] = ("relative " + existing_cn).strip()

    if is_grid:
        children = _transform_children(element.children)
        return _make_node("Grid", props, children)

    # Children's actual absolute-offset layout WINS over the parent's declared
    # flow class. Figma Dev Mode routinely emits `flex flex-col` at parents
    # whose children are positioned side-by-side via `absolute left-[Npx]` —
    # trusting the class collapses horizontal rows into vertical stacks.
    # `_infer_absolute_flow` only returns a definite answer when 2+ children
    # have monotonically-increasing offsets on ONE axis, so decorative SVG
    # overlays and mixed layouts still fall through to the className path.
    if inferred_flow == "row":
        # Rewrite the className: drop flex-col if present, add flex + gap
        cleaned = " ".join(t for t in cn.split() if t != "flex-col")
        tokens = cleaned.split() if cleaned else []
        if not any(t in ("flex", "grid", "inline-flex", "inline-grid") for t in tokens):
            cleaned = f"flex gap-[{inferred_gap}px] {cleaned}".strip()
        else:
            cleaned = f"gap-[{inferred_gap}px] {cleaned}".strip()
        props["className"] = _filter_container_height(cleaned)
        children = _transform_children(element.children)
        return _make_node("Row", props, children)

    if "flex-col" in cn:
        # Stack (flex-col): strip fixed heights so content can grow past Figma height
        if "className" in props:
            props["className"] = _filter_container_height(props["className"])
        children = _transform_children(element.children)
        return _make_node("Stack", props, children)

    if _FLEX_ROW_RE.search(cn):
        children = _transform_children(element.children)
        return _make_node("Row", props, children)

    # Inferred flow from absolute-offset children (C.8 generalisation):
    # When Figma used absolute top-[Npx] / left-[Npx] to position children and
    # C.4 will strip those offsets, we promote the parent to Stack/Row and inject
    # the replacement gap so children breathe instead of collapsing.
    if inferred_flow in ("col", "row", "wrap"):
        flow_class = (
            f"flex flex-col gap-[{inferred_gap}px]"
            if inferred_flow == "col"
            else f"flex flex-wrap gap-[{inferred_gap}px]"
            if inferred_flow == "wrap"
            else f"flex gap-[{inferred_gap}px]"
        )
        existing = props.get("className", "")
        tokens = existing.split() if existing else []
        if not any(t in ("flex", "grid", "inline-flex", "inline-grid") for t in tokens):
            props["className"] = (flow_class + " " + existing).strip()
        # Strip fixed heights — the new flex container should grow with content
        if "className" in props:
            props["className"] = _filter_container_height(props["className"])
        children = _transform_children(element.children)
        node_type = "Stack" if inferred_flow == "col" else "Row"
        return _make_node(node_type, props, children)

    # Default: Container — keep fixed heights (they size the box) but remove
    # overflow-clip so children are not visually clipped.
    if "className" in props:
        # Strip overflow-clip on Container nodes that have Stack/Row children
        # to prevent Figma-derived height boxes from clipping overflowing content
        props["className"] = _strip_overflow_clip(props["className"])
    # Container nodes whose className was entirely position-only (`absolute
    # inset-*`, stripped in C.4) end up with no className at all. Their
    # `size-full` Image descendants then resolve against an unbounded parent
    # and render at the SVG's natural size. Give such wrapper Containers a
    # `relative w-full h-full` default so descendants size against the
    # nearest bounded ancestor.
    # NOT ON A CANVAS. This default exists because a flowed page has no bounded
    # ancestor for a `size-full` descendant to resolve against. A canvas HAS
    # one — the frame — and giving an emptied wrapper `relative w-full h-full`
    # makes it the containing block instead, which is the same collapse that
    # `display: contents` caused: percentages meant for the frame resolve
    # against a wrapper that is only as tall as its own flow content.
    if not props.get("className") and not _CANVAS_MODE:
        props["className"] = "relative w-full h-full"
    children = _transform_children(element.children)
    return _make_node("Container", props, children)


def _transform_children(children: list) -> list:
    """Transform a list of JSXElement/str children into schema nodes."""
    result = []
    for child in children:
        if isinstance(child, JSXElement):
            node = _transform_node(child)
            if node is not None:
                result.append(node)
        # str children are text nodes — skip at this level
        # (they're consumed by _descendant_text in parent classification)
    return result


def _rewrite_asset_paths(node: dict, asset_paths: dict[str, str]) -> None:
    """Walk the schema tree and rewrite any src that matches asset_paths."""
    if not isinstance(node, dict):
        return
    props = node.get("props", {})
    src = props.get("src")
    if isinstance(src, str) and src in asset_paths:
        props["src"] = asset_paths[src]
    for child in node.get("children") or []:
        _rewrite_asset_paths(child, asset_paths)


def transform_jsx_to_schema(
    jsx_source: str,
    asset_paths: dict[str, str] | None = None,
    canvas: tuple[float, float] | None = None,
) -> dict:
    """Parse the JSX source and convert to PageV2 schema. When asset_paths
    is supplied (output of figma_asset_downloader), every img src that
    matches a CDN URL is rewritten to the local /figma/... path.

    Returns a PageV2-shaped dict: {schemaVersion: '2.0', id, title,
    dataSources: [], children: [<root_node>]}.
    """
    global _CANVAS_MODE
    root_element = parse_jsx_tree(jsx_source)
    _CANVAS_MODE = canvas is not None
    try:
        root_node = _transform_node(root_element)
    finally:
        _CANVAS_MODE = False

    # The MCP root commonly carries `size-full` which collapses to zero
    # height when its scaffold parent isn't bounded — the entire design
    # then renders on a 1-pixel-tall line. Substitute a viewport-sized
    # min-height so the layout has somewhere to grow.
    if isinstance(root_node, dict):
        root_props = root_node.get("props") or {}
        root_cn = root_props.get("className", "")
        if canvas is not None:
            # THE BOX THE DESIGN WAS DRAWN IN. `size-full` means "be my
            # parent", and the parent here is the page — so without this the
            # frame is whatever the viewport is, and every child positioned
            # against 3902px lands somewhere else. Substituting
            # `min-h-screen w-full` (what this did before) gives the root a
            # viewport width, which is the one width the design was NOT drawn
            # at.
            width, height = canvas
            root_props["className"] = " ".join(
                t for t in root_cn.split() if t not in ("size-full",)
            ).strip()
            style = dict(root_props.get("style") or {})
            style.update({"width": f"{width:g}px", "height": f"{height:g}px",
                          "position": "relative"})
            root_props["style"] = style
            root_node["props"] = root_props
        elif "size-full" in root_cn:
            root_props["className"] = root_cn.replace("size-full", "min-h-screen w-full").strip()
            root_node["props"] = root_props

    schema: dict = {
        "schemaVersion": "2.0",
        "id": str(_uuid.uuid4()),
        "title": "Figma Import",
        "dataSources": [],
        "children": [root_node] if root_node is not None else [],
    }

    if asset_paths:
        for child in schema["children"]:
            _rewrite_asset_paths(child, asset_paths)

    return schema
