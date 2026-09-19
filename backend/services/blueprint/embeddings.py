"""Embedding fields — records found by what they look like or mean.

A field declared ``{"type": "vector", "embedding": {"of": "photo"}}`` holds the
embedding of another field on the same record. Everything that has to agree
about such a field reads it from here:

* the data layer emits a pgvector column of :data:`EMBEDDING_DIMENSIONS` with an
  HNSW cosine index (``projection.drizzle_column``);
* the runtime manifest ``src/lib/embedding-columns.ts`` tells the Data Engine
  which column to fill from which source, and whether the source is an image or
  text (:func:`embedding_columns`);
* pages and forms never show or ask for it, because nobody types a vector
  (:func:`is_embedding_field`).

The dimension is the platform's, not the Blueprint's: it is the output length
of the embedding model the platform runs (CLIP ViT-B/32 in
``sidecars/clip``), so it is a constant here and the sidecar reports its own
so the runtime can refuse a mismatch by name.
"""
from __future__ import annotations

import re
from typing import Any

#: Output length of the platform's embedding model (open_clip ViT-B-32).
#: Changing the model means changing this and re-embedding every row.
EMBEDDING_DIMENSIONS = 512

#: Field types whose value is a stored image (a forge_files id).
IMAGE_TYPES = frozenset({"image", "photo", "picture"})

#: Field types whose value is text an embedding can be computed from.
_TEXT_TYPES = frozenset({
    "text", "string", "str", "varchar", "char", "longtext", "mediumtext",
    "tinytext", "citext", "name", "url",
})


def _type(field: dict) -> str:
    return str(field.get("type") or "").lower().split("(")[0].strip()


def is_embedding_field(field: Any) -> bool:
    """A field the platform fills and no person reads or writes: a `vector`
    field, or an untyped one that says what it embeds. A field typed as
    something a person reads stays that type whatever else it carries —
    0l133sp2's `kycStatus: {type: "string", embedding: {of: "none"}}` became a
    vector(512) column, and a status nobody could write."""
    if not isinstance(field, dict):
        return False
    kind = _type(field)
    return kind in ("vector", "embedding") or (isinstance(field.get("embedding"), dict) and not kind)


def is_image_field(field: Any) -> bool:
    return isinstance(field, dict) and _type(field) in IMAGE_TYPES


def source_kind(field: dict) -> str | None:
    """``"image"`` or ``"text"`` for a field an embedding can be taken of."""
    t = _type(field)
    if t in IMAGE_TYPES:
        return "image"
    if t in _TEXT_TYPES:
        return "text"
    return None


def _snake(name: str) -> str:
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", (name or "").strip())
    return re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()


def entity_embeddings(entity: dict) -> list[dict[str, str]]:
    """The embedding columns of one entity that can actually be filled.

    A declaration whose ``of`` names no field on the entity, or a field of a
    kind nothing can embed, is left out: the column still exists (it was
    declared) but no row will ever have a value, and
    :func:`unfillable_embeddings` says why.
    """
    fields = {str(f.get("name")): f for f in entity.get("fields") or []
              if isinstance(f, dict) and f.get("name")}
    out: list[dict[str, str]] = []
    for f in fields.values():
        spec = f.get("embedding")
        if not isinstance(spec, dict):
            continue
        source = fields.get(str(spec.get("of") or ""))
        kind = source_kind(source) if source else None
        if not kind:
            continue
        out.append({
            "property": str(f["name"]),
            "column": _snake(str(f["name"])),
            "of": str(source["name"]),
            "source": kind,
        })
    return out


def unfillable_embeddings(entity: dict) -> list[str]:
    """Why each declared embedding on ``entity`` can never be filled."""
    fields = {str(f.get("name")): f for f in entity.get("fields") or []
              if isinstance(f, dict) and f.get("name")}
    problems: list[str] = []
    for f in fields.values():
        spec = f.get("embedding")
        if not isinstance(spec, dict):
            continue
        of = str(spec.get("of") or "")
        source = fields.get(of)
        if source is None:
            problems.append(
                f"{entity.get('name')}.{f['name']} embeds {of!r}, which is not "
                f"a field of {entity.get('name')}")
        elif not source_kind(source):
            problems.append(
                f"{entity.get('name')}.{f['name']} embeds {of!r}, a "
                f"{source.get('type')!r} field; only an image or a text field "
                f"can be embedded")
    return problems


def embedding_columns(doc: dict) -> dict[str, list[dict[str, str]]]:
    """Per entity — under every name the runtime may use for it — the columns
    to fill and what fills them."""
    out: dict[str, list[dict[str, str]]] = {}
    for entity in (doc.get("data") or {}).get("entities") or []:
        if entity.get("status") == "DEPRECATED":
            continue
        cols = entity_embeddings(entity)
        if not cols:
            continue
        name = str(entity.get("name") or "")
        table = str(entity.get("table") or _snake(name))
        for key in {name, name.lower(), table, table.lower()}:
            if key:
                out[key] = cols
    return out
