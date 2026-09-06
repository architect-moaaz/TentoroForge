"""The Figma file as a design reference (PRD §44, §47, §48, §53, §55).

What this is *not* is the point of the module, so it goes first.

§118: *"Figma is not simply converted into JSX."* The old platform did exactly
that — frame in, page schema out — and inherited every gap the design had. A
Figma file drawn for a demo has four screens and no error states, no empty
states, no permission-denied view, no forgot-password flow (§54). Converting it
directly produces an application with the same four screens, and the missing
ninety percent never becomes visible as missing.

§48 gives the correct reading: Figma is **strong design evidence, not complete
requirements**. A frame labelled ``Approve Candidate`` proves a button exists.
It does not say who may approve, under what conditions, what it writes, or what
happens when it is refused.

So this module produces a *reference*: the thing a developer keeps open on the
second monitor. The DAG builds the application from the Blueprint, and composes
every page against this reference, exactly as a developer builds from a ticket
while matching the design. §40 ranks it: a user-provided Figma design outranks
the application's own design system, domain patterns, and anything A2UI would
recommend on its own — and is outranked only by what the user says right now.

What that requires the reference to carry
-----------------------------------------
§53 lists what the generated application must preserve: layout, spacing,
typography, visual hierarchy, color, information density, component hierarchy,
navigation, interaction patterns. Each has a home below:

* :class:`DesignTokens`     — color, typography, spacing, radius, elevation (§47)
* :class:`ScreenRef`        — layout, density, hierarchy, and a rendered image
* :class:`ComponentRef`     — component hierarchy, variants (§46)
* :class:`InteractionRef`   — navigation and interaction patterns (§55)

The rendered image on :class:`ScreenRef` is load-bearing rather than decorative.
It is what makes "does the build match the design" answerable by looking, which
is how a human answers it, and it is the input a visual check needs later.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from services.figma.gateway import FigmaGateway, FigmaGatewayError
from services.figma.url import FigmaTarget


# ---------------------------------------------------------------------------
# The reference
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScreenRef:
    """One frame that plausibly represents an application screen.

    ``looks_like_screen`` is recorded, not enforced. §49 requires inference to
    carry confidence rather than being filtered on a rule, because a file's
    frame naming is a convention this platform does not control — and a filter
    that guesses wrong deletes evidence with no trace that it did.
    """

    node_id: str
    name: str
    canvas: str = ""
    width: float = 0.0
    height: float = 0.0
    looks_like_screen: bool = True
    #: §53 — the rendered frame, as a data URI or fetched asset reference.
    image: str = ""
    #: Structure as Figma describes it, kept raw. §14 evidence cites into this.
    structure: dict[str, Any] = field(default_factory=dict)

    @property
    def evidence_locator(self) -> str:
        return f"{self.canvas}/{self.name}".strip("/")


@dataclass(frozen=True)
class ComponentRef:
    """A reusable Figma component — a §46 candidate for the UI Registry."""

    node_id: str
    name: str
    variants: tuple[str, ...] = ()
    instance_count: int = 0
    #: Set when the file carries Code Connect mappings (§46).
    code_component: str = ""


@dataclass(frozen=True)
class InteractionRef:
    """A prototype link — §55 evidence for navigation and flow."""

    source_node: str
    target_node: str
    trigger: str = ""
    action: str = ""


@dataclass(frozen=True)
class DesignTokens:
    """§47's extracted design system — the starting Application Design System.

    Deliberately shallow dicts rather than a typed token model: this is what
    Figma reported, and normalising it into the platform's own token vocabulary
    is the Design System Service's job (§97), not the extractor's. Reshaping
    here would lose the Figma names, and the Figma names are what make a token
    traceable back to the file a user can open.
    """

    colors: dict[str, str] = field(default_factory=dict)
    typography: dict[str, Any] = field(default_factory=dict)
    spacing: dict[str, Any] = field(default_factory=dict)
    radius: dict[str, Any] = field(default_factory=dict)
    elevation: dict[str, Any] = field(default_factory=dict)
    other: dict[str, Any] = field(default_factory=dict)

    def is_empty(self) -> bool:
        return not any((self.colors, self.typography, self.spacing,
                        self.radius, self.elevation, self.other))


@dataclass
class DesignReference:
    """Everything extracted from one Figma file, as evidence.

    ``source_id`` is what §14 evidence entries cite (``source: FIGMA-001``),
    so it must be stable for the life of the connection — it identifies the
    file, not the extraction run.
    """

    target: FigmaTarget
    source_id: str = "FIGMA-001"
    #: ``figma`` or ``uxpilot`` — the tool the design lives in. Every field on
    #: this reference is shaped by Figma, which came first; a UX Pilot
    #: extraction fills the same shape (a design is a screen, the page is the
    #: file) so the store, the brief and the layout read one thing.
    provider: str = "figma"
    screens: list[ScreenRef] = field(default_factory=list)
    components: list[ComponentRef] = field(default_factory=list)
    interactions: list[InteractionRef] = field(default_factory=list)
    tokens: DesignTokens = field(default_factory=DesignTokens)
    #: §102 — what could not be extracted, so a thin reference is visibly thin
    #: rather than quietly passing as a complete one.
    gaps: list[str] = field(default_factory=list)

    def evidence_for(self, node_id: str, locator: str = "") -> dict[str, str]:
        """One ``requirements[].evidence[]`` entry, in the §14 shape."""
        entry = {"type": self.provider or "figma", "source": self.source_id, "node": node_id}
        if locator:
            entry["locator"] = locator
        return entry

    def screen(self, node_id: str) -> ScreenRef | None:
        return next((s for s in self.screens if s.node_id == node_id), None)

    def summary(self) -> dict[str, int]:
        """Counts, for §50's "I found 14 screens, five modules..." opener."""
        return {
            "screens": sum(1 for s in self.screens if s.looks_like_screen),
            "frames": len(self.screens),
            "components": len(self.components),
            "interactions": len(self.interactions),
            "colorTokens": len(self.tokens.colors),
            "typographyTokens": len(self.tokens.typography),
        }


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------

#: Frames named like these are almost certainly not application screens.
#: Used to set ``looks_like_screen=False``, never to drop the frame.
_NON_SCREEN = re.compile(
    r"^(?:cover|thumbnail|logo|icons?|assets?|colou?rs?|typography|"
    r"styleguide|style ?guide|components?|scratch|wip|archive|old|"
    r"notes?|spacer|divider)\b",
    re.I,
)


async def extract(
    gateway: FigmaGateway,
    target: FigmaTarget,
    *,
    source_id: str = "FIGMA-001",
    max_screens: int = 40,
    with_images: bool = True,
) -> DesignReference:
    """Build a :class:`DesignReference` from a live Figma file.

    Every step is independently recoverable: a file with no published
    variables still yields screens, and a frame whose render fails still
    yields structure. §102 wants a Figma connection failure distinguished from
    an empty design, so a step that fails records a gap and the extraction
    continues — but a failure to reach Figma *at all* propagates, because a
    reference built from nothing is not a thin reference, it is a wrong one.
    """
    ref = DesignReference(target=target, source_id=source_id)

    # §44 — the file's pages, frames and geometry. This one is not optional:
    # without it there is no reference, and continuing would produce an empty
    # DesignReference that reads downstream as "the design has no screens".
    metadata = await gateway.call(
        "get_metadata", file_key=target.file_key, node_id=target.node_id
    )
    ref.screens = _screens_from_metadata(metadata, limit=max_screens)
    if not ref.screens:
        ref.gaps.append("no frames found in the file or selected node")

    # §47 — the design system as Figma records it.
    try:
        variables = await gateway.call(
            "get_variable_defs", file_key=target.file_key, node_id=target.node_id
        )
        ref.tokens = _tokens_from_variables(variables)
    except FigmaGatewayError as exc:
        ref.gaps.append(f"design tokens unavailable ({exc.kind})")
    if ref.tokens.is_empty():
        # Not a failure: plenty of real files style everything locally without
        # publishing variables. It *is* something the design system agent must
        # know, because it changes where the token values have to come from.
        ref.gaps.append("file publishes no design variables; tokens must be "
                        "derived from the frames themselves")

    # §44/§53 — structure per screen, and §55 — prototype interactions.
    for screen in list(ref.screens):
        if not screen.looks_like_screen:
            continue
        try:
            context = await gateway.call(
                "get_design_context", file_key=target.file_key,
                node_id=screen.node_id,
                # WITHOUT THIS THE SERVER ANSWERS WITH METADATA INSTEAD OF CODE,
                # silently, whenever the node is large — its own words: "code
                # should always be returned, instead of returning just metadata
                # if the output size is too large".
                #
                # A real dashboard frame (3902x1975, 104 nested elements) came
                # back as 139KB of the same `<frame>` markup `get_metadata`
                # returns. `_structure_from_code` stored it as `code`, so the
                # reference looked complete and every consumer of it — the
                # label harvest, the asset list, the whole pixel path, which
                # parses React JSX — silently had nothing to work with.
                #
                # A screen big enough to be worth reproducing is exactly the
                # screen that trips the size cutoff, so this is not an edge.
                forceCode=True,
            )
        except FigmaGatewayError as exc:
            ref.gaps.append(f"no structure for {screen.name} ({exc.kind})")
            continue
        _attach_structure(ref, screen, context)

    # §55 wants navigation, modal relationships and drill-down from prototype
    # links. Generated TSX cannot express them, so when that is all the server
    # returned, the interaction graph is not empty — it is unavailable, and
    # navigation has to be inferred and confirmed (§49, §50) instead of read.
    if not ref.interactions and any(
        (s.structure or {}).get("source") == "design_context_code" for s in ref.screens
    ):
        ref.gaps.append(
            "prototype interactions unavailable: this server returns design "
            "context as code, which carries no links (§55) — navigation must "
            "be inferred and confirmed with the user"
        )

    # §46 — components that already map to code, when the file says so.
    try:
        mapping = await gateway.call(
            "get_code_connect_map", file_key=target.file_key, node_id=target.node_id
        )
        _attach_code_connect(ref, mapping)
    except FigmaGatewayError:
        # Code Connect is opt-in and most files have none. Absence is normal
        # and says nothing about the design, so it is not recorded as a gap.
        pass

    if with_images:
        await _attach_images(gateway, ref)

    return ref


async def _attach_images(gateway: FigmaGateway, ref: DesignReference) -> None:
    """§53 — render each screen, so fidelity is checkable by looking."""
    for index, screen in enumerate(ref.screens):
        if not screen.looks_like_screen:
            continue
        try:
            blocks = await gateway.call(
                "get_screenshot",
                file_key=ref.target.file_key,
                node_id=screen.node_id,
            )
        except FigmaGatewayError as exc:
            ref.gaps.append(f"no render for {screen.name} ({exc.kind})")
            continue
        image = next((b for b in blocks if b.get("type") == "image"), None)
        if not image:
            continue
        mime = image.get("mimeType") or "image/png"
        ref.screens[index] = _replace(
            screen, image=f"data:{mime};base64,{image.get('data', '')}"
        )


# ---------------------------------------------------------------------------
# Normalisers
# ---------------------------------------------------------------------------

def _replace(screen: ScreenRef, **changes: Any) -> ScreenRef:
    from dataclasses import replace
    return replace(screen, **changes)


def payload_of(blocks: Iterable[dict[str, Any]]) -> Any:
    """The useful body of a tool result.

    Servers answer in one of three ways — structured content, a JSON string in
    a text block, or prose. All three arrive here; the caller should not have
    to know which one it got.
    """
    items = list(blocks or [])
    for block in items:
        if block.get("type") == "structured":
            return block.get("data")
    text = "\n".join(b.get("text", "") for b in items if b.get("type") == "text")
    if not text.strip():
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


#: Element names the Dev Mode MCP uses, mapped to the Figma node types the
#: rest of this module already understands.
_MARKUP_TYPES: dict[str, str] = {
    "canvas": "CANVAS",
    "frame": "FRAME",
    "component": "COMPONENT",
    "componentset": "COMPONENT_SET",
    "component-set": "COMPONENT_SET",
    "section": "SECTION",
    "instance": "INSTANCE",
    "group": "GROUP",
    "text": "TEXT",
    "vector": "VECTOR",
    "rectangle": "RECTANGLE",
    "ellipse": "ELLIPSE",
    "line": "LINE",
    "image": "IMAGE",
}


def _nodes_from_markup(text: str) -> dict | None:
    """`get_metadata` as the Dev Mode MCP actually answers it — XML, not JSON.

    THE SAME SURPRISE `_attach_structure` RECORDS ONE FUNCTION BELOW: the
    server answers in the shape it finds useful, and this package assumed the
    REST API's node tree. `payload_of` falls back to returning the raw text
    when it will not parse as JSON, `_walk_nodes` then walks a string and finds
    nothing, and a file with a hundred frames extracted as "no frames found in
    the file or selected node" — a wrong reference that looked merely thin.

    Measured on a real file: 141KB of markup, 104 `<frame>` elements, read as
    zero screens.

    Converted into the dict shape `_walk_nodes` already consumes rather than
    given a second walker, so everything downstream — the screen filter, the
    component harvest, the interactions — is untouched. Returns None when the
    text is not markup either, which keeps "we got prose" distinguishable from
    "we got a tree with nothing in it".
    """
    import xml.etree.ElementTree as ET

    body = (text or "").strip()
    start, end = body.find("<"), body.rfind(">")
    if start < 0 or end <= start:
        return None
    try:
        root = ET.fromstring(body[start:end + 1])
    except ET.ParseError:
        return None

    # A SCREEN IS A FRAME THE PAGE HOLDS, NOT EVERY FRAME. Dev Mode markup
    # writes `<frame>` for groups as well, so a real file reported 40 screens
    # of which one was a screen — the other 39 were "Group", "Mask group" and
    # "Clip path group" nested inside it. `_NON_SCREEN` filters by name
    # (cover, thumbnail, logo...) and none of those match.
    #
    # Depth is the fact that separates them: on a canvas, the screens are its
    # direct children; a `<frame>` deeper than that is part of one. Deeper
    # frames are typed GROUP, which `_screens_from_metadata` already ignores,
    # and nothing is lost — a screen's internals come from its design context,
    # not from this tree.
    #
    # When a node was selected rather than a page, the root IS the screen and
    # is kept as one.
    root_is_canvas = _MARKUP_TYPES.get(root.tag.lower()) == "CANVAS"

    def convert(element: Any, depth: int = 0) -> dict:
        attrib = element.attrib
        kind = _MARKUP_TYPES.get(element.tag.lower(), element.tag.upper())
        if kind == "FRAME" and root_is_canvas and depth > 1:
            kind = "GROUP"
        node: dict[str, Any] = {
            "type": kind,
            "id": attrib.get("id", ""),
            "name": attrib.get("name", ""),
        }
        box: dict[str, float] = {}
        for key in ("x", "y", "width", "height"):
            raw = attrib.get(key)
            if raw is None:
                continue
            try:
                box[key] = float(raw)
            except (TypeError, ValueError):
                continue
        if box:
            # Under the name the REST payload uses, so `_screens_from_metadata`
            # reads one field regardless of which server answered.
            node["absoluteBoundingBox"] = box
        children = [convert(child, depth + 1) for child in element]
        if children:
            node["children"] = children
        return node

    return convert(root)


def _screens_from_metadata(blocks, *, limit: int) -> list[ScreenRef]:
    payload = payload_of(blocks)
    if isinstance(payload, str):
        payload = _nodes_from_markup(payload) or payload
    else:
        # A REST node tree types every frame FRAME, nested or not; the markup
        # converter demotes frames below a canvas's children to groups, and
        # the same rule applies here or a screen's inner frames read as
        # screens of their own.
        payload = _demote_nested_frames(payload)
    nodes = _walk_nodes(payload)

    screens: list[ScreenRef] = []
    for canvas, node in nodes:
        node_type = str(node.get("type") or "").upper()
        if node_type not in ("FRAME", "COMPONENT", "COMPONENT_SET", "SECTION"):
            continue
        name = str(node.get("name") or "").strip()
        if not name:
            continue
        box = node.get("absoluteBoundingBox") or node.get("boundingBox") or {}
        screens.append(ScreenRef(
            node_id=str(node.get("id") or ""),
            name=name,
            canvas=canvas,
            width=float(box.get("width") or node.get("width") or 0),
            height=float(box.get("height") or node.get("height") or 0),
            looks_like_screen=not bool(_NON_SCREEN.match(name)),
            # THE SCREEN'S GEOMETRY, KEPT. The metadata carries every element's
            # box, auto-layout or not; the design context code does not for
            # auto-layout, and a dashboard whose cards took their size from
            # the layout had no region to look at. Boxes are in the screen's
            # own coordinates, which is how the crops and the transform read.
            structure={"boxes": _boxes_under(node, box)},
        ))
        if len(screens) >= limit:
            break
    return [s for s in screens if s.node_id]


def _demote_nested_frames(payload: Any) -> Any:
    """Frames below a canvas's own children — or below a selected root frame
    when no canvas is in the tree — become groups, as the markup path already
    reads them. A document root is neither: its canvases decide."""
    if not isinstance(payload, dict):
        return payload

    def has_canvas(node: Any) -> bool:
        if not isinstance(node, dict):
            return False
        if str(node.get("type") or "").upper() == "CANVAS":
            return True
        return any(has_canvas(c) for c in node.get("children") or [])

    def convert(node: dict, below_screen: bool, parent_is_canvas: bool, rootless: bool) -> dict:
        out = dict(node)
        kind = str(node.get("type") or "").upper()
        is_screen_level = parent_is_canvas or (rootless and not below_screen)
        if kind == "FRAME" and not is_screen_level:
            out["type"] = "GROUP"
        kids = node.get("children") or []
        if kids:
            child_below = below_screen or (kind == "FRAME" and is_screen_level) or kind == "GROUP"
            out["children"] = [convert(c, child_below, kind == "CANVAS", rootless) if isinstance(c, dict) else c
                               for c in kids]
        return out

    root = payload.get("document") if isinstance(payload.get("document"), dict) else payload
    rootless = not has_canvas(root)
    converted = convert(root, False, False, rootless)
    return {**payload, "document": converted} if root is not payload else converted


def _boxes_under(node: dict, origin: dict) -> list[dict]:
    """Every descendant's box relative to the screen's own top-left."""
    ox, oy = float(origin.get("x") or 0), float(origin.get("y") or 0)
    out: list[dict] = []

    def walk(n: dict) -> None:
        for child in n.get("children") or []:
            if not isinstance(child, dict):
                continue
            b = child.get("absoluteBoundingBox") or child.get("boundingBox") or {}
            if child.get("id") and b.get("width") is not None and b.get("height") is not None:
                out.append({"id": str(child["id"]), "name": str(child.get("name") or ""),
                            "x": float(b.get("x") or 0) - ox, "y": float(b.get("y") or 0) - oy,
                            "width": float(b["width"]), "height": float(b["height"])})
            walk(child)

    walk(node)
    return out


def _walk_nodes(payload: Any, canvas: str = "") -> list[tuple[str, dict]]:
    """Flatten Figma's node tree into ``(canvas name, node)`` pairs.

    Figma nests ``document → CANVAS → FRAME → …`` and the MCP may hand back
    any level of that depending on whether a node was selected. Walking from
    whatever arrives keeps the caller from having to know which.
    """
    out: list[tuple[str, dict]] = []
    if isinstance(payload, dict):
        if "document" in payload:
            return _walk_nodes(payload["document"], canvas)
        if "nodes" in payload and isinstance(payload["nodes"], dict):
            for entry in payload["nodes"].values():
                out += _walk_nodes(entry.get("document", entry), canvas)
            return out
        node_type = str(payload.get("type") or "").upper()
        here = str(payload.get("name") or "") if node_type == "CANVAS" else canvas
        if payload.get("id"):
            out.append((canvas, payload))
        for child in payload.get("children") or []:
            out += _walk_nodes(child, here)
    elif isinstance(payload, list):
        for item in payload:
            out += _walk_nodes(item, canvas)
    return out


def _tokens_from_variables(blocks) -> DesignTokens:
    """§47 — sort Figma variables into the design-system buckets.

    Figma variables are a flat ``name → value`` map and the name carries the
    grouping (``color/brand/primary``, ``spacing/md``). Bucketing on the name
    is how the file's own author intended them to be read.
    """
    payload = payload_of(blocks)
    if not isinstance(payload, dict):
        return DesignTokens()

    flat = payload.get("variables") if isinstance(payload.get("variables"), dict) else payload

    colors: dict[str, str] = {}
    typography: dict[str, Any] = {}
    spacing: dict[str, Any] = {}
    radius: dict[str, Any] = {}
    elevation: dict[str, Any] = {}
    other: dict[str, Any] = {}

    for name, value in (flat or {}).items():
        key = str(name)
        low = key.lower()
        if _is_colour(low, value):
            colors[key] = str(value)
        elif any(t in low for t in ("font", "text", "type", "letter", "line-height", "leading")):
            typography[key] = value
        elif any(t in low for t in ("radius", "corner", "rounded")):
            radius[key] = value
        elif any(t in low for t in ("shadow", "elevation", "depth", "blur")):
            elevation[key] = value
        elif any(t in low for t in ("space", "spacing", "gap", "size", "padding", "margin")):
            spacing[key] = value
        else:
            other[key] = value

    return DesignTokens(colors, typography, spacing, radius, elevation, other)


def _is_colour(name: str, value: Any) -> bool:
    if any(t in name for t in ("color", "colour", "fill", "stroke", "background", "border")):
        return True
    return isinstance(value, str) and bool(
        re.match(r"^#[0-9a-f]{3,8}$|^rgba?\(", value.strip(), re.I)
    )


def _attach_structure(ref: DesignReference, screen: ScreenRef, blocks) -> None:
    """Record a screen's structure and harvest what the shape actually carries.

    ``get_design_context`` answers in one of two shapes and the difference
    matters more than it looks. The hosted Figma MCP returns **generated TSX
    source** — the design expressed as code — while other servers and the REST
    API return a JSON node tree. Code carries the screen's text, its assets and
    its composition; it does *not* carry node ids, component metadata or
    prototype links, because those are not expressible in JSX.

    Assuming the tree shape and receiving code was the bug worth catching here:
    the walk finds nothing, no error is raised, and the reference reports a
    design with no components and no navigation. §102 wants absence
    distinguished from failure, so each shape harvests what it genuinely has
    and :attr:`DesignReference.gaps` records what it cannot.
    """
    payload = payload_of(blocks)
    index = ref.screens.index(screen)

    if isinstance(payload, str):
        ref.screens[index] = _replace(screen, structure={
            **_structure_from_code(payload), "boxes": (screen.structure or {}).get("boxes") or []})
        return

    if not isinstance(payload, dict):
        ref.gaps.append(f"no usable structure for {screen.name}")
        return

    ref.screens[index] = _replace(
        screen, structure={**(payload if isinstance(payload, dict) else {"raw": payload}),
                           "boxes": (screen.structure or {}).get("boxes") or []})

    known = {c.node_id for c in ref.components}
    for _canvas, node in _walk_nodes(payload):
        node_type = str(node.get("type") or "").upper()
        node_id = str(node.get("id") or "")
        if node_type in ("COMPONENT", "COMPONENT_SET") and node_id not in known:
            known.add(node_id)
            ref.components.append(ComponentRef(
                node_id=node_id,
                name=str(node.get("name") or "").strip(),
                variants=tuple(
                    str(v) for v in (node.get("variantProperties") or {}).keys()
                ),
            ))
        # §55 — prototype links, wherever Figma hung them.
        for link in _interactions_of(node):
            if link not in ref.interactions:
                ref.interactions.append(link)


#: Figma's MCP serves rendered assets from this host; the URLs expire, so they
#: are recorded as evidence of *what* the screen shows, not as a durable src.
_ASSET_URL = re.compile(
    r"https://www\.figma\.com/api/mcp/asset/[A-Za-z0-9_-]+"
    r"|https?://(?:127\.0\.0\.1|localhost):3845/assets/[A-Za-z0-9_-]+(?:\.[A-Za-z0-9]+)?"
)

#: Visible copy in generated TSX: JSX text nodes and quoted string props that
#: read like labels. This is the screen's vocabulary, and §49's inference of
#: capability from a design leans on it directly — "Schedule Interview" on a
#: button is the evidence that interview scheduling is a capability.
_JSX_TEXT = re.compile(r">\s*([A-Z][^<>{}\n]{2,60}?)\s*<")


def _structure_from_code(code: str) -> dict[str, Any]:
    """What generated TSX can honestly yield as design reference."""
    labels: list[str] = []
    for match in _JSX_TEXT.finditer(code):
        text = match.group(1).strip()
        if text and text not in labels:
            labels.append(text)
    return {
        "source": "design_context_code",
        "code": code,
        "labels": labels,
        "assets": sorted(set(_ASSET_URL.findall(code))),
    }


def _interactions_of(node: dict) -> list[InteractionRef]:
    out: list[InteractionRef] = []
    source = str(node.get("id") or "")
    for interaction in node.get("interactions") or []:
        trigger = str((interaction.get("trigger") or {}).get("type") or "")
        for action in interaction.get("actions") or []:
            destination = action.get("destinationId") or action.get("destination")
            if not destination:
                continue
            out.append(InteractionRef(
                source_node=source,
                target_node=str(destination),
                trigger=trigger,
                action=str(action.get("navigation") or action.get("type") or ""),
            ))
    # Older payloads expose a single transition instead of `interactions`.
    if node.get("transitionNodeID"):
        out.append(InteractionRef(
            source_node=source,
            target_node=str(node["transitionNodeID"]),
            trigger="ON_CLICK",
            action="NAVIGATE",
        ))
    return out


def _attach_code_connect(ref: DesignReference, blocks) -> None:
    """§46 — components the file already maps to real code."""
    payload = payload_of(blocks)
    if not isinstance(payload, dict):
        return
    for node_id, entry in payload.items():
        name = ""
        if isinstance(entry, dict):
            name = str(entry.get("codeConnectName") or entry.get("component") or "")
        elif isinstance(entry, str):
            name = entry
        if not name:
            continue
        for index, component in enumerate(ref.components):
            if component.node_id == str(node_id):
                from dataclasses import replace
                ref.components[index] = replace(component, code_component=name)
                break
        else:
            ref.components.append(ComponentRef(
                node_id=str(node_id), name=name, code_component=name
            ))
