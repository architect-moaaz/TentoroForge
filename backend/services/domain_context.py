"""Domain Context — lightweight keyword classifier for the pre-pipeline
planner call. The full discovery dossier (with persona blocks, design
patterns, compliance notes, etc.) is produced by `agents.domain_agent.
run_domain_discovery` at Layer 1 of the pipeline — that replaces what was
previously the curated `backend/knowledge/` KB folder plus the hardcoded
persona content in this module.

What stays here:
  - A label-only `detect_domain(description) -> dict` for callers that
    need a cheap domain hint BEFORE the pipeline runs (e.g. the planner
    pre-call from the chat handler). The dict has the same shape as the
    discovery agent output so downstream code doesn't need to branch, but
    everything beyond `domain` is empty.

  - `build_domain_profile(ctx, role)` — the canonical accessor every
    downstream agent uses. Renders a structured `[DOMAIN PROFILE]` block
    tailored to the role from the discovery dossier. Returns "" when no
    useful content is available (graceful degradation).

  - `get_domain_label(ctx)` — tiny helper for callers that just need
    the canonical domain label.

If you need full domain context (personas, design patterns, compliance),
read `src/contracts/discovery.json` produced by the pipeline, or call
`run_domain_discovery` directly.
"""
from __future__ import annotations

import re



def classify_domain(description: str) -> str:
    """Public accessor — return just the classified domain LABEL.

    Same classifier as :func:`detect_domain`, but returns the bare
    label string. Introduced for Phase 1 of the design-brief rollout
    (services.design_brief_author reads this) so callers that only need
    the domain don't have to unwrap the dossier dict.

    Deterministic; keyword-scored. Never raises. Returns "General" for
    descriptions that don't match any keyword bucket.
    """
    if not description or not isinstance(description, str):
        return "General"
    return _classify_domain(description.lower(), description)


def detect_domain(description: str) -> dict:
    """Lightweight, deterministic, keyword-based domain label classifier.

    Returns a dict shaped like the discovery agent output but with EMPTY
    personas — callers that need persona content must run the discovery
    agent (typically Layer 1 of the pipeline does this).

    Use cases for this stub:
      - Pre-pipeline planner calls that need a cheap domain hint
      - Chat handlers that want to label the conversation before any
        expensive LLM work
      - Fallback path when ANTHROPIC_API_KEY is missing
    """
    lower = description.lower()
    domain = _classify_domain(lower, description)

    return {
        "domain": domain,
        "description": description,
        "personas": {},  # empty — discovery agent populates these
        "source": "keyword_classifier",
    }


# Cache compiled keyword patterns — _classify_domain runs per generation and
# the keyword list is static.
_KEYWORD_RE_CACHE: dict[str, "re.Pattern[str]"] = {}


def _keyword_hits(keyword: str, text: str) -> bool:
    """Does `keyword` occur in `text` as a WHOLE word (or whole phrase)?

    `"grade" in "upgraded"` was True, which is how a substring test misclassifies.
    Word boundaries are applied at both ends; internal spaces and hyphens in a
    multi-word keyword ("real estate", "e-commerce") are matched flexibly so a
    hyphen/space variation does not miss.
    """
    kw = (keyword or "").strip().lower()
    if not kw:
        return False
    pat = _KEYWORD_RE_CACHE.get(kw)
    if pat is None:
        parts = [re.escape(p) for p in re.split(r"[\s\-]+", kw) if p]
        if not parts:
            return False
        body = r"[\s\-]+".join(parts)
        #  does not work next to non-word chars (e.g. "now()"), so anchor on
        # a non-word-character lookaround instead.
        pat = re.compile(rf"(?<!\w){body}(?!\w)")
        _KEYWORD_RE_CACHE[kw] = pat
    return bool(pat.search(text))


def _classify_domain(lower: str, original: str) -> str:
    """Classify the domain from keywords in the description.

    Uses an ordered list of (domain, keywords) tuples so more specific domains
    are checked before broader ones (e.g., Hospitality before E-Commerce).
    """
    # Ordered: more specific domains first to avoid false matches on common words
    domain_keywords = [
        ("Healthcare", [
            "hospital", "patient", "medical", "clinic", "doctor", "nurse",
            "health", "ehr", "emr", "pharmacy", "prescription", "diagnosis",
            "appointment", "lab result", "radiology", "telemedicine",
        ]),
        ("Hospitality & Food", [
            "restaurant", "hotel", "reservation", "booking", "menu",
            "food", "hospitality", "kitchen", "catering", "guest",
            "table management", "room service",
        ]),
        ("Finance & Banking", [
            "bank", "finance", "loan", "payment", "transaction", "accounting",
            "invoice", "ledger", "credit", "debit", "insurance", "portfolio",
            "trading", "wealth", "mortgage", "fintech",
        ]),
        ("E-Commerce & Retail", [
            "shop", "store", "ecommerce", "e-commerce", "product catalog",
            "cart", "checkout", "retail", "marketplace",
            "warehouse", "fulfillment",
        ]),
        ("Education", [
            "school", "university", "student", "teacher", "course", "learning",
            "lms", "grade", "classroom", "curriculum", "enrollment", "academic",
            "exam", "assignment", "tutor",
        ]),
        ("Human Resources", [
            "hr", "human resource", "employee", "payroll", "leave", "attendance",
            "recruitment", "onboarding", "performance review", "benefit",
            "timesheet", "workforce", "talent", "compensation",
        ]),
        ("Real Estate & Property", [
            "property", "real estate", "tenant", "landlord", "lease", "rental",
            "listing", "apartment", "building", "maintenance request", "hoa",
        ]),
        ("Manufacturing", [
            "manufacturing", "production", "assembly", "quality control",
            "bill of materials", "bom", "work order", "shop floor",
            "maintenance", "equipment", "downtime",
        ]),
        ("Logistics & Supply Chain", [
            "logistics", "supply chain", "shipment", "fleet", "delivery",
            "tracking", "route", "dispatch", "freight", "carrier", "3pl",
        ]),
        ("Legal", [
            "law firm", "legal", "case management", "attorney", "court",
            "contract management", "compliance", "litigation", "paralegal",
        ]),
        ("Project Management", [
            "project management", "task tracker", "kanban", "sprint",
            "agile", "scrum", "milestone", "backlog", "jira", "trello",
            "time tracking", "resource allocation",
        ]),
        ("CRM & Sales", [
            "crm", "sales", "lead", "pipeline", "contact", "deal",
            "opportunity", "customer relationship", "prospect", "quota",
        ]),
        ("Government & Public Sector", [
            "government", "citizen", "permit", "license", "municipal",
            "public service", "regulatory", "compliance", "inspection",
        ]),
        ("Non-Profit", [
            "non-profit", "nonprofit", "donation", "volunteer", "grant",
            "fundraising", "charity", "ngo",
        ]),
        ("Media & Content", [
            "content management", "cms", "blog", "article", "publishing",
            "media", "editorial", "podcast", "video platform",
        ]),
        ("Agriculture", [
            "farm", "agriculture", "crop", "livestock", "harvest",
            "irrigation", "soil", "agronomic",
        ]),
        ("Energy & Utilities", [
            "energy", "utility", "power", "solar", "wind", "grid",
            "meter reading", "consumption", "renewable",
        ]),
    ]

    # SCORE every domain, then take the best — do not return the first domain
    # that happens to match one word.
    #
    # Two defects, one root cause: a bare membership test (`kw in lower`)
    # evaluated in list order.
    #
    #  * T5-1 — no scoring. The first domain with ANY single keyword hit won
    #    outright, so a description with one incidental "appointment" and eight
    #    e-commerce terms classified as Healthcare. List position beat all the
    #    evidence, and reordering the list silently changed every result.
    #  * T5-2 — no word boundaries. Substring matching fired on "grade" inside
    #    "upgraded", "bom" inside "bombard", "grid" inside "gridlock", "power"
    #    inside "powerful". (It is also why the "hr" keyword carried a trailing
    #    space as a hand-rolled boundary — that hack is no longer needed.)
    #
    # Ties keep the original list order, so the "more specific domains first"
    # intent still decides genuinely equal evidence.
    best_domain = "General Business"
    best_score = 0
    for domain, keywords in domain_keywords:
        score = sum(1 for kw in keywords if _keyword_hits(kw, lower))
        if score > best_score:
            best_domain, best_score = domain, score
    return best_domain


def get_domain_label(domain_ctx: dict | None) -> str:
    """Get the domain label (e.g., 'Healthcare') or empty string."""
    if not domain_ctx:
        return ""
    return domain_ctx.get("domain", "")


# ── [DOMAIN PROFILE] block — the new unified accessor ───────────────────────
#
# Replaces the `get_agent_persona(...) + get_known_issues(...)` two-call
# concat that every downstream agent used. Now agents make one call and
# get a single structured Markdown block containing exactly the dossier
# sections relevant to their role.
#
# Role→sections map below is the source of truth for what each agent
# sees. Adding a new section: extend `_render_*` helpers + the map.
# Adding a new role: extend the map. Agents that pass an unknown role
# fall back to a minimal block (header + persona if any).

_ROLE_SECTIONS: dict[str, frozenset[str]] = {
    # Layer 1
    "planner":           frozenset({"persona", "pitfalls", "compliance", "entities", "patterns", "uncertain"}),
    # Layer 2 — contracts + schema
    "contract_writer":   frozenset({"persona", "pitfalls", "compliance", "entities", "forms"}),
    "schema_designer":   frozenset({"persona", "pitfalls", "entities", "patterns", "visual", "forms"}),
    # Layer 3 — backend
    "auth_agent":        frozenset({"persona", "pitfalls", "compliance"}),
    "api_generator":     frozenset({"persona", "pitfalls", "compliance", "entities"}),
    "business_logic":    frozenset({"persona", "pitfalls", "compliance", "entities"}),
    # Layer 4 — UI
    "component_builder": frozenset({"persona", "pitfalls", "patterns", "visual"}),
    "page_assembler":    frozenset({"persona", "pitfalls", "patterns", "visual", "forms"}),
    # Shell layout — wraps every page; needs patterns (which suggest nav groupings)
    # + visual constraints to honour the dossier's palette/typography.
    "shell_layout_agent": frozenset({"pitfalls", "patterns", "visual"}),
    # Layer 5 — verification
    "qa_tester":         frozenset({"persona", "pitfalls", "compliance", "uncertain"}),
    # Auxiliary agents (no persona — discovery doesn't generate one for them,
    # but they still benefit from selected dossier sections).
    "design_agent":      frozenset({"pitfalls", "patterns", "visual"}),
    "validator":         frozenset({"pitfalls", "compliance"}),
    "indexer":           frozenset({"pitfalls"}),
    "seed_generator":    frozenset({"entities"}),
    "fix_agent":         frozenset({"pitfalls", "patterns"}),
}


def _render_persona(domain_ctx: dict, role: str) -> str:
    personas = domain_ctx.get("personas") or {}
    persona = personas.get(role, "") if isinstance(personas, dict) else ""
    if not isinstance(persona, str) or not persona.strip():
        return ""
    return f"### Your role-specific guidance\n{persona.strip()}"


def _render_pitfalls(domain_ctx: dict, role: str) -> str:
    items = domain_ctx.get("commonPitfalls") or []
    items = [str(x).strip() for x in items if isinstance(x, str) and x.strip()]
    if not items:
        return ""
    lines = ["### Common pitfalls to avoid in this domain"]
    lines.extend(f"- {p}" for p in items)
    return "\n".join(lines)


def _render_compliance(domain_ctx: dict, role: str) -> str:
    items = domain_ctx.get("complianceNotes") or []
    items = [str(x).strip().lower() for x in items if isinstance(x, str) and x.strip()]
    # "none" alone is meaningless — drop it so we don't render an empty section.
    items = [c for c in items if c != "none"]
    if not items:
        return ""
    lines = ["### Compliance regimes that apply"]
    lines.extend(f"- {c}" for c in items)
    lines.append(
        "Treat these as hard constraints — schema choices, error messages, "
        "and audit-trail requirements must respect them."
    )
    return "\n".join(lines)


def _render_entities(domain_ctx: dict, role: str) -> str:
    items = domain_ctx.get("entitySuggestions") or []
    if not isinstance(items, list) or not items:
        return ""
    lines = ["### Entity hints from discovery"]
    lines.append(
        "These are research-driven suggestions, not requirements — the plan "
        "is still authoritative. Use them to fill gaps or sanity-check naming."
    )
    for ent in items[:10]:
        if not isinstance(ent, dict):
            continue
        name = str(ent.get("name", "")).strip()
        if not name:
            continue
        fields = ent.get("likelyFields") or []
        if isinstance(fields, list) and fields:
            field_list = ", ".join(str(f) for f in fields[:8])
            lines.append(f"- **{name}** (likely fields: {field_list})")
        else:
            lines.append(f"- **{name}**")
    if len(lines) <= 2:
        return ""
    return "\n".join(lines)


def _render_patterns(domain_ctx: dict, role: str) -> str:
    items = domain_ctx.get("designPatterns") or []
    if not isinstance(items, list) or not items:
        return ""
    lines = ["### Design patterns common in this domain"]
    for p in items[:6]:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name", "")).strip()
        desc = str(p.get("description", "")).strip()
        if not name:
            continue
        if desc:
            lines.append(f"- **{name}** — {desc}")
        else:
            lines.append(f"- **{name}**")
    if len(lines) <= 1:
        return ""
    return "\n".join(lines)


def _render_visual(domain_ctx: dict, role: str) -> str:
    vl = domain_ctx.get("visualLanguage") or {}
    if not isinstance(vl, dict):
        return ""
    palette = str(vl.get("paletteCharacter", "")).strip()
    typo = str(vl.get("typographyTone", "")).strip()
    density = str(vl.get("densityPreference", "")).strip()
    anchors = vl.get("colorAnchors") if isinstance(vl.get("colorAnchors"), dict) else {}
    primary_hex = str((anchors or {}).get("primary", "")).strip()
    secondary_hex = str((anchors or {}).get("secondary", "")).strip()
    accent_hex = str((anchors or {}).get("accent", "")).strip()
    has_any_anchor = bool(primary_hex or secondary_hex or accent_hex)
    if not (palette or typo or density or has_any_anchor):
        return ""
    lines = ["### Visual language — REQUIRED constraints (not hints)"]
    if palette:
        lines.append(
            f"- **Palette character:** {palette}. The hex codes below "
            f"encode this character — your job is to honour them in the "
            f"design spec + globals.css."
        )
    if has_any_anchor:
        anchor_parts = []
        if primary_hex:
            anchor_parts.append(f"primary `{primary_hex}`")
        if secondary_hex:
            anchor_parts.append(f"secondary `{secondary_hex}`")
        if accent_hex:
            anchor_parts.append(f"accent `{accent_hex}`")
        lines.append(
            f"- **Color anchors (researched):** {', '.join(anchor_parts)}. "
            f"Use these exact hex codes (or perceptually close variants) "
            f"as the foundation of your palette. Do NOT swap them out for "
            f"generic SaaS blue (#3b82f6), emerald (#10b981), or slate "
            f"(#475569)."
        )
    elif palette:
        # No anchors but we have a character — fall back to the hint about
        # avoiding generic defaults (kept from the previous version).
        lines.append(
            "- Translate the palette character into concrete hex codes that "
            "visibly express it. Do NOT default to generic SaaS blue "
            "(#3b82f6), emerald (#10b981), or slate (#475569) unless the "
            "character explicitly calls for them."
        )
    font_family = str(vl.get("fontFamily", "")).strip()
    if typo or font_family:
        if font_family:
            lines.append(
                f"- **Typography:** tone is *{typo or 'unspecified'}*. Use this "
                f"exact font-family stack — `{font_family}` — in the design "
                f"spec's `typography.fontFamily` and in globals.css "
                f"(`body {{ font-family: {font_family}; }}`). Do NOT swap it "
                f"for a generic 'Inter' unless the dossier explicitly says so."
            )
        else:
            lines.append(
                f"- **Typography tone:** {typo}. Pick a font family that conveys "
                f"this tone (e.g. serif for refined, geometric sans for technical, "
                f"humanist sans for friendly)."
            )
    if density:
        lines.append(
            f"- **Density preference:** {density}. This drives padding, line-"
            f"height, and component sizing — bind to it instead of using the "
            f"library defaults."
        )
    return "\n".join(lines)


def _render_forms(domain_ctx: dict, role: str) -> str:
    items = domain_ctx.get("formPatterns") or []
    if not isinstance(items, list) or not items:
        return ""
    lines = ["### Form patterns to favour"]
    for f in items[:6]:
        if isinstance(f, dict):
            pattern = str(f.get("pattern", "")).strip()
            if pattern:
                lines.append(f"- {pattern}")
        elif isinstance(f, str) and f.strip():
            lines.append(f"- {f.strip()}")
    if len(lines) <= 1:
        return ""
    return "\n".join(lines)


def _render_uncertain(domain_ctx: dict, role: str) -> str:
    items = domain_ctx.get("uncertainAreas") or []
    items = [str(x).strip() for x in items if isinstance(x, str) and x.strip()]
    if not items:
        return ""
    lines = [
        "### Areas of uncertainty (flagged by discovery)",
        "The discovery agent was less confident on these — proceed but stay "
        "alert for places where the plan may need clarification:",
    ]
    lines.extend(f"- {u}" for u in items[:6])
    return "\n".join(lines)


_SECTION_RENDERERS = {
    "persona":    _render_persona,
    "pitfalls":   _render_pitfalls,
    "compliance": _render_compliance,
    "entities":   _render_entities,
    "patterns":   _render_patterns,
    "visual":     _render_visual,
    "forms":      _render_forms,
    "uncertain":  _render_uncertain,
}


# ── APP-ARCHETYPE CONTEXT ───────────────────────────────────────────────────
#
# App-archetype contexts are static, hand-authored blocks describing an app
# SHAPE (persona / data shape / UX cues) as opposed to a business DOMAIN
# (Healthcare / Hospitality / etc.). They're injected into the planner prompt
# when `services.app_design_catalog.classify_app_archetype()` matches a brief
# so the planner reasons about the correct entities + surfaces from the start,
# instead of hallucinating a generic CRUD.
#
# Add a block below and register it in `_APP_ARCHETYPE_CONTEXTS`. Consumers
# call `build_archetype_context(name)`.

_VISUAL_COMMERCE_CONTEXT = """\
## [APP ARCHETYPE CONTEXT] — Visual Product Search + Price Comparison

### Persona
End-user is trying to identify and price-check a product they see in a
store, in an ad, or online. They open the app on a phone, point the
camera at the product (or upload a photo from their gallery), and expect
to see live prices from multiple retailers within a few seconds — with a
one-tap outbound to the retailer's product page. Admins curate the
allow-list of retailers the app queries.

### Data shape (canonical)
- **scan_events** — one row per user scan. Fields:
  - `id` (uuid), `user_id` (uuid, fk users)
  - `image_id` (uuid, fk forge_files) — the uploaded/captured image
  - `identified_product_json` (jsonb) — {brand, model, category, attributes, confidence}
  - `matches` (jsonb array) — [{title, price, currency, seller, url, image}, ...]
  - `ts` (timestamp)
- **retail_sources** — the admin-controlled allow-list. Fields:
  - `id` (uuid), `name` (varchar), `source_key` (varchar, unique)
  - `enabled` (boolean, default true), `priority` (integer, default 100)
  - `region` (varchar) — e.g. "US", "IN", "EU"
- **users** — standard user + admin roles; admins own the retail-sources
  page, end-users own the scan page.

### UX cues
- **Mobile-first, camera-primary.** The scan page is a full-viewport
  camera surface with an unmissable capture button. Every other control
  is secondary.
- **Results grid is the reward.** After identify + search, render a
  Grid of Cards (image, title, price, seller badge, outbound button) —
  do NOT render results as a dense Table on mobile.
- **Confidence gating.** If the identifier's confidence is below the
  threshold (0.5 default), show a friendly "we couldn't identify this"
  empty state instead of a wrong match list.
- **Outbound links open in a new tab.** The user's next action is
  usually leaving the app for the retailer's product page.
- **Admin surface is a plain CRUD list** with per-row enable/disable
  toggle, priority, and region. Not a dashboard, not a report — just a
  list you can quickly gate on.

### Agent-graph shape
This app uses an app-agent (not a deterministic workflow):
  system_prompt → tool(ai_identify_product) → router(confidence ≥ 0.5)
  → tool(mcp:firecrawl.search) → guardrail(filter by retail_sources.enabled)
  → memory(cache by image hash, 24h TTL) → return {product, matches}
"""


_APP_ARCHETYPE_CONTEXTS: dict[str, str] = {
    "visual-product-search": _VISUAL_COMMERCE_CONTEXT,
}


def build_archetype_context(archetype: str | None) -> str:
    """Return the hand-authored context block for an APP archetype.

    Returns the block with a leading `\\n\\n` and trailing `\\n` so it
    concatenates cleanly onto a base prompt via `BASE + build_archetype_context(...)`.
    Returns "" when `archetype` is None or unregistered (planner falls back
    to its generic prompt).
    """
    if not archetype:
        return ""
    block = _APP_ARCHETYPE_CONTEXTS.get(archetype)
    if not block:
        return ""
    return f"\n\n{block.rstrip()}\n"


# Dossier `source` values that mean the content was actually RESEARCHED by the
# discovery agent. Everything else — `keyword_classifier` (detect_domain),
# `fallback_keyword_classifier` (_fallback_dossier), an absent source, or any
# future producer — is a guess and is captioned as one. Allow-list rather than
# deny-list so a new fallback cannot slip through unlabelled.
_RESEARCHED_SOURCES = frozenset({"domain_agent", "validation_salvage"})


def build_domain_profile(domain_ctx: dict | None, role: str) -> str:
    """Build a structured `[DOMAIN PROFILE]` block ready to drop into an
    agent's system_prompt.

    Replaces the old two-call pattern:
        domain_persona = get_agent_persona(domain_ctx, role)
        kb_context = get_known_issues(area)
        prompt = BASE + domain_persona + kb_context

    With a single call:
        prompt = BASE + build_domain_profile(domain_ctx, role)

    Returns "" when:
      - domain_ctx is None / not a dict
      - the dossier has no content for any of role's sections AND no
        domain label (graceful degradation — agents fall back to their
        generic prompt)
    """
    if not isinstance(domain_ctx, dict) or not domain_ctx:
        return ""

    sections = _ROLE_SECTIONS.get(role, frozenset({"persona"}))
    rendered: list[str] = []
    for key in ("persona", "pitfalls", "compliance", "entities",
                "patterns", "visual", "forms", "uncertain"):
        if key not in sections:
            continue
        block = _SECTION_RENDERERS[key](domain_ctx, role)
        if block:
            rendered.append(block)

    domain = str(domain_ctx.get("domain", "")).strip()
    description = str(domain_ctx.get("description", "")).strip()

    # If absolutely nothing rendered AND we don't even have a domain label,
    # return empty so the agent falls back to its generic prompt.
    if not rendered and not domain:
        return ""

    header_parts = ["## [DOMAIN PROFILE]"]
    if domain:
        header_parts[0] += f" — {domain}"
    if description:
        header_parts.append(description)

    # Say when this dossier was NOT researched (register T5-4).
    #
    # A keyword-classified dossier is a bare label with every other section
    # empty, and it was rendered here exactly like a fully-researched one — so
    # every downstream agent treated a one-word guess as established fact and
    # built personas, pages and copy on it.
    #
    # The condition is an ALLOW-LIST of researched sources, not a `fallback*`
    # prefix test. The prefix version matched only `_fallback_dossier` and
    # missed `detect_domain`'s own `keyword_classifier` — which is the very
    # path this defect is about — so the caveat was unreachable in practice.
    # An allow-list also means a NEW fallback producer cannot silently bypass
    # the caveat by choosing another name; anything unrecognised is treated as
    # a guess, which is the safe direction.
    if str(domain_ctx.get("source", "")).strip() not in _RESEARCHED_SOURCES:
        reason = str(domain_ctx.get("_fallbackReason", "") or "discovery did not run")
        header_parts.append(
            f"> NOTE: this profile is a KEYWORD GUESS, not researched "
            f"({reason}). The domain label is inferred from words in the "
            f"description and the remaining sections are empty. Do not treat "
            f"it as established fact — prefer what the user's own description "
            f"states."
        )

    body = "\n\n".join(header_parts + rendered)
    return f"\n\n{body}\n"
