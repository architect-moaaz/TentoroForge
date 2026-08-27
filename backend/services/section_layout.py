"""Section layout, enforced once over whatever composed the page.

Why this is its own module
--------------------------
Two things write a dashboard: the A2UI composer and the deterministic
maquette/sub-dashboard composers. A2UI gets first refusal and writes nothing
unless its composition clears the substance floor, so the deterministic side
owns the slot on every decline — and owns sub-dashboards, collections and
records outright.

That is a reasonable split on CONTENT. It is a bad split on LAYOUT: these rules
were first fixed in the A2UI binder, and the other composer promptly shipped
the same cramped cards, because a layout invariant living inside one writer has
to be re-learned by every other writer. Same "two components each holding half
a contract" shape the rules themselves are about, one level up.

So the rules live here, over the emitted page schema, and run after whoever
wrote it. The composers keep competing on content; the layout is settled once.

Deterministic, pure, and idempotent — a second pass finds the Rows already
converted and the densities already set, and changes nothing.
"""
from __future__ import annotations

import glob
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


# ── section layout ───────────────────────────────────────────────────────
# A2UI's `Row` means "these sit side by side". Forge's `Row` is `flex flex-row`
# and a flex child defaults to `flex: 0 1 auto`, so a Card with no width, basis
# or grow renders exactly as wide as its text. Three cards in a Row therefore
# hug the left edge and leave the rest of the viewport empty — the live symptom
# on 1xbse9xr. Two components, each holding a plausible half of the contract,
# and nothing that made them agree.
#
# `Grid` is the half that was already right: it owns a responsive column ladder
# (columns=3 -> `grid-cols-1 sm:grid-cols-2 lg:grid-cols-3`) plus equal-width
# and equal-height options. The deterministic dashboard composer learned to
# reach for it; this binder mapped Row -> Row verbatim and never did.
#
# So the conversion happens here, once, on the built tree — after `build()` has
# decided every node's real type, and in one function a test can call directly.

# Widgets that stand as peers in a section. A row of these is a LAYOUT; the
# ordering carries no meaning, so handing each an equal column is always right.
_SECTION_PEERS = frozenset({
    "Card", "Panel", "Chart", "Table", "DataGrid", "List", "Kanban",
    "Calendar", "Timeline", "ResourceTimeline", "ActivityFeed", "MetricTile",
    "StatCard", "Stat", "Gauge", "SplitArc", "Heatmap", "Schematic",
    "DescriptionList", "KeyValueList", "Stepper", "ApprovalStepper",
})

# Row props Grid has no concept of. Carrying them over would leave dead props
# that read as intent nobody implements.
_ROW_ONLY_PROPS = ("justify", "align", "wrap")


def _is_section_row(node: dict, kids: list) -> bool:
    """A row of content peers, as opposed to a genuine row of chrome.

    The discriminator has to hold both ways. `row-mid` (three Cards) is a
    layout and must become a Grid. `sec-header` (a greeting beside a date
    picker) is a real row and must not — a Grid would hand the picker half
    the page.
    """
    if node.get("type") != "Row" or len(kids) < 2:
        return False                      # a one-column Grid is a Row, verbosely
    if (node.get("props") or {}).get("wrap") is False:
        return False                      # the composer asked for one line
    return all(k.get("type") in _SECTION_PEERS for k in kids)


# Card reads its padding off a VIEWPORT breakpoint (`p-5 sm:p-8 md:p-10`), so
# on a wide desktop every card takes the loose 40px — the full-bleed one and
# the one-third-of-a-row one alike. On the narrow card that is 80px of 467
# spent on padding, and it is what pushed a five-column table past its box.
#
# A card cannot know how wide it will be rendered. This module does: it has
# just decided the section's column count. So it sets the density rather than
# leaving the card to assume it has the whole page.
_DENSITY_FOR_COLUMNS = {2: "regular"}   # 3-up and denser fall through to tight


def density_for_columns(columns: int) -> str | None:
    """How much padding a card gets when it is one of `columns` across.

    Public because the deterministic composers call it at author time — they
    know the column count as they build the grid, so they can emit the right
    density rather than emit a wrong one for the pass below to correct. Same
    rule either way; stated here once.
    """
    if columns < 2:
        return None                  # a full-width card has the room it assumes
    return _DENSITY_FOR_COLUMNS.get(columns, "tight")


def _apply_density(kids: list, columns: int) -> None:
    """Tell the peer cards how much room they actually got. In place."""
    density = density_for_columns(columns)
    if density is None:
        return
    for kid in kids:
        # Only Card has the prop; on anything else it would be a dead prop that
        # reads as intent nobody implements.
        if kid.get("type") != "Card":
            continue
        props = kid.setdefault("props", {})
        props.setdefault("density", density)   # authored intent always wins


def shape_sections(node: Any) -> Any:
    """Give every section an explicit column count. Returns a new tree.

    Two repairs, both about a column count nobody stated:
      * a Row of peers becomes a Grid, because Row has no notion of columns
        at all and sizes children to their content;
      * a Grid that never carried `columns` gets one per child, because the
        renderer defaults that prop to 1 — which is why a five-tile KPI strip
        rendered as a single stacked column.

    An authored `columns` is never overridden: a deliberate 2-up of four cards
    is a composition decision, not an omission.
    """
    if not isinstance(node, dict):
        return node

    out = dict(node)
    kids = [shape_sections(k) for k in node.get("children") or []
            if isinstance(k, dict)]
    if node.get("children") is not None:
        out["children"] = kids

    props = dict(out.get("props") or {})
    if _is_section_row(node, kids):
        out["type"] = "Grid"
        for dead in _ROW_ONLY_PROPS:
            props.pop(dead, None)
        props["columns"] = len(kids)
        # Peers in a section are read side by side, so a three-row table beside
        # a nine-row one must not render ragged, and a wide table must not
        # steal its neighbours' share of the width.
        props["equalRows"] = True
        props["equalCols"] = True
        out["props"] = props
        _apply_density(kids, props["columns"])
    elif out.get("type") == "Grid":
        # A card grid is usually ONE Repeat that fans out to N cards when the
        # data arrives, so its column count is not its child count. Inferring
        # one would cement `columns: 1` — the single-stacked-column look — and
        # make it read as a deliberate choice rather than a missing prop.
        runtime_expanded = any(k.get("type") == "Repeat" for k in kids)
        if "columns" not in props and kids and not runtime_expanded:
            props["columns"] = len(kids)
            out["props"] = props
        # A Grid the composer already emitted has the same cramped cards.
        cols = props.get("columns")
        if isinstance(cols, int):
            _apply_density(kids, cols)
    return out


# ── the pass ─────────────────────────────────────────────────────────────

def normalize_section_layout(output_dir: str) -> dict:
    """Apply the section-layout rules to every page schema. Best-effort.

    Runs after the composers so it sees final content, and it is the only
    place these rules are stated — an A2UI dashboard, a deterministic
    dashboard and a collection page all land on the same layout contract.
    """
    sdir = os.path.join(output_dir, "src", "schemas")
    if not os.path.isdir(sdir):
        return {"changed": 0, "files": 0}

    changed = files = 0
    # Recursive: schemas nest under src/schemas/<section>/ on larger apps, and
    # a flat glob silently skips exactly the pages big enough to be cramped.
    for fp in sorted(glob.glob(os.path.join(sdir, "**", "*.json"),
                               recursive=True)):
        try:
            with open(fp, encoding="utf-8") as fh:
                schema = json.load(fh)
        except Exception:  # noqa: BLE001 — a page we cannot read is not ours to fix
            continue
        root = schema.get("root")
        if not isinstance(root, dict):
            continue
        shaped = shape_sections(root)
        if shaped == root:
            continue
        schema["root"] = shaped
        try:
            with open(fp, "w", encoding="utf-8") as fh:
                json.dump(schema, fh, indent=2)
        except Exception as e:  # noqa: BLE001
            logger.warning("section_layout: could not write %s: %s", fp, e)
            continue
        changed += 1
        files += 1
    return {"changed": changed, "files": files}
