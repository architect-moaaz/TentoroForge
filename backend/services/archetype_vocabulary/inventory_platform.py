"""Inventory-platform vocabulary — SKUs, stock levels, warehouses,
receiving, purchase orders, WMS-style operations.

Shape mirrors booking_platform / banking_platform. Reads as "what does
every WMS / inventory / warehouse app carry that a code generator would
otherwise re-invent every time?"

Design decisions worth naming:

  - **Products + inventory + PO tables.** SKU work IS bulk-compare
    work (columnar, sortable, filterable, editable in place). Card
    grids for skus are wrong — every real WMS commits to a dense
    table for the item master.

  - **Orders use card-list.** An order is a "your things" record —
    the picker's queue, one card per order-number, primary action
    right-aligned.

  - **Warehouses + suppliers use card-grid.** Directories of
    physical places / trading partners; browse by identity.

  - **Stock movements use ledger-list.** Every stock adjustment
    (received, shipped, damaged, transferred) is an append-only
    ledger entry — the WMS audit trail.

  - **Empty-state copy is matter-of-fact utility.** Warehouse ops
    read status while moving; theatre gets in the way.
"""
from __future__ import annotations

from services.archetype_vocabulary import (
    ArchetypeVocabulary,
    ComponentPreference,
)


INVENTORY_PLATFORM = ArchetypeVocabulary(
    id="inventory-platform",

    # ── Per-persona primary screens ─────────────────────────────────
    primary_screens_per_persona={
        # Warehouse worker / picker — task-driven surface.
        "warehouse_worker":  ["orders", "receiving", "putaway", "tasks"],
        "picker":            ["orders", "receiving", "putaway", "tasks"],

        # Warehouse manager — operational overview + inventory control.
        "warehouse_manager": ["dashboard", "inventory", "orders",
                              "purchase-orders", "warehouses"],
        "manager":           ["dashboard", "inventory", "orders",
                              "purchase-orders", "warehouses"],

        # Buyer — supplier + PO management.
        "buyer":             ["purchase-orders", "suppliers", "products", "receiving"],

        # Admin — user provisioning, product catalog, warehouse setup.
        "admin":             ["dashboard", "users", "products", "warehouses", "reports"],
    },

    # ── Section splits within screens ───────────────────────────────
    section_recipes={
        # Inventory stock-state — the WMS traffic light.
        "inventory":        ["in-stock", "low-stock", "out-of-stock"],

        # Order pick+ship lifecycle.
        "orders":           ["new", "picking", "shipped"],

        # PO lifecycle — draft → submitted → received → closed.
        "purchase-orders":  ["draft", "submitted", "received", "closed"],

        # Receiving queue.
        "receiving":        ["expected-today", "arrived", "putaway-pending"],
    },

    # ── Shape per entity ─────────────────────────────────────────────
    component_preferences={
        # SKU / product master — bulk-compare table.
        "products":         ComponentPreference(shape="table",
                                                 primary_field="sku"),
        "skus":             ComponentPreference(shape="table",
                                                 primary_field="sku"),

        # Stock levels — dense table with warehouse + qty columns.
        "inventory":        ComponentPreference(shape="table",
                                                 primary_field="sku"),
        "stock_levels":     ComponentPreference(shape="table",
                                                 primary_field="sku"),
        "stock":            ComponentPreference(shape="table",
                                                 primary_field="sku"),

        # Orders — picker's queue as cards.
        "orders":           ComponentPreference(shape="card-list",
                                                 primary_field="orderNumber"),
        "sales_orders":     ComponentPreference(shape="card-list",
                                                 primary_field="orderNumber"),

        # POs — bulk-compare table.
        "purchase_orders":  ComponentPreference(shape="table",
                                                 primary_field="poNumber"),
        "pos":              ComponentPreference(shape="table",
                                                 primary_field="poNumber"),

        # Physical directories.
        "warehouses":       ComponentPreference(shape="card-grid",
                                                 primary_field="name"),
        "locations":        ComponentPreference(shape="card-grid",
                                                 primary_field="name"),
        "bins":             ComponentPreference(shape="card-grid",
                                                 primary_field="name"),

        # Trading partners.
        "suppliers":        ComponentPreference(shape="card-grid",
                                                 primary_field="name"),
        "vendors":          ComponentPreference(shape="card-grid",
                                                 primary_field="name"),

        # Movements ledger — append-only audit trail.
        "stock_movements":  ComponentPreference(shape="ledger-list",
                                                 primary_field="sku"),
        "inventory_movements": ComponentPreference(shape="ledger-list",
                                                    primary_field="sku"),
        "adjustments":      ComponentPreference(shape="ledger-list",
                                                 primary_field="sku"),
    },

    # ── Empty states — matter-of-fact utility ─────────────────────
    signature_states={
        # Inventory surface.
        "empty_inventory":       "No stock recorded yet. Receive your first "
                                  "PO to populate inventory.",
        "empty_in_stock":        "Nothing in stock in this view.",
        "empty_low_stock":       "No items below reorder point.",
        "empty_out_of_stock":    "No items out of stock — all counts positive.",

        # Orders surface.
        "empty_orders":          "No orders yet. New orders land here for "
                                  "picking as they come in.",
        "empty_new":             "No new orders.",
        "empty_picking":         "Nothing in pick right now.",
        "empty_shipped":         "No shipments in this window.",

        # PO surface.
        "empty_purchase_orders": "No purchase orders yet. Create your first "
                                  "PO to start receiving stock.",
        "empty_draft":           "No drafts saved.",
        "empty_submitted":       "No submitted POs awaiting fulfillment.",
        "empty_received":        "No received POs in this window.",
        "empty_closed":          "No closed POs recorded.",

        # Receiving surface.
        "empty_receiving":       "Nothing expected right now. The dock is clear.",
        "empty_expected_today":  "No arrivals expected today.",
        "empty_arrived":         "Nothing has arrived yet.",
        "empty_putaway_pending": "No items waiting for putaway.",

        # Directories.
        "empty_warehouses":      "No warehouses configured. Add your first "
                                  "site to start tracking stock.",
        "empty_locations":       "No locations mapped yet.",
        "empty_suppliers":       "No suppliers on file. Add your first "
                                  "vendor to create purchase orders.",
        "empty_vendors":         "No vendors on file.",

        # Movements.
        "empty_stock_movements": "No stock movements yet. Every receive, "
                                  "ship, and adjustment lands here.",

        # Products.
        "empty_products":        "No products in the catalog. Add your first "
                                  "SKU to start tracking inventory.",
        "empty_skus":            "No SKUs in the catalog.",

        # Admin operational.
        "empty_dashboard":       "No activity yet. Metrics populate as "
                                  "stock starts moving.",
        "empty_users":           "No users provisioned yet.",
        "empty_tasks":           "No open tasks.",
        "empty_reports":         "No reports generated yet.",

        # Generic filtered-out state.
        "no_results":            "No matches for the current filter. Try "
                                  "widening your search.",
    },

    # ── Section-split filters ──────────────────────────────────────
    section_filters={
        # Stock state — inventory-industry vocabulary.
        "in-stock":         {"status": ["in_stock", "instock", "available", "active"]},
        "low-stock":        {"status": ["low_stock", "lowstock", "reorder"]},
        "out-of-stock":     {"status": ["out_of_stock", "outofstock", "depleted"]},

        # Order lifecycle.
        "new":              {"status": ["new", "created", "pending"]},
        "picking":          {"status": ["picking", "in_pick", "processing"]},
        "shipped":          {"status": ["shipped", "dispatched", "fulfilled"]},

        # PO lifecycle.
        "draft":            {"status": ["draft"]},
        "submitted":        {"status": ["submitted", "open", "issued"]},
        "received":         {"status": ["received", "partial_received"]},
        "closed":           {"status": ["closed", "completed"]},

        # Receiving lifecycle.
        "expected-today":   {"status": ["expected", "scheduled"]},
        "arrived":          {"status": ["arrived", "at_dock"]},
        "putaway-pending":  {"status": ["putaway_pending", "awaiting_putaway"]},
    },

    # ── Status badge variants ──────────────────────────────────────
    status_badges={
        # Stock state.
        "in_stock":         {"variant": "success", "label": "In stock"},
        "low_stock":        {"variant": "warning", "label": "Low stock"},
        "out_of_stock":     {"variant": "danger",  "label": "Out of stock"},
        "backordered":      {"variant": "warning", "label": "Backordered"},
        "discontinued":     {"variant": "neutral", "label": "Discontinued"},

        # Order / receive lifecycle.
        "received":         {"variant": "success", "label": "Received"},
        "shipped":          {"variant": "success", "label": "Shipped"},
        "cancelled":        {"variant": "neutral", "label": "Cancelled"},
        "damaged":          {"variant": "danger",  "label": "Damaged"},

        # PO lifecycle.
        "draft":            {"variant": "neutral", "label": "Draft"},
        "submitted":        {"variant": "warning", "label": "Submitted"},
        "closed":           {"variant": "neutral", "label": "Closed"},
    },

    # What a warehouse actually opens the app to see: what's running out,
    # what's inbound, what moved. Generic dashboards led with "total
    # records"; nobody in this business cares about that number.
    dashboard_recipe={
        "kpis": [
            {"label": "Low stock",      "entity": "products",
             "op": "count", "filter": {"status": "low_stock"}},
            {"label": "Out of stock",   "entity": "products",
             "op": "count", "filter": {"status": "out_of_stock"}},
            {"label": "Open POs",       "entity": "purchase_orders",
             "op": "count", "filter": {"status": "submitted"}},
            {"label": "Inventory value", "entity": "products",
             "op": "sum", "field": "price"},
        ],
        "sections": [
            {"title": "Needs reordering", "entity": "products",
             "shape": "table", "filter": {"status": "low_stock"}, "limit": 8},
            {"title": "Inbound purchase orders", "entity": "purchase_orders",
             "shape": "table", "filter": {"status": "submitted"}, "limit": 6},
            {"title": "Recent stock movements", "entity": "stock_movements",
             "shape": "ledger-list", "limit": 10},
        ],
    },

    # What each screen SHOWS. A warehouse reads left-to-right off the
    # identifier: SKU first, always — it's the only column anyone
    # searches by, and a picker who can't see it has to open the row.
    # Counts sit next to the threshold they're judged against
    # (on-hand beside reorder point) because "is this low?" is a
    # comparison, not a lookup. Timestamps are deliberately absent from
    # every list except the movements ledger, where the time IS the
    # record.
    page_recipes={
        # Item master. Identity → classification → the two numbers that
        # drive reordering.
        "products": {
            "list_columns": ["sku", "name", "category",
                             "quantityOnHand", "reorderPoint", "status"],
            "filter_chips": ["status", "category", "warehouse"],
            "detail_sections": [
                {"label": "Item",   "fields": ["sku", "name", "category",
                                               "description"]},
                {"label": "Stock",  "fields": ["quantityOnHand", "reorderPoint",
                                               "warehouse", "location"]},
                {"label": "Supply", "fields": ["supplier", "leadTimeDays",
                                               "unitCost", "price"]},
            ],
        },

        # Stock-by-location. Same SKU appears once per site, so the
        # warehouse column carries as much weight as the identifier.
        # On-hand / reserved / available is the WMS's own arithmetic —
        # showing only one of the three invites a bad promise.
        "inventory": {
            "list_columns": ["sku", "warehouse", "location",
                             "quantityOnHand", "quantityAvailable", "status"],
            # Lead with what is running out. Sorting stock by "recently
            # updated" answers a question nobody on the floor asked.
            "list_order": {"field": ["quantityAvailable", "qtyAvailable",
                                     "quantityOnHand", "qtyOnHand"],
                           "dir": "asc"},
            "filter_chips": ["warehouse", "status"],
            "detail_sections": [
                {"label": "Item",    "fields": ["sku", "productName"]},
                {"label": "On hand", "fields": ["quantityOnHand",
                                                "quantityReserved",
                                                "quantityAvailable"]},
                {"label": "Where",   "fields": ["warehouse", "location", "bin"]},
            ],
        },

        # Stock-by-location under its other common name. Column
        # candidates cover the qty*/quantity* split between generators.
        "stock_levels": {
            "list_columns": ["sku", "skuCode", "warehouse", "location",
                             "qtyOnHand", "qtyAvailable", "status"],
            "list_order": {"field": ["qtyAvailable", "quantityAvailable",
                                     "qtyOnHand", "quantityOnHand"],
                           "dir": "asc"},
            "filter_chips": ["warehouse", "location", "status"],
            "detail_sections": [
                {"label": "Item",    "fields": ["sku", "skuCode", "productName"]},
                {"label": "On hand", "fields": ["qtyOnHand", "qtyCommitted",
                                                "qtyAvailable"]},
                {"label": "Where",   "fields": ["warehouse", "location", "bin"]},
            ],
        },

        # Picker's queue. Order number is what's printed on the pick
        # sheet, so it leads; the customer is how the floor talks about
        # the order.
        "orders": {
            "list_columns": ["orderNumber", "customerName", "status",
                             "itemCount", "orderDate"],
            "filter_chips": ["status", "warehouse"],
            "detail_sections": [
                {"label": "Order",       "fields": ["orderNumber", "customerName",
                                                    "orderDate", "status"]},
                {"label": "Fulfillment", "fields": ["warehouse", "shippingAddress",
                                                    "carrier", "trackingNumber"]},
                {"label": "Lines",       "fields": ["items", "itemCount",
                                                    "totalAmount"]},
            ],
        },

        # Buyer's list. Expected date is the column a buyer chases —
        # it belongs on the list, not buried in the record.
        "purchase_orders": {
            "list_columns": ["poNumber", "supplier", "status",
                             "expectedDate", "totalAmount"],
            "list_order": {"field": ["expectedDate", "expectedAt",
                                     "expectedDeliveryDate"], "dir": "asc"},
            "filter_chips": ["status", "supplier"],
            "detail_sections": [
                {"label": "Purchase order", "fields": ["poNumber", "supplier",
                                                       "orderDate", "status"]},
                {"label": "Receiving",      "fields": ["expectedDate",
                                                       "receivedDate",
                                                       "warehouse"]},
                {"label": "Cost",           "fields": ["subtotal", "tax",
                                                       "totalAmount", "currency"]},
            ],
        },

        # Sites. A warehouse is a place and a phone number — the
        # address is the record, not a footnote.
        "warehouses": {
            "list_columns": ["name", "code", "city", "manager", "capacity"],
            "filter_chips": ["region", "type"],
            "detail_sections": [
                {"label": "Site",       "fields": ["name", "code", "type"]},
                {"label": "Address",    "fields": ["addressLine1", "city",
                                                   "region", "postalCode",
                                                   "country"]},
                {"label": "Operations", "fields": ["manager", "capacity", "phone"]},
            ],
        },

        # Trading partners. Lead time is the number that decides when a
        # PO has to go out, so it earns a list column over anything else
        # on the terms sheet.
        "suppliers": {
            "list_columns": ["name", "contactName", "email", "phone",
                             "leadTimeDays"],
            "filter_chips": ["country", "status"],
            "detail_sections": [
                {"label": "Supplier", "fields": ["name", "code", "website"]},
                {"label": "Contact",  "fields": ["contactName", "email", "phone"]},
                {"label": "Terms",    "fields": ["paymentTerms", "leadTimeDays",
                                                 "currency", "minimumOrderValue"]},
            ],
        },

        # The audit trail. Reads as "what moved, how much, where from and
        # to" — the four questions asked of any adjustment during a count
        # dispute. Time comes last because you already know roughly when.
        "stock_movements": {
            # The one screen where "what just happened" IS the question.
            "list_order": {"field": ["occurredAt", "movedAt", "createdAt"],
                           "dir": "desc"},
            "list_columns": ["sku", "movementType", "quantity",
                             "warehouse", "reference", "movedAt"],
            "filter_chips": ["movementType", "warehouse"],
            "detail_sections": [
                {"label": "Movement", "fields": ["sku", "movementType",
                                                 "quantity"]},
                {"label": "Location", "fields": ["warehouse", "fromLocation",
                                                 "toLocation"]},
                {"label": "Audit",    "fields": ["reference", "performedBy",
                                                 "movedAt", "notes"]},
            ],
        },
    },
)
