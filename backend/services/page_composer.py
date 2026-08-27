"""CREATIVE-6a — LLM page-schema composer.

An LLM alternative to the deterministic ``apply_*_maquette`` composers.
Given ONE plan.page + the full composition context (vocab, preset,
library manifest, patterns, brief, variance seed), the composer asks
the LLM to author a complete page schema — root ``Stack``, dataSources,
nested Table/Card/DescriptionList/Chart/... nodes — that the runtime
can render the same way it renders the deterministic output.

SCOPE (this slice — CREATIVE-6a). Module + tests + dry-run scratchpad
ONLY. The pipeline still routes through the deterministic composers —
CREATIVE-6b flips the flag. That means every guarantee here is unit-
testable in isolation; no live-app path depends on this module yet.

MIRRORS :mod:`services.vocab_composer` intentionally:

  * async ``compose_page`` + sync ``compose_page_sync`` facade
  * structured JSON output from a single LLM call
  * Python-side merge/validator that rejects malformed output
  * fail-open cascade — any exception returns ``(None, provenance)``
    so the pipeline can transparently fall back to the deterministic
    composer that CREATIVE-6b keeps as the safety net.
  * bounded in-memory LRU cache (disk cache lands in 6b's pipeline)
  * provenance dict identical in spirit — ``source``/``changes``/etc.

DELIBERATELY DIFFERENT from vocab_composer:

  * Manifest is subsetted per page.kind. Vocab composition doesn't care
    which components a form vs a dashboard needs; page composition
    does. Filtering by category keeps the prompt small enough for a
    single completion.
  * Validation is stricter — component types, dataSource entities, and
    ``{{binding}}`` references are checked against the plan + manifest.
    A vocab that names a bad component is a soft warning; a page that
    names a bad component would crash the runtime. Fail closed.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from functools import lru_cache
from typing import Any

from schemas.design_brief import VisualLock
from services.archetype_vocabulary import ArchetypeVocabulary


logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-4-5"

# --------------------------------------------------------------------- #
# Manifest subsetting
# --------------------------------------------------------------------- #
#
# The library ships ~157 components. Sending all of them into every page
# prompt burns tokens on components that would never render on this
# page kind (a login page will never place a Kanban). We subset by the
# categories the manifest already tags — see library_manifest._CATEGORY_RULES.
#
# Rules:
#   - Always include: layout, action, display, nav (chrome + primitives
#     every page uses).
#   - Include `input` for form-shaped pages + settings (they render form
#     controls). Exclude it for detail/list/dashboard so the LLM doesn't
#     reach for an Input inside a Table cell.
#   - Include `data` for list, detail, dashboard (they render collections
#     or description-lists). Exclude for form/settings.
#   - Include `chart` for dashboard + settings-lite (metrics tiles); off
#     for pure form/create/edit.
#   - `media` + `overlay` are opt-in ONLY on pages that need them today
#     — kept off by default to preserve budget.
#
# Any unrecognised page.kind falls back to the full manifest — better to
# spend tokens than to drop a category the LLM legitimately needs.

_ALWAYS_INCLUDE = frozenset({"layout", "action", "display", "nav"})

_KIND_CATEGORY_RULES: dict[str, dict[str, bool]] = {
    # Collections
    "list":       {"data": True},
    "collection": {"data": True},
    # Records
    "detail":     {"data": True, "display": True},
    "record":     {"data": True, "display": True},
    # Metrics
    "dashboard":  {"data": True, "chart": True},
    # Inputs
    "form":       {"input": True, "data": False, "chart": False},
    "create":     {"input": True, "data": False, "chart": False},
    "edit":       {"input": True, "data": False, "chart": False},
    # Settings — usually a form-shaped page with a few display bits, no
    # tables + no charts.
    "settings":   {"input": True, "display": True, "data": False, "chart": False},
}


def _filter_manifest_for_page(manifest: dict, page_kind: str) -> dict:
    """Return a manifest subset relevant to this page's kind.

    Never raises — a shape mismatch on input just falls through to
    returning the manifest unchanged (better than crashing composition).
    """
    if not isinstance(manifest, dict):
        return {"components": {}}
    comps = manifest.get("components")
    if not isinstance(comps, dict) or not comps:
        return {"components": {}}

    kind = (page_kind or "").strip().lower()
    rules = _KIND_CATEGORY_RULES.get(kind)
    if rules is None:
        # Unknown kind — send everything (safer than filtering blind).
        return {"components": dict(comps)}

    include: set[str] = set(_ALWAYS_INCLUDE)
    for cat, wanted in rules.items():
        if wanted:
            include.add(cat)
        else:
            include.discard(cat)

    kept: dict[str, dict] = {}
    for name, entry in comps.items():
        if not isinstance(entry, dict):
            continue
        cat = entry.get("category", "")
        if cat in include:
            kept[name] = entry
    return {"components": kept}


# --------------------------------------------------------------------- #
# Cache (bounded in-memory LRU; disk persistence lives in the pipeline)
# --------------------------------------------------------------------- #

_MEMO_CACHE: "dict[str, tuple[dict, dict]]" = {}
_MEMO_MAX = 64


def _reset_cache_for_tests() -> None:
    _MEMO_CACHE.clear()


def cache_key(
    page: dict,
    plan: dict,
    vocab: ArchetypeVocabulary,
    preset: VisualLock,
    manifest_subset: dict,
    *,
    patterns: list[dict] | None = None,
    variance_seed: int | str | None = None,
    brief: Any | None = None,
    reference_images: list[dict] | None = None,
) -> str:
    """Deterministic hash of the page composer's inputs.

    Folds in the fields whose change should invalidate the cached
    composition — page identity, plan description, composite vocab id,
    composite preset name, sorted patterns, variance seed, and the
    manifest subset's component names (order-insensitive).
    """
    parts: list[str] = []
    page = page if isinstance(page, dict) else {}
    parts.append(str(page.get("id") or page.get("name") or ""))
    parts.append(str(page.get("route") or ""))
    parts.append(str(page.get("kind") or page.get("type") or ""))
    parts.append(str(page.get("entity") or ""))
    parts.append(str((plan or {}).get("description") or "").strip())
    parts.append(getattr(vocab, "id", "") or "")
    parts.append(getattr(preset, "preset_name", "") or "")

    if variance_seed is not None:
        parts.append(f"seed={variance_seed}")

    if isinstance(patterns, list):
        pids: list[str] = []
        for p in patterns:
            if isinstance(p, dict):
                v = p.get("id") or p.get("name") or p.get("title") or ""
                if isinstance(v, str) and v.strip():
                    pids.append(v.strip())
            elif isinstance(p, str) and p.strip():
                pids.append(p.strip())
        parts.append(",".join(sorted(pids)))

    if isinstance(manifest_subset, dict):
        comps = manifest_subset.get("components")
        if isinstance(comps, dict) and comps:
            sig = ",".join(sorted(comps.keys()))
            parts.append("lib=" + hashlib.sha256(sig.encode("utf-8")).hexdigest()[:16])

    # Whether the model could SEE the montage changes the composition, so
    # it has to change the key — otherwise a prose-only result cached on
    # an earlier run would be served to a run that has the screens, and
    # the A/B would silently compare a thing against itself. Fingerprint
    # the image payloads rather than counting them, so swapping which
    # montage is designated also invalidates.
    if reference_images:
        # The attachment loader interleaves a short text label before each
        # image, so fold in both kinds — a caption change is a reference
        # change too, and hashing only the images would miss it.
        h = hashlib.sha256()
        for blk in reference_images:
            if not isinstance(blk, dict):
                continue
            h.update(str(blk.get("type") or "").encode("utf-8"))
            txt = blk.get("text")
            if isinstance(txt, str):
                h.update(txt.encode("utf-8"))
            src = blk.get("source")
            if isinstance(src, dict):
                h.update(str(src.get("media_type") or "").encode("utf-8"))
                data = src.get("data")
                if isinstance(data, str):
                    # Prefix + length rather than the whole payload: enough
                    # to tell images apart, cheap on multi-megabyte base64.
                    h.update(data[:2048].encode("utf-8"))
                    h.update(str(len(data)).encode("utf-8"))
        parts.append(f"img={len(reference_images)}:{h.hexdigest()[:16]}")

    if brief is not None:
        identity = getattr(brief, "identity", None)
        if identity is not None:
            try:
                if hasattr(identity, "model_dump"):
                    d = identity.model_dump(mode="json", exclude_none=True)
                elif hasattr(identity, "dict"):
                    d = identity.dict(exclude_none=True)  # type: ignore[call-arg]
                else:
                    d = dict(identity)
                parts.append(json.dumps(d, sort_keys=True, default=str))
            except Exception:  # noqa: BLE001
                parts.append(repr(identity))

    raw = "\x1f".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------- #
# Prompt
# --------------------------------------------------------------------- #

def _entity_names(plan: dict) -> list[str]:
    """Return the list of entity names in ``plan`` (dict or list form)."""
    ents = (plan or {}).get("entities")
    if isinstance(ents, dict):
        return [str(k) for k in ents.keys() if isinstance(k, str)]
    if isinstance(ents, list):
        out: list[str] = []
        for e in ents:
            if isinstance(e, dict):
                n = e.get("name") or e.get("slug")
                if isinstance(n, str) and n.strip():
                    out.append(n.strip())
            elif isinstance(e, str) and e.strip():
                out.append(e.strip())
        return out
    return []


def _entity_fields(plan: dict, entity_name: str) -> list[str]:
    """Return the field names for one entity, or [] when unknown."""
    if not entity_name:
        return []
    ents = (plan or {}).get("entities")
    entry: Any = None
    if isinstance(ents, dict):
        entry = ents.get(entity_name)
    elif isinstance(ents, list):
        for e in ents:
            if isinstance(e, dict) and (e.get("name") == entity_name or e.get("slug") == entity_name):
                entry = e
                break
    if not isinstance(entry, dict):
        return []
    fields = entry.get("fields") or entry.get("columns") or []
    out: list[str] = []
    if isinstance(fields, list):
        for f in fields:
            if isinstance(f, dict):
                n = f.get("name") or f.get("slug")
                if isinstance(n, str):
                    out.append(n)
            elif isinstance(f, str):
                out.append(f)
    return out


def _entity_fields_map(plan: dict) -> dict[str, list[str]]:
    """Map every plan entity → its declared field names."""
    return {name: _entity_fields(plan, name) for name in _entity_names(plan)}


def _summarize_page(page: dict) -> dict:
    """Compact page slice for the prompt — drop noise, keep intent."""
    p = page if isinstance(page, dict) else {}
    out = {
        "route": p.get("route") or "",
        "kind": p.get("kind") or p.get("type") or "",
        "entity": p.get("entity") or "",
        "title": p.get("title") or p.get("name") or "",
        "description": (p.get("description") or "")[:400],
    }
    # Optional structural hints the planner already carries.
    for k in ("sections", "widgets", "fields", "actions", "features"):
        v = p.get(k)
        if v:
            out[k] = v
    return out


def _summarize_vocab(vocab: ArchetypeVocabulary, page_kind: str, page_entity: str) -> dict:
    """Pick just the vocab slices this page cares about."""
    if vocab is None:
        return {}
    kind = (page_kind or "").strip().lower()
    entity = (page_entity or "").strip()

    # section_recipes uses page-kind-ish keys (e.g. "detail", "list") in some
    # vocabularies and screen-slug keys ("member/dashboard") in others. We
    # send BOTH the kind-scoped and any recipe whose key contains the entity
    # name to keep the prompt tight.
    recipes: dict[str, list[str]] = {}
    for screen, sections in (vocab.section_recipes or {}).items():
        if not isinstance(sections, list):
            continue
        if screen == kind or (entity and entity.lower() in screen.lower()):
            recipes[screen] = sections

    # component_preferences — probe standard casing variants.
    pref = None
    for name in (entity, entity.lower(), entity.lower() + "s"):
        if not name:
            continue
        pref = (vocab.component_preferences or {}).get(name)
        if pref is not None:
            break

    return {
        "id": vocab.id or "",
        "section_recipes_for_kind": recipes,
        "component_preference": {
            "shape": getattr(pref, "shape", ""),
            "primary_field": getattr(pref, "primary_field", ""),
            "primary_component": getattr(pref, "primary_component", ""),
        } if pref is not None else {},
        "signature_states": dict(vocab.signature_states or {}),
        "status_badges": dict(vocab.status_badges or {}),
    }


# Bindings are evaluated by FEEL-lite (packages/renderer → @tentoroforge/
# feel-lite), NOT by JavaScript. Every JS-ism the model reaches for parses as
# an error, is swallowed, and silently yields false — so the node renders as
# though the condition were never true. Observed on 6q7oqejv: `{{!x.length}}`
# on two list pages, which would have hidden their empty states forever.
#
# The empty-state recipe is the important half. The model wrote a negation
# because it did not know `Conditional` already has a falsy branch, so there
# is nothing to negate.
_BINDING_SYNTAX_BLOCK = """BINDING EXPRESSIONS — `{{...}}` is FEEL-lite, not JavaScript.

Supported inside `{{ }}`:
  - a dataSource name .................. {{warehouses}}
  - a field path ....................... {{product.name}}
  - an array index ..................... {{suppliers[0].name}}
  - a length ........................... {{warehouses.length}}
  - comparison ......................... {{stock.quantity < 10}}
  - a formatter ........................ {{order.total | currency}}

NOT supported — these parse as an error and evaluate to false, so the node
silently never appears:
  - `!x` / `!x.length`   (no JS negation)
  - `&&`, `||`, `? :`    (no JS boolean/ternary operators)
  - `x.map(...)`, `x.filter(...)`, or any method call

`bind` on a form control is NOT a binding — the renderer drops it and the
Form collects by `name`. Use a bare field name; there is no `form` scope.
(On Text/Repeat, `bind` IS a real binding.)
  RIGHT {"name":"title","bind":"title"}   WRONG {"bind":"{{form.title}}"}

To show something ONLY WHEN A LIST IS EMPTY, do not negate. `Conditional`
takes a truthy `when` plus TWO children — the first renders when truthy, the
second when falsy:

  {"type":"Conditional","props":{"when":"{{warehouses.length}}"},
   "children":[ {"type":"Table", ...}, {"type":"EmptyStateRich", ...} ]}

PROPS: use only prop names listed for that component above. A name that is
not on its list is dropped silently at render time — the component still
appears, but that prop does nothing (an input whose value prop was invented
renders permanently blank).
"""


@lru_cache(maxsize=1)
def _contract_props() -> dict[str, set[str]]:
    """Real prop names per component, from ``component-contracts.json``.

    That file is generated from the components' Zod props, so it is the only
    honest answer to "does this component accept this prop". Components with
    an empty entry (props reached through a schema-package indirection the
    extractor can't follow) are omitted — no entry means no basis to judge,
    which is the correct outcome for them.

    Cached: read once per process, and it never changes at runtime.
    """
    try:
        from services.library_manifest import _default_contracts_path
        raw = json.loads(
            _default_contracts_path().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — a missing dist must not break composing
        return {}
    return {name: set(entry.keys())
            for name, entry in raw.items()
            if isinstance(entry, dict) and entry}


def _format_manifest_block(manifest_subset: dict) -> str:
    """Render the filtered manifest as a compact table for the prompt.

    For components with a curated shape example in
    :mod:`services.component_examples`, appends a correct-shape JSON
    snippet under the entry. Without examples the composer's LLM guesses
    prop shapes from names alone and breaks shape-heavy components
    (FilterBar chips render as broken dropdowns, Cascader options as
    empty boxes, Table headers as raw uppercased keys). One-line JSON
    per example — ~600-1000 tokens total for the top-15 shape-heavy
    components, cheap next to composition itself.
    """
    if not isinstance(manifest_subset, dict):
        return ""
    comps = manifest_subset.get("components")
    if not isinstance(comps, dict) or not comps:
        return ""
    try:
        from services.component_examples import COMPONENT_EXAMPLES
    except Exception:  # noqa: BLE001 — examples are optional enrichment
        COMPONENT_EXAMPLES = {}
    import json as _json
    lines: list[str] = [
        "LIBRARY COMPONENTS AVAILABLE (name -> category / data_shape).",
        "You MUST pick node types from this list — no invented names.",
        "For components with a `props example` line, copy the shape verbatim —",
        "the library validates props strictly and mis-shaped props render broken.",
    ]
    for name in sorted(comps.keys()):
        e = comps[name]
        if not isinstance(e, dict):
            continue
        cat = e.get("category", "")
        shape = e.get("data_shape", "")
        summary = e.get("summary", "")
        key_props = e.get("key_props") or []
        props_hint = ""
        if isinstance(key_props, list) and key_props:
            names = [p.get("name") for p in key_props if isinstance(p, dict) and p.get("name")]
            if names:
                props_hint = f"  key_props: {', '.join(names)}"
        summary_snip = f"  — {summary}" if summary else ""
        lines.append(f"  - {name} [{cat}/{shape}]{summary_snip}{props_hint}")
        ex = COMPONENT_EXAMPLES.get(name)
        if isinstance(ex, dict):
            # One-line JSON keeps token cost bounded; the LLM parses it fine.
            lines.append(f"      props example: {_json.dumps(ex, separators=(',', ':'))}")
    return "\n".join(lines) + "\n"


def _format_patterns_block(patterns: list[dict] | None) -> str:
    if not isinstance(patterns, list) or not patterns:
        return ""
    lines: list[str] = ["DESIGN PATTERNS TO REFLECT ON THIS PAGE (where applicable):"]
    for p in patterns:
        if isinstance(p, str):
            name = p.strip()
            if name:
                lines.append(f"  - {name}")
            continue
        if not isinstance(p, dict):
            continue
        name = str(p.get("title") or p.get("name") or p.get("id") or "").strip()
        if not name:
            continue
        summary = str(p.get("summary") or p.get("description") or "").strip()
        line = f"  - {name}"
        if summary:
            line += f": {summary}"
        lines.append(line)
    if len(lines) == 1:
        return ""
    return "\n".join(lines) + "\n"


def _variance_line(seed: int | str | None) -> str:
    if seed is None:
        return ""
    s = str(seed).strip()
    if not s:
        return ""
    return (
        f"\nVARIANCE TOKEN: {s}. Use this seed to introduce controlled "
        "variability — section orderings, empty-state phrasings, tone "
        "of headings — but never to violate hard constraints.\n"
    )


def _brief_identity_slice(brief: Any | None) -> dict | None:
    if brief is None:
        return None
    identity = getattr(brief, "identity", None)
    if identity is None:
        return None
    try:
        if hasattr(identity, "model_dump"):
            data = identity.model_dump(mode="json", exclude_none=True)
        elif hasattr(identity, "dict"):
            data = identity.dict(exclude_none=True)  # type: ignore[call-arg]
        else:
            data = dict(identity)
    except Exception:  # noqa: BLE001
        return None
    picked: dict[str, Any] = {}
    for k in ("domain", "register", "voice", "voice_free"):
        v = data.get(k)
        if v not in (None, "", [], {}):
            picked[k] = v
    return picked or None


def _preset_slice(preset: VisualLock) -> dict:
    """Palette + typography names only — the renderer applies tokens; the
    prompt just needs to remind the LLM of the app's visual voice."""
    if preset is None:
        return {}
    try:
        data = preset.model_dump(mode="json", exclude_none=False)
    except AttributeError:
        data = preset.dict()  # type: ignore[attr-defined]
    return {
        "preset_name": data.get("preset_name") or "",
        "palette": data.get("palette") or {},
        "typography": data.get("typography") or {},
    }


def _build_prompt(
    page: dict,
    plan: dict,
    vocab: ArchetypeVocabulary,
    preset: VisualLock,
    manifest_subset: dict,
    *,
    patterns: list[dict] | None,
    variance_seed: int | str | None,
    brief: Any | None,
    has_reference_images: bool = False,
) -> str:
    page_slice = _summarize_page(page)
    vocab_slice = _summarize_vocab(vocab, page_slice["kind"], page_slice["entity"])
    preset_slice = _preset_slice(preset)
    identity = _brief_identity_slice(brief)
    entity_map = _entity_fields_map(plan)

    parts: list[str] = []
    parts.append(
        "You are composing ONE full page schema for a Next.js app. The output "
        "is a single JSON object that the runtime renders directly — no code, "
        "no prose. Every choice you make must map to real registered "
        "components and real entities the plan already declares.\n"
    )
    parts.append(
        "\nSCHEMA CONTRACT (v2):\n"
        "  Page = {\n"
        '    "schemaVersion": "2",\n'
        '    "id":            <string>,\n'
        '    "route":         <string>,\n'
        '    "layout":        "main",\n'
        '    "dataSources":   [DataSource, ...] (optional),\n'
        '    "root":          Node\n'
        "  }\n"
        "  Node = {\n"
        '    "type":     <ComponentName from LIBRARY COMPONENTS below>,\n'
        '    "props":    { ... optional per-component props },\n'
        '    "children": [Node, ...] (optional)\n'
        "  }\n"
        "  DataSource = {\n"
        '    "name":    <string, referenced by bindings as {{name}}>,\n'
        '    "entity":  <one of the PLAN ENTITIES below>,\n'
        '    "op":      "list" | "get" | "aggregate" | "series",\n'
        '    "filter":  { ... optional field==value },\n'
        '    "orderBy": [ { field, dir: "asc"|"desc" }, ... ],\n'
        '    "limit":   <int>\n'
        "  }\n"
        "  Bindings: use `{{name}}` for whole rows/lists and `{{name.field}}` "
        "for scalar text, e.g. `content: \"{{customer.fullName}}\"`.\n"
    )
    parts.append(
        "\nHARD CONSTRAINTS (the assembler REJECTS the whole output if any fail):\n"
        "  * Every `type` MUST appear in LIBRARY COMPONENTS below.\n"
        "  * Every `dataSource.entity` MUST appear in PLAN ENTITIES below.\n"
        "  * Every `{{name}}` binding MUST reference either a defined "
        "dataSource.name OR a `<dataSource>.<field>` where field is a "
        "declared column of that entity.\n"
        "  * The `root` node MUST be a `Stack` with `props.gap` set. Use "
        '`"tokens.spacing.6"` unless the vocab suggests otherwise.\n'
        "  * NEVER put a raw hex value in an inline `style`. Use tokens only "
        '(`"tokens.spacing.4"`, `"tokens.color.brand"`, etc). The palette '
        "below is FOR REFERENCE — the renderer applies tokens.\n"
    )
    if has_reference_images:
        # The screens lead the message. Say what they are and what to take
        # from them, or the model treats them as decoration and composes
        # from the text alone — which is the behaviour this replaced.
        parts.append(
            "\nREFERENCE DESIGN: the images at the top of this message are the "
            "approved design for this product. Compose this page so it looks "
            "like it belongs in that set. Match their density, their grouping "
            "and section rhythm, how much chrome sits above the content, "
            "whether cards carry borders or sit flat, and how headings and "
            "labels are weighted. Take the LAYOUT from them, not the content "
            "— the entities, fields and bindings below are authoritative, and "
            "no label from a reference screen belongs in the output unless "
            "this app's own plan uses it.\n"
        )
    parts.append("\nPAGE TO COMPOSE:\n" + json.dumps(page_slice, indent=2))
    parts.append("\nPLAN ENTITIES (name -> fields):\n" + json.dumps(entity_map, indent=2))
    if identity is not None:
        parts.append("\nBRIEF IDENTITY:\n" + json.dumps(identity, indent=2))
    if vocab_slice:
        parts.append(
            "\nVOCAB SLICE (recipes + preferences the archetype already committed to):\n"
            + json.dumps(vocab_slice, indent=2)
        )
    if preset_slice:
        parts.append("\nVISUAL PRESET (reference only — apply via tokens):\n"
                     + json.dumps(preset_slice, indent=2))
    patterns_block = _format_patterns_block(patterns)
    if patterns_block:
        parts.append("\n" + patterns_block)
    variance_block = _variance_line(variance_seed)
    if variance_block:
        parts.append(variance_block)
    manifest_block = _format_manifest_block(manifest_subset)
    if manifest_block:
        parts.append("\n" + manifest_block)
    parts.append("\n" + _BINDING_SYNTAX_BLOCK)
    parts.append(
        "\nOUTPUT: pure JSON, no prose, no code fences. Produce ONE Page object "
        "matching the SCHEMA CONTRACT above. Prefer the vocab's component "
        "preference when it exists; otherwise pick the best-fit type for the "
        "page kind (list -> Table, detail -> Card+DescriptionList, "
        "dashboard -> Grid+MetricTile+Chart, form -> Form + input nodes)."
    )
    return "".join(parts)


# --------------------------------------------------------------------- #
# LLM call — kept small so tests can monkeypatch this seam
# --------------------------------------------------------------------- #

async def _call_llm(
    prompt: str,
    *,
    model: str,
    timeout_s: float,
    images: list[dict] | None = None,
) -> dict:
    """Return parsed JSON dict from the LLM. Raises on failure — callers
    convert exceptions into ``source: "failed"`` provenance.

    ``images`` are Anthropic-shaped content blocks for the project's
    designated montage — as the attachment loader returns them, which
    means a short text label before each image. They lead the message,
    ahead of the instruction, so the model is looking at the reference
    screens while it reads what to do — the prose reference stays in the prompt as
    well, since it carries the typed targets the images can't state.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    try:
        from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"anthropic SDK unavailable: {exc}") from exc

    content: Any = prompt
    if images:
        content = [*images, {"type": "text", "text": prompt}]

    client = llm_client.AsyncAnthropic(api_key=api_key)
    coro = client.messages.create(
        model=model,
        max_tokens=8000,
        temperature=0.4,
        messages=[{"role": "user", "content": content}],
    )
    response = await asyncio.wait_for(coro, timeout=timeout_s)
    text = "".join(
        getattr(b, "text", "") for b in response.content
        if getattr(b, "type", "") == "text"
    ).strip()
    if not text:
        raise RuntimeError("empty LLM response")
    if text.startswith("```"):
        text = text.strip("`")
        nl = text.find("\n")
        if nl != -1:
            text = text[nl + 1 :]
        text = text.strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    return json.loads(text)


# --------------------------------------------------------------------- #
# Validation — Python mirror of the essentials in packages/schema/src/page.ts
# --------------------------------------------------------------------- #

_BINDING_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")


def _inert_bind_paths(root: Any, manifest_subset: dict) -> set[tuple[str, ...]]:
    """Paths of ``props.bind`` strings that no renderer ever resolves.

    ``bind`` carries THREE different contracts depending on where it sits,
    which is why this has to be path-precise rather than a name blocklist:

      * ``props.bind`` on a form control — DEAD. Input/Textarea/DatePicker
        destructure it as ``bind: _bind`` and drop it; the Form collects
        values by ``name`` through FormData. Nothing reads the string.
      * ``node.bind`` on a Text — a real binding expression, resolved via
        ``resolveBinding``.
      * ``node.bind`` on a Repeat — a dataSource name.

    Only the first is exempt. Exempting the name globally would blind the
    validator on Text and Repeat, which are exactly the nodes where a bad
    binding produces the empty-table class this validator exists to catch.

    Input-ness comes from the library manifest's own ``category``, not a
    hand-typed list, so a new control is covered the day it is registered.
    """
    comps = manifest_subset.get("components") if isinstance(manifest_subset, dict) else None
    inputs = {
        name for name, entry in (comps or {}).items()
        if isinstance(entry, dict) and entry.get("category") == "input"
    }
    if not inputs:
        return set()

    found: set[tuple[str, ...]] = set()

    def walk(node: Any, path: tuple[str, ...]) -> None:
        if isinstance(node, dict):
            if node.get("type") in inputs:
                props = node.get("props")
                if isinstance(props, dict) and isinstance(props.get("bind"), str):
                    found.add(path + ("props", "bind"))
            for k, v in node.items():
                walk(v, path + (str(k),))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, path + (f"[{i}]",))

    walk(root, ("root",))
    return found



def _walk_strings(obj: Any, sink: list[tuple[str, tuple[str, ...]]], path: tuple[str, ...] = ()) -> None:
    """Collect (string_value, dot-path) tuples from the tree.

    Only recurses into dicts and lists. Path is kept for error messages.
    """
    if isinstance(obj, str):
        sink.append((obj, path))
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _walk_strings(v, sink, path + (str(k),))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk_strings(v, sink, path + (f"[{i}]",))


def _walk_nodes(node: Any, sink: list[dict]) -> None:
    """Depth-first walk that appends every node-shaped dict to ``sink``.

    A node is a dict with a string ``type`` field AND is reached via a
    ``children`` list (or as the root). Props are NOT walked as nodes —
    Table.props.columns or Select.props.options often carry configuration
    dicts with a ``type`` key (``{type: "select", ...}`` for a filter
    config, or a column with ``{type: "date"}``) that would spuriously
    fail the "is-in-manifest" check if we treated them as components.
    """
    if isinstance(node, dict) and isinstance(node.get("type"), str):
        sink.append(node)
        children = node.get("children")
        if isinstance(children, list):
            for c in children:
                _walk_nodes(c, sink)
    elif isinstance(node, list):
        for v in node:
            _walk_nodes(v, sink)
    # Bare dicts (e.g. the root wrapper) are not nodes on their own; the
    # caller passes ``schema["root"]`` directly, which IS a node.


# Props whose string values are PER-ROW templates, not dataSource bindings.
#
# ``Table.applyTemplate`` (packages/library/src/components/Table/Table.tsx)
# substitutes these against the row record, and its regex deliberately
# accepts BOTH ``{id}`` and ``{{id}}`` — widened, per the comment there,
# because matching only ``{id}`` left stray braces and broke the detail
# route. So ``{{id}}`` inside a rowAction navigate is CORRECT output that
# renders correctly.
#
# The binding validator below reads every ``{{...}}`` as a dataSource
# reference, so it was failing those pages — and a failed composition is
# discarded entirely, falling back to the deterministic composer. That hit
# list and detail pages hardest, which are exactly the pages a reference
# screen has the most to say about.
_PER_ROW_TEMPLATE_PROPS = frozenset({"rowHref", "navigate", "href"})


def _is_per_row_template(path: tuple[str, ...]) -> bool:
    """True when this string is resolved against a row, not a dataSource."""
    if not path:
        return False
    if path[-1] not in _PER_ROW_TEMPLATE_PROPS:
        return False
    # `rowHref` is row-scoped by definition. `navigate`/`href` only when they
    # sit inside a row-action list — a top-level Button navigate has no row
    # to resolve against and must still validate.
    if path[-1] == "rowHref":
        return True
    return any(seg in ("rowActions", "bulkActions") for seg in path)


def _validate_page_schema(
    schema: Any,
    plan: dict,
    manifest_subset: dict,
) -> tuple[bool, list[str], list[str]]:
    """Return ``(is_valid, errors, warnings)``.

    Errors block the composition (caller returns None). Warnings surface
    on provenance but don't fail the schema.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(schema, dict):
        return False, ["schema is not a JSON object"], warnings

    if schema.get("schemaVersion") != "2":
        errors.append(f"schemaVersion must be '2', got {schema.get('schemaVersion')!r}")
    if not isinstance(schema.get("id"), str) or not schema["id"].strip():
        errors.append("id missing or not a non-empty string")
    if not isinstance(schema.get("route"), str) or not schema["route"].strip():
        errors.append("route missing or not a non-empty string")

    root = schema.get("root")
    if not isinstance(root, dict):
        errors.append("root missing or not an object")
        return False, errors, warnings

    if root.get("type") != "Stack":
        errors.append(f"root.type must be 'Stack', got {root.get('type')!r}")
    else:
        root_props = root.get("props") if isinstance(root.get("props"), dict) else {}
        if not root_props.get("gap"):
            warnings.append("root Stack has no props.gap — sections will collide")

    manifest_names: set[str] = set()
    if isinstance(manifest_subset, dict):
        comps = manifest_subset.get("components")
        if isinstance(comps, dict):
            manifest_names = set(comps.keys())

    entity_map = _entity_fields_map(plan)
    entity_names = set(entity_map.keys())

    # Data source validation.
    ds_names: set[str] = set()
    ds_entities: dict[str, str] = {}  # name -> entity
    ds_raw = schema.get("dataSources") or []
    if not isinstance(ds_raw, list):
        errors.append("dataSources must be a list when present")
        ds_raw = []
    for i, ds in enumerate(ds_raw):
        if not isinstance(ds, dict):
            errors.append(f"dataSources[{i}] is not an object")
            continue
        name = ds.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"dataSources[{i}].name missing")
            continue
        ds_names.add(name)
        entity = ds.get("entity")
        if entity is not None:
            if not isinstance(entity, str) or entity not in entity_names:
                errors.append(
                    f"dataSources[{i}].entity {entity!r} not in plan entities"
                )
            else:
                ds_entities[name] = entity

    # Node type validation.
    all_nodes: list[dict] = []
    _walk_nodes(root, all_nodes)
    for n in all_nodes:
        t = n.get("type")
        if not isinstance(t, str) or t not in manifest_names:
            errors.append(f"node.type {t!r} not in filtered library manifest")
        children = n.get("children")
        if children is not None and not isinstance(children, list):
            errors.append(f"node {t!r} has non-list children ({type(children).__name__})")

    # Prop-name validation — WARN only, deliberately.
    #
    # This exists because the binding checks below only verify that a
    # binding's VALUE resolves; nothing ever verified that the prop NAME
    # is real. An invented prop whose value happens to resolve sailed
    # through, and Zod then dropped it at render time without erroring —
    # which is how every composed edit form on 6q7oqejv shipped with
    # `props.binding` (the editor's name) instead of `bind`, and rendered
    # with no prefill at all.
    #
    # Checked against the CONTRACT, never against `key_props`. key_props is a
    # ranked list capped at 4 for prompt budget — `Form.workflow` and
    # `Form.submitLabel` are real props that fall off that cap, and flagging
    # them would bury the true positives in noise.
    #
    # Warn rather than error: the contract is generated, and a component whose
    # props hide behind an indirection (FadeIn/Stagger) yields an empty entry.
    # Failing composition on a gap in generated metadata would discard good
    # pages; a warning on provenance costs nothing and stays visible.
    _known = _contract_props()
    # Universal props every node may carry regardless of component.
    _UNIVERSAL = {"className", "style", "id", "children", "key"}
    for n in all_nodes:
        t = n.get("type")
        known = _known.get(t) if isinstance(t, str) else None
        if not known:            # unknown component, or no hints for it
            continue
        props = n.get("props")
        if not isinstance(props, dict):
            continue
        for pname in props:
            if pname in known or pname in _UNIVERSAL or pname.startswith("data-"):
                continue
            warnings.append(
                f"{t}.props.{pname} is not a listed prop — it will be dropped "
                f"at render time. Listed: {sorted(known)}"
            )

    # Binding validation — every {{name}} or {{name.field}} in a string
    # anywhere in the tree must resolve to a defined dataSource (and, when
    # a field is used, to a declared field of that dataSource's entity).
    strings: list[tuple[str, tuple[str, ...]]] = []
    _walk_strings(root, strings, path=("root",))
    _RESERVED_ROOTS = {
        "route", "params", "query", "session", "user", "actor",
        "now", "tokens",
        # Common Repeat / iterator locals — a Repeat's `as` prop introduces
        # a per-row alias that binding writers reference as `{{item.field}}`
        # or `{{row.field}}`. These are NOT dataSources, so treat as reserved.
        "item", "row", "record",
    }
    # Additionally: any Repeat node's props.as declares a local alias
    # (e.g. `as: "plan"` → `{{plan.name}}` is legal within the loop body).
    # Collect all such aliases and treat them as reserved binding roots.
    for n in all_nodes:
        if n.get("type") == "Repeat":
            props = n.get("props") if isinstance(n.get("props"), dict) else {}
            alias = props.get("as")
            if isinstance(alias, str) and alias.strip():
                _RESERVED_ROOTS.add(alias.strip())
    inert_binds = _inert_bind_paths(root, manifest_subset)
    for s, path in strings:
        if _is_per_row_template(path) or path in inert_binds:
            continue
        for m in _BINDING_RE.finditer(s):
            raw = m.group(1).strip()
            if not raw:
                continue
            # Support `foo.bar.baz` and `foo[0].bar` shapes — normalise to
            # a first token + trailing path.
            first = re.split(r"[.\[]", raw, maxsplit=1)[0].strip()
            if not first or first in _RESERVED_ROOTS:
                continue
            if first not in ds_names:
                errors.append(
                    f"binding {{{{{raw}}}}} at {'/'.join(path)} references unknown "
                    f"dataSource {first!r} (defined: {sorted(ds_names)})"
                )
                continue
            # If a field is referenced and we know the entity, verify it.
            rest = raw[len(first):].lstrip(". ")
            if rest:
                # Only check the first field hop; nested field lookups are
                # dynamic and would false-positive on genuine relations.
                field = re.split(r"[.\[]", rest, maxsplit=1)[0]
                entity = ds_entities.get(first)
                if entity and field:
                    fields = set(entity_map.get(entity) or [])
                    if fields and field not in fields:
                        # Some standard row helpers ({{row.rowIndex}}) — soft warn only.
                        warnings.append(
                            f"binding {{{{{raw}}}}} references field {field!r} "
                            f"not declared on entity {entity!r}"
                        )

    return (not errors), errors, warnings


# --------------------------------------------------------------------- #
# Auto-id — every composed node carries a stable `id` on disk
# --------------------------------------------------------------------- #
#
# LLM-composed schemas rarely emit per-node ``id`` fields. The runtime
# renderer synthesises ids on the fly (see ``dispatch.tsx`` +
# ``syntheticNodeId``), but downstream fragment-mapping components
# (DataBoundary, Conditional) key their children off ``child.id``; when
# both siblings arrive without an id they collapse to the same fallback
# key and React fires an "encountered two children with the same key"
# error. Assigning deterministic ids at composition time keeps the
# JSON on disk self-describing and fixes the class of key warnings at
# the source. The renderer's synthetic-key fallback is defence-in-depth,
# not the only line of protection.


def _ensure_node_ids(schema: Any, prefix: str = "root") -> int:
    """Walk the composed schema tree, assigning ``id`` to every node
    missing one. Returns the number of ids assigned (useful for
    provenance + tests).

    Format: ``<parent-path>-<type>-<index-in-parent-siblings>``. The
    root always gets ``id: "root"`` if missing. Never overwrites existing
    ids. Recurses only through ``children`` lists — never into ``props``
    or ``dataSources`` (those carry configuration dicts with a ``type``
    field that are NOT library components).
    """
    if not isinstance(schema, dict):
        return 0
    root = schema.get("root")
    if not isinstance(root, dict):
        return 0

    assigned = 0

    def _walk(node: dict, path: str) -> None:
        nonlocal assigned
        if not isinstance(node, dict):
            return
        if not node.get("id"):
            node["id"] = path
            assigned += 1
        children = node.get("children")
        if isinstance(children, list):
            t_counts: dict[str, int] = {}
            for c in children:
                if not isinstance(c, dict):
                    continue
                ctype = str(c.get("type") or "node")
                idx = t_counts.get(ctype, 0)
                t_counts[ctype] = idx + 1
                _walk(c, f"{path}-{ctype}-{idx}")

    _walk(root, prefix)
    return assigned


# --------------------------------------------------------------------- #
# Public entrypoint
# --------------------------------------------------------------------- #

def _make_failed_prov(reason: str, detail: Any | None = None) -> dict:
    prov: dict[str, Any] = {"source": "failed", "reason": reason}
    if detail is not None:
        prov["detail"] = detail
    return prov


async def compose_page(
    page: dict,
    plan: dict,
    vocab: ArchetypeVocabulary,
    preset: VisualLock,
    library_manifest: dict,
    *,
    patterns: list[dict] | None = None,
    variance_seed: int | str | None = None,
    brief: Any | None = None,
    reference_images: list[dict] | None = None,
    model: str = DEFAULT_MODEL,
    timeout_s: float = 60.0,
) -> tuple[dict | None, dict]:
    """Compose a full page schema via LLM.

    On success returns ``(page_schema, provenance)`` with
    ``provenance["source"] == "composed"``. On ANY failure (LLM error,
    timeout, invalid JSON, validation reject) returns
    ``(None, {"source": "failed", "reason": ..., ...})`` so the caller
    can fall back to the deterministic composer.

    Never raises for reasons under this module's control.
    """
    page_kind = (page or {}).get("kind") or (page or {}).get("type") or ""
    manifest_subset = _filter_manifest_for_page(library_manifest, page_kind)

    key = cache_key(
        page or {}, plan or {}, vocab, preset, manifest_subset,
        patterns=patterns, variance_seed=variance_seed, brief=brief,
        reference_images=reference_images,
    )
    cached = _MEMO_CACHE.get(key)
    if cached is not None:
        schema, prov = cached
        return schema, {**prov, "source": "cached"}

    try:
        prompt = _build_prompt(
            page or {}, plan or {}, vocab, preset, manifest_subset,
            patterns=patterns, variance_seed=variance_seed, brief=brief,
            has_reference_images=bool(reference_images),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[page-composer] prompt build failed: %s", exc)
        return None, _make_failed_prov("prompt_build_failed", str(exc))

    try:
        raw = await _call_llm(prompt, model=model, timeout_s=timeout_s,
                              images=reference_images)
    except asyncio.TimeoutError:
        logger.warning("[page-composer] timeout on route=%s", (page or {}).get("route"))
        return None, _make_failed_prov("timeout")
    except json.JSONDecodeError as exc:
        logger.warning("[page-composer] invalid JSON: %s", exc)
        return None, _make_failed_prov("invalid_json", str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[page-composer] LLM call failed: %s", exc)
        return None, _make_failed_prov("llm_error", str(exc))

    if not isinstance(raw, dict):
        return None, _make_failed_prov("non_object", type(raw).__name__)

    valid, errors, warnings = _validate_page_schema(raw, plan or {}, manifest_subset)
    validation_report = {"errors": errors, "warnings": warnings}
    if not valid:
        logger.warning(
            "[page-composer] validation failed route=%s errors=%d first=%s",
            (page or {}).get("route"), len(errors), errors[0] if errors else "?",
        )
        return None, {
            **_make_failed_prov("validation_failed"),
            "validation": validation_report,
        }

    # Final step BEFORE caching: assign stable ids to every node the LLM
    # left un-id'd. Deterministic per input, so a cache hit still returns
    # the same auto-id'd schema — no cache-key change needed.
    ids_assigned = _ensure_node_ids(raw)

    prov = {
        "source": "composed",
        "route": raw.get("route") or (page or {}).get("route"),
        "changes": {
            "manifest_components_considered": len(
                (manifest_subset.get("components") or {})
            ),
            "data_sources_emitted": len(raw.get("dataSources") or []),
            "ids_assigned": ids_assigned,
        },
        "validation": validation_report,
    }

    if len(_MEMO_CACHE) >= _MEMO_MAX:
        try:
            _MEMO_CACHE.pop(next(iter(_MEMO_CACHE)), None)
        except StopIteration:
            pass
    _MEMO_CACHE[key] = (raw, prov)
    return raw, prov


def _run_coro_in_thread(coro_factory, timeout_s: float = 120.0):
    """Run an async coroutine on a fresh loop in a worker thread.

    Same shape as :func:`services.vocab_composer_pipeline._run_coro_in_thread`
    — used when the sync facade is invoked from an already-running event loop
    (typical FastAPI request handler).
    """
    import threading
    result: dict[str, Any] = {}

    def _runner() -> None:
        new_loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(new_loop)
            result["value"] = new_loop.run_until_complete(coro_factory())
        except Exception as err:  # noqa: BLE001
            result["error"] = err
        finally:
            try:
                new_loop.close()
            except Exception:  # noqa: BLE001
                pass

    t = threading.Thread(target=_runner, daemon=True, name="page-composer-bridge")
    t.start()
    t.join(timeout=timeout_s)
    if t.is_alive():
        raise TimeoutError(f"page composer did not complete within {timeout_s}s")
    if "error" in result:
        raise result["error"]
    return result.get("value")


def compose_page_sync(
    page: dict,
    plan: dict,
    vocab: ArchetypeVocabulary,
    preset: VisualLock,
    library_manifest: dict,
    *,
    patterns: list[dict] | None = None,
    variance_seed: int | str | None = None,
    brief: Any | None = None,
    model: str = DEFAULT_MODEL,
    timeout_s: float = 60.0,
) -> tuple[dict | None, dict]:
    """Sync facade over :func:`compose_page`.

    Bridges to a worker thread when a loop is already running so a
    FastAPI request handler doesn't block itself. Any bridge-level
    failure (timeout, loop shutdown) surfaces as
    ``source: "failed", reason: "bridge_error"``.
    """
    coro_factory = lambda: compose_page(
        page, plan, vocab, preset, library_manifest,
        patterns=patterns, variance_seed=variance_seed, brief=brief,
        model=model, timeout_s=timeout_s,
    )
    loop_running = False
    try:
        loop = asyncio.get_event_loop()
        loop_running = loop.is_running()
    except RuntimeError:
        loop_running = False
    try:
        if loop_running:
            return _run_coro_in_thread(coro_factory, timeout_s=timeout_s + 60.0)
        return asyncio.run(coro_factory())
    except Exception as err:  # noqa: BLE001
        logger.warning("[page-composer] sync bridge failed: %s", err)
        return None, _make_failed_prov("bridge_error", f"{type(err).__name__}: {err}")


__all__ = [
    "DEFAULT_MODEL",
    "cache_key",
    "compose_page",
    "compose_page_sync",
    "_ensure_node_ids",
]
