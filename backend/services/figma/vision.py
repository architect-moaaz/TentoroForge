"""What each rectangle of a frame actually IS, decided by looking at it.

WHY LOOKING IS THE ONLY OPTION LEFT. A flattened export carries no names. On
the dashboard this was written against, all 274 `data-name` attributes were
`Vector`, `Group`, `Clip path group` or `Mask group`, and Figma's own metadata
agreed — `Group 3`, `clip2_568_17068`. Two text nodes in the whole file had
real words in them. So there is no string to match an entity against, no layer
called "Revenue" to bind to a column, and `figma_binding_extractor`'s
name-match and semantic-type detectors have nothing to read.

What survives flattening is the picture. A bar chart still looks like a bar
chart, and a table still looks like a table, which is why this asks a model to
look rather than asking a parser to guess. `regions` supplies the rectangles
and their node ids; this supplies what they are.

WHY THE ANSWER IS EVIDENCE, NOT A DECISION (§48, §49). A classification here
never edits the design. It is recorded with a confidence and a reason, and a
later step decides whether to act on it — replacing a picture of a chart with a
real one is a change to the application, and it should be reviewable as such.
An unrecognised region keeps its image, which is always a legal outcome: the
page renders either way, and the worst case of not knowing is the page we
already have.

WHY NESTED REGIONS ARE SENT AS THEY ARE. `regions.candidates` deliberately does
not collapse a card and the chart inside it, because choosing between them is
the judgement being delegated. The model sees both and is asked which one is
the chart; a `container` verdict on the outer rectangle is the useful answer,
not a failure.
"""
from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any, Callable, Sequence

from services.figma.regions import Region

logger = logging.getLogger(__name__)

#: What a rectangle can turn out to be. Closed on purpose: an open vocabulary
#: produced "dashboard-widget" and "data-visualisation" on the same frame, and
#: nothing downstream can act on either. Every value here has a component or a
#: deliberate no-op behind it.
KINDS = ("bar_chart", "line_chart", "area_chart", "pie_chart", "donut_chart",
         "table", "metric", "form", "nav", "logo", "illustration", "container",
         "unknown")

#: Kinds a real component can replace a picture with. `container`, `logo`,
#: `illustration` and `unknown` are honest outcomes that keep the image.
ACTIONABLE = ("bar_chart", "line_chart", "area_chart", "pie_chart",
              "donut_chart", "table", "metric")

REPLY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["regions"],
    "properties": {
        "regions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["nodeId", "kind", "confidence", "reason"],
                "properties": {
                    "nodeId": {"type": "string"},
                    "kind": {"type": "string", "enum": list(KINDS)},
                    # The words on the picture, when there are any. A chart
                    # titled "Total Ticket Stats" says what it plots, and that
                    # is the only naming this design has anywhere.
                    "title": {"type": "string"},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                    # WHAT IT SHOULD SHOW, decided in the same look that
                    # decided what it is. Splitting these into two calls means
                    # the second one reasons about a label instead of a
                    # picture — and the picture is the only evidence there is.
                    # "" is the honest answer when no entity fits; the region
                    # then keeps its image.
                    "entity": {"type": "string"},
                    "xField": {"type": "string"},
                    "valueField": {"type": "string"},
                    "columns": {"type": "array", "items": {"type": "string"}},
                    # A metric is a number computed over its entity: how many
                    # records (`count`), or a `sum`/`avg` of `valueField`.
                    "fn": {"type": "string", "enum": ["count", "sum", "avg"]},
                },
            },
        }
    },
}

_SYSTEM = (
    "You identify what each rectangle of a user interface design is, by "
    "looking at a picture of it.\n\n"
    "You are shown numbered crops of one screen. For each, say what it is "
    "from the closed list you are given, read its title off the image if it "
    "has one, and give a confidence between 0 and 1.\n\n"
    "The rectangles overlap on purpose: a card and the chart drawn inside it "
    "are both shown. Call the card `container` and the chart by its type — do "
    "not call both of them charts, and do not refuse to answer because they "
    "overlap.\n\n"
    "Distinguish the chart types by their marks, not by their subject: "
    "vertical or horizontal bars are `bar_chart`; a line with no fill is "
    "`line_chart`; a line with shaded area beneath is `area_chart`; a filled "
    "circle divided into wedges is `pie_chart`; the same with a hole is "
    "`donut_chart`. A grid of rows and columns of text is `table`, and so is "
    "a list of rows that each describe one record — a time, a title, a "
    "place and a status per row is a table drawn as a list. A single "
    "large number with a label is `metric`.\n\n"
    "`unknown` is a real answer and a better one than a guess. A wrong kind "
    "replaces a correct picture with a wrong component; an `unknown` leaves "
    "the picture alone, which always renders.\n\n"
    "WHEN YOU ARE GIVEN THE APPLICATION'S ENTITIES, also say what each region "
    "should be showing. Set `entity` to the one it plots or lists, `xField` "
    "and `valueField` for a chart, `columns` for a table — every one of them a "
    "field name copied exactly from the entity you named. Judge by what the "
    "picture shows: a chart of monthly values wants a date-like field on x, a "
    "table of companies wants the columns whose headers you can read. A "
    "`metric` wants `fn`: `count` when the number is how many of the entity "
    "there are (\"132 members\"), `sum` or `avg` with `valueField` when it "
    "totals or averages a field.\n\n"
    "Leave `entity` empty when nothing fits. Binding a chart to the wrong "
    "entity produces a confident, wrong application; leaving it empty keeps "
    "the drawing, which is merely incomplete."
)


def _crop_dir(app_root: str | Path) -> Path:
    out = Path(app_root) / ".forge-cache" / "figma-regions"
    out.mkdir(parents=True, exist_ok=True)
    return out


async def render_regions(gateway: Any, file_key: str,
                         regions: Sequence[Region],
                         app_root: str | Path) -> list[tuple[Region, Path]]:
    """A PNG per region, via the same gateway the extraction already uses.

    Best-effort per region: a frame where half the crops fail is still worth
    classifying, and a region with no picture simply is not offered to the
    model. Nothing here may raise into a build.
    """
    out_dir = _crop_dir(app_root)
    shots: list[tuple[Region, Path]] = []
    for region in regions:
        path = out_dir / f"{region.node_id.replace(':', '-')}.png"
        if path.is_file() and path.stat().st_size > 0:
            shots.append((region, path))
            continue
        try:
            blocks = await gateway.call("get_screenshot", file_key=file_key,
                                        node_id=region.node_id)
        except Exception as exc:  # noqa: BLE001 — one crop, never the build
            logger.info("[figma-vision] no crop for %s: %s", region.node_id, exc)
            continue
        image = next((b for b in blocks if b.get("type") == "image"), None)
        if not image or not image.get("data"):
            continue
        try:
            path.write_bytes(base64.b64decode(image["data"]))
        except Exception as exc:  # noqa: BLE001
            logger.info("[figma-vision] undecodable crop %s: %s",
                        region.node_id, exc)
            continue
        shots.append((region, path))
    return shots


def _entity_brief(entities: Sequence[dict]) -> str:
    """The entities and their fields, small enough to sit beside the images."""
    lines = []
    for ent in entities:
        fields = [str(f.get("name") or "") for f in (ent.get("fields") or [])]
        fields = [f for f in fields if f][:14]
        if ent.get("name") and fields:
            lines.append(f"  {ent['name']}: {', '.join(fields)}")
    return "\n".join(lines)


def classify(ask: Callable[..., str],
             shots: Sequence[tuple[Region, Path]],
             entities: Sequence[dict] = ()) -> list[dict]:
    """What each rendered region is, as a list of records.

    ``ask`` is the executor callable — ``__call__(system=, user=, schema=,
    images=)`` — so this shares the client, the timeouts, the retries and the
    structured-output enforcement with every other model call in the pipeline
    rather than opening a second path to the API.

    Returns [] on any failure. A page whose regions were not classified is the
    page as it renders today, which is a working page.
    """
    if not shots:
        return []

    # THE MODEL IS TOLD WHICH PICTURE IS WHICH. Images arrive as an ordered
    # list with no identifiers of their own, so the mapping to node ids lives
    # in the text and the reply is required to echo it back. Without this the
    # classifications are correct and unattributable.
    lines = [
        f"Image {i + 1} is region `{r.node_id}` — {r.width:.0f}x{r.height:.0f}px "
        f"at ({r.x:.0f}, {r.y:.0f}) in the frame."
        for i, (r, _p) in enumerate(shots)
    ]
    user = (
        "Here are the numbered regions of one screen, in the order the images "
        "appear.\n\n" + "\n".join(lines) +
        "\n\nReturn one entry per region, echoing its `nodeId` exactly as "
        "written above."
    )
    brief = _entity_brief(entities)
    if brief:
        user += ("\n\nThe application stores these entities. Field names are "
                 "exact; copy them.\n\n" + brief)

    try:
        raw = ask(system=_SYSTEM, user=user, schema=REPLY_SCHEMA,
                  images=[p for _r, p in shots])
        # A client may answer with a bare str or with a `ModelReply` carrying
        # usage — `ModelClient` documents both, and a test fake is a one-liner
        # precisely because the bare string is allowed.
        found = json.loads(getattr(raw, "text", raw)).get("regions") or []
    except Exception as exc:  # noqa: BLE001 — vision is an enrichment
        logger.warning("[figma-vision] classification failed: %s", exc)
        return []

    # A nodeId the model invented names nothing, and a kind outside the enum
    # cannot be acted on. Both are dropped rather than repaired: this is
    # evidence, and evidence that does not refer to anything is not evidence.
    known = {r.node_id for r, _p in shots}
    out = []
    for entry in found:
        if not isinstance(entry, dict):
            continue
        node_id = str(entry.get("nodeId") or "")
        if node_id not in known or entry.get("kind") not in KINDS:
            continue
        # A field the entity does not have cannot be bound, and a binding to
        # a field that does not exist renders an empty chart that looks like a
        # data problem. Checked here rather than trusted.
        by_name = {str(e.get("name") or ""): e for e in entities}
        entity = str(entry.get("entity") or "").strip()
        known_fields = {str(f.get("name") or "")
                        for f in (by_name.get(entity, {}).get("fields") or [])}
        keep = lambda f: f in known_fields  # noqa: E731
        out.append({
            "nodeId": node_id,
            "kind": entry["kind"],
            "title": str(entry.get("title") or "").strip(),
            "confidence": float(entry.get("confidence") or 0.0),
            "reason": str(entry.get("reason") or "").strip(),
            "entity": entity if entity in by_name else "",
            "xField": (str(entry.get("xField") or "")
                       if keep(str(entry.get("xField") or "")) else ""),
            "valueField": (str(entry.get("valueField") or "")
                           if keep(str(entry.get("valueField") or "")) else ""),
            "columns": [c for c in (entry.get("columns") or [])
                        if isinstance(c, str) and keep(c)],
        })
    return out
