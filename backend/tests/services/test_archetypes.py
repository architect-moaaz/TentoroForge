"""Tests for the archetype library + detector + spec injection.

Focus is on the visual-product-search archetype since that's the one
`nni3wjf6` needed. Detector must fire on the exact prompt that shipped;
must NOT fire on unrelated prompts; and must suppress the ANTI_ENTITIES
that leaked in without it.
"""
from __future__ import annotations

import pytest

from services.archetype_detector import apply_archetype_to_spec, detect_archetype
from services.archetypes import all_archetypes, get_archetype
from services.locked_spec import build_locked_spec


VISUAL_PRODUCT_SEARCH = (
    "Mobile-first app where a user scans a product with their phone camera "
    "or uploads an image. The app identifies the exact or similar-looking "
    "product using AI, then shows price comparison across retailers using "
    "the Firecrawl web-search MCP with tappable links to each seller. "
    "Admin can control the retailer allow-list (enable/disable, priority). "
    "Store scan history per user."
)


# ---------- library registration ------------------------------------------

def test_library_registers_visual_product_search():
    names = [getattr(m, "NAME", None) for m in all_archetypes()]
    assert "visual-product-search" in names


def test_get_archetype_by_name_returns_module():
    mod = get_archetype("visual-product-search")
    assert mod is not None
    assert getattr(mod, "NAME") == "visual-product-search"


def test_get_archetype_unknown_returns_none():
    assert get_archetype("does-not-exist") is None


def test_visual_product_search_declares_required_fields():
    mod = get_archetype("visual-product-search")
    for field in [
        "NAME", "KEYWORDS", "DEFAULT_ACTORS", "DEFAULT_ENTITIES",
        "DEFAULT_FEATURES", "DEFAULT_WORKFLOWS", "DEFAULT_COMPONENTS",
        "ANTI_ENTITIES", "EXTERNALS",
    ]:
        assert hasattr(mod, field), f"visual-product-search missing {field}"


# ---------- detector ------------------------------------------------------

def test_detector_fires_on_visual_product_search_prompt():
    assert detect_archetype(VISUAL_PRODUCT_SEARCH) == "visual-product-search"


def test_detector_returns_none_for_todo():
    assert detect_archetype("A simple todo app for tasks") is None


def test_detector_returns_none_for_hr_prompt():
    # HR would eventually get its own archetype; today it must not misfire
    # on visual-product-search.
    assert detect_archetype(
        "Recruitment tracker for candidates and job applications"
    ) is None


def test_detector_returns_none_for_blank_prompt():
    assert detect_archetype("") is None
    assert detect_archetype("   ") is None


def test_detector_requires_multiple_keywords():
    # A prompt with ONE keyword shouldn't fire — false-positive prevention.
    assert detect_archetype("A photo gallery.") is None


# ---------- spec injection ------------------------------------------------

def test_build_locked_spec_auto_applies_archetype():
    """The visual-product-search prompt should end up with the archetype's
    entities pinned, ANTI_ENTITIES stripped, and Firecrawl in externals."""
    spec = build_locked_spec(VISUAL_PRODUCT_SEARCH)
    names = {e.name for e in spec.entities}
    # Archetype adds Scan/PriceResult/Retailer/MatchedProduct if missing.
    assert "Scan" in names
    assert "PriceResult" in names
    assert "Retailer" in names
    assert "MatchedProduct" in names
    # Firecrawl external is present.
    providers = {x.provider for x in spec.externals}
    assert "Firecrawl" in providers


def test_archetype_kind_wins_over_extractor():
    """Even if the extractor called Scan an entity, the archetype pins
    it as an event (no create/edit pages downstream)."""
    spec = build_locked_spec(VISUAL_PRODUCT_SEARCH)
    scan = next(e for e in spec.entities if e.name == "Scan")
    assert scan.kind == "event"
    price = next(e for e in spec.entities if e.name == "PriceResult")
    assert price.kind == "event"
    retailer = next(e for e in spec.entities if e.name == "Retailer")
    assert retailer.kind == "entity"


def test_anti_entities_are_stripped():
    """Cart/Order/Invoice must not survive even if the extractor would
    have picked them up."""
    spec = build_locked_spec(VISUAL_PRODUCT_SEARCH)
    names = {e.name.lower() for e in spec.entities}
    for anti in ["cart", "order", "invoice", "payment", "visitor"]:
        assert anti not in names


def test_admin_actor_is_seeded_by_archetype():
    """Both user + admin come out of the spec — the archetype declares
    both, even if the extractor missed 'admin' in some prompt variants."""
    spec = build_locked_spec(VISUAL_PRODUCT_SEARCH)
    roles = {a.role for a in spec.actors}
    assert "user" in roles
    assert "admin" in roles


def test_apply_archetype_to_spec_is_idempotent():
    """Calling apply twice must not duplicate actors/entities/features."""
    spec = build_locked_spec(VISUAL_PRODUCT_SEARCH)
    before_actors = len(spec.actors)
    before_entities = len(spec.entities)
    before_features = len(spec.features)
    apply_archetype_to_spec(spec, "visual-product-search")
    assert len(spec.actors) == before_actors
    assert len(spec.entities) == before_entities
    assert len(spec.features) == before_features


def test_apply_archetype_unknown_name_is_noop():
    spec = build_locked_spec("Some unrelated prompt about pandas.")
    before = spec.to_dict()
    apply_archetype_to_spec(spec, "does-not-exist")
    assert spec.to_dict() == before


# ---------- end-to-end manifest check -------------------------------------

def test_visual_product_search_manifest_shape():
    """With the archetype pinned, the manifest is a tight, coherent app."""
    from services.scope_card import build_manifest

    spec = build_locked_spec(VISUAL_PRODUCT_SEARCH)
    manifest = build_manifest(spec)
    paths = {p.path for p in manifest.pages}
    # Every load-bearing page is present.
    for expected in ("/scans", "/scans/[id]", "/retailers", "/retailers/new",
                     "/retailers/[id]", "/retailers/[id]/edit",
                     "/login", "/register"):
        assert expected in paths, f"missing {expected}"
    # No phantom pages from the ANTI list.
    for bad in ("/carts", "/orders", "/invoices", "/customers", "/visitors"):
        assert bad not in paths, f"unwanted {bad} leaked in"
    # Events do NOT get create/edit routes.
    assert "/scans/new" not in paths
    assert "/scans/[id]/edit" not in paths
    assert "/priceresults/new" not in paths
    # Managed entity DOES get CreateRetailer workflow.
    assert "CreateRetailer" in manifest.workflows
    # Event entity does NOT get a CreateScan workflow.
    assert "CreateScan" not in manifest.workflows
