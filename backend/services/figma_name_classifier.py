"""Map a Figma layer name (+ Figma node type) to a schema node type +
initial props. The lookup is an intentional long switch — readability beats
cleverness. Unknown names fall through to Box (a tolerant container the
renderer treats as a passthrough). The caller can flag those nodes for
optional LLM fallback.

Layer name patterns are drawn from real Figma files we ingest; each rule
documents the matching pattern. Order matters: specific before generic.
"""
from __future__ import annotations
import re

HEADING_RE = re.compile(r"^heading\s*(\d)$", re.I)


def classify(
    name: str,
    figma_type: str,
    child_count: int = 0,
) -> tuple[str, dict]:
    """Map a Figma node name + type → (schema_type, extra props).

    `child_count` is optional — when supplied (typically from the walker
    which has access to the raw children array) it suppresses FRAME→Image
    classification for frames that hold a whole UI tree. A Figma frame
    named "Background Image" with 30 children is a screenshot / mockup
    frame, NOT an image asset; classifying it as Image and exporting it
    as a single SVG loses the entire UI structure. Default 0 keeps the
    classifier safe to call without children context (older callers).
    """
    n = (name or "").strip()
    if not n:
        return "Box", {}
    lower = n.lower()

    # Headings: "Heading 1" .. "Heading 6"
    m = HEADING_RE.match(lower)
    if m:
        return "Heading", {"level": int(m.group(1))}

    # *-Title → Heading 4 (common in Figma where the wrapper is "Heading 4" and
    # the inner TEXT carries the content but is named "X Title")
    if lower.endswith(" title"):
        return "Heading", {"level": 4}

    # Body text — variants
    if lower in {"paragraph", "body", "description"}:
        return "Text", {}
    if lower.endswith(" description") or lower.endswith(" subtitle") or lower.endswith(" text"):
        return "Text", {}

    # Form primitives — specific before generic
    if lower == "checkbox":
        return "Checkbox", {}
    if lower == "form" or lower.endswith(" form"):
        return "Form", {}
    if lower == "button" or lower.endswith(" button"):
        return "Button", {}
    if lower == "link" or lower.endswith(" link"):
        return "Link", {}
    # Inputs — extract type from name
    if "email input" in lower:
        return "Input", {"type": "email"}
    if "password input" in lower:
        return "Input", {"type": "password"}
    if lower == "input" or lower.endswith(" input"):
        return "Input", {"type": "text"}
    # Placeholder text inside inputs
    if lower.endswith(" placeholder"):
        return "Text", {"role": "placeholder"}

    # Labels — exact "label" (a container row: checkbox + text) is a Container;
    # "X Label" (a text node naming a field) maps to Text with role label.
    if lower == "label":
        return "Container", {}
    if lower == "primitive.label" or lower.endswith(" label"):
        return "Text", {"role": "label"}

    # Media
    if "logo" in lower and ("image" in lower or figma_type == "RECTANGLE" or figma_type == "FRAME"):
        return "Image", {"alt": "Logo"}
    if lower == "icon" or lower.endswith(" icon"):
        return "Icon", {}
    # Image classification — be tight. "image" in a frame name often
    # describes a Figma documentation frame ("Background Image" wrapping
    # a whole dashboard mockup, "Hero Section Image" wrapping a marketing
    # section) rather than a real image asset. Only classify when the
    # name is an unambiguous image asset reference AND the node looks
    # like one (RECTANGLE with an image fill, or a leaf FRAME with no
    # auto-layout / children).
    is_image_name = (
        lower == "image"
        or lower.startswith("image ")        # "Image 1", "Image-12"
        or lower.endswith(" image")           # "Background Image", "Hero Image"
        or lower.endswith(".png") or lower.endswith(".jpg")
        or lower.endswith(".jpeg") or lower.endswith(".webp")
    )
    if is_image_name:
        # RECTANGLE/VECTOR nodes are real image leaves — always Image.
        if figma_type in ("RECTANGLE", "VECTOR"):
            return "Image", {"alt": n}
        # FRAME nodes — Image ONLY when the frame is a true leaf (no
        # children). A FRAME named "Background Image" with descendants
        # is a documentation / mockup frame, NOT an asset; classifying
        # it as Image would either (a) export the whole UI tree as one
        # SVG screenshot (pre-fix) or (b) drop the UI tree entirely
        # because Image is treated as a leaf node type and children get
        # stripped. Falling through to Box/Container/Stack/Row lets the
        # walker descend and classify each piece individually.
        if figma_type == "FRAME" and child_count == 0:
            return "Image", {"alt": n}
    # Generic image keyword without a specific suffix → fall through to
    # Box/Container so the children get classified individually.

    # Overlays — modal / dialog / popup / drawer frames + "View *" panels.
    # Figma designers commonly name modal frames as "Modal", "Dialog",
    # "View contact", "Edit profile", "Confirm delete", etc. We treat any
    # frame whose name starts with "View " / "Edit " / "Create " followed
    # by a noun as a Dialog candidate too — those are conventional
    # CRUD-style modal frame names.
    if (lower in {"modal", "dialog", "popup", "overlay", "drawer", "sheet"}
        or lower.endswith(" modal") or lower.endswith(" dialog")
        or lower.endswith(" popup") or lower.endswith(" drawer")
        or lower.endswith(" overlay") or lower.endswith(" sheet")):
        # Use the original-cased name as a fallback dialog title.
        title = n if n.lower() not in {"modal","dialog","popup","overlay","drawer","sheet"} else ""
        return "Dialog", ({"title": title} if title else {})

    # Layout containers
    if lower == "container" or lower == "wrapper":
        return "Container", {}

    # Raw Figma TEXT nodes without a recognized name (e.g. chart axis labels
    # "Jun"/"16000", table cell strings, free-floating annotations) must still
    # become Text so their `characters` content propagates onto props.content.
    # Falling through to Box silently drops the text and leaves the rendered
    # output with empty styled rectangles.
    if figma_type == "TEXT":
        return "Text", {}

    return "Box", {}


def refine_container_type(node_with_meta: dict) -> str:
    """Pick Stack/Row/Grid/Container based on the walked node's auto-layout meta.
    Called only after classify() returned 'Container'.

    Rules:
      _layoutMode == "HORIZONTAL" and _layoutWrap == "WRAP" → "Grid"
      _layoutMode == "HORIZONTAL"                          → "Row"
      _layoutMode == "VERTICAL"                            → "Stack"
      otherwise                                            → "Container"
    """
    layout_mode = node_with_meta.get("_layoutMode")
    layout_wrap = node_with_meta.get("_layoutWrap")

    if layout_mode == "HORIZONTAL" and layout_wrap == "WRAP":
        return "Grid"
    if layout_mode == "HORIZONTAL":
        return "Row"
    if layout_mode == "VERTICAL":
        return "Stack"

    return "Container"


# --------------------------------------------------------------------------- #
# Spec D Wave 5 — LLM classifier fallback (additive, flag-gated).             #
# The keyword table remains authoritative. When the keyword table shrugs      #
# (returns ``Box`` for an unknown layer name), and the FORGE_FIGMA_LLM flag   #
# is set with a populated component registry, we ask the LLM whether one of   #
# the *registered* components fits. Registry-safety is enforced inside        #
# ``classify_figma_name_llm`` — the LLM cannot invent a component that isn't  #
# in the closed list.                                                         #
# --------------------------------------------------------------------------- #

def classify_with_llm(
    name: str,
    figma_type: str,
    child_count: int = 0,
    *,
    neighbors: list[str] | None = None,
) -> tuple[str, dict]:
    """Keyword-first wrapper around :func:`classify`. Falls through to the
    Wave 5 LLM classifier when the keyword table returns the safe
    ``Box`` default and the LLM path is eligible.
    """
    schema_type, extra = classify(name, figma_type, child_count=child_count)
    if schema_type != "Box":
        return schema_type, extra

    from .figma_llm_ctx import (
        figma_llm_enabled,
        get_component_registry,
        get_name_query_fn,
    )
    if not figma_llm_enabled():
        return schema_type, extra
    registry = get_component_registry()
    if not registry:
        return schema_type, extra

    try:
        from .figma_name_llm import classify_figma_name_llm
        pick = classify_figma_name_llm(
            name,
            node_type=figma_type,
            neighbors=list(neighbors or []),
            component_registry=registry,
            query_fn=get_name_query_fn(),
        )
        # classify_figma_name_llm already enforces registry-safety: the
        # only strings it will hand back are either a registered
        # component or the string "Box".
        if pick.component and pick.component != "Box":
            return pick.component, {}
    except Exception:  # noqa: BLE001
        pass
    return schema_type, extra
