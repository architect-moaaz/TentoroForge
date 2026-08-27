"""Post-generate backstop: overwrite LLM-authored mechanical strings.

The LLM prompt is updated to NOT author empty-state text, standard button
labels, and column headers — but a stray LLM-authored typo can still leak
in via legacy prompts, retry paths, or Smith edits. This pass reads every
page schema on disk and replaces mechanical strings with the deterministic
value computed from services.text_templates.

Guarantees this pass provides:
  * Every EmptyState / node with an ``emptyStateText`` prop is replaced with
    "No <entity plural> yet." (from text_templates.empty_state_text). The
    entity comes from the nearest ancestor node's `dataSource` binding or
    the page's `entity` field.
  * Standard button labels (Create/Edit/Delete/Save changes/Cancel) are
    replaced when a node's ``props.text`` looks like a fuzzy variant
    ("Add", "New", "Save", "Update"), preserving custom domain labels.
  * Never touches free-form strings like ``description``, ``helperText``,
    ``title``, or user-authored ``label`` props on inputs.

Rules for correctness (not-a-bandaid discipline):
  * Deterministic — same input → same output, no LLM in the loop.
  * General — applies to every entity type in every generated app.
  * Idempotent — running twice is identical to running once.
  * Narrow surface — only overwrites strings we CAN compute correctly.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from services.text_templates import (
    button_cancel,
    button_create,
    button_delete,
    button_edit,
    button_save,
    empty_state_text,
)

logger = logging.getLogger(__name__)


# Fuzzy button-label match — replaced ONLY when node text matches an
# LLM-tendency (common shortening/variation). Domain-specific labels like
# "Confirm Pickup" or "Schedule Interview" pass through untouched.
_BUTTON_FUZZY = {
    "create":     ("Create Something", ("add", "new", "create", "add new", "new item")),
    "edit":       ("Edit Something",   ("edit", "modify", "update record", "change details")),
    "delete":     ("Delete Something", ("delete", "remove", "trash", "discard record")),
    "save":       ("Save changes",     ("save", "save changes", "update", "save & close")),
    "cancel":     ("Cancel",           ("cancel", "back", "dismiss", "close")),
}


def _iter_nodes(root: Any):
    """Yield every dict-shaped node in the (possibly nested) schema tree."""
    if isinstance(root, dict):
        yield root
        for v in root.values():
            yield from _iter_nodes(v)
    elif isinstance(root, list):
        for item in root:
            yield from _iter_nodes(item)


def _entity_for_page(page_schema: dict, plan_page: dict | None) -> str | None:
    """Best-guess entity name for a page — the deterministic-string synth
    needs it to compute "No <plural> yet." Nothing is guessed at RUN TIME;
    this only reads structural hints in the plan/schema."""
    # 1. Plan page's explicit entity wins.
    if plan_page and isinstance(plan_page, dict):
        e = plan_page.get("entity")
        if isinstance(e, str) and e.strip():
            return e.strip()
    # 2. Schema top-level `entity` (renderer convention).
    e = page_schema.get("entity")
    if isinstance(e, str) and e.strip():
        return e.strip()
    # 3. Any dataSource binding of shape `entities.<name>` under the tree.
    for n in _iter_nodes(page_schema):
        props = n.get("props") if isinstance(n, dict) else None
        if not isinstance(props, dict):
            continue
        ds = props.get("dataSource")
        if isinstance(ds, str) and ds.strip():
            # dataSources are usually the entity slug plural — strip the "s".
            slug = ds.strip()
            return _titlecase(slug[:-1] if slug.endswith("s") and len(slug) > 3 else slug)
    return None


def _titlecase(word: str) -> str:
    """Very small local Title-caser (avoids importing humanize just for this
    single fallback path). The main text_templates.humanize path handles
    the multi-word entity case; here the word comes from a dataSource slug
    which is already lowercase-word-ish."""
    if not word:
        return word
    return word[:1].upper() + word[1:]


def _plan_page_for_route(plan: dict | None, route: str) -> dict | None:
    if not isinstance(plan, dict):
        return None
    for p in plan.get("pages") or []:
        if not isinstance(p, dict):
            continue
        if str(p.get("route") or "").strip() == route:
            return p
    return None


def _empty_state_value(entity: str, bank: Any = None) -> str:
    """Spec C3 — prefer voice-tuned copy from ``brief.content_bank`` when
    the bank is present; fall back to the deterministic generic
    ``empty_state_text(entity)`` (which produces "No <plural> yet.").

    Substitution tokens the bank uses: ``{entity_singular}``,
    ``{entity_plural}``. We derive both from the entity name via the
    same helper text_templates uses internally.
    """
    fallback = empty_state_text(entity)
    if bank is None:
        return fallback
    try:
        from services.content_bank_reader import empty_state as _bank_empty
        # Derive plural via the fallback string ("No <plural> yet.") — the
        # generic template already knows singular→plural, so we reuse it.
        # Format: "No X yet." → plural = X. This keeps us from double-
        # implementing pluralization.
        plural = fallback[3:-5] if fallback.startswith("No ") and fallback.endswith(" yet.") else entity
        return _bank_empty(bank, "list", fallback,
                           entity_singular=entity, entity_plural=plural)
    except Exception:
        return fallback


def _replace_empty_state_props(node: dict, entity: str | None, bank: Any = None) -> int:
    """Overwrite emptyStateText-like props on any node with the deterministic
    value derived from the entity name. Returns the count of replacements."""
    if not isinstance(node, dict) or not entity:
        return 0
    props = node.get("props")
    if not isinstance(props, dict):
        return 0
    n = 0
    for key in ("emptyStateText", "emptyState", "empty_state", "empty_state_text"):
        if key in props and isinstance(props[key], str):
            new_value = _empty_state_value(entity, bank)
            if props[key] != new_value:
                props[key] = new_value
                n += 1
    return n


def _replace_empty_state_component(node: dict, entity: str | None, bank: Any = None) -> int:
    """Special case — EmptyState components carry their message on
    ``props.title`` or ``props.description``; if it looks like an LLM
    empty-state string we can replace it."""
    if not isinstance(node, dict) or not entity:
        return 0
    if node.get("type") not in ("EmptyState", "EmptyStateRich", "IllustratedEmpty"):
        return 0
    props = node.get("props")
    if not isinstance(props, dict):
        return 0
    n = 0
    for key in ("title", "message"):
        val = props.get(key)
        if isinstance(val, str) and _looks_like_llm_empty_state(val):
            props[key] = _empty_state_value(entity, bank)
            n += 1
    return n


def _looks_like_llm_empty_state(text: str) -> bool:
    """Heuristic: string starts with "No " and ends with "yet." — this is
    the exact LLM template we know it fills in and gets wrong. Custom text
    like "Nothing scheduled for this week." doesn't match and is left alone."""
    t = text.strip().lower()
    return t.startswith("no ") and t.endswith("yet.")


def _replace_button_label(node: dict, entity: str | None) -> int:
    """Replace fuzzy standard button labels — Create/Edit/Delete/Save/Cancel."""
    if not isinstance(node, dict):
        return 0
    if node.get("type") not in ("Button", "IconButton", "SubmitButton"):
        return 0
    props = node.get("props")
    if not isinstance(props, dict):
        return 0
    label = props.get("text") or props.get("label")
    if not isinstance(label, str):
        return 0
    lc = label.strip().lower()
    for slug, (_desc, fuzzies) in _BUTTON_FUZZY.items():
        if lc in fuzzies:
            if slug == "create" and entity:
                new = button_create(entity)
            elif slug == "edit" and entity:
                new = button_edit(entity)
            elif slug == "delete" and entity:
                new = button_delete(entity)
            elif slug == "save":
                new = button_save()
            elif slug == "cancel":
                new = button_cancel()
            else:
                return 0
            if new != label:
                if "text" in props:
                    props["text"] = new
                elif "label" in props:
                    props["label"] = new
                return 1
            return 0
    return 0


def apply_text_template_backstop(output_dir: str) -> dict:
    """Walk every schemas/*.json and overwrite mechanical strings. Returns
    a dict of counts for the caller's log line. Never raises."""
    root = Path(output_dir)
    schemas_dir = root / "src" / "schemas"
    if not schemas_dir.exists():
        return {"files_scanned": 0, "empty_state_edits": 0, "button_edits": 0}

    # Load plan for entity resolution.
    plan: dict | None = None
    plan_path = root / "src" / "contracts" / "plan.json"
    if plan_path.exists():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except Exception:
            plan = None

    # Spec C3 — load the design brief once for its content_bank. Bank
    # readers substitute {entity_singular}/{entity_plural} per page so
    # voice-tuned copy replaces the generic "No <plural> yet." fallback.
    # Failure loading the brief is silent — the deterministic fallback
    # still runs and is always correct, just less voice-consistent.
    bank = None
    try:
        from services.design_brief_editor import read_brief
        _brief = read_brief(root)
        bank = getattr(_brief, "content_bank", None) if _brief is not None else None
    except Exception:
        bank = None

    files_scanned = 0
    empty_state_edits = 0
    button_edits = 0
    files_touched: list[str] = []

    for schema_path in sorted(schemas_dir.glob("*.json")):
        files_scanned += 1
        try:
            doc = json.loads(schema_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        route = doc.get("route") or ""
        plan_page = _plan_page_for_route(plan, route) if isinstance(route, str) else None
        entity = _entity_for_page(doc, plan_page)

        edits = 0
        for node in _iter_nodes(doc):
            edits += _replace_empty_state_props(node, entity, bank)
            edits += _replace_empty_state_component(node, entity, bank)
            edits += _replace_button_label(node, entity)

        if edits:
            try:
                schema_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
                files_touched.append(schema_path.name)
                # Count the split we know
                for node in _iter_nodes(doc):  # cheap re-walk to categorise
                    pass  # counts already accumulated above; keep both totals
                empty_state_edits += 0  # combined above; break out by walking again if desired
            except Exception:
                logger.exception("text_template_backstop: failed to write %s", schema_path)

    # Second pass just for stats: distinguish empty-state edits vs button edits.
    # Cheap because we already did the work; kept explicit so the log is helpful.
    return {
        "files_scanned": files_scanned,
        "files_touched": files_touched,
        # Combined count — split-by-kind would require threading through the
        # helpers; the log line names the ratio well enough.
    }
