"""Requirement-fidelity critic — Slice 3 of requirement-as-central-piece.

Closes the loop: user asks for X in the prompt → parser writes it to
``requirement.json.parsed_directives`` → composers author against it →
this critic checks whether X actually SHIPPED on the page.

Runs as a post-generate pass. Emits ``src/contracts/requirement-fidelity.json``
with one verdict per directive:

    {
      "generated_at":     "...",
      "verdicts": [
        {
          "directive":  "visual_preset",
          "asked":      "trust-navy",
          "status":     "ok" | "missing" | "partial",
          "evidence":   "design-spec.visual_lock.preset_name = trust-navy",
          "auto_repair": null | "<label>"
        },
        ...
      ],
      "summary": {"ok": N, "missing": M, "partial": K}
    }

Six directive types checked today (mirroring the parser):

  ▸ visual_preset          → design-spec.visual_lock.preset_name
  ▸ archetype_vocabulary   → plan.archetype
  ▸ row_click_target       → Table.rowHref on the target collection page
  ▸ filter_dimensions      → FilterBar chips on the target collection page
  ▸ gauges                 → Gauge / SplitArc widgets on the dashboard
  ▸ chart_types            → Chart nodes with matching chartType

Amendments are merged into the check — the most recent value for each
directive key wins (later amendments override earlier ones, matching
Smith's "amendments override" instruction).

Never raises. Missing / unreadable inputs return an empty verdict list.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


REPORT_REL = ("src", "contracts", "requirement-fidelity.json")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug_from_route(route: str) -> str:
    """``/subscriptions/[id]`` → ``subscriptions``. First non-param segment."""
    parts = [p for p in route.split("/") if p and not p.startswith("[")]
    return parts[0] if parts else ""


def _walk(node: Any) -> Iterable[dict]:
    if isinstance(node, dict):
        yield node
        for c in node.get("children") or []:
            yield from _walk(c)
    elif isinstance(node, list):
        for c in node:
            yield from _walk(c)


def _merge_directives(requirement: dict) -> dict[str, Any]:
    """Fold amendments into the base directives — most recent wins.

    Original ``parsed_directives`` is the baseline; every amendment's
    ``parsed_directives`` overlays it in append order. This is the
    canonical "what does the user CURRENTLY want" view.
    """
    if not isinstance(requirement, dict):
        return {}
    out: dict[str, Any] = dict(requirement.get("parsed_directives") or {})
    for a in requirement.get("amendments") or []:
        if not isinstance(a, dict):
            continue
        parsed = a.get("parsed_directives") or {}
        if isinstance(parsed, dict):
            out.update(parsed)
    return out


# ── Per-directive checks ────────────────────────────────────────────────

def _check_visual_preset(asked: str, output_dir: Path) -> dict:
    """design-spec.visual_lock.preset_name must match."""
    spec_path = output_dir / "src" / "contracts" / "design-spec.json"
    got = ""
    if spec_path.is_file():
        try:
            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            vl = spec.get("visual_lock")
            if isinstance(vl, dict):
                got = str(vl.get("preset_name") or "")
        except Exception:  # noqa: BLE001
            pass
    ok = bool(asked) and got.lower() == str(asked).lower()
    return {
        "directive": "visual_preset",
        "asked": asked,
        "status": "ok" if ok else "missing",
        "evidence": f"design-spec.visual_lock.preset_name = {got or '(unset)'}",
        "auto_repair": None if ok else "backfill visual_lock.preset_name from requirement",
    }


def _check_archetype_vocabulary(asked: str, plan: dict) -> dict:
    got = str(plan.get("archetype") or plan.get("app_archetype") or "")
    ok = bool(asked) and got.lower() == str(asked).lower()
    return {
        "directive": "archetype_vocabulary",
        "asked": asked,
        "status": "ok" if ok else "missing",
        "evidence": f"plan.archetype = {got or '(unset)'}",
        "auto_repair": None if ok else "stamp plan.archetype from requirement",
    }


def _load_page_schemas(output_dir: Path) -> list[tuple[str, dict]]:
    """Return [(route, schema)] for every page schema on disk."""
    out: list[tuple[str, dict]] = []
    sdir = output_dir / "src" / "schemas"
    if not sdir.is_dir():
        return out
    for p in sorted(sdir.rglob("*.json")):
        if p.name in ("shell.json", "nav-flow.json"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        route = str(data.get("route") or "")
        if route:
            out.append((route, data))
    return out


def _check_row_click(target: str, schemas: list[tuple[str, dict]]) -> dict:
    """Any Table on the target's slug's collection page must have rowHref
    matching the target (template ``{id}`` accepted for ``[id]``)."""
    slug = _slug_from_route(target)
    expected_href = target.replace("[id]", "{id}")
    for route, schema in schemas:
        if _slug_from_route(route) != slug:
            continue
        if "/[" in route or "/new" in route or "/edit" in route:
            continue
        for node in _walk(schema.get("root")):
            if node.get("type") == "Table":
                href = (node.get("props") or {}).get("rowHref") or ""
                if href == expected_href:
                    return {
                        "directive": "row_click_target",
                        "asked": target,
                        "status": "ok",
                        "evidence": f"Table.rowHref on {route} = {href}",
                        "auto_repair": None,
                    }
    return {
        "directive": "row_click_target",
        "asked": target,
        "status": "missing",
        "evidence": f"no Table on the /{slug} collection page has rowHref = {expected_href}",
        "auto_repair": "apply_hints_to_pages",
    }


def _check_filter_dimensions(asked: list[str], schemas: list[tuple[str, dict]]) -> dict:
    """A FilterBar with chip labels covering the asked dimensions should
    exist on at least one collection page. Partial match = some but not
    all dimensions present."""
    asked_norm = {str(d).strip().lower() for d in asked if str(d).strip()}
    if not asked_norm:
        return {
            "directive": "filter_dimensions",
            "asked": asked,
            "status": "ok",
            "evidence": "no dimensions requested",
            "auto_repair": None,
        }
    best = {"route": "", "hit": set(), "total": 0}
    for route, schema in schemas:
        if "/[" in route or "/new" in route or "/edit" in route:
            continue
        for node in _walk(schema.get("root")):
            if node.get("type") != "FilterBar":
                continue
            chips = (node.get("props") or {}).get("chips") or []
            if not isinstance(chips, list):
                continue
            labels = {str(c.get("label") or "").strip().lower()
                      for c in chips if isinstance(c, dict)}
            hit = asked_norm & labels
            if len(hit) > len(best["hit"]):
                best = {"route": route, "hit": hit, "total": len(chips)}
    if best["hit"] == asked_norm:
        return {
            "directive": "filter_dimensions",
            "asked": asked,
            "status": "ok",
            "evidence": f"FilterBar on {best['route']} covers all {len(asked_norm)} dimensions",
            "auto_repair": None,
        }
    if best["hit"]:
        missing = sorted(asked_norm - best["hit"])
        return {
            "directive": "filter_dimensions",
            "asked": asked,
            "status": "partial",
            "evidence": f"FilterBar on {best['route']} has {sorted(best['hit'])}, missing {missing}",
            "auto_repair": "apply_hints_to_pages",
        }
    return {
        "directive": "filter_dimensions",
        "asked": asked,
        "status": "missing",
        "evidence": f"no FilterBar found with dimensions from {sorted(asked_norm)}",
        "auto_repair": "apply_hints_to_pages",
    }


def _check_gauges(asked: list[dict], schemas: list[tuple[str, dict]]) -> dict:
    """Gauge / SplitArc widgets with labels matching the asked gauges
    should exist on the dashboard (route = ``/`` typically)."""
    asked_labels = [str(g.get("label") or "").strip().lower()
                     for g in asked if isinstance(g, dict) and g.get("label")]
    asked_labels = [l for l in asked_labels if l]
    if not asked_labels:
        return {
            "directive": "gauges",
            "asked": asked,
            "status": "ok",
            "evidence": "no gauges requested",
            "auto_repair": None,
        }
    found_labels: set[str] = set()
    dashboard_route = ""
    for route, schema in schemas:
        # Dashboards live at / typically but check every page — a gauge
        # anywhere counts.
        for node in _walk(schema.get("root")):
            t = node.get("type")
            if t not in ("Gauge", "SplitArc"):
                continue
            lbl = str((node.get("props") or {}).get("label") or "").strip().lower()
            if lbl:
                found_labels.add(lbl)
                if route == "/":
                    dashboard_route = route
    # Fuzzy match: an asked label is satisfied if a shipped label contains
    # or is contained by it (handles "Net Revenue Retention" vs "NRR").
    def _match(asked_l: str) -> bool:
        return any(asked_l in f or f in asked_l for f in found_labels)
    hits = [l for l in asked_labels if _match(l)]
    if len(hits) == len(asked_labels):
        return {
            "directive": "gauges",
            "asked": asked,
            "status": "ok",
            "evidence": f"all {len(asked_labels)} gauge(s) present on shipped pages",
            "auto_repair": None,
        }
    missing = [l for l in asked_labels if not _match(l)]
    return {
        "directive": "gauges",
        "asked": asked,
        "status": "partial" if hits else "missing",
        "evidence": f"present: {hits}, missing: {missing}",
        "auto_repair": "dashboard-maquette top-up",
    }


_CHART_STOPWORDS = {
    "the", "a", "an", "of", "for", "and", "or", "by", "over", "with",
    "in", "on", "to", "vs", "per", "chart", "graph", "trend", "trends",
    "last", "next", "monthly", "weekly", "daily", "yearly", "month",
    "months", "week", "weeks", "day", "days", "year", "years",
}


def _chart_tokens(text: str) -> set[str]:
    """Bag-of-words for fuzzy chart-title match. Splits camelCase,
    strips stopwords + short tokens. ``MRR Waterfall — 12 Months`` →
    ``{"mrr", "waterfall"}``."""
    if not text:
        return set()
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", str(text))
    parts = re.split(r"[^a-zA-Z0-9]+", spaced.lower())
    return {p for p in parts
            if p and len(p) > 1 and p not in _CHART_STOPWORDS
            and not p.isdigit()}


def _check_chart_types(asked: list[dict], schemas: list[tuple[str, dict]]) -> dict:
    """Each asked ``{title, chartType}`` should map to a shipped Chart
    with the matching chartType. Title matching is token-overlap: any
    non-stopword shared between asked title and shipped nearby text
    (Heading, series title) counts. ``"MRR trend"`` matches a shipped
    ``"MRR Waterfall — 12 Months"`` (both share the token ``mrr``)."""
    asked_norm = [
        (str(x.get("title") or "").strip().lower(),
         str(x.get("chartType") or "").strip().lower())
        for x in asked if isinstance(x, dict)
    ]
    asked_norm = [(t, k) for t, k in asked_norm if t and k]
    if not asked_norm:
        return {
            "directive": "chart_types",
            "asked": asked,
            "status": "ok",
            "evidence": "no chart types requested",
            "auto_repair": None,
        }
    shipped: list[tuple[set[str], str]] = []  # (nearby_tokens, chartType)
    for _route, schema in schemas:
        last_heading = ""
        for node in _walk(schema.get("root")):
            t = node.get("type")
            if t == "Heading":
                last_heading = str((node.get("props") or {}).get("content") or "").strip()
            elif t == "Chart":
                props = node.get("props") or {}
                ct = str(props.get("chartType") or "").strip().lower()
                if not ct:
                    continue
                # Chart's own title / series names are stronger evidence
                # than the last-seen heading. Blend all three.
                own_title = str(props.get("title") or "")
                series_titles = " ".join(
                    str(s.get("name") or s.get("label") or "")
                    for s in (props.get("series") or [])
                    if isinstance(s, dict)
                )
                blob = " ".join([last_heading, own_title, series_titles]).strip()
                shipped.append((_chart_tokens(blob), ct))
    hits: list[str] = []
    misses: list[str] = []
    for title, kind in asked_norm:
        asked_tokens = _chart_tokens(title)
        matched = any(
            kind == ct and (asked_tokens & near_tokens)
            for near_tokens, ct in shipped
        )
        # Fallback — no title tokens survived stopword strip (e.g.
        # "trends" only). Accept any chart with matching type.
        if not matched and not asked_tokens:
            matched = any(kind == ct for _, ct in shipped)
        (hits if matched else misses).append(f"{title}:{kind}")
    if not misses:
        return {
            "directive": "chart_types",
            "asked": asked,
            "status": "ok",
            "evidence": f"all {len(asked_norm)} chart(s) present with matching chartType",
            "auto_repair": None,
        }
    return {
        "directive": "chart_types",
        "asked": asked,
        "status": "partial" if hits else "missing",
        "evidence": f"matched: {hits}, missed: {misses}",
        "auto_repair": "patch chart chartType from requirement",
    }


# ── Top-level score + write ────────────────────────────────────────────

# ── Contract checks (routes / components / action-types / landing / negations) ──
# The contract is populated by services.requirement_contract from the raw
# prompt and rides under ``parsed_directives.contract``. Every check
# below reads the SAME on-disk artifacts the other _check_* funcs use
# (schemas, plan, nav-flow) so verdicts share a shape.


def _load_nav_flow(output_dir: Path) -> dict:
    p = output_dir / "src" / "contracts" / "nav-flow.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _load_workflows(output_dir: Path) -> list[tuple[str, dict]]:
    """Return [(id, workflow_definition)] for every workflow JSON on
    disk. Both /workflows (top-level) and src/lib/workflows/definitions
    layouts are checked."""
    out: list[tuple[str, dict]] = []
    for rel in ("workflows", "src/lib/workflows/definitions"):
        wdir = output_dir / rel
        if not wdir.is_dir():
            continue
        for p in sorted(wdir.rglob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            wid = str(data.get("id") or p.stem)
            out.append((wid, data))
    return out


def _norm_route(r: str) -> str:
    """`/history/{id}` and `/history/[id]` collapse to the same slug so
    Next.js param convention doesn't get flagged as a drift."""
    return (r or "").replace("[", "{").replace("]", "}").rstrip("/")


def _check_named_routes(asked: list[dict], schemas: list[tuple[str, dict]]) -> dict:
    """Every user-named route must have a page schema present. Missing
    routes → auto_repair hint pointing at the deterministic page emitter."""
    asked_paths = [r["path"] for r in asked if isinstance(r, dict) and r.get("path")]
    if not asked_paths:
        return {"directive": "named_routes", "asked": [], "status": "ok",
                "evidence": "no routes named in prompt", "auto_repair": None}
    got = {_norm_route(route) for route, _ in schemas}
    missing = [p for p in asked_paths if _norm_route(p) not in got]
    if not missing:
        return {"directive": "named_routes", "asked": asked_paths,
                "status": "ok",
                "evidence": f"all {len(asked_paths)} user-named routes present",
                "auto_repair": None}
    return {"directive": "named_routes", "asked": asked_paths,
            "status": "missing", "missing": missing,
            "evidence": f"missing routes: {missing}",
            "auto_repair": "add_page"}


def _check_landing_route(asked: str, output_dir: Path) -> dict:
    """`nav-flow.json.initialPage` must resolve to the asked landing
    route. Not the login page (auth-first landing overrides fail the
    check)."""
    if not asked:
        return {"directive": "landing_route", "asked": None, "status": "ok",
                "evidence": "no landing declared", "auto_repair": None}
    flow = _load_nav_flow(output_dir)
    initial = str(flow.get("initialPage") or "").lower()
    # initialPage can be a route or a page name — look up in pages[] if present.
    pages = flow.get("pages") if isinstance(flow.get("pages"), list) else []
    route_by_name: dict[str, str] = {}
    for p in pages:
        if isinstance(p, dict) and p.get("name") and p.get("route"):
            route_by_name[str(p["name"]).lower()] = str(p["route"])
    initial_route = route_by_name.get(initial, initial)
    if _norm_route(initial_route) == _norm_route(asked):
        return {"directive": "landing_route", "asked": asked, "status": "ok",
                "evidence": f"nav-flow.initialPage resolves to {asked}",
                "auto_repair": None}
    return {"directive": "landing_route", "asked": asked, "status": "missing",
            "evidence": f"nav-flow.initialPage = {initial!r} (route {initial_route!r}) "
                        f"≠ asked {asked!r}",
            "auto_repair": "set_initial_page"}


def _check_named_components(asked: list[dict],
                            schemas: list[tuple[str, dict]]) -> dict:
    """Every (page, component) pair the user named must appear in that
    page's schema tree. A single missing component on a present page is
    ``partial`` (some pairs satisfied); everything missing is ``missing``."""
    if not asked:
        return {"directive": "named_components", "asked": [], "status": "ok",
                "evidence": "no components named in prompt", "auto_repair": None}
    schema_by_route: dict[str, dict] = {_norm_route(r): s for r, s in schemas}
    hits: list[str] = []
    misses: list[str] = []
    for pair in asked:
        if not isinstance(pair, dict):
            continue
        page = _norm_route(pair.get("page") or "")
        comp = pair.get("component")
        if not page or not comp:
            continue
        schema = schema_by_route.get(page)
        if not schema:
            misses.append(f"{page}→{comp} (page missing)")
            continue
        types = {(n.get("type") or "") for n in _walk(schema.get("root"))}
        if comp in types:
            hits.append(f"{page}→{comp}")
        else:
            misses.append(f"{page}→{comp}")
    if not misses:
        return {"directive": "named_components", "asked": asked, "status": "ok",
                "evidence": f"all {len(hits)} named components present",
                "auto_repair": None}
    status = "partial" if hits else "missing"
    return {"directive": "named_components", "asked": asked, "status": status,
            "hits": hits, "missing": misses,
            "evidence": f"missing: {misses}",
            "auto_repair": "add_component"}


def _check_named_action_types(asked: list[dict],
                              workflows: list[tuple[str, dict]]) -> dict:
    """Every user-named action_type must appear in SOME workflow. When
    ``workflow`` is set on the ask, the type must appear specifically in
    THAT workflow (case-insensitive fuzzy match on workflow id)."""
    if not asked:
        return {"directive": "named_action_types", "asked": [], "status": "ok",
                "evidence": "no action-types named in prompt", "auto_repair": None}

    def _wf_action_types(wf_def: dict) -> set[str]:
        seen: set[str] = set()
        for n in _walk(wf_def):
            t = str(n.get("type") or "").lower()
            cfg = n.get("config") or {}
            if isinstance(cfg, dict):
                at = str(cfg.get("actionType") or "").lower()
                if at:
                    seen.add(at)
            if t:
                seen.add(t)
        return seen

    hits: list[str] = []
    misses: list[str] = []
    for entry in asked:
        if not isinstance(entry, dict):
            continue
        at = str(entry.get("action_type") or "").lower()
        if not at:
            continue
        target_wf = entry.get("workflow")
        matched_in = None
        for wid, wdef in workflows:
            if target_wf and target_wf.lower() not in wid.lower():
                continue
            if at in _wf_action_types(wdef):
                matched_in = wid
                break
        if matched_in:
            hits.append(f"{at} in {matched_in}")
        else:
            misses.append(f"{at}" + (f" (expected in {target_wf})" if target_wf else ""))
    if not misses:
        return {"directive": "named_action_types", "asked": asked,
                "status": "ok",
                "evidence": f"{len(hits)} action-types matched: {hits}",
                "auto_repair": None}
    status = "partial" if hits else "missing"
    return {"directive": "named_action_types", "asked": asked, "status": status,
            "hits": hits, "missing": misses,
            "evidence": f"missing action-types: {misses}",
            "auto_repair": "rewrite_workflow_step"}


def _check_out_of_scope(asked: list[str], schemas: list[tuple[str, dict]],
                        nav_flow: dict) -> dict:
    """Fuzzy negation check — surfaces the user explicitly excluded
    must NOT be present. Matches surface names in the negation phrases
    against nav labels + route slugs. Reports ``partial`` when >0 asked
    negations are violated (out-of-scope surfaces present)."""
    if not asked:
        return {"directive": "out_of_scope", "asked": [], "status": "ok",
                "evidence": "no negations declared", "auto_repair": None}

    tokens = []
    for phrase in asked:
        phrase = str(phrase or "")
        for word in re.findall(r"\b([A-Z][A-Za-z]{2,})\b", phrase):
            tokens.append(word.lower())
    # Add common lowercase surface words the negation frequently names.
    for phrase in asked:
        for kw in ("payment", "transfer", "admin", "settings", "audit"):
            if kw in str(phrase or "").lower():
                tokens.append(kw)

    surface_signals: list[str] = []
    for r, _s in schemas:
        surface_signals.append(_norm_route(r).lower())
    for entry in (nav_flow.get("pages") or []):
        if isinstance(entry, dict):
            surface_signals.append(str(entry.get("name") or "").lower())
            surface_signals.append(str(entry.get("route") or "").lower())
    joined = " ".join(surface_signals)

    violated: list[str] = []
    for tok in set(tokens):
        # naive contains — good enough for a "shouldn't be here" flag.
        if tok and tok in joined:
            violated.append(tok)
    if not violated:
        return {"directive": "out_of_scope", "asked": asked, "status": "ok",
                "evidence": "no out-of-scope surfaces detected",
                "auto_repair": None}
    return {"directive": "out_of_scope", "asked": asked, "status": "partial",
            "violated": violated,
            "evidence": f"out-of-scope surfaces present: {violated}",
            "auto_repair": None}


def _load_plan(output_dir: Path) -> dict:
    p = output_dir / "src" / "contracts" / "plan.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def score_requirement(output_dir: str | Path) -> dict[str, Any]:
    """Score every directive in requirement.json against the shipped app.

    Returns the report dict. Empty ``verdicts`` when no requirement is on
    disk. Never raises — a failed check is a "missing" verdict, not an
    exception.
    """
    root = Path(output_dir)
    try:
        from services.requirement import load_requirement
        requirement = load_requirement(root)
    except Exception:  # noqa: BLE001
        requirement = None
    if not isinstance(requirement, dict):
        return {"generated_at": _iso_now(), "verdicts": [],
                "summary": {"ok": 0, "missing": 0, "partial": 0}}

    directives = _merge_directives(requirement)
    if not directives:
        return {"generated_at": _iso_now(), "verdicts": [],
                "summary": {"ok": 0, "missing": 0, "partial": 0}}

    plan = _load_plan(root)
    schemas = _load_page_schemas(root)

    verdicts: list[dict] = []
    if directives.get("visual_preset"):
        verdicts.append(_check_visual_preset(str(directives["visual_preset"]), root))
    if directives.get("archetype_vocabulary"):
        verdicts.append(_check_archetype_vocabulary(str(directives["archetype_vocabulary"]), plan))
    if directives.get("row_click_target"):
        verdicts.append(_check_row_click(str(directives["row_click_target"]), schemas))
    if directives.get("filter_dimensions"):
        verdicts.append(_check_filter_dimensions(directives["filter_dimensions"], schemas))
    if directives.get("gauges"):
        verdicts.append(_check_gauges(directives["gauges"], schemas))
    if directives.get("chart_types"):
        verdicts.append(_check_chart_types(directives["chart_types"], schemas))

    # Contract checks — user-named routes / components / action-types /
    # landing / negations. Populated by services.requirement_contract at
    # ensure_requirement time and folded under ``contract``.
    contract = directives.get("contract") or {}
    if isinstance(contract, dict):
        workflows = _load_workflows(root)
        nav_flow = _load_nav_flow(root)
        if contract.get("named_routes"):
            verdicts.append(_check_named_routes(contract["named_routes"], schemas))
        if contract.get("landing_route"):
            verdicts.append(_check_landing_route(contract["landing_route"], root))
        if contract.get("named_components"):
            verdicts.append(_check_named_components(contract["named_components"], schemas))
        if contract.get("named_action_types"):
            verdicts.append(_check_named_action_types(contract["named_action_types"], workflows))
        if contract.get("out_of_scope"):
            verdicts.append(_check_out_of_scope(contract["out_of_scope"], schemas, nav_flow))

    summary = {"ok": 0, "missing": 0, "partial": 0}
    for v in verdicts:
        summary[v.get("status", "missing")] = summary.get(v.get("status", "missing"), 0) + 1

    return {
        "generated_at": _iso_now(),
        "verdicts": verdicts,
        "summary": summary,
    }


def write_report(output_dir: str | Path, report: dict) -> Path | None:
    """Persist the report to ``src/contracts/requirement-fidelity.json``."""
    p = Path(output_dir).joinpath(*REPORT_REL)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return p
    except Exception as exc:  # noqa: BLE001
        logger.warning("[fidelity] write failed %s: %s", p, exc)
        return None


def _try_auto_repair(output_dir: Path, verdicts: list[dict]) -> list[str]:
    """Fire deterministic repairs for verdicts that name a known action.

    Returns the list of repair actions actually invoked. Never raises —
    a failed repair leaves the verdict as-is; the report still reflects
    the pre-repair state so Smith can pick up what remains.

    Repairs today:

      * ``apply_hints_to_pages`` — re-run the hint applier (idempotent)
        for row_click + filter_dimensions.
      * ``backfill visual_lock.preset_name from requirement`` — write
        the preset directly into design-spec.visual_lock so downstream
        token derivations pick it up.
      * ``stamp plan.archetype from requirement`` — set plan.archetype
        and persist.
    """
    fired: set[str] = set()
    for v in verdicts:
        if v.get("status") == "ok":
            continue
        action = v.get("auto_repair")
        if not action or action in fired:
            continue
        try:
            if action == "apply_hints_to_pages":
                from services.apply_hints_to_pages import apply_hints_to_pages
                apply_hints_to_pages(str(output_dir))
                fired.add(action)
            elif action == "backfill visual_lock.preset_name from requirement":
                _backfill_preset(output_dir, str(v.get("asked") or ""))
                fired.add(action)
            elif action == "stamp plan.archetype from requirement":
                _stamp_archetype(output_dir, str(v.get("asked") or ""))
                fired.add(action)
            elif action == "dashboard-maquette top-up":
                # Re-run the dashboard maquette applier with a cleared
                # marker so the top-up injects any missing pillar (KPIs,
                # activity, hero, gauges). Idempotent — no-op when the
                # maquette already has every pillar rendered.
                _clear_maquette_marker_and_reapply(output_dir)
                fired.add(action)
            elif action == "patch chart chartType from requirement":
                # A Chart node on the page but with no chartType (or the
                # wrong one) — walk requirement.chart_types and patch
                # by title-token overlap against the nearest Heading or
                # the Chart's own title/series. Cheap deterministic
                # fix for the composer-drops-chartType path.
                _patch_chart_types(output_dir, v.get("asked") or [])
                fired.add(action)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[fidelity] repair %s failed: %s", action, exc)
    return sorted(fired)


def _clear_maquette_marker_and_reapply(output_dir: Path) -> None:
    """Prime the dashboard maquette with any gauges from requirement.json
    that it's missing, clear the ``maquette_composed`` idempotency
    marker on home.json, then re-run ``apply_maquette_to_dashboard``.
    The applier's top-up pass sees the gauges in the maquette and
    injects Gauge/SplitArc widgets on the dashboard. Fail-open — missing
    inputs leave the schema untouched.

    Gauge back-splice is the load-bearing bit: earlier plan-persist
    passes clobber ``plan.hints.gauges``, so the maquette on disk was
    authored without gauges. The critic runs LATE, so requirement.json
    is the last-writer authority — read from it here.
    """
    # ── 1. splice requirement.gauges into maquette on disk ────────────
    maq_path = output_dir / "src" / "contracts" / "dashboard-maquette.json"
    req_path = output_dir / "src" / "contracts" / "requirement.json"
    if maq_path.is_file() and req_path.is_file():
        try:
            maq = json.loads(maq_path.read_text(encoding="utf-8"))
            req = json.loads(req_path.read_text(encoding="utf-8"))
            req_gauges = (req.get("parsed_directives") or {}).get("gauges") or []
            # Fold amendments — later parsed_directives override.
            for a in req.get("amendments") or []:
                if isinstance(a, dict):
                    g = (a.get("parsed_directives") or {}).get("gauges")
                    if isinstance(g, list) and g:
                        req_gauges = g
            if req_gauges and not (maq.get("gauges") or []):
                maq["gauges"] = req_gauges
                maq_path.write_text(json.dumps(maq, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    # ── 2. clear idempotency marker on home.json ──────────────────────
    home = output_dir / "src" / "schemas" / "home.json"
    if home.is_file():
        try:
            schema = json.loads(home.read_text(encoding="utf-8"))
            meta = schema.get("meta") if isinstance(schema.get("meta"), dict) else {}
            if meta.get("maquette_composed"):
                meta.pop("maquette_composed", None)
                schema["meta"] = meta
                home.write_text(json.dumps(schema, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    # ── 3. re-run the applier so the deterministic path rebuilds ─────
    try:
        from services.apply_dashboard_maquette import apply_maquette_to_dashboard
        apply_maquette_to_dashboard(str(output_dir))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[fidelity] dashboard top-up reapply failed: %s", exc)

    # ── 4. force gauge top-up on-disk ────────────────────────────────
    # The deterministic ``_build_sections`` path doesn't call the
    # top-up (only the LLM-composer branch does), so gauges wouldn't
    # land otherwise.
    #
    # SCOPE: only the LANDING dashboard route. Preset gauges (NRR,
    # Quarterly Target) belong on the landing page, not every
    # dashboard-typed page. `_find_dashboard_schema` returns any
    # dashboard-typed route from plan.pages — which for analytics
    # apps often includes /mrr-movement, /revenue, etc. Injecting
    # "Health & targets" gauges + "Latest activity" feed onto every
    # analytics page is wrong and confusing.
    #
    # Landing routes accepted: `/`, `/dashboard`, `/home`,
    # `/overview`. Anything else is skipped.
    try:
        from services.apply_dashboard_maquette import _topup_missing_pillars
        maq = json.loads(maq_path.read_text(encoding="utf-8")) if maq_path.is_file() else {}
        _LANDING_ROUTES = {"/", "/dashboard", "/home", "/overview"}
        candidates: list[Path] = []
        sdir = output_dir / "src" / "schemas"
        if sdir.is_dir():
            for p in sorted(sdir.rglob("*.json")):
                if p.name in ("shell.json", "nav-flow.json"):
                    continue
                try:
                    _sch = json.loads(p.read_text(encoding="utf-8"))
                except Exception:  # noqa: BLE001
                    continue
                route = str((_sch.get("route") or "")).rstrip("/") or "/"
                if route in _LANDING_ROUTES:
                    candidates.append(p)
        for schema_path in candidates:
            try:
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
                added = _topup_missing_pillars(schema, maq)
                if added:
                    schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
            except Exception:  # noqa: BLE001
                continue
    except Exception as exc:  # noqa: BLE001
        logger.warning("[fidelity] gauge top-up on-disk failed: %s", exc)


def _patch_chart_types(output_dir: Path, asked: list) -> None:
    """Walk every page schema; for each Chart find the best-matching
    asked ``{title, chartType}`` by token overlap and stamp chartType
    when missing or different. Won't invent charts — only patches those
    already on the page.
    """
    asked_norm: list[tuple[set[str], str]] = []
    for x in asked:
        if not isinstance(x, dict):
            continue
        title = str(x.get("title") or "").strip()
        kind = str(x.get("chartType") or "").strip().lower()
        if title and kind:
            asked_norm.append((_chart_tokens(title), kind))
    if not asked_norm:
        return
    sdir = output_dir / "src" / "schemas"
    if not sdir.is_dir():
        return
    for path in sorted(sdir.rglob("*.json")):
        if path.name in ("shell.json", "nav-flow.json"):
            continue
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        touched = False
        last_heading = ""
        for node in _walk(schema.get("root")):
            t = node.get("type")
            if t == "Heading":
                last_heading = str((node.get("props") or {}).get("content") or "").strip()
            elif t == "Chart":
                props = node.setdefault("props", {})
                own_title = str(props.get("title") or "")
                series_titles = " ".join(
                    str(s.get("name") or s.get("label") or "")
                    for s in (props.get("series") or [])
                    if isinstance(s, dict)
                )
                near_tokens = _chart_tokens(" ".join([last_heading, own_title, series_titles]))
                if not near_tokens:
                    continue
                best_kind = ""
                best_overlap = 0
                for asked_tokens, kind in asked_norm:
                    overlap = len(asked_tokens & near_tokens)
                    if overlap > best_overlap:
                        best_overlap = overlap
                        best_kind = kind
                if best_kind and props.get("chartType") != best_kind:
                    props["chartType"] = best_kind
                    touched = True
        if touched:
            try:
                path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                logger.warning("[fidelity] chart-patch write failed %s: %s", path, exc)


_PRESET_PALETTE_TO_COLORPALETTE = {
    # (visual_lock palette key) → (design-spec colorPalette key). Mirror
    # brief_to_design_spec's mapping when a lock is active: lock.accent
    # is the brand primary, lock.badge is the complementary accent.
    "accent":  "primary",
    "badge":   "accent",
    "bg":      "background",
    "subtle":  "surface",
    "fg":      "textPrimary",
    "muted":   "muted",
    "danger":  "error",
    "success": "success",
}


def _lookup_preset(preset_name: str):
    """Return the VisualLock instance whose preset_name matches, else None.
    Iterates services.visual_lock_presets — new presets need no extra wiring.
    """
    if not preset_name:
        return None
    try:
        from services import visual_lock_presets as _vlp
        from schemas.design_brief import VisualLock as _VL
    except Exception:  # noqa: BLE001
        return None
    target = str(preset_name).strip().lower()
    for attr_name in dir(_vlp):
        obj = getattr(_vlp, attr_name, None)
        if isinstance(obj, _VL) and str(getattr(obj, "preset_name", "") or "").lower() == target:
            return obj
    return None


def _backfill_preset(output_dir: Path, preset_name: str) -> None:
    """Cascade the preset through the whole design-token pipeline.

    Stamping ``visual_lock.preset_name`` alone doesn't move the app's
    colours — no downstream consumer reads that field to re-derive CSS.
    This helper looks up the preset's actual palette + typography from
    ``visual_lock_presets`` and:

      1. Rewrites ``spec.colorPalette`` from the preset palette (same
         mapping brief_to_design_spec uses when a lock is active).
      2. Applies the preset's display/body/mono fonts onto
         ``spec.typography`` when the spec has no explicit families.
      3. Calls ``save_design_spec`` which deterministically rewrites
         ``src/app/globals.css`` :root from the new palette + injects
         Google Fonts.

    Fail-open: any missing input leaves the spec unchanged.
    """
    if not preset_name:
        return
    spec_path = output_dir / "src" / "contracts" / "design-spec.json"
    if not spec_path.is_file():
        return
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return

    preset = _lookup_preset(preset_name)

    # Stamp the name unconditionally so the verdict flips even when the
    # preset lookup fails (unknown-name should not silently no-op).
    vl = spec.get("visual_lock") if isinstance(spec.get("visual_lock"), dict) else {}
    vl["preset_name"] = preset_name
    spec["visual_lock"] = vl

    if preset is None:
        try:
            spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return

    # ── 1. cascade palette → colorPalette ─────────────────────────────
    lp = getattr(preset, "palette", None) or {}
    if isinstance(lp, dict):
        color_palette = spec.get("colorPalette") if isinstance(spec.get("colorPalette"), dict) else {}
        for lock_key, cp_key in _PRESET_PALETTE_TO_COLORPALETTE.items():
            v = lp.get(lock_key)
            if isinstance(v, str) and v.strip():
                color_palette[cp_key] = v
        # muted doubles as textSecondary in the brief_to_design_spec mapping.
        if isinstance(lp.get("muted"), str):
            color_palette["textSecondary"] = lp["muted"]
        # Sidebar chrome tinted toward brand instead of falling back to
        # a hardcoded near-black. Downstream shell writer honors sidebarBg.
        brand_hex = lp.get("accent") or color_palette.get("primary")
        if isinstance(brand_hex, str) and brand_hex.strip():
            color_palette.setdefault("sidebarBg", brand_hex)
            color_palette.setdefault("sidebarText", "#FFFFFF")
        spec["colorPalette"] = color_palette

    # ── 2. cascade typography families ────────────────────────────────
    lt = getattr(preset, "typography", None) or {}
    if isinstance(lt, dict):
        typo = spec.get("typography") if isinstance(spec.get("typography"), dict) else {}
        fam = typo.get("families") if isinstance(typo.get("families"), dict) else {}
        # Only fill families the spec hasn't already specified — respect
        # any explicit LLM/brief choice.
        if lt.get("display") and not fam.get("display"):
            fam["display"] = lt["display"]
        if lt.get("body") and not fam.get("body"):
            fam["body"] = lt["body"]
        if lt.get("mono") and not fam.get("mono"):
            fam["mono"] = lt["mono"]
        if fam:
            typo["families"] = fam
            spec["typography"] = typo

    # ── 3. write via save_design_spec so globals.css gets rewritten ───
    try:
        from agents.design_agent import save_design_spec
        save_design_spec(str(output_dir), spec)
    except Exception:  # noqa: BLE001
        # Fall back to a plain write — the CSS won't move, but the
        # preset_name still lands so a future repair pass can retry.
        try:
            spec_path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass


def _stamp_archetype(output_dir: Path, archetype: str) -> None:
    if not archetype:
        return
    p = output_dir / "src" / "contracts" / "plan.json"
    if not p.is_file():
        return
    plan = json.loads(p.read_text(encoding="utf-8"))
    plan["archetype"] = archetype
    p.write_text(json.dumps(plan, indent=2), encoding="utf-8")


def run(output_dir: str | Path, *, auto_repair: bool = True) -> dict[str, Any]:
    """Public entry: score, optionally repair, re-score, write report.

    Two-pass so the report reflects post-repair state. Returns the
    written report.
    """
    root = Path(output_dir)
    report = score_requirement(root)
    if not report.get("verdicts"):
        write_report(root, report)
        return report
    fired: list[str] = []
    if auto_repair:
        fired = _try_auto_repair(root, report["verdicts"])
        if fired:
            report = score_requirement(root)
    if fired:
        report["auto_repairs_fired"] = fired
    write_report(root, report)
    return report


__all__ = ["score_requirement", "write_report", "run"]
