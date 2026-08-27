"""Archetype-owned page rewrites (post-generate).

Symmetric to services.archetype_workflows: for archetypes whose primary
entry-point page has a canonical shape the LLM keeps drifting on, replace
the LLM-authored schema with a deterministic one after generation.

The visual-product-search /scan page is the motivating case. The LLM
authors it as a static dashboard with bare workflow-Buttons — click
triggers the workflow but sends an empty input, and the workflow's
"imageUrl required" rule aborts. The correct shape:

  poll: {interval, stopWhen}
  root: Conditional {
    branches: [
      not(scan)                    → Form with FileUpload + Scan Button
      scan.status = 'processing'   → Spinner
      scan.status = 'completed'    → Result Card + Prices Table
      scan.status = 'failed'       → Error Banner
      scan                         → catch-all Waiting
    ]
  }

Runs from services.post_generate_fixes as one of the last passes so
every earlier repair (json-repair, dedup, etc.) has already normalized
the file. Idempotent — if the /scan page already has a `poll` block and
`Conditional` root we assume the author (either a prior run of this
guard or a Smith edit) already brought it to shape and skip.
"""
from __future__ import annotations

import json
import re
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _load_plan_archetype(root: Path) -> str | None:
    """Read the persisted plan and return its archetype tag."""
    for cand in (
        root / "src" / "contracts" / "plan.json",
        root / "contracts" / "plan.json",
    ):
        if not cand.exists():
            continue
        try:
            plan = json.loads(cand.read_text(encoding="utf-8"))
            return plan.get("archetype") or plan.get("app_archetype")
        except Exception:  # noqa: BLE001
            continue
    return None


def _find_workflow_name(root: Path, patterns: tuple[str, ...]) -> str | None:
    """Find the file basename (without .json) of a workflow whose stored
    ``name`` contains any of the given patterns (case-insensitive). Returns
    the ``name`` (used for dispatch), not the filename."""
    wf_dir = root / "workflows"
    if not wf_dir.is_dir():
        return None
    for f in sorted(wf_dir.glob("*.json")):
        try:
            wf = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        name = str(wf.get("name") or "")
        low = name.lower()
        if any(p in low for p in patterns):
            return name
    return None


def _find_entity_name(root: Path, aliases: tuple[str, ...]) -> str | None:
    """Return the entity display name (as used in dataSources) whose id/table
    matches one of the aliases. Reads registry.json."""
    reg_path = root / "registry.json"
    if not reg_path.exists():
        return None
    try:
        reg = json.loads(reg_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    entities = (reg.get("entities") or {}) if isinstance(reg, dict) else {}
    for ent_name, rec in entities.items():
        if not isinstance(rec, dict):
            continue
        candidates = {
            str(rec.get("id") or "").lower(),
            str(rec.get("table") or "").lower(),
            str(rec.get("name") or ent_name).lower(),
            str(rec.get("singular") or "").lower(),
        }
        for a in aliases:
            if a.lower() in candidates:
                return rec.get("name") or ent_name
    return None


def _build_scan_page_schema(
    scan_entity: str,
    price_entity: str | None,
    workflow_name: str,
) -> dict[str, Any]:
    """The stateful scan-and-compare page shape. Feel-lite grammar in
    Conditional.if expressions (`=`, not `==`; `not(x)`, not `!x`).
    stopWhen uses the AutoRefresh JS-style evaluator (`===`, `'x'`)."""
    # Fallback data source shapes work even if the price entity is missing.
    # `scan` MUST be scoped to in-flight rows only. Without a status filter
    # `op:"one"` returns the most recently created scan regardless of state,
    # so the completed-branch pins forever and clicking "New scan" never
    # returns the user to the idle upload form. Filter to pending/processing
    # and sort desc so the polling handoff (create → pending → processing →
    # completed) still targets the same row across ticks.
    data_sources: list[dict] = [
        {
            "name": "scan",
            "entity": scan_entity,
            "op": "one",
            "filter": {"status": "pending"},
            "sort": {"field": "createdAt", "order": "desc"},
        },
    ]
    if price_entity:
        data_sources.append({"name": "prices", "entity": price_entity, "op": "list"})

    # Header card: heading + copy + the uploaded image.
    # /api/files/{id} serves the raw bytes (route.ts in every generated app),
    # so binding <img src="/api/files/{{scan.imageUrl}}"> shows what the user
    # actually scanned. When imageUrl is a full URL (edge case for admin-seeded
    # rows), the leading `/api/files/` prefix will 404 harmlessly; the AutoRefresh
    # poll doesn't crash.
    results_branch_children: list[dict] = [
        {
            "type": "Card",
            "children": [
                {
                    "type": "Row",
                    "props": {"gap": "tokens.spacing.6", "align": "center"},
                    "children": [
                        {
                            "type": "Image",
                            "props": {
                                "src": "/api/files/{{scan.imageUrl}}",
                                "alt": "Scanned product",
                                "width": 160,
                                "height": 160,
                                "className": "rounded-md object-cover",
                            },
                        },
                        {
                            "type": "Stack",
                            "props": {"gap": "tokens.spacing.2"},
                            "children": [
                                {"type": "Heading", "props": {"content": "Scan complete", "level": 2}},
                                {
                                    "type": "Text",
                                    "props": {
                                        "content": "Compare prices from every retailer below.",
                                        "variant": "muted",
                                    },
                                },
                            ],
                        },
                    ],
                }
            ],
        }
    ]
    if price_entity:
        # Repeat + Card grid — one card per price row with a proper anchor
        # Link the user can click through to. Table's built-in Cell has no
        # url/link format (as of writing), and swapping to a cards grid also
        # gives the retailer/price better visual weight than a raw table row.
        # Repeat schema: `bind` is TOP-LEVEL (v2 convention read by Repeat.tsx),
        # not inside `props`. Props there are dropped and the loop renders nothing.
        results_branch_children.append({
            "type": "Repeat",
            "bind": "prices",
            "props": {"as": "row", "layout": "grid", "gap": "tokens.spacing.4"},
            "children": [
                {
                    "type": "Card",
                    "children": [
                        {
                            "type": "Stack",
                            "props": {"gap": "tokens.spacing.3"},
                            "children": [
                                {"type": "Heading",
                                 "props": {"content": "{{row.retailerIdLabel}}", "level": 3}},
                                {"type": "Stat",
                                 "props": {
                                     "label": "Price",
                                     "value": "{{row.price}}",
                                     "hint": "{{row.currency}}",
                                 }},
                                {"type": "Link",
                                 "props": {
                                     "href": "{{row.productUrl}}",
                                     "label": "View on retailer →",
                                     "external": True,
                                 }},
                            ],
                        }
                    ],
                }
            ],
        })

    return {
        "schemaVersion": "2",
        "id": "scan",
        "route": "/scan",
        "layout": "main",
        "meta": {
            "title": "Scan a product",
            "description": (
                "Upload or capture a product image. We identify it and compare "
                "prices across every retailer."
            ),
        },
        # SUBMIT-AUTHORITY marker (VPS-M). Mirrors the plan.pages[/scan].submit
        # declaration in archetypes/visual_product_search.py::REQUIRED_PAGES so
        # any post-generate pass that inspects the SCHEMA (rather than the plan)
        # sees the workflow binding too. The actual runtime dispatch is driven
        # by the Form's props.workflow below; this top-level marker is the
        # audit trail for guards + validators. See SLICE-A T4/T5.
        "submit": {
            "kind": "workflow",
            "target": workflow_name,
        },
        # AutoRefresh: poll while scan is in-flight, stop when terminal.
        "poll": {
            "interval": 2500,
            "stopWhen": (
                "scan.status === 'completed' || scan.status === 'failed'"
            ),
        },
        "dataSources": data_sources,
        "root": {
            "type": "Conditional",
            "props": {
                "branches": [
                    # IDLE — no scan yet. Show the upload form.
                    #
                    # Uses Form CONTAINER mode (not declarative). Form's `fields`
                    # array doesn't support kind:"file"; container mode wraps
                    # children in a <form> and collects every named input's
                    # value on submit. FileUpload writes its returned URL to a
                    # hidden input with `name=imageUrl`, so the Form's onSubmit
                    # dispatch payload is {imageUrl: "<uploaded url>"} — exactly
                    # what the workflow's imageUrl-required rule wants.
                    {
                        "if": "not(scan)",
                        "node": {
                            "type": "Stack",
                            "props": {"gap": "tokens.spacing.6"},
                            "children": [
                                {
                                    "type": "Heading",
                                    "props": {"content": "Scan a product", "level": 1},
                                },
                                {
                                    "type": "Text",
                                    "props": {
                                        "content": (
                                            "Upload an image. We'll identify the "
                                            "product and find prices across every "
                                            "retailer."
                                        ),
                                        "variant": "muted",
                                    },
                                },
                                {
                                    "type": "Card",
                                    "children": [
                                        {
                                            "type": "Form",
                                            "props": {
                                                "workflow": workflow_name,
                                                # Form container mode's default onSuccess
                                                # navigates to parentPath() — that would kick
                                                # the user off /scan the moment they submit,
                                                # missing the entire stateful poll+results flow.
                                                # For visual-product-search /scan we want to
                                                # stay put; the AutoRefresh poll picks up the
                                                # scan.status transitions and Conditional
                                                # branches into Scanning → Completed.
                                                "onSuccess": {"toast": "Scanning…"},
                                            },
                                            "children": [
                                                {
                                                    "type": "Stack",
                                                    "props": {"gap": "tokens.spacing.4"},
                                                    "children": [
                                                        {
                                                            "type": "FileUpload",
                                                            "props": {
                                                                "name": "imageUrl",
                                                                "label": "Upload an image",
                                                                "accept": "image/*",
                                                            },
                                                        },
                                                        # Camera path — same `name` as FileUpload
                                                        # so a submit fills `imageUrl` regardless of
                                                        # source. Both hidden inputs coexist safely
                                                        # because CameraCapture only renders its
                                                        # hidden input AFTER a photo is captured
                                                        # and uploaded, so FormData's last-wins
                                                        # collapse never blanks a real FileUpload id.
                                                        {
                                                            "type": "Text",
                                                            "props": {
                                                                "content": "— or —",
                                                                "variant": "muted",
                                                                "align": "center",
                                                            },
                                                        },
                                                        {
                                                            "type": "CameraCapture",
                                                            "props": {
                                                                "name": "imageUrl",
                                                                "label": "Use your camera",
                                                                "captureLabel": "Take photo",
                                                            },
                                                        },
                                                        {
                                                            "type": "Button",
                                                            "props": {
                                                                "label": "Scan & compare",
                                                                "variant": "primary",
                                                                "submit": True,
                                                            },
                                                        },
                                                    ],
                                                },
                                            ],
                                        }
                                    ],
                                },
                            ],
                        },
                    },
                    # SCANNING — workflow in flight, page auto-polls.
                    {
                        "if": "scan.status = 'processing'",
                        "node": {
                            "type": "Stack",
                            "props": {"gap": "tokens.spacing.6", "align": "center"},
                            "children": [
                                {
                                    "type": "Heading",
                                    "props": {"content": "Scanning…", "level": 2},
                                },
                                {"type": "Progress", "props": {"indeterminate": True}},
                                {
                                    "type": "Text",
                                    "props": {
                                        "content": (
                                            "Identifying the product and checking "
                                            "prices across retailers."
                                        ),
                                        "variant": "muted",
                                    },
                                },
                            ],
                        },
                    },
                    # FAILED — banner with retry hint.
                    {
                        "if": "scan.status = 'failed'",
                        "node": {
                            "type": "Stack",
                            "props": {"gap": "tokens.spacing.4"},
                            "children": [
                                {
                                    "type": "Banner",
                                    "props": {
                                        "variant": "error",
                                        "content": (
                                            "Scan failed. Try again with a clearer "
                                            "image."
                                        ),
                                    },
                                }
                            ],
                        },
                    },
                    # COMPLETED — results view.
                    {
                        "if": "scan.status = 'completed'",
                        "node": {
                            "type": "Stack",
                            "props": {"gap": "tokens.spacing.6"},
                            "children": results_branch_children,
                        },
                    },
                    # Catch-all: any other status (e.g. 'pending').
                    {
                        "if": "scan",
                        "node": {
                            "type": "Stack",
                            "props": {"gap": "tokens.spacing.4", "align": "center"},
                            "children": [
                                {
                                    "type": "Heading",
                                    "props": {"content": "Scan submitted", "level": 2},
                                },
                                {"type": "Progress", "props": {"indeterminate": True}},
                                {
                                    "type": "Text",
                                    "props": {
                                        "content": (
                                            "Status: {{scan.status}} — this page "
                                            "auto-refreshes."
                                        ),
                                        "variant": "muted",
                                    },
                                },
                            ],
                        },
                    },
                ]
            },
        },
    }


def _already_stateful(schema: dict) -> bool:
    """The rewrite is idempotent: once the schema has our shape (poll +
    Conditional root with branches AND a real FileUpload in the idle
    branch) leave it alone. Guards against a second run clobbering a
    Smith edit while still healing a page that has the outer shape but
    a broken input (an earlier revision of this guard emitted Form.fields
    with kind:"file", which the library silently drops → the page renders
    with no upload control at all)."""
    if not isinstance(schema, dict):
        return False
    if not isinstance(schema.get("poll"), dict):
        return False
    root = schema.get("root") or {}
    if not isinstance(root, dict) or root.get("type") != "Conditional":
        return False
    props = root.get("props") or {}
    branches = props.get("branches")
    if not isinstance(branches, list) or len(branches) < 3:
        return False
    # Deep search for a FileUpload node — required to be considered
    # actually functional (not just outer-shape correct).
    def _has_file_upload(node: object) -> bool:
        if isinstance(node, dict):
            if node.get("type") == "FileUpload":
                return True
            for v in node.values():
                if _has_file_upload(v):
                    return True
        elif isinstance(node, list):
            return any(_has_file_upload(x) for x in node)
        return False
    return _has_file_upload(root)


def rewrite_scan_page_for_visual_product_search(output_dir: str) -> int:
    """Post-gen: rewrite /scan schema for visual-product-search apps.

    No-op unless the plan's archetype is visual-product-search AND a
    /scan schema exists AND it's not already in stateful shape.

    Returns the number of files rewritten (0 or 1).
    """
    root = Path(output_dir)
    if not root.exists():
        return 0
    if _load_plan_archetype(root) != "visual-product-search":
        return 0

    schema_path = root / "src" / "schemas" / "scan.json"
    if not schema_path.exists():
        return 0

    try:
        current = json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[archetype-page-fix] scan.json unparseable: %s", exc)
        return 0

    if _already_stateful(current):
        return 0

    # Resolve concrete entity + workflow names from the generated app so the
    # rewrite matches the actual schema instead of the archetype's ideal names.
    scan_entity = _find_entity_name(root, ("scansession", "scan_session", "scan"))
    price_entity = _find_entity_name(
        root, ("pricelisting", "price_listing", "priceresult", "price_result"),
    )
    if not scan_entity:
        logger.warning(
            "[archetype-page-fix] no scan entity found in registry — skipping"
        )
        return 0

    workflow_name = _find_workflow_name(
        root,
        ("scanproduct", "identifyproduct", "scanidentify", "scanandcompare"),
    )
    if not workflow_name:
        logger.warning(
            "[archetype-page-fix] no scan/identify workflow found — skipping"
        )
        return 0

    new_schema = _build_scan_page_schema(scan_entity, price_entity, workflow_name)
    schema_path.write_text(
        json.dumps(new_schema, indent=2), encoding="utf-8",
    )
    logger.info(
        "[archetype-page-fix] rewrote /scan to stateful pattern "
        "(scan_entity=%s, prices=%s, workflow=%s)",
        scan_entity, price_entity, workflow_name,
    )
    return 1


# ── Barcode capability wiring (LensShop back-port, 2026-08-19) ───────────

def _barcode_card(workflow_name: str, history_nav: str | None) -> dict:
    """The proven scan-a-barcode Card: Form → BarcodeSearchWorkflow with an
    auto-submitting BarcodeScanner. Decode lands in the hidden input, the
    scanner submits the form itself, and success navigates to history."""
    on_success: dict = {"toast": "Barcode scanned — searching offers…"}
    if history_nav:
        on_success["navigate"] = history_nav
    return {
        "id": "barcode-search-card",
        "type": "Card",
        "props": {"className": "w-full"},
        "children": [
            {"id": "barcode-search-heading", "type": "Heading",
             "props": {"content": "Search by barcode", "level": 3}},
            {"id": "barcode-search-hint", "type": "Text",
             "props": {"content": "Scan with your camera or drop a barcode image.",
                        "className": "text-sm text-muted-foreground"}},
            {"id": "barcode-search-form", "type": "Form",
             "props": {"workflow": workflow_name,
                        "onSuccess": on_success,
                        "submitLabel": "Search product",
                        "className": "w-full flex flex-col gap-4"},
             "children": [
                 {"id": "barcode-search-scanner", "type": "BarcodeScanner",
                  "props": {"name": "barcode", "autoSubmit": True}},
             ]},
        ],
    }


def _first_children_list(schema: dict) -> list | None:
    """Return the first mutable children list under the page root — handles
    both plain container roots and stateful Conditional roots (children live
    under props.branches[N].node.children)."""
    root = schema.get("root") if isinstance(schema.get("root"), dict) else schema
    if isinstance(root.get("children"), list):
        return root["children"]
    branches = (root.get("props") or {}).get("branches")
    if isinstance(branches, list):
        for br in branches:
            node = br.get("node") if isinstance(br, dict) else None
            if isinstance(node, dict) and isinstance(node.get("children"), list):
                return node["children"]
    return None


def add_barcode_capabilities(output_dir: str) -> int:
    """Wire the barcode feature set into a visual-product-search app.

    Idempotent post-generate pass (all insertions are id-guarded):
      1. /scan page (+ landing page when present) gets the barcode Card
         dispatching the barcode workflow with an auto-submitting scanner.
      2. History list items get a product thumbnail bound to
         ``{{item.imageUrl}}`` (renders nothing until a scan has an image).
      3. Detail-scoped PriceResult list dataSources get
         ``filter: {scanSessionId: "$routeId"}`` so each scan's results page
         shows only its own offers (the data-engine bridge resolves the
         sentinel from the route id).

    Returns the number of files touched. Never raises.
    """
    root = Path(output_dir)
    if _load_plan_archetype(root) != "visual-product-search":
        return 0
    wf_name = _find_workflow_name(root, ("barcode",))
    schemas = root / "src" / "schemas"
    if not schemas.is_dir():
        return 0

    history_nav = None
    for cand in ("history", "scans", "sessions"):
        if (schemas / f"{cand}.json").exists():
            history_nav = f"/{cand}"
            break

    touched = 0

    # 1. Barcode card on /scan + landing page.
    if wf_name:
        for fname in ("scan.json", "home.json", "index.json"):
            f = schemas / fname
            if not f.exists():
                continue
            try:
                schema = json.loads(f.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            # Semantic guard: any existing BarcodeScanner on the page means
            # the capability is already wired (hand-authored ids differ from
            # ours on reference apps like LensShop).
            if '"BarcodeScanner"' in json.dumps(schema):
                continue
            children = _first_children_list(schema)
            if children is None:
                continue
            children.append(_barcode_card(wf_name, history_nav))
            f.write_text(json.dumps(schema, indent=2), encoding="utf-8")
            touched += 1

    # 2. History thumbnails: first Repeat item template gets an Image bound
    #    to the session's imageUrl if the template has none.
    if history_nav:
        f = schemas / f"{history_nav.lstrip('/')}.json"
        try:
            schema = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            schema = None
        if schema and "history-item-thumb" not in json.dumps(schema):
            def _inject_thumb(node: object) -> bool:
                if isinstance(node, dict):
                    if node.get("type") == "Repeat":
                        blob = json.dumps(node)
                        if '"Image"' not in blob:
                            kids = node.get("children")
                            if isinstance(kids, list) and kids:
                                first = kids[0]
                                if isinstance(first, dict) and isinstance(first.get("children"), list):
                                    first["children"].insert(0, {
                                        "id": "history-item-thumb",
                                        "type": "Image",
                                        "props": {
                                            "src": "{{item.imageUrl}}",
                                            "alt": "Scanned product",
                                            "className": "w-full h-40 object-cover rounded-lg",
                                        },
                                    })
                                    return True
                        return False
                    for v in node.values():
                        if isinstance(v, (dict, list)) and _inject_thumb(v):
                            return True
                elif isinstance(node, list):
                    for c in node:
                        if _inject_thumb(c):
                            return True
                return False
            if _inject_thumb(schema):
                f.write_text(json.dumps(schema, indent=2), encoding="utf-8")
                touched += 1

    # 3. Scope detail-page offer lists to their scan via the $routeId sentinel.
    for f in schemas.rglob("*.json"):
        if "[id]" not in str(f.relative_to(schemas)):
            continue
        try:
            schema = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        srcs = (schema.get("props") or {}).get("dataSources") or schema.get("dataSources")
        if not isinstance(srcs, list):
            continue
        changed = False
        for src in srcs:
            if not isinstance(src, dict) or src.get("op") != "list":
                continue
            ent = re.sub(r"[^a-z0-9]", "", str(src.get("entity") or "").lower())
            if "price" in ent and not src.get("filter"):
                src["filter"] = {"scanSessionId": "$routeId"}
                changed = True
        if changed:
            f.write_text(json.dumps(schema, indent=2), encoding="utf-8")
            touched += 1

    return touched


# ── Results-page emitter (LensShop back-port, FIX-W9) ────────────────────

def _build_results_page_schema(
    scan_entity: str,
    price_entity: str,
    list_route: str,
    confirm_workflow: str | None,
    delete_workflow: str | None,
) -> dict[str, Any]:
    """Product-card results grid for ``/<scans>/[id]/results``.

    Mirrors the live-proven LensShop results.json: session header card with
    the scanned image, then Grid(3) → Repeat(priceResults) → Card with the
    offer image, retailer + price row and a real store link. Buttons carry
    the proven arg shapes ({{scanSession.id}}), so Discard hits the CRUD
    delete workflow whose WHERE binds {{id}}.
    """
    header_buttons: list[dict] = [
        {"type": "Button", "props": {"label": "Back", "variant": "ghost",
                                     "navigate": list_route}},
        {"type": "Button", "props": {"label": "Scan Another",
                                     "variant": "primary", "navigate": "/"}},
    ]
    action_buttons: list[dict] = []
    if confirm_workflow:
        action_buttons.append({
            "id": "mat_wf_confirmproduct", "type": "Button",
            "props": {"label": "Confirm Product", "variant": "primary",
                      "workflow": confirm_workflow,
                      "args": {"scanSessionId": "{{scanSession.id}}"}},
        })
    if delete_workflow:
        action_buttons.append({
            "id": "mat_wf_discardscan", "type": "Button",
            "props": {"label": "Discard Scan", "variant": "outline",
                      "workflow": delete_workflow,
                      "args": {"id": "{{scanSession.id}}"},
                      "onSuccess": {"toast": "Scan discarded",
                                    "navigate": list_route}},
        })

    children: list[dict] = [
        {
            "type": "Row",
            "props": {"justify": "between", "align": "center"},
            "children": [
                {"type": "Heading", "props": {"content": "Scan Results", "level": 1}},
                {"type": "Row", "props": {"gap": "tokens.spacing.2"},
                 "children": header_buttons},
            ],
        },
        {
            "type": "Card",
            "children": [{
                "type": "Row",
                "props": {"gap": "tokens.spacing.6", "align": "center"},
                "children": [
                    {"type": "Image", "props": {
                        "src": "/api/files/{{scanSession.imageUrl}}",
                        "alt": "Scanned product", "width": 140, "height": 140,
                        "className": "rounded-md object-cover"}},
                    {"type": "Stack", "props": {"gap": "tokens.spacing.2"},
                     "children": [
                         {"type": "Text", "props": {"content": "Identified product",
                                                    "variant": "muted"}},
                         {"type": "Heading", "props": {
                             "content": "{{priceResults[0].productName}}",
                             "level": 2}},
                         {"type": "Badge", "props": {
                             "label": "{{scanSession.status}}"}},
                     ]},
                ],
            }],
        },
        {"type": "Heading", "props": {"content": "Price Comparison", "level": 2}},
        {
            "type": "Grid",
            "props": {"columns": "3", "gap": "tokens.spacing.4"},
            "children": [{
                # `source` in props is the v1 Repeat convention Repeat.tsx reads.
                "type": "Repeat",
                "props": {"source": "priceResults"},
                "children": [{
                    "type": "Card",
                    "children": [{
                        "type": "Stack",
                        "props": {"gap": "tokens.spacing.3"},
                        "children": [
                            {"type": "Image", "props": {
                                "src": "{{item.imageUrl}}", "alt": "Offer",
                                "width": 240, "height": 160,
                                "className": "rounded-md object-cover w-full"}},
                            {"type": "Row",
                             "props": {"justify": "between", "align": "center"},
                             "children": [
                                 {"type": "Heading", "props": {
                                     "content": "{{item.retailerName}}",
                                     "level": 3}},
                                 {"type": "Text", "props": {
                                     "content": "{{item.price}} {{item.currency}}",
                                     "className": "font-semibold"}},
                             ]},
                            {"type": "Link", "props": {
                                "label": "View at store →",
                                "navigate": "{{item.productUrl}}",
                                "external": True}},
                        ],
                    }],
                }],
            }],
        },
    ]
    if action_buttons:
        children.append({
            "type": "Row",
            "props": {"gap": "tokens.spacing.3"},
            "children": action_buttons,
        })

    return {
        "schemaVersion": "2",
        "id": "visual-scan-results",
        "route": f"{list_route}/[id]/results",
        "layout": "main",
        "meta": {"title": "Scan Results",
                 "description": "Identified product and live retailer prices."},
        "dataSources": [
            {"name": "scanSession", "entity": scan_entity, "op": "get"},
            {"name": "priceResults", "entity": price_entity, "op": "list",
             "query": {"filters": {"scanSessionId": "$routeId"}},
             "sort": {"field": "price", "order": "asc"}},
        ],
        "root": {"type": "Stack", "props": {"gap": "tokens.spacing.6"},
                 "children": children},
    }


def ensure_results_page_for_visual_product_search(output_dir: str) -> int:
    """Post-gen: guarantee ``/<scans>/[id]/results`` exists as the proven
    product-card grid for visual-product-search apps.

    Idempotent: a page we already emitted (id ``visual-scan-results``) is
    rewritten in place; any OTHER existing results.json (LLM- or
    user-authored) is left alone. Returns files written (0 or 1).
    """
    root = Path(output_dir)
    if not root.exists() or _load_plan_archetype(root) != "visual-product-search":
        return 0

    scan_entity = _find_entity_name(root, ("scansession", "scan_session", "scan"))
    price_entity = _find_entity_name(
        root, ("pricelisting", "price_listing", "priceresult", "price_result"))
    if not scan_entity or not price_entity:
        return 0

    # Locate the scan entity's detail dir on disk (`src/schemas/<slug>/[id]`).
    schemas_dir = root / "src" / "schemas"
    detail_dir: Path | None = None
    if schemas_dir.is_dir():
        for d in sorted(schemas_dir.glob("*/[[]id[]]")):
            slug_norm = d.parent.name.lower().replace("-", "").replace("_", "")
            if "scan" in slug_norm:
                detail_dir = d
                break
    if detail_dir is None:
        detail_dir = schemas_dir / "scans" / "[id]"
    list_route = "/" + detail_dir.parent.name

    results_path = detail_dir / "results.json"
    if results_path.exists():
        try:
            existing = json.loads(results_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            existing = {}
        if existing.get("id") != "visual-scan-results":
            return 0  # authored by someone else — hands off

    confirm_wf = _find_workflow_name(root, ("confirmproduct",))
    delete_wf = _find_workflow_name(
        root, ("deletescansession", "deletescan"))

    schema = _build_results_page_schema(
        scan_entity, price_entity, list_route, confirm_wf, delete_wf)
    detail_dir.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
    logger.info(
        "[archetype-page-fix] wrote %s results page (scan=%s, prices=%s, "
        "confirm=%s, delete=%s)",
        schema["route"], scan_entity, price_entity, confirm_wf, delete_wf)
    return 1
