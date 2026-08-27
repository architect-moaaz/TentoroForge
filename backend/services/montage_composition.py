"""Read a design-reference montage for LAYOUT, composition and richness.

The montage answers "what should a screen of this kind look like, and how
much should be on it" — the frame, the regions in order, how dense the
table is, whether a detail page carries a right rail. That is the standard
the generated app should meet.

It deliberately answers nothing else:

* **No colour.** The palette comes from the design option the user picks at
  the research gate (`services/design_templates`). A hex arriving from a
  montage would silently compete with that pick, so hexes are stripped on
  the way in rather than trusted not to appear.
* **No entities or columns.** The generation pipeline decides what is on
  each page — the plan and registry know the app is about Sessions and that
  `startTime` is real. A reference that named "Invoices" would import a
  domain the app does not have. The extractor is told to describe shape,
  and the rendered block repeats that boundary to the maquette author.

The reference speaks the maquette layer's own vocabulary rather than prose.
"a table running 7-8 columns" is unactionable — the authors choose from five
collection layouts, five hero kinds and three rhythms, so the montage reports
`{"shape": "table", "columns_target": 8}` and anything off-list is dropped.
Those vocabularies are read from the modules that own them (never re-declared
here) so they cannot drift apart. The counts matter most: nothing else in the
system has an opinion about how MUCH belongs on a page, which is why density
had been a side effect of how wide an entity happened to be.

The output feeds the maquette authors (dashboard / collection / record),
which are the layer that decides page composition. Like the 21st.dev
references, the vision call runs once and persists to
``contracts/composition-reference.json``; the maquettes read the file, so
they stay pure and unit-testable.

Fail-soft throughout: no montage, an unreadable response, or a sparse one
means the maquettes get an empty block and behave exactly as before.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable

logger = logging.getLogger(__name__)


class MontageCompositionError(RuntimeError):
    """The montage yielded nothing usable. Callers swallow this."""


# The screen kinds the maquette layer actually authors. Anything else the
# model volunteers is dropped rather than carried into a prompt nobody reads.
_SCREEN_KINDS = ("dashboard", "collection", "record")

_MAX_REGIONS = 8
_MAX_CHARS = 240

# Any hex colour, in every form the models emit.
_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")

# ── The maquette layer's vocabularies ───────────────────────────────────────
# Read from the modules that own them. A second copy here would drift the
# first time someone adds a layout, and the montage would start recommending
# shapes the schema rejects.

# kind → ((json field, vocabulary key), ...)
_ENUM_FIELDS: dict[str, tuple[tuple[str, str], ...]] = {
    "collection": (("shape", "collection_shape"),),
    "dashboard": (("hero_kind", "dashboard_hero"), ("rhythm", "dashboard_rhythm")),
    "record": (("hero_kind", "record_hero"),),
}

# kind → ((json field, min, max), ...). Bounds are renderability limits, not
# taste: a 40-column table is a horizontal scrollbar, not a dense one.
_COUNT_FIELDS: dict[str, tuple[tuple[str, int, int], ...]] = {
    "collection": (("columns_target", 3, 12),),
    "dashboard": (("kpis_target", 2, 8), ("sections_target", 2, 8)),
    "record": (("sections_target", 2, 8), ("fields_target", 4, 40)),
}

_INT = re.compile(r"\d+")


def _enums() -> dict[str, tuple[str, ...]]:
    """The real vocabularies, or `{}` when they cannot be read.

    Imported lazily: the maquette modules import *this* one, so a top-level
    import either way would close a cycle. An empty result degrades to the
    prose-only behaviour rather than failing a build.
    """
    try:
        from services.collection_maquette import COLLECTION_LAYOUTS
        from services.dashboard_maquette import HERO_KINDS, SECTION_RHYTHMS
        from services.record_maquette import RECORD_HERO_KINDS
    except Exception as e:  # noqa: BLE001
        logger.info("[montage] maquette vocabularies unavailable (%s); prose only", e)
        return {}
    return {
        "collection_shape": tuple(COLLECTION_LAYOUTS),
        "dashboard_hero": tuple(HERO_KINDS),
        "dashboard_rhythm": tuple(SECTION_RHYTHMS),
        "record_hero": tuple(RECORD_HERO_KINDS),
    }


def _clamp_count(value: Any, lo: int, hi: int) -> int | None:
    """A target count, or None when the model gave nothing numeric.

    Tolerates the range strings models like to write: "7-8" reads as 8,
    because the reference is a bar to reach, not a ceiling to stay under.
    Junk is dropped rather than defaulted — an invented target is worse
    than no target, since the author would aim at it.
    """
    if isinstance(value, bool):                      # bool is an int subclass
        return None
    if isinstance(value, (int, float)):
        found = [int(value)]
    else:
        found = [int(m) for m in _INT.findall(str(value or ""))]
    if not found:
        return None
    return max(lo, min(hi, max(found)))


def _typed_picks(kind: str, spec: dict, enums: dict[str, tuple[str, ...]]) -> dict:
    """The schema-legal subset of one screen's typed fields."""
    out: dict[str, Any] = {}
    for field, vocab_key in _ENUM_FIELDS.get(kind, ()):
        allowed = enums.get(vocab_key) or ()
        raw = str(spec.get(field) or "").strip()
        if raw and raw in allowed:                   # off-list → dropped, not coerced
            out[field] = raw
    for field, lo, hi in _COUNT_FIELDS.get(kind, ()):
        if field in spec:
            n = _clamp_count(spec.get(field), lo, hi)
            if n is not None:
                out[field] = n
    return out


def _build_system(enums: dict[str, tuple[str, ...]]) -> str:
    """The system prompt, naming the vocabularies the authors actually accept."""
    if not enums:
        return _SYSTEM
    lines = [_SYSTEM, "", "TYPED PICKS — use these exact values, or omit the field:"]
    for kind in _SCREEN_KINDS:
        parts = [f'"{f}": one of {list(enums.get(k) or [])}'
                 for f, k in _ENUM_FIELDS.get(kind, ()) if enums.get(k)]
        parts += [f'"{f}": integer {lo}-{hi}'
                  for f, lo, hi in _COUNT_FIELDS.get(kind, ())]
        if parts:
            lines.append(f"  {kind}: " + "; ".join(parts))
    lines.append("Put these alongside `regions` and `density` in each screen "
                 "object. Never invent a value that is not listed.")
    return "\n".join(lines)


_SYSTEM = """\
You are reading a montage of product screenshots as a COMPOSITION reference.

Report only SHAPE: the frame, which regions each kind of screen carries and
in what order, and how dense the content is (how many columns a table runs,
how many tiles sit above the fold, how many fields a detail page shows).

Two hard rules:
  1. NEVER report colour. No hex values, no colour names. A different part
     of the system owns the palette.
  2. NEVER name a business entity, table or column you can read in the
     screenshots. Say "table with 7-8 columns including a status pill", not
     "Invoices table with Amount and Due Date". The app being built has its
     own domain; you are describing arrangement and density only.

Output ONE JSON object, nothing else:
{
  "layout": "<the frame in a short phrase — nav placement, content width, rails>",
  "screens": {
    "dashboard":  {"regions": ["<region, in visual order>", ...], "density": "<how much, in numbers>"},
    "collection": {"regions": [...], "density": "..."},
    "record":     {"regions": [...], "density": "..."}
  }
}
Include only the screen kinds the montage actually shows. Keep each string
under 200 characters."""

_USER = ("Read these screens as a composition reference. Describe layout, the "
         "regions each screen kind carries, and how dense the content is. "
         "Shape only — no colours, no entity or column names.")


def _strip_colour(text: Any) -> str:
    """Remove hexes without destroying the surrounding shape description.

    'sidebar in #0B1220 with #FFFFFF content' → 'sidebar with content'. The
    words matter; the colour must not survive.
    """
    s = str(text or "")
    s = _HEX.sub("", s)
    # Clean up the connectives left dangling by a removed colour.
    s = re.sub(r"\b(?:in|with|of|on)\s+(?=\s|$|[,.])", "", s)
    s = re.sub(r"\s{2,}", " ", s)
    s = re.sub(r"\s+([,.])", r"\1", s)
    return s.strip(" ,.-").strip()[:_MAX_CHARS]


def _parse(raw: str) -> dict:
    text = str(raw or "").strip()
    if text.startswith("```"):                      # fenced — models do this
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        doc = json.loads(text)
    except Exception as e:  # noqa: BLE001
        raise MontageCompositionError(f"unparseable composition response: {e}") from e
    if not isinstance(doc, dict):
        raise MontageCompositionError("composition response was not an object")
    return doc


def extract_composition_reference(
    image_blocks: list[dict],
    *,
    llm: Callable[..., str] | None = None,
) -> dict:
    """Montage image blocks → `{layout, screens: {kind: {regions, density}}}`.

    Raises MontageCompositionError when there is nothing to read or the
    response is unusable — the pipeline caller swallows it and proceeds
    without a reference.
    """
    blocks = [b for b in (image_blocks or [])
              if isinstance(b, dict) and b.get("type") in ("image", "document")]
    if not blocks:
        raise MontageCompositionError("no image blocks in the design reference")

    if llm is None:
        from services.llm_client import complete as _complete  # local: keeps import light

        def llm(system: str, content: list[dict]) -> str:      # noqa: ANN001
            return _complete(system=system, content=content)

    enums = _enums()
    raw = llm(_build_system(enums), [*blocks, {"type": "text", "text": _USER}])
    doc = _parse(raw)

    layout = _strip_colour(doc.get("layout"))
    screens: dict[str, dict] = {}
    src = doc.get("screens")
    if isinstance(src, dict):
        for kind in _SCREEN_KINDS:                  # bounded — unknown kinds dropped
            spec = src.get(kind)
            if not isinstance(spec, dict):
                continue
            regions = [_strip_colour(r) for r in (spec.get("regions") or [])
                       if str(r or "").strip()][:_MAX_REGIONS]
            regions = [r for r in regions if r]
            density = _strip_colour(spec.get("density"))
            typed = _typed_picks(kind, spec, enums)
            if regions or density or typed:
                screens[kind] = {"regions": regions, "density": density, **typed}

    if not screens and not layout:
        raise MontageCompositionError("composition response carried no shape")

    logger.info("[montage] composition reference: layout=%r, screens=%s",
                layout[:60], sorted(screens))
    return {"layout": layout, "screens": screens}


# Prompt labels for the typed fields. The JSON keys carry `_target` for the
# gate's benefit; the author reads a shorter word.
_TARGET_LABELS = (("shape", "shape"), ("hero_kind", "hero"), ("rhythm", "rhythm"),
                  ("kpis_target", "kpis"), ("columns_target", "columns"),
                  ("sections_target", "sections"), ("fields_target", "fields"))


def _target_line(spec: dict) -> str:
    """`shape=table, columns=8` — the numbers the author should aim at."""
    parts = [f"{label}={spec[key]}" for key, label in _TARGET_LABELS if spec.get(key)]
    return ", ".join(parts)


def render_composition_block(reference: dict | None) -> str:
    """The reference as a prompt block for the maquette authors.

    Returns "" for anything empty, so an author with no montage builds
    exactly as it did before.
    """
    if not isinstance(reference, dict):
        return ""
    screens = reference.get("screens")
    if not isinstance(screens, dict) or not screens:
        return ""

    lines = ["", "REFERENCE COMPOSITION (the bar this app should meet):"]
    layout = str(reference.get("layout") or "").strip()
    if layout:
        lines.append(f"  layout: {layout}")
    for kind in _SCREEN_KINDS:
        spec = screens.get(kind)
        if not isinstance(spec, dict):
            continue
        lines.append(f"  {kind}:")
        for region in spec.get("regions") or []:
            lines.append(f"    • {region}")
        density = str(spec.get("density") or "").strip()
        if density:
            lines.append(f"    density: {density}")
        target = _target_line(spec)
        if target:
            lines.append(f"    TARGET: {target}")
    lines.append(
        "  TARGET lines are the bar to meet, not a ceiling: author at least"
    )
    lines.append(
        "  that many columns/tiles/sections when the entity supports it. Use"
    )
    lines.append(
        "  the listed shape and hero unless the real data cannot carry it."
    )
    lines.append(
        "  This describes SHAPE and DENSITY only — how many regions, how many"
    )
    lines.append(
        "  columns, how much detail. It does NOT name this app's entities or"
    )
    lines.append(
        "  columns: use the real ones listed below, never a noun borrowed from"
    )
    lines.append(
        "  the reference. Colour is decided elsewhere — ignore it entirely."
    )
    lines.append("")
    return "\n".join(lines)


# ── Persistence: written once, read by every maquette author ────────────────
# Mirrors the 21st.dev reference flow — the vision call happens in the
# pipeline, the maquettes read a file. Keeps the authors pure and means a
# reference costs one call, not three.

_FILENAME = "composition-reference.json"


def save_composition_reference(output_dir: str, reference: dict) -> None:
    """Persist to ``<output_dir>/src/contracts/composition-reference.json``."""
    from pathlib import Path

    path = Path(output_dir) / "src" / "contracts" / _FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(reference, indent=2), encoding="utf-8")
    logger.info("[montage] composition reference persisted → %s", path)


def composition_targets(output_dir: str) -> dict:
    """`{kind: {typed field: value}}` for the persisted reference, or `{}`.

    The read side for anything that wants to CHECK density rather than
    suggest it — the delivery gate comparing a shipped page against the bar
    the montage set. Prose (`regions`, `density`) is deliberately excluded:
    it is for the author to read, not for a gate to assert on. Never raises.
    """
    from pathlib import Path

    path = Path(output_dir) / "src" / "contracts" / _FILENAME
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.info("[montage] unreadable composition reference (%s); no targets", e)
        return {}
    screens = doc.get("screens") if isinstance(doc, dict) else None
    if not isinstance(screens, dict):
        return {}

    out: dict[str, dict] = {}
    for kind in _SCREEN_KINDS:
        spec = screens.get(kind)
        if not isinstance(spec, dict):
            continue
        typed = {k: spec[k] for k, _ in _TARGET_LABELS if spec.get(k) is not None}
        if typed:
            out[kind] = typed
    return out


def load_composition_block(plan: dict | None) -> str:
    """The rendered block for a maquette prompt, or "" when there's no montage.

    Reads `plan["_output_dir"]` the same way `_read_21st_references` does, so
    unit tests that pass a bare plan get "" and behave as before. Never
    raises — a missing or corrupt reference must not fail a build.
    """
    from pathlib import Path

    if not isinstance(plan, dict):
        return ""
    out_dir = plan.get("_output_dir")
    if not isinstance(out_dir, str) or not out_dir:
        return ""
    path = Path(out_dir) / "src" / "contracts" / _FILENAME
    if not path.is_file():
        return ""
    try:
        return render_composition_block(json.loads(path.read_text(encoding="utf-8")))
    except Exception as e:  # noqa: BLE001
        logger.info("[montage] unreadable composition reference (%s); ignoring", e)
        return ""
