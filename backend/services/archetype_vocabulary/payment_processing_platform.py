"""Payment-processing-platform vocabulary — Stripe / Adyen / Square-like
payment gateways, chargeback handling, merchant + support tooling.

Shape mirrors banking_platform / crm_platform. Values are the
conventions every real payment platform (Stripe, Adyen, Square,
Braintree) commits to that a generator would otherwise re-invent.

Design decisions worth naming:

  - **Transactions / payments / payouts use ledger-list.** Money that
    moves in a stream reads as a ledger — dense rows, right-aligned
    amount column, status chip on the leading edge. Same signature as
    the banking preset.

  - **Disputes use kanban.** A dispute flows through a pipeline
    (Needs response → Under review → Won / Lost) — kanban makes the
    stage-progression literal. Same reason banking's applications and
    CRM's deals live on a kanban.

  - **Merchants / customers stay a table** — bulk comparison work for
    admins. Context-scoped so an unrelated persona doesn't see them.

  - **Cards / payment methods use card-list** — the wallet's "your
    saved methods" view (brand + last4 + Set default / Remove action).

  - **Empty-state copy is professional-financial.** Payment tooling
    surfaces money — chirpy copy reads as tone-deaf when a merchant
    is checking whether a chargeback landed.
"""
from __future__ import annotations

from services.archetype_vocabulary import (
    ArchetypeVocabulary,
    ComponentPreference,
)


PAYMENT_PROCESSING_PLATFORM = ArchetypeVocabulary(
    id="payment-processing-platform",

    # ── Per-persona primary screens ─────────────────────────────────
    # Merchant surface = "my money": payments in, disputes to respond
    # to, payouts to my bank. Admin surface = the whole platform.
    # Support surface = the queues they work.
    primary_screens_per_persona={
        # Merchant / business owner — retail seller, restaurant, SaaS
        # owner, all lands on the same set.
        "merchant":         ["payments", "customers", "disputes", "payouts"],
        "business_owner":   ["payments", "customers", "disputes", "payouts"],
        "store_owner":      ["payments", "customers", "disputes", "payouts"],

        # Platform admin — payment ops team.
        "payment_admin":    ["dashboard", "transactions", "merchants",
                              "disputes", "settlements", "reports"],
        "admin":            ["dashboard", "transactions", "merchants",
                              "disputes", "settlements", "reports"],

        # Support agent surface — the queues they work.
        "support":          ["dispute-queue", "refund-requests", "chargeback-cases"],
        "payment_support":  ["dispute-queue", "refund-requests", "chargeback-cases"],
        "agent":            ["dispute-queue", "refund-requests", "chargeback-cases"],
    },

    # ── Section splits within screens ───────────────────────────────
    section_recipes={
        # Payments lifecycle — the four states every payment carries.
        "payments":         ["succeeded", "pending", "failed", "refunded"],

        # Disputes flow — needs response first (SLA), then under review,
        # then decisioned.
        "disputes":         ["needs-response", "under-review", "won", "lost"],

        # Payouts lifecycle — in-flight to the merchant's bank.
        "payouts":          ["in-transit", "paid", "failed"],

        # Transactions — admin's wide feed; splits by recency + risk.
        "transactions":     ["today", "this-week", "flagged"],

        # Refund requests lifecycle.
        "refund-requests":  ["pending", "approved", "denied"],
    },

    # ── Shape per entity ─────────────────────────────────────────────
    component_preferences={
        # Payments / transactions / charges — money in a stream. Ledger.
        "payments":         ComponentPreference(shape="ledger-list",
                                                 primary_field="description"),
        "transactions":     ComponentPreference(shape="ledger-list",
                                                 primary_field="description"),
        "charges":          ComponentPreference(shape="ledger-list",
                                                 primary_field="description"),

        # Customers — admin's people directory; table for bulk work.
        "customers":            ComponentPreference(shape="table",
                                                     primary_field="email",
                                                     context="admin"),
        "payment_customers":    ComponentPreference(shape="table",
                                                     primary_field="email",
                                                     context="admin"),

        # Disputes / chargebacks — a stage-progression pipeline.
        "disputes":         ComponentPreference(shape="kanban",
                                                 primary_field="reason"),
        "chargebacks":      ComponentPreference(shape="kanban",
                                                 primary_field="reason"),

        # Payouts / settlements — money moving to the merchant bank.
        "payouts":          ComponentPreference(shape="ledger-list",
                                                 primary_field="amount"),
        "settlements":      ComponentPreference(shape="ledger-list",
                                                 primary_field="amount"),

        # Merchants / sellers — admin's business directory; bulk table.
        "merchants":        ComponentPreference(shape="table",
                                                 primary_field="businessName",
                                                 context="admin"),
        "sellers":          ComponentPreference(shape="table",
                                                 primary_field="businessName",
                                                 context="admin"),

        # Refunds — the money-out ledger.
        "refunds":          ComponentPreference(shape="ledger-list",
                                                 primary_field="description"),

        # Saved payment methods / cards — the "your wallet" view.
        "payment_methods":  ComponentPreference(shape="card-list",
                                                 primary_field="brandLast4"),
        "cards":            ComponentPreference(shape="card-list",
                                                 primary_field="brandLast4"),
    },

    # ── Empty states — professional-financial, never chirpy ────────
    signature_states={
        # Merchant surface headliners.
        "empty_payments":       "No payments yet. Charges will appear here "
                                 "as they process.",
        "empty_disputes":       "No disputes on file. Any chargebacks land "
                                 "here for response.",
        "empty_payouts":        "No payouts yet. Once settlements clear "
                                 "they'll show here.",
        "empty_transactions":   "No transactions in this period yet.",
        "empty_customers":      "No customers on file. They'll appear here "
                                 "as they check out.",
        "empty_merchants":      "No merchants onboarded yet.",
        "empty_settlements":    "No settlements have been finalised yet.",
        "empty_refunds":        "No refunds issued.",
        "empty_refund_requests":    "No refund requests waiting.",
        "empty_dispute_queue":      "The dispute queue is clear.",
        "empty_chargeback_cases":   "No chargeback cases open.",
        "empty_dashboard":      "No activity yet. Metrics will populate "
                                 "here once processing starts.",
        "empty_reports":        "No reports available yet.",

        # Per-section splits — one entry per unique section name.
        "empty_succeeded":      "No successful payments yet.",
        "empty_pending":        "Nothing pending right now.",
        "empty_failed":         "No failed payments — everything is clearing.",
        "empty_refunded":       "No refunded payments in this view.",
        "empty_needs_response": "No disputes need your response. Nice work.",
        "empty_under_review":   "No disputes under review right now.",
        "empty_won":            "No won disputes in this window.",
        "empty_lost":           "No lost disputes in this window.",
        "empty_in_transit":     "No payouts in transit.",
        "empty_paid":           "No paid payouts in this window.",
        "empty_today":          "Nothing today.",
        "empty_this_week":      "Nothing this week yet.",
        "empty_flagged":        "No flagged transactions. All clear.",
        "empty_approved":       "No approved refund requests in this window.",
        "empty_denied":         "No denied refund requests.",

        # Filtered-out state.
        "no_results":           "No matches for the current filter. Try "
                                 "widening your search.",
    },

    # ── Section-split filters ──────────────────────────────────────
    section_filters={
        # Payments lifecycle.
        "succeeded":        {"status": ["succeeded", "paid", "captured"]},
        "pending":          {"status": ["pending", "authorized", "processing"]},
        "failed":           {"status": ["failed", "declined"]},
        "refunded":         {"status": ["refunded", "partially_refunded"]},

        # Disputes lifecycle.
        "needs-response":   {"status": ["needs_response", "warning_needs_response"]},
        "under-review":     {"status": ["under_review", "warning_under_review"]},
        "won":              {"status": ["won", "warning_closed", "resolved_won"]},
        "lost":             {"status": ["lost", "resolved_lost"]},

        # Payouts lifecycle.
        "in-transit":       {"status": ["in_transit", "pending"]},
        "paid":             {"status": ["paid", "completed"]},

        # Transactions windows — no lifecycle filter (date-driven).
        "today":            {},
        "this-week":        {},
        "flagged":          {"status": ["flagged", "review_required"]},

        # Refund request lifecycle.
        "approved":         {"status": ["approved", "issued"]},
        "denied":           {"status": ["denied", "rejected"]},
    },

    # ── Status badge variants ──────────────────────────────────────
    status_badges={
        # Payments lifecycle.
        "succeeded":        {"variant": "success", "label": "Succeeded"},
        "paid":             {"variant": "success", "label": "Paid"},
        "captured":         {"variant": "success", "label": "Captured"},
        "pending":          {"variant": "warning", "label": "Pending"},
        "authorized":       {"variant": "warning", "label": "Authorized"},
        "processing":       {"variant": "warning", "label": "Processing"},
        "failed":           {"variant": "danger",  "label": "Failed"},
        "declined":         {"variant": "danger",  "label": "Declined"},
        "refunded":         {"variant": "neutral", "label": "Refunded"},

        # Disputes / chargebacks.
        "disputed":         {"variant": "danger",  "label": "Disputed"},
        "chargeback":       {"variant": "danger",  "label": "Chargeback"},
        "needs_response":   {"variant": "warning", "label": "Needs response"},
        "under_review":     {"variant": "warning", "label": "Under review"},
        "won":              {"variant": "success", "label": "Won"},
        "lost":             {"variant": "danger",  "label": "Lost"},

        # Payouts.
        "in_transit":       {"variant": "warning", "label": "In transit"},
        "completed":        {"variant": "success", "label": "Completed"},

        # Refund request lifecycle.
        "approved":         {"variant": "success", "label": "Approved"},
        "issued":           {"variant": "success", "label": "Issued"},
        "denied":           {"variant": "danger",  "label": "Denied"},
        "rejected":         {"variant": "danger",  "label": "Rejected"},

        # Fraud / risk.
        "flagged":          {"variant": "danger",  "label": "Flagged"},
        "blocked":          {"variant": "danger",  "label": "Blocked"},
        "review_required":  {"variant": "warning", "label": "Review required"},
    },

    # A payments operator opens the app to answer three questions in
    # this order: how much cleared, how much didn't, and what has a
    # deadline on it. Volume is a ``sum`` over the money column, never a
    # row count — nobody in this business measures a day in payments,
    # they measure it in currency. Failures come second because a rising
    # decline rate is the earliest signal of a broken integration or an
    # issuer block. Disputes come third and are ranked by response
    # obligation, not by amount: an unanswered dispute is auto-lost, so
    # a small one past its deadline outranks a large one that isn't.
    dashboard_recipe={
        "kpis": [
            {"label": "Volume processed",   "entity": "payments",
             "op": "sum", "field": "amount",
             "filter": {"status": ["succeeded", "paid", "captured"]}},
            {"label": "Failed payments",    "entity": "payments",
             "op": "count", "filter": {"status": ["failed", "declined"]}},
            {"label": "Disputes needing a response", "entity": "disputes",
             "op": "count", "filter": {"status": ["needs_response"]}},
            {"label": "Amount at risk",     "entity": "disputes",
             "op": "sum", "field": "amount"},
            {"label": "Payouts in transit", "entity": "payouts",
             "op": "sum", "field": "amount",
             "filter": {"status": ["in_transit"]}},
            {"label": "Refunded",           "entity": "refunds",
             "op": "sum", "field": "amount"},
        ],
        "sections": [
            # Deadline work first — a dispute left unanswered is decided
            # against the merchant by default.
            {"title": "Disputes needing a response", "entity": "disputes",
             "shape": "table",
             "filter": {"status": ["needs_response"]}, "limit": 8},
            {"title": "Failed payments", "entity": "payments",
             "shape": "ledger-list",
             "filter": {"status": ["failed", "declined"]}, "limit": 8},
            # The live money stream — the only block guaranteed to have
            # rows on a healthy day, when the two queues above are empty.
            {"title": "Recent payments", "entity": "payments",
             "shape": "ledger-list", "limit": 10},
        ],
    },

    # Payments records are read amount-first-among-the-facts but
    # identity-first overall: an operator is looking up "the charge from
    # this customer for this thing", so the human-readable descriptor
    # leads and the money sits where the eye lands next. Disputes are
    # the exception — their list carries the deadline column, because
    # the whole job on that screen is triaging by time remaining.
    page_recipes={
        "payments": {
            "list_columns": ["description", "customer", "amount", "status",
                             "paymentMethod"],
            "filter_chips": ["status", "paymentMethod"],
            "detail_sections": [
                {"label": "Payment",    "fields": ["description", "amount",
                                                    "currency", "status"]},
                {"label": "Customer",   "fields": ["customer", "email",
                                                    "paymentMethod", "last4"]},
                {"label": "Processing", "fields": ["processorReference",
                                                    "capturedAt", "fee",
                                                    "netAmount"]},
            ],
        },
        "disputes": {
            # dueBy in the list, not on the record — triage is the screen.
            "list_columns": ["reason", "customer", "amount", "status",
                             "dueBy", "evidenceSubmitted"],
            "filter_chips": ["status", "reason"],
            "detail_sections": [
                {"label": "Dispute",  "fields": ["reason", "amount",
                                                  "currency", "status"]},
                {"label": "Deadline", "fields": ["dueBy", "openedAt", "stage"]},
                {"label": "Evidence", "fields": ["evidenceSubmitted",
                                                  "evidenceDueBy", "outcome"]},
            ],
        },
        "payouts": {
            "list_columns": ["amount", "status", "arrivalDate",
                             "bankAccount", "currency"],
            "filter_chips": ["status"],
            "detail_sections": [
                {"label": "Payout",      "fields": ["amount", "currency",
                                                     "status"]},
                {"label": "Destination", "fields": ["bankAccount", "bankName",
                                                     "last4"]},
                {"label": "Timing",      "fields": ["initiatedAt",
                                                     "arrivalDate", "method"]},
            ],
        },
        "refunds": {
            "list_columns": ["description", "customer", "amount", "status",
                             "reason"],
            "filter_chips": ["status", "reason"],
            "detail_sections": [
                {"label": "Refund",           "fields": ["description", "amount",
                                                          "reason", "status"]},
                {"label": "Original payment", "fields": ["payment", "chargeId",
                                                          "paymentDate"]},
                {"label": "Processing",       "fields": ["initiatedBy",
                                                          "processedAt"]},
            ],
        },
        "merchants": {
            "list_columns": ["businessName", "email", "status", "riskLevel",
                             "payoutSchedule"],
            "filter_chips": ["status", "riskLevel"],
            "detail_sections": [
                {"label": "Business", "fields": ["businessName", "legalName",
                                                  "website", "country"]},
                {"label": "Account",  "fields": ["email", "phone", "status",
                                                  "mcc"]},
                {"label": "Payouts",  "fields": ["payoutSchedule", "bankAccount",
                                                  "currency"]},
            ],
        },
        "customers": {
            # Email leads: in payments the email IS the identity, and
            # it's what support is handed when a customer calls.
            "list_columns": ["email", "name", "totalSpent",
                             "defaultPaymentMethod", "status"],
            "filter_chips": ["status"],
            "detail_sections": [
                {"label": "Customer", "fields": ["name", "email", "phone"]},
                {"label": "Billing",  "fields": ["defaultPaymentMethod",
                                                  "billingAddress", "currency"]},
                {"label": "Activity", "fields": ["totalSpent", "paymentCount",
                                                  "lastPaymentAt"]},
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
                                                "billingPostalCode"]},
            ],
        },
        "settlements": {
            "list_columns": ["amount", "status", "settlementDate",
                             "transactionCount", "currency"],
            "filter_chips": ["status"],
            "detail_sections": [
                {"label": "Settlement", "fields": ["amount", "currency",
                                                    "status"]},
                {"label": "Period",     "fields": ["periodStart", "periodEnd",
                                                    "settlementDate"]},
                {"label": "Breakdown",  "fields": ["grossAmount", "fees",
                                                    "netAmount",
                                                    "transactionCount"]},
            ],
        },
    },
)
