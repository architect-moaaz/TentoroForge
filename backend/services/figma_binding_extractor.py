"""Detect data bindings in Figma-derived page schemas and wire them
to the resource registry.

Input: a PageV2 schema produced by ``jsx_to_schema.transform_jsx_to_schema``
(typically a static tree — hardcoded strings, N sibling Cards with sample
data, no dataSources) + the app's canonical resource registry
(``registry.json``).

Output: the SAME schema with:
  * ``dataSources`` populated for every entity a repeat resolves to
  * ``Repeat`` nodes wrapping the collapsed template of each detected
    repeated sibling group, with ``bind: "<sourceName>"`` at top level
  * ``{{item.<field>}}`` bindings on Text/Image/Heading nodes inside a
    Repeat where the node's Figma name, position, or content pattern
    matches a real column on the resolved entity

Three deterministic detectors run in order — cheapest first, most
confident last takes precedence when they disagree:

  1. **Repeat detection** — sibling nodes with identical ``type`` and
     matching class-token signature are collapsed to one template +
     one ``Repeat`` wrapper. This alone catches most product cards,
     table rows, gallery items, message threads.
  2. **Name-match binding** — the Figma layer's data-name / content /
     ``className`` tokens are compared against the resolved entity's
     column names. A direct match binds; a token overlap binds with
     a slug-normalised comparison.
  3. **Semantic-type binding** — text matching a currency (``$149.99``),
     date (``Aug 15``), or email pattern is bound to the first column
     of the matching semantic type on the entity.

Prose (marketing copy, headings, non-matched labels) stays literal.

Best-effort — every step fail-safes to leaving the schema unchanged.
Never raises into the caller's happy path.
"""
from __future__ import annotations

import copy
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# ── Detectors ────────────────────────────────────────────────────────────

# Sibling-repeat detection: how many identical siblings before we treat
# them as a list. 2 is aggressive (any pair), 3 is safe. Start at 2 —
# design leans mostly on 3+ cards but pair-lists are common too.
_MIN_REPEAT_SIBLINGS = 2

# Currency: $149, $149.99, €99, ¥1000. Precision-loose on separator.
_CURRENCY_RE = re.compile(r"^\s*[\$€£¥₹]\s*[\d,]+(?:\.\d{1,2})?\s*$")

# Date: Aug 15, 2026 / 2026-08-15 / 08/15/2026. Very rough.
_DATE_RE = re.compile(
    r"^\s*(?:"
    r"\d{4}-\d{2}-\d{2}|"
    r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2}(?:,?\s*\d{4})?"
    r")\s*$"
)

_EMAIL_RE = re.compile(r"^\s*[\w.+-]+@[\w-]+\.[\w.-]+\s*$")


def extract_bindings(schema: dict, registry: dict) -> dict:
    """Return a NEW schema with bindings + dataSources populated.

    Never mutates the input schema. Returns the original schema unchanged
    on any error, missing registry, or nothing-to-bind case.
    """
    if not isinstance(schema, dict) or not isinstance(registry, dict):
        return schema
    entities = registry.get("entities") or {}
    if not entities:
        return schema
    try:
        out = copy.deepcopy(schema)
        _process_root(out, entities)
        return out
    except Exception:  # noqa: BLE001 — never break the caller
        logger.exception("[figma-bind] extract_bindings failed")
        return schema


# ── Traversal ────────────────────────────────────────────────────────────

def _process_root(schema: dict, entities: dict) -> None:
    """Walk the schema's root subtree; collapse repeats and bind fields.

    ``entities`` is the registry's entity map — {EntityName: {fields: {...}}}.
    dataSources declared this run are collected and appended to the
    schema's ``dataSources`` array at the end.
    """
    added_sources: dict[str, dict] = {}
    for name, ds in _existing_sources(schema):
        added_sources[name] = ds

    root = schema.get("root") or schema
    _walk_and_bind(root, entities, added_sources)

    if added_sources:
        # Preserve any existing dataSources not overwritten by our run.
        merged = list((schema.get("dataSources") or []))
        existing_names = {d.get("name") for d in merged if isinstance(d, dict)}
        for nm, ds in added_sources.items():
            if nm not in existing_names:
                merged.append(ds)
        schema["dataSources"] = merged


def _existing_sources(schema: dict) -> list[tuple[str, dict]]:
    ds = schema.get("dataSources") or []
    out: list[tuple[str, dict]] = []
    for d in ds:
        if isinstance(d, dict) and d.get("name"):
            out.append((d["name"], d))
    return out


def _walk_and_bind(node: Any, entities: dict, sources: dict) -> None:
    """Recursive walk. For every container node, check its `children` list
    for a repeated-siblings run; when detected, replace the run with a
    Repeat wrapper and bind fields inside its template.
    """
    if isinstance(node, dict):
        children = node.get("children")
        if isinstance(children, list) and len(children) >= _MIN_REPEAT_SIBLINGS:
            new_children = _collapse_repeats(children, entities, sources)
            if new_children is not children:
                node["children"] = new_children
                children = new_children
        # Recurse into whatever children we ended up with.
        if isinstance(children, list):
            for c in children:
                _walk_and_bind(c, entities, sources)
        for k, v in node.items():
            if k == "children":
                continue
            if isinstance(v, (dict, list)):
                _walk_and_bind(v, entities, sources)
    elif isinstance(node, list):
        for c in node:
            _walk_and_bind(c, entities, sources)


# ── Repeat detection ─────────────────────────────────────────────────────

def _node_signature(node: Any) -> str | None:
    """Fingerprint a node by its structural shape (type + top-level
    class tokens + children types). Two nodes with the same signature
    are treated as instances of the same template."""
    if not isinstance(node, dict):
        return None
    t = node.get("type") or node.get("component")
    if not t:
        return None
    props = node.get("props") or {}
    # Sort className tokens so order doesn't defeat the match. Keep the
    # signature-defining structural tokens; drop position-specific ones
    # (they'd differ per instance and defeat the match).
    cn = str(props.get("className") or "")
    tokens = tuple(sorted(
        tok for tok in cn.split()
        if not (
            tok.startswith("top-") or tok.startswith("left-")
            or tok.startswith("right-") or tok.startswith("bottom-")
            or tok in ("absolute",)
        )
    ))
    kids = tuple(
        ((c.get("type") or c.get("component")) or "?") if isinstance(c, dict) else "?"
        for c in (node.get("children") or [])
    )
    return f"{t}|{tokens}|{kids}"


def _collapse_repeats(children: list, entities: dict, sources: dict) -> list:
    """Look for consecutive runs of same-signature children. Collapse
    each run into ONE ``Repeat`` node whose child is the run's first
    element, transformed with ``{{item.<field>}}`` bindings.

    Returns the original list when no run qualifies.
    """
    # Group consecutive-run indices by signature.
    runs: list[tuple[int, int, str]] = []   # (start, end_exclusive, signature)
    i = 0
    while i < len(children):
        sig = _node_signature(children[i])
        if not sig:
            i += 1
            continue
        j = i + 1
        while j < len(children) and _node_signature(children[j]) == sig:
            j += 1
        if (j - i) >= _MIN_REPEAT_SIBLINGS:
            runs.append((i, j, sig))
        i = j
    if not runs:
        return children

    # Build new children list — non-run entries pass through; each run
    # becomes ONE Repeat node.
    new_children: list = []
    cursor = 0
    for start, end, _sig in runs:
        new_children.extend(children[cursor:start])
        template_source = children[start]
        entity_name = _guess_entity_for_run(children[start:end], entities)
        template = copy.deepcopy(template_source)
        if entity_name:
            _bind_template_fields(template, entities.get(entity_name) or {}, entity_name)
            ds_name = _slug(entity_name) + "s" if not _slug(entity_name).endswith("s") else _slug(entity_name)
            sources[ds_name] = {"name": ds_name, "entity": entity_name, "op": "list"}
            repeat = {"type": "Repeat", "bind": ds_name, "children": [template]}
        else:
            # Repeat detected but no entity resolves — still collapse to
            # a Repeat so the design intent is preserved; leave the bind
            # empty for a downstream pass (or human) to fill.
            repeat = {"type": "Repeat", "bind": "", "children": [template]}
        new_children.append(repeat)
        cursor = end
    new_children.extend(children[cursor:])
    return new_children


# ── Entity resolution ────────────────────────────────────────────────────

def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _guess_entity_for_run(nodes: list, entities: dict) -> str | None:
    """Pick the entity whose name / column set best matches this run.

    Signals (in decreasing weight):
      * A node in the run has ``data-name`` / ``_figmaNodeId`` label
        whose slug matches an entity name.
      * The union of text tokens in the run overlaps N+ column names on
        an entity — pick the entity with the most overlap.
    """
    # 1) direct data-name → entity match
    for n in nodes:
        for label in _extract_labels(n):
            key = _slug(label)
            for ent in entities:
                if _slug(ent) == key or _slug(ent) + "card" == key or key.startswith(_slug(ent)):
                    return ent

    # 2) text-token overlap with columns
    tokens = set()
    for n in nodes:
        tokens.update(_slug(t) for t in _extract_text_tokens(n) if t)
    if not tokens:
        return None

    best_ent, best_overlap = None, 0
    for ent, meta in entities.items():
        cols = (meta.get("fields") or {}).keys() if isinstance(meta, dict) else []
        cols_slugged = {_slug(c) for c in cols}
        overlap = len(tokens & cols_slugged)
        if overlap > best_overlap:
            best_ent, best_overlap = ent, overlap
    # Require at least ONE column-name match to be confident.
    return best_ent if best_overlap >= 1 else None


def _extract_labels(node: Any) -> list[str]:
    """Every user-facing label on a node — Figma data-name, layer id,
    className hint. Used for entity name matching."""
    out: list[str] = []
    if not isinstance(node, dict):
        return out
    props = node.get("props") or {}
    for k in ("data-name", "dataName", "_figmaName", "_figmaNodeId", "name"):
        v = props.get(k) or node.get(k)
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
    return out


def _extract_text_tokens(node: Any) -> list[str]:
    """All literal text under a node, split into rough word tokens.
    Used for column-name overlap detection."""
    out: list[str] = []
    if not isinstance(node, dict):
        return out
    props = node.get("props") or {}
    content = props.get("content")
    if isinstance(content, str):
        out.extend(re.split(r"[^a-zA-Z0-9]+", content))
    for k in ("children", "child"):
        v = node.get(k)
        if isinstance(v, list):
            for c in v:
                out.extend(_extract_text_tokens(c))
        elif isinstance(v, dict):
            out.extend(_extract_text_tokens(v))
    return [t for t in out if t]


# ── Field binding inside a Repeat template ───────────────────────────────

def _bind_template_fields(template: Any, entity_meta: dict, entity_name: str) -> None:
    """Walk the template subtree and replace hardcoded text/img.src with
    ``{{item.<field>}}`` bindings where a column can be resolved.

    Priority:
      1. Node data-name matches a column → bind
      2. Text content matches a semantic pattern (currency/date/email)
         AND the entity has exactly one column of that type → bind
    """
    cols = (entity_meta.get("fields") or {})
    if not cols:
        return
    col_names_by_slug = {_slug(c): c for c in cols}

    def _first_col_of_semantic(kind: str) -> str | None:
        """Return the first column whose declared semantic OR type matches."""
        for name, meta in cols.items():
            if not isinstance(meta, dict):
                continue
            sem = str(meta.get("semantic") or "").lower()
            typ = str(meta.get("type") or "").lower()
            if kind == "currency" and (sem in ("currency", "money", "price", "amount") or typ in ("decimal", "money", "numeric")):
                return name
            if kind == "date" and (sem in ("date", "datetime", "timestamp") or typ in ("timestamp", "date", "datetime")):
                return name
            if kind == "email" and (sem == "email" or "email" in _slug(name)):
                return name
        return None

    def _walk(n: Any) -> None:
        if isinstance(n, dict):
            t = n.get("type") or n.get("component")
            if t:
                # This is a real node — apply bindings if applicable.
                props = n.get("props") or {}
                if t in ("Text", "Heading") and isinstance(props.get("content"), str):
                    bind_col = _resolve_column_for_text_node(n, col_names_by_slug, _first_col_of_semantic)
                    if bind_col:
                        props["content"] = "{{item." + bind_col + "}}"
                        n["props"] = props
                elif t == "Image" and isinstance(props.get("src"), str):
                    for cand in ("imageUrl", "image_url", "photoUrl", "avatarUrl", "image", "photo", "avatar"):
                        if cand in cols:
                            props["src"] = "{{item." + cand + "}}"
                            n["props"] = props
                            break
            # Descend ONLY through children lists — never into `props`
            # (mutating it recursively caused infinite growth).
            for k in ("children", "child"):
                v = n.get(k)
                if isinstance(v, list):
                    for c in v:
                        _walk(c)
                elif isinstance(v, dict):
                    _walk(v)
        elif isinstance(n, list):
            for c in n:
                _walk(c)

    _walk(template)


def _resolve_column_for_text_node(
    node: dict,
    col_names_by_slug: dict[str, str],
    first_col_of_semantic,
) -> str | None:
    """Pick a column name to bind this Text/Heading node to. None = leave literal."""
    props = node.get("props") or {}
    content = props.get("content") or ""

    # 1) Figma layer name / data-name matches a column name
    for label in _extract_labels(node):
        key = _slug(label)
        if key in col_names_by_slug:
            return col_names_by_slug[key]
        # partial match — the label CONTAINS a column name
        for slug, real in col_names_by_slug.items():
            if slug and slug in key and len(slug) >= 3:
                return real

    # 2) Content matches a semantic pattern
    text = content.strip()
    if _CURRENCY_RE.match(text):
        col = first_col_of_semantic("currency")
        if col:
            return col
    if _DATE_RE.match(text):
        col = first_col_of_semantic("date")
        if col:
            return col
    if _EMAIL_RE.match(text):
        col = first_col_of_semantic("email")
        if col:
            return col

    # 3) Content is a single word that matches a column name
    text_slug = _slug(text)
    if text_slug and text_slug in col_names_by_slug:
        return col_names_by_slug[text_slug]

    return None


__all__ = ["extract_bindings"]
