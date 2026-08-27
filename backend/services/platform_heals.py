"""Platform heals — fix known platform-regression classes IN PLACE on a
generated app.

Every heal here is the deterministic re-apply of a platform fix that
already landed at the source (template / emitter / guard), distilled from
the 2026-08-21 cwx1stzz live-debug session. Existing apps carry the bad
artifacts baked into their output tree, so fixing the emitter alone leaves
them broken; these functions bring an app's output up to the current
platform behaviour without touching any LLM-authored judgment.

Heal classes covered (symptom → heal):

1. "server shows null / API shows the value", "KPI breakdowns are 0"
   → template-owned runtime files drifted (rules engine grant-union
     semantics, data-engine-bridge role-only ctx). Re-sync them.
2. "KPI grid collapsed to a gapless 2-col mosaic"
   → skin CSS wrote `grid-template-columns … !important` against KPI
     grids. Strip those rules from globals.css.
3. "multi-column grids render as 2 columns at desktop"
   → Tailwind purged dynamic `lg:grid-cols-N`. Ensure the safelist.
4. "everything is cramped / components have no space between them"
   → numeric spacing tokens missing (token guard) + vendored engine
     emitting `--spacing-*` while the library reads `--token-spacing-*`.
5. "filter dropdowns list statuses that don't exist"
   → align dashboard filter Select options to the plan's enum_values.
6. "sections fused together"
   → floor a `tokens.spacing.3` dashboard root gap at spacing.4.

All heals are idempotent and additive: safe to run repeatedly, safe to run
on healthy apps (they report zero changes).
"""
from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_BACKEND_ROOT = Path(__file__).resolve().parent.parent

# Template-owned files (never LLM-authored) that are safe to re-sync
# wholesale: (template path relative to backend/, app path relative to app).
_TEMPLATE_OWNED = [
    ("templates/runtime/rules/engine.ts", "src/lib/rules/engine.ts"),
    ("templates/app-foundation/src/lib/data-engine-bridge.ts",
     "src/lib/data-engine-bridge.ts"),
]

_SAFELIST_BLOCK = (
    "  // Grid/library components compose some utility names dynamically\n"
    "  // (`lg:grid-cols-${n}`), which the JIT scanner can never see —\n"
    "  // without a safelist those classes render in the DOM with no CSS\n"
    "  // rule and multi-column layouts silently collapse to the fallback.\n"
    "  safelist: [\n"
    "    { pattern: /^grid-cols-(1|2|3|4|5|6)$/, variants: [\"sm\", \"md\", \"lg\", \"xl\"] },\n"
    "  ],\n"
)

# A skin rule that hard-forces the KPI grid's track count. Column count is
# the composer's call (schema Grid columns=N); with !important this rule
# beat class, stylesheet, and even inline CSS at every viewport width.
_DESTRUCTIVE_KPI_RULE = re.compile(
    r"[^{}]*\.grid:has\(\[data-(?:metric-tile|importance)\]\)[^{}]*"
    r"\{[^{}]*grid-template-columns[^{}]*!important[^{}]*\}\n?"
)


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


# ── Heal 1: template-owned runtime files ─────────────────────────────────

def sync_template_runtime_files(output_dir: str) -> dict:
    root = Path(output_dir)
    synced: list[str] = []
    for tmpl_rel, app_rel in _TEMPLATE_OWNED:
        src = _BACKEND_ROOT / tmpl_rel
        dst = root / app_rel
        if not src.is_file() or not dst.is_file():
            continue  # app predates the file or template moved — skip, never create
        if src.read_bytes() != dst.read_bytes():
            shutil.copyfile(src, dst)
            synced.append(app_rel)
    return {"synced": synced}


# ── Heal 2: destructive skin CSS ─────────────────────────────────────────

def strip_destructive_skin_css(output_dir: str) -> dict:
    css_path = Path(output_dir) / "src" / "app" / "globals.css"
    s = _read(css_path)
    if s is None:
        return {"stripped": 0}
    new, n = _DESTRUCTIVE_KPI_RULE.subn(
        "\n/* platform_heals: removed skin rule that force-collapsed KPI grids */\n", s)
    if n:
        css_path.write_text(new, encoding="utf-8")
    return {"stripped": n}


# ── Heal 3: tailwind safelist ────────────────────────────────────────────

def ensure_tailwind_safelist(output_dir: str) -> dict:
    cfg = Path(output_dir) / "tailwind.config.ts"
    s = _read(cfg)
    if s is None or "safelist" in s:
        return {"added": False}
    m = re.search(r"^(\s*)content:\s*\[[^\]]*\],\n", s, re.M)
    if not m:
        return {"added": False}
    s = s[:m.end()] + _SAFELIST_BLOCK + s[m.end():]
    cfg.write_text(s, encoding="utf-8")
    return {"added": True}


# ── Heal 4: vendored engine --token- prefix ──────────────────────────────

def patch_engine_token_prefix(output_dir: str) -> dict:
    dist = (Path(output_dir) / "node_modules" / "@tentoroforge" / "engine"
            / "dist" / "EngineProvider.js")
    s = _read(dist)
    if s is None or "out[`--token-${key}`]" in s:
        return {"patched": False}
    anchor = "out[`--${key}`] = String(v);"
    if anchor not in s:
        return {"patched": False}
    s = s.replace(anchor, anchor + "\n                out[`--token-${key}`] = String(v);", 1)
    dist.write_text(s, encoding="utf-8")
    return {"patched": True}


# ── Heal 5: dashboard rhythm floor ───────────────────────────────────────

def floor_dashboard_rhythm(output_dir: str) -> dict:
    """spacing.3 (12px) between full page sections reads cramped on every
    dashboard with serif headings + carded rows; the maquette now floors
    'tight' at spacing.4 — bring already-generated dashboards up to it."""
    floored: list[str] = []
    schemas = Path(output_dir) / "src" / "schemas"
    if not schemas.is_dir():
        return {"floored": floored}
    for fp in schemas.rglob("dashboard.json"):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        root = data.get("root")
        if not isinstance(root, dict):
            continue
        props = root.get("props")
        if isinstance(props, dict) and props.get("gap") == "tokens.spacing.3":
            props["gap"] = "tokens.spacing.4"
            fp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            floored.append(str(fp.relative_to(output_dir)))
    return {"floored": floored}


# ── Heal 6: dashboard filter enums ↔ plan ────────────────────────────────

def _plan_entities(plan: dict) -> list[tuple[str, dict]]:
    ents = plan.get("entities") or {}
    if isinstance(ents, dict):
        return list(ents.items())
    out = []
    for e in ents:
        if isinstance(e, dict) and e.get("name"):
            out.append((e["name"], e))
    return out


def _enum_for(plan: dict, column: str, label: str) -> Optional[list[str]]:
    """Resolve which entity's enum a filter Select means.

    Preference order:
      1. the entity whose name appears in the Select's label
         ("Event Status" → Event.status),
      2. a unique column match across entities,
      3. all matching entities agree on the values.
    Ambiguous otherwise → None (leave the Select alone).
    """
    candidates: list[tuple[str, list[str]]] = []
    for name, ent in _plan_entities(plan):
        for f in ent.get("fields") or []:
            if f.get("name") == column and f.get("enum_values"):
                candidates.append((name, list(f["enum_values"])))
    if not candidates:
        return None
    low = (label or "").lower()
    for name, values in candidates:
        if name.lower() in low:
            return values
    if len(candidates) == 1:
        return candidates[0][1]
    first = candidates[0][1]
    if all(v == first for _, v in candidates[1:]):
        return first
    return None


def _title(value: str) -> str:
    return " ".join(w.capitalize() for w in value.replace("_", " ").split())


def align_dashboard_filter_enums(output_dir: str) -> dict:
    """Filter Selects (data-dashboard-filter) must offer the plan's REAL
    enum values — the composer/LLM invented options like `active`/`upcoming`
    (Event has draft/published/live/…) and `critical` (Task priority is
    low/medium/high), so those filters could never match a row."""
    root = Path(output_dir)
    plan_fp = root / "src" / "contracts" / "plan.json"
    try:
        plan = json.loads(plan_fp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"aligned": []}

    aligned: list[str] = []
    schemas = root / "src" / "schemas"
    if not schemas.is_dir():
        return {"aligned": aligned}

    def walk(node: Any) -> bool:
        changed = False
        if isinstance(node, dict):
            props = node.get("props")
            if (node.get("type") == "Select" and isinstance(props, dict)
                    and props.get("data-dashboard-filter")):
                values = _enum_for(plan, str(props.get("name") or ""),
                                   str(props.get("label") or ""))
                if values:
                    existing = props.get("options") or []
                    all_label = next(
                        (o.get("label") for o in existing
                         if isinstance(o, dict) and o.get("value") == ""),
                        "All",
                    )
                    new_opts = ([{"value": "", "label": all_label}]
                                + [{"value": v, "label": _title(v)} for v in values])
                    if new_opts != existing:
                        props["options"] = new_opts
                        changed = True
            for child in node.get("children") or []:
                changed = walk(child) or changed
        elif isinstance(node, list):
            for item in node:
                changed = walk(item) or changed
        return changed

    for fp in schemas.rglob("*.json"):
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if walk(data.get("root")):
            fp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            aligned.append(str(fp.relative_to(output_dir)))
    return {"aligned": aligned}


# ── Heal 7: workflow inbox shadowing a domain Task entity ────────────────

_INBOX_MARKER = "Task Inbox (Slice E T2)"


def relocate_workflow_inbox(output_dir: str) -> dict:
    """When the domain has a Task entity, the workflow-approval inbox that
    the injector historically parked at /tasks steals the menu's "Tasks"
    click and renders a near-always-empty page OUTSIDE the (dashboard)
    shell (no chrome). Move it to /inbox and repoint nav references at the
    entity's real route. Mirrors the runtime_injector collision guard for
    apps generated before it existed."""
    root = Path(output_dir)
    inbox_page = root / "src" / "app" / "tasks" / "page.tsx"
    content = _read(inbox_page)
    if content is None or _INBOX_MARKER not in content:
        return {"relocated": False}

    plan_fp = root / "src" / "contracts" / "plan.json"
    try:
        plan = json.loads(plan_fp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"relocated": False}
    ents = plan.get("entities") or {}
    names = []
    if isinstance(ents, dict):
        for k, v in ents.items():
            names.append(str(k))
            if isinstance(v, dict) and v.get("table"):
                names.append(str(v["table"]))
    if not any(n.lower() in ("task", "tasks") for n in names):
        return {"relocated": False}

    src_dir = root / "src" / "app" / "tasks"
    dst_dir = root / "src" / "app" / "inbox"
    if dst_dir.exists():
        shutil.rmtree(src_dir)
    else:
        shutil.move(str(src_dir), str(dst_dir))
        for fp in dst_dir.rglob("*.tsx"):
            fp.write_text(
                fp.read_text(encoding="utf-8").replace("/tasks/", "/inbox/"),
                encoding="utf-8",
            )

    # Repoint nav-flow references: the entity's list page is what "Tasks"
    # means to the user. Only rewrite when that page really exists.
    nav_fp = root / "src" / "contracts" / "nav-flow.json"
    repointed = False
    try:
        nav = json.loads(nav_fp.read_text(encoding="utf-8"))
        routes = {p.get("route") for p in nav.get("pages") or [] if isinstance(p, dict)}
        target = "/task" if "/task" in routes else ("/tasks" if "/tasks" in routes else None)
        if target and target != "/tasks":
            def repoint(obj):
                nonlocal repointed
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if k == "route" and v == "/tasks":
                            obj[k] = target
                            repointed = True
                        else:
                            repoint(v)
                elif isinstance(obj, list):
                    for item in obj:
                        repoint(item)
            repoint(nav.get("personas"))
            if repointed:
                nav_fp.write_text(json.dumps(nav, indent=1), encoding="utf-8")
    except (OSError, json.JSONDecodeError):
        pass

    # The menu derives from nav-flow + on-disk template routes — re-sync so
    # "Tasks" points at the entity page and "Inbox" appears for the queue.
    try:
        from services.shell_menu_sync import sync_shell_menu
        sync_shell_menu(str(root))
    except Exception as e:  # noqa: BLE001
        logger.warning("relocate_workflow_inbox: menu re-sync failed: %s", e)

    return {"relocated": True, "nav_repointed": repointed}


# ── Heal 8: detail-shaped collection routes ──────────────────────────────

def rebuild_detail_shaped_collections(output_dir: str) -> dict:
    """An entity's TOP-LEVEL route must render a collection. cwx1stzz shipped
    `/task` as a single-record detail (`op:"get"` + an update button) with no
    task list anywhere — the /tasks inbox template masked the gap from the
    coverage guards. Rebuild such routes deterministically: kanban when the
    entity has a small status enum (the shape briefs ask for), plain list
    otherwise. Idempotent — a rebuilt page carries a list dataSource and
    never matches again. LLM-authored pages that already list rows are
    untouched."""
    root = Path(output_dir)
    plan_fp = root / "src" / "contracts" / "plan.json"
    try:
        plan = json.loads(plan_fp.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"rebuilt": []}

    try:
        from services.entity_shape import is_join_entity
    except Exception:  # noqa: BLE001
        def is_join_entity(_e):  # type: ignore[misc]
            return False

    rebuilt: list[str] = []
    for name, ent in _plan_entities(plan):
        if not isinstance(ent, dict) or is_join_entity(ent):
            continue
        # Candidate collection slugs: entity name + table, kebab-cased.
        def kebab(x: str) -> str:
            out, prev = [], ""
            for ch in str(x):
                if ch.isupper() and prev and (prev.islower() or prev.isdigit()):
                    out.append("-")
                out.append(ch.lower())
                prev = ch
            return "".join(out).replace("_", "-")
        slugs = {kebab(name)}
        if ent.get("table"):
            slugs.add(kebab(ent["table"]))
        for slug in sorted(slugs):
            fp = root / "src" / "schemas" / f"{slug}.json"
            if not fp.is_file():
                continue
            try:
                schema = json.loads(fp.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            route = str(schema.get("route") or "")
            if route != f"/{slug}" or "[id]" in route:
                continue
            sources = schema.get("dataSources") or []
            has_collection_source = any(
                isinstance(ds, dict) and (
                    ds.get("op") in ("list", "aggregate", "series", "stats")
                    or ds.get("where") is not None)
                for ds in sources)
            if has_collection_source or not sources:
                continue  # already a collection page (or static) — hands off
            # Detail-shaped: every source resolves a single record.
            from services.apply_collection_maquette import _column_type_map
            from services.composer_prop_hygiene import sanitize_schema
            from services.deterministic_pages import (build_kanban_page,
                                                      build_list_page)
            columns = _column_type_map(ent)
            status_enum = next(
                (f.get("enum_values") for f in ent.get("fields") or []
                 if isinstance(f, dict) and str(f.get("name", "")).lower().endswith("status")
                 and isinstance(f.get("enum_values"), list)
                 and 2 <= len(f["enum_values"]) <= 6),
                None)
            title = str(name).rstrip("s") + "s"
            hint = {"title": title}
            if status_enum:
                new_schema = build_kanban_page(str(name), columns, route,
                                               design_spec=None, page_hint=hint)
            else:
                new_schema = build_list_page(str(name), columns, route,
                                             design_spec=None, page_hint=hint)
            sanitize_schema(new_schema)
            fp.write_text(json.dumps(new_schema, indent=2), encoding="utf-8")
            rebuilt.append(f"/{slug}")
    return {"rebuilt": rebuilt}


# ── Orchestrator ─────────────────────────────────────────────────────────

def apply_platform_heals(output_dir: str) -> dict:
    """Run every heal; each is independent and failure-isolated so one bad
    artifact can't block the rest."""
    report: dict[str, Any] = {}
    heals = [
        ("template_runtime", sync_template_runtime_files),
        ("skin_css", strip_destructive_skin_css),
        ("tailwind_safelist", ensure_tailwind_safelist),
        ("engine_token_prefix", patch_engine_token_prefix),
        ("dashboard_rhythm", floor_dashboard_rhythm),
        ("filter_enums", align_dashboard_filter_enums),
        ("workflow_inbox", relocate_workflow_inbox),
        ("collection_shape", rebuild_detail_shaped_collections),
    ]
    for key, fn in heals:
        try:
            report[key] = fn(output_dir)
        except Exception as e:  # noqa: BLE001 — heal isolation by design
            logger.warning("platform_heals.%s failed on %s: %s", key, output_dir, e)
            report[key] = {"error": str(e)}
    # Numeric spacing scale + typography subtrees — the invalid-inline-var
    # class ("everything is cramped").
    try:
        from services.token_completeness_guard import apply_token_completeness_guard
        report["tokens"] = apply_token_completeness_guard(output_dir)
    except Exception as e:  # noqa: BLE001
        logger.warning("platform_heals.tokens failed on %s: %s", output_dir, e)
        report["tokens"] = {"error": str(e)}
    report["changed"] = any(
        v for k, v in report.items()
        if k != "changed" and isinstance(v, dict) and any(
            bool(x) for kk, x in v.items() if kk != "error")
    )
    return report
