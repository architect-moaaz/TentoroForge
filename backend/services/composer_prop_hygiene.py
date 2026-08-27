"""Composer prop hygiene — strip Phase 2 metadata from schema `props`.

The dashboard / collection / record maquette composers author rich
schemas that include Phase 2 signature-moves + hero-kinds + section
rhythm metadata (``data-signature-move``, ``data-hero-kind``,
``data-slot``, ``data-section-tone``, ``data-layout``, ``data-mode``,
``data-footer-kind``, ``data-row-treatment``, ``data-filter-expr``,
``data-journey``) plus layout hints (``style``) INSIDE the ``props``
object of each node.

The composers author schemas that include ``data-*`` metadata inside
``props`` (Phase 2 signature-moves / hero-kinds / section rhythm) as
deliberate intent — the design team expects a later slice to consume
these off the DOM. That intent is documented in
``test_apply_collection_maquette``. So this module DOES NOT strip
``data-*``; it only strips keys that are guaranteed duplicates of
something the renderer already handles through a dedicated slot:

* ``style`` in ``props`` is duplicated by the node-level ``style``
  slot (``StyleSlot`` handles background/motion/color/spacing) and the
  composer accidentally emitting a raw ``style`` object inside props
  yields a strict-mode warning with no upside.

If a future slice needs to strip more, add the key here + update the
matching tests so intent stays visible. If the goal is to silence
schema warnings for ``data-*``, extend the renderer zod schemas with a
node-level passthrough for the ``data-*`` prefix — that closes the
warning while preserving the composer's intent.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Duplicate-slot keys only. See module docstring for the rationale on
# why data-* attrs are intentionally NOT included.
_METADATA_KEYS_DROP = frozenset({
    "style",
})


def sanitize_props_recursive(node: Any) -> int:
    """Recursively strip duplicate-slot keys (currently just ``style``)
    from every node's ``props``. Returns the number of keys scrubbed.
    Mutates in place. Never touches node-level attrs (composers deliberately
    stash Phase 2 metadata there for downstream consumption)."""
    if not isinstance(node, dict):
        return 0

    scrubbed = 0
    props = node.get("props")
    if isinstance(props, dict):
        for key in list(props.keys()):
            if key in _METADATA_KEYS_DROP:
                del props[key]
                scrubbed += 1

    # Recurse into children + slots.
    kids = node.get("children")
    if isinstance(kids, list):
        for child in kids:
            scrubbed += sanitize_props_recursive(child)

    slots = node.get("slots")
    if isinstance(slots, dict):
        for arr in slots.values():
            if isinstance(arr, list):
                for child in arr:
                    scrubbed += sanitize_props_recursive(child)
    return scrubbed


def sanitize_schema(schema: dict) -> int:
    """Sanitize an entire page schema (``{root: {...}, dataSources: [...]}``).
    Returns the total number of props scrubbed. Mutates in place.
    Callers use the return value only to decide whether to log."""
    if not isinstance(schema, dict):
        return 0
    root = schema.get("root")
    if not isinstance(root, dict):
        return 0
    n = sanitize_props_recursive(root)
    if n:
        logger.debug("[composer-hygiene] scrubbed %d Phase 2 metadata key(s)", n)
    return n
