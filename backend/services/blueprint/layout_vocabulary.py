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
        #: What the translation had to give up, in words a reader can act on.
        self.recorded: list[str] = []

    def _record(self, kind: str, where: Any, what: str, detail: str,
                *, material: bool = False) -> None:
        """The binder's loss ledger, for the one path that has no ledger.

        `_translate_option_sources` is shared with the A2UI translator, whose
        `_Binder` writes every removal to a ledger. It grew a `_record` call
        (73b29f2) this stand-in never had, and on UAT (2026-09-18) the first
        page to reach that branch raised AttributeError — which no refusal
        handler catches — and took the whole build down. Kept rather than
        dropped: the caller surfaces it as an issue on the result.
        """
        self.recorded.append(f"{kind} {what} on {where}: {detail}"
                             + (" (material)" if material else ""))

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
        issues = getattr(result, "issues", None)
        if book.recorded and isinstance(issues, list):
            issues.extend(book.recorded)
        body["dataSources"] = book.sources
        _name_the_signed_in_user(body)
        # The renderer evaluates visibleIf/when with FEEL-lite; an author
        # writes `===`, `!==`, `&&`, `||`. Stored translated, so the Blueprint
        # speaks the contract's language (the planner translates again for
        # layouts that landed before this seam did).
        from services.blueprint.page_planner import speak_feel
        speak_feel(body.get("root"))


#: What a composer calls the signed-in person, and what the renderer calls them.
#: The interpolation scope carries `user: ctx.user` — `{{user.id}}`,
#: `{{user.homePropertyId}}`. A queue composed with
#: `{{currentUser.homePropertyId}}` interpolated to nothing, so the filter it
#: sent was empty and the page showed no cases even to the role it was for.
_USER_ALIASES = ("currentUser", "sessionUser", "me", "$user")


def _name_the_signed_in_user(body: dict) -> None:
    """Rewrite every `{{<alias>.x}}` binding in a layout to `{{user.x}}`."""
    import re
    pattern = re.compile(r"\{\{\s*(?:%s)\." % "|".join(re.escape(a) for a in _USER_ALIASES))

    def walk(node):
        if isinstance(node, dict):
            for k, v in list(node.items()):
                node[k] = walk(v)
            return node
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, str) and "{{" in node:
            return pattern.sub("{{user.", node)
        return node
    walk(body)
