"""Deterministic JSON patch ops on a page schema.

Powers the drag-and-drop form builder: the canvas emits a typed op
(insert / delete / reorder / update-props) and the backend applies it
without any LLM in the hot path. All ops are pure — no in-place
mutation — so an optimistic-UI client can safely apply the same op
locally before the round-trip.

Path model:
  `at_path` / `parent_path` is a list of str|int that addresses a node
  inside the schema tree. For example ["root","children",0,"children",2]
  resolves to `schema["root"]["children"][0]["children"][2]`.

Errors:
  Every op raises :class:`PatchError` (never KeyError / IndexError /
  TypeError) with a human-readable message so the API can surface it
  directly to the UI.

Spec: docs/superpowers/specs/2026-07-22-dnd-form-builder.md.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Sequence


class PatchError(ValueError):
    """A schema-patch operation could not be applied. Message is safe to
    surface directly to the UI."""


# --------------------------------------------------------------------------- #
# Path resolution — the shared primitive
# --------------------------------------------------------------------------- #

def _resolve(schema: dict, path: Sequence[Any]) -> Any:
    """Walk `path` from `schema` and return the node. Raises PatchError
    on any dead branch (missing key, index out of range, or trying to
    index into a scalar)."""
    cur: Any = schema
    for i, seg in enumerate(path):
        try:
            cur = cur[seg]
        except (KeyError, IndexError, TypeError):
            raise PatchError(
                f"invalid path: segment {seg!r} at position {i} does not "
                f"resolve — path={list(path)}"
            )
    return cur


# --------------------------------------------------------------------------- #
# insert
# --------------------------------------------------------------------------- #

def insert(
    schema: dict,
    *,
    at_path: Sequence[Any],
    index: int,
    component: str,
    props: dict[str, Any] | None = None,
) -> dict:
    """Insert a new component into a children list. `at_path` must resolve
    to a `list` — typically an element's `children` array. `index` past
    the end is clamped (matches JS Array.splice + dnd-kit's "drop at end").
    Returns a new schema dict; the input is never mutated."""
    if not isinstance(component, str) or not component:
        raise PatchError("component must be a non-empty string")

    out = deepcopy(schema)
    target = _resolve(out, at_path)
    if not isinstance(target, list):
        raise PatchError(
            f"insert target at path={list(at_path)} is not a list — "
            f"got {type(target).__name__}"
        )
    node = {"type": component, "props": dict(props or {})}
    # Clamp index into [0, len].
    idx = max(0, min(int(index), len(target)))
    target.insert(idx, node)
    return out


# --------------------------------------------------------------------------- #
# delete
# --------------------------------------------------------------------------- #

def delete(schema: dict, *, at_path: Sequence[Any]) -> dict:
    """Remove the node at `at_path`. Path must be non-empty (deleting the
    root would leave an unrenderable schema). The final path segment is
    used as the key/index to remove; every segment before it must resolve.
    """
    if not at_path:
        raise PatchError("cannot delete root — at_path is empty")

    out = deepcopy(schema)
    parent = _resolve(out, at_path[:-1])
    last = at_path[-1]
    if isinstance(parent, list):
        if not isinstance(last, int) or last < 0 or last >= len(parent):
            raise PatchError(
                f"invalid path: index {last!r} out of range in parent "
                f"list of length {len(parent)}"
            )
        parent.pop(last)
    elif isinstance(parent, dict):
        if last not in parent:
            raise PatchError(
                f"invalid path: key {last!r} absent from parent dict — "
                f"keys are {sorted(parent.keys())}"
            )
        del parent[last]
    else:
        raise PatchError(
            f"invalid path: cannot delete from {type(parent).__name__} "
            f"parent at path={list(at_path[:-1])}"
        )
    return out


# --------------------------------------------------------------------------- #
# reorder
# --------------------------------------------------------------------------- #

def reorder(
    schema: dict,
    *,
    parent_path: Sequence[Any],
    from_index: int,
    to_index: int,
) -> dict:
    """Move a child within a list. `parent_path` MUST resolve to a list.
    `from_index` must be in-range; `to_index` past the end appends.
    Same-index is a no-op that still returns a deep copy (so the caller
    doesn't accidentally rely on identity)."""
    out = deepcopy(schema)
    target = _resolve(out, parent_path)
    if not isinstance(target, list):
        raise PatchError(
            f"reorder parent at path={list(parent_path)} is not a list — "
            f"got {type(target).__name__}"
        )
    if not isinstance(from_index, int) or from_index < 0 or from_index >= len(target):
        raise PatchError(
            f"invalid from_index {from_index!r} — parent list has "
            f"{len(target)} items"
        )
    node = target.pop(from_index)
    # Clamp to_index into [0, len(target)] AFTER the pop.
    idx = max(0, min(int(to_index), len(target)))
    target.insert(idx, node)
    return out


# --------------------------------------------------------------------------- #
# update_props
# --------------------------------------------------------------------------- #

def update_props(
    schema: dict,
    *,
    at_path: Sequence[Any],
    props: dict[str, Any],
) -> dict:
    """Shallow-merge `props` into the target node's `props` dict. A node
    without a `props` key gets one created."""
    if not isinstance(props, dict):
        raise PatchError(f"props must be a dict, got {type(props).__name__}")

    out = deepcopy(schema)
    node = _resolve(out, at_path)
    if not isinstance(node, dict):
        raise PatchError(
            f"update_props target at path={list(at_path)} is not an "
            f"object node — got {type(node).__name__}"
        )
    existing = node.get("props")
    if not isinstance(existing, dict):
        existing = {}
    existing.update(props)
    node["props"] = existing
    return out
