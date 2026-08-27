"""Top-level orchestrator: Figma document → (PageV2 schema, tokens).
Combines the walker, classifier, and style extractor into a single call."""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib

from services.figma_node_walker import walk_and_flatten
from services.figma_name_classifier import (
    classify,
    classify_with_llm,
    refine_container_type,
)
from services.figma_style_extractor import extract_tokens, node_to_utility_classes


# Node types that never own structural children. Their visible content is
# either folded descendant text (Heading / Text / Button / Input / Link)
# or a single image asset (Image / Icon).  Vector-shape children inside a
# Figma icon are classified as Box; if left attached they render as red
# squares because figma_style_extractor projects the brand fill colour
# onto them. Dropping their children is the only way to get a clean
# rendering without a per-icon SVG export pipeline.
_LEAF_TYPES = {
    "Heading", "Text", "Button", "Input", "Link", "Checkbox",
    "Image", "Icon",
}


@dataclass
class BuildResult:
    page: dict
    tokens: dict
    complete: bool
    incomplete_nodes: list[dict] = field(default_factory=list)


def _id_for(figma_id: str) -> str:
    """Schema id derived from Figma id so re-ingesting the same file
    produces the same schema ids (idempotency)."""
    h = hashlib.sha1((figma_id or "").encode()).hexdigest()[:8]
    return f"n_{h}"


def _is_vector_only_frame(node: dict) -> bool:
    """A FRAME whose entire subtree contains nothing but VECTOR /
    BOOLEAN_OPERATION leaves (no TEXT, no nested FRAMEs with structural
    content). Common case: a logo wrapper holding one path per glyph,
    or a multi-piece icon composition. Without this signal the schema
    emits N empty Boxes — one per glyph — and the rendered logo is invisible.

    Bbox guard: only treat as logo-like when the frame fits within a
    reasonable badge / wordmark footprint (≤ 600×200 px). A 1200×800 vector
    composition is more likely a hand-drawn hero illustration where the
    user expects the individual path layers rather than a flat SVG.
    """
    if node.get("type") != "FRAME":
        return False
    bbox = node.get("absoluteBoundingBox") or {}
    w = bbox.get("width") or 0
    h = bbox.get("height") or 0
    if w > 600 or h > 200:
        return False
    children = node.get("children") or []
    if not children:
        return False
    VECTOR_LEAF = {"VECTOR", "BOOLEAN_OPERATION", "LINE", "ELLIPSE",
                   "REGULAR_POLYGON", "STAR"}
    def all_vector(n: dict) -> bool:
        t = n.get("type")
        if t in VECTOR_LEAF:
            return True
        if t == "GROUP":
            kids = n.get("children") or []
            return bool(kids) and all(all_vector(k) for k in kids)
        return False
    return all(all_vector(c) for c in children)


def _build_node(entry: dict, asset_paths: dict[str, str] | None = None) -> dict:
    node = entry["node"]
    # Pass child_count so the classifier can refuse to treat a FRAME
    # holding a UI tree (e.g. "Background Image" wrapping a whole
    # dashboard mockup) as a single Image asset.
    child_count = len(node.get("children") or [])
    # Spec D W5: keyword classifier first, LLM classifier as fallback
    # when the keyword table returns the safe `Box` default and the
    # FORGE_FIGMA_LLM path is eligible (flag + populated registry).
    schema_type, props = classify_with_llm(
        node.get("name", ""),
        node.get("type", ""),
        child_count=child_count,
    )
    # Vector-only FRAMEs (logos, multi-path icon compositions) override
    # whatever the name-based classifier returned — we want them rendered
    # as a single SVG asset, not as N empty Boxes. The asset-export
    # pipeline already exports anything we classify as Image, so this
    # change automatically wires the logo URL onto the resulting node.
    if _is_vector_only_frame(node):
        schema_type = "Image"
        props = {**props, "alt": node.get("name") or "Image"}
    # When the classifier doesn't know the name but the Figma frame has
    # auto-layout, refine into Row/Stack/Grid based on the layout mode.
    # Without this fallback every unrecognised frame collapses to Box and
    # loses its flex direction — the source of "two-column Figma design
    # rendered as a single vertical stack" failures.
    if schema_type == "Container":
        schema_type = refine_container_type(node)
    elif schema_type == "Box" and node.get("_layoutMode") in ("HORIZONTAL", "VERTICAL"):
        schema_type = refine_container_type(node)

    # Figma auto-layout HORIZONTAL frames don't wrap children — Figma will
    # overflow horizontally instead. Our Row component defaults to
    # `flex-wrap`, so without this flag a sidebar + main content row whose
    # total fixed-pixel width exceeds the viewport wraps the sidebar
    # ABOVE the main area on smaller screens. Set wrap=false so Row.tsx
    # skips emitting `flex-wrap` and the row matches Figma's overflow
    # behaviour.
    if schema_type == "Row" and node.get("_layoutMode") == "HORIZONTAL":
        props = {**props, "wrap": False}

    # Ghost button detection. The library Button defaults to variant:"primary"
    # (bg-primary text-primary-foreground), which gives every nav item a
    # heavy filled background. When the Figma source has NO visible solid
    # fills on a Button-classified frame, that's a sidebar / nav-row item —
    # the designer relied on text + icon + hover to read as interactive.
    # Emit variant:"ghost" so the library doesn't paint a filled background.
    if schema_type == "Button":
        has_visible_solid_fill = any(
            (f or {}).get("type") == "SOLID"
            and (f or {}).get("visible") is not False
            and ((f or {}).get("opacity") in (None, 1, 1.0)
                 or (f or {}).get("opacity", 1) > 0.05)
            for f in (node.get("fills") or [])
        )
        if not has_visible_solid_fill:
            props = {**props, "variant": "ghost"}

    # Dialog nodes need a stable string id on `props.id` (separate from the
    # schema-tree `node.id`) so Buttons with `opensDialog="<id>"` can target
    # them via DialogStateContext at runtime. Use the derived schema id.
    if schema_type == "Dialog":
        props.setdefault("id", _id_for(node.get("id", "?")))
    props = dict(props)
    if schema_type in ("Heading", "Text") and node.get("characters"):
        props["content"] = node["characters"]
    utility = node_to_utility_classes(node)
    if utility:
        props["className"] = " ".join(utility)
    # Wire any pre-exported asset URL onto Image / Icon nodes so they render
    # the design instead of a broken-image icon. Callers can pass None when
    # asset export hasn't run yet — the schema then carries no `src`, and the
    # Image renderer renders nothing rather than a broken-image placeholder.
    if asset_paths and schema_type in ("Image", "Icon"):
        src = asset_paths.get(node.get("id") or "")
        if src:
            props["src"] = src
    return {
        "id": _id_for(node.get("id", "?")),
        "type": schema_type,
        "props": props,
        "children": [],
    }


def _fold_descendant_text(
    fid_to_entry: dict[str, dict],
    children_by_parent_fid: dict[str | None, list[str]],
    root_fid: str,
) -> str:
    """Depth-first concatenation of `characters` under root_fid.

    Used to populate `content` / `label` / `placeholder` on leaf node types
    (Heading, Text, Button, Input, Link) when the named Figma wrapper itself
    has no `characters` field but a TEXT descendant does. Without this fold,
    a frame named "Heading 1" containing a TEXT child renders as an empty
    Heading because the wrapper has no characters.
    """
    parts: list[str] = []

    def go(fid: str) -> None:
        entry = fid_to_entry.get(fid)
        if entry is not None:
            ch = entry["node"].get("characters")
            if ch:
                parts.append(ch)
        for c in children_by_parent_fid.get(fid, []):
            go(c)

    go(root_fid)
    return " ".join(p.strip() for p in parts if p and p.strip()).strip()


def _first_icon_descendant_src(
    fid_to_entry: dict[str, dict],
    children_by_parent_fid: dict[str | None, list[str]],
    root_fid: str,
    asset_paths: dict[str, str] | None,
) -> str | None:
    """Find the first descendant whose name classifies it as Icon AND has an
    exported asset URL. Used to surface the icon of a nav-item FRAME onto its
    Button via `iconSrc`, instead of dropping the icon when the Button leaf
    strips its children.

    Returns the asset URL (e.g. `/api/asset/<proj>/figma/<id>.svg`) or None
    when no Icon descendant has an exported asset.
    """
    if not asset_paths:
        return None
    from services.figma_name_classifier import classify

    def go(fid: str) -> str | None:
        entry = fid_to_entry.get(fid)
        if entry is not None:
            node = entry["node"]
            schema_type, _ = classify(
                node.get("name") or "",
                node.get("type") or "",
                child_count=len(node.get("children") or []),
            )
            if schema_type == "Icon":
                src = asset_paths.get(node.get("id") or "")
                if src:
                    return src
        for c in children_by_parent_fid.get(fid, []):
            hit = go(c)
            if hit:
                return hit
        return None

    return go(root_fid)


def _first_text_descendant_classes(
    fid_to_entry: dict[str, dict],
    children_by_parent_fid: dict[str | None, list[str]],
    root_fid: str,
) -> list[str]:
    """Return the text-color and font-size / font-weight utility classes from
    the FIRST TEXT descendant under root_fid. Used to propagate per-text
    styling onto leaf wrappers (Heading / Text / Button / Link) whose own
    Figma node has no fill or style — without this, folding inner TEXT into
    a parent Heading drops the inner TEXT's colour and font-size.
    """
    def find(fid: str) -> str | None:
        entry = fid_to_entry.get(fid)
        if entry is not None and entry["node"].get("type") == "TEXT":
            return fid
        for c in children_by_parent_fid.get(fid, []):
            hit = find(c)
            if hit:
                return hit
        return None

    first = find(root_fid)
    if not first:
        return []
    entry = fid_to_entry.get(first) or {}
    cls = node_to_utility_classes(entry.get("node") or {})
    # Keep only the colour / typography utilities — radius / padding / gap
    # belong on the wrapper, which already has them from its own node.
    return [
        c for c in cls
        if c.startswith("text-[") or c.startswith("font-")
    ]


def _infer_row_layout_from_bbox(child_entries: list[dict]) -> tuple[str | None, list[str]]:
    """Inspect children's `absoluteBoundingBox` to decide whether their
    parent should render as a Row, Stack, or neither (None).

    Designers often use absolute-positioning in Figma instead of auto-layout
    HORIZONTAL — the panel-split for a login screen is a typical case.
    Without `_layoutMode`, the classifier falls back to Container which
    produces a block-flow layout that stacks children vertically. This
    function recovers the row arrangement from the raw bbox geometry.

    Returns: ("Row", per_child_class_list) — list parallel to child_entries
    giving the extra className each child should pick up. Small children
    (< ~30% of the row's total width) get a fixed `w-[Npx] shrink-0` from
    their bbox so icon+label rows render with a tight icon tile and a
    flex-grow text column, instead of being split 50/50 by `flex-1` each.
    Larger children get `flex-1` to share the remaining space.
    For ("Stack", []) the column flow doesn't need per-child width hints.
    Returns (None, []) when bbox data is missing or layout direction
    can't be inferred.
    """
    boxes: list[tuple[float, float, float, float]] = []
    has_bbox: list[bool] = []
    for ce in child_entries:
        bb = (ce.get("node") or {}).get("absoluteBoundingBox") or {}
        x = bb.get("x"); y = bb.get("y")
        w = bb.get("width") or 0; h = bb.get("height") or 0
        if x is None or y is None:
            boxes.append((0.0, 0.0, 0.0, 0.0))
            has_bbox.append(False)
        else:
            boxes.append((float(x), float(y), float(w), float(h)))
            has_bbox.append(True)

    if sum(has_bbox) < 2:
        return None, []

    xs = [b[0] for b, ok in zip(boxes, has_bbox) if ok]
    ys = [b[1] for b, ok in zip(boxes, has_bbox) if ok]
    x_spread = max(xs) - min(xs)
    y_spread = max(ys) - min(ys)

    # Row signal: children's x positions are spread but y positions cluster.
    # Threshold guards against tiny offsets (e.g. label/icon stacked but
    # slightly indented).
    if x_spread > 50 and x_spread > y_spread * 2:
        widths = [b[2] for b, ok in zip(boxes, has_bbox) if ok]
        total_w = sum(widths) or 1.0
        extras: list[str] = []
        for b, ok in zip(boxes, has_bbox):
            if not ok:
                extras.append("flex-1")
                continue
            w = b[2]
            ratio = w / total_w
            # Small child (< ~30% of the row's width) → fixed bbox width.
            # Common case: icon-tile (~40-48px) next to a long text column.
            # Without this, the icon tile would `flex-1` and dominate.
            if ratio < 0.30 and w > 0 and w < 200:
                extras.append(f"w-[{int(round(w))}px] shrink-0")
            else:
                extras.append("flex-1")
        return "Row", extras
    # Column signal: y positions spread, x positions cluster.
    if y_spread > 50 and y_spread > x_spread * 2:
        return "Stack", []

    return None, []


# ── Polish heuristics ───────────────────────────────────────────────────────
# Pattern-driven schema cleanup that runs after the main build. Each rule
# tightens one common gap between the raw Figma → schema mapping and what a
# human would naturally write in the editor — wrapping the root card with
# centering, making icon tiles fixed-size, etc. Designed to be safely
# idempotent: re-running on an already-polished schema is a no-op.


def _walk(node: dict, fn) -> None:
    if not isinstance(node, dict):
        return
    fn(node)
    for c in node.get("children") or []:
        _walk(c, fn)


def _append_classes(node: dict, *classes: str) -> None:
    """Add each utility class to node.props.className if not already present."""
    if not classes:
        return
    p = node.setdefault("props", {})
    tokens = (p.get("className") or "").split()
    for cls in classes:
        if cls and cls not in tokens:
            tokens.append(cls)
    p["className"] = " ".join(tokens)


def _remove_class(node: dict, cls: str) -> None:
    p = node.setdefault("props", {})
    tokens = [t for t in (p.get("className") or "").split() if t != cls]
    p["className"] = " ".join(tokens)


def _has_class_prefix(node: dict, *prefixes: str) -> bool:
    cn = ((node.get("props") or {}).get("className") or "")
    return any(any(t.startswith(p) for p in prefixes) for t in cn.split())


_FIXED_W_RE = __import__("re").compile(r"\bw-\[(\d+)px\]")
_FIXED_MINH_RE = __import__("re").compile(r"\bmin-h-\[(\d+)px\]")
# Sidebar widths Tailwind-utility-style OR arbitrary-value-style.
# Token-form matcher (whole-class only) since `\b` doesn't anchor after `]`.
# Matches: w-60, w-72, w-1/4, w-[247px], w-[20%]. Excludes w-full.
_SIDEBAR_W_TOKEN_RE = __import__("re").compile(
    r"^w-(?:\[[^\]]+\]|\d+(?:\.\d+)?(?:/\d+)?)$"
)


def _has_sidebar_width(class_str: str) -> bool:
    """True when the className contains a width token that names a sidebar
    column (not full-width). Used by the page-shell heuristic to distinguish
    a real fixed-width sidebar from a content container.
    """
    for tok in class_str.split():
        if tok == "w-full":
            continue
        if _SIDEBAR_W_TOKEN_RE.match(tok):
            return True
    return False
# Viewport-height markers an LLM shell typically emits — we treat them as
# evidence of "shell intent" so the heuristic upgrades the row to a real
# sticky-sidebar layout instead of leaving min-h-screen alone.
_VIEWPORT_H_TOKENS = {"min-h-screen", "h-screen", "min-h-full", "h-full"}


def _swap_token(cn: str, pattern, replacement: str) -> str:
    """Replace tokens matching `pattern` (a compiled regex) with `replacement`,
    or remove them when `replacement` is empty. Whitespace-tokenised."""
    out: list[str] = []
    for tok in cn.split():
        if pattern.fullmatch(tok):
            if replacement:
                out.append(replacement)
        else:
            out.append(tok)
    return " ".join(out)


def _apply_page_shell_layout(page_root_children: list[dict]) -> None:
    """Detect a Figma "page frame" pattern at the root — a Row whose
    className locks it to fixed pixel dimensions (`w-[NNNNpx] min-h-[NNNNpx]`)
    AND whose children include one fixed-width Stack (sidebar) plus one
    flex-1 Stack (main panel) — and swap it for a viewport-fill page shell:

      root row:  w-[1391px] min-h-[1134px]
              → w-full h-screen overflow-hidden items-stretch
      sidebar:   w-[247px] min-h-[852px]
              → w-[247px] h-screen overflow-y-auto shrink-0 flex flex-col
      main:      flex-1 min-h-[1134px]
              → flex-1 h-screen overflow-y-auto

    The sidebar's LAST child that itself contains a profile-like Image +
    Text pair gets `mt-auto` so it pins to the bottom of the sidebar column.
    Inner content in the main panel keeps growing naturally — any nested
    `w-[NNNNpx]` ≥ 800 inside the main panel rewrites to `w-full` so cards
    span the full content width rather than 1144px-capped.

    Idempotent: re-running on an already-shelled schema is a no-op (the
    fixed-px regex doesn't match `w-full` etc.).
    """
    import re as _re
    for root_row in page_root_children:
        if root_row.get("type") != "Row":
            continue
        rprops = root_row.get("props") or {}
        rcn = rprops.get("className") or ""
        rtokens = set(rcn.split())

        # Trigger on EITHER pattern:
        #   A. Figma frame:   w-[Npx] AND min-h-[Npx]
        #   B. LLM shell:     min-h-screen / h-screen / etc.
        is_figma_frame = bool(_FIXED_W_RE.search(rcn) and _FIXED_MINH_RE.search(rcn))
        is_viewport_shell = bool(rtokens & _VIEWPORT_H_TOKENS)
        if not (is_figma_frame or is_viewport_shell):
            continue

        # Looks like a page frame OR an LLM-generated shell. Inspect children
        # for the sidebar (fixed-or-utility width) + main (flex-1) pattern.
        kids = root_row.get("children") or []
        if len(kids) < 2:
            continue
        sidebar = None
        main = None
        for k in kids:
            if k.get("type") not in ("Stack", "Container"):
                continue
            kcn = (k.get("props") or {}).get("className") or ""
            ktokens = kcn.split()
            if sidebar is None and _has_sidebar_width(kcn):
                sidebar = k
            elif main is None and "flex-1" in ktokens:
                main = k
        if sidebar is None or main is None:
            continue

        # ── Root row: drop fixed w/min-h AND replace any viewport-h marker
        # with the canonical (h-screen + overflow-hidden + items-stretch +
        # w-full). The LLM may emit `min-h-screen` which doesn't trigger the
        # sticky-sidebar behavior we want — we want a hard `h-screen` so
        # main can `overflow-y-auto` independently.
        rcn = _swap_token(rcn, _FIXED_W_RE, "")
        rcn = _swap_token(rcn, _FIXED_MINH_RE, "")
        # Drop any viewport-h marker the LLM emitted; we're adding our own.
        rcn = " ".join(t for t in rcn.split() if t not in _VIEWPORT_H_TOKENS)
        for cls in ("w-full", "h-screen", "overflow-hidden", "items-stretch"):
            if cls not in rcn.split():
                rcn = (rcn + " " + cls).strip()
        rprops["className"] = " ".join(rcn.split())

        # ── Sidebar: keep its existing width, drop fixed min-h + viewport-h
        # markers, add hidden-on-mobile + md:flex + the desktop column
        # geometry. Without the `md:` prefixes the desktop sticky sidebar
        # also tries to render at h-screen on narrow viewports, pushing
        # main content off-screen with no escape (no hamburger / drawer
        # wired yet). The `hidden md:flex` collapse to "no sidebar on
        # mobile" is the most pragmatic responsive behaviour we can ship
        # without also building a Drawer.
        scn = (sidebar.get("props") or {}).get("className") or ""
        scn = _swap_token(scn, _FIXED_MINH_RE, "")
        scn = " ".join(t for t in scn.split() if t not in _VIEWPORT_H_TOKENS)
        scn_toks = scn.split()
        # Drawer geometry on mobile (default Tailwind, no breakpoint):
        # fixed offscreen-left, slides in via `data-sidebar-open="true"`
        # selector targeting [data-shell-sidebar]. On md+ revert to a
        # normal inline column.
        for cls in (
            "fixed", "inset-y-0", "left-0", "z-40",
            "-translate-x-full", "transition-transform", "duration-200",
            "md:relative", "md:inset-auto", "md:translate-x-0", "md:z-auto",
            "md:flex", "md:flex-col", "md:h-screen", "md:overflow-y-auto",
            "md:shrink-0", "sidebar-scroll",
        ):
            if cls not in scn_toks:
                scn_toks.append(cls)
        # Strip any unprefixed display utility we (or the LLM) previously
        # emitted — they would render the sidebar on mobile where it should
        # be offscreen. Keep only the md:-prefixed forms.
        for stale in ("flex", "flex-col", "h-screen", "overflow-y-auto",
                      "shrink-0", "hidden"):
            if stale in scn_toks and f"md:{stale}" in scn_toks:
                scn_toks.remove(stale)
        # Remove any LLM-emitted `hidden` not paired with md:flex — we now
        # use the translate-x trick instead of display toggling so the
        # drawer can animate.
        if "hidden" in scn_toks and "md:flex" in scn_toks:
            scn_toks.remove("hidden")
        sidebar.setdefault("props", {})["className"] = " ".join(scn_toks)
        # Mark the sidebar so the ShellStateProvider's CSS selectors find it.
        sidebar.setdefault("props", {})["shellRole"] = "sidebar"

        # ── Spawn a backdrop sibling so taps outside the open drawer close
        # it (and the page below dims on mobile). Mobile-only via CSS
        # (`hidden md:hidden` would hide everywhere; we use the
        # data-sidebar-open selector to show only when open on mobile).
        backdrop_id = f"{root_row.get('id', 'shell')}_backdrop"
        already_has_backdrop = any(
            isinstance(k, dict) and (k.get("props") or {}).get("shellRole") == "backdrop"
            for k in kids
        )
        if not already_has_backdrop:
            backdrop = {
                "id": backdrop_id,
                "type": "Container",
                "props": {
                    "shellRole": "backdrop",
                    "className": (
                        # CSS in globals.css toggles opacity + pointer-events
                        # via [data-sidebar-open="true"] [data-sidebar-backdrop]
                        "fixed inset-0 bg-black/40 z-30 "
                        "opacity-0 pointer-events-none transition-opacity "
                        "md:hidden"
                    ),
                },
                "children": [],
            }
            # Insert backdrop right BEFORE the sidebar so the sidebar's higher
            # z-40 renders above the backdrop's z-30.
            kids.insert(kids.index(sidebar), backdrop)
            root_row["children"] = kids

        # ── Toggle button discovery. Tag any Button that the LLM emitted as
        # the hamburger trigger (workflow=shell.toggleSidebar OR aria-label
        # naming a sidebar/menu toggle) with `togglesSidebar: true` so the
        # Button component renders `data-sidebar-toggle=""` for the
        # ShellStateProvider's delegated click handler.
        def _tag_toggle(n: dict) -> None:
            if not isinstance(n, dict):
                return
            if n.get("type") == "Button":
                props = n.get("props") or {}
                workflow = props.get("workflow") or ""
                onClick = props.get("onClick")
                if isinstance(onClick, str) and onClick.startswith("workflow:"):
                    workflow = onClick.removeprefix("workflow:")
                aria = (props.get("aria-label") or "").lower()
                is_toggle = (
                    workflow == "shell.toggleSidebar"
                    or "open menu" in aria
                    or "open sidebar" in aria
                    or "menu" == aria
                )
                if is_toggle and not props.get("togglesSidebar"):
                    props["togglesSidebar"] = True
                    n["props"] = props
            for c in n.get("children") or []:
                _tag_toggle(c)
        _tag_toggle(main)

        # ── Main: drop fixed min-h + viewport-h, add h-screen + scroll +
        # min-w-0 (so its flex item doesn't grow past the row width when
        # content is wider than the column). Main panel takes the full
        # viewport on mobile (sidebar is hidden), full-width-minus-sidebar
        # on desktop.
        mcn = (main.get("props") or {}).get("className") or ""
        mcn = _swap_token(mcn, _FIXED_MINH_RE, "")
        mcn = " ".join(t for t in mcn.split() if t not in _VIEWPORT_H_TOKENS)
        for cls in ("h-screen", "overflow-y-auto", "main-scroll", "min-w-0"):
            if cls not in mcn.split():
                mcn = (mcn + " " + cls).strip()
        main.setdefault("props", {})["className"] = " ".join(mcn.split())

        # ── Relax fixed widths inside the main panel. Anything ≥ 800px in
        # the original Figma frame was a content column that's now meant
        # to grow with the viewport.
        def relax(n: dict) -> None:
            if not isinstance(n, dict):
                return
            props = n.get("props") or {}
            cn = props.get("className") or ""
            new_toks: list[str] = []
            replaced = False
            for tok in cn.split():
                m = _FIXED_W_RE.fullmatch(tok)
                if m and int(m.group(1)) >= 800:
                    new_toks.append("w-full")
                    replaced = True
                else:
                    new_toks.append(tok)
            if replaced:
                n.setdefault("props", {})["className"] = " ".join(new_toks)
            for c in n.get("children") or []:
                relax(c)
        relax(main)

        # ── Profile pin: the LAST direct child of the sidebar that looks
        # like a user/profile block (any Row/Stack — pin whatever the last
        # block is, since Figma sidebars conventionally end with a user
        # profile, sign-out, or footer chip).
        side_kids = sidebar.get("children") or []
        if side_kids:
            last = side_kids[-1]
            if isinstance(last, dict) and last.get("type") in ("Stack", "Row", "Container"):
                lcn = (last.get("props") or {}).get("className") or ""
                if "mt-auto" not in lcn.split():
                    last.setdefault("props", {})["className"] = (lcn + " mt-auto").strip()

        # ── Card-row wrap rescue. _build_node defaults wrap=false on every
        # HORIZONTAL row (to prevent the sidebar+main pattern from wrapping
        # the sidebar above main). But that leaves stat-card rows / chart-row
        # / product-card rows pinned to a single line — on mobile they
        # overflow horizontally. Detect card-row patterns and re-enable wrap
        # so the cards stack on narrow viewports.
        #
        # Trigger: Row in the main panel with ≥ 3 direct children where each
        # child has a small fixed pixel width (180-400px is the typical
        # stat/product card range). Sidebar+main rows have only 2 children
        # of very different sizes so they don't match.
        def _rescue_wrap_on_card_rows(n: dict) -> None:
            if not isinstance(n, dict):
                return
            if n.get("type") == "Row":
                kids = n.get("children") or []
                if len(kids) >= 3:
                    fixed_widths: list[int] = []
                    for k in kids:
                        kcn = ((k.get("props") or {}).get("className") or "")
                        for tok in kcn.split():
                            m = _FIXED_W_RE.fullmatch(tok)
                            if m:
                                fixed_widths.append(int(m.group(1)))
                                break
                    looks_like_cards = (
                        len(fixed_widths) >= 3
                        and all(180 <= w <= 400 for w in fixed_widths)
                    )
                    if looks_like_cards:
                        props = n.setdefault("props", {})
                        props["wrap"] = True
                        existing = (props.get("className") or "").split()
                        for cls in ("flex-wrap",):
                            if cls not in existing:
                                existing.append(cls)
                        props["className"] = " ".join(existing)
            for c in n.get("children") or []:
                _rescue_wrap_on_card_rows(c)
        _rescue_wrap_on_card_rows(main)


# Whole-token matcher for an arbitrary fixed pixel width (`w-[1271px]`).
# Anchored (^…$) so it never matches the `w-[Npx]` substring inside
# `max-w-[Npx]` / `min-w-[Npx]`, keeping the transform idempotent.
_FLUID_W_TOKEN_RE = __import__("re").compile(r"^w-\[(\d+)px\]$")
# Content-container threshold. Sidebars (~247px) and small fixed columns/chips
# stay fixed so the sidebar + asymmetric-row heuristics keep working; only
# page/section/card-scale widths become fluid.
_FLUID_MIN_WIDTH_PX = 600


def _fluidize_fixed_width_shells(page_root_children: list[dict]) -> None:
    """Make large fixed-pixel-width containers fluid so the page reflows below
    its Figma frame width.

    A Figma frame locks content sections to a fixed width (e.g. `w-[1271px]`);
    on any viewport narrower than that the section overflows and never reflows,
    and on wider viewports it pins left. Rewrite each such container to
    `w-full max-w-[Npx] mx-auto` so it fills the available width up to the
    design width and centers — visually identical to the Figma at >= Npx while
    shrinking gracefully below it.

    Only whole `w-[Npx]` tokens with N >= _FLUID_MIN_WIDTH_PX are touched, so
    fixed-width sidebars and small leaf columns are left alone. Idempotent.
    """
    def _walk(node: dict) -> None:
        if not isinstance(node, dict):
            return
        props = node.get("props") or {}
        cn = props.get("className")
        if isinstance(cn, str) and cn:
            changed = False
            out: list[str] = []
            for tok in cn.split():
                m = _FLUID_W_TOKEN_RE.match(tok)
                if m and int(m.group(1)) >= _FLUID_MIN_WIDTH_PX:
                    if "w-full" not in out:
                        out.append("w-full")
                    out.append(f"max-w-[{m.group(1)}px]")
                    changed = True
                else:
                    out.append(tok)
            if changed:
                if "mx-auto" not in out:
                    out.append("mx-auto")
                props["className"] = " ".join(out)
                node["props"] = props
        for c in node.get("children") or []:
            _walk(c)

    for child in page_root_children:
        _walk(child)


def _apply_polish_heuristics(page_root_children: list[dict]) -> None:
    """Apply the seven post-build polish rules. Operates in place on the
    list of root nodes returned by build_page_schema. Each rule is a small,
    self-contained pattern check; together they bring the deterministic
    output much closer to how a human designer would express the layout
    in our schema vocabulary.
    """
    # Rule 0 — Page-shell layout. Runs first so subsequent rules see
    # the relaxed widths and the page-shell flag.
    _apply_page_shell_layout(page_root_children)

    # Rule 0b — Responsive fluidization. The page-shell pass only handles the
    # sidebar + main pattern; a centered fixed-width column (vertical stack of
    # w-[Npx] sections, as most dashboards are) is left fully fixed. Convert
    # large fixed widths to `w-full max-w-[Npx] mx-auto` so the page reflows.
    _fluidize_fixed_width_shells(page_root_children)

    fake_root = {"type": "_root", "children": page_root_children}

    # Rule 1 — Root card centering.
    # The mapper produces an outer Stack with `rounded-*` that wraps a Row
    # of LEFT/RIGHT panels (the classic "centered card" layout). On its own
    # the wrapper spans the full viewport, leaving the page edge-to-edge.
    # Add max-width + auto margins + shadow so it sits centered on the page.
    for c in page_root_children:
        if c.get("type") != "Stack":
            continue
        cn = (c.get("props") or {}).get("className", "")
        if "rounded-" not in cn:
            continue
        kids = c.get("children") or []
        if not (len(kids) == 1 and kids[0].get("type") == "Row"):
            continue
        if not _has_class_prefix(c, "max-w-"):
            _append_classes(c, "max-w-6xl", "mx-auto", "my-12", "shadow-2xl", "overflow-hidden")

    # Walk every node once and apply leaf-pattern rules.
    def per_node(n: dict) -> None:
        t = n.get("type")
        kids = n.get("children") or []

        # Rule 2 — Container[Checkbox, Text] → flex items-center gap-2.
        # The "Remember me" checkbox pattern: a Container holding a Checkbox
        # plus a text label. Without flex, the checkbox stacks above the
        # label vertically (Container defaults to block flow). The check is
        # tight on children: at most 3 nodes, with a Checkbox + a Text.
        if t == "Container" and 0 < len(kids) <= 3:
            child_types = [k.get("type") for k in kids]
            if "Checkbox" in child_types and "Text" in child_types:
                if not _has_class_prefix(n, "flex"):
                    _append_classes(n, "flex", "items-center", "gap-2")

        # Rule 4 — Row containing a Container + a Link → space them apart.
        # The "Remember me ⇆ Forgot password?" form-control row. Without
        # justify-between the link sits against the checkbox group.
        if t == "Row":
            child_types = [k.get("type") for k in kids]
            if "Container" in child_types and "Link" in child_types:
                if not _has_class_prefix(n, "justify-"):
                    _append_classes(n, "justify-between")
                if not _has_class_prefix(n, "items-"):
                    _append_classes(n, "items-center")
                _append_classes(n, "w-full")

        # Rule 6 — Icon-tile: a Stack containing exactly one Icon.
        # In Figma a typical icon-tile is a small rounded background with
        # the icon centered on top. The mapper produces a Stack with an
        # Icon child whose bbox is small (40-48px), but the Stack might
        # have picked up `flex-1` from the row-inference step. Replace
        # that with a fixed square size (respecting any explicit width
        # already emitted from Figma's layoutSizingHorizontal=FIXED).
        if t == "Stack" and len(kids) == 1 and kids[0].get("type") == "Icon":
            _remove_class(n, "flex-1")
            if not _has_class_prefix(n, "w-", "size-"):
                _append_classes(n, "w-10")
            if not _has_class_prefix(n, "h-"):
                _append_classes(n, "h-10")
            if not _has_class_prefix(n, "items-"):
                _append_classes(n, "items-center")
            if not _has_class_prefix(n, "justify-"):
                _append_classes(n, "justify-center")

    _walk(fake_root, per_node)

    # Rule 3 — Button as the last child of a Form (or Form-nested Stack)
    # gets w-full. CTA buttons in a form panel are typically full-width.
    def form_walker(n: dict) -> None:
        if not isinstance(n, dict):
            return
        if n.get("type") == "Form":
            for k in n.get("children") or []:
                if k.get("type") == "Button":
                    cn = (k.get("props") or {}).get("className", "")
                    if "w-full" not in cn.split():
                        _append_classes(k, "w-full")
                # Look one level deeper too — Forms often wrap their
                # final Button in a Stack/Container.
                if k.get("type") in ("Stack", "Container"):
                    for gk in k.get("children") or []:
                        if gk.get("type") == "Button":
                            cn = (gk.get("props") or {}).get("className", "")
                            if "w-full" not in cn.split():
                                _append_classes(gk, "w-full")
        for c in n.get("children") or []:
            form_walker(c)
    form_walker(fake_root)


_DIALOG_TRIGGER_STOPWORDS: set[str] = {
    # Overlay/UI words — these always appear in dialog names, never useful
    # for matching with a button.
    "modal", "dialog", "popup", "overlay", "drawer", "sheet", "panel",
    # English filler words.
    "the", "a", "an", "of", "in", "and", "or", "to", "for", "on", "at",
    "this", "that", "with",
    # Generic action verbs that appear on too many buttons to disambiguate.
    "button", "submit", "ok", "cancel", "close", "back",
}


def _tokens_from_label(s: str) -> set[str]:
    """Lowercase, split on non-letters, drop stopwords + 1-letter tokens."""
    if not s:
        return set()
    import re as _re
    raw = _re.split(r"[^a-zA-Z]+", s.lower())
    return {t for t in raw if len(t) > 1 and t not in _DIALOG_TRIGGER_STOPWORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = a & b
    union = a | b
    return len(inter) / len(union) if union else 0.0


# Minimum Jaccard score between a button label and a dialog title for the
# auto-wire to fire. 0.34 catches "View Context" vs "View contact Modal"
# (tokens: {view,context} vs {view,contact}; intersection={view},
# union={view,context,contact} → 1/3 ≈ 0.33). Tune up if false positives
# show up in real Figma files.
_DIALOG_TRIGGER_MIN_SCORE = 0.33


def _collect_typed(schema_node: dict, want: str, acc: list[dict] | None = None) -> list[dict]:
    """Depth-first walk yielding every node whose `type` matches `want`."""
    if acc is None:
        acc = []
    if isinstance(schema_node, dict):
        if schema_node.get("type") == want:
            acc.append(schema_node)
        for c in schema_node.get("children") or []:
            _collect_typed(c, want, acc)
    return acc


def _auto_wire_dialog_triggers(page_root_children: list[dict]) -> int:
    """Scan the page tree for Dialog nodes and Button nodes, then set
    `opensDialog` on every button whose label keyword-matches a dialog
    title (Jaccard similarity above the threshold).

    Returns the number of buttons wired. Idempotent — buttons that already
    have a non-empty `opensDialog` are left untouched.

    Multi-match handling: when several buttons score equally well against
    the same dialog (e.g. a list of rows each with a "View Context"
    button), ALL of them get wired. This is the common pattern for
    table/list rows with a per-row detail modal.
    """
    fake_root = {"type": "_root", "children": page_root_children}
    dialogs = _collect_typed(fake_root, "Dialog")
    buttons = _collect_typed(fake_root, "Button")
    if not dialogs or not buttons:
        return 0

    dialog_tokens: list[tuple[str, set[str]]] = []
    for d in dialogs:
        props = d.get("props") or {}
        did = props.get("id") or d.get("id")
        if not did:
            continue
        title_tokens = _tokens_from_label(props.get("title") or "")
        if not title_tokens:
            continue
        dialog_tokens.append((did, title_tokens))
    if not dialog_tokens:
        return 0

    wired = 0
    for b in buttons:
        props = b.setdefault("props", {})
        # Respect explicit prior wiring — only fill in blanks.
        if props.get("opensDialog"):
            continue
        label_tokens = _tokens_from_label(props.get("label") or "")
        if not label_tokens:
            continue
        best_id: str | None = None
        best_score = 0.0
        for did, dtok in dialog_tokens:
            s = _jaccard(label_tokens, dtok)
            if s > best_score:
                best_score = s
                best_id = did
        if best_id and best_score >= _DIALOG_TRIGGER_MIN_SCORE:
            props["opensDialog"] = best_id
            wired += 1
    return wired


def build_page_schema(
    document: dict,
    asset_paths: dict[str, str] | None = None,
) -> BuildResult:
    walked = walk_and_flatten(document)
    tokens = extract_tokens(walked)
    from services.figma_typography_extractor import extract_typography
    tokens["typography"] = extract_typography(walked)

    nodes_by_fid: dict[str, dict] = {}
    fid_to_entry: dict[str, dict] = {}
    children_by_parent_fid: dict[str | None, list[str]] = {}
    incomplete: list[dict] = []

    for entry in walked:
        fid = entry["node"].get("id", "?")
        built = _build_node(entry, asset_paths=asset_paths)
        nodes_by_fid[fid] = built
        fid_to_entry[fid] = entry
        parent_fid = (entry["parent"] or {}).get("id") if entry["parent"] else None
        children_by_parent_fid.setdefault(parent_fid, []).append(fid)
        if built["type"] == "Box":
            incomplete.append({"figma_id": fid, "name": entry["node"].get("name")})

    # Bbox-based layout inference: for any Container/Box without an explicit
    # auto-layout mode, look at its children's absoluteBoundingBox geometry
    # to decide if it's a horizontal row or a vertical stack. This recovers
    # two-column layouts in Figma files where the designer used absolute
    # positioning instead of auto-layout HORIZONTAL.
    for fid, schema_node in nodes_by_fid.items():
        if schema_node["type"] not in ("Container", "Box"):
            continue
        entry = fid_to_entry.get(fid)
        if not entry:
            continue
        if entry["node"].get("_layoutMode") in ("HORIZONTAL", "VERTICAL"):
            continue  # explicit layout — don't override
        child_fids = children_by_parent_fid.get(fid, [])
        child_entries = [
            fid_to_entry[c] for c in child_fids if c in fid_to_entry
        ]
        inferred_type, child_extras = _infer_row_layout_from_bbox(child_entries)
        if not inferred_type:
            continue
        schema_node["type"] = inferred_type
        # When promoting a Container to Row from bbox geometry, children are
        # at FIXED positions in the original Figma frame — they're not meant
        # to wrap. Setting wrap=false makes the Row renderer skip emitting
        # `flex-wrap`, so the row stays one line even when its total width
        # exceeds the viewport. Without this, two 695px panels in a 1391px
        # row wrap onto separate lines on any laptop screen narrower than
        # 1391px — the teal RIGHT panel ends up below the LEFT instead of
        # beside it.
        if inferred_type == "Row":
            schema_node.setdefault("props", {})["wrap"] = False
        # Apply per-child extra classes (parallel list to child_fids).
        # Each entry is a space-separated utility string — small children
        # get `w-[Npx] shrink-0`, large children get `flex-1`. Skip the
        # row-inference width hint when the child already has an explicit
        # `w-[…]` or `flex-1` from Figma's layoutSizing — the FIXED/FILL
        # semantics from the design are higher priority than the bbox-
        # derived guess.
        if child_extras:
            import re as _re
            _WIDTH_RE = _re.compile(r"^(w-|flex-1$|basis-|size-)")
            for cfid, extra in zip(child_fids, child_extras):
                cnode = nodes_by_fid.get(cfid)
                if cnode is None or not extra:
                    continue
                cprops = cnode.setdefault("props", {})
                existing_cn = cprops.get("className") or ""
                existing_tokens = existing_cn.split()
                has_width = any(_WIDTH_RE.match(t) for t in existing_tokens)
                for tok in extra.split():
                    if has_width and _WIDTH_RE.match(tok):
                        continue  # keep designer's explicit sizing
                    if tok not in existing_tokens:
                        existing_tokens.append(tok)
                cprops["className"] = " ".join(existing_tokens)

    # Fold descendant text into the leaf node's headline prop. Required because
    # Figma wraps text in named frames (e.g. "Heading 1" → child TEXT carries
    # the actual characters), so the named wrapper itself has no `characters`.
    # Also fold the inner TEXT's colour / font-size utilities into the wrapper's
    # className so the visible styling is preserved after children are dropped.
    for fid, schema_node in nodes_by_fid.items():
        ntype = schema_node["type"]
        if ntype not in _LEAF_TYPES:
            continue
        props = schema_node.setdefault("props", {})
        folded = _fold_descendant_text(fid_to_entry, children_by_parent_fid, fid)
        if ntype in ("Heading", "Text") and not props.get("content") and folded:
            props["content"] = folded
        elif ntype == "Button" and not props.get("label") and folded:
            props["label"] = folded
        elif ntype == "Link" and not props.get("label") and folded:
            props["label"] = folded
        elif ntype == "Input" and not props.get("placeholder") and folded:
            props["placeholder"] = folded

        # When a Button wraps a Figma frame whose children include an Icon
        # leaf with an exported SVG asset (e.g. nav item "Settings Button" →
        # icon + label), surface the icon URL onto the Button via `iconSrc`
        # so the rendered button still shows the icon instead of dropping it
        # when leaf-folding strips Button's children. The library Button reads
        # `iconSrc` as a URL fallback whenever `icon` (lucide name) isn't set.
        if ntype == "Button" and not props.get("icon") and not props.get("iconSrc"):
            icon_src = _first_icon_descendant_src(
                fid_to_entry, children_by_parent_fid, fid, asset_paths,
            )
            if icon_src:
                props["iconSrc"] = icon_src

        # Inherit text colour + font-size + weight from the first TEXT descendant
        # — only for the text-bearing leaves where the wrapper itself doesn't
        # carry styling. Image / Icon / Checkbox don't need this.
        if ntype in ("Heading", "Text", "Button", "Link"):
            inner = _first_text_descendant_classes(
                fid_to_entry, children_by_parent_fid, fid,
            )
            if inner:
                existing = (props.get("className") or "").split()
                # Don't overwrite a value the wrapper already supplied for the
                # same utility kind (e.g. wrapper already has `text-[14px]`).
                def kind(c: str) -> str:
                    if c.startswith("text-[") and c.endswith("px]"):
                        return "text-size"
                    if c.startswith("text-["):
                        return "text-color"
                    if c.startswith("font-"):
                        return "font"
                    return "other"
                have = {kind(c) for c in existing}
                merged = list(existing) + [c for c in inner if kind(c) not in have]
                cn = " ".join(merged).strip()
                if cn:
                    props["className"] = cn

    # Reattach children — but NEVER for leaf types. The descendant Box nodes
    # that compose a Figma icon (vector layers) get the brand fill colour
    # projected onto them by node_to_utility_classes; leaving them attached
    # produces stacked red squares. Their text has already been folded above.
    for fid, schema_node in nodes_by_fid.items():
        if schema_node["type"] in _LEAF_TYPES:
            schema_node["children"] = []
            continue
        schema_node["children"] = [
            nodes_by_fid[c] for c in children_by_parent_fid.get(fid, [])
        ]

    root_fid = walked[0]["node"].get("id") if walked else None
    root = nodes_by_fid.get(root_fid) if root_fid else None
    if not root:
        root = {"id": "empty", "type": "Stack", "props": {}, "children": []}

    page = {
        "schemaVersion": "2.0",
        "id": _id_for(document.get("id", "page")),
        "title": document.get("name", "Untitled"),
        "dataSources": [],
        "children": root["children"] if root.get("type") == "Stack" else [root],
    }

    # Polish heuristics — pattern-driven cleanup that tightens the schema
    # to match how a human would naturally author it:
    #   - Root card → max-width + centering
    #   - Container[Checkbox, Text] → flex row
    #   - Row[Container, Link] → justify-between
    #   - Icon-tile Stack → fixed-square sizing
    #   - Form's last Button → w-full
    _apply_polish_heuristics(page["children"])

    # Auto-wire dialog triggers: for every Button whose label keyword-matches
    # a Dialog's title, set props.opensDialog = dialog.id. Runs last so it
    # sees the fully-built tree (labels folded, leaf children cleaned up).
    _auto_wire_dialog_triggers(page["children"])

    return BuildResult(
        page=page, tokens=tokens,
        complete=(len(incomplete) == 0),
        incomplete_nodes=incomplete,
    )
