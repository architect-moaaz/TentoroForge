"""Banking-platform vocabulary — retail/commercial banking, credit
unions, fintech, loan origination, treasury, and compliance-heavy
financial-services apps.

Reference implementation matched to the patterns every modern banking
UI carries — the conventions the LLM would otherwise re-invent every
time. Same shape as booking_platform.py; values are what banking is
instead of what wellness is.

Design decisions worth naming:

  - **Accounts + Cards use card-grid, not table.** A customer's own
    accounts and cards are "your things" — icon + nickname + balance
    + primary action, browsed by identity not compared as rows. A
    banker's admin-scoped customer view is where a table earns its
    place (see ``customers`` / ``members`` with context="officer").

  - **Transactions use ledger-list.** Ledger-list is the banking-
    industry signature: right-aligned amount column, running balance
    on the trailing edge, category chip on the leading edge, dense
    but scannable rows. Slice-3 promoted the shape into KNOWN_SHAPES
    + the collection composer, so ``transactions`` binds to it
    directly. Backed by ``lifecycle: "append_only"`` on the entity —
    rows only ever INSERT, never UPDATE/DELETE (the Data Engine 405s
    mutations).

  - **Applications use kanban.** Loan applications flow through a
    pipeline (New → In Review → Decisioned) — kanban makes the flow
    literal. Slice-3 added ``kanban`` to KNOWN_SHAPES so the composer
    branches on it directly. Same reason CRM opportunities live on
    a kanban.

  - **Empty-state copy is warm-but-professional.** Banking readers
    reach for their money at stressed moments (missing paycheck,
    disputed charge, blocked card). Chirpy empty-state copy reads as
    tone-deaf; we lean warm-professional — never chirpy, never cold.

  - **Section filters carry the industry status vocabulary.**
    ``pending/authorized/processing``, ``posted/cleared/settled``,
    ``disputed/chargeback``, ``active/frozen/blocked`` — these are
    the exact words seen on real bank statements. Downstream picks
    the first that matches the entity's harvested enum values.
"""
from __future__ import annotations

from services.archetype_vocabulary import (
    ArchetypeVocabulary,
    ComponentPreference,
)


BANKING_PLATFORM = ArchetypeVocabulary(
    id="banking-platform",

    # ── Per-persona primary screens ─────────────────────────────────
    # Ordered by importance. Case-normalised role aliases included —
    # planners emit "customer" or "client" or "member" depending on
    # whether the source prompt was a retail bank / private bank /
    # credit-union brief; all should get the same set.
    primary_screens_per_persona={
        # Retail customer surface — accounts + transactions + moving
        # money + cards + statements. Universal across every consumer
        # banking product.
        "customer":         ["accounts", "transactions", "transfers",
                              "cards", "statements"],
        "member":           ["accounts", "transactions", "transfers",
                              "cards", "statements"],
        "client":           ["accounts", "transactions", "transfers",
                              "cards", "statements"],

        # Loan / relationship officer surface — application pipeline
        # + the customers they own + operational tasks.
        "officer":          ["applications", "accounts", "customers", "tasks"],
        "banker":           ["applications", "accounts", "customers", "tasks"],
        "loan_officer":     ["applications", "accounts", "customers", "tasks"],

        # Compliance surface — KYC / SAR / audit / regulatory reports.
        # Distinct persona from officer: separate queue, separate law.
        "compliance":           ["kyc-queue", "sar-alerts", "audit-log", "reports"],
        "compliance_officer":   ["kyc-queue", "sar-alerts", "audit-log", "reports"],

        # Admin / manager — the operating dashboard for the whole
        # bank: products (deposit/loan), rates, fees, users, reports.
        "admin":        ["dashboard", "products", "rates", "fees",
                          "users", "reports"],
        "manager":      ["dashboard", "products", "rates", "fees",
                          "users", "reports"],
        "bank_admin":   ["dashboard", "products", "rates", "fees",
                          "users", "reports"],
    },

    # ── Section splits within screens ───────────────────────────────
    # Section names double as filter predicate keys the composer maps
    # to real filter expressions (see ``section_filters`` below).
    section_recipes={
        # Transactions lifecycle: what's about to hit vs what has hit
        # vs what's contested. The three-way split is universal — every
        # bank statement carries these three columns in some form.
        "transactions":         ["pending", "posted", "disputed"],
        "transaction_history":  ["pending", "posted", "disputed"],

        # Statements = time-window peek at the register.
        "statements":       ["current-month", "past-3-months", "archive"],

        # Cards = wallet view: what works, what's aged out, what's frozen.
        "cards":            ["active", "expired", "blocked"],

        # Applications pipeline: intake → review → decision.
        "applications":         ["new", "in-review", "decisioned"],
        "loan_applications":    ["new", "in-review", "decisioned"],

        # KYC queue lifecycle. The three states any KYC ops team splits by.
        "kyc-queue":        ["pending-review", "awaiting-documents", "escalated"],

        # SAR alerts lifecycle. Open → investigating → closed.
        "sar-alerts":       ["open", "under-investigation", "closed"],

        # Accounts — customer view splits by product class, not lifecycle.
        # A checking + a savings + a closed account all live on the same
        # screen; the split matches the mental model.
        "accounts":         ["primary", "savings", "closed"],
    },

    # ── Shape per entity ─────────────────────────────────────────────
    component_preferences={
        # Accounts — customer's own accounts as card-grid (nickname +
        # balance + primary action). The most-important field is the
        # nickname the customer set ("Vacation Fund"), falling back
        # to the account name when no nickname was set.
        "accounts":         ComponentPreference(shape="card-grid",
                                                 primary_field="nickname"),
        "bank_accounts":    ComponentPreference(shape="card-grid",
                                                 primary_field="nickname"),

        # Transactions — Slice-3 promoted to ledger-list. Right-aligned
        # amount column (MoneyDisplay via format:"currency"), status
        # badge, timestamp, and a companion running-balance dataSource
        # bound to op:"series" agg:"running_sum". Row style: subtle
        # top-border between rows (compact), no per-row card wrapper.
        "transactions":         ComponentPreference(shape="ledger-list",
                                                     primary_field="description"),
        "transaction_history":  ComponentPreference(shape="ledger-list",
                                                     primary_field="description"),

        # Cards — wallet grid. Primary field is the last-4 (the way
        # every customer identifies "which card is this").
        "cards":            ComponentPreference(shape="card-grid",
                                                 primary_field="last4"),

        # Applications — a pipeline. Kanban makes the pipeline literal
        # (New / In Review / Decisioned columns). Slice-3 added ``kanban``
        # to KNOWN_SHAPES so this preference now applies verbatim (the
        # composer branches on it directly rather than falling back to
        # table via the unknown-shape guard).
        "applications":         ComponentPreference(shape="kanban",
                                                     primary_field="applicantName"),
        "loan_applications":    ComponentPreference(shape="kanban",
                                                     primary_field="applicantName"),

        # Customers / members — a table for the banker/officer persona.
        # Context-scoped so the customer persona doesn't ever see a
        # "customers" table (they don't see other customers).
        "customers":    ComponentPreference(shape="table",
                                             context="officer"),
        "members":      ComponentPreference(shape="table",
                                             context="officer"),

        # Beneficiaries / payees — "your saved recipients" is a
        # card-list (icon + name + inline meta + Send/Edit action).
        "beneficiaries":    ComponentPreference(shape="card-list",
                                                 primary_field="name"),
        "payees":           ComponentPreference(shape="card-list",
                                                 primary_field="name"),

        # Products — deposit / loan / card products the bank sells.
        # Card-grid with the product name as the primary field. Admin-
        # facing catalog view.
        "products":         ComponentPreference(shape="card-grid",
                                                 primary_field="name"),
        "bank_products":    ComponentPreference(shape="card-grid",
                                                 primary_field="name"),
    },

    # ── Empty states — warm-but-professional, never chirpy ─────────
    signature_states={
        # Customer surface — the moment they open the app for the first
        # time or after a period of inactivity.
        "empty_accounts":       "No accounts yet. Open your first account "
                                 "to start tracking your money.",
        "empty_transactions":   "No activity here yet. Transactions will "
                                 "appear as soon as they post.",
        "empty_pending":        "Nothing pending. All your activity is "
                                 "up to date.",
        "empty_posted":         "No posted transactions in this period.",
        "empty_disputed":       "No disputes on file.",
        "empty_transfers":      "No transfers yet. Move money between "
                                 "accounts or send to a saved payee.",
        "empty_cards":          "No cards yet. Request your first card "
                                 "to start spending.",
        "empty_active":         "No active cards. Request a new one to "
                                 "get started.",
        "empty_expired":        "No expired cards on record.",
        "empty_blocked":        "No blocked cards. Everything is active.",
        "empty_statements":     "No statements yet. Your first one will "
                                 "post at the end of the cycle.",
        "empty_current_month":  "No activity this month yet.",
        "empty_past_3_months":  "Nothing in the last three months.",
        "empty_archive":        "Nothing archived yet.",
        "empty_beneficiaries":  "No saved payees yet. Add one to send "
                                 "money faster next time.",
        "empty_payees":         "No saved payees yet. Add one to send "
                                 "money faster next time.",

        # Officer / banker surface.
        "empty_applications":   "No open applications. New submissions "
                                 "land here for triage.",
        "empty_new":            "No new applications waiting. Nice work.",
        "empty_in_review":      "Nothing under review right now.",
        "empty_decisioned":     "No decisions in this window.",
        "empty_customers":      "No customers assigned to you yet.",
        "empty_tasks":          "No open tasks. Your queue is clear.",

        # Compliance surface.
        "empty_kyc_queue":              "The queue is clear. New applicants "
                                         "will appear here for review.",
        "empty_pending_review":         "Nothing pending review.",
        "empty_awaiting_documents":     "No cases waiting on documents.",
        "empty_escalated":              "No escalated cases.",
        "empty_sar_alerts":             "No SAR alerts open. All clear.",
        "empty_open":                   "Nothing open right now.",
        "empty_under_investigation":    "No active investigations.",
        "empty_closed":                 "No closed items in this view.",
        "empty_audit_log":              "No audit events logged for this "
                                         "period yet.",
        "empty_reports":                "No reports generated yet.",

        # Admin operational.
        "empty_dashboard":      "No activity yet. Metrics will appear "
                                 "here once the bank starts processing.",
        "empty_products":       "No products configured. Add your first "
                                 "product to start accepting applications.",
        "empty_primary":        "No primary account on file.",
        "empty_savings":        "No savings accounts yet.",
        "empty_rates":          "No rates published yet.",
        "empty_fees":           "No fees configured.",
        "empty_users":          "No users provisioned yet.",

        # Generic filtered-out state — separate from empty-collection
        # so the copy can suggest widening the filter rather than
        # nudging the reader to seed data.
        "no_results":           "No matches for the current filter. Try "
                                 "widening your search.",
    },

    # ── Section-split filters ──────────────────────────────────────
    # One filter per named section in `section_recipes`. Values are
    # ordered preference lists — the section-split resolver picks the
    # first value that appears in the entity's declared enum, drops
    # the filter entirely when none match. Purely additive: sections
    # like `current-month` / `archive` that carry no lifecycle filter
    # stay as visual splits with no server-side filter.
    section_filters={
        # Transactions lifecycle.
        "pending":              {"status": ["pending", "authorized", "processing"]},
        "posted":               {"status": ["posted", "cleared", "settled"]},
        "disputed":             {"status": ["disputed", "chargeback"]},

        # SAR / general lifecycle.
        "open":                 {"status": ["open", "new"]},
        "under-investigation":  {"status": ["under_investigation", "in_review"]},
        "closed":               {"status": ["closed", "resolved", "dismissed"]},

        # Cards lifecycle.
        "active":               {"status": ["active", "issued"]},
        "expired":              {"status": ["expired"]},
        "blocked":               {"status": ["blocked", "frozen", "locked"]},

        # Applications pipeline.
        "new":                  {"status": ["new", "submitted"]},
        "in-review":            {"status": ["in_review", "under_review", "processing"]},
        "decisioned":           {"status": ["approved", "declined", "rejected"]},

        # KYC queue lifecycle.
        "pending-review":       {"status": ["pending_review", "pending", "queued"]},
        "awaiting-documents":   {"status": ["awaiting_documents", "docs_needed"]},
        "escalated":            {"status": ["escalated", "flagged"]},

        # No lifecycle filter — visual split only. A follow-on slice can
        # add real date-range filtering once the runtime supports it.
        "current-month":    {},
        "past-3-months":    {},
        "archive":          {},
        # Accounts split by product class → no shared status filter here;
        # the composer maps section→dataSource per-account-type upstream.
        "primary":          {},
        "savings":          {},
    },

    # ── Status badge variants ──────────────────────────────────────
    # Industry-standard label + variant per status value. Union of
    # every value declared in section_filters plus the extra ones
    # every real bank statement surfaces.
    status_badges={
        # Transaction lifecycle.
        "pending":          {"variant": "warning", "label": "Pending"},
        "authorized":       {"variant": "warning", "label": "Authorized"},
        "processing":       {"variant": "warning", "label": "Processing"},
        "posted":           {"variant": "success", "label": "Posted"},
        "cleared":          {"variant": "success", "label": "Cleared"},
        "settled":          {"variant": "success", "label": "Settled"},
        "disputed":         {"variant": "danger",  "label": "Disputed"},
        "chargeback":       {"variant": "danger",  "label": "Chargeback"},
        "reversed":         {"variant": "neutral", "label": "Reversed"},

        # Cards lifecycle.
        "active":           {"variant": "success", "label": "Active"},
        "issued":           {"variant": "success", "label": "Issued"},
        "expired":          {"variant": "neutral", "label": "Expired"},
        "blocked":          {"variant": "danger",  "label": "Blocked"},
        "frozen":           {"variant": "danger",  "label": "Frozen"},
        "locked":           {"variant": "danger",  "label": "Locked"},

        # Applications pipeline outcomes.
        "new":              {"variant": "neutral", "label": "New"},
        "submitted":        {"variant": "neutral", "label": "Submitted"},
        "in_review":        {"variant": "warning", "label": "In review"},
        "under_review":     {"variant": "warning", "label": "Under review"},
        "approved":         {"variant": "success", "label": "Approved"},
        "declined":         {"variant": "danger",  "label": "Declined"},
        "rejected":         {"variant": "danger",  "label": "Rejected"},

        # Alerts / SAR lifecycle.
        "open":                 {"variant": "warning", "label": "Open"},
        "under_investigation":  {"variant": "warning", "label": "Under investigation"},
        "closed":               {"variant": "neutral", "label": "Closed"},
        "resolved":             {"variant": "success", "label": "Resolved"},
        "dismissed":            {"variant": "neutral", "label": "Dismissed"},

        # KYC lifecycle.
        "pending_review":       {"variant": "warning", "label": "Pending review"},
        "queued":               {"variant": "warning", "label": "Queued"},
        "awaiting_documents":   {"variant": "warning", "label": "Awaiting documents"},
        "docs_needed":          {"variant": "warning", "label": "Docs needed"},
        "escalated":            {"variant": "danger",  "label": "Escalated"},
        "flagged":              {"variant": "danger",  "label": "Flagged"},
    },

    # A bank's landing page is a money page, not a records page. The
    # first number is the balance under management — the one figure a
    # branch or ops lead is accountable for — and everything after it is
    # something that will cost the bank if nobody touches it today: money
    # not yet cleared, charges a customer is contesting (regulated
    # response clocks), applications sitting undecided, cards someone
    # locked out of. Generic dashboards led with "total customers"; that
    # number never once changed what a banker did next.
    dashboard_recipe={
        "kpis": [
            {"label": "Deposits under management", "entity": "accounts",
             "op": "sum", "field": "balance"},
            {"label": "Pending settlement",     "entity": "transactions",
             "op": "sum", "field": "amount",
             "filter": {"status": ["pending", "authorized", "processing"]}},
            {"label": "Open disputes",          "entity": "transactions",
             "op": "count", "filter": {"status": ["disputed", "chargeback"]}},
            {"label": "Applications in review", "entity": "applications",
             "op": "count", "filter": {"status": ["in_review", "under_review"]}},
            {"label": "New applications",       "entity": "applications",
             "op": "count", "filter": {"status": ["new", "submitted"]}},
            {"label": "Blocked cards",          "entity": "cards",
             "op": "count", "filter": {"status": ["blocked", "frozen", "locked"]}},
        ],
        "sections": [
            # Disputes first: they carry a regulatory response deadline,
            # so they are the one list where "I didn't get to it" is a
            # compliance event rather than a backlog.
            {"title": "Disputes needing a response", "entity": "transactions",
             "shape": "ledger-list",
             "filter": {"status": ["disputed", "chargeback"]}, "limit": 8},
            {"title": "Applications awaiting a decision", "entity": "applications",
             "shape": "table",
             "filter": {"status": ["in_review", "under_review"]}, "limit": 8},
            # The always-populated tail — on a quiet day the two lists
            # above are empty (which is the good outcome), and a landing
            # page that renders nothing at all reads as broken.
            {"title": "Recent activity", "entity": "transactions",
             "shape": "ledger-list", "limit": 10},
        ],
    },

    # What each screen SHOWS. Banking reading order is near-universal
    # and it is never the database's order: a transaction is read as
    # "what was it / who was it with / how much", with the timestamp
    # trailing, because the reader is scanning for a charge they already
    # remember. Detail groups follow the same logic — the sections are
    # the ones printed on a real statement or application packet, not
    # a flat dump of every column.
    page_recipes={
        "accounts": {
            "list_columns": ["accountNumber", "nickname", "accountType",
                             "balance", "status"],
            "filter_chips": ["accountType", "status"],
            "detail_sections": [
                {"label": "Account",   "fields": ["accountNumber", "nickname",
                                                   "accountType", "openedDate"]},
                {"label": "Balances",  "fields": ["balance", "availableBalance",
                                                   "currency", "interestRate"]},
                {"label": "Ownership", "fields": ["customer", "branch", "status"]},
            ],
        },
        "transactions": {
            # Amount before status: the reader is reconciling a number,
            # and the badge is the qualifier on it, not the headline.
            "list_columns": ["description", "merchant", "category",
                             "amount", "status", "postedAt"],
            "filter_chips": ["status", "category"],
            "detail_sections": [
                {"label": "Transaction", "fields": ["description", "merchant",
                                                     "category", "amount"]},
                {"label": "Posting",     "fields": ["status", "postedAt",
                                                     "transactionDate",
                                                     "referenceNumber"]},
                {"label": "Account",     "fields": ["account", "balanceAfter",
                                                     "type"]},
            ],
        },
        "cards": {
            # Last-4 leads because that is how every customer and every
            # support agent identifies a card out loud.
            "list_columns": ["last4", "cardholderName", "cardType",
                             "status", "expiryDate"],
            "filter_chips": ["status", "cardType"],
            "detail_sections": [
                {"label": "Card",   "fields": ["last4", "cardType", "network",
                                                "cardholderName"]},
                {"label": "Status", "fields": ["status", "issuedDate",
                                                "expiryDate"]},
                {"label": "Limits", "fields": ["dailyLimit", "creditLimit",
                                                "account"]},
            ],
        },
        "applications": {
            "list_columns": ["applicantName", "productType", "amount",
                             "status", "submittedAt"],
            "filter_chips": ["status", "productType"],
            "detail_sections": [
                {"label": "Applicant", "fields": ["applicantName", "email",
                                                   "phone", "employmentStatus"]},
                {"label": "Request",   "fields": ["productType", "amount",
                                                   "termMonths", "purpose"]},
                {"label": "Decision",  "fields": ["status", "creditScore",
                                                   "decisionedBy", "decisionDate"]},
            ],
        },
        "customers": {
            # KYC + risk sit in the list, not buried on the record — an
            # officer needs to see who is out of review before opening
            # anything.
            "list_columns": ["fullName", "email", "phone", "kycStatus",
                             "riskRating"],
            "filter_chips": ["kycStatus", "riskRating"],
            "detail_sections": [
                {"label": "Identity",     "fields": ["fullName", "dateOfBirth",
                                                      "email", "phone"]},
                {"label": "Compliance",   "fields": ["kycStatus", "riskRating",
                                                      "lastReviewDate"]},
                {"label": "Relationship", "fields": ["relationshipManager",
                                                      "customerSince", "segment"]},
            ],
        },
        "beneficiaries": {
            "list_columns": ["name", "accountNumber", "bankName", "relationship"],
            "filter_chips": ["bankName"],
            "detail_sections": [
                {"label": "Payee",   "fields": ["name", "nickname", "relationship"]},
                {"label": "Account", "fields": ["accountNumber", "routingNumber",
                                                 "bankName", "swiftCode"]},
            ],
        },
        "products": {
            "list_columns": ["name", "productType", "interestRate",
                             "minimumBalance", "status"],
            "filter_chips": ["productType", "status"],
            "detail_sections": [
                {"label": "Product", "fields": ["name", "productType",
                                                 "description"]},
                {"label": "Terms",   "fields": ["interestRate", "minimumBalance",
                                                 "termMonths"]},
                {"label": "Fees",    "fields": ["monthlyFee", "overdraftFee",
                                                 "status"]},
            ],
        },
    },
)
