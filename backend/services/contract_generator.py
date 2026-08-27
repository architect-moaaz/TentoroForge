"""Deterministic contract generator — replaces the LLM-powered contract_agent.

Reads plan JSON and generates contracts via string templating.
Zero LLM cost. Zero hallucination. Consistent every time.
"""

import json
import re
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _normalize_models(data_models: Any) -> list[dict]:
    """Accept ``data_models`` as a LIST of ``{"name", ...}`` dicts OR a legacy
    DICT keyed by name; return a list of dicts each carrying ``name`` (folding
    the key in for the dict form). Canonical reader for entity/model lists so
    helpers never silently read the stale, now-empty ``plan["entities"]``."""
    if isinstance(data_models, dict):
        out: list[dict] = []
        for name, body in data_models.items():
            entry = dict(body) if isinstance(body, dict) else {}
            entry.setdefault("name", name)
            out.append(entry)
        return out
    if isinstance(data_models, list):
        return [m for m in data_models if isinstance(m, dict) and m.get("name")]
    return []


def _plan_models(plan: dict) -> list[dict]:
    """Canonical entity/model source with legacy fallback."""
    return _normalize_models(plan.get("data_models") or plan.get("entities") or [])


def _registry_entities(plan: dict, registry: dict | None) -> dict:
    """The canonical registry ``entities`` map (keyed by PascalName). Built once
    from the SAME plan when not supplied. Never raises — returns ``{}`` on
    failure so callers fall back to the name_normalizer trio."""
    if registry is None:
        try:
            from services.resource_registry import build_canonical_registry
            registry = build_canonical_registry(plan)
        except Exception as e:  # noqa: BLE001 — registry is best-effort here
            logger.warning("resource registry unavailable for contracts: %s", e)
            registry = {}
    return (registry or {}).get("entities") or {}


def _fam(entities: dict, name: str) -> dict:
    """Name family (``table``/``slug``/``camel``) for ``name`` from the registry,
    falling back to the canonical normalizer when the entity isn't registered."""
    rec = entities.get(name)
    if isinstance(rec, dict) and rec.get("table"):
        return rec
    from services import name_normalizer as _nn
    return {"table": _nn.to_table(name), "slug": _nn.to_slug(name), "camel": _nn.to_camel(name)}


def generate_contracts(output_dir: str, plan: dict, registry: dict | None = None) -> dict[str, Any]:
    """Generate all contract files from the plan.

    ``registry`` is the canonical resource registry (built from the SAME plan);
    when omitted it's built once here and threaded into every sub-generator so
    entity name families come from a single authority, never re-derived.

    Returns:
        {"generated": [...], "errors": [...]}
    """
    root = Path(output_dir)
    contracts_dir = root / "src" / "contracts"
    contracts_dir.mkdir(parents=True, exist_ok=True)
    (root / "contracts").mkdir(parents=True, exist_ok=True)

    if registry is None:
        try:
            from services.resource_registry import build_canonical_registry
            registry = build_canonical_registry(plan)
        except Exception as e:  # noqa: BLE001 — never block contracts on registry build
            logger.warning("resource registry unavailable for contracts: %s", e)
            registry = None

    generated: list[str] = []
    errors: list[str] = []

    # 1. api-client.ts
    try:
        _generate_api_client(contracts_dir / "api-client.ts", plan, registry)
        generated.append("src/contracts/api-client.ts")
    except Exception as e:
        errors.append(f"api-client.ts: {e}")

    # 2. navigation-flow.json
    try:
        _generate_navigation_flow(contracts_dir / "navigation-flow.json", plan, registry)
        generated.append("src/contracts/navigation-flow.json")
    except Exception as e:
        errors.append(f"navigation-flow.json: {e}")

    # 3. event-bindings.json
    try:
        _generate_event_bindings(contracts_dir / "event-bindings.json", plan, registry)
        generated.append("src/contracts/event-bindings.json")
    except Exception as e:
        errors.append(f"event-bindings.json: {e}")

    # 4. seed-plan.json
    try:
        _generate_seed_plan(root / "contracts" / "seed-plan.json", plan)
        generated.append("contracts/seed-plan.json")
    except Exception as e:
        errors.append(f"seed-plan.json: {e}")

    # 5. app-model.json — dependency graph + page/route manifest.
    # Imported lazily: app_model_builder imports naming helpers from this
    # module, so a top-level import would be circular.
    try:
        from services.app_model_builder import write_app_model
        write_app_model(output_dir, plan, registry)
        generated.append("src/contracts/app-model.json")
    except Exception as e:
        errors.append(f"app-model.json: {e}")

    # 6. design-system.tsx — page shells + column renderers. Static, styled via
    # semantic Tailwind tokens (defined in globals.css from design-spec.json), so
    # it respects the app palette without interpolation. Required by
    # phase_gates.check_contract_completeness; read as reference by the TSX
    # component/page agents. In schema-mode nothing imports it, but emitting it
    # deterministically lets the contract gate pass so the LLM agent is skipped.
    try:
        (contracts_dir / "design-system.tsx").write_text(_DESIGN_SYSTEM_TSX)
        generated.append("src/contracts/design-system.tsx")
    except Exception as e:
        errors.append(f"design-system.tsx: {e}")

    logger.info("Contract generation: %d generated, %d errors", len(generated), len(errors))
    return {"generated": generated, "errors": errors}


# Static design-system contract: real, import-safe, server-compatible React
# shells + column renderers. Colours/spacing come from semantic Tailwind classes
# wired to the design tokens in globals.css, so this file needs no per-app
# interpolation while still matching the generated palette + type scale.
_DESIGN_SYSTEM_TSX = '''import * as React from "react";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

// Auto-generated design-system contract (deterministic). Page shells that every
// page can wrap with, plus small column-renderer helpers. Styled with semantic
// Tailwind tokens (bg-card, text-foreground, text-page-title, ...) defined in
// src/app/globals.css from design-spec.json.

export function ListPageShell({
  title, description, actions, children,
}: {
  title: string; description?: string; actions?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-page-title font-bold text-foreground">{title}</h1>
          {description ? <p className="text-body text-muted-foreground mt-1">{description}</p> : null}
        </div>
        {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </div>
  );
}

export function DetailPageShell({
  title, backHref = "..", actions, children,
}: {
  title: string; backHref?: string; actions?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <div className="space-y-6">
      <Link href={backHref} className="inline-flex items-center gap-1 text-body text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> Back
      </Link>
      <div className="flex items-start justify-between gap-4">
        <h1 className="text-page-title font-bold text-foreground">{title}</h1>
        {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
      </div>
      {children}
    </div>
  );
}

export function FormPageShell({
  title, backHref = "..", children,
}: {
  title: string; backHref?: string; children: React.ReactNode;
}) {
  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <Link href={backHref} className="inline-flex items-center gap-1 text-body text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> Back
      </Link>
      <h1 className="text-page-title font-bold text-foreground">{title}</h1>
      {children}
    </div>
  );
}

export function DashboardShell({
  title, children,
}: {
  title: string; children: React.ReactNode;
}) {
  return (
    <div className="space-y-6">
      <h1 className="text-page-title font-bold text-foreground">{title}</h1>
      {children}
    </div>
  );
}

export function StatusBadge({ status }: { status?: string | null }) {
  return (
    <span className="inline-flex items-center rounded-full bg-secondary px-2.5 py-0.5 text-micro font-medium text-secondary-foreground">
      {status || "—"}
    </span>
  );
}

export function DateCell({ value }: { value?: string | Date | null }) {
  if (!value) return <span className="text-muted-foreground">—</span>;
  const d = typeof value === "string" ? new Date(value) : value;
  return <span className="text-body tabular-nums">{isNaN(d.getTime()) ? "—" : d.toLocaleDateString()}</span>;
}

export function UserAvatar({ name }: { name?: string | null }) {
  const initials = (name || "?").split(" ").filter(Boolean).map((s) => s[0]).slice(0, 2).join("").toUpperCase();
  return (
    <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-primary/10 text-micro font-semibold text-primary">
      {initials || "?"}
    </span>
  );
}

export function ActionDropdown({ children }: { children?: React.ReactNode }) {
  return <div className="inline-flex items-center gap-1">{children}</div>;
}
'''


# ─── Helpers ───

# The canonical naming trio now lives in ``name_normalizer`` (single authority).
# These are thin re-exports kept ONLY for back-compat with stray importers
# (e.g. ``workflow_generator`` imports ``_to_table``/``_to_slug`` from here).
# No entity-derivation caller in THIS module uses them any more — every entity
# name family flows through the resource registry via ``_fam``.
from services.name_normalizer import (  # noqa: E402
    to_slug as _to_slug,
    to_camel as _to_camel,
    to_table as _to_table,
)


def _field_to_ts_type(field: dict) -> str:
    """Convert plan field type to TypeScript type."""
    t = field.get("type", "varchar").lower()
    if "int" in t or "serial" in t or "numeric" in t or "decimal" in t or "float" in t or "double" in t:
        return "number"
    if "bool" in t:
        return "boolean"
    if "json" in t:
        return "any"
    if "date" in t or "timestamp" in t or "time" in t:
        return "string"
    if "uuid" in t or "text" in t or "varchar" in t or "char" in t:
        return "string"
    return "string"


# ─── Contract Generators ───

def _generate_api_client(path: Path, plan: dict, registry: dict | None = None):
    """Generate src/contracts/api-client.ts — typed fetch wrapper for all entities."""
    models = _plan_models(plan)
    reg_entities = _registry_entities(plan, registry)

    lines = [
        "// Auto-generated API client — all CRUD goes through the Data Engine",
        "// DO NOT EDIT — regenerated from plan on each build",
        "",
        "const API_BASE = '';",
        "",
        "async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {",
        "  const res = await fetch(`${API_BASE}${path}`, {",
        "    ...init,",
        "    headers: { 'Content-Type': 'application/json', ...init?.headers },",
        "  });",
        "  if (!res.ok) {",
        "    const err = await res.json().catch(() => ({}));",
        "    throw new Error(err?.error?.message || `Request failed: ${res.status}`);",
        "  }",
        "  return res.json();",
        "}",
        "",
        "interface ListResponse<T> { data: T[]; total: number; page: number; limit: number; }",
        "",
    ]

    for model in models:
        name = model.get("name", "")
        if not name:
            continue
        slug = _fam(reg_entities, name)["table"]  # registry table, e.g. expenseReports / equipment
        fields = model.get("fields", [])

        # Type definition
        lines.append(f"// ─── {name} ───")
        lines.append(f"export interface {name} {{")
        for field in fields:
            fname = field.get("name", "")
            ftype = _field_to_ts_type(field)
            nullable = field.get("nullable", False)
            lines.append(f"  {fname}{'?' if nullable else ''}: {ftype};")
        lines.append("}")
        lines.append(f"export type Create{name}Input = Omit<{name}, 'id' | 'createdAt' | 'updatedAt'>;")
        lines.append(f"export type Update{name}Input = Partial<Create{name}Input>;")
        lines.append("")

        # CRUD functions — all point to /api/data/{slug}
        lines.append(f"export async function get{name}s(opts?: {{ search?: string; [key: string]: any }}): Promise<ListResponse<{name}>> {{")
        lines.append(f"  const params = new URLSearchParams();")
        lines.append(f"  if (opts) Object.entries(opts).forEach(([k, v]) => {{ if (v) params.set(k, String(v)); }});")
        lines.append(f"  return apiRequest(`/api/data/{slug}?${{params}}`);")
        lines.append("}")
        lines.append("")
        lines.append(f"export async function get{name}(id: string): Promise<{name}> {{")
        lines.append(f"  return apiRequest(`/api/data/{slug}/${{id}}`);")
        lines.append("}")
        lines.append("")
        lines.append(f"export async function create{name}(data: Create{name}Input): Promise<{name}> {{")
        lines.append(f"  return apiRequest('/api/data/{slug}', {{ method: 'POST', body: JSON.stringify(data) }});")
        lines.append("}")
        lines.append("")
        lines.append(f"export async function update{name}(id: string, data: Update{name}Input): Promise<{name}> {{")
        lines.append(f"  return apiRequest(`/api/data/{slug}/${{id}}`, {{ method: 'PUT', body: JSON.stringify(data) }});")
        lines.append("}")
        lines.append("")
        lines.append(f"export async function delete{name}(id: string): Promise<void> {{")
        lines.append(f"  await apiRequest(`/api/data/{slug}/${{id}}`, {{ method: 'DELETE' }});")
        lines.append("}")
        lines.append("")
        lines.append(f"export async function get{name}Stats(): Promise<{{ total: number }}> {{")
        lines.append(f"  return apiRequest('/api/data/{slug}/stats');")
        lines.append("}")
        lines.append("")

    path.write_text("\n".join(lines))


def _generate_navigation_flow(path: Path, plan: dict, registry: dict | None = None):
    """Generate src/contracts/navigation-flow.json from plan.user_journeys and plan.pages."""
    models = _plan_models(plan)
    reg_entities = _registry_entities(plan, registry)
    journeys = plan.get("user_journeys", [])

    flow: dict[str, Any] = {"flows": {"entity_crud": {}, "dashboard": {}, "auth": {}}, "navigation": {}}

    # Entity CRUD flows
    for model in models:
        name = model.get("name", "")
        if not name or name in ("User", "WorkflowTask"):
            continue
        # Route/file segment = registry slug (kebab PLURAL); api segment =
        # registry table (camelCase plural). Previously the route used a
        # divergent inline kebab-SINGULAR (`recruitment-drive`) while the api
        # path used `_to_table` — the registry makes both agree on the one base.
        fam = _fam(reg_entities, name)
        slug = fam["slug"]
        table = fam["table"]
        fields = [f.get("name", "") for f in model.get("fields", [])
                  if f.get("name") not in ("id", "createdAt", "updatedAt", "created_at", "updated_at")]

        flow["flows"]["entity_crud"][name] = {
            "list": {
                "route": f"/{slug}",
                "actions": {
                    "search": {"type": "inline", "trigger": "input:search", "effect": "filter_table"},
                    "create": {"target": f"/{slug}/new", "trigger": f"button:New {name}"},
                    "view_detail": {"target": f"/{slug}/{{id}}", "trigger": "table_row_click"},
                    "delete": {"type": "confirm_dialog", "api": f"DELETE /api/data/{table}/{{id}}", "on_success": "refresh+toast:Deleted"},
                },
            },
            "create": {
                "route": f"/{slug}/new",
                "form_fields": fields[:10],
                "submit": {"api": f"POST /api/data/{table}", "on_success": f"redirect:/{slug}+toast:Created", "on_error": "inline_validation"},
                "back": {"target": f"/{slug}", "trigger": "button:Back"},
            },
            "detail": {
                "route": f"/{slug}/{{id}}",
                "actions": {
                    "edit": {"type": "inline_form", "api": f"PUT /api/data/{table}/{{id}}", "on_success": "refresh+toast:Updated"},
                    "delete": {"type": "confirm_dialog", "api": f"DELETE /api/data/{table}/{{id}}", "on_success": f"redirect:/{slug}+toast:Deleted"},
                    "back": {"target": f"/{slug}", "trigger": "button:Back"},
                },
            },
        }

    # Dashboard
    flow["flows"]["dashboard"] = {
        "route": "/dashboard",
        "widgets": {
            "stat_cards": {
                "entities": [m.get("name", "") for m in models if m.get("name") not in ("User", "WorkflowTask")],
                "api": "/api/data/{entity}/stats",
                "click": "navigate:/{entity}",
            },
        },
    }

    # Auth
    flow["flows"]["auth"] = {
        "login": {"route": "/login", "submit": {"api": "signIn('credentials')", "on_success": "redirect:/dashboard"}},
        "signup": {"route": "/signup", "submit": {"api": "POST /api/auth/signup", "on_success": "redirect:/login+toast:Account created"}},
        "logout": {"trigger": "user_menu:Sign Out", "action": "signOut()", "on_success": "redirect:/login"},
    }

    # Navigation
    nav_items = [{"label": "Dashboard", "href": "/dashboard"}]
    for model in models:
        name = model.get("name", "")
        if not name or name in ("User", "WorkflowTask"):
            continue
        slug = _fam(reg_entities, name)["slug"]  # registry slug (kebab plural)
        nav_items.append({"label": name, "href": f"/{slug}"})

    flow["navigation"] = {
        "sidebar_items": nav_items,
        "user_menu": ["Sign Out"],
    }

    path.write_text(json.dumps(flow, indent=2))


def _generate_event_bindings(path: Path, plan: dict, registry: dict | None = None):
    """Generate src/contracts/event-bindings.json from plan.api_strategy."""
    api_strategy = plan.get("api_strategy", {})
    workflows = plan.get("workflows", [])
    models = _plan_models(plan)
    reg_entities = _registry_entities(plan, registry)

    bindings: list[dict] = []

    for entity_name, strategy in api_strategy.items():
        crud = strategy.get("crud", {})
        for op, config in crud.items():
            if isinstance(config, dict) and config.get("triggers_workflow"):
                slug = _fam(reg_entities, entity_name)["table"]
                binding = {
                    "event": f"{entity_name.lower()}_{op}d" if not op.endswith("e") else f"{entity_name.lower()}_{op}d",
                    "source": f"data:{slug}:{op}",
                    "workflows": [config["triggers_workflow"]],
                }
                condition = config.get("condition")
                if condition:
                    binding["conditions"] = [{"field": "status", "changed": True}] if "changed" in condition else []
                    binding["description"] = condition
                bindings.append(binding)

    # Auto-start approval/review workflows on entity creation. Plan workflows at
    # contract time are lightweight ({name, trigger, description, steps}) — no
    # nodes yet — so infer: an approval-like workflow (approve/reject/review/…
    # keywords) that names a known entity gets a `<entity>_created` binding, so
    # creating the entity starts the workflow, which pauses at its approval node
    # and persists a task for the manager to resolve. Matches the Data Engine's
    # emitted event `${entityName.toLowerCase()}_created`.
    existing_created = {(b["event"], w) for b in bindings for w in b.get("workflows", [])}
    for wf in workflows:
        wf_name = wf.get("name", "")
        if not wf_name:
            continue
        entity = _infer_workflow_entity(wf, models)
        if not entity:
            continue
        event = f"{entity.lower()}_created"
        if (event, wf_name) in existing_created:
            continue
        bindings.append({
            "event": event,
            "source": f"data:{entity.lower()}:create",
            "workflows": [wf_name],
            "description": f"Start {wf_name} when a {entity} is created (pauses for approval)",
        })
        existing_created.add((event, wf_name))

    # Ensure every workflow has at least one binding (manual trigger fallback).
    bound_workflows = {w for b in bindings for w in b.get("workflows", [])}
    for wf in workflows:
        wf_name = wf.get("name", "")
        if wf_name and wf_name not in bound_workflows:
            trigger = wf.get("trigger", "")
            bindings.append({
                "event": f"{wf_name.lower()}_trigger",
                "source": f"workflow:{wf_name}",
                "workflows": [wf_name],
                "description": trigger or f"Manual trigger for {wf_name}",
            })

    path.write_text(json.dumps({"bindings": bindings}, indent=2))


_APPROVAL_KEYWORDS = ("approv", "reject", "review", "sign-off", "sign off", "decision", "authoriz")


def ensure_approval_bindings(output_dir, plan: dict) -> dict:
    """Guarantee `src/contracts/event-bindings.json` binds `<entity>_created` to
    each approval/review workflow, so creating the entity auto-starts the workflow
    (which pauses for approval and persists a task).

    The file itself is LLM-authored by the contract agent — this deterministic
    post-pass patches it (or creates it) after the contracts phase, adding only
    the approval start-bindings it's missing. Idempotent. This is the live-path
    home for the logic that `_generate_event_bindings` was never wired to run.
    """
    from pathlib import Path as _Path
    path = _Path(str(output_dir)) / "src" / "contracts" / "event-bindings.json"
    workflows = plan.get("workflows", []) or []
    entities = _plan_models(plan)

    try:
        cfg = json.loads(path.read_text()) if path.exists() else {}
    except Exception:  # noqa: BLE001
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    bindings = cfg.get("bindings")
    if not isinstance(bindings, list):
        bindings = []

    have = {(b.get("event"), w) for b in bindings if isinstance(b, dict) for w in (b.get("workflows") or [])}
    added = 0
    for wf in workflows:
        name = wf.get("name", "")
        entity = _infer_workflow_entity(wf, entities)
        if not name or not entity:
            continue
        event = f"{entity.lower()}_created"
        if (event, name) in have:
            continue
        bindings.append({
            "event": event,
            "source": f"data:{entity.lower()}:create",
            "workflows": [name],
            "description": f"Start {name} when a {entity} is created (pauses for approval)",
        })
        have.add((event, name))
        added += 1

    if added or not path.exists():
        cfg["bindings"] = bindings
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cfg, indent=2))
    return {"added": added, "total": len(bindings)}


def _infer_workflow_entity(wf: dict, entities: list) -> str | None:
    """Return the entity a workflow governs, or None. Only returns a value when
    the workflow reads as an approval/review flow AND its text names a known
    entity — so we never auto-start non-approval workflows on create. When several
    entities match, the longest name wins (most specific)."""
    text = " ".join(str(wf.get(k, "")) for k in ("name", "trigger", "description"))
    text += " " + " ".join(str(s) for s in (wf.get("steps") or []))
    low = text.lower()
    if not any(kw in low for kw in _APPROVAL_KEYWORDS):
        return None
    norm_text = re.sub(r"[^a-z0-9]", "", low)
    best = None
    for e in entities or []:
        name = e.get("name") if isinstance(e, dict) else str(e)
        if not name:
            continue
        if re.sub(r"[^a-z0-9]", "", name.lower()) in norm_text:
            if best is None or len(name) > len(best):
                best = name
    return best


def _generate_seed_plan(path: Path, plan: dict):
    """Generate contracts/seed-plan.json — topological sort + row counts."""
    models = _plan_models(plan)
    relations = plan.get("relations", [])

    # Build dependency graph
    deps: dict[str, set[str]] = {m.get("name", ""): set() for m in models}
    for rel in relations:
        from_entity = rel.get("from", "")
        to_entity = rel.get("to", "")
        if from_entity in deps and to_entity in deps:
            deps[from_entity].add(to_entity)

    # Also check FK fields
    for model in models:
        name = model.get("name", "")
        for field in model.get("fields", []):
            fname = field.get("name", "")
            if fname.endswith("Id") and fname != "id":
                ref_name = fname[:-2]  # userId → User
                ref_name = ref_name[0].upper() + ref_name[1:]
                if ref_name in deps:
                    deps[name].add(ref_name)

    # Topological sort
    sorted_tables: list[dict] = []
    visited: set[str] = set()

    def visit(name: str):
        if name in visited:
            return
        visited.add(name)
        for dep in deps.get(name, set()):
            visit(dep)
        model = next((m for m in models if m.get("name") == name), None)
        if model:
            sorted_tables.append({
                "name": name,
                "order": len(sorted_tables) + 1,
                "row_count": 5 if name == "User" else 10,
                "references": list(deps.get(name, set())),
            })

    for name in deps:
        visit(name)

    seed_plan = {
        "tables": sorted_tables,
        "constraints": {
            "admin_user": {"email": "admin@company.com", "password": "password123", "role": "admin"},
        },
    }

    path.write_text(json.dumps(seed_plan, indent=2))
