"""Inject photoUrl / backgroundImage into emitted page schemas.

Runs AFTER the page/schema agents finish. Deterministic — walks the JSON
tree, finds Avatar/Hero nodes, and sets their photo fields from the
design_spec.entityPhotos map. Existing values are preserved (LLM wins
when it sets a real URL); the injector only fills GAPS.

Recursion strategy: walks every dict value, recursing into:
  - 'children' (list of nodes)
  - 'slots'   (dict of slot_name → list of nodes)
  - 'props'   (so deeply-nested props with their own trees work)
The walker carries a 'context' (currently just the nearest enclosing
Repeat's entity), used to pick which entityPhotos[X] applies to a given
Avatar instance.
"""
from __future__ import annotations
from typing import Any


def _first_photo(entity_photos: dict[str, str]) -> str | None:
    if not entity_photos:
        return None
    return next(iter(entity_photos.values()))


def _walk(node: Any, entity_photos: dict[str, str], current_entity: str | None) -> None:
    """In-place mutation. Recurses into children/slots/props."""
    if isinstance(node, list):
        for item in node:
            _walk(item, entity_photos, current_entity)
        return
    if not isinstance(node, dict):
        return

    node_type = node.get("type")

    # If this dict has no "type" key it is a slots map (slot_name → list of nodes).
    # Recurse into each slot's list of nodes.
    if node_type is None:
        for value in node.values():
            _walk(value, entity_photos, current_entity)
        return

    # Track current_entity from Repeat nodes for descendants
    new_entity = current_entity
    if node_type == "Repeat":
        # Look for an "entity" hint in props; fall back to the each-binding name
        # if it looks like a known entity (case-insensitive match against
        # entity_photos keys).
        props = node.get("props") or {}
        explicit = props.get("entity")
        if explicit and explicit in entity_photos:
            new_entity = explicit
        else:
            # heuristic: each="users" → "User" (singularise + capitalise)
            each = props.get("each") or ""
            if isinstance(each, str):
                candidate = each.rstrip("s").capitalize()
                if candidate in entity_photos:
                    new_entity = candidate

    # Inject Avatar.photoUrl
    # Match Avatar and any recipe-emitted variant whose name ends in "Avatar"
    # (e.g. PersonAvatar, InstructorAvatar). Same for Hero below.
    _is_avatar = node_type == "Avatar" or (
        isinstance(node_type, str) and node_type.endswith("Avatar") and node_type != "Avatar"
    )
    if _is_avatar:
        props = node.setdefault("props", {})
        if "photoUrl" not in props or not props["photoUrl"]:
            photo = entity_photos.get(current_entity or "") if current_entity else None
            if photo is None:
                photo = _first_photo(entity_photos)
            if photo:
                props["photoUrl"] = photo

    # Inject Hero.backgroundImage — accept any type ending in "Hero"
    # (PinnedMomentHero, FeaturedMomentHero, WellnessHero, etc.) so recipe
    # anchor components also get photos. Real defect: yoga studio dashboard
    # shipped a grey placeholder because the anchor was `PinnedMomentHero`
    # not the bare `Hero`.
    _is_hero = node_type == "Hero" or (
        isinstance(node_type, str) and node_type.endswith("Hero") and node_type != "Hero"
    )
    if _is_hero:
        props = node.setdefault("props", {})
        if not props.get("backgroundImage"):
            photo = entity_photos.get(current_entity or "") if current_entity else None
            if photo is None:
                photo = _first_photo(entity_photos)
            if photo:
                props["backgroundImage"] = {"url": photo, "overlay": 0.4}

    # Recurse
    for key in ("root", "children", "slots", "props"):
        if key in node:
            _walk(node[key], entity_photos, new_entity)


def inject_photos(page_schema: dict, entity_photos: dict[str, str]) -> dict:
    """Mutate page_schema in place AND return it. Safe to call with empty
    entity_photos (no-op)."""
    if not entity_photos:
        return page_schema
    _walk(page_schema, entity_photos, current_entity=None)
    return page_schema


def inject_photos_into_dir(output_dir: str, entity_photos: dict[str, str]) -> int:
    """Walk all *.json in src/schemas/ and apply the injector. Returns the
    count of files mutated (i.e. files where at least one photo field was
    set). Safe to call with empty entity_photos."""
    from pathlib import Path
    import json
    if not entity_photos:
        return 0
    schemas_dir = Path(output_dir) / "src" / "schemas"
    if not schemas_dir.exists():
        return 0
    mutated = 0
    for json_file in schemas_dir.rglob("*.json"):
        try:
            page = json.loads(json_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        before = json.dumps(page, sort_keys=True)
        inject_photos(page, entity_photos)
        after = json.dumps(page, sort_keys=True)
        if before != after:
            json_file.write_text(json.dumps(page, indent=2), encoding="utf-8")
            mutated += 1
    return mutated
