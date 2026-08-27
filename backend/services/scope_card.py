"""Scope Card — Layer 2 of the contracts-before-generation architecture.

Deterministic derivation from a LockedSpec to the PageManifest that
downstream generators must obey. No LLM in this path — pure rules:

- kind=entity    → list + detail + create + edit pages
- kind=event     → list + detail only (an event cannot be edited or
                   authored by a user; it's produced by the system)
- kind=role      → no pages, no table
- kind=external  → no pages, no table (data lives elsewhere)
- kind=derived   → list page only (aggregated view of other entities)

Auth features (login / register) always become their own pages so the
generator can rely on their existence when authoring flows.

The manifest is persisted to contracts/manifest.json and is the sole
authority for what the app is allowed to contain. Any page the LLM
subsequently authors that is not in the manifest MUST be rejected by
the page-schema-agent's contract validator (Layer 3, Phase 3).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from services.locked_spec import LockedSpec, load_locked_spec

PageKind = Literal["list", "detail", "create", "edit", "custom", "auth"]


@dataclass
class Page:
    path: str
    kind: PageKind
    entity: str | None = None
    feature: str | None = None
    actor: str | None = None


@dataclass
class Manifest:
    pages: list[Page] = field(default_factory=list)
    entities_with_tables: list[str] = field(default_factory=list)
    workflows: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "pages": [asdict(p) for p in self.pages],
            "entities_with_tables": self.entities_with_tables,
            "workflows": self.workflows,
        }


def _slug(name: str) -> str:
    """Route-safe lowercase slug. Retailer → retailer, PriceResult → priceresult."""
    return "".join(ch for ch in name.lower() if ch.isalnum() or ch == "-")


def _pluralize(name: str) -> str:
    """Naive pluralizer for the list-route path. Scan → scans, Category → categories."""
    s = _slug(name)
    if s.endswith("y") and not s.endswith(("ay", "ey", "iy", "oy", "uy")):
        return s[:-1] + "ies"
    if s.endswith(("s", "x", "z", "ch", "sh")):
        return s + "es"
    return s + "s"


def build_manifest(spec: LockedSpec) -> Manifest:
    """Derive the manifest deterministically from a LockedSpec."""
    pages: list[Page] = []
    tables: list[str] = []
    workflows: list[str] = []

    seen_paths: set[str] = set()

    def _add(page: Page) -> None:
        if page.path not in seen_paths:
            seen_paths.add(page.path)
            pages.append(page)

    for entity in spec.entities:
        plural = _pluralize(entity.name)

        if entity.kind in ("role", "external"):
            # No pages, no table.
            continue

        if entity.kind == "derived":
            # Aggregated view: list only.
            _add(Page(path=f"/{plural}", kind="list", entity=entity.name))
            continue

        # entity or event → always list + detail
        _add(Page(path=f"/{plural}", kind="list", entity=entity.name))
        _add(Page(path=f"/{plural}/[id]", kind="detail", entity=entity.name))
        tables.append(entity.name)

        if entity.kind == "entity":
            # Managed entities get create + edit pages.
            _add(Page(path=f"/{plural}/new", kind="create", entity=entity.name))
            _add(Page(path=f"/{plural}/[id]/edit", kind="edit", entity=entity.name))
            workflows.append(f"Create{entity.name}")
            workflows.append(f"Update{entity.name}")
            workflows.append(f"Delete{entity.name}")

    # Auth features → dedicated pages.
    auth_features = [f for f in spec.features if f.verb == "auth"]
    if auth_features:
        _add(Page(path="/login", kind="auth", feature="login"))
        _add(Page(path="/register", kind="auth", feature="register"))

    # Custom feature-driven pages. A verb that doesn't map to a CRUD action
    # AND doesn't already correspond to a list/detail page becomes its own
    # /<verb>-<target> custom page. Examples: scan → /scan, compare-prices →
    # /compare. The exact contents are the page-schema-agent's job; the
    # manifest just declares the route.
    _CRUD_VERBS = {"create", "update", "delete", "view", "auth"}
    for feat in spec.features:
        if feat.verb in _CRUD_VERBS:
            continue
        # Custom action page — path is /<verb> when there's no target, else
        # /<verb>-<target-slug> (avoid colliding with /<plural>).
        if feat.target_entity:
            target_slug = _slug(feat.target_entity)
            plural_slug = _pluralize(feat.target_entity)
            path = f"/{feat.verb}"
            # If /verb collides with an existing plural, disambiguate.
            if path in seen_paths or path == f"/{plural_slug}":
                path = f"/{feat.verb}-{target_slug}"
        else:
            path = f"/{feat.verb}"
        _add(Page(
            path=path,
            kind="custom",
            entity=feat.target_entity,
            feature=feat.name,
            actor=feat.actor,
        ))

    # Dedup workflow list (some entities can share names).
    workflows = list(dict.fromkeys(workflows))

    return Manifest(pages=pages, entities_with_tables=tables, workflows=workflows)


def persist_manifest(manifest: Manifest, output_dir: str | Path) -> Path:
    base = Path(output_dir)
    contracts_dir = base / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    path = contracts_dir / "manifest.json"
    path.write_text(json.dumps(manifest.to_dict(), indent=2), encoding="utf-8")
    return path


def load_manifest(output_dir: str | Path) -> Manifest | None:
    base = Path(output_dir)
    path = base / "contracts" / "manifest.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Manifest(
            pages=[Page(**p) for p in data.get("pages", [])],
            entities_with_tables=list(data.get("entities_with_tables", [])),
            workflows=list(data.get("workflows", [])),
        )
    except Exception:
        return None


def build_and_persist_from_spec(output_dir: str | Path) -> Manifest | None:
    """Convenience: read locked_spec.json, build manifest, persist. Returns
    None if the locked spec hasn't been persisted yet."""
    spec = load_locked_spec(output_dir)
    if spec is None:
        return None
    manifest = build_manifest(spec)
    persist_manifest(manifest, output_dir)
    return manifest
