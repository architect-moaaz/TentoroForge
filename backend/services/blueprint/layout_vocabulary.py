"""The composers say it in their words; the contract reads its own.

Two composers write `pageLayouts` — the A2UI server and the LLM page author —
and both describe a dropdown's option source entity-first: `optionsFrom:
{entity, labelField, valueField}`. The Form field schema reads
`interaction.optionsFrom: {source, value, label}`, where `source` is a list in
the page's `dataSources`. `a2ui_to_forge` learned the translation for the
A2UI path; the agent path never went through it, and the refund intake form
on Criterion Refunds v2 was refused three more times with the right field in
the wrong words, while the record rule — taught to accept a form that
chooses the record — saw no source to resolve.

This is the one seam every layout passes before validation, whichever
composer wrote it. It translates in place and registers the list the source
names, reusing a list the layout already declares for that entity.
"""
from __future__ import annotations

from typing import Any


class _SourceBook:
    """What `option_source` needs of a binder: an entity index and a place to
    register a list, reusing one the layout already reads."""

    def __init__(self, registry: dict, sources: list[dict]):
        from services.a2ui_to_forge import _entity_index
        self.idx = _entity_index(registry)
        self.sources = sources

    def _add_source(self, spec: dict) -> str:
        for existing in self.sources:
            if (isinstance(existing, dict) and existing.get("entity") == spec.get("entity")
                    and str(existing.get("op") or "list") == str(spec.get("op") or "list")
                    and not existing.get("filter") and not existing.get("where")):
                return str(existing.get("name"))
        names = {str(s.get("name")) for s in self.sources if isinstance(s, dict)}
        name, n = str(spec["name"]), 2
        while name in names:
            name, n = f"{spec['name']}{n}", n + 1
        self.sources.append({**spec, "name": name})
        return name


def translate_layout_vocabulary(result: Any, doc: dict | None) -> None:
    """Translate every page-layout proposal's option sources and item values."""
    if doc is None:
        return
    proposals = [p for p in getattr(result, "proposals", []) or []
                 if getattr(p, "section", None) == "pageLayouts" and isinstance(getattr(p, "body", None), dict)]
    if not proposals:
        return
    from services.a2ui_authority import registry_from_blueprint
    from services.a2ui_to_forge import _translate_option_sources
    registry = registry_from_blueprint(doc)
    for proposal in proposals:
        body = proposal.body
        sources = [s for s in (body.get("dataSources") or []) if isinstance(s, dict)]
        book = _SourceBook(registry, sources)
        _translate_option_sources(body.get("root"), book, registry)
        body["dataSources"] = book.sources
