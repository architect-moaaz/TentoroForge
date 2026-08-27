"""Delivery gate — plan ↔ artifact symmetry, enforced (F1 + G2).

The pipeline has ~60 guards checking that artifacts are *internally*
valid, and (since REL-S2) critics checking the *plan* covers the brief.
What nothing checked until now is the reverse direction: **did the
artifacts deliver what the plan promised?** The live audit of the
reference app (2026-08-17) found exactly this class shipping to users:

- ``/admins`` in ``plan.pages`` → no schema, no route → 404 in prod
- ``ReprocessDocumentWorkflow`` (trigger: *button on detail page*) →
  no launcher anywhere in the UI
- nav-flow transition ``button:Back`` → no Back button in the source
  page schema
- plan says ``/`` is a *dashboard* → shipped page is an upload form
- brief signature moves (status rail, mono metadata strip) → authored,
  cached, never shipped

This module is the gate that turns each of those from a user discovery
into a build failure. Two rule families:

**F1 — functional symmetry** (severity ``error``):
  1. planned_page_missing   — plan page has no live route
  2. page_unreachable       — route exists but no nav/transition reaches it
  3. workflow_launcher_missing — UI-triggered workflow has no launcher
  4. transition_trigger_missing — nav-flow trigger element absent
  5. kind_mismatch          — shipped page shape ≠ plan kind (``warn``:
     kind inference is heuristic)

**G2 — design promise delivery** (severity ``warn`` for v1 — design
misses shouldn't block builds until the evidence catalog matures;
``info`` when a move kind has no evidence spec yet):
  6. signature_move_missing — brief move with known evidence spec absent
  7. signature_move_unverifiable — move kind not in the catalog

Pure deterministic reads — no LLM, no network. Inputs (all already
written by the pipeline):

  src/contracts/plan.json        — the promises
  src/contracts/nav-flow.json    — nav surface + transitions
  src/schemas/registry.ts        — authoritative live-route list
  src/schemas/**/*.json          — shipped page trees
  contracts/brief.json           — design promises (signature_moves)
  src/app/globals.css            — shipped design CSS

Gate mode via ``FORGE_DELIVERY_GATE`` = ``off`` | ``warn`` (default) |
``strict``. Warn writes ``contracts/delivery-report.json`` and logs;
strict additionally raises :class:`DeliveryGateError` when any
``error``-severity violation survives. (Non-binary flag — deliberately
NOT routed through flag_profile, per its binary-only contract.)
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

REPORT_REL = ("contracts", "delivery-report.json")

# Plan trigger prefixes that imply a USER-facing launcher must exist.
# db_change / schedule / cron / webhook fire without a user — no UI needed.
_UI_TRIGGER_PREFIXES = ("form_submit", "button", "manual", "user")

# Node types that count as a "button" for transition triggers.
_BUTTON_TYPES = {"Button", "IconButton", "AddToCart"}

# Node types whose presence identifies a page kind (heuristics — used
# for the warn-level kind_mismatch rule only).
_KIND_EVIDENCE: dict[str, set[str]] = {
    "form":      {"Form"},
    "list":      {"Table", "List", "Kanban", "CardGrid", "Repeat", "SearchInput"},
    "dashboard": {"MetricTile", "Chart", "Stat", "Gauge", "SplitArc", "Heatmap"},
    "detail":    {"DescriptionList", "Tabs"},
}


class DeliveryGateError(RuntimeError):
    """Raised in strict mode when error-severity violations survive."""

    def __init__(self, violations: list["Violation"]) -> None:
        self.violations = violations
        errs = [v for v in violations if v.severity == "error"]
        super().__init__(
            f"delivery gate failed: {len(errs)} undelivered promise(s) — "
            + "; ".join(f"[{v.rule}] {v.subject}" for v in errs[:5])
            + (" …" if len(errs) > 5 else "")
        )


@dataclass(frozen=True)
class Violation:
    rule: str                 # stable slug
    severity: str             # "error" | "warn" | "info"
    subject: str              # the promise that wasn't delivered
    msg: str                  # human-readable line
    repair_hint: str = ""     # which seam can fix it


# ══════════════════════════════════════════════════════════════════
# Artifact loaders — every one fail-open (missing artifact → empty)
# ══════════════════════════════════════════════════════════════════

def _load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _load_plan(root: Path) -> dict:
    return _load_json(root / "src" / "contracts" / "plan.json") or {}


def _load_nav_flow(root: Path) -> dict:
    return _load_json(root / "src" / "contracts" / "nav-flow.json") or {}


def _load_brief(root: Path) -> dict:
    return _load_json(root / "contracts" / "brief.json") or {}


def _load_registry_routes(root: Path) -> set[str]:
    """Parse the authoritative live-route keys out of registry.ts.

    The registry is emitted by schema_pipeline as
    ``"/route": () => import(...)`` lines — routes NOT in this map 404
    at runtime even when a schema file exists on disk (the audit's
    ``/admins`` case had neither, but the stale-action-contract case
    shows schemas and routes can disagree, so the registry is the
    ground truth we check against).
    """
    p = root / "src" / "schemas" / "registry.ts"
    if not p.is_file():
        return set()
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return set()
    return set(re.findall(r'"(/[^"]*)"\s*:\s*\(\)\s*=>', text))


def _load_page_schemas(root: Path) -> list[tuple[str, dict]]:
    """[(route, schema_doc)] for every page schema on disk."""
    sdir = root / "src" / "schemas"
    if not sdir.is_dir():
        return []
    out: list[tuple[str, dict]] = []
    for p in sorted(sdir.rglob("*.json")):
        if p.name in ("shell.json",):
            continue
        doc = _load_json(p)
        if not isinstance(doc, dict):
            continue
        route = doc.get("route")
        if not isinstance(route, str) or not route:
            # Derive from file layout: documents/search.json → /documents/search
            rel = p.relative_to(sdir).with_suffix("")
            route = "/" + "/".join(rel.parts)
            if route == "/index":
                route = "/"
        out.append((route, doc))
    return out


def _read_globals_css(root: Path) -> str:
    p = root / "src" / "app" / "globals.css"
    try:
        return p.read_text(encoding="utf-8") if p.is_file() else ""
    except Exception:  # noqa: BLE001
        return ""


# ══════════════════════════════════════════════════════════════════
# Shared helpers
# ══════════════════════════════════════════════════════════════════

def _norm_route(r: str) -> str:
    """``/x/[id]`` and ``/x/{id}`` collapse; trailing slash dropped."""
    return (r or "").replace("[", "{").replace("]", "}").rstrip("/") or "/"


def _canon(s: str) -> str:
    """Workflow-name canonicalization: lowercase alnum, 'workflow'
    suffix stripped — ``ReprocessDocumentWorkflow`` ≡
    ``reprocess-document``."""
    out = re.sub(r"[^a-z0-9]", "", str(s or "").lower())
    return out[:-8] if out.endswith("workflow") else out


def _walk(node: Any) -> Iterable[dict]:
    if isinstance(node, dict):
        yield node
        for v in node.values():
            if isinstance(v, (dict, list)):
                yield from _walk(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _node_type(node: dict) -> str:
    return str(node.get("component") or node.get("type") or "")


def _node_label(node: dict) -> str:
    props = node.get("props") if isinstance(node.get("props"), dict) else {}
    for key in ("label", "text", "content", "title"):
        v = props.get(key) or node.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _workflow_refs_in(schema: dict) -> set[str]:
    """Every workflow name referenced anywhere in a page tree, canon'd."""
    refs: set[str] = set()
    for node in _walk(schema):
        for key in ("workflow", "workflowId", "workflow_ref", "workflowName"):
            v = node.get(key)
            if isinstance(v, str) and v.strip():
                refs.add(_canon(v))
    return refs


# ══════════════════════════════════════════════════════════════════
# F1 rules
# ══════════════════════════════════════════════════════════════════

def check_planned_pages(
    plan: dict, registry_routes: set[str], nav_flow: dict,
) -> list[Violation]:
    """Rule 1+2: every plan page must be live and reachable."""
    out: list[Violation] = []
    live = {_norm_route(r) for r in registry_routes}

    nav_routes: set[str] = set()
    for entry in nav_flow.get("pages") or []:
        if isinstance(entry, dict) and entry.get("route"):
            nav_routes.add(_norm_route(str(entry["route"])))
    # Transition targets are reachable even without a nav entry.
    page_by_id = {
        str(e.get("id")): _norm_route(str(e.get("route") or ""))
        for e in (nav_flow.get("pages") or []) if isinstance(e, dict)
    }
    for t in nav_flow.get("transitions") or []:
        if isinstance(t, dict) and t.get("to") in page_by_id:
            nav_routes.add(page_by_id[str(t["to"])])

    for pg in plan.get("pages") or []:
        if not isinstance(pg, dict):
            continue
        route = pg.get("route")
        if not isinstance(route, str) or not route:
            continue
        if pg.get("hidden") is True:
            continue
        norm = _norm_route(route)
        if norm not in live:
            out.append(Violation(
                rule="planned_page_missing", severity="error", subject=route,
                msg=f"plan.pages declares {route!r} but the route registry has no "
                    "entry — the page 404s in the shipped app",
                repair_hint="add_page seam (emit schema + registry entry) or drop from plan via plan writeback",
            ))
        elif norm not in nav_routes and norm != "/":
            out.append(Violation(
                rule="page_unreachable", severity="error", subject=route,
                msg=f"{route!r} is live but no nav entry or transition reaches it — "
                    "users can only find it by typing the URL",
                repair_hint="sync_shell_menu / add nav-flow entry",
            ))
    return out


def check_workflow_launchers(
    plan: dict, schemas: list[tuple[str, dict]],
) -> list[Violation]:
    """Rule 3: every UI-triggered plan workflow has a rendered launcher."""
    shipped_refs: set[str] = set()
    for _route, doc in schemas:
        shipped_refs |= _workflow_refs_in(doc)

    out: list[Violation] = []
    for wf in plan.get("workflows") or []:
        if not isinstance(wf, dict):
            continue
        name = wf.get("name")
        trigger = wf.get("trigger")
        trigger_str = (
            trigger if isinstance(trigger, str)
            else str((trigger or {}).get("type") or "") if isinstance(trigger, dict)
            else ""
        ).strip().lower()
        if not name or not trigger_str.startswith(_UI_TRIGGER_PREFIXES):
            continue
        if _canon(name) not in shipped_refs:
            out.append(Violation(
                rule="workflow_launcher_missing", severity="error", subject=str(name),
                msg=f"workflow {name!r} (trigger: {trigger_str!r}) has no launcher "
                    "in any shipped page — the feature is unreachable",
                repair_hint="workflow_launch_forms (form triggers) / transition "
                            "materializer Button injection (button triggers)",
            ))
    return out


def check_transition_triggers(
    nav_flow: dict, schemas: list[tuple[str, dict]],
) -> list[Violation]:
    """Rule 4: nav-flow transition triggers must have their element."""
    schema_by_route = {_norm_route(r): doc for r, doc in schemas}
    page_route_by_id = {
        str(e.get("id")): _norm_route(str(e.get("route") or ""))
        for e in (nav_flow.get("pages") or []) if isinstance(e, dict)
    }

    out: list[Violation] = []
    for t in nav_flow.get("transitions") or []:
        if not isinstance(t, dict):
            continue
        trigger = str(t.get("trigger") or "")
        src_route = page_route_by_id.get(str(t.get("from")))
        if not trigger or not src_route:
            continue
        doc = schema_by_route.get(src_route)
        if doc is None:
            continue  # page-missing rule already covers this route

        if trigger.startswith("button:"):
            wanted = trigger.split(":", 1)[1].strip().lower()
            found = any(
                _node_type(n) in _BUTTON_TYPES
                and _node_label(n).lower() == wanted
                for n in _walk(doc)
            )
            if not found:
                out.append(Violation(
                    rule="transition_trigger_missing", severity="error",
                    subject=f"{src_route} → {trigger}",
                    msg=f"nav-flow declares transition {t.get('id')!r} triggered by "
                        f"button {wanted!r} on {src_route!r} — no such button in the "
                        "page schema",
                    repair_hint="transition materializer: inject Button with the "
                                "declared label + navigate target",
                ))
        elif trigger.startswith("submit:"):
            found = any(_node_type(n) == "Form" for n in _walk(doc))
            if not found:
                out.append(Violation(
                    rule="transition_trigger_missing", severity="error",
                    subject=f"{src_route} → {trigger}",
                    msg=f"transition {t.get('id')!r} fires on form submit but "
                        f"{src_route!r} contains no Form",
                    repair_hint="form_scaffold on the source page",
                ))
    return out


def check_page_kinds(
    plan: dict, schemas: list[tuple[str, dict]],
) -> list[Violation]:
    """Rule 5 (warn): shipped page shape should match its plan kind."""
    schema_by_route = {_norm_route(r): doc for r, doc in schemas}
    out: list[Violation] = []
    for pg in plan.get("pages") or []:
        if not isinstance(pg, dict):
            continue
        route = pg.get("route")
        kind = str(pg.get("kind") or pg.get("type") or "").lower()
        if not route or kind not in _KIND_EVIDENCE:
            continue
        doc = schema_by_route.get(_norm_route(str(route)))
        if doc is None:
            continue  # covered by planned_page_missing
        types = {_node_type(n) for n in _walk(doc)}
        if "Redirect" in types:
            # Route-dedup collapsed this route into an alias of another
            # page — the Redirect stub intentionally carries no kind
            # evidence of its own. Judging it against the plan kind is a
            # false positive (fleet Phase-0: 21 of these warns).
            continue
        if not (types & _KIND_EVIDENCE[kind]):
            # What does it look like instead? Best-effort diagnosis.
            actual = next(
                (k for k, ev in _KIND_EVIDENCE.items() if types & ev), "unknown",
            )
            out.append(Violation(
                rule="kind_mismatch", severity="warn", subject=str(route),
                msg=f"plan declares {route!r} as {kind!r} but the shipped page "
                    f"looks like {actual!r} — plan and app disagree about what "
                    "this page is",
                repair_hint="plan writeback (if the shipped shape is right) or "
                            "recompose the page (if the plan is right)",
            ))
    return out


# ══════════════════════════════════════════════════════════════════
# G2 — signature-move evidence
# ══════════════════════════════════════════════════════════════════

# kind-substring → list of (artifact, regex). ANY match = move shipped.
# artifact: "schemas" = concatenated page-schema JSON text,
#           "css"     = globals.css text.
# The catalog grows as move kinds recur across briefs; unknown kinds
# report as unverifiable (info) rather than silently passing.
_MOVE_EVIDENCE: list[tuple[str, list[tuple[str, str]]]] = [
    ("status_rail", [
        ("css", r"status-rail|data-status[^_a-z]|border-left:\s*[234]px"),
        ("schemas", r"statusRail|status-rail|data-status"),
    ]),
    ("metadata_strip", [
        ("css", r"metadata-strip|file-manifest|manifest"),
        ("schemas", r"metadata[_-]?strip|manifest"),
    ]),
    ("monospaced_metadata", [           # alias spelling of the same idea
        ("css", r"metadata-strip|manifest"),
        ("schemas", r"metadata[_-]?strip|manifest"),
    ]),
    ("ordinal", [                        # numbered section markers
        ("css", r"section-ordinal|counter\("),
        ("schemas", r"ordinal"),
    ]),
    ("accent_underline", [
        ("css", r"underline-accent|border-bottom:\s*[23]px solid var\(--"),
    ]),
]


def check_signature_moves(
    brief: dict, schemas: list[tuple[str, dict]], css_text: str,
) -> list[Violation]:
    """Rules 6+7: every brief signature move ships, or the report says
    so. Moves with no evidence spec are 'unverifiable' — visible in the
    report so the catalog can grow, never silently green."""
    moves = brief.get("signature_moves")
    if not isinstance(moves, list) or not moves:
        return []
    schemas_text = " ".join(json.dumps(doc) for _r, doc in schemas)
    corpus = {"schemas": schemas_text, "css": css_text}

    out: list[Violation] = []
    for move in moves:
        if not isinstance(move, dict):
            continue
        kind = str(move.get("kind") or "").lower()
        if not kind:
            continue
        specs = [
            checks for key, checks in _MOVE_EVIDENCE if key in kind
        ]
        if not specs:
            out.append(Violation(
                rule="signature_move_unverifiable", severity="info", subject=kind,
                msg=f"brief signature move {kind!r} has no evidence spec in the "
                    "delivery-gate catalog — shipped state unknown",
                repair_hint="add an evidence entry to _MOVE_EVIDENCE",
            ))
            continue
        shipped = any(
            re.search(pattern, corpus.get(artifact, ""), re.IGNORECASE)
            for checks in specs
            for artifact, pattern in checks
        )
        if not shipped:
            detail = str(move.get("detail") or "")[:120]
            out.append(Violation(
                rule="signature_move_missing", severity="warn", subject=kind,
                msg=f"brief promises {kind!r} ({detail}…) — no evidence in "
                    "shipped schemas or CSS",
                repair_hint="design_language/composer must materialize the move, "
                            "or drop it from the brief",
            ))
    return out


# ══════════════════════════════════════════════════════════════════
# Gate entry point
# ══════════════════════════════════════════════════════════════════

def check_dashboard_substance(
    root: Path, schemas: list[tuple[str, dict]],
) -> list[Violation]:
    """G6 — a dashboard has to actually say something.

    Dashboards were the one page kind no gate judged: ``page_signature``
    needs an entity to name a job, a dashboard has none, so the anatomy pass
    skipped every one of them. Across the 223-app corpus that let 54 of 125
    dashboards ship below the floor — 43 with no chart at all, and two of the
    thirty most recent with no KPIs, no chart and no activity surface.

    The rules live in ``dashboard_anatomy`` rather than here, because
    ``page_anatomy`` reports the same findings and two copies of "what a
    dashboard needs" is exactly the drift this codebase keeps paying for.
    """
    from services.dashboard_anatomy import dashboard_findings

    registry = _load_json(root / "contracts" / "resource-registry.json")
    out: list[Violation] = []
    # An app can carry more than one schema file claiming the same dashboard
    # route (index.json + home.json). Judging each is correct; reporting the
    # same rule twice for one route is just noise.
    seen: set[tuple[str, str]] = set()
    for route, doc in schemas:
        for f in dashboard_findings(route, doc, registry):
            key = (f["rule"], _norm_route(route))
            if key in seen:
                continue
            seen.add(key)
            out.append(Violation(
                rule=f["rule"], severity=f["severity"], subject=route,
                msg=f["detail"],
                repair_hint="dashboard_page_composer / dashboard_completeness_guard",
            ))
    return out


def check_ia_shape(
    plan: dict,
    nav_flow: dict,
    schemas: list[tuple[str, dict]],
    shell: dict | None,
) -> list[Violation]:
    """F3 — the IA must put the right thing in the right place, completely.

    * ``join_entity_in_menu``  (error): a pure-join entity (SessionSpeaker)
      surfaces as a shell menu destination — DB detail leaking into IA.
    * ``menu_missing_section`` (error): a top-level shell page exists in
      nav-flow but no menu button/group points at its top route — the
      section is invisible (qeqorfii: Organizers, Tasks).
    * ``junk_create_page``     (error): a create form under a non-entity
      stem (``/home/new`` — a "create" for the dashboard).
    """
    from services.entity_shape import join_route_slugs
    from services.ensure_edit_routes import _NON_ENTITY_STEMS

    out: list[Violation] = []
    joins = join_route_slugs(plan)

    # Every route a shell menu can reach: props.groups entries + literal
    # nav Buttons (both menu shapes exist across frames).
    menu_routes: set[str] = set()
    if isinstance(shell, dict):
        for node in _walk(shell):
            p = node.get("props") if isinstance(node.get("props"), dict) else {}
            if isinstance(p.get("groups"), list):
                for g in p["groups"]:
                    if isinstance(g, dict) and isinstance(g.get("route"), str):
                        menu_routes.add(g["route"])
                    for s in (g.get("items") or []) if isinstance(g, dict) else []:
                        if isinstance(s, dict) and isinstance(s.get("route"), str):
                            menu_routes.add(s["route"])
            if node.get("type") == "Button" and isinstance(p.get("navigate"), str):
                menu_routes.add(p["navigate"])

    for r in menu_routes:
        slug = r.strip("/").split("/", 1)[0] if r != "/" else "/"
        if slug in joins:
            out.append(Violation(
                rule="join_entity_in_menu", severity="error", subject=r,
                msg="menu links a pure-join entity's route — manage the "
                    "relationship inline on the parent detail page",
                repair_hint="sync_shell_menu (join filter) / remove menu entry",
            ))

    # Section completeness: every non-auth, shell:true, non-dynamic,
    # non-join top-level nav page must be reachable from the menu.
    auth = set(nav_flow.get("auth_routes") or []) | {"/login", "/signup"}
    menu_tops = {("/" + r.strip("/").split("/", 1)[0]) if r != "/" else "/"
                 for r in menu_routes}
    seen: set[str] = set()
    for p in nav_flow.get("pages") or []:
        if not isinstance(p, dict) or p.get("shell") is False:
            continue
        r = p.get("route")
        if not isinstance(r, str) or "[" in r or r in auth or r == "/":
            continue
        if r.count("/") != 1:
            continue  # only top-level landing pages are sections
        slug = r.strip("/")
        if slug in joins or r in seen:
            continue
        seen.add(r)
        if menu_routes and r not in menu_tops:
            out.append(Violation(
                rule="menu_missing_section", severity="error", subject=r,
                msg="top-level page exists but no shell menu entry reaches it",
                repair_hint="sync_shell_menu",
            ))

    for route, schema in schemas:
        nr = _norm_route(route)
        m = re.match(r"^/([a-z0-9-]+)/new$", nr or "")
        if m and m.group(1) in _NON_ENTITY_STEMS:
            out.append(Violation(
                rule="junk_create_page", severity="error", subject=nr,
                msg="create form under a non-entity page — nothing to create",
                repair_hint="remove_junk_create_pages",
            ))
    return out


def _security_family(root: Path) -> list[Violation]:
    """Rule family ``security`` — folds the deterministic security
    gate's STATIC results (:mod:`services.security_gate`) into this
    report. Static-only here (no ``base_url`` → no live probes); the
    security gate also writes its own ``security-report.json``.
    Non-fatal: a crashing security gate never breaks the delivery gate.
    """
    try:
        from services.security_gate import run_security_gate

        sec = run_security_gate(str(root))
        out: list[Violation] = []
        for f in sec.get("errors") or []:
            out.append(Violation(
                rule=f"security_{f.get('rule', 'finding')}", severity="error",
                subject=str(f.get("file") or f.get("slug") or f.get("rule") or ""),
                msg=str(f.get("detail") or ""),
                repair_hint="security_gate — see security-report.json",
            ))
        for f in sec.get("warnings") or []:
            out.append(Violation(
                rule=f"security_{f.get('rule', 'finding')}", severity="warn",
                subject=str(f.get("file") or f.get("slug") or f.get("rule") or ""),
                msg=str(f.get("detail") or ""),
                repair_hint="security_gate — see security-report.json",
            ))
        return out
    except Exception:  # noqa: BLE001
        logger.exception("[delivery-gate] security family failed (non-fatal)")
        return []


def gate_mode() -> str:
    """off | warn | strict — non-binary, so read directly (not via
    flag_profile, whose contract is binary gates only)."""
    raw = (os.environ.get("FORGE_DELIVERY_GATE") or "").strip().lower()
    return raw if raw in ("off", "warn", "strict") else "warn"


# ══════════════════════════════════════════════════════════════════
# Rule: shipped density vs the montage's declared bar
# ══════════════════════════════════════════════════════════════════

# What counts as "how much is on this page", per screen kind. Only the
# things that can be counted honestly off a schema — a card-list carries
# no columns, and inventing a measure for it would manufacture findings.
_DENSITY_PROBES = {
    "collection": ("columns_target", "columns"),
    "dashboard": ("kpis_target", "kpi tiles"),
}

# The planner and the montage layer name the same screens differently:
# the plan says `list` / `detail`, the maquettes say `collection` /
# `record`. Keying the probes on the montage words alone made every
# plan-typed `list` invisible here — on x4fcmdyi that hid eight tables
# shipping under the seven-column bar, and only the dashboard (the one
# word both layers spell the same) ever produced a finding.
_KIND_SYNONYMS = {
    "list": "collection", "index": "collection", "table": "collection",
    "collection": "collection",
    "detail": "record", "record": "record", "profile": "record",
    "dashboard": "dashboard", "overview": "dashboard",
    "home": "dashboard", "admin": "dashboard",
}


def _montage_kind(plan_kind: str) -> str:
    """Plan page type → the montage's name for that screen kind, or ""."""
    return _KIND_SYNONYMS.get(str(plan_kind or "").strip().lower(), "")


def _count_table_columns(doc: dict) -> Optional[int]:
    """Columns on the widest Table, or None when the page carries no table."""
    counts = []
    for node in _walk(doc):
        if _node_type(node) != "Table":
            continue
        cols = (node.get("props") or {}).get("columns")
        if isinstance(cols, list):
            counts.append(len(cols))
    return max(counts) if counts else None


def _count_metric_tiles(doc: dict) -> Optional[int]:
    n = sum(1 for node in _walk(doc) if _node_type(node) == "MetricTile")
    return n or None


def check_composition_targets(
    targets: dict, schemas: list[tuple[str, dict]], kind_by_route: dict,
) -> list[Violation]:
    """Rule (warn): a page thinner than the reference montage's bar.

    Until the montage existed, nothing in the system had an opinion about
    how MUCH belonged on a page — the author listed whatever columns the
    entity happened to have, so density was arithmetic on the schema rather
    than a decision anyone made. This is the read-back that makes the
    declared bar mean something.

    ``warn`` on purpose. An entity with five columns cannot honour a bar of
    eight, and falling short for that reason is legitimate. Making the gap
    visible is the point; blocking on it would punish honest data.
    """
    if not targets:
        return []                     # no montage — nobody set a bar

    out: list[Violation] = []
    for route, doc in schemas:
        kind = _montage_kind(kind_by_route.get(_norm_route(str(route))) or "")
        probe = _DENSITY_PROBES.get(kind)
        if probe is None:
            continue
        field, noun = probe
        want = (targets.get(kind) or {}).get(field)
        if not isinstance(want, int):
            continue

        got = (_count_table_columns(doc) if kind == "collection"
               else _count_metric_tiles(doc))
        if got is None or got >= want:
            continue                  # unmeasurable, or the bar was met

        out.append(Violation(
            rule=f"density_below_reference_{field.replace('_target', '')}",
            severity="warn", subject=str(route),
            msg=(f"{route!r} ships {got} {noun}; the design reference sets "
                 f"the bar at {want}. Either the entity cannot carry more, "
                 f"or the page is thinner than the montage it was built from."),
            repair_hint=("re-author the maquette for this route with the "
                         "reference TARGET in the prompt "
                         "(plan_finalize.author_*_maquettes_if_enabled), or "
                         "widen the entity if the columns simply don't exist"),
        ))
    return out


def run_delivery_gate(output_dir: str | Path, *, mode: str | None = None) -> dict:
    """Run every rule, write ``contracts/delivery-report.json``, return
    the report. ``strict`` raises :class:`DeliveryGateError` when
    error-severity violations survive. Never raises for any other
    reason — a broken gate must not break generation.
    """
    m = mode or gate_mode()
    if m == "off":
        return {"skipped": True, "mode": "off"}

    root = Path(output_dir)
    try:
        plan = _load_plan(root)
        nav_flow = _load_nav_flow(root)
        registry_routes = _load_registry_routes(root)
        schemas = _load_page_schemas(root)
        brief = _load_brief(root)
        css_text = _read_globals_css(root)

        violations: list[Violation] = []
        violations += check_planned_pages(plan, registry_routes, nav_flow)
        violations += check_workflow_launchers(plan, schemas)
        violations += check_transition_triggers(nav_flow, schemas)
        violations += check_page_kinds(plan, schemas)
        violations += check_signature_moves(brief, schemas, css_text)
        shell = _load_json(root / "src" / "schemas" / "shell.json")
        violations += check_ia_shape(plan, nav_flow, schemas,
                                     shell if isinstance(shell, dict) else None)
        violations += check_dashboard_substance(root, schemas)
        violations += _security_family(root)
        # Density vs the montage's declared bar. Reads the same typed
        # targets the maquette authors were given, so author and gate
        # cannot drift apart.
        try:
            from services.montage_composition import composition_targets
            _kind_by_route = {
                _norm_route(str(pg.get("route"))):
                    str(pg.get("kind") or pg.get("type") or "").lower()
                for pg in (plan.get("pages") or [])
                if isinstance(pg, dict) and pg.get("route")
            }
            violations += check_composition_targets(
                composition_targets(str(root)), schemas, _kind_by_route)
        except Exception as _ct_exc:  # noqa: BLE001 — a gate must not break gen
            logger.debug("[gate] composition-target rule skipped: %s", _ct_exc)

        summary = {"error": 0, "warn": 0, "info": 0}
        for v in violations:
            summary[v.severity] = summary.get(v.severity, 0) + 1

        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": m,
            "violations": [asdict(v) for v in violations],
            "summary": summary,
        }
        try:
            p = root.joinpath(*REPORT_REL)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(report, indent=2), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.warning("[delivery-gate] report write failed: %s", exc)

        if summary["error"] or summary["warn"]:
            logger.warning(
                "[delivery-gate] %d error(s), %d warning(s) — see delivery-report.json",
                summary["error"], summary["warn"],
            )
        if m == "strict" and summary["error"]:
            raise DeliveryGateError(violations)
        return report
    except DeliveryGateError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("[delivery-gate] internal error (degrading to no-op)")
        return {"error": str(exc), "mode": m}


__all__ = [
    "DeliveryGateError",
    "Violation",
    "check_page_kinds",
    "check_planned_pages",
    "check_signature_moves",
    "check_transition_triggers",
    "check_workflow_launchers",
    "check_composition_targets",
    "gate_mode",
    "run_delivery_gate",
]
