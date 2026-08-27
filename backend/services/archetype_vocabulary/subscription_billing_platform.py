"""Subscription-billing-platform vocabulary — Recurly / Chargebee /
Zuora-like recurring billing, dunning, plan management.

Shape mirrors banking_platform / payment_processing_platform. Values
are the conventions every real subscription platform (Recurly,
Chargebee, Zuora, Stripe Billing) commits to that a generator would
otherwise re-invent.

Design decisions worth naming:

  - **Subscriptions stay a table.** Ops teams work them in bulk
    (past-due sweeps, mid-cycle upgrades). A table is right; a card
    grid would waste screen density.

  - **Invoices + usage + dunning use ledger-list.** Numbers-in-a-
    stream reads as a ledger. Right-aligned amount, dense rows, status
    chip on the leading edge.

  - **Plans use card-grid.** Plans are a marketing surface (pricing
    tiers, feature lists) — the "compare plans" moment wants a card
    grid, not a table.

  - **Customer self-serve view uses card-list for payment methods**
    and shows the current plan card + usage ledger under one page.

  - **Empty-state copy is professional-financial**, matching the
    banking sibling. Never chirpy when money is involved.
"""
from __future__ import annotations

from services.archetype_vocabulary import (
    ArchetypeVocabulary,
    ComponentPreference,
)


SUBSCRIPTION_BILLING_PLATFORM = ArchetypeVocabulary(
    id="subscription-billing-platform",

    # ── Per-persona primary screens ─────────────────────────────────
    primary_screens_per_persona={
        # Customer self-serve — my plan, my invoices, my card, my usage.
        "customer":     ["my-subscription", "invoices", "payment-methods", "usage"],
        "subscriber":   ["my-subscription", "invoices", "payment-methods", "usage"],

        # Billing admin — the whole platform.
        "billing_admin":    ["dashboard", "subscriptions", "invoices",
                              "plans", "dunning", "reports"],
        "admin":            ["dashboard", "subscriptions", "invoices",
                              "plans", "dunning", "reports"],

        # Finance — revenue + collections view.
        "finance":      ["revenue", "invoices", "dunning", "reports"],

        # Support — the failure queues they clear.
        "support":          ["failed-payments", "cancellations", "refund-requests"],
        "billing_support":  ["failed-payments", "cancellations", "refund-requests"],
    },

    # ── Section splits within screens ───────────────────────────────
    section_recipes={
        # Subscriptions lifecycle — the five states every subscription
        # platform tracks.
        "subscriptions":    ["active", "trialing", "past-due",
                              "cancelled", "paused"],

        # Invoices lifecycle — the AR ledger's five columns.
        "invoices":         ["draft", "sent", "paid", "overdue", "void"],

        # Dunning lifecycle — the collections funnel.
        "dunning":          ["retry-scheduled", "final-notice", "cancelled"],

        # Plans lifecycle — active catalog + legacy + retired.
        "plans":            ["active", "grandfathered", "archived"],

        # Customer self-serve view splits.
        "my-subscription":  ["current-plan", "usage", "history"],
    },

    # ── Shape per entity ─────────────────────────────────────────────
    component_preferences={
        # Subscriptions — bulk ops table for admins.
        "subscriptions":    ComponentPreference(shape="table",
                                                 primary_field="customerEmail"),

        # Invoices — AR ledger.
        "invoices":         ComponentPreference(shape="ledger-list",
                                                 primary_field="invoiceNumber"),

        # Plans — marketing catalog; card-grid.
        "plans":            ComponentPreference(shape="card-grid",
                                                 primary_field="name"),
        "pricing_plans":    ComponentPreference(shape="card-grid",
                                                 primary_field="name"),

        # Usage records — metered numbers stream.
        "usage":            ComponentPreference(shape="ledger-list",
                                                 primary_field="metric"),
        "usage_records":    ComponentPreference(shape="ledger-list",
                                                 primary_field="metric"),

        # Saved payment methods — customer wallet.
        "payment_methods":  ComponentPreference(shape="card-list",
                                                 primary_field="brandLast4"),

        # Dunning events — collections history stream.
        "dunning_events":   ComponentPreference(shape="ledger-list",
                                                 primary_field="customerEmail"),
        "dunning":          ComponentPreference(shape="ledger-list",
                                                 primary_field="customerEmail"),

        # Customers — admin's people table.
        "customers":        ComponentPreference(shape="table",
                                                 primary_field="email",
                                                 context="admin"),
        "subscribers":      ComponentPreference(shape="table",
                                                 primary_field="email",
                                                 context="admin"),
    },

    # ── Empty states — professional-financial, never chirpy ────────
    signature_states={
        # Admin surface headliners.
        "empty_subscriptions":  "No subscriptions yet. Customers who "
                                 "subscribe will appear here.",
        "empty_invoices":       "No invoices yet. They generate "
                                 "automatically as billing periods close.",
        "empty_dunning":        "No accounts in dunning. Failed payments "
                                 "retry here automatically.",
        "empty_plans":          "No plans yet. Create your first plan so "
                                 "customers can subscribe.",
        "empty_usage":          "No usage recorded yet.",
        "empty_dashboard":      "No activity yet. Revenue metrics will "
                                 "populate here once billing starts.",
        "empty_reports":        "No reports available yet.",
        "empty_revenue":        "No revenue posted yet.",

        # Customer self-serve.
        "empty_my_subscription":    "You don't have an active subscription. "
                                     "Choose a plan to get started.",
        "empty_payment_methods":    "No payment methods on file. Add a card "
                                     "to keep your subscription active.",

        # Support surface.
        "empty_failed_payments":    "No failed payments to work through.",
        "empty_cancellations":      "No recent cancellations.",
        "empty_refund_requests":    "No refund requests open.",

        # Per-section splits.
        "empty_active":         "Nothing active in this view.",
        "empty_trialing":       "No trials in progress.",
        "empty_past_due":       "No past-due accounts. Collections are clean.",
        "empty_cancelled":      "No cancelled accounts in this window.",
        "empty_paused":         "No paused subscriptions.",
        "empty_draft":          "No draft invoices.",
        "empty_sent":           "No sent invoices in this window.",
        "empty_paid":           "No paid invoices in this window.",
        "empty_overdue":        "No overdue invoices. Nice work.",
        "empty_void":           "No voided invoices.",
        "empty_retry_scheduled":    "No retries scheduled.",
        "empty_final_notice":       "No accounts in final-notice.",
        "empty_grandfathered":  "No grandfathered plans on file.",
        "empty_archived":       "Nothing archived.",
        "empty_current_plan":   "No current plan selected.",
        "empty_history":        "No history yet.",

        # Filtered-out state.
        "no_results":           "No matches for the current filter. Try "
                                 "widening your search.",
    },

    # ── Section-split filters ──────────────────────────────────────
    section_filters={
        # Subscriptions lifecycle.
        "active":           {"status": ["active", "in_trial", "current"]},
        "trialing":         {"status": ["trialing", "in_trial", "trial"]},
        "past-due":         {"status": ["past_due", "pastdue", "unpaid"]},
        "cancelled":        {"status": ["cancelled", "canceled", "churned"]},
        "paused":           {"status": ["paused", "on_hold"]},

        # Invoices lifecycle.
        "draft":            {"status": ["draft", "open"]},
        "sent":             {"status": ["sent", "issued", "outstanding"]},
        "paid":             {"status": ["paid", "settled"]},
        "overdue":          {"status": ["overdue", "past_due"]},
        "void":             {"status": ["void", "voided"]},

        # Dunning lifecycle.
        "retry-scheduled":  {"status": ["retry_scheduled", "retrying"]},
        "final-notice":     {"status": ["final_notice", "last_attempt"]},

        # Plans lifecycle.
        "grandfathered":    {"status": ["grandfathered", "legacy"]},
        "archived":         {"status": ["archived", "retired"]},

        # Customer self-serve — visual splits, no lifecycle filter.
        "current-plan":     {},
        "usage":            {},
        "history":          {},
    },

    # ── Status badge variants ──────────────────────────────────────
    status_badges={
        # Subscriptions.
        "active":           {"variant": "success", "label": "Active"},
        "trialing":         {"variant": "warning", "label": "Trialing"},
        "in_trial":         {"variant": "warning", "label": "In trial"},
        "past_due":         {"variant": "danger",  "label": "Past due"},
        "cancelled":        {"variant": "neutral", "label": "Cancelled"},
        "canceled":         {"variant": "neutral", "label": "Cancelled"},
        "churned":          {"variant": "neutral", "label": "Churned"},
        "paused":           {"variant": "warning", "label": "Paused"},
        "on_hold":          {"variant": "warning", "label": "On hold"},

        # Invoices.
        "draft":            {"variant": "neutral", "label": "Draft"},
        "sent":             {"variant": "warning", "label": "Sent"},
        "issued":           {"variant": "warning", "label": "Issued"},
        "paid":             {"variant": "success", "label": "Paid"},
        "settled":          {"variant": "success", "label": "Settled"},
        "overdue":          {"variant": "danger",  "label": "Overdue"},
        "void":             {"variant": "neutral", "label": "Void"},
        "voided":           {"variant": "neutral", "label": "Voided"},

        # Dunning.
        "retry_scheduled":  {"variant": "warning", "label": "Retry scheduled"},
        "retrying":         {"variant": "warning", "label": "Retrying"},
        "final_notice":     {"variant": "danger",  "label": "Final notice"},

        # Plans.
        "grandfathered":    {"variant": "accent",  "label": "Grandfathered"},
        "legacy":           {"variant": "accent",  "label": "Legacy"},
        "archived":         {"variant": "neutral", "label": "Archived"},
    },

    # Recurring revenue is the only number this business is actually
    # run on, so it leads — as a ``sum`` over the recurring amount of
    # ACTIVE subscriptions, which is what MRR means; a count of
    # subscriptions is a vanity figure that moves in the wrong direction
    # when a big account downgrades. After MRR the dashboard reads as
    # the revenue funnel in order: what's paying, what's still in trial
    # and about to decide, what's already failing to collect. Dunning is
    # last but it is the one anybody acts on today — every account in
    # retry is revenue already earned that will churn on its own if the
    # card is never fixed.
    dashboard_recipe={
        "kpis": [
            {"label": "Monthly recurring revenue", "entity": "subscriptions",
             "op": "sum", "field": "amount",
             "filter": {"status": ["active"]}},
            {"label": "Active subscriptions", "entity": "subscriptions",
             "op": "count", "filter": {"status": ["active"]}},
            {"label": "In trial",           "entity": "subscriptions",
             "op": "count", "filter": {"status": ["trialing", "in_trial"]}},
            {"label": "Past due",           "entity": "subscriptions",
             "op": "count", "filter": {"status": ["past_due"]}},
            {"label": "Overdue receivables", "entity": "invoices",
             "op": "sum", "field": "amount",
             "filter": {"status": ["overdue"]}},
            {"label": "Accounts in dunning", "entity": "dunning",
             "op": "count",
             "filter": {"status": ["retry_scheduled", "retrying",
                                    "final_notice"]}},
        ],
        "sections": [
            # Collections first — this is money the business already
            # earned and is on track to lose to an expired card.
            {"title": "Failed renewals in dunning", "entity": "dunning",
             "shape": "ledger-list",
             "filter": {"status": ["retry_scheduled", "final_notice"]},
             "limit": 8},
            {"title": "Overdue invoices", "entity": "invoices",
             "shape": "ledger-list",
             "filter": {"status": ["overdue"]}, "limit": 8},
            # Trials are the other clock in this domain: each row is a
            # conversion decision that happens whether or not anyone
            # reached out first.
            {"title": "Trials in progress", "entity": "subscriptions",
             "shape": "table",
             "filter": {"status": ["trialing", "in_trial"]}, "limit": 8},
        ],
    },

    # Billing screens are read by account, not by record id: the person
    # looking has a customer in mind and wants their plan, their state
    # and their next charge on one line. Hence customerEmail leads the
    # subscriptions list and the period boundary is a list column rather
    # than a detail field — "when does this renew" is the question the
    # screen exists to answer.
    page_recipes={
        "subscriptions": {
            "list_columns": ["customerEmail", "plan", "status", "amount",
                             "currentPeriodEnd", "seats"],
            "filter_chips": ["status", "plan"],
            "detail_sections": [
                {"label": "Subscription", "fields": ["customerEmail", "plan",
                                                      "status", "quantity"]},
                {"label": "Billing",      "fields": ["amount", "currency",
                                                      "billingInterval",
                                                      "nextInvoiceDate"]},
                {"label": "Term",         "fields": ["startedAt",
                                                      "currentPeriodEnd",
                                                      "trialEndsAt",
                                                      "cancelAtPeriodEnd"]},
            ],
        },
        "invoices": {
            "list_columns": ["invoiceNumber", "customerEmail", "amount",
                             "status", "dueDate"],
            "filter_chips": ["status"],
            "detail_sections": [
                {"label": "Invoice", "fields": ["invoiceNumber", "customerEmail",
                                                 "issueDate", "dueDate"]},
                {"label": "Amounts", "fields": ["subtotal", "tax", "amount",
                                                 "amountPaid"]},
                {"label": "Status",  "fields": ["status", "paidAt",
                                                 "paymentMethod"]},
            ],
        },
        "plans": {
            "list_columns": ["name", "price", "billingInterval", "status",
                             "trialDays"],
            "filter_chips": ["status", "billingInterval"],
            "detail_sections": [
                {"label": "Plan",         "fields": ["name", "code",
                                                      "description"]},
                {"label": "Pricing",      "fields": ["price", "currency",
                                                      "billingInterval",
                                                      "setupFee"]},
                {"label": "Availability", "fields": ["status", "trialDays",
                                                      "features"]},
            ],
        },
        "usage": {
            "list_columns": ["metric", "customerEmail", "quantity", "period",
                             "unitPrice"],
            "filter_chips": ["metric"],
            "detail_sections": [
                {"label": "Usage",       "fields": ["metric", "quantity",
                                                     "unit"]},
                {"label": "Attribution", "fields": ["customerEmail",
                                                     "subscription", "period"]},
                {"label": "Rating",      "fields": ["unitPrice", "amount",
                                                     "recordedAt"]},
            ],
        },
        "customers": {
            "list_columns": ["email", "name", "plan", "status",
                             "lifetimeValue"],
            "filter_chips": ["status", "plan"],
            "detail_sections": [
                {"label": "Customer", "fields": ["name", "email", "company"]},
                {"label": "Billing",  "fields": ["plan", "status",
                                                  "paymentMethod",
                                                  "billingAddress"]},
                {"label": "Value",    "fields": ["mrr", "lifetimeValue",
                                                  "customerSince"]},
            ],
        },
        "payment_methods": {
            "list_columns": ["brandLast4", "cardholderName", "expiryDate",
                             "isDefault", "status"],
            "filter_chips": ["status"],
            "detail_sections": [
                {"label": "Method", "fields": ["brandLast4", "brand",
                                                "cardholderName"]},
                {"label": "Expiry", "fields": ["expiryMonth", "expiryYear",
                                                "status"]},
                {"label": "Usage",  "fields": ["isDefault", "addedAt",
                                                "subscription"]},
            ],
        },
        "dunning_events": {
            # Attempt number is the whole story of a dunning row — it
            # tells the agent how close this account is to being cut off.
            "list_columns": ["customerEmail", "invoice", "attemptNumber",
                             "status", "nextRetryAt"],
            "filter_chips": ["status"],
            "detail_sections": [
                {"label": "Attempt",   "fields": ["customerEmail", "invoice",
                                                   "attemptNumber"]},
                {"label": "Outcome",   "fields": ["status", "failureReason",
                                                   "attemptedAt"]},
                {"label": "Next step", "fields": ["nextRetryAt",
                                                   "notificationSent",
                                                   "finalNoticeAt"]},
            ],
        },
    },
)
