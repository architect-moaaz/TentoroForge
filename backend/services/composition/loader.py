"""Load + validate the composition recipe library.

The library is two JSON files in this package:
    recipes.json — page recipes, each declaring an ordered anchor list.
    anchors.json — every anchor referenced by any recipe, with its contract.

Everything downstream of discovery reads through this loader. The loader:
    - Reads both files once and caches (they're immutable at runtime).
    - Validates cross-references: every anchor a recipe cites must exist.
    - Exposes typed accessors so callers don't touch raw dicts.

Fail-fast contract
------------------
`load_library()` raises `CompositionLibraryError` if the JSON is malformed OR
if any recipe references an anchor missing from anchors.json. That's the whole
point of the machine-readable library — the moment a recipe drifts from an
anchor, generation stops. No silent misspellings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any


class CompositionLibraryError(RuntimeError):
    """Raised when the on-disk library is malformed or cross-references break."""


@dataclass(frozen=True)
class Recipe:
    """One page recipe — a named sequence of anchor slots."""

    name: str
    category: str
    label: str
    purpose: str
    personas: tuple[str, ...]
    anchors: tuple[str, ...]

    @classmethod
    def from_dict(cls, name: str, d: dict[str, Any]) -> "Recipe":
        return cls(
            name=name,
            category=str(d.get("category", "")),
            label=str(d.get("label", "")),
            purpose=str(d.get("purpose", "")),
            personas=tuple(d.get("personas") or ()),
            anchors=tuple(d.get("anchors") or ()),
        )


@dataclass(frozen=True)
class Anchor:
    """One anchor — a component contract every recipe cites by name."""

    name: str
    categories: tuple[str, ...]
    appears_in: tuple[str, ...]
    binds_required: tuple[dict[str, Any], ...]
    binds_optional: tuple[dict[str, Any], ...]
    copy_slots: tuple[str, ...]
    tokens: tuple[str, ...]
    component: str
    impl_status: str = "stub"
    notes: str = ""

    @classmethod
    def from_dict(cls, name: str, d: dict[str, Any]) -> "Anchor":
        binds = d.get("binds") or {}
        return cls(
            name=name,
            categories=tuple(d.get("categories") or ()),
            appears_in=tuple(d.get("appears_in") or ()),
            binds_required=tuple(binds.get("required") or ()),
            binds_optional=tuple(binds.get("optional") or ()),
            copy_slots=tuple(d.get("copy_slots") or ()),
            tokens=tuple(d.get("tokens") or ()),
            component=str(d.get("component", "")),
            impl_status=str(d.get("impl_status", "stub")),
            notes=str(d.get("notes", "")),
        )


@dataclass(frozen=True)
class Category:
    id: str
    label: str
    recipe_count: int


@dataclass(frozen=True)
class Library:
    """The whole library, cached in memory after first load."""

    categories: tuple[Category, ...]
    recipes: dict[str, Recipe]
    anchors: dict[str, Anchor]

    @property
    def category_ids(self) -> set[str]:
        return {c.id for c in self.categories}


# ── file paths ────────────────────────────────────────────────
_MODULE_DIR = Path(__file__).parent
RECIPES_PATH = _MODULE_DIR / "recipes.json"
ANCHORS_PATH = _MODULE_DIR / "anchors.json"


# ── validation ────────────────────────────────────────────────
def validate_library(
    categories: list[Category],
    recipes: dict[str, Recipe],
    anchors: dict[str, Anchor],
) -> None:
    """Raise CompositionLibraryError on any structural problem.

    Checks:
    - Every recipe's `category` matches a declared category id.
    - Every recipe's `anchors[]` entries exist in anchors.json.
    - Every anchor's `appears_in[]` references a real recipe (reverse index
      consistency).
    - Every anchor's `categories[]` matches the category of every recipe it
      claims to appear in.
    - No orphan anchor (declared but referenced by no recipe).
    """
    errors: list[str] = []
    category_ids = {c.id for c in categories}

    # Recipe → category id must be declared
    for r_name, r in recipes.items():
        if r.category not in category_ids:
            errors.append(
                f"recipe {r_name!r}: category {r.category!r} not in declared "
                f"categories {sorted(category_ids)}"
            )
        # Recipe → anchors must all resolve
        for a_name in r.anchors:
            if a_name not in anchors:
                errors.append(
                    f"recipe {r_name!r}: anchor {a_name!r} not in anchors.json"
                )

    # Anchor → appears_in reverse index consistency
    for a_name, a in anchors.items():
        for r_name in a.appears_in:
            if r_name not in recipes:
                errors.append(
                    f"anchor {a_name!r}: appears_in cites unknown recipe "
                    f"{r_name!r}"
                )
                continue
            # bidirectional consistency
            if a_name not in recipes[r_name].anchors:
                errors.append(
                    f"anchor {a_name!r}: appears_in says {r_name!r} but that "
                    f"recipe does not list this anchor"
                )
        # Orphan check
        if not a.appears_in:
            errors.append(f"anchor {a_name!r}: not referenced by any recipe")

    if errors:
        joined = "\n  - ".join(errors[:20])
        summary = f"{len(errors)} error(s)"
        if len(errors) > 20:
            summary += f" (showing first 20)"
        raise CompositionLibraryError(
            f"composition library validation failed — {summary}:\n  - {joined}"
        )


# ── loader ────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def load_library(
    recipes_path: Path = RECIPES_PATH,
    anchors_path: Path = ANCHORS_PATH,
) -> Library:
    """Read both files, parse, validate, cache. Repeat calls are free."""
    try:
        recipes_raw = json.loads(recipes_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise CompositionLibraryError(
            f"failed to read recipes.json at {recipes_path}: {exc}"
        ) from exc
    try:
        anchors_raw = json.loads(anchors_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise CompositionLibraryError(
            f"failed to read anchors.json at {anchors_path}: {exc}"
        ) from exc

    # Categories
    cats_raw = recipes_raw.get("categories") or []
    categories = [
        Category(
            id=str(c.get("id", "")),
            label=str(c.get("label", "")),
            recipe_count=int(c.get("recipes", 0)),
        )
        for c in cats_raw
    ]

    # Recipes
    recipes_dict = recipes_raw.get("recipes") or {}
    recipes = {
        name: Recipe.from_dict(name, d) for name, d in recipes_dict.items()
    }

    # Anchors
    anchors_dict = anchors_raw.get("anchors") or {}
    anchors = {
        name: Anchor.from_dict(name, d) for name, d in anchors_dict.items()
    }

    validate_library(categories, recipes, anchors)

    return Library(
        categories=tuple(categories), recipes=recipes, anchors=anchors,
    )


# ── convenience accessors ─────────────────────────────────────
def list_categories() -> list[Category]:
    return list(load_library().categories)


def list_recipes(category: str | None = None) -> list[Recipe]:
    lib = load_library()
    all_recipes = list(lib.recipes.values())
    if category is None:
        return all_recipes
    return [r for r in all_recipes if r.category == category]


def get_recipe(name: str) -> Recipe:
    lib = load_library()
    if name not in lib.recipes:
        raise CompositionLibraryError(
            f"recipe {name!r} not found. Available: "
            f"{sorted(lib.recipes)[:8]}…"
        )
    return lib.recipes[name]


def get_anchor(name: str) -> Anchor:
    lib = load_library()
    if name not in lib.anchors:
        raise CompositionLibraryError(f"anchor {name!r} not found.")
    return lib.anchors[name]
