"""Deterministic ScanProductWorkflow emitter for visual-product-search.

The archetype (services/archetypes/visual_product_search.py) declares one
domain workflow, ``ScanProductWorkflow``. It is the pipeline's single
scan → identify → compare fan-out and touches primitives no default
step-list expresses correctly:

  - ai_identify_product     (Claude vision preset)
  - mcp_tool_call           (Firecrawl search + extract)
  - db_insert / db_update   (products, price_listings, scan_sessions)

This module hand-authors the workflow node graph. It runs BEFORE the LLM
step translator, keyed on ``plan.archetype == "visual-product-search"``
plus workflow name ``ScanProductWorkflow`` (see archetype_workflows/__init__).

Resolution strategy
-------------------
Entity names in the archetype's canonical set (Scan, MatchedProduct,
PriceResult, Retailer) get mapped to REAL table names via the resource
registry when available, else the planner's ``data_models`` + naming
conventions. Missing tables degrade gracefully — the node still emits so
the workflow is authored, and downstream table-guard passes heal the
identifier when the table exists under a variant name.
"""
from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


# ── Table resolution ─────────────────────────────────────────────────────

def _canon(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _resolve_table(
    candidates: list[str],
    table_names: set[str] | None,
    registry: dict | None,
) -> str | None:
    """Find the actual table name matching any of ``candidates``.

    Checks the resource registry first (its ``entities.*.table`` field is the
    authoritative name), then falls back to a normalized substring match
    against ``table_names`` (the real Drizzle files on disk). Returns None
    only when nothing plausibly matches; the workflow node keeps working
    with the first candidate in that case (log a warning)."""
    table_set = set(table_names or [])
    canon_to_real: dict[str, str] = {_canon(t): t for t in table_set}

    if registry:
        ents = (registry.get("entities") or {}) if isinstance(registry, dict) else {}
        for _name, rec in ents.items():
            if not isinstance(rec, dict):
                continue
            rec_table = rec.get("table") or rec.get("slug")
            rec_id = rec.get("id") or rec.get("singular")
            rec_name = rec.get("name") or _name
            for cand in candidates:
                cc = _canon(cand)
                if any(_canon(x) == cc for x in (rec_table, rec_id, rec_name)):
                    if rec_table and rec_table in table_set:
                        return rec_table
                    # Registry says this entity exists but Drizzle file may
                    # use a different form — return the registry's own
                    # table name, downstream table-guard will heal.
                    if rec_table:
                        return rec_table

    for cand in candidates:
        cc = _canon(cand)
        # exact
        if cc in canon_to_real:
            return canon_to_real[cc]
        # substring either direction
        for real_c, real in canon_to_real.items():
            if cc and (cc in real_c or real_c in cc):
                return real
    return None


# ── Node builders ────────────────────────────────────────────────────────

def _pos(y: int) -> dict:
    return {"x": 250, "y": y}


def _node(node_id: str, node_type: str, label: str, y: int, config: dict | None) -> dict:
    return {
        "id": node_id,
        "type": node_type,
        "position": _pos(y),
        "data": {
            "label": label,
            "nodeType": node_type,
            "config": config or {},
        },
    }


def _edge(src: str, dst: str) -> dict:
    return {"id": f"e_{src}_{dst}", "source": src, "target": dst}


# ── Main emitter ─────────────────────────────────────────────────────────


# Per-lane fault tolerance. One dead retailer page (bot-blocked scrape, <N
# search results, a flaky extraction) must cost ONE offer, not the whole run —
# without this the engine dies mid-graph and the session is stranded in
# "pending" forever (register: dxlc5m31 "barcode finds product but no
# prices"). The engine skips a tolerant node's failure and continues on the
# success path. Critical spine nodes (create_session, identify, create_product,
# attach_*) stay strict: if THEY fail the run should fail.
_TOLERANT_PREFIXES = (
    "search", "price_search", "ps_",          # offer searches
    "extract", "x",                            # per-offer scrapes (extract_*, xu0…)
    "insert_price", "insert_pb", "i",          # per-offer inserts (iu0, ie2…)
    "set_product_image", "notify", "not_",     # cosmetic tail nodes
)
_STRICT_IDS = {
    "trigger", "end", "create_session", "identify", "identify_web",
    "insert_product", "create_product", "attach_to_scan", "attach_new",
    "att_u", "att_e", "mark_completed", "find_upc", "find_ean",
    "check_upc", "check_ean", "web_search",
}


def _mark_tolerant_lanes(nodes: list[dict]) -> None:
    for n in nodes:
        nid = str(n.get("id") or "")
        if nid in _STRICT_IDS:
            continue
        if nid.startswith(_TOLERANT_PREFIXES):
            cfg = (n.get("data") or {}).get("config")
            if isinstance(cfg, dict) and cfg.get("actionType"):
                cfg["continueOnError"] = True


def build_scan_product_workflow(
    wf: dict,
    plan: dict,
    table_names: set[str] | None,
    registry: dict | None,
) -> dict | None:
    """Emit the full ScanProductWorkflow JSON.

    The workflow is triggered manually (by the /scan Form submit). The form
    supplies ``scanSessionId`` (the row it just created) and ``rawImageUrl``
    (a forge_files reference). The workflow:

    1. marks the scan session as processing
    2. asks the vision AI to identify the product
    3. persists a Product row (best-effort — reuse if a matching brand+model
       exists is an optimization we defer)
    4. writes the identified productId + confidence back onto the session
    5. reads the retailer allow-list
    6. per retailer, calls Firecrawl search → extract → persists a
       PriceListing row
    7. marks the scan session complete

    Steps 6a/6b are UNROLLED at generation time: the actual retailer set
    only exists after the seed runs, but the archetype guarantees a small
    finite list. The workflow uses a single per-batch mcp_tool_call that
    Firecrawl multiplexes internally via the ``retailer_url`` arg — future
    work: add a foreach node type and let the runtime iterate at execution
    time. For now, one round-trip returns a batch of URLs and the runtime
    fan-outs price extraction.
    """
    scan_table = _resolve_table(
        ["scan_sessions", "scans", "scan"],
        table_names, registry,
    )
    product_table = _resolve_table(
        ["products", "product", "matched_products", "matched_product",
         "matchedProducts"],
        table_names, registry,
    )
    price_table = _resolve_table(
        ["price_listings", "price_listing", "priceListings", "priceResults",
         "price_results"],
        table_names, registry,
    )
    retailer_table = _resolve_table(
        ["retailers", "retailer", "retail_sources"],
        table_names, registry,
    )

    # Log gaps but keep going. Table-guard heals; missing values just
    # produce a workflow that logs an unknown-table error at run time
    # instead of silently doing nothing.
    for label, val in [
        ("scan_sessions", scan_table),
        ("products", product_table),
        ("price_listings", price_table),
        ("retailers", retailer_table),
    ]:
        if not val:
            logger.warning(
                "scan_product_workflow: no matching table for %r — node will "
                "use the fallback identifier; check the plan.data_models list",
                label,
            )
    scan_table = scan_table or "scan_sessions"
    product_table = product_table or "products"
    price_table = price_table or "price_listings"
    retailer_table = retailer_table or "retailers"

    # ── Trigger + process variables ─────────────────────────────────────
    trigger_cfg = {
        "type": "api_event",
        "event": "scan_submitted",
    }
    process_variables = [
        {"name": "scanSessionId", "type": "uuid", "required": True,
         "description": "The scan_sessions row already created by the /scan form."},
        {"name": "rawImageUrl", "type": "string", "required": True,
         "description": "URL/id of the uploaded image (forge_files reference)."},
    ]

    # ── Nodes ───────────────────────────────────────────────────────────
    nodes: list[dict] = [
        _node("trigger", "trigger", "Scan submitted", 0, trigger_cfg),
        _node("mark_processing", "action", "Mark scan processing", 120, {
            "actionType": "db_update",
            "table": scan_table,
            "where": {"id": "{{scanSessionId}}"},
            "values": {"status": "processing"},
        }),
        _node("identify", "action", "AI identify product", 240, {
            "actionType": "ai_identify_product",
            "image_file_id": "{{rawImageUrl}}",
            # Standard vision-preset output shape:
            #   { brand, model, category, attributes, confidence }
            # Bound downstream via {{identify.brand}} etc.
        }),
        _node("insert_product", "action", "Persist identified product", 360, {
            "actionType": "db_insert",
            "table": product_table,
            "values": {
                "name": "{{identify.brand}} {{identify.model}}",
                "brand": "{{identify.brand}}",
                "model": "{{identify.model}}",
                "category": "{{identify.category}}",
                "imageUrl": "{{rawImageUrl}}",
            },
            # db_insert returns {inserted: {id, ...}}; bind as {{insert_product.inserted.id}}.
        }),
        _node("attach_to_scan", "action", "Attach product to scan", 480, {
            "actionType": "db_update",
            "table": scan_table,
            "where": {"id": "{{scanSessionId}}"},
            "values": {
                "recognisedProductId": "{{insert_product.inserted.id}}",
                "confidenceScore": "{{identify.confidence}}",
            },
        }),
        _node("list_retailers", "action", "Load retailer allow-list", 600, {
            "actionType": "db_query",
            "table": retailer_table,
            "where": {"active": True},
            # Result at {{list_retailers.rows}} — array of retailer rows.
        }),
        # Batch search: Firecrawl's search tool accepts a single query with
        # site-restricted syntax and returns a list. We call it once with a
        # composed query that names the identified product plus limits to
        # the retailer domains from the allow-list (Firecrawl honors
        # multiple `site:` clauses in the query). Result at
        # {{search.result.data.web}} — array of {url, title, description}.
        # Firecrawl v2's schema requires `sources[i]` to be an OBJECT
        # (`{"type": "web"}`), not a bare string — passing `["web"]` fails
        # with `sources.0: Invalid input: expected object, received string`.
        _node("search", "action", "Search retailers via Firecrawl", 720, {
            "actionType": "mcp_tool_call",
            "mcp_server_name": "Firecrawl",
            "mcp_tool_name": "firecrawl_search",
            "args": {
                "query": "{{identify.brand}} {{identify.model}} price",
                "limit": 5,
                "sources": [{"type": "web"}],
            },
        }),
        # Extract structured price data from the first result URL (Firecrawl
        # extract with a schema returns {price:number, currency:string}
        # among fields it can parse). Bound via {{extract.result.json.price}} etc.
        # Deferred: iterate over ALL urls when the engine grows a foreach.
        # Use `firecrawl_scrape` with `formats:["json"]` + `jsonOptions.prompt`
        # rather than `firecrawl_extract`. Firecrawl v2 has deprecated the
        # `/v2/extract` endpoint (their MCP tool responds "Bad Request" on
        # retail URLs like louisvuitton.com even though `extract` still works
        # for trivial pages like example.com). `scrape` + `json` format is the
        # advertised replacement and reliably returns `{json:{price,currency}}`
        # for real product pages. Result path downstream:
        #   {{scrape.result.data.json.price}}
        #   {{scrape.result.data.json.currency}}
        _node("extract", "action", "Extract price from top result", 840, {
            "actionType": "mcp_tool_call",
            "mcp_server_name": "Firecrawl",
            "mcp_tool_name": "firecrawl_scrape",
            "args": {
                "url": "{{search.result.data.web[0].url}}",
                "formats": ["json"],
                "jsonOptions": {
                    "prompt": "Return a JSON object {price:number, currency:string}. price = the main visible product price as a NUMBER with no currency symbol or thousands-separator commas (e.g. 3550). currency = ISO code (USD, EUR, GBP). Ignore struck-through, tax, shipping, or subscription prices.",
                },
            },
        }),
        _node("insert_price", "action", "Persist price listing", 960, {
            "actionType": "db_insert",
            "table": price_table,
            "values": {
                "productId": "{{insert_product.inserted.id}}",
                "scanSessionId": "{{scanSessionId}}",
                "productUrl": "{{search.result.data.web[0].url}}",
                "price": "{{extract.result.json.price}}",
                # Firecrawl's page-extract often returns null currency — the
                # page has "$3,550.00" without an explicit ISO code, and the
                # extract prompt can't force a value when nothing on the page
                # matches. Currency is required by the price-result-currency
                # business rule. The seeded retailers list is US-only, so USD
                # is the correct default until we grow a URL-TLD → currency
                # heuristic (or an AI classifier step).
                "currency": "USD",
            },
        }),
    ]

    # Fan out per-URL scrapes for the remaining search results. The `search`
    # node's limit is 5, so URLs 0 (handled above by `extract`/`insert_price`)
    # through 4 give us five price rows per scan. Chained sequentially rather
    # than parallel — the engine has no `foreach` yet and Firecrawl's per-key
    # rate limits are conservative, so sequential is safer than a manual join.
    # Each `extract_N` mirrors the top-URL `extract` node's contract exactly.
    URL_FANOUT = 5  # includes URL 0
    _EXTRACT_PROMPT = (
        "Return a JSON object {price:number, currency:string}. "
        "price = the main visible product price as a NUMBER with no currency symbol or "
        "thousands-separator commas (e.g. 3550). currency = ISO code (USD, EUR, GBP). "
        "Ignore struck-through, tax, shipping, or subscription prices."
    )
    y_cursor = 1080
    for i in range(1, URL_FANOUT):
        extract_id = f"extract_{i}"
        insert_id = f"insert_price_{i}"
        nodes.append(_node(extract_id, "action", f"Extract price from result #{i + 1}", y_cursor, {
            "actionType": "mcp_tool_call",
            "mcp_server_name": "Firecrawl",
            "mcp_tool_name": "firecrawl_scrape",
            "args": {
                "url": f"{{{{search.result.data.web[{i}].url}}}}",
                "formats": ["json"],
                "jsonOptions": {"prompt": _EXTRACT_PROMPT},
            },
        }))
        y_cursor += 120
        nodes.append(_node(insert_id, "action", f"Persist price listing #{i + 1}", y_cursor, {
            "actionType": "db_insert",
            "table": price_table,
            "values": {
                "productId": "{{insert_product.inserted.id}}",
                "scanSessionId": "{{scanSessionId}}",
                "productUrl": f"{{{{search.result.data.web[{i}].url}}}}",
                "price": f"{{{{{extract_id}.result.json.price}}}}",
                "currency": "USD",
            },
        }))
        y_cursor += 120

    nodes.append(_node("mark_completed", "action", "Mark scan completed", y_cursor, {
        "actionType": "db_update",
        "table": scan_table,
        "where": {"id": "{{scanSessionId}}"},
        "values": {"status": "completed"},
    }))
    y_cursor += 120
    nodes.append(_node("end", "end", "Complete", y_cursor, None))

    # Chain: … → extract → insert_price → extract_1 → insert_price_1 → …
    #        → insert_price_{N-1} → mark_completed → end.
    edges: list[dict] = [
        _edge("trigger", "mark_processing"),
        _edge("mark_processing", "identify"),
        _edge("identify", "insert_product"),
        _edge("insert_product", "attach_to_scan"),
        _edge("attach_to_scan", "list_retailers"),
        _edge("list_retailers", "search"),
        _edge("search", "extract"),
        _edge("extract", "insert_price"),
    ]
    prev = "insert_price"
    for i in range(1, URL_FANOUT):
        edges.append(_edge(prev, f"extract_{i}"))
        edges.append(_edge(f"extract_{i}", f"insert_price_{i}"))
        prev = f"insert_price_{i}"
    edges.append(_edge(prev, "mark_completed"))
    edges.append(_edge("mark_completed", "end"))

    _mark_tolerant_lanes(nodes)
    return {
        "id": "scan-product-workflow",
        "name": wf.get("name") or "ScanProductWorkflow",
        "description": wf.get("description")
            or "Scan → identify product → compare prices across retailers via Firecrawl.",
        # Engine-level cleanup: a mid-run throw (vision timeout, dead scrape
        # spine) must not strand the session in "processing" — the results
        # page polls status and would spin forever.
        "onFailure": {
            "actionType": "db_update",
            "table": scan_table,
            "where": {"id": "{{scanSessionId}}"},
            "values": {"status": "failed"},
        },
        "processVariables": process_variables,
        "definition": {
            "trigger": trigger_cfg,
            "nodes": nodes,
            "edges": edges,
        },
    }


# ── BarcodeSearchWorkflow emitter ────────────────────────────────────────
#
# Ported from the live-proven LensShop reference (output/dxlc5m31,
# 2026-08-19). Graph:
#
#   trigger(barcode) → create_session → find_upc → check_upc
#     then → [known-product tail: fresh offer search + 3 scrapes + attach]
#     else → find_ean → check_ean
#       then → [known-product tail (ean variant)]
#       else → web_search → identify_web (ai_extract) → create_product
#              → price_search → 3× (scrape + insert) → attach_new → notify → end
#
# Two hard-won constraints baked in:
#   1. All dynamic values use DIRECT node-output bindings
#      ("{{find_upc.rows[0].canonicalName}}") — set_variable does NOT
#      interpolate {{…}} in variableValue, so shared-variable indirection
#      silently searches the literal template text.
#   2. Known-product scans still re-scrape offers into THEIR OWN session
#      (results pages scope offers by scanSessionId), and every scrape
#      prompt also extracts image_url so offer/product/session images
#      populate.

_OFFER_PROMPT = (
    "Return a JSON object {price:number, currency:string}. price = the main "
    "visible product price as a NUMBER with no currency symbol or "
    "thousands-separator commas (e.g. 3550). currency = ISO code (USD, EUR, "
    "GBP). Ignore struck-through, tax, shipping, or subscription prices. "
    "Also return retailer = the friendly store name (e.g. \"Amazon\", "
    "\"Walmart\") inferred from the page or URL. Also return image_url = the "
    "absolute https URL of the MAIN product image on the page (og:image meta "
    "tag or the primary gallery image). Must be a full URL ending in an "
    "image file or CDN path; empty string if none found."
)


def _resolve_column(
    registry: dict | None,
    table: str,
    candidates: list[str],
    fallback: str,
) -> str:
    """Pick the real column/prop name on ``table`` matching a candidate.

    Registry column records can be sparse; when nothing matches, return the
    LensShop-proven fallback — the runtime's camelCase↔snake tolerance and
    the archetype's ensured plan columns make that safe."""
    if not registry:
        return fallback
    tc = _canon(table)
    for _name, rec in (registry.get("entities") or {}).items():
        if not isinstance(rec, dict):
            continue
        if _canon(rec.get("table") or "") != tc:
            continue
        col_names = [
            (c.get("name") if isinstance(c, dict) else c) or ""
            for c in (rec.get("columns") or [])
        ]
        canon_cols = {_canon(c): c for c in col_names if c}
        for cand in candidates:
            hit = canon_cols.get(_canon(cand))
            if hit:
                return hit
    return fallback


def build_barcode_search_workflow(
    wf: dict,
    plan: dict,
    table_names: set[str] | None,
    registry: dict | None,
) -> dict | None:
    """Emit the full BarcodeSearchWorkflow JSON (scan-a-barcode entry point)."""
    scan_table = _resolve_table(
        ["scan_sessions", "scans", "scan"], table_names, registry) or "scan_sessions"
    product_table = _resolve_table(
        ["products", "product", "matched_products", "matched_product"],
        table_names, registry) or "products"
    price_table = _resolve_table(
        ["price_results", "price_listings", "price_listing", "priceResults"],
        table_names, registry) or "price_results"

    # Column names, resolved per app with the reference app's names as fallback.
    c_name = _resolve_column(registry, product_table,
                             ["canonicalName", "name", "title", "productName"], "canonicalName")
    c_brand = _resolve_column(registry, product_table, ["brand", "maker"], "brand")
    c_cat = _resolve_column(registry, product_table, ["category", "productCategory"], "category")
    c_ean = _resolve_column(registry, product_table, ["ean", "barcode", "gtin"], "ean")
    c_upc = _resolve_column(registry, product_table, ["upc"], "upc")
    c_pimg = _resolve_column(registry, product_table, ["imageUrl", "image", "photoUrl"], "imageUrl")

    trigger_cfg = {"type": "manual"}
    process_variables = [
        {"name": "barcode", "type": "string", "source": "trigger", "required": True,
         "description": "Decoded barcode digits (EAN-13 or UPC-A) from the BarcodeScanner."},
    ]

    def scrape(node_id: str, search_id: str, idx: int, label: str) -> dict:
        return _node(node_id, "action", label, 0, {
            "actionType": "mcp_tool_call",
            "mcp_server_name": "Firecrawl",
            "mcp_tool_name": "firecrawl_scrape",
            "args": {
                "url": f"{{{{{search_id}.result.data.web[{idx}].url}}}}",
                "formats": ["json"],
                "jsonOptions": {"prompt": _OFFER_PROMPT},
            },
        })

    def offer_insert(node_id: str, search_id: str, scrape_id: str, idx: int, label: str) -> dict:
        return _node(node_id, "action", label, 0, {
            "actionType": "db_insert",
            "table": price_table,
            "values": {
                "scanSessionId": "{{create_session.inserted.id}}",
                "productUrl": f"{{{{{search_id}.result.data.web[{idx}].url}}}}",
                "price": f"{{{{{scrape_id}.result.json.price}}}}",
                "currency": f"{{{{{scrape_id}.result.json.currency}}}}",
                "retailerName": f"{{{{{scrape_id}.result.json.retailer}}}}",
                "imageUrl": f"{{{{{scrape_id}.result.json.image_url}}}}",
            },
        })

    nodes: list[dict] = [
        _node("trigger", "trigger", "Barcode scanned", 0, trigger_cfg),
        _node("create_session", "action", "Create scan session", 0, {
            "actionType": "db_insert",
            "table": scan_table,
            "values": {"status": "pending"},
        }),
        _node("find_upc", "action", "Find product by UPC", 0, {
            "actionType": "db_query",
            "table": product_table,
            "where": {c_upc: "{{barcode}}"},
        }),
        _node("check_upc", "condition", "UPC match?", 0, {
            "expression": "find_upc.count > 0",
        }),
        _node("find_ean", "action", "Find product by EAN", 0, {
            "actionType": "db_query",
            "table": product_table,
            "where": {c_ean: "{{barcode}}"},
        }),
        _node("check_ean", "condition", "EAN match?", 0, {
            "expression": "find_ean.count > 0",
        }),
        # ── Unknown-product path: identify via the web, register, price ──
        _node("web_search", "action", "Search the web for the barcode", 0, {
            "actionType": "mcp_tool_call",
            "mcp_server_name": "Firecrawl",
            "mcp_tool_name": "firecrawl_search",
            "args": {"query": "{{barcode}}", "limit": 5},
        }),
        _node("identify_web", "action", "AI-identify product from results", 0, {
            "actionType": "ai_extract",
            "aiInput": "{{web_search.result.data.web}}",
            "aiExtractFields": ["product_name", "product_brand", "product_category"],
            "aiPrompt": (
                "These are web search results for the product barcode "
                "{{barcode}}. Work out what single retail product this "
                "barcode belongs to. Return product_name (a concise product "
                "title incl. size/variant), product_brand and "
                "product_category. If the results are inconclusive use "
                "'Unknown product {{barcode}}' as product_name and empty "
                "strings for the rest."
            ),
        }),
        _node("create_product", "action", "Register identified product", 0, {
            "actionType": "db_insert",
            "table": product_table,
            "values": {
                c_name: "{{identify_web.data.product_name}}",
                c_brand: "{{identify_web.data.product_brand}}",
                c_cat: "{{identify_web.data.product_category}}",
                c_ean: "{{barcode}}",
            },
        }),
        _node("price_search", "action", "Search retail offers", 0, {
            "actionType": "mcp_tool_call",
            "mcp_server_name": "Firecrawl",
            "mcp_tool_name": "firecrawl_search",
            "args": {"query": "{{identify_web.data.product_name}} price buy", "limit": 3},
        }),
    ]
    for i in range(3):
        nodes.append(scrape(f"extract_b{i}", "price_search", i, f"Scrape offer {i + 1}"))
        nodes.append(offer_insert(f"insert_pb{i}", "price_search", f"extract_b{i}", i,
                                  f"Save offer {i + 1}"))
    nodes += [
        _node("set_product_image", "action", "Set product image", 0, {
            "actionType": "db_update",
            "table": product_table,
            "where": {"id": "{{create_product.inserted.id}}"},
            "values": {c_pimg: "{{extract_b0.result.json.image_url}}"},
        }),
        _node("attach_new", "action", "Attach product to session", 0, {
            "actionType": "db_update",
            "table": scan_table,
            "where": {"id": "{{create_session.inserted.id}}"},
            "values": {
                "recognisedProductId": "{{create_product.inserted.id}}",
                "imageUrl": "{{extract_b0.result.json.image_url}}",
                "confidenceScore": "1",
                "status": "completed",
            },
        }),
        _node("notify_new", "action", "Notify (new product)", 0, {
            "actionType": "send_notification",
            "message": ("Identified '{{identify_web.data.product_name}}' from "
                        "barcode {{barcode}} and gathered live retailer offers."),
            "recipientRole": "user", "toRole": "user", "channel": "in_app",
        }),
        _node("end", "end", "Complete", 0, None),
    ]

    edges: list[dict] = [
        _edge("trigger", "create_session"),
        _edge("create_session", "find_upc"),
        _edge("find_upc", "check_upc"),
        {**_edge("check_upc", "find_ean"), "data": {"edgeType": "else"}},
        _edge("find_ean", "check_ean"),
        {**_edge("check_ean", "web_search"), "data": {"edgeType": "else"}},
        _edge("web_search", "identify_web"),
        _edge("identify_web", "create_product"),
        _edge("create_product", "price_search"),
        _edge("price_search", "extract_b0"),
    ]
    chain = ["extract_b0", "insert_pb0", "extract_b1", "insert_pb1",
             "extract_b2", "insert_pb2", "set_product_image", "attach_new",
             "notify_new", "end"]
    for a, b in zip(chain, chain[1:]):
        edges.append(_edge(a, b))

    # ── Known-product tails: per-branch, direct bindings only ────────────
    for sfx, src, check in (("u", "find_upc", "check_upc"),
                            ("e", "find_ean", "check_ean")):
        name_bind = f"{{{{{src}.rows[0].{c_name}}}}}"
        ps = f"ps_{sfx}"
        nodes.append(_node(ps, "action", f"Search offers ({sfx})", 0, {
            "actionType": "mcp_tool_call",
            "mcp_server_name": "Firecrawl",
            "mcp_tool_name": "firecrawl_search",
            "args": {"query": f"{name_bind} price buy", "limit": 3},
        }))
        prev = ps
        for i in range(3):
            x, ins = f"x{sfx}{i}", f"i{sfx}{i}"
            nodes.append(scrape(x, ps, i, f"Scrape offer {i + 1} ({sfx})"))
            nodes.append(offer_insert(ins, ps, x, i, f"Save offer {i + 1} ({sfx})"))
            edges.append(_edge(prev, x))
            edges.append(_edge(x, ins))
            prev = ins
        att, notif = f"att_{sfx}", f"not_{sfx}"
        nodes.append(_node(att, "action", f"Attach product ({sfx})", 0, {
            "actionType": "db_update",
            "table": scan_table,
            "where": {"id": "{{create_session.inserted.id}}"},
            "values": {
                "recognisedProductId": f"{{{{{src}.rows[0].id}}}}",
                "imageUrl": f"{{{{{src}.rows[0].{c_pimg}}}}}",
                "confidenceScore": "1",
                "status": "completed",
            },
        }))
        nodes.append(_node(notif, "action", f"Notify ({sfx})", 0, {
            "actionType": "send_notification",
            "message": (f"Matched '{name_bind}' from your catalog and "
                        "refreshed live retailer offers."),
            "recipientRole": "user", "toRole": "user", "channel": "in_app",
        }))
        edges.append({**_edge(check, ps), "data": {"edgeType": "then"}})
        edges.append(_edge(prev, att))
        edges.append(_edge(att, notif))
        edges.append(_edge(notif, "end"))

    # Lay nodes out vertically in declaration order for the editor canvas.
    for i, n in enumerate(nodes):
        n["position"] = _pos(i * 110)

    _mark_tolerant_lanes(nodes)
    return {
        "id": "barcode-search-workflow",
        "name": wf.get("name") or "BarcodeSearchWorkflow",
        "description": wf.get("description")
            or "Scan a barcode → match catalog or identify via the web → "
               "scrape live retailer offers with images.",
        # Same stranded-session guard as the scan workflow; here the session
        # row is created inside the run, so reference the insert output.
        "onFailure": {
            "actionType": "db_update",
            "table": scan_table,
            "where": {"id": "{{create_session.inserted.id}}"},
            "values": {"status": "failed"},
        },
        "processVariables": process_variables,
        "definition": {
            "trigger": trigger_cfg,
            "nodes": nodes,
            "edges": edges,
        },
    }
