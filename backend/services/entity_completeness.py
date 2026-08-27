"""Detect entities that MUST carry a media/photo field, and ensure they do.

Root cause this addresses: LLM-authored plans forget domain-obvious fields
because the planner treats field authoring as free-form and there's no
completeness contract. B-021.7 was "Plant has no imageUrl" — a plant is
plainly a physical thing users want a photo of, but the planner didn't
emit that column.

This module extends `services.commerce_flag` with a different completeness
signal: even when the app isn't a storefront, entities that represent
media-bearing real-world things (Recipe, Property, Vehicle, Portfolio, Post,
Profile, Event, Room, Menu, Photo) need a photo field to be useful.

Rules for correctness (not-a-bandaid):
  * Deterministic — same plan → same output.
  * General — applies to every generated app that has product/media entities.
  * Additive — never removes existing fields; never overwrites a field that
    already has ANY media-like column.
  * Idempotent — running twice is identical to running once.
"""

from __future__ import annotations

import logging
import re
from typing import Iterable

logger = logging.getLogger(__name__)


# ---------- vocabulary -----------------------------------------------------

# Entity NAMES (lowercased) that unambiguously demand a photo/image field.
# Curated conservatively — an internal admin `User` doesn't need a photo by
# default (there's already avatar handling elsewhere), but a public-facing
# `Profile` does.
MEDIA_BEARING_ENTITY_NAMES: frozenset[str] = frozenset({
    # Physical goods (product-like)
    "product", "item", "listing", "sku", "merchandise",
    # Domain: horticulture / agriculture
    "plant", "crop", "flower", "tree", "seed", "seedling",
    # Domain: real estate / hospitality
    "property", "listing", "unit", "room", "suite", "apartment",
    "house", "villa",
    # Domain: automotive
    "vehicle", "car", "truck", "motorcycle", "bike",
    # Domain: food/beverage
    "recipe", "dish", "menu", "menuitem", "menu_item",
    # Domain: content / social
    "post", "article", "profile", "portfolio", "album", "gallery",
    "photo", "picture", "media", "asset", "artwork", "painting",
    # Domain: events / experiences
    "event", "tour", "activity", "class", "workshop",
})

# Vocabulary in the brief that FORCES a media field on ANY product-shaped
# entity (even if the name isn't in the list above).
MEDIA_BRIEF_CUES: frozenset[str] = frozenset({
    "photo", "photos", "photograph", "photographs",
    "image", "images", "picture", "pictures",
    "gallery", "galleries",
    "thumbnail", "thumbnails",
    "media", "cover",
    "upload an image", "upload images", "upload a photo", "upload photos",
    "product images", "product photos",
})

# Field names that already satisfy the media requirement.
_MEDIA_FIELD_NAMES: frozenset[str] = frozenset({
    "image", "imageurl", "image_url",
    "photo", "photourl", "photo_url",
    "picture", "pictureurl", "picture_url",
    "thumbnail", "thumbnailurl", "thumbnail_url",
    "cover", "coverurl", "cover_url",
    "media", "mediaurl", "media_url",
    "avatar", "avatarurl", "avatar_url",
    "logo", "logourl", "logo_url",
})

# Standard photo column added when none exists. Kept as `photoUrl` (varchar-
# shaped) so the runtime FileUpload → forge_files pipeline lands into it as
# a text-shaped file reference — same shape the CV upload uses.
_PHOTO_FIELD = {
    "name": "photoUrl",
    "type": "varchar",
    "not_null": False,
    "semantic_type": "media",  # hint the semantic_field_types resolver → FileUpload control
}


# ---------- helpers --------------------------------------------------------

def _brief_text(plan: dict) -> str:
    parts: list[str] = []
    for key in ("brief", "description", "domain", "name", "prompt", "summary", "goal"):
        v = plan.get(key)
        if isinstance(v, str):
            parts.append(v)
    sb = plan.get("structured_brief") or plan.get("structuredBrief") or {}
    if isinstance(sb, dict):
        for k in ("summary", "description", "elevator_pitch", "goal", "notes"):
            v = sb.get(k)
            if isinstance(v, str):
                parts.append(v)
    return " ".join(parts).lower()


def _entity_has_media_field(entity: dict) -> bool:
    fields = entity.get("fields")
    if not isinstance(fields, list):
        return False
    for f in fields:
        if not isinstance(f, dict):
            continue
        name = str(f.get("name") or "").lower()
        if name in _MEDIA_FIELD_NAMES:
            return True
        # `semantic_type: media/photo/image` is also a satisfier.
        sem = str(f.get("semantic_type") or "").lower()
        if sem in ("media", "photo", "image", "picture"):
            return True
    return False


def _entity_name_wants_media(entity_name: str) -> bool:
    return entity_name.strip().lower() in MEDIA_BEARING_ENTITY_NAMES


def _brief_forces_media(text: str) -> bool:
    if not text:
        return False
    for phrase in MEDIA_BRIEF_CUES:
        if " " in phrase:
            if phrase in text:
                return True
        else:
            if re.search(rf"\b{re.escape(phrase)}\b", text):
                return True
    return False


# ---------- public API -----------------------------------------------------

def entity_needs_media(entity_name: str, entity_spec: dict, *,
                       brief_forces_media: bool = False,
                       is_commerce: bool = False) -> bool:
    """Return True when `entity_name` should carry a photo field but doesn't.

    Trigger conditions (any of):
      1. Entity name matches the media-bearing catalog (Plant, Product, ...).
      2. Entity is commerce=True (product on a storefront).
      3. The brief explicitly asks for photos/images/gallery/media on the app.

    In all cases, no injection happens if a media-shaped field already exists.
    """
    if not isinstance(entity_spec, dict):
        return False
    if _entity_has_media_field(entity_spec):
        return False
    if _entity_name_wants_media(entity_name):
        return True
    if is_commerce:
        return True
    if brief_forces_media:
        return True
    return False


def ensure_media_fields(plan: dict) -> dict:
    """Walk every entity and append a `photoUrl` field where required.
    Mutates + returns the same plan for chaining."""
    entities = plan.get("entities")
    if not isinstance(entities, dict) or not entities:
        return plan
    brief_forces = _brief_forces_media(_brief_text(plan))
    for name, spec in entities.items():
        if not isinstance(spec, dict):
            continue
        is_commerce = spec.get("commerce") is True
        if entity_needs_media(name, spec, brief_forces_media=brief_forces,
                              is_commerce=is_commerce):
            fields = spec.setdefault("fields", [])
            if isinstance(fields, list):
                fields.append(dict(_PHOTO_FIELD))
                logger.info("entity_completeness: added photoUrl to %s", name)
    return plan
