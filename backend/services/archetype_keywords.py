"""One catalog of archetype keywords — the only place an archetype is named.

Adding a domain vocabulary used to mean editing four places. Two of them
were keyword tables that looked interchangeable and were not:

  - ``plan_directive_parser`` matched multi-word PHRASES against the raw
    user prompt, first hit wins.
  - ``product_brief`` matched single TOKENS against a haystack built from
    entity names plus description, needing two hits to fire.

Both were called ``_ARCHETYPE_KEYWORDS``, and ``vocab_ranker`` imported
the second under a comment claiming there was only one. When the
legislative vocabulary was added to the first table and not the second,
the detector recognised the domain, the vocabulary loaded on demand, and
the ranker — which is what actually assembles the candidate pool — could
not see it. `legislative-platform` was registered, tested, and
unreachable. Nothing failed; a Palestinian Legislative Council app was
matched to `analytics-dashboard-platform`, whose recipe names
`report_runs` and `datasets`, so every KPI it offered was dropped on
entity mismatch and the dashboard fell back to a generic bootstrap.

So the two keyword styles stay — they read different inputs and a single
merged blob would match badly on both — but they now live side by side in
one entry per archetype. Miss one and the entry is visibly half-written
rather than silently absent, and ``test_archetype_keywords`` fails when
the catalog and the vocabulary registry disagree.

Order is significant and load-bearing; the per-entry comments record why.
Both derived views preserve it.

Pure data. No I/O, no imports from the services that consume it — the
consumers import this, never the reverse.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArchetypeKeywords:
    """Everything needed to recognise one archetype, in one place.

    ``vocab_id`` is the canonical registry id (always ``*-platform``) —
    the same string ``services.archetype_vocabulary.load_vocabulary``
    is keyed on. Callers that used to pass a short slug get the full id
    now, which removes the slug/id bridge that hid this bug.

    ``prompt_phrases`` are multi-word and deliberately specific: they run
    against the user's own sentence, where one hit is enough to be
    intentional. ``plan_tokens`` are single words run against entity
    names and description prose, where two hits are required because any
    one of them can appear by accident.
    """

    vocab_id: str
    prompt_phrases: tuple[str, ...]
    plan_tokens: tuple[str, ...]


# Order = precedence. A more specific archetype must precede the generic
# one it would otherwise lose to.
ARCHETYPES: tuple[ArchetypeKeywords, ...] = (
    # Booking / scheduling — yoga studios, salons, courts, appointments.
    ArchetypeKeywords(
        "booking-platform",
        ("booking", "reservation", "appointment scheduler", "class booking"),
        ("booking", "reservation", "appointment", "class_session",
         "classsession", "instructor", "membership_plan", "membershipplan",
         "session_slot"),
    ),
    # Subscription billing — Recurly / Chargebee / Zuora / Stripe Billing.
    # BEFORE payment-processing so "recurring subscription billing" stays
    # here, and BEFORE banking so "SaaS subscription with invoices" isn't
    # pulled to banking.
    ArchetypeKeywords(
        "subscription-billing-platform",
        ("subscription billing", "recurring billing"),
        ("subscription", "billing", "saas", "recurring", "mrr", "arr",
         "dunning", "invoice", "usage-based", "metered", "trial"),
    ),
    # Payment processing — Stripe / Adyen / Square / Braintree. BEFORE
    # banking so "merchant chargeback / payout" lands here; banking still
    # wins for bank/loan/kyc, none of which hit this list.
    ArchetypeKeywords(
        "payment-processing-platform",
        ("payment processing", "checkout gateway"),
        ("payments", "payment", "stripe", "checkout", "gateway", "merchant",
         "chargeback", "dispute", "payout", "settlement", "refund"),
    ),
    # Banking / fintech — retail banking, loan origination, compliance.
    # Pairs with the TRUST_NAVY visual preset.
    ArchetypeKeywords(
        "banking-platform",
        ("banking", "bank account", "core banking", "payments platform",
         "money movement"),
        ("bank", "banking", "account", "loan", "credit", "compliance", "kyc",
         "ledger", "treasury", "fintech", "deposits", "mortgage",
         "transaction", "statement", "beneficiary", "payee"),
    ),
    # Healthcare / clinical / EHR. More specific than booking, which also
    # carries "appointment" — a booking app that mentions appointment once
    # still needs a second medical hit to land here.
    ArchetypeKeywords(
        "healthcare-platform",
        ("ehr", "electronic health record", "patient chart"),
        ("healthcare", "patient", "clinical", "hospital", "clinic", "ehr",
         "emr", "doctor", "nurse", "medical", "prescription", "vitals"),
    ),
    # Field service / dispatch / HVAC / on-site repair.
    ArchetypeKeywords(
        "field-service-platform",
        ("field service", "dispatch", "work order"),
        ("field service", "technician", "dispatch", "work order", "hvac",
         "plumbing", "on-site", "repair", "service call", "field engineer",
         "service ticket"),
    ),
    # Learning management. "training" is pinned here rather than
    # field-service to avoid double-counting.
    ArchetypeKeywords(
        "learning-platform",
        ("learning management", "lms", "course platform"),
        ("lms", "learning", "courses", "lessons", "cohort", "training",
         "e-learning", "quizzes", "curriculum", "students", "learners"),
    ),
    # Marketplace / two-sided.
    ArchetypeKeywords(
        "marketplace-platform",
        ("marketplace", "multi-vendor storefront"),
        ("marketplace", "seller", "buyer", "listing", "storefront",
         "multi-vendor", "etsy", "upwork", "service marketplace",
         "two-sided"),
    ),
    # CMS / editorial / publishing.
    ArchetypeKeywords(
        "content-platform",
        ("content management", "cms", "editorial workflow"),
        ("cms", "content", "articles", "blog", "editorial", "publishing",
         "posts", "media library", "docs site", "knowledge base"),
    ),
    # CRM / sales pipeline.
    ArchetypeKeywords(
        "crm-platform",
        ("crm", "customer relationship", "sales pipeline", "lead management"),
        ("crm", "sales", "deals", "pipeline", "leads", "contacts",
         "opportunities", "quotas", "ae", "account executive"),
    ),
    # Inventory / WMS.
    ArchetypeKeywords(
        "inventory-platform",
        ("inventory management", "stock control", "warehouse"),
        ("inventory", "warehouse", "stock", "sku", "wms", "receiving",
         "picking", "purchase order", "po", "supplier"),
    ),
    # Project management / agency.
    ArchetypeKeywords(
        "project-platform",
        ("project management", "task tracker", "issue tracker"),
        ("project management", "pm", "agency", "consulting", "tasks",
         "milestones", "timesheet", "sprint", "standup", "kanban board",
         "jira", "linear"),
    ),
    # Dev-tools / CI-CD / observability. BEFORE analytics-dashboard so an
    # SRE dashboard resolves to dev-tools, not the generic BI vocab.
    ArchetypeKeywords(
        "dev-tools-platform",
        ("dev tools", "developer platform", "api dashboard"),
        ("devtools", "dev tools", "ci/cd", "github actions", "circleci",
         "jenkins", "deployments", "monitoring", "sentry", "grafana",
         "datadog", "alerts", "incidents", "oncall", "sre", "observability",
         "build pipeline"),
    ),
    # Legislature and municipal council — bills, ordinances, agendas,
    # roll-call votes. BEFORE analytics-dashboard, whose tokens
    # ("reporting", "kpi") are generic enough to claim any civic admin app
    # — which is exactly what happened before this entry existed. AFTER
    # subscription-billing so "bill" cannot outrank a real billing app
    # (the token is a substring of "billing").
    ArchetypeKeywords(
        "legislative-platform",
        ("legislative", "legislature", "city council", "council meeting",
         "bill tracking", "ordinance", "agenda management", "municipal clerk",
         "committee hearing", "roll call vote", "public meeting",
         "board of supervisors"),
        ("legislative", "legislature", "ordinance", "bill", "agenda",
         "agenda_item", "committee", "vote_session", "vote_record",
         "roll call", "quorum", "hansard", "parliamentary", "plenary",
         "constituency", "political_bloc"),
    ),
    # Analytics / BI — Metabase / Amplitude / Looker. Deliberately last
    # among the "dashboard-ish" archetypes: its tokens are the vaguest in
    # the catalog and it wins by default when nothing better matches.
    ArchetypeKeywords(
        "analytics-dashboard-platform",
        ("analytics dashboard", "kpi dashboard", "metrics dashboard",
         "revenue analytics", "operator view", "operational dashboard",
         "reporting dashboard", "executive dashboard"),
        ("analytics", "bi", "business intelligence", "metabase", "amplitude",
         "looker", "mixpanel", "tableau", "queries", "datasets", "kpi",
         "reporting"),
    ),
    # Messaging / realtime chat.
    ArchetypeKeywords(
        "messaging-platform",
        ("chat app", "team messaging", "direct messaging"),
        ("slack", "teams", "messaging", "chat", "channels", "dms",
         "direct message", "workspace", "mentions", "threads",
         "realtime chat", "communication"),
    ),
    # Document intelligence — OCR / extraction / indexed search. AFTER
    # content-platform so a plain CMS description doesn't get pulled here
    # on its single "knowledge base" hit.
    ArchetypeKeywords(
        "document-intelligence-platform",
        ("document intelligence", "document ai", "invoice extraction"),
        ("document intelligence", "ocr", "extraction", "document",
         "batch upload", "invoice extraction", "receipt scanner",
         "docparser", "rossum", "nanonets", "textract", "document ai",
         "indexed search", "full-text search", "knowledge base",
         "doc search"),
    ),
)


def plan_token_table() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """``((vocab_id, tokens), ...)`` for haystack scoring, in precedence order.

    Consumed by ``product_brief._archetype_from_plan`` (first entry with
    2+ hits wins) and by ``vocab_ranker`` (scores every entry, keeps
    those clearing ``min_score``).
    """
    return tuple((a.vocab_id, a.plan_tokens) for a in ARCHETYPES)


def prompt_phrase_table() -> dict[str, tuple[str, ...]]:
    """``{vocab_id: phrases}`` for prompt matching, in precedence order.

    Consumed by ``plan_directive_parser.detect_vocab_archetype``, which
    returns the first vocab_id with any phrase present.
    """
    return {a.vocab_id: a.prompt_phrases for a in ARCHETYPES}


def known_keyword_archetypes() -> tuple[str, ...]:
    """Every vocab_id this catalog can recognise."""
    return tuple(a.vocab_id for a in ARCHETYPES)


__all__ = [
    "ArchetypeKeywords",
    "ARCHETYPES",
    "plan_token_table",
    "prompt_phrase_table",
    "known_keyword_archetypes",
]
