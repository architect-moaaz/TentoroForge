"""Marketplace-platform vocabulary — two-sided marketplaces, sellers,
buyers, listings, orders, disputes. Etsy / Upwork / Airbnb-shape apps.

Shape mirrors booking_platform / banking_platform. Reads as "what does
every marketplace app (Etsy, Reverb, Upwork, TaskRabbit, Airbnb, Poshmark)
carry that a code generator would otherwise re-invent every time?"

Design decisions worth naming:

  - **Listings + sellers use card-grid.** Marketplaces are visual —
    photo + title + price + rating is the universal listing card.
    Sellers get their store-card treatment (avatar + storename +
    rating).

  - **Orders use card-list.** Each order is a "your things" record —
    order number + item summary + status + primary action (track /
    review).

  - **Buyers (admin view) use table.** Marketplace admins need to
    bulk-inspect customers — table with signup date, order count, LTV.

  - **Reviews use card-list.** Each review is a card — star rating +
    title + body + author.

  - **Disputes use table.** Ops work — sortable by age, severity, buyer.

  - **Empty-state copy is friendly.** Marketplace tone is retail —
    warm, invitational, keeps the mood lively.
"""
from __future__ import annotations

from services.archetype_vocabulary import (
    ArchetypeVocabulary,
    ComponentPreference,
)


MARKETPLACE_PLATFORM = ArchetypeVocabulary(
    id="marketplace-platform",

    # ── Per-persona primary screens ─────────────────────────────────
    primary_screens_per_persona={
        # Buyer / shopper — discovery + purchase surface.
        "buyer":    ["browse", "my-orders", "favorites", "messages"],
        "shopper":  ["browse", "my-orders", "favorites", "messages"],
        "customer": ["browse", "my-orders", "favorites", "messages"],

        # Seller / vendor — store-management surface.
        "seller":   ["my-listings", "orders", "revenue", "messages"],
        "vendor":   ["my-listings", "orders", "revenue", "messages"],

        # Admin — marketplace ops surface.
        "admin":              ["dashboard", "listings", "orders",
                                "users", "disputes", "reports"],
        "marketplace_admin":  ["dashboard", "listings", "orders",
                                "users", "disputes", "reports"],
    },

    # ── Section splits within screens ───────────────────────────────
    section_recipes={
        # Listings lifecycle (seller + admin view).
        "listings":     ["active", "sold", "draft", "flagged"],
        "my-listings":  ["active", "sold", "draft", "flagged"],

        # Buyer's order queue.
        "my-orders":    ["pending", "shipped", "delivered", "cancelled"],

        # Seller / admin order queue.
        "orders":       ["new", "processing", "shipped", "delivered", "disputed"],

        # Dispute lifecycle.
        "disputes":     ["open", "under-review", "resolved"],
    },

    # ── Shape per entity ─────────────────────────────────────────────
    component_preferences={
        # Listings — visual catalog.
        "listings":     ComponentPreference(shape="card-grid",
                                             primary_field="title"),
        # No entry for "products" — collides with other archetypes; a
        # marketplace app that names its listings entity "products" still
        # falls back to Table which reads acceptable; only add if the
        # planner emits it and we regret the default.

        # Orders — one card per order.
        "orders":       ComponentPreference(shape="card-list",
                                             primary_field="orderNumber"),
        "transactions": ComponentPreference(shape="card-list",
                                             primary_field="orderNumber"),

        # Seller / vendor store directory.
        "sellers":      ComponentPreference(shape="card-grid",
                                             primary_field="storeName"),
        "vendors":      ComponentPreference(shape="card-grid",
                                             primary_field="storeName"),

        # Buyer directory — admin-scoped, table for bulk inspection.
        "buyers":       ComponentPreference(shape="table",
                                             primary_field="fullName",
                                             context="admin"),
        "customers":    ComponentPreference(shape="table",
                                             primary_field="fullName",
                                             context="admin"),

        # Reviews.
        "reviews":      ComponentPreference(shape="card-list",
                                             primary_field="title"),
        "ratings":      ComponentPreference(shape="card-list",
                                             primary_field="title"),

        # Messages.
        "messages":     ComponentPreference(shape="card-list",
                                             primary_field="subject"),

        # Disputes — ops sortable table.
        "disputes":     ComponentPreference(shape="table",
                                             primary_field="orderNumber"),
    },

    # ── Empty states — friendly retail voice ──────────────────────
    signature_states={
        # Buyer view.
        "empty_browse":        "Nothing here right now. Try a different "
                                "category or search.",
        "empty_my_orders":     "You haven't placed any orders yet. Browse "
                                "the catalog to make your first purchase.",
        "empty_favorites":     "No favorites yet. Save items you like for "
                                "later.",
        "empty_messages":      "No messages yet. Conversations with sellers "
                                "will appear here.",
        "empty_pending":       "No pending orders.",
        "empty_shipped":       "Nothing shipped yet.",
        "empty_delivered":     "No delivered orders in this window.",
        "empty_cancelled":     "No cancelled orders.",

        # Seller view.
        "empty_my_listings":   "No listings yet. Create your first listing "
                                "to start selling.",
        "empty_listings":      "No listings in this view.",
        "empty_active":        "No active listings.",
        "empty_sold":          "Nothing sold yet.",
        "empty_draft":         "No draft listings saved.",
        "empty_flagged":       "No flagged listings.",
        "empty_orders":        "No orders yet. Orders land here as buyers "
                                "check out.",
        "empty_new":           "No new orders waiting.",
        "empty_processing":    "No orders processing.",
        "empty_disputed":      "No disputed orders.",
        "empty_revenue":       "No revenue tracked yet.",

        # Admin ops.
        "empty_dashboard":     "No activity yet. Metrics populate as the "
                                "marketplace gets traffic.",
        "empty_users":         "No users provisioned yet.",
        "empty_buyers":        "No buyers on file yet.",
        "empty_customers":     "No customers on file yet.",
        "empty_sellers":       "No sellers on the marketplace yet.",
        "empty_vendors":       "No vendors on the marketplace yet.",
        "empty_disputes":      "No open disputes. Nice.",
        "empty_open":          "Nothing open right now.",
        "empty_under_review":  "Nothing under review.",
        "empty_resolved":      "No resolved disputes in this window.",
        "empty_reports":       "No reports generated yet.",
        "empty_reviews":       "No reviews yet.",
        "empty_ratings":       "No ratings yet.",

        # Generic filtered-out state.
        "no_results":          "No matches for the current filter. Try "
                                "widening your search.",
    },

    # ── Section-split filters ──────────────────────────────────────
    section_filters={
        # Listing lifecycle.
        "active":       {"status": ["active", "live", "available"]},
        "sold":         {"status": ["sold", "out_of_stock"]},
        "draft":        {"status": ["draft"]},
        "flagged":      {"status": ["flagged", "under_review"]},

        # Order lifecycle.
        "pending":      {"status": ["pending", "new"]},
        "processing":   {"status": ["processing", "picking"]},
        "shipped":      {"status": ["shipped", "in_transit"]},
        "delivered":    {"status": ["delivered", "completed"]},
        "cancelled":    {"status": ["cancelled", "voided"]},
        "disputed":     {"status": ["disputed", "chargeback"]},
        "new":          {"status": ["new", "created"]},

        # Dispute lifecycle.
        "open":         {"status": ["open", "new"]},
        "under-review": {"status": ["under_review", "in_review", "investigating"]},
        "resolved":     {"status": ["resolved", "closed"]},
    },

    # ── Status badge variants ──────────────────────────────────────
    status_badges={
        # Listing lifecycle.
        "active":       {"variant": "success", "label": "Active"},
        "sold":         {"variant": "success", "label": "Sold"},
        "draft":        {"variant": "neutral", "label": "Draft"},
        "flagged":      {"variant": "warning", "label": "Flagged"},

        # Order lifecycle.
        "pending":      {"variant": "warning", "label": "Pending"},
        "shipped":      {"variant": "success", "label": "Shipped"},
        "delivered":    {"variant": "success", "label": "Delivered"},
        "cancelled":    {"variant": "neutral", "label": "Cancelled"},
        "disputed":     {"variant": "danger",  "label": "Disputed"},
        "resolved":     {"variant": "success", "label": "Resolved"},
    },

    # A marketplace operator is not running a store, they are running a
    # two-sided flow, so the dashboard is GMV plus the three places that
    # flow jams: orders sellers haven't fulfilled, orders a buyer has
    # contested, and listings moderation has pulled. GMV is a ``sum``
    # over order value — a marketplace's health is the money crossing it,
    # and order COUNT hides the fact that ten small orders replaced one
    # large one. Average order value rides alongside because the two
    # numbers only mean something read together: GMV up with AOV down is
    # a different business than GMV up with AOV flat.
    dashboard_recipe={
        "kpis": [
            {"label": "Gross merchandise value", "entity": "orders",
             "op": "sum", "field": "total"},
            {"label": "Orders to fulfil",  "entity": "orders",
             "op": "count", "filter": {"status": ["pending"]}},
            {"label": "Orders in dispute", "entity": "orders",
             "op": "count", "filter": {"status": ["disputed"]}},
            {"label": "Active listings",   "entity": "listings",
             "op": "count", "filter": {"status": ["active"]}},
            {"label": "Flagged listings",  "entity": "listings",
             "op": "count", "filter": {"status": ["flagged"]}},
            {"label": "Average order value", "entity": "orders",
             "op": "avg", "field": "total"},
        ],
        "sections": [
            # Fulfilment is the promise the marketplace made on the
            # seller's behalf; an unshipped order is the buyer's first
            # reason to leave.
            {"title": "Orders awaiting fulfilment", "entity": "orders",
             "shape": "card-list",
             "filter": {"status": ["pending"]}, "limit": 8},
            # Deliberately unfiltered: this vocabulary's badge set has no
            # dispute-specific open state, and every row on a disputes
            # table is a live case worth an operator's eyes anyway.
            {"title": "Open disputes", "entity": "disputes",
             "shape": "table", "limit": 8},
            {"title": "Listings flagged for review", "entity": "listings",
             "shape": "card-grid",
             "filter": {"status": ["flagged"]}, "limit": 6},
        ],
    },

    # Marketplace screens always carry the OTHER side of the trade. A
    # listing without its seller and an order without its buyer are both
    # unreadable to an operator arbitrating between two parties, so both
    # names ride in the list columns rather than hiding on the record.
    page_recipes={
        "listings": {
            "list_columns": ["title", "seller", "price", "status",
                             "category", "stock"],
            "filter_chips": ["status", "category"],
            "detail_sections": [
                {"label": "Listing", "fields": ["title", "description",
                                                 "category", "condition"]},
                {"label": "Pricing", "fields": ["price", "currency",
                                                 "quantity", "shippingCost"]},
                {"label": "Seller",  "fields": ["seller", "storeName",
                                                 "location", "status"]},
            ],
        },
        "orders": {
            "list_columns": ["orderNumber", "buyer", "seller", "total",
                             "status", "placedAt"],
            "filter_chips": ["status", "seller"],
            "detail_sections": [
                {"label": "Order",       "fields": ["orderNumber", "buyer",
                                                     "placedAt", "status"]},
                {"label": "Items",       "fields": ["listing", "quantity",
                                                     "unitPrice", "total"]},
                {"label": "Fulfilment",  "fields": ["seller", "shippingAddress",
                                                     "trackingNumber",
                                                     "deliveredAt"]},
            ],
        },
        "sellers": {
            # Rating before volume: on a marketplace, trust is the
            # inventory. A high-volume seller with a falling rating is
            # the account ops needs to find first.
            "list_columns": ["storeName", "email", "rating", "listingCount",
                             "totalSales"],
            "filter_chips": ["status"],
            "detail_sections": [
                {"label": "Store",       "fields": ["storeName", "ownerName",
                                                     "description", "location"]},
                {"label": "Performance", "fields": ["rating", "reviewCount",
                                                     "totalSales",
                                                     "fulfilmentRate"]},
                {"label": "Account",     "fields": ["email", "phone",
                                                     "joinedAt",
                                                     "payoutMethod"]},
            ],
        },
        "buyers": {
            "list_columns": ["fullName", "email", "orderCount", "totalSpent",
                             "joinedAt"],
            "filter_chips": ["status"],
            "detail_sections": [
                {"label": "Buyer",    "fields": ["fullName", "email", "phone"]},
                {"label": "Activity", "fields": ["orderCount", "totalSpent",
                                                  "lastOrderAt"]},
                {"label": "Account",  "fields": ["joinedAt", "shippingAddress",
                                                  "status"]},
            ],
        },
        "reviews": {
            "list_columns": ["title", "rating", "listing", "author",
                             "createdAt"],
            "filter_chips": ["rating"],
            "detail_sections": [
                {"label": "Review",  "fields": ["title", "rating", "body"]},
                {"label": "Subject", "fields": ["listing", "seller", "order"]},
                {"label": "Author",  "fields": ["author", "createdAt",
                                                 "verifiedPurchase"]},
            ],
        },
        "disputes": {
            "list_columns": ["orderNumber", "buyer", "seller", "reason",
                             "status", "openedAt"],
            "filter_chips": ["status", "reason"],
            "detail_sections": [
                {"label": "Case",       "fields": ["orderNumber", "reason",
                                                    "description"]},
                {"label": "Parties",    "fields": ["buyer", "seller"]},
                {"label": "Resolution", "fields": ["status", "resolution",
                                                    "refundAmount",
                                                    "resolvedAt"]},
            ],
        },
        "messages": {
            "list_columns": ["subject", "sender", "recipient", "listing",
                             "sentAt"],
            "filter_chips": ["listing"],
            "detail_sections": [
                {"label": "Message",      "fields": ["subject", "body"]},
                {"label": "Participants", "fields": ["sender", "recipient",
                                                      "listing"]},
                {"label": "Timing",       "fields": ["sentAt", "readAt"]},
            ],
        },
    },
)
