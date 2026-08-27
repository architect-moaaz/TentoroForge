"""Visual-Product-Search archetype.

The scan-and-compare app: a user snaps a photo (or uploads an image), the
app identifies the product via vision-capable AI, then fans out to a set
of admin-approved retailers via Firecrawl MCP to compare live prices.
Admin manages the retailer allow-list. Scan history is per-user.

This archetype is the reason the whole archetype library exists — every
platform bug we discovered in nni3wjf6 traces back to the pipeline
having no idea it was building this specific shape of app. With the
archetype pinned, the whole downstream pipeline knows:

- there are exactly 3 event entities (Scan, MatchedProduct, PriceResult)
  and 1 managed entity (Retailer)
- no Cart/Order/Invoice tables get injected (ANTI_ENTITIES)
- Firecrawl MCP is expected (EXTERNALS)
- the scan-product workflow needs a Camera + FileUpload + confidence
  gate + per-retailer price fetch loop
"""
from __future__ import annotations

NAME = "visual-product-search"

# Detector scores prompt by keyword-overlap. Two or more distinct
# keywords ⇒ archetype fires. Kept intentionally domain-specific — no
# stopwords like "user" or "app".
KEYWORDS = [
    "scan",
    "scans",
    "scanning",
    "camera",
    "photo",
    "image",
    "identify",
    "identifies",
    "product",
    "products",
    "price comparison",
    "compare price",
    "compare prices",
    "retailer",
    "retailers",
    "seller",
    "sellers",
    "shopping search",
    "visual product",
    "visual search",
    "allow-list",
    "allowlist",
    "firecrawl",
]

# Two personas: end-user (scanning) + admin (curating the retailer list).
DEFAULT_ACTORS = [
    {"role": "user", "permissions_hint": ["scan", "view_own_history"]},
    {"role": "admin", "permissions_hint": ["manage_retailers"]},
]

# All entities except Retailer are events — records produced by the
# workflow, never authored by a user. That means: list + detail only,
# no /new or /[id]/edit pages, no CreateX workflows.
DEFAULT_ENTITIES = [
    {"name": "Scan", "kind": "event", "cardinality": "many"},
    {"name": "MatchedProduct", "kind": "event", "cardinality": "many"},
    {"name": "PriceResult", "kind": "event", "cardinality": "many"},
    {"name": "Retailer", "kind": "entity", "cardinality": "many"},
]

# Feature verbs that translate to workflow calls or custom pages.
# scan/upload/compare become custom pages (/scan, /compare). view is
# CRUD. manage is admin-only CRUD on Retailer. auth is implicit
# because "per user" is in the prompt template.
DEFAULT_FEATURES = [
    {"name": "scan-product", "actor": "user", "verb": "scan", "target_entity": "Scan"},
    {"name": "upload-scan", "actor": "user", "verb": "upload", "target_entity": "Scan"},
    {"name": "view-history", "actor": "user", "verb": "view", "target_entity": "Scan"},
    {"name": "view-comparison", "actor": "user", "verb": "compare", "target_entity": "PriceResult"},
    {"name": "manage-retailers", "actor": "admin", "verb": "manage", "target_entity": "Retailer"},
    {"name": "login", "actor": "user", "verb": "auth", "target_entity": None},
    {"name": "register", "actor": "user", "verb": "auth", "target_entity": None},
]

# The one workflow that owns the whole scan → identify → compare fan-out.
# CreateRetailer / UpdateRetailer / DeleteRetailer come from the manifest
# derivation automatically because Retailer is a managed entity.
DEFAULT_WORKFLOWS = ["ScanProductWorkflow"]

# Component types the planner is biased to reach for. Camera & FileUpload
# for the scan page; ProductCard for the identified product summary;
# Table for the retailer allow-list; Card + Badge for the comparison view.
DEFAULT_COMPONENTS = [
    "Camera",
    "FileUpload",
    "ProductCard",
    "Card",
    "Badge",
    "Table",
    "Stat",
    "Link",
    "Button",
    "Heading",
    "Text",
    "Repeat",
]

# Explicit block-list. `product` in the prompt is NOT a signal to add
# a shopping cart — this is comparison, not commerce. Same for order/
# invoice/payment: they belong in a checkout archetype we don't have
# and shouldn't get spuriously created here.
ANTI_ENTITIES = [
    # Commerce entities the pipeline sometimes injects on "product" keyword.
    "Cart",
    "CartItem",
    "Order",
    "OrderItem",
    "Invoice",
    "InvoiceLine",
    "Payment",
    # Roles that shouldn't be entities.
    "Customer",
    "Visitor",
    "Admin",
    # Freeform extractor false positives — "Product" appears in the prompt
    # but MatchedProduct is the real (event) entity. "History" is what the
    # /scans list IS — no separate history table needed.
    "Product",
    "History",
    # Ambiguous verb-nouns that would otherwise show up as entities.
    "Record",
]

# Firecrawl MCP is required. The recipe uses firecrawl_search to find
# candidate URLs then firecrawl_extract on each product page (see O7
# in the pipeline remediation plan).
EXTERNALS = [
    {"type": "mcp", "provider": "Firecrawl"},
]

# Human-facing summary the scope-card UI can display when this archetype
# is detected, so the user knows what the pipeline is about to build.
SUMMARY = (
    "A visual product search app. Users scan or upload a product image, "
    "the app identifies it with AI, then compares live prices across "
    "admin-approved retailers via Firecrawl. Ships with 4 entities, "
    "1 workflow, and ~10 pages. No cart or checkout — this is a "
    "comparison app, not commerce."
)

# STATEFUL SINGLE-PAGE — scan workflows are short-running (seconds, not
# hours) and the user expects to stay on the page while it works and see
# results appear inline. Planner/Smith should emit a stateful single-page
# schema for the scan route (Conditional branching on scan.status, with a
# top-level `poll` block driving auto-refresh) instead of a page-per-state
# split. See docs/superpowers/patterns/stateful-single-page.md for the
# canonical shape + example.
PREFERS_STATEFUL_SINGLE_PAGE = True
STATEFUL_PAGES = [
    {
        "route": "/scan",
        "polls_entity": "Scan",
        "status_field": "status",
        "terminal_states": ["completed", "failed"],
        "example_schema": "backend/services/schema_examples/stateful_scan_page.json",
    },
]

# Pages the archetype REQUIRES on the plan. The planner sometimes forgets
# the primary entry point (repeatedly emits list/detail/history but no /scan)
# — deterministic post-plan injection guarantees the app has a scan route.
# Consumed by `services.archetype_workflows.ensure_required_pages`.
#
# Each entry is a partial plan.pages dict; the injector unions it with the
# existing pages, keyed by route (an existing page at the same route wins,
# so the planner can specialize the shape without losing the entry point).
REQUIRED_PAGES = [
    {
        "route": "/scan",
        "name": "Scan Product",
        "type": "visual_scan",
        "page_type": "visual_scan",
        "archetype": "visual_scan",
        "entity": "ScanEvent",
        "description": (
            "Primary entry point: user captures/uploads a product image, "
            "workflow identifies it, and results (matched product + retailer "
            "prices) render inline via the stateful single-page pattern."
        ),
        # SUBMIT-AUTHORITY declaration (SLICE-A T4/T5). The /scan Form's
        # dispatch target is ScanProductWorkflow; declaring it here makes
        # the plan-level submit contract explicit so form_scaffold /
        # action_authority / any post-generate passes that read
        # plan.pages[].submit see a consistent target — the same target
        # the deterministic /scan schema emitter (archetype_page_fixes)
        # writes onto Form.props.workflow. VPS-M: without this, the
        # scan submit was left orphan-shaped from the plan's POV and
        # only orphan_wiring_pass caught it — and that pass historically
        # skipped api_event workflows entirely.
        "submit": {
            "kind": "workflow",
            "target": "ScanProductWorkflow",
        },
    },
]

# Workflows the archetype REQUIRES on the plan. Same contract as
# REQUIRED_PAGES: partial plan.workflows dicts, unioned by fuzzy name so a
# planner-authored "Scan Barcode Workflow" counts as present. Steps stay
# empty on injected entries — the deterministic emitter in
# services.archetype_workflows authors the full node graph, keyed on the
# name (see the barcode aliases there). Ported from the live-proven
# LensShop reference app (output/dxlc5m31, 2026-08-19).
REQUIRED_WORKFLOWS = [
    {
        "name": "BarcodeSearchWorkflow",
        "trigger": "manual",
        "trigger_inputs": [{"name": "barcode", "type": "string"}],
        "description": (
            "Scan a product barcode (camera or image) → match the catalog "
            "by UPC/EAN or identify the product via web search → scrape "
            "live retailer offers with prices and images."
        ),
        "steps": [],
    },
]

# Columns the archetype REQUIRES on specific entities so the deterministic
# workflows have real columns to bind. Unioned into plan.data_models by
# `services.archetypes.ensure_required_columns` (fuzzy entity-name match,
# existing fields win).
REQUIRED_ENTITY_COLUMNS = [
    {
        "entity_candidates": ["Product", "MatchedProduct", "products"],
        "fields": [
            {"name": "upc", "type": "string", "nullable": True,
             "description": "UPC-A barcode digits (12)."},
            {"name": "ean", "type": "string", "nullable": True,
             "description": "EAN-13 barcode digits (13; '0'+UPC for 0-prefixed)."},
            {"name": "imageUrl", "type": "string", "nullable": True},
        ],
    },
    {
        "entity_candidates": ["Scan", "ScanSession", "scan_sessions"],
        "fields": [
            {"name": "imageUrl", "type": "string", "nullable": True},
        ],
    },
    {
        "entity_candidates": ["PriceResult", "PriceListing", "price_results"],
        "fields": [
            {"name": "imageUrl", "type": "string", "nullable": True},
            {"name": "retailerName", "type": "string", "nullable": True},
            {"name": "productUrl", "type": "string", "nullable": True},
        ],
    },
]
