"""The design system a Figma file already states (PRD §47, §40, §53, §116).

§47 is not asking for a judgement. A file's published variables *are* its
colour system, type scale, spacing and radii — the author already decided
them, and §47 says the extraction "becomes the starting Application Design
System". Renaming ``color/brand/primary`` to ``colors["brand/primary"]`` is a
projection, not a design decision.

So this is a service, not an agent (§116). A model asked to "extract the design
system" from a token list will paraphrase it — round a hex value, rename a
scale step, drop the one token it did not recognise — and every one of those
is a silent divergence from the file the user is holding us to.

On §46 and the UI registry
--------------------------
§46 maps Figma components into the application's UI registry, and this does not
write one. ``uiRegistry`` was removed from the pipeline deliberately: it named
components that were never code, and a page composed against invented component
names is composed against nothing. The Figma Intelligence Agent's §30
capability reflects that — it may write ``requirements`` and ``designSystem``,
not ``uiRegistry`` — so writing one here would be refused anyway.

The component list is not lost. It stays in the stored design reference, which
is where a registry backed by real components would read it from.

Why it runs *after* the design system agent
-------------------------------------------
``designSystem`` is a singleton section, so ``upsert`` shallow-merges and the
last writer of a key wins. §40 ranks a user-provided Figma design above the
platform's own design system, and §53 says explicit user designs have priority
over generic AI recommendations. Running this after the ``design_system`` node
makes that precedence a property of the merge order rather than an instruction
a model is asked to honour.

The agent's contribution is not lost — it owns the keys Figma has nothing to
say about (accessibility rules, responsive rules, interaction conventions,
information density), and those survive the merge untouched.
"""
from __future__ import annotations

import json
from typing import Any

from services.figma.reference import DesignReference


def _stringify(value: Any) -> str:
    """Token values as strings, because that is what the contract declares.

    Figma variables hold numbers, aliases and composite objects. ``16`` must
    not become ``"16.0"`` and a composite must stay readable, so integers keep
    their integer form and structures are rendered as compact JSON rather than
    Python ``repr``.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    if isinstance(value, str):
        return value
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _tokens(bucket: dict[str, Any]) -> dict[str, str]:
    return {str(k): _stringify(v) for k, v in (bucket or {}).items()}


def design_system_from(ref: DesignReference) -> dict[str, Any]:
    """§47 — the Figma-stated half of ``designSystem``.

    Only keys the file actually speaks to are returned. An empty ``colors``
    written over an agent's considered palette would be a regression disguised
    as an extraction, so absent buckets are omitted rather than emptied.
    """
    out: dict[str, Any] = {"derivedFromFigma": True}
    for key, bucket in (
        ("colors", ref.tokens.colors),
        ("typography", ref.tokens.typography),
        ("spacing", ref.tokens.spacing),
        ("radius", ref.tokens.radius),
        ("elevation", ref.tokens.elevation),
    ):
        projected = _tokens(bucket)
        if projected:
            out[key] = projected
    return out


def apply_design_reference(svc: Any) -> dict[str, Any]:
    """Project every connected design onto the Blueprint. Idempotent.

    Returns what it wrote, for the run report. Writes nothing and reports
    nothing when no design is connected, which is the whole of this node's
    behaviour for a prompt-only application.
    """
    from services.figma import store

    sources = svc.doc.get("designSources") or []
    if not sources:
        return {}

    written: dict[str, Any] = {}
    for source in sources:
        source_id = str(source.get("id") or "")
        ref = store.load(source_id, svc.output_dir)
        if ref is None:
            # §93 — a Blueprint restored without its payload names a source
            # whose design is gone. Recording it beats pretending the file had
            # no design system.
            svc.doc.setdefault("designSources", [])
            _note_gap(source, f"stored extraction for {source_id} is missing")
            continue

        design_system = design_system_from(ref)
        if len(design_system) > 1:  # more than derivedFromFigma alone
            current = svc.doc.get("designSystem") or {}
            svc.doc["designSystem"] = {**current, **design_system}
            written["designSystem"] = sorted(
                k for k in design_system if k != "derivedFromFigma"
            )

    svc.save()
    return written


def _note_gap(source: dict, message: str) -> None:
    gaps = source.setdefault("gaps", [])
    if message not in gaps:
        gaps.append(message)
