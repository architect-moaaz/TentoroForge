"""Smith's tool palette — thin wrappers over existing services.

Smith reuses every read-only inspector from :mod:`services.fix_agent_tools`
(the fix-assistant's Slice 0 palette), and adds:

- :func:`list_components_tool` — read the component library's contract
  catalog (``packages/registry/dist/component-contracts.json``). Smith
  needs to know what components exist and what props they accept before
  proposing a page-schema edit.

Terminal tools Smith can call:

- ``propose_fix(diagnosis)`` — reuses the fix-assistant's Diagnosis
  contract. Streams a FixProposalCard + stashes ``pending_fix``. Works
  for BOTH workflow_node_config and page_schema_patch seams.
- ``answer(text)`` — a plain conversational reply. No side effects.
  Used when the user asks "explain how X works" or "why is Y designed
  that way" — Smith just talks, doesn't change code.
- ``ask_user(question)`` — one focused clarifying question when
  genuinely blocked. Halts the loop.

The catalog itself (:data:`TOOL_CATALOG`) is what Smith sees in his
system prompt — extending it in-place is how new capabilities show up
without touching the agent loop.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from services import fix_agent_tools as fixtools

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Library catalog reader  (the one new tool Smith adds beyond fix_agent_tools)
# --------------------------------------------------------------------------- #

_CATALOG_REL = os.path.join("packages", "registry", "dist", "component-contracts.json")
_MAX_COMPONENT_LIST = 200  # protect the model against a huge dump
_MAX_PROPS_PER_COMPONENT = 20


def _repo_root_candidates(output_dir: Optional[str]) -> list[Path]:
    """Where the library catalog might live. Tried in order.

    - When ``FORGE_LIBRARY_CATALOG`` is set, it is used **exclusively** —
      no fallback. A misconfigured override must fail loudly (available:
      False) rather than silently pick up a different catalog and mislead
      Smith about what components exist.
    - Otherwise: try alongside the backend (dev tree), then alongside
      the generated app (deploy tree).
    """
    env = os.environ.get("FORGE_LIBRARY_CATALOG")
    if env:
        return [Path(env)]

    out: list[Path] = []
    # Walk up from this file to find the sibling `packages/` dir.
    here = Path(__file__).resolve().parent  # backend/services/
    for anc in here.parents:
        out.append(anc / _CATALOG_REL)
        if (anc / "packages").is_dir():
            break
    # Also try above the generated app.
    if output_dir:
        for anc in Path(output_dir).resolve().parents:
            out.append(anc / _CATALOG_REL)
            if (anc / "packages").is_dir():
                break
    return out


def _find_library_catalog(output_dir: Optional[str]) -> Optional[Path]:
    for cand in _repo_root_candidates(output_dir):
        if cand.is_file():
            return cand
    return None


def _load_library_catalog(output_dir: Optional[str]) -> tuple[Optional[dict], Optional[str]]:
    """Return the parsed catalog dict and the path we read it from (or
    ``None, reason``)."""
    path = _find_library_catalog(output_dir)
    if path is None:
        return None, "component-contracts.json not found (looked next to backend/)"
    try:
        return json.loads(path.read_text(encoding="utf-8")), str(path)
    except (OSError, ValueError) as exc:
        return None, f"catalog unreadable: {exc}"


def _summarize_prop(name: str, spec: Any) -> dict:
    """Turn a component-contracts prop entry into a compact model-friendly
    summary. Component-contracts uses ``{type, enum?, optional}`` — we mirror
    that but drop noisy fields."""
    if not isinstance(spec, dict):
        return {"name": name, "type": "unknown"}
    out: dict = {"name": name, "type": spec.get("type") or "unknown"}
    if spec.get("optional") is False:
        out["required"] = True
    if isinstance(spec.get("enum"), list) and spec["enum"]:
        vals = [str(v) for v in spec["enum"][:8]]
        out["enum"] = vals + (["…"] if len(spec["enum"]) > 8 else [])
    return out


def list_pages_tool(output_dir: Optional[str] = None) -> dict:
    """Enumerate every page schema in the app.

    Returns::

        {
          "available": True,
          "pages": [
            {"path": "src/schemas/assessments.json", "route": "/assessments",
             "workflowRefs": ["assessmentschedulingworkflow"],
             "fieldCount": 6},
            …
          ],
          "totalCount": 17,
        }

    Smith calls this BEFORE reading a specific page — the slice-1 trace
    showed the model guessing paths like `pages/assessments/index` that
    don't exist. Giving it the full list up front converges faster.
    """
    if not output_dir:
        return {"available": False, "reason": "no output_dir"}
    root = Path(output_dir) / "src" / "schemas"
    if not root.is_dir():
        return {"available": False, "reason": f"no schemas/ dir at {root}"}

    pages: list[dict] = []
    for path in sorted(root.rglob("*.json")):
        rel = str(path.relative_to(output_dir))
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        # workflow refs — reuse fixtools' walker for parity with read_page.
        wf_refs: list[str] = []
        try:
            fixtools._walk_workflow_refs(data, wf_refs)
        except Exception:  # noqa: BLE001
            wf_refs = []
        # field defs
        fields: list[dict] = []
        try:
            fixtools._walk_field_defs(data, fields)
        except Exception:  # noqa: BLE001
            fields = []
        pages.append({
            "path": rel,
            "route": data.get("route"),
            "workflowRefs": list(dict.fromkeys(wf_refs)),  # dedupe, preserve order
            "fieldCount": len(fields),
        })
    return {
        "available": True,
        "pages": pages,
        "totalCount": len(pages),
    }


def list_components_tool(
    output_dir: Optional[str] = None,
    kind: Optional[str] = None,  # reserved for slice 2 (e.g. "input", "layout")
) -> dict:
    """Enumerate every component in the library with a compact prop summary.

    Result::

        {
          "available": True,
          "source": "…/packages/registry/dist/component-contracts.json",
          "components": [
             {"name": "Button", "props": [{"name":"variant","type":"enum",
                                            "enum":["primary","secondary","danger"]}]},
             …
          ],
          "totalCount": 105,
        }

    Or, if the catalog isn't found::

        {"available": False, "reason": "..."}
    """
    catalog, meta = _load_library_catalog(output_dir)
    if catalog is None:
        return {"available": False, "reason": meta or "unknown reason"}

    components: list[dict] = []
    for cname, cspec in catalog.items():
        if not isinstance(cspec, dict):
            continue
        # Drop internal props that pollute the surface.
        keep = [
            (pname, pspec) for pname, pspec in cspec.items()
            if not pname.startswith("_") and pname not in {"children", "className", "style"}
        ]
        # Keep required props first so the model sees them.
        keep.sort(key=lambda kv: (
            0 if (isinstance(kv[1], dict) and kv[1].get("optional") is False) else 1,
            kv[0],
        ))
        props = [_summarize_prop(pname, pspec) for pname, pspec in keep[:_MAX_PROPS_PER_COMPONENT]]
        components.append({"name": cname, "props": props})
        if len(components) >= _MAX_COMPONENT_LIST:
            break

    components.sort(key=lambda c: c["name"])
    return {
        "available": True,
        "source": meta,
        "components": components,
        "totalCount": len(catalog),
    }


# --------------------------------------------------------------------------- #
# Re-exports from fix_agent_tools  (the inspection surface Smith reuses)
# --------------------------------------------------------------------------- #

recall = fixtools.recall
list_workflows = fixtools.list_workflows
read_workflow = fixtools.read_workflow
read_column = fixtools.read_column
analyze_workflow_values_tool = fixtools.analyze_workflow_values_tool
parse_error_tool = fixtools.parse_error_tool
probe_logs_tool = fixtools.probe_logs_tool
probe_endpoint_tool = fixtools.probe_endpoint_tool


# --------------------------------------------------------------------------- #
# read_page — Smith needs the structural outline, not just route+refs.
# --------------------------------------------------------------------------- #

_OUTLINE_MAX_NODES = 80
_OUTLINE_MAX_DEPTH = 6


def _outline_node(node: Any, path: str, out: list[dict], depth: int) -> None:
    """Walk a page-schema tree and emit a flat outline with jsonPointer
    paths — everything Smith needs to author an RFC-6902 patch WITHOUT
    guessing indices."""
    if len(out) >= _OUTLINE_MAX_NODES or depth > _OUTLINE_MAX_DEPTH:
        return
    if isinstance(node, dict):
        t = node.get("type")
        if isinstance(t, str) and t:
            props = node.get("props") if isinstance(node.get("props"), dict) else {}
            # Surface the props most likely to matter to an editor: identity
            # (label / name), data (dataSource / entity), routing (to / href).
            snap = {}
            for k in ("label", "name", "title", "placeholder", "dataSource",
                     "entity", "workflowId", "workflow", "to", "href",
                     "groupBy", "kind"):
                if k in props:
                    snap[k] = props[k]
            item: dict = {"path": path, "type": t}
            if snap:
                item["props"] = snap
            out.append(item)
        # Recurse into children lists (content, children, items, tabs, columns).
        for child_key in ("content", "children", "items", "tabs", "columns", "actions"):
            children = node.get(child_key)
            if isinstance(children, list):
                for i, ch in enumerate(children):
                    _outline_node(ch, f"{path}/{child_key}/{i}", out, depth + 1)
    elif isinstance(node, list):
        for i, ch in enumerate(node):
            _outline_node(ch, f"{path}/{i}", out, depth + 1)


def read_page(output_dir: str, path: str) -> dict:
    """Read a page schema and return route + workflow refs + form fields
    (the fix-agent contract) PLUS a compact structural outline of the
    page's content tree so Smith knows exactly which components exist and
    can author correct RFC-6902 paths in a page_schema_patch.

    Each outline entry is ``{path, type, props?}`` where ``path`` is a
    JSON-pointer-style locator into the raw schema (`/content/0/children/2`).
    Capped at 80 nodes / depth 6 so the response stays token-sized.
    """
    base = fixtools.read_page(output_dir, path)
    if not isinstance(base, dict) or "error" in base:
        return base
    # Re-read the raw JSON to build the outline (fixtools.read_page throws it
    # away). Cheap — the file is already on disk and small.
    rel = base.get("path")
    if not rel:
        return base
    from pathlib import Path as _P
    abs_ = _P(output_dir) / rel
    try:
        raw = json.loads(abs_.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return base
    outline: list[dict] = []
    if isinstance(raw, dict):
        # Real generated pages use `root` as the tree; some older/thinner
        # ones use `content`. Whichever exists, walk it and label the
        # jsonPointer paths accordingly so RFC-6902 ops target the right key.
        for root_key in ("root", "content"):
            if root_key in raw:
                _outline_node(raw.get(root_key), f"/{root_key}", outline, 1)
                break
    base["outline"] = outline
    return base


# --------------------------------------------------------------------------- #
# Tool catalog — what Smith sees in his system prompt.
# --------------------------------------------------------------------------- #

TOOL_CATALOG: list[dict] = [
    # Inspection ---------------------------------------------------------
    {"name": "recall",
     "signature": "recall() -> {promptBlock, entities, roles}",
     "desc": "Why the app exists: intent, entities, roles, recent history."},
    {"name": "list_workflows",
     "signature": "list_workflows() -> {workflows:[{id,path,name}]}",
     "desc": "Enumerate every workflow file (path relative to output_dir)."},
    {"name": "read_workflow",
     "signature": "read_workflow(path) -> {name, nodes, edges}",
     "desc": "Load a workflow; inspect its nodes and their config.values."},
    {"name": "list_pages",
     "signature": "list_pages() -> {pages:[{path, route, workflowRefs, fieldCount}]}",
     "desc": "Enumerate every page schema (src/schemas/*.json). CALL THIS "
             "BEFORE `read_page` — never guess a page path."},
    {"name": "read_page",
     "signature": "read_page(path) -> {route, workflowRefs, fields, outline:[{path,type,props}]}",
     "desc": "Load a page/form schema; see button→workflow refs, field "
             "controls, AND a compact tree outline with jsonPointer paths "
             "for every component (use those paths verbatim in "
             "page_schema_patch RFC-6902 ops)."},
    {"name": "read_column",
     "signature": "read_column(entity, column) -> {type, notNull, fk}",
     "desc": "SQL type + FK target of a column from the resource registry."},
    {"name": "check_data_source",
     "signature": "check_data_source(path) -> {path, route, dataSources, violations, peer_hints}",
     "desc": "Validate every dataSource on a page against the per-op "
             "shape rules (get carries no filter, list uses filter not "
             "where, aggregate needs metrics, series needs groupBy+"
             "metric) AND against the resource registry (entity must "
             "resolve). Attaches peer-shape hints from Slice 12A. Call "
             "this FIRST when the user says an X page is empty, "
             "unbound, or only shows the id — it names the exact "
             "dataSource key that's wrong."},
    {"name": "list_components",
     "signature": "list_components() -> {components:[{name, props}]}",
     "desc": "Enumerate every component in the library with its prop schema. "
             "Look this up BEFORE proposing a page_schema_patch that adds a "
             "new component — you must reference a component that exists."},
    # Cross-file scan tools — locate by CONTENT, not by guessing paths.
    {"name": "grep_schemas",
     "signature": "grep_schemas(pattern, case_sensitive?) -> {matches:[{path,count,previews}]}",
     "desc": "Case-insensitive substring scan across every page schema + "
             "workflow JSON. Use FIRST when the user names a field label "
             "(\"CV Upload\"), an element (\"Approve button\"), or any "
             "text they can see on the screen — locate the file(s) before "
             "guessing paths."},
    {"name": "find_component",
     "signature": "find_component(component) -> {usages:[{path,count,fields}]}",
     "desc": "Every page that uses a given component (e.g. `Select`, "
             "`FileUpload`, `Kanban`). Returns paths + field names each "
             "usage sits on. Use before swapping a component to see what "
             "else it touches."},
    {"name": "list_entities",
     "signature": "list_entities() -> {entities:[{name,table,columns:[{name,type,notNull,fk}]}]}",
     "desc": "Full domain data model from the resource registry — "
             "entities + columns + FKs. Consult BEFORE proposing an "
             "add_page or add_entity so you build ON the schema that "
             "actually exists."},
    {"name": "read_entity",
     "signature": "read_entity(name) -> {entity:{name,table,columns:[…]}}",
     "desc": "One entity by name. Complements list_entities when you "
             "want the full column detail on a specific entity."},
    # SMITH-SOURCE-1 — map a symptom to the backend generator responsible.
    {"name": "find_source_generator",
     "signature": "find_source_generator(symptom) -> {matched, modules:[…], "
                  "hint, recommendation}",
     "desc": "Map a bug SYMPTOM description (in the user's words) to the "
             "backend emitter module(s) most likely responsible. Use BEFORE "
             "editing when the symptom sounds systemic ('every status "
             "dropdown', 'all detail pages'). recommendation is either "
             "'propose_source_fix' (systemic → suggest a source-code task, "
             "don't N-edit) or 'in_place_edit_ok' (single artifact → normal "
             "edit_page/edit_workflow). Returns modules with file paths so "
             "your reply can name where the source fix belongs."},
    # PLATFORM-HEALS — deterministic in-place repair of known
    # platform-regression classes. Symptom vocabulary → this tool:
    #   "everything is cramped / no space between components"
    #   "KPI cards squeezed into 2 columns / grid collapsed"
    #   "server shows null but the API returns the value"
    #   "KPI breakdowns are 0 while the total is right"
    #   "filter dropdown lists statuses that don't exist"
    {"name": "heal_platform_regressions",
     "signature": "heal_platform_regressions() -> {template_runtime, skin_css, "
                  "tailwind_safelist, engine_token_prefix, dashboard_rhythm, "
                  "filter_enums, tokens, changed}",
     "desc": "Run every known platform heal on this app IN PLACE: re-sync "
             "template-owned runtime files (rules engine grant semantics, "
             "data-engine bridge), strip skin CSS that force-collapses KPI "
             "grids with !important, ensure the Tailwind grid-cols safelist, "
             "backfill numeric spacing tokens, patch the vendored engine's "
             "--token- CSS-var prefix, floor cramped dashboard rhythm, and "
             "align dashboard filter dropdowns to the plan's REAL enum "
             "values. Call this FIRST for layout/spacing complaints "
             "('cramped', 'no gaps', 'squeezed'), redacted-field symptoms "
             "('shows null but API has data', 'breakdown KPIs are 0'), or "
             "impossible filter options — one call fixes the whole class, "
             "then re-check before hand-editing schemas. Idempotent and "
             "safe on healthy apps (reports changed:false)."},
    # PHASE-3 design brief tools — read + patch the app's aesthetic
    # contract. `get_brief` for questions like "what colors are we using?";
    # `edit_brief` for asks like "make it more compact" or "change the
    # accent to green". Both are cheap file ops; token recompile is a
    # follow-up cascade.
    {"name": "get_brief",
     "signature": "get_brief() -> {domain, register, palette, typography, "
                  "layout, signature_moves, anti_patterns} | null",
     "desc": "Return the app's current design brief (from "
             "contracts/brief.json). Null when no brief has been "
             "authored yet — Discovery must have run with "
             "FORGE_BRIEF_AUTHOR=1. Use before proposing aesthetic "
             "edits so you know the starting point."},
    {"name": "edit_brief",
     "signature": "edit_brief(patch) -> {applied: bool, before, after} | error",
     "desc": "Apply a partial patch to the design brief. `patch` is a "
             "nested dict matching the brief schema — only supplied "
             "paths are overwritten. Lists (signature_moves, "
             "anti_patterns) are REPLACED wholesale. Base antipatterns "
             "always survive. Examples: {\"layout\":{\"density\":"
             "\"compact\"}} makes it more compact; {\"palette\":"
             "{\"brand\":\"#4A7A3E\"}} changes brand color. Use for "
             "aesthetic asks; token recompile happens as a follow-up."},
    # Smith Auto-Act (S2) — scored decision that replaces the "which page?"
    # punt. Prefer this over find_resources when the user's ask is
    # label-shaped ("change the Status field", "make Priority a badge")
    # and could plausibly land on more than one page.
    {"name": "resolve_target",
     "signature": "resolve_target(query, label?, current_route?, recent_edits?) -> "
                  "{kind: act|act_all|chip|ask, targets:[{kind, route, "
                  "path, matched_by, excerpt}], reason, scores}",
     "desc": "Score candidates + return a decision. `kind=act` means "
             "proceed on the one target confidently (typically because "
             "current_route matches). `act_all` means the query said "
             "\"everywhere\"/\"on all pages\" — apply to every match. "
             "`chip` returns 2-4 near-equal candidates; present them "
             "as a picker. `ask` means no good candidates or too many "
             "weak ones — fall back to prose. Pass current_route from "
             "your <smith-current-context> block when it's set, and "
             "recent_edits from <smith-recent-edits> when present — "
             "both narrow the decision on the page the user actually "
             "cares about."},
    # SMITH-SEARCH-1 — the one-call graph lookup Smith reaches for FIRST
    # when the user names an entity or feature.
    {"name": "find_resources",
     "signature": "find_resources(query) -> {matched_entity, confidence, "
                  "pages:[{route, schema_path, kind}], workflows:[{name, "
                  "path}], fks_out, fks_in, hint}",
     "desc": "Single-call graph lookup for an entity or feature phrase. "
             "Accepts entity Pascal name (\"RecruitmentDrive\"), snake "
             "table (\"recruitment_drives\"), slug (\"drives\"), or a "
             "plain-English phrase (\"recruitment drive\"). Returns EVERY "
             "page, workflow, and FK dependency in one payload so you "
             "don't burn tool calls hunting them individually. CALL THIS "
             "FIRST whenever a user asks about a domain object — the "
             "graph slice tells you which of N pages to touch and which "
             "dependents will break. `hint` is a one-line summary; "
             "`confidence` is \"exact\"/\"alias\"/\"route-stem\"/\"fuzzy\" — "
             "prefer confirming scope with the user when confidence "
             "isn't exact AND >1 page matches."},
    # ── Delegated mutation sub-agent ──────────────────────────────
    {"name": "_tool_app_modifier",
     "signature": "_tool_app_modifier(ask, blueprint_summary?) -> {status, summary, files_touched, registry_delta, validation, trace}",
     "desc": "Delegate a MUTATION ask to the sandboxed Read/Bash/Edit/"
             "Write/RegistryPatch sub-agent. Use this whenever the user "
             "asks to CHANGE, ADD, REMOVE, or FIX something in the app "
             "— it enforces the 7-step ordering (read registry → read "
             "contract → find files → impact analysis → modify → "
             "validate → update registry+plan+contracts) that the "
             "reasoning-only tools do not. It runs its OWN 20-tool-call "
             "budget and returns a structured envelope; you narrate the "
             "``summary`` back to the user. Pass ``ask`` verbatim from "
             "the user."},
    {"name": "analyze_workflow_values",
     "signature": "analyze_workflow_values(path) -> {findings:[…]}",
     "desc": "Type-check a workflow's db_insert/db_update value bindings."},
    {"name": "parse_error",
     "signature": "parse_error(text) -> {kind, workflow?, table?, column?}",
     "desc": "Extract structured locators from a pasted error string."},
    {"name": "probe_logs",
     "signature": "probe_logs(lines=200) -> {available, evidence}",
     "desc": "Read the tail of the app's server log if one exists."},
    {"name": "probe_endpoint",
     "signature": "probe_endpoint(url) -> {available, evidence}",
     "desc": "Bounded localhost GET (only localhost allowed)."},

    # Claude-Code-style tools — direct file work, no seam ---------------
    # Prefer these when the user's ask is a specific, targeted edit
    # (rename a field, remove a widget, tweak a label). Use the seam
    # tools (propose_fix + page_schema_patch) when you want the platform
    # to run guards + repair passes after your edit.
    {"name": "read_file",
     "signature": "read_file(path) -> {content, lines, truncated}",
     "desc": "Return the literal bytes of a file under the generated app. "
             "Use this INSTEAD of read_page when you need exact strings "
             "you're about to edit — read_page returns a structural "
             "summary, not the actual text on disk."},
    {"name": "edit_file",
     "signature": "edit_file(path, old_string, new_string) -> {edited, matches_replaced}",
     "desc": "Exact-string replace. `old_string` MUST be unique in the "
             "file — refuses ambiguous matches so you can't silently "
             "overwrite the wrong region. Call read_file first, copy the "
             "exact bytes you want to change, and edit against that "
             "verbatim. Chain multiple edit_file calls for multi-region "
             "changes; each call must appear coherent to verify_promise."},
    {"name": "verify_promise",
     "signature": "verify_promise(path, claim) -> {kept, failures?, reason}",
     "desc": "Re-read the file and check whether a plain-language claim "
             "holds. `claim` is your INTENT (\"the password field is "
             "removed\", \"a status dropdown was added\"). Call AFTER "
             "each edit_file to prove the promise landed — don't self-"
             "report \"Done\" until verify_promise returns kept:true."},

    # Orchestrator-era tools --------------------------------------------
    {"name": "understand_ask",
     "signature": "understand_ask({verb, ...fields for that verb, "
                  "confidence?, clarification_needed?})",
     "desc": "REQUIRED first tool for any change ask (skip for "
             "greetings/meta questions). CHOOSE THE VERB FIRST — each "
             "needs different facts, and a request forced into the "
             "wrong one fails as 'nothing to change':\n"
             "  rename        {screen, element_label, current_behavior, "
             "desired_behavior, target_file} — change the wording of "
             "something that exists.\n"
             "  compose_route {route} — build or rebuild the screen at a "
             "route. Use this when a route renders nothing.\n"
             "  add_widgets   {route, widgets:[...]} — add named sections "
             "to a screen: 'put upcoming sessions and quorum status on "
             "the dashboard'.\n"
             "  rebuild       {} — regenerate the whole application from "
             "its definition.\n"
             "Omitting `verb` means rename. If you can't confidently fill "
             "the verb's fields, use read_page / list_pages first; if the "
             "ask itself is ambiguous, set `clarification_needed` and "
             "follow up with ask_user. Only SKIP understand_ask for "
             "greeting/explain turns — every edit turn is gated on it."},
    {"name": "think",
     "signature": "think(thought) -> {recorded, chars}",
     "desc": "Private reasoning step. No-op side-effects; the thought "
             "persists in your conversation history for subsequent "
             "turns. Use to plan multi-step actions, cross-reference "
             "facts, or reason about ambiguity WITHOUT burning an "
             "inspection or edit call. Cheap; use liberally when the "
             "next action isn't obvious. Not counted as a mutation."},
    {"name": "edit_page",
     "signature": "edit_page(path, intent) -> {applied, edited_paths, "
                  "diff_summary, reason?}",
     "desc": "LLM-DRIVEN page-schema edit — the correct tool for any "
             "change to a page schema (add/remove/rename a field, "
             "switch a control's TYPE like Select→FileUpload, tweak "
             "PROPS, add sections). Pass the schema file path + the "
             "user's INTENT in plain English — a sub-agent reads the "
             "current schema, the app-map, and the component registry, "
             "then emits the coherent new schema. NO deterministic "
             "'authority' guards run after, so the intent sticks. "
             "Examples: intent=\"Change CV Upload to FileUpload "
             "accepting PDF/DOC\" or \"Add a passport number field "
             "after nationality\"."},
    {"name": "add_page",
     "signature": "add_page(archetype, entity, route, title?, "
                  "features?, fields?) -> {applied, changes, verify, "
                  "edited_paths}",
     "desc": "Create a WHOLE NEW page against an existing entity "
             "(list/detail/create/edit/dashboard/kanban/calendar/etc). "
             "Composes schema + route glue via add_page_seam; writes "
             "atomically with rollback on failure. Use when list_pages "
             "shows no matching page for the ask. Skip when you're "
             "modifying an existing page — use edit_page instead."},
    {"name": "remove_page",
     "signature": "remove_page(route, cascade?, _confirmed?) -> "
                  "{status: 'needs_confirmation'|'ok', ...}",
     "desc": "Inverse of add_page. Deletes the schema at ROUTE (and "
             "every archetype under it when cascade=true — the whole "
             "feature area). Strips matching nav-flow entries + "
             "transitions and regenerates registry.ts + sidebar so the "
             "app dispatcher stops trying to import the deleted file. "
             "Atomic with rollback. Use for 'remove X feature' asks."},
    {"name": "add_workflow",
     "signature": "add_workflow(op, entity, name?) -> {applied, "
                  "changes, verify, edited_paths}",
     "desc": "Create a new CRUD workflow (op ∈ create|update|delete) "
             "against an existing entity. Composes the JSON via "
             "add_workflow_seam and validates it before writing."},
    {"name": "use_21st_component",
     "signature": "use_21st_component(path, description, hint?) -> "
                  "{applied, edited_paths, diff_summary, source: '21st', reason?}",
     "desc": "Fetch a hand-designed React/Tailwind component from the "
             "21st.dev catalog (Magic MCP), convert it to a schemaVersion:2 "
             "fragment via LLM, and splice it into an existing page. Use "
             "when the user asks for a visually-designed pattern the "
             "library primitives don't cover elegantly — 'add a pricing "
             "card grid', 'hero with product screenshot', 'feature "
             "comparison table', 'testimonial carousel'. Requires "
             "FORGE_21ST_MCP=on + FORGE_21ST_API_KEY (returns applied:False "
             "with a clear reason when unavailable). Gracefully falls back "
             "to nothing on 21st failure — retry with edit_page in that "
             "case. path = schema file being edited. description = plain "
             "English component description ('wellness studio dashboard "
             "header with 4 metric tiles'). hint = optional context "
             "(domain, palette, brand voice)."},
    {"name": "wire_form_to_workflow",
     "signature": "wire_form_to_workflow(page_route, workflow_name, "
                  "field_map?) -> {applied, page_path, wf_path, changes}",
     "desc": "Wire an EXISTING form's submit to an EXISTING workflow. "
             "Reads both artifacts, derives the field→input map (identity "
             "by default; pass field_map to override), and updates both "
             "files atomically: Form.props.workflow=<name> on the page, "
             "trigger.type=form + source declaration on the workflow, "
             "plus mirroring page.submit + workflow.source + inputs[].source "
             "back to plan.json. Use for RETROFITTING orphan workflows "
             "or manually connecting an unwired form to a workflow. "
             "For NEW features that need both a page AND a workflow, "
             "use plan_and_apply."},
    {"name": "set_field_interaction",
     "signature": "set_field_interaction(page, field, interaction?, mode?='merge') "
                  "-> {applied, edited_paths, diff_summary, reason?}",
     "desc": "Author reactive form behaviour — computed fields, cascade "
             "dropdowns, autofill on change, conditional visibility. "
             "SCHEMA IS ALREADY LIVE — the runtime hooks "
             "(useComputedFields/useDependentOptions/useOnChangePopulate) "
             "consume the interaction block you write here. Use this for "
             "asks like 'when X changes → Y', 'compute X from Y', "
             "'refresh dropdown based on', 'auto-fill'. NEVER hand off "
             "to refiner — the validator returns actionable errors; if "
             "unknown-field/function, retry with correction.\n\n"
             "interaction shape:\n"
             "  {\n"
             "    computed?:    {formula: str, readOnly?: bool},\n"
             "    optionsFrom?: {source: str, value: str, label: str, filter?: dict},\n"
             "    onChange?:    {fetch: {resource, by, from}, set: dict},\n"
             "    dependsOn?:   list[str]  (auto-derived from formula/filter),\n"
             "    visibleIf?/requiredIf?/enabledIf?/readOnlyIf?: predicate str\n"
             "  }\n"
             "modes: merge (default, unions keys), replace (drops old), "
             "remove (deletes the interaction block; interaction arg ignored).\n\n"
             "Canonical examples:\n"
             "  • 'make HRA 40% of basic' →\n"
             "      page=<form>, field='hra', interaction={computed:{formula:'basicSalary * 0.4'}}\n"
             "  • 'when I pick a country, refresh states' →\n"
             "      page=<form>, field='state', interaction={optionsFrom:{source:'states', "
             "value:'id', label:'name', filter:{countryId:'{{country}}'}}}\n"
             "  • 'when a customer is selected, fill address+phone' →\n"
             "      page=<form>, field='customerId', "
             "interaction={onChange:{fetch:{resource:'customers',by:'id',from:'customerId'}, "
             "set:{address:'{{result.address}}', phone:'{{result.phone}}'}}}\n"
             "  • 'remove the computed formula on HRA' →\n"
             "      page=<form>, field='hra', mode='remove'"},
    {"name": "create_business_rule",
     "signature": "create_business_rule(name, rule_type, model_name?, field_name?, config) "
                  "-> {applied, rule_id, exported, edited_paths, summary}",
     "desc": "Author a BUSINESS RULE (project_rules) — cross-cutting data logic "
             "that the runtime rules engine enforces on EVERY create/update of "
             "an entity (both the data-engine and workflow write paths), and "
             "that shows up in the editor's Rules panel. Persists to the DB and "
             "immediately ships rules/index.json into the app — no regeneration.\n"
             "USE THIS (not set_field_interaction) when the user wants a rule "
             "that GUARDS or DERIVES data model-wide: 'reject orders over $10k', "
             "'require a customer on every invoice', 'total = qty × price', "
             "'employees must be 18+', 'status defaults to draft'.\n"
             "vs set_field_interaction: that one is for a SINGLE FORM FIELD's "
             "reactive UI behaviour (cascade dropdowns, autofill-on-change, "
             "show/hide one field). A business rule is server-enforced on the "
             "DATA, applies to all writes, and is visible in the Rules editor.\n\n"
             "rule_type + config shapes:\n"
             "  validation → {expression|min|max|required, errorMessage}  (reject bad writes)\n"
             "  computed   → {expression}                                  (field_name required; derive a value)\n"
             "  business   → {expression, trigger:'on_create'|'on_update', errorMessage}  (guard)\n"
             "  condition_action → {whenFeel, then:[{type,...}], otherwise:[], scope, salience}\n"
             "config expressions use FEEL-lite over the entity's fields.\n\n"
             "Canonical examples:\n"
             "  • 'reject orders over $10,000' →\n"
             "      name='order-cap', rule_type='validation', model_name='Order',\n"
             "      config={expression:'total <= 10000', errorMessage:'order exceeds the $10k cap'}\n"
             "  • 'order total should be quantity times unit price' →\n"
             "      name='order-total', rule_type='computed', model_name='Order', field_name='total',\n"
             "      config={expression:'quantity * unitPrice'}\n"
             "  • 'every invoice needs a customer' →\n"
             "      name='invoice-customer-required', rule_type='business', model_name='Invoice',\n"
             "      config={expression:'customerId != null', trigger:'on_create', errorMessage:'customer is required'}"},
    {"name": "add_entity",
     "signature": "add_entity(name, fields, table?) -> {applied, "
                  "changes, verify, edited_paths}",
     "desc": "Create a new entity: registry entry + Drizzle schema + "
             "barrel export. `fields` is a list of {name, type, "
             "notNull?, ...}. Rolled back atomically on failure. "
             "Follow up with add_page(archetype='create', entity=<new>, "
             "…) to give it a UI."},
    {"name": "plan_and_apply",
     "signature": "plan_and_apply(ask) -> {status, plan, steps, edited_paths}",
     "desc": "One call for ADD-A-FEATURE asks that span multiple seams "
             "(new entity + list page + create page + workflow + wiring). "
             "Translates the natural-language ask into an ordered 3-5 "
             "step plan (add_entity → add_page(list) → add_page(create) "
             "→ add_workflow → wire_form_to_workflow), executes each "
             "step deterministically, and returns a single result you "
             "can report. Prefer this over 5 separate turns for feature "
             "asks — the user sees one clean 'here's what I'll do' plan, "
             "one progress stream, and one 'done, here's what changed' "
             "summary. If ANY step fails, the result includes the "
             "failing step so you can retry or ask the user."},
    {"name": "impact_analysis",
     "signature": "impact_analysis({entity|field?, page?, workflow?}) -> "
                  "{impact, summary}",
     "desc": "Blast-radius report BEFORE you touch anything cross-cutting. "
             "For an entity/field change, lists every page/workflow/api "
             "route that reads or writes it, plus contracts and env "
             "requirements it implies (e.g. a `photo`/`cv` field means "
             "S3_BUCKET must be set). Cheapest way to spot second-order "
             "damage — run it whenever your edit could ripple past one "
             "file."},
    {"name": "edit_workflow",
     "signature": "edit_workflow(workflow_id, changes) -> "
                  "{success, applied?, violations?, error?}",
     "desc": "Structured edit of an EXISTING workflow — the sibling of "
             "page_schema_patch for workflows. `changes` is a list of ops: "
             "add_trigger_input, remove_trigger_input, set_step_config, "
             "add_step, remove_step, rewire, rename. Runs plan_validator "
             "before write — refuses to break the workflow. Prefer this "
             "over edit_file on any `workflows/*.json`."},
    {"name": "run_guards",
     "signature": "run_guards() -> {green, failures[], summary}",
     "desc": "Run the full post-generate guard suite (mutation-input "
             "coverage, seed-synth, action-contract, FK source, read-"
             "binding, etc.) and return a machine-readable verdict. Call "
             "AFTER your edits land to catch second-order breakage the "
             "orchestrator will otherwise surface on its own critic turn."},

    # Terminals ----------------------------------------------------------
    {"name": "propose_fix",
     "signature": "propose_fix(diagnosis) -> terminates the loop",
     "desc": "Present a fix (workflow_node_config OR page_schema_patch). "
             "Streams a FixProposalCard with an Apply button. Prefer this "
             "over answer() any time you want to CHANGE existing code."},
    {"name": "handoff_to_pipeline",
     "signature": "handoff_to_pipeline(kind, message) -> terminates the loop",
     "desc": "Hand off to the platform's existing build pipeline. "
             "kind=\"discovery\" runs the domain-research agent (use when "
             "the user is describing a NEW app to build); kind=\"planner\" "
             "runs the planner (post-discovery); kind=\"refine\" runs the "
             "code-editing refiner for a scoped change beyond your seams. "
             "`message` is what you want to hand off — typically the user's "
             "original message (or a rephrased version)."},
    {"name": "answer",
     "signature": "answer(text) -> terminates the loop",
     "desc": "Reply conversationally with no code change. Use for "
             "greetings, meta questions ('who are you?', 'what can you do?'), "
             "explanations, and short discussions. Keep it warm and short."},
    {"name": "ask_user",
     "signature": "ask_user(question) -> terminates the loop",
     "desc": "Ask ONE focused clarifying question when you cannot localize "
             "the issue or when the user's request is genuinely ambiguous."},
    {"name": "publish",
     "signature": "publish(target='vercel') -> {ok, target, message}",
     "desc": "Deploy the current generated app to Vercel using the same "
             "pipeline the human Publish button uses. Kicks off in the "
             "background and returns immediately — the user watches the "
             "toolbar's Publish button for the live URL. Only call when "
             "the user explicitly asks to publish/deploy/ship the app."},

    {"name": "generate_mobile_app",
     "signature": "generate_mobile_app(platform='android', profile='preview') -> "
                  "{ok, build_id, poll_url, message}",
     "desc": "Queue an Expo EAS build of the mobile shell for this app. "
             "platform is 'android' or 'ios'. profile is 'preview' "
             "(installable APK / device IPA — the default; also "
             "'preview-simulator' for an iOS Simulator IPA) or "
             "'production' (store-ready AAB / IPA). Kicks off the same "
             "background build the Publish dialog's Mobile-app tab uses — "
             "returns immediately with the build row id + poll URL. Only "
             "call when the user explicitly asks to build/generate the "
             "APK, IPA, Android app, or iOS app. Requires the project "
             "to have a deployed URL + EAS credentials configured in "
             "Settings → Integrations; missing pieces surface as a clear "
             "error in the return."},

    {"name": "revert_last_patch",
     "signature": "revert_last_patch() -> "
                  "{ok, reverted_sha, files, summary}",
     "desc": "Reverse the most recent commit as a NEW commit — the "
             "underlying seam for 'undo that' / 'actually no, don't do "
             "that'. History-preserving (original commit stays in git "
             "log). Use ONLY when the user asks to undo or the previous "
             "patch was wrong. Does not touch anything else. Never call "
             "speculatively — a revert IS a mutation and shows up in "
             "the app's git history."},

    {"name": "add_role",
     "signature": "add_role(role_name) -> {ok, added, actors}",
     "desc": "Add a role (e.g. 'Editor', 'Admin', 'Viewer') to the "
             "app's actor list. Idempotent — a role that already "
             "exists (case-insensitive) is not duplicated. Persists "
             "to plan.json under `actors`."},

    {"name": "remove_role",
     "signature": "remove_role(role_name) -> "
                  "{ok, removed, actors, affected_pages}",
     "desc": "Remove a role from the app's actor list. Reports which "
             "pages had that role in their access.roles so the user "
             "can be warned before proceeding. Combine with the "
             "confirmation gate for destructive UX."},

    {"name": "restrict_page_to_role",
     "signature": "restrict_page_to_role(page_route, role_name) -> "
                  "{ok, page, roles}",
     "desc": "Add a role gate to a page — sets `access.roles` on the "
             "page in plan.json so only that role (plus any existing "
             "roles) can reach it. Idempotent: repeats don't duplicate."},

    # SV-9 — Self-Verify Pass -------------------------------------------
    {"name": "verify_app",
     "signature": "verify_app(scope?, target?, fix?) -> {run_id, status, "
                  "interactions_run, interactions_passed, faults_count, remediation}",
     "desc": "Run the Self-Verify Pass on this app (real headless-browser "
             "click-through via forge-verify). Use whenever the user asks "
             "\"does it work\", \"test the flow\", \"why isn't X clicking\", "
             "\"verify my deployed app\", or wants confidence the app is "
             "green. DO NOT attempt manual verification via file reads — "
             "the runner is authoritative and reproduces real defects. "
             "Args: scope = '*' or route glob (default '*'); target = "
             "'preview' | 'deploy' (default 'preview'); fix = true → "
             "Smith fixes classified faults in ≤3 rounds (default true). "
             "Returns a RemediationReport summary you should paraphrase to "
             "the user."},

    # JV-8 — surface the last verify run's structured report so Smith can
    # answer follow-up questions ("what went wrong on /scan?", "which
    # workflow failed?") without re-running the whole pass.
    {"name": "read_last_verify_run",
     "signature": "read_last_verify_run() -> {run_id, status, "
                  "interactions:{run,passed,faults_count}, faults:[...], "
                  "journey:{first_run,autofix,second_run}}",
     "desc": "Read the structured report of the MOST RECENT Verify run for "
             "this app. Use when the user asks a follow-up about a verify "
             "that already happened (\"why did the scan fail?\", \"which "
             "workflow was broken?\", \"what did autofix change?\"). Faster "
             "than re-running verify_app. Returns per-journey status, "
             "remediation hints with target_seam, autofix dispatch results, "
             "and interaction fault classifications. If no verify has run "
             "yet returns {\"error\": \"no_runs\"}."},
]


# Convenience map for the agent dispatch table (mirrors fix_chat_agent's
# _READONLY_TOOLS so smith_agent can build its own dispatcher off it).
def grep_schemas_tool(output_dir: str, pattern: str, *, case_sensitive: bool = False) -> dict:
    """Search every JSON file under ``src/schemas/`` + ``workflows/`` for
    ``pattern``. Returns ``{matches: [{path, count, previews:[str]}]}``
    so Smith can find "where is CV Upload rendered?" without knowing
    the file path in advance."""
    from pathlib import Path
    import re as _re

    if not pattern or not isinstance(pattern, str):
        return {"matches": [], "error": "empty pattern"}
    root = Path(output_dir)
    if not root.exists():
        return {"matches": [], "error": "output_dir missing"}

    flags = 0 if case_sensitive else _re.IGNORECASE
    try:
        rx = _re.compile(_re.escape(pattern), flags)
    except _re.error as exc:
        return {"matches": [], "error": f"bad pattern: {exc}"}

    matches: list[dict] = []
    for sub in ("src/schemas", "workflows"):
        p = root / sub
        if not p.is_dir():
            continue
        for f in p.rglob("*.json"):
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            hits = list(rx.finditer(text))
            if not hits:
                continue
            previews: list[str] = []
            for m in hits[:3]:
                start = max(0, m.start() - 40)
                end = min(len(text), m.end() + 40)
                previews.append(text[start:end].replace("\n", " "))
            matches.append({
                "path": str(f.relative_to(root)),
                "count": len(hits),
                "previews": previews,
            })
    return {"matches": matches[:30], "total": len(matches), "pattern": pattern}


def find_component_tool(output_dir: str, component: str) -> dict:
    """Find every page schema that uses ``component`` (e.g. ``Select``,
    ``FileUpload``, ``Kanban``). Returns ``{usages: [{path, count, fields:[..]}]}``
    with the field names/props each usage sits on so Smith can decide
    whether a swap needs prop cleanup."""
    from pathlib import Path
    import json as _json

    if not component:
        return {"usages": [], "error": "empty component name"}
    root = Path(output_dir) / "src" / "schemas"
    if not root.is_dir():
        return {"usages": [], "error": "no src/schemas"}

    def _walk(node, out_hits: list[dict], breadcrumb: str = ""):
        if isinstance(node, dict):
            t = node.get("type")
            if isinstance(t, str) and t == component:
                fname = node.get("props", {}).get("field") or node.get("props", {}).get("name") or node.get("id") or ""
                out_hits.append({"field": str(fname), "at": breadcrumb})
            for k, v in node.items():
                _walk(v, out_hits, f"{breadcrumb}/{k}" if breadcrumb else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                _walk(v, out_hits, f"{breadcrumb}[{i}]" if breadcrumb else f"[{i}]")

    usages: list[dict] = []
    for f in root.rglob("*.json"):
        try:
            spec = _json.loads(f.read_text(encoding="utf-8"))
        except (OSError, _json.JSONDecodeError):
            continue
        hits: list[dict] = []
        _walk(spec, hits)
        if hits:
            usages.append({
                "path": str(f.relative_to(Path(output_dir))),
                "count": len(hits),
                "fields": [h["field"] for h in hits if h["field"]][:8],
            })
    return {"usages": usages[:30], "total": len(usages), "component": component}


def list_entities_tool(output_dir: str) -> dict:
    """Return every entity from ``contracts/resource-registry.json`` (or
    fallback ``registry.json``). Shape:
    ``{entities: [{name, table, columns:[{name, type, notNull, fk}]}]}``.
    Smith uses this to understand the domain data model without
    walking Drizzle schema files."""
    from pathlib import Path
    import json as _json

    root = Path(output_dir)
    for cand in ("contracts/resource-registry.json", "registry.json"):
        p = root / cand
        if not p.exists():
            continue
        try:
            reg = _json.loads(p.read_text(encoding="utf-8"))
        except (OSError, _json.JSONDecodeError):
            continue
        raw_entities = reg.get("entities")
        if isinstance(raw_entities, dict):
            # registry.json shape: {"entities": {"Candidate": {fields:{…}}}}
            out: list[dict] = []
            for name, e in raw_entities.items():
                fields = e.get("fields") or {}
                cols = [
                    {"name": fn, "type": (fs or {}).get("type"),
                     "notNull": (fs or {}).get("notNull") or (fs or {}).get("required"),
                     "fk": (fs or {}).get("references") or (fs or {}).get("fk")}
                    for fn, fs in (fields.items() if isinstance(fields, dict) else [])
                ]
                out.append({"name": name, "table": e.get("table"), "columns": cols[:12]})
            return {"entities": out, "source": cand}
        if isinstance(raw_entities, list):
            out = []
            for e in raw_entities:
                if not isinstance(e, dict) or not e.get("name"):
                    continue
                cols = [
                    {"name": c.get("name"), "type": c.get("type"),
                     "notNull": c.get("notNull"), "fk": c.get("references")}
                    for c in (e.get("columns") or [])
                    if isinstance(c, dict)
                ]
                out.append({"name": e["name"], "table": e.get("table"),
                            "columns": cols[:12]})
            return {"entities": out, "source": cand}
    return {"entities": [], "error": "no registry found"}


def read_entity_tool(output_dir: str, name: str) -> dict:
    """One entity by name — full column detail + relationships. Falls
    back to :func:`list_entities_tool` filter when the registry lacks
    a targeted lookup."""
    if not name:
        return {"entity": None, "error": "empty name"}
    all_ents = list_entities_tool(output_dir).get("entities") or []
    _norm = lambda s: str(s or "").strip().lower()
    for e in all_ents:
        if _norm(e.get("name")) == _norm(name):
            return {"entity": e}
    # Also try table match
    for e in all_ents:
        if _norm(e.get("table")) == _norm(name):
            return {"entity": e}
    return {"entity": None, "error": f"entity {name!r} not found",
            "known": [e.get("name") for e in all_ents]}


def _read_forge_project_id(output_dir: str) -> str | None:
    """Resolve the platform project UUID for a generated app from its env files
    (every generated app ships FORGE_PROJECT_ID in .env.local)."""
    from pathlib import Path as _Path
    for fn in (".env.local", ".env"):
        p = _Path(output_dir) / fn
        if not p.exists():
            continue
        try:
            for line in p.read_text().splitlines():
                s = line.strip()
                if s.startswith("FORGE_PROJECT_ID="):
                    val = s.split("=", 1)[1].strip().strip('"').strip("'")
                    if val:
                        return val
        except Exception:
            continue
    return None


def _smith_create_business_rule(output_dir: str, args: dict) -> dict:
    """Author a Business Rule (project_rules) and ship it into the running app.

    Writes the rule to the platform DB (so the editor's Rules panel sees it),
    then re-exports rules/index.json into the app so the runtime rules engine
    picks it up on the next request — no regeneration needed.

    args = {
      "name":       "order-total",        # required, short kebab-case id
      "rule_type":  "validation" | "computed" | "business" | "condition_action"
                    | "access" | "state_machine" | "trigger" | "decision_table",
      "model_name": "Order",              # entity the rule targets (or null)
      "field_name": "total",              # optional field
      "config":     { ... }               # shape depends on rule_type:
        # validation → {expression|min|max|required, errorMessage}
        # computed   → {expression}     (field_name required)
        # business   → {expression, trigger:on_create|on_update, errorMessage}
        # condition_action → {whenFeel, then:[actions], otherwise:[], scope, salience}
    }
    """
    from pathlib import Path as _Path
    name = (args.get("name") or "").strip()
    rule_type = (args.get("rule_type") or "").strip()
    if not name or not rule_type:
        return {"applied": False, "edited_paths": [],
                "reason": "name and rule_type are required"}
    project_id = _read_forge_project_id(output_dir)
    if not project_id:
        return {"applied": False, "edited_paths": [],
                "reason": "could not resolve FORGE_PROJECT_ID for this app — the rule can't be persisted"}
    rule = {
        "name": name,
        "rule_type": rule_type,
        "model_name": args.get("model_name"),
        "field_name": args.get("field_name"),
        "config": args.get("config") if isinstance(args.get("config"), dict) else {},
        "is_active": True,
    }
    from services.runtime_injector import create_project_rule_sync, _export_rules_to_filesystem
    res = create_project_rule_sync(project_id, rule)
    if not res.get("ok"):
        return {"applied": False, "edited_paths": [], "reason": res.get("error", "insert failed")}
    exported = True
    try:
        _export_rules_to_filesystem(_Path(output_dir), project_id)
    except Exception:  # noqa: BLE001
        exported = False
    tgt = f" on {rule['model_name']}" if rule.get("model_name") else ""
    return {
        "applied": True,
        "edited_paths": ["rules/index.json"],
        "rule_id": res["id"],
        "exported": exported,
        "summary": (f"Created {rule_type} rule '{name}'{tgt}"
                    + (" and shipped it into the app." if exported else " (saved; export pending).")),
    }


READONLY_HANDLERS = {
    "recall":                   lambda output_dir, args: recall(output_dir),
    "list_workflows":           lambda output_dir, args: list_workflows(output_dir),
    "read_workflow":            lambda output_dir, args: read_workflow(output_dir, args.get("path", "")),
    "list_pages":               lambda output_dir, args: list_pages_tool(output_dir),
    "read_page":                lambda output_dir, args: read_page(output_dir, args.get("path", "")),
    "read_column":              lambda output_dir, args: read_column(output_dir, args.get("entity", ""), args.get("column", "")),
    "check_data_source":        lambda output_dir, args: _check_data_source_tool(output_dir, args.get("path", "")),
    "list_components":          lambda output_dir, args: list_components_tool(output_dir, kind=args.get("kind")),
    "analyze_workflow_values":  lambda output_dir, args: analyze_workflow_values_tool(output_dir, args.get("path", "")),
    "parse_error":              lambda output_dir, args: parse_error_tool(args.get("text", "")),
    "probe_logs":               lambda output_dir, args: probe_logs_tool(output_dir, lines=args.get("lines", 200)),
    "probe_endpoint":           lambda output_dir, args: probe_endpoint_tool(output_dir, args.get("url", "")),
    # Claude-Code-style file tools — read/edit/verify against real bytes.
    "read_file":                lambda output_dir, args: _smith_read_file(output_dir, args),
    "edit_file":                lambda output_dir, args: _smith_edit_file(output_dir, args),
    "verify_promise":           lambda output_dir, args: _smith_verify_promise(output_dir, args),
    # Orchestrator-era tools (S1-S5 of the smith-orch plan).
    "impact_analysis":          lambda output_dir, args: _smith_impact_analysis(output_dir, args),
    "edit_workflow":            lambda output_dir, args: _smith_edit_workflow(output_dir, args),
    "run_guards":               lambda output_dir, args: _smith_run_guards(output_dir),
    "edit_page":                lambda output_dir, args: _smith_edit_page(output_dir, args),
    "add_page":                 lambda output_dir, args: _smith_add_page(output_dir, args),
    "remove_page":              lambda output_dir, args: _smith_remove_page(output_dir, args),
    "add_workflow":             lambda output_dir, args: _smith_add_workflow(output_dir, args),
    "wire_form_to_workflow":    lambda output_dir, args: _smith_wire_form_to_workflow(output_dir, args),
    "use_21st_component":       lambda output_dir, args: _smith_use_21st_component(output_dir, args),
    "set_field_interaction":    lambda output_dir, args: _smith_set_field_interaction(output_dir, args),
    "create_business_rule":     lambda output_dir, args: _smith_create_business_rule(output_dir, args),
    "add_entity":               lambda output_dir, args: _smith_add_entity(output_dir, args),
    "plan_and_apply":           lambda output_dir, args: _smith_plan_and_apply(output_dir, args),
    "think":                    lambda output_dir, args: _smith_think(args),
    "understand_ask":           lambda output_dir, args: _smith_understand_ask(args),
    # Cross-file scan tools — locate files/schemas by content, not by
    # guessing the path. Smith calls these FIRST when the user names a
    # screen, a component, or an entity, so he never confabulates
    # "matches" without reading.
    "grep_schemas":             lambda output_dir, args: grep_schemas_tool(output_dir, args.get("pattern", ""), case_sensitive=bool(args.get("case_sensitive", False))),
    "find_component":           lambda output_dir, args: find_component_tool(output_dir, args.get("component", "")),
    "list_entities":            lambda output_dir, args: list_entities_tool(output_dir),
    "read_entity":              lambda output_dir, args: read_entity_tool(output_dir, args.get("name", "")),
    # PHASE-3 design brief tools.
    "get_brief":                lambda output_dir, args: _smith_get_brief(output_dir),
    "edit_brief":               lambda output_dir, args: _smith_edit_brief(output_dir, args),
    # Smith Auto-Act (S2) — scored decision. Prefer over find_resources
    # for label-shaped edit asks.
    "resolve_target":           lambda output_dir, args: _smith_resolve_target(output_dir, args),
    # SMITH-SEARCH-1 — one-call graph slice.
    "find_resources":           lambda output_dir, args: _smith_find_resources(output_dir, args.get("query", "")),
    # SMITH-SOURCE-1 — symptom → backend generator mapper.
    "find_source_generator":    lambda output_dir, args: _smith_find_source_generator(args.get("symptom", "")),
    # PLATFORM-HEALS — one-call in-place repair of known regression classes.
    "heal_platform_regressions": lambda output_dir, args: _smith_heal_platform_regressions(output_dir),
    # Delegated mutation sub-agent — Smith invokes this whenever a user
    # asks for a change/add/remove/fix. Runs a sandboxed 7-step ReAct
    # loop and returns a structured envelope.
    "_tool_app_modifier":       lambda output_dir, args: _dispatch_tool_app_modifier(output_dir, args),
    # Deployment — user asks Smith to publish/deploy the app.
    "publish":                  lambda output_dir, args: _smith_publish(output_dir, args),
    # Mobile build — user asks Smith to generate the APK/IPA.
    "generate_mobile_app":      lambda output_dir, args: _smith_generate_mobile_app(output_dir, args),
    "revert_last_patch":        lambda output_dir, args: _smith_revert_last_patch(output_dir, args),
    # JV-8 — read the most recent VerifyRun row's structured report so
    # Smith can answer follow-ups after a verify+fix without re-running.
    "read_last_verify_run":     lambda output_dir, args: _smith_read_last_verify_run(output_dir, args),
    "add_role":                 lambda output_dir, args: _smith_add_role(output_dir, args),
    "remove_role":              lambda output_dir, args: _smith_remove_role(output_dir, args),
    "restrict_page_to_role":    lambda output_dir, args: _smith_restrict_page_to_role(output_dir, args),
}


def _check_data_source_tool(output_dir: str, path: str) -> dict:
    """Bridge to :mod:`services.data_source_checker`. Lazy import so
    the peer-shape analyzer's app-map traversal isn't loaded at
    Smith-tools import time."""
    from services.data_source_checker import check_data_source
    return check_data_source(output_dir, path)


def _dispatch_tool_app_modifier(output_dir: str, args: dict) -> dict:
    """Bridge Smith's sync tool dispatch to the sync wrapper around
    the async modifier. Lazy import so the modifier's SDK dependency
    isn't loaded at Smith-tools import time."""
    from agents.tool_app_modifier import run_tool_app_modifier_sync
    ask = str((args or {}).get("ask") or "").strip()
    if not ask:
        return {
            "status": "blocked",
            "summary": "Cannot delegate without an ``ask`` — pass the user's request verbatim.",
            "files_touched": [], "registry_delta": {"added":[], "removed":[], "modified":[]},
            "validation": {}, "trace": [], "commit": None,
            "question_for_user": "What should I change?",
        }
    return run_tool_app_modifier_sync(
        ask=ask,
        output_dir=output_dir,
        blueprint_summary=str((args or {}).get("blueprint_summary") or ""),
    )


def _smith_think(args: dict) -> dict:
    """A no-op tool whose whole purpose is to give Smith a place to reason
    between actions. The thought lives in the conversation history (the
    tool CALL args are what the model re-reads on the next turn), so
    calling ``think`` multiple times builds up a persistent scratchpad."""
    text = args.get("thought") or args.get("text") or ""
    if not isinstance(text, str) or not text.strip():
        return {"recorded": False, "error": "thought must be a non-empty string"}
    return {"recorded": True, "chars": len(text.strip())}


_UNDERSTAND_ASK_REQUIRED = {
    "screen", "element_label", "current_behavior",
    "desired_behavior", "target_file",
}


def _smith_understand_ask(args: dict) -> dict:
    """Structured ask-extraction. Smith MUST call this before any
    mutating tool on a non-trivial change request. The orchestrator
    later relevance-checks Smith's diff against ``target_file`` +
    ``element_label`` — this is what closes the 'cheapest-edit-wins'
    loophole where Smith reformats unrelated fields and marks resolved.

    Empty/missing fields → validation error; Smith retries with a real
    extraction. ``clarification_needed`` (a string) short-circuits the
    orchestrator to ``ask_user`` on low-confidence asks."""
    if not isinstance(args, dict):
        return {"recorded": False, "error": "understand_ask requires an object arg"}
    # PER VERB, NOT ONE SHAPE. These five fields describe a rename, and they
    # were required of every request — so "build the dashboard at /" could not
    # be expressed here at all. The model either failed validation or invented
    # an `element_label`, and the dispatcher then found nothing to rename and
    # reported that the current state already matched.
    from services.smith.verbs import missing_fields, is_known, VERB_HELP

    if not is_known(args):
        return {
            "recorded": False,
            "error": ("unknown verb. Choose one of: "
                      + "; ".join(f"{v} — {h}" for v, h in VERB_HELP.items())),
        }
    missing = missing_fields(args)
    clarification = args.get("clarification_needed")
    if missing and not (isinstance(clarification, str) and clarification.strip()):
        return {
            "recorded": False,
            "error": (
                f"missing required fields: {missing}. Either fill them in "
                "(you have read_file / list_pages to disambiguate) or set "
                "clarification_needed to a specific question and call "
                "ask_user with it."
            ),
        }
    conf = args.get("confidence")
    try:
        conf = float(conf) if conf is not None else 0.7
    except (TypeError, ValueError):
        conf = 0.7
    return {
        "recorded": True,
        "understanding": {
            # What kind of change this is. Absent means `rename`, which is what
            # every turn used to be.
            "verb": (str(args.get("verb") or "").strip().lower() or "rename"),
            "route": args.get("route"),
            "widgets": args.get("widgets") or [],
            "screen": args.get("screen"),
            "element_label": args.get("element_label"),
            "current_behavior": args.get("current_behavior"),
            "desired_behavior": args.get("desired_behavior"),
            "target_file": args.get("target_file"),
            "target_node_hint": args.get("target_node_hint"),
            "confidence": max(0.0, min(1.0, conf)),
            "clarification_needed": clarification if isinstance(clarification, str) else None,
        },
    }


def _smith_find_source_generator(symptom: str) -> dict:
    """SMITH-SOURCE-1 wrapper — map a symptom to backend emitter modules.
    Never raises. Empty symptom returns matched=False."""
    from services.smith_find_source import find_source_generator
    try:
        return find_source_generator(symptom or "")
    except Exception as e:  # noqa: BLE001
        return {"error": f"find_source_generator failed: {e!r}"}


def _smith_get_brief(output_dir: str) -> dict:
    """PHASE-3 tool handler — return the current DesignBrief as a dict,
    or {"brief": null} if none has been authored."""
    from services.design_brief_editor import read_brief

    b = read_brief(output_dir)
    if b is None:
        return {"brief": None, "hint": (
            "No design brief on disk. Run Discovery with "
            "FORGE_BRIEF_AUTHOR=1, or await Phase 1 rollout for this "
            "project."
        )}
    return {"brief": b.model_dump()}


def _smith_edit_brief(output_dir: str, args: dict) -> dict:
    """PHASE-3 tool handler — apply a partial patch to the brief and
    trigger the token-recompile cascade so the generated app picks up
    the new palette/typography.

    Args:
        patch: nested dict matching the brief schema. Only the paths you
            supply are overwritten. Lists are replaced wholesale.

    Returns:
        {"applied": True, "before": {summary}, "after": {summary, brief},
         "cascade": {...}} on success. The `brief_edit` shape doubles as
        the ChatMessage metadata payload so DesignBriefCard renders
        the diff inline. {"error": "..."} on failure.
    """
    from services.design_brief_editor import BriefEditError, edit_brief_on_disk

    patch = args.get("patch") if isinstance(args, dict) else None
    if not isinstance(patch, dict) or not patch:
        return {"error": "edit_brief requires a non-empty `patch` dict"}
    try:
        before, after = edit_brief_on_disk(output_dir, patch)
    except BriefEditError as exc:
        return {"error": str(exc)}

    # Fire the cascade — token recompile. Non-fatal; brief change is
    # already on disk regardless.
    cascade_result: dict = {"recompiled": False, "reason": "not-run"}
    try:
        from services.brief_loop_cascade import cascade as _cascade
        cascade_result = _cascade(output_dir)
    except Exception as exc:  # noqa: BLE001
        cascade_result = {"recompiled": False, "reason": f"cascade error: {exc}"}

    return {
        "applied": True,
        "before": {"summary": before.summary_line()},
        "after": {"summary": after.summary_line(), "brief": after.model_dump()},
        "cascade": cascade_result,
    }


def _smith_resolve_target(output_dir: str, args: dict) -> dict:
    """Smith Auto-Act (S2) — score candidates + return an act/chip/ask decision.

    Meant to be called by Smith BEFORE any mutation tool when the ask is
    label-shaped ("change the Status field", "make Priority a badge") and
    could plausibly land on more than one page. It bundles the scans
    (grep_schemas → list_pages → optional list_entities) and runs the
    pure decision function in :mod:`services.smith_decide`.

    Args:
        query: The user's phrase, verbatim.
        label: OPTIONAL narrower literal to grep for (defaults to `query`).
        current_route: OPTIONAL — the visual-editor's route. When Smith
            has this in its ``<smith-current-context>`` block, echo it
            back here so the +50 route-bias applies.
        recent_edits: OPTIONAL — list of recently-touched routes (from
            the ``<smith-recent-edits>`` memory block, newest first).
            Awards +20 to any candidate whose route is in the list.

    Returns:
        Dict with ``kind`` in {act, act_all, chip, ask}, ``targets``
        (list of {kind, route, path, matched_by, excerpt}), ``reason``,
        and ``scores`` for debugging.
    """
    from services.smith_decide import build_candidates_from_scan, resolve

    query = (args.get("query") or "").strip()
    if not query:
        return {"error": "query is required (the user's ask, verbatim)"}
    label = (args.get("label") or query).strip()
    current_route = args.get("current_route") or None
    _re_in = args.get("recent_edits") or ()
    recent_edits = tuple(r for r in _re_in if isinstance(r, str) and r) if isinstance(_re_in, (list, tuple)) else ()

    try:
        pages_out = list_pages_tool(output_dir)
        pages = pages_out.get("pages") or []
    except Exception:
        pages = []
    page_index = {p.get("path"): p.get("route") for p in pages if p.get("path")}

    grep_matches: list[dict] = []
    try:
        grep_out = grep_schemas_tool(output_dir, label, case_sensitive=False)
        for m in (grep_out.get("matches") or []):
            grep_matches.append(m)
    except Exception:
        pass

    candidates = build_candidates_from_scan(
        grep_matches=grep_matches,
        page_index=page_index,
    )

    res = resolve(
        query,
        candidates,
        current_route=current_route,
        recent_edits=recent_edits,
    )
    return {
        "kind": res.kind,
        "targets": [
            {
                "kind": c.kind,
                "route": c.route,
                "path": c.path,
                "matched_by": list(c.matched_by),
                "excerpt": c.excerpt,
            }
            for c in res.targets
        ],
        "reason": res.reason,
        "scores": [
            {"route": c.route, "path": c.path, "score": s}
            for c, s in (res.scores or ())
        ],
    }


def _smith_find_resources(output_dir: str, query: str) -> dict:
    """SMITH-SEARCH-1 wrapper — one-call graph slice for an entity/feature phrase.

    Delegates to :func:`services.smith_find_resources.find_resources`. Kept as
    a thin wrapper so the handler signature matches every other tool
    (``(output_dir, args)``) and error handling is uniform."""
    from services.smith_find_resources import find_resources
    if not isinstance(query, str) or not query.strip():
        return {"error": "query is required (entity name or feature phrase)"}
    try:
        return find_resources(output_dir, query)
    except Exception as e:  # noqa: BLE001
        return {"error": f"find_resources failed: {e!r}"}


def _smith_add_page(output_dir: str, args: dict) -> dict:
    """Direct wrapper around :func:`fix_applier._apply_add_page`.

    Composes a diagnosis Smith would otherwise have to author by hand
    for ``propose_fix(seam='add_page', ...)`` — but with no free-form
    explanation, so the coherence gate is a no-op."""
    from services.fix_applier import _apply_add_page
    diagnosis = {
        "artifact": {"kind": "page", "path": args.get("route") or ""},
        "explanation": "",
        "proposedFix": {"seam": "add_page", "patch": {
            "archetype": args.get("archetype") or args.get("kind") or "",
            "entity":    args.get("entity")    or "",
            "route":     args.get("route")     or "",
            "title":     args.get("title"),
            "features":  args.get("features"),
            "fields":    args.get("fields"),
        }},
    }
    result = _apply_add_page(output_dir, diagnosis, git=False)
    result["edited_paths"] = [c["path"] for c in result.get("changes") or [] if c.get("path")]
    return result


def _smith_remove_page(output_dir: str, args: dict) -> dict:
    """Direct wrapper around :func:`fix_applier._apply_remove_page`.

    Phase 1a — confirmation gate. Refuses to execute unless the LLM
    passes ``_confirmed=True``. First call returns a structured
    "needs_confirmation" summary the LLM relays to the user; on the
    next turn the LLM re-issues the same call with ``_confirmed=True``
    after the user says "yes". No server-side state — the flow lives
    in the chat trace.
    """
    from services.confirmation_gate import needs_confirmation_result
    from services.fix_applier import _apply_remove_page

    route = str(args.get("route") or "").strip()
    cascade = bool(args.get("cascade"))
    if not args.get("_confirmed"):
        # Ask the SEAM what it will delete rather than inferring it. The
        # prompt used to pass only (kind, route), so `cascade` never reached
        # the user (register SX-1) — and `dependents` only walked nav edges
        # POINTING AT the named route, never the siblings cascade takes. The
        # user could agree to "remove page /x" and lose the whole slice.
        removes: list[str] = []
        try:
            from pathlib import Path as _Path
            from services.remove_page_seam import _find_matching
            schemas_dir = _Path(output_dir) / "src" / "schemas"
            if schemas_dir.is_dir():
                removes = [m.route for m in
                           _find_matching(schemas_dir, route, cascade=cascade)]
        except Exception:
            logger.exception(
                "remove_page: could not enumerate what cascade=%s would delete "
                "for %r — the prompt will say so rather than understate it",
                cascade, route,
            )
            removes = []

        dependents: list[str] = []
        try:
            from services.app_map import build_app_map  # type: ignore
            m = build_app_map(output_dir)
            # Nav edges pointing at any route that is going away.
            dead = set(removes) | {route}
            for e in (m.get("navGraph") or {}).get("edges") or []:
                if e.get("to") in dead:
                    dependents.append(f"nav edge {e.get('from')} → {e.get('to')}")
        except Exception:
            pass

        if cascade and not removes:
            dependents.append(
                "could not enumerate the cascade set — the real blast radius "
                "may be larger than shown"
            )
        return needs_confirmation_result(
            "page", route or "?", dependents=dependents,
            cascade=cascade, removes=removes,
        )

    diagnosis = {
        "artifact": {"kind": "page", "path": route},
        "explanation": "",
        "proposedFix": {"seam": "remove_page", "patch": {
            "route":   route,
            "cascade": bool(args.get("cascade")),
        }},
    }
    result = _apply_remove_page(output_dir, diagnosis, git=False)
    result["edited_paths"] = [c["path"] for c in result.get("changes") or [] if c.get("path")]
    return result


def _smith_add_workflow(output_dir: str, args: dict) -> dict:
    """Direct wrapper around :func:`fix_applier._apply_add_workflow`."""
    from services.fix_applier import _apply_add_workflow
    diagnosis = {
        "artifact": {"kind": "workflow", "path": args.get("name") or ""},
        "explanation": "",
        "proposedFix": {"seam": "add_workflow", "patch": {
            "op":     args.get("op") or "create",
            "entity": args.get("entity") or "",
            "name":   args.get("name"),
        }},
    }
    result = _apply_add_workflow(output_dir, diagnosis, git=False)
    result["edited_paths"] = [c["path"] for c in result.get("changes") or [] if c.get("path")]
    return result


def _smith_wire_form_to_workflow(output_dir: str, args: dict) -> dict:
    """Direct wrapper around :func:`services.wire_form_workflow.
    wire_form_to_workflow`.

    Deterministic seam — no LLM, no diagnosis wrapper needed. Reads two
    artifacts, patches both atomically, mirrors to plan.json. Shape:

        args = {
          "page_route":    "/candidates/new",
          "workflow_name": "ParseCvWorkflow",
          "field_map":     {"cvUrl": "cvUrl"}    # optional
        }
    """
    from services.wire_form_workflow import wire_form_to_workflow
    result = wire_form_to_workflow(
        output_dir,
        page_route=args.get("page_route") or "",
        workflow_name=args.get("workflow_name") or "",
        field_map=args.get("field_map"),
        git=True,
    )
    # Normalise for Smith's answer/verify pipeline: expose edited_paths so
    # the retry-break + turn-end commit see the touched files.
    edited: list[str] = []
    if result.get("page_path"):
        edited.append(result["page_path"])
    if result.get("wf_path"):
        edited.append(result["wf_path"])
    return {
        **result,
        "success": bool(result.get("applied")),
        "edited_paths": edited,
    }


def _smith_set_field_interaction(output_dir: str, args: dict) -> dict:
    """Direct wrapper around :func:`services.set_field_interaction.
    set_field_interaction`.

    Deterministic seam — LLM proposes the shape via args, validator +
    writer are pure Python. On validation error, returns applied=False
    with actionable messages so Smith's ReAct loop can correct + retry.
    Shape::

        args = {
          "page":  "employees/new",              # required
          "field": "hra",                        # required
          "interaction": {                       # required unless mode='remove'
            "computed":    {"formula": "basicSalary * 0.4"},
            "optionsFrom": {"source": "states", ...},
            "onChange":    {"fetch": {...}, "set": {...}},
            "dependsOn":   [...],
            "visibleIf" / "requiredIf" / "enabledIf" / "readOnlyIf": "predicate",
          },
          "mode":  "merge" | "replace" | "remove"  # optional, default "merge"
        }
    """
    from services.set_field_interaction import set_field_interaction
    page = args.get("page") or ""
    field = args.get("field") or ""
    if not page or not field:
        return {
            "applied": False,
            "edited_paths": [],
            "reason": "page and field are required",
        }
    result = set_field_interaction(
        output_dir,
        page=page,
        field=field,
        interaction=args.get("interaction"),
        mode=(args.get("mode") or "merge"),
    )
    result["success"] = bool(result.get("applied"))
    return result


def _smith_add_entity(output_dir: str, args: dict) -> dict:
    """Direct wrapper around :func:`fix_applier._apply_add_entity`."""
    from services.fix_applier import _apply_add_entity
    diagnosis = {
        "artifact": {"kind": "entity", "path": args.get("name") or ""},
        "explanation": "",
        "proposedFix": {"seam": "add_entity", "patch": {
            "name":   args.get("name")   or "",
            "fields": args.get("fields") or [],
            "table":  args.get("table"),
        }},
    }
    result = _apply_add_entity(output_dir, diagnosis, git=False)
    result["edited_paths"] = [c["path"] for c in result.get("changes") or [] if c.get("path")]
    return result


def _smith_plan_and_apply(output_dir: str, args: dict) -> dict:
    """One-shot multi-step feature builder — plan + execute in a single
    tool call. Smith uses this for "add a feature" asks that span
    entity + pages + workflow + wiring; the alternative is 5 separate
    Smith turns, each with its own LLM latency and its own chance to
    lose thread.

    Args: ``{ask: str}``. Delegates to
    :func:`services.smith_plan_and_apply.plan_and_apply`.
    """
    ask = args.get("ask")
    if not isinstance(ask, str) or not ask.strip():
        return {"success": False, "error": "ask must be a non-empty string"}
    try:
        from services.smith_plan_and_apply import plan_and_apply
        r = plan_and_apply(ask.strip(), output_dir)
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": f"plan_and_apply crashed: {exc}"}
    # Normalize to the shape Smith's dispatcher expects.
    ok = r.get("status") == "ok"
    r["success"] = ok
    if not ok and r.get("status") == "plan_error":
        r["error"] = r.get("error") or "planner failed"
    return r


def _smith_edit_page(output_dir: str, args: dict) -> dict:
    """LLM-driven page-schema edit.

    Delegates to :func:`services.llm_edit.smart_edit_page`, which:
      * Reads the current schema.
      * Injects the app-map + component registry into the LLM prompt.
      * Emits a full new schema.
      * Writes atomically with structural validation.
      * Does NOT run the post-generate opinion guards — the LLM's
        control choice is the authority.

    See ``checkpoint_dday`` for why this replaces the old JSON-Patch
    edit_page: the guard suite was reversing the LLM's intent (e.g.
    FK-named columns were forced back to Select even when the user
    explicitly asked for FileUpload)."""
    from services.llm_edit import smart_edit_page
    from agents.fix_chat_agent import _default_query as _sdk_query
    path = args.get("path") or (args.get("target") or {}).get("path")
    intent = args.get("intent") or args.get("ask") or ""
    if not path or not isinstance(intent, str) or not intent.strip():
        return {"applied": False,
                "reason": "edit_page requires {path, intent: <plain english>}",
                "edited_paths": []}

    def _query_fn(system_prompt: str, user_prompt: str) -> str:
        # Reuse the SDK boundary the fix-chat agent uses. Fresh one-shot
        # ``messages.create`` call — no tool loop needed here since the
        # LLM emits a complete new schema in one turn.
        import os
        try:
            from services import llm_client  # LangGraph migration (LG-1): ChatAnthropic-backed shim
        except Exception as exc:  # pragma: no cover — import guard
            raise RuntimeError(f"anthropic SDK missing: {exc}") from exc
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        client = llm_client.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=16000,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        return "".join(b.text for b in msg.content if hasattr(b, "text"))

    return smart_edit_page(
        output_dir=output_dir,
        target_path=path,
        intent=intent,
        query_fn=_query_fn,
    )


def _smith_use_21st_component(output_dir: str, args: dict) -> dict:
    """Fetch a component from 21st.dev, convert JSX→schema, splice into a page.

    Pipeline:
      1. ``magic_mcp_client.generate_component(description, hint)`` calls
         21st's Magic MCP over HTTP → returns raw React/Tailwind JSX.
      2. ``magic_jsx_to_schema.convert_jsx_to_schema`` LLM-converts the JSX
         into a schemaVersion:2 node fragment mapped to our library
         components (drops hooks/state/imports, translates shadcn → our
         primitives).
      3. ``smart_edit_page`` splices the fragment into the target page.
         We pass the compact JSON in the intent so edit_page's sub-agent
         places it correctly (usually as a new top-level child).

    Fails closed at every step — a missing API key, MCP failure, empty JSX,
    unparseable conversion, or edit_page rejection returns ``applied:False``
    with a specific reason. The caller (Smith) can then fall back to
    ``edit_page`` with a plain-English intent.
    """
    import asyncio

    path = args.get("path") or (args.get("target") or {}).get("path")
    description = args.get("description") or args.get("ask") or args.get("intent") or ""
    hint = args.get("hint") or ""
    if not path or not isinstance(description, str) or not description.strip():
        return {"applied": False,
                "source": "21st",
                "reason": "use_21st_component requires {path, description}",
                "edited_paths": []}

    from services import magic_mcp, magic_mcp_client, magic_jsx_to_schema
    if not magic_mcp.is_enabled():
        return {"applied": False,
                "source": "21st",
                "reason": ("21st.dev MCP not configured — set FORGE_21ST_MCP=on "
                           "+ FORGE_21ST_API_KEY in the backend .env. "
                           "Fall back to `edit_page` with a plain-English intent."),
                "edited_paths": []}

    # Step 1: JSX from 21st.
    try:
        jsx = asyncio.run(magic_mcp_client.generate_component(description, hint=hint or None))
    except Exception as exc:  # noqa: BLE001
        return {"applied": False,
                "source": "21st",
                "reason": f"21st MCP call failed: {exc}",
                "edited_paths": []}
    if not jsx or not jsx.strip():
        return {"applied": False,
                "source": "21st",
                "reason": "21st.dev returned no JSX for the description. Try a more specific description or fall back to edit_page.",
                "edited_paths": []}

    # Step 2: JSX → schema fragment.
    try:
        fragment = asyncio.run(
            magic_jsx_to_schema.convert_jsx_to_schema(jsx, hint=description)
        )
    except Exception as exc:  # noqa: BLE001
        return {"applied": False,
                "source": "21st",
                "reason": f"JSX→schema conversion failed: {exc}",
                "edited_paths": []}
    if fragment is None:
        return {"applied": False,
                "source": "21st",
                "reason": "JSX→schema conversion returned no valid node. The source JSX may be too complex.",
                "edited_paths": []}

    # Step 3: splice into the target page via edit_page.
    compact = json.dumps(fragment, separators=(",", ":"))
    splice_intent = (
        f"Append this pre-authored schema fragment as a new top-level child of "
        f"the page root (before any footer/action row). Do NOT re-author it — "
        f"insert exactly as given. Fragment:\n\n{compact}\n\n"
        f"User's original ask (for context): {description}"
    )
    result = _smith_edit_page(output_dir, {"path": path, "intent": splice_intent})
    result = dict(result) if isinstance(result, dict) else {}
    result["source"] = "21st"
    result.setdefault("edited_paths", [])
    return result


def _smith_impact_analysis(output_dir: str, args: dict) -> dict:
    """Blast-radius report for `{entity, field?} | {page} | {workflow}`."""
    from services.impact_analysis import analyze_impact
    report = analyze_impact(output_dir, args or {})
    return {"impact": report.to_dict(), "summary": report.summary()}


#: `edit_workflow` change ops that DESTROY or relocate authored work and so
#: require the same confirmation `remove_page` asks for. `remove_step` drops
#: a step (and its config) outright; `rename` moves the file, which breaks
#: every button bound to the old id. Both were ungated (register S24-4) —
#: `remove_page` was the only tool in the whole catalog that confirmed.
_DESTRUCTIVE_WORKFLOW_OPS = ("remove_step", "rename")


def _smith_edit_workflow(output_dir: str, args: dict) -> dict:
    """Structured edit of an existing workflow — see
    :mod:`services.edit_workflow_seam` for the supported change ops.

    Destructive ops (:data:`_DESTRUCTIVE_WORKFLOW_OPS`) return
    ``needs_confirmation`` unless the caller passes ``_confirmed=True``.
    The orchestrator only lets that flag through when it can see the user
    was actually asked and actually said yes.
    """
    from services.confirmation_gate import needs_confirmation_result
    from services.edit_workflow_seam import edit_workflow
    wid = args.get("workflow_id") or args.get("id") or ""
    changes = args.get("changes") or {}

    if isinstance(changes, dict) and not args.get("_confirmed"):
        destructive = [op for op in _DESTRUCTIVE_WORKFLOW_OPS if op in changes]
        if destructive:
            dependents = []
            if "remove_step" in changes:
                dependents.append(
                    f"step {changes['remove_step']!r} and its configuration are "
                    f"deleted; anything wired to it is rewired to its successor"
                )
            if "rename" in changes:
                dependents.append(
                    f"the workflow file moves to workflows/{changes['rename']}.json "
                    f"— every button bound to {wid!r} stops resolving"
                )
            return needs_confirmation_result(
                "workflow", f"{wid} ({', '.join(destructive)})",
                dependents=dependents,
            )

    result = edit_workflow(output_dir, wid, changes,
                           args.get("expected_version"))
    return result.to_dict()


def _smith_run_guards(output_dir: str) -> dict:
    """Run the full post-generate guard suite and return a structured
    ``GuardResult`` verdict Smith can react to."""
    from services.post_generate_fixes import apply_post_generate_fixes_with_result
    r = apply_post_generate_fixes_with_result(output_dir)
    return {"green": r.green, "failures": [f.to_dict() for f in r.failures],
            "summary": r.to_prompt()}


# Lazy imports so the module keeps its current import cost — smith_edit_tools
# pulls patch_coherence which is otherwise only needed at fix-apply time.
def _smith_read_file(output_dir: str, args: dict) -> dict:
    from services.smith_edit_tools import read_file
    return read_file(output_dir, args)


def _smith_edit_file(output_dir: str, args: dict) -> dict:
    from services.smith_edit_tools import edit_file
    return edit_file(output_dir, args)


def _smith_verify_promise(output_dir: str, args: dict) -> dict:
    from services.smith_edit_tools import verify_promise
    return verify_promise(output_dir, args)


def _smith_add_role(output_dir: str, args: dict) -> dict:
    """Add a role to plan['actors']. Phase 6."""
    from services.role_seams import add_role_in_file
    return add_role_in_file(output_dir, args.get("role_name") or "")


def _smith_remove_role(output_dir: str, args: dict) -> dict:
    """Remove a role from plan['actors']. Phase 6."""
    from services.role_seams import remove_role_in_file
    return remove_role_in_file(output_dir, args.get("role_name") or "")


def _smith_restrict_page_to_role(output_dir: str, args: dict) -> dict:
    """Set access.roles on a page. Phase 6."""
    from services.role_seams import restrict_page_to_role_in_file
    return restrict_page_to_role_in_file(
        output_dir,
        args.get("page_route") or "",
        args.get("role_name") or "",
    )


def _smith_revert_last_patch(output_dir: str, args: dict) -> dict:
    """Reverse the most recent commit in the app repo (Phase 1b).

    Delegates to :func:`services.patch_history.revert_last_patch`. See
    the tool catalog entry for user-facing rules.
    """
    from services.patch_history import revert_last_patch
    return revert_last_patch(output_dir)


def _smith_publish(output_dir: str, args: dict) -> dict:
    """Kick off a Vercel publish of the current app in the background.

    Runs the same VercelDeployProvider the human Publish button uses.
    Doesn't block Smith's turn — deploys take 3–5 minutes and the
    modal/toolbar already reflect progress via /deployments/latest.
    Returns immediately with the deployment row id and a note pointing
    the user at the toolbar.
    """
    import asyncio
    from pathlib import Path

    from sqlalchemy import select as _select

    from database import async_session
    from models.project import Project as _Project
    from models.platform_integration import PlatformIntegration as _PI
    from services.deploy.provider import DeploySnapshot as _Snapshot
    from services.deploy.vercel_provider import (
        VercelDeployProvider as _Provider,
    )
    from services.platform_integrations_crypto import (
        CryptoError as _CryptoError,
        decrypt as _decrypt,
    )

    target = (args or {}).get("target") or "vercel"
    if target != "vercel":
        return {
            "ok": False,
            "error": (
                f"Target {target!r} not supported yet. Only 'vercel' is "
                "wired up; the Tentoro Cloud option is coming soon."
            ),
        }

    resolved = str(Path(output_dir).resolve())

    async def _run() -> None:
        # Fresh session — this task outlives the caller's request scope.
        async with async_session() as db:
            res = await db.execute(
                _select(_Project).where(_Project.output_dir == resolved)
            )
            project = res.scalars().first()
            if project is None:
                # Try LIKE match in case output_dir was stored with a
                # trailing slash or symlink diff.
                res = await db.execute(
                    _select(_Project).where(
                        _Project.output_dir.like(f"%{Path(resolved).name}%")
                    )
                )
                project = res.scalars().first()
            if project is None:
                return

            # Same integration decrypt loop the /publish endpoint uses.
            ires = await db.execute(
                _select(_PI).where(_PI.org_id == project.org_id)
            )
            integrations: dict[str, str] = {}
            for row in ires.scalars().all():
                if not row.value_ct or not row.value_iv:
                    continue
                try:
                    integrations[row.key] = _decrypt(
                        row.provider, row.value_ct, row.value_iv
                    )
                except _CryptoError:
                    pass

            snapshot = _Snapshot(
                project_id=str(project.id),
                project_slug=project.short_id,
                output_dir=project.output_dir,
                integrations=integrations,
                triggered_by="smith",
            )
            provider = _Provider(db=db)
            # Consume the async generator to completion so the DB row
            # advances to succeeded/failed regardless of any client
            # SSE connection. Errors are already logged inside publish().
            try:
                async for _evt in provider.publish(snapshot):
                    pass
            except Exception:
                pass

    # Smith's ReAct loop runs sync tool fns in a threadpool -> no running
    # loop here. asyncio.run() would spawn a fresh loop and then blow up
    # on the first DB call because SQLAlchemy's asyncpg pool is bound to
    # the main FastAPI loop ("got Future attached to a different loop").
    # Dispatch onto the main loop instead.
    from services.main_loop import dispatch_background as _dispatch
    if not _dispatch(_run()):
        return {
            "ok": False,
            "error": (
                "Publish couldn't start — the backend main loop wasn't "
                "captured. Please retry, or use the Publish button in the "
                "toolbar."
            ),
        }

    return {
        "ok": True,
        "target": "vercel",
        "message": (
            "Publish started. It takes 3–5 minutes. Watch the Publish "
            "button in the toolbar for the live URL, or open the Publish "
            "dialog to see per-stage progress."
        ),
    }


# --------------------------------------------------------------------------- #
# generate_mobile_app — MOBILE Smith tool                                     #
# --------------------------------------------------------------------------- #

_MOBILE_VALID_PROFILES = {"preview", "preview-simulator", "production"}
_MOBILE_VALID_PLATFORMS = {"android", "ios"}


def _smith_generate_mobile_app(output_dir: str, args: dict) -> dict:
    """Queue an EAS mobile build for this app.

    Bridges Smith's tool-loop to the MOBILE-C infrastructure the Publish
    dialog uses. Everything is the same: DB row inserted first, EAS
    build kicked off + polled in a background task, terminal status
    lands on the row for the UI to pick up.

    Returns a compact envelope so Smith can tell the user "started, poll
    at X" without embedding EAS internals. Missing pieces (no deployed
    URL, no credentials, no mobile scaffolding) come back as
    ``{ok: false, error, missing_keys?}`` — Smith surfaces the message
    to the user verbatim so they can fix it.
    """
    import asyncio
    from pathlib import Path

    from sqlalchemy import select as _select

    from database import async_session
    from models.mobile_build import MobileBuild as _MobileBuild
    from models.project import Project as _Project
    from services.eas_client import EasClientError as _EasErr
    from services.eas_client import (
        create_build as _create_build,
        is_terminal as _is_terminal,
        normalize_status as _normalize_status,
        poll_build as _poll_build,
    )
    from services.mobile_credentials import (
        MissingRequired as _MissingRequired,
        load_mobile_credentials as _load_mobile_credentials,
    )

    args = args or {}
    platform = str(args.get("platform") or "android").strip().lower()
    profile = str(args.get("profile") or "preview").strip().lower()

    if platform not in _MOBILE_VALID_PLATFORMS:
        return {
            "ok": False,
            "error": f"platform must be one of {sorted(_MOBILE_VALID_PLATFORMS)}, got {platform!r}.",
        }
    if profile not in _MOBILE_VALID_PROFILES:
        return {
            "ok": False,
            "error": f"profile must be one of {sorted(_MOBILE_VALID_PROFILES)}, got {profile!r}.",
        }
    if profile == "preview-simulator" and platform != "ios":
        return {
            "ok": False,
            "error": "profile 'preview-simulator' is iOS-only. Use 'preview' for Android.",
        }

    resolved = str(Path(output_dir).resolve())
    mobile_dir = Path(resolved) / "mobile"
    if not mobile_dir.is_dir():
        return {
            "ok": False,
            "error": (
                "This app doesn't have mobile/ scaffolding yet. Re-run "
                "generation so the Expo shell is emitted, then try again."
            ),
        }

    async def _run() -> None:
        """Full pipeline: locate project → creds → deployed URL → insert
        row → kick EAS build → poll to terminal. Runs as a fresh
        background task so Smith's sync dispatcher can return
        immediately. Any failure lands on the DB row as ``error_message``
        so the Publish-dialog UI surfaces it."""
        from routers.mobile_builds import (
            _apple_env,
            _apply_state,
            _google_env,
            _latest_deployed_url,
            _mark_failed,
            _POLL_INTERVAL_SEC,
            _POLL_MAX_SECONDS,
        )

        async with async_session() as db:
            res = await db.execute(
                _select(_Project).where(_Project.output_dir == resolved)
            )
            project = res.scalars().first()
            if project is None:
                res = await db.execute(
                    _select(_Project).where(
                        _Project.output_dir.like(f"%{Path(resolved).name}%")
                    )
                )
                project = res.scalars().first()
            if project is None:
                return

            try:
                creds = await _load_mobile_credentials(project.org_id, db)
            except _MissingRequired as exc:
                logger.warning(
                    "smith mobile: missing creds for org %s: %s",
                    project.org_id, exc,
                )
                return

            if profile == "production":
                if platform == "ios" and not creds.can_submit_ios():
                    return
                if platform == "android" and not creds.can_submit_android():
                    return

            deployed_url = await _latest_deployed_url(project.id) or ""
            if not deployed_url:
                return

            row = _MobileBuild(
                project_id=project.id,
                triggered_by=project.owner_id,
                profile=profile,
                platform=platform,
                status="pending",
            )
            db.add(row)
            await db.flush()
            await db.commit()
            await db.refresh(row)
            build_row_id = row.id

        try:
            state = await _create_build(
                str(mobile_dir),
                profile=profile,
                platform=platform,
                expo_token=creds.expo_eas_token,
                deployed_url=deployed_url,
                apple_env=_apple_env(creds) if platform == "ios" else None,
                google_env=_google_env(creds) if platform == "android" else None,
            )
        except _EasErr as exc:
            await _mark_failed(build_row_id, str(exc))
            return

        await _apply_state(build_row_id, state)

        started = asyncio.get_event_loop().time()
        while True:
            async with async_session() as sess:
                row2 = await sess.get(_MobileBuild, build_row_id)
                if row2 is None or _is_terminal(row2.status):
                    return
            if asyncio.get_event_loop().time() - started > _POLL_MAX_SECONDS:
                await _mark_failed(
                    build_row_id,
                    "Timed out waiting for EAS build to finish (>1h).",
                )
                return
            await asyncio.sleep(_POLL_INTERVAL_SEC)
            try:
                state = await _poll_build(
                    str(mobile_dir), state.build_id,
                    expo_token=creds.expo_eas_token,
                )
            except _EasErr as exc:
                logger.warning("smith mobile poll_build failed: %s", exc)
                continue
            await _apply_state(build_row_id, state)

    # Same rationale as _smith_publish: sync tool in threadpool → no loop
    # here, and asyncio.run() crosses loops with the asyncpg pool. Route
    # onto the main FastAPI loop.
    from services.main_loop import dispatch_background as _dispatch
    if not _dispatch(_run()):
        return {
            "ok": False,
            "error": (
                "Mobile build couldn't start — the backend main loop "
                "wasn't captured. Please retry, or use the Publish "
                "dialog's Mobile-app tab."
            ),
        }

    return {
        "ok": True,
        "platform": platform,
        "profile": profile,
        "message": (
            f"Started an EAS {profile} build for {platform}. It takes "
            f"10–20 minutes. Open the Publish dialog's Mobile-app tab "
            f"to watch progress and grab the download link when it's ready. "
            f"If credentials or the deployed URL are missing, the row will "
            f"surface the exact gap there."
        ),
    }


def _smith_read_last_verify_run(output_dir: str, args: dict) -> dict:
    """Read the latest VerifyRun row for the project owning this
    ``output_dir`` and return its structured report.

    Sync tool wrapper — runs an event loop in a threadpool because the
    Smith SDK dispatches tools synchronously. Reuses format_verify_report_json
    so what Smith sees here is 1:1 with what the SelfVerifyCard renders."""
    import asyncio
    from pathlib import Path

    from sqlalchemy import select as _select, desc as _desc

    from database import async_session
    from models.project import Project as _Project
    from models.verify_run import VerifyRun as _VerifyRun
    from services.verify_summary import format_verify_report_json

    resolved = str(Path(output_dir).resolve())

    async def _run() -> dict:
        async with async_session() as db:
            project = (await db.execute(
                _select(_Project).where(_Project.output_dir == resolved),
            )).scalar_one_or_none()
            if not project:
                # Second try: match by suffix — some projects store
                # relative paths, and the resolved-abs mismatch shouldn't
                # look like "no runs" to Smith.
                projects = (await db.execute(_select(_Project))).scalars().all()
                project = next(
                    (p for p in projects if p.output_dir
                     and Path(p.output_dir).name == Path(resolved).name),
                    None,
                )
            if not project:
                return {"error": "project_not_found_for_output_dir"}

            row = (await db.execute(
                _select(_VerifyRun)
                .where(_VerifyRun.project_id == project.id)
                .order_by(_desc(_VerifyRun.created_at))
                .limit(1),
            )).scalar_one_or_none()
            payload: dict = format_verify_report_json(row) if row is not None else {}
            # IRF-M5-T9: attach the pipeline-persisted verify_history +
            # edit_history so Smith sees per-stage domain_conformance
            # findings (from stage_verify_ladder) alongside the DB verify
            # run. Rolling buffers are already bounded server-side.
            try:
                from services.session_context import load_history as _sc_load
                hist = _sc_load(resolved)
                if isinstance(hist, dict):
                    payload = dict(payload)  # avoid mutating the DB serializer output
                    payload["session_history"] = {
                        "verify_history": hist.get("verify_history") or [],
                        "edit_history": hist.get("edit_history") or [],
                    }
            except Exception:  # noqa: BLE001
                pass
            if row is None and not payload.get("session_history"):
                return {"error": "no_runs"}
            return payload

    # Same rationale as _smith_publish: sync tool in threadpool → no loop
    # in this thread. Create one, drive to completion, close.
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Threadpool has no loop; asyncio.run() below covers it.
            raise RuntimeError("nested loop")
    except RuntimeError:
        pass
    return asyncio.run(_run())


def _smith_heal_platform_regressions(output_dir: str) -> dict:
    """One-call, in-place repair of every known platform-regression class.

    Mutating but safe: each heal is deterministic, idempotent, and touches
    only platform-owned artifacts (template runtime files, skin CSS rules,
    config safelists, token files) or plan-derived facts (filter enum
    options) — never LLM-authored judgment.
    """
    from services.platform_heals import apply_platform_heals
    report = apply_platform_heals(output_dir)
    report["hint"] = (
        "Heals applied in place. If the app's dev server is running, ask the "
        "user to reload; a node_modules patch (engine_token_prefix) needs the "
        "dev server restarted to take effect."
        if report.get("changed") else
        "No regressions found — this app is already on current platform "
        "behaviour. The symptom likely has an app-specific cause; continue "
        "with check_data_source / read_page diagnosis."
    )
    return report
