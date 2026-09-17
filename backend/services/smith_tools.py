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

#: Wording a defect taught us, kept where the generated line from `VERB_HELP`
#: would lose it. Everything else is generated — this description advertised
#: NINE of the thirty verbs, so every verb the coverage work added was
#: invisible to the model reading it, and `restyle` or `edit_access` could not
#: be chosen from a list that never mentioned them.
_VERB_NOTES: dict[str, str] = {
    'add_field':
        "add ONE NEW field/attribute to an existing entity's DATA MODEL: 'add a discount field to offers', 'give tasks a due date'. This is the verb whenever the ask introduces a new field on an entity, EVEN IF it also says 'and show it on <page>' — the column must exist before any page can show it, and add_widgets/compose_route cannot create a column. Pick add_field now; displaying the field is a separate later edit_page turn.",
    'add_widgets':
        "add named sections to a screen: 'put upcoming sessions and quorum status on the dashboard'. NOT for a new data-model field (see add_field).",
    'compose_route':
        'build or rebuild the screen at a route. Use this when a route renders nothing.',
    'connect_service':
        "make the application ACTUALLY TALK to an outside service: 'connect it to our Outlook', 'send the emails through our own account', 'connect it to Xero'. Outbound email is connected for real; anything with no adapter is refused with the reason and the nearest thing that works. `integration` is the service in the user's words — never a key, which must not reach the conversation log.",
    'connect_figma':
        'attach a Figma design as evidence. `token_env` is the NAME of the environment variable holding the token (e.g. FIGMA_TOKEN); never the token itself, which must not reach the conversation log.',
    'connect_uxpilot':
        'attach a UX Pilot page as evidence. `key_env` is the NAME of the environment variable holding the UX Pilot API key; never the key itself.',
    'disconnect_design':
        "remove the connected design and compose every screen from the component library instead: 'disconnect the Figma design', 'drop the design'.",
    'import_data':
        "load the data they ALREADY HAVE from the spreadsheet they attached: 'here's our customer spreadsheet, load it in'. Needs only which kind of record the file holds; never pass rows or a filename. The first call writes nothing and returns the dry run to show them.",
    'export_data':
        "give them their data back as a spreadsheet: 'can I get all this out as a spreadsheet?', 'back it up somewhere'. One kind of record, or all of them in a zip when no entity is named. Reads only — nothing to confirm, nothing to undo.",
    'rebuild':
        'regenerate the whole application from its definition.',
    'rename':
        'change the wording of something that exists.',
}


def _understand_ask_desc() -> str:
    """The tool's description, carrying every verb the dispatcher can run.

    Generated from `REQUIRED_BY_VERB`, so it cannot fall behind it again: a
    verb the model is never told about is a verb it never picks, and the ask
    lands on whichever of the nine it had heard of instead.
    """
    from services.smith.verbs import REQUIRED_BY_VERB, VERB_HELP

    lines = ["REQUIRED first tool for any change ask (skip for greetings/meta "
             "questions). CHOOSE THE VERB FIRST — each needs different facts, "
             "and a request forced into the wrong one fails as 'nothing to "
             "change':"]
    for verb in sorted(REQUIRED_BY_VERB):
        fields = "{" + ", ".join(sorted(REQUIRED_BY_VERB[verb])) + "}"
        said = _VERB_NOTES.get(verb) or " ".join(str(VERB_HELP.get(verb, "")).split())
        lines.append(f"  {verb} {fields} — {said}")
    lines.append("Omitting `verb` means rename. If you can't confidently fill "
                 "the verb's fields, use read_page / list_pages first; if the "
                 "ask itself is ambiguous, set `clarification_needed` and "
                 "follow up with ask_user. Only SKIP understand_ask for "
                 "greeting/explain turns — every edit turn is gated on it.")
    return "\n".join(lines)


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
     "desc": _understand_ask_desc()},
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
    {"name": "compose_route",
     "signature": "compose_route(route, request?) -> {applied, "
                  "edited_paths, diff_summary, reason?}",
     "desc": "BUILD OR REBUILD THE WHOLE SCREEN at a route, by running "
             "the same page-composition agent the build itself runs "
             "(A2UI + the authoring agent), then committing through the "
             "Blueprint so the app re-projects. Use when a route renders "
             "nothing or 404s, or when the user wants the screen laid "
             "out again from scratch. NOT for changing one label or one "
             "field \u2014 that is edit_page. The page must already exist "
             "in the definition; check list_pages first."},
    {"name": "rename_field",
     "signature": "rename_field(entity, field, new_value) -> {applied, edited_paths, diff_summary, reason?}",
     "desc": "RENAME A FIELD everywhere the Blueprint uses it \u2014 the entity, table columns, "
             "form fields, bindings, workflow values and reads, rules, relationships. "
             "Deterministic. On a Blueprint-built app edit_field(rename) routes here."},
    {"name": "remove_field",
     "signature": "remove_field(entity, field) -> {applied, edited_paths, diff_summary, reason?}",
     "desc": "REMOVE A FIELD and take it out of every screen, workflow and rule that used it; "
             "what still reads it is named for Verify & Fix. On a Blueprint-built app the "
             "legacy remove_field routes here."},
    {"name": "add_requirement",
     "signature": "add_requirement(requirement) -> {applied, diff_summary}",
     "desc": "RECORD A NEW REQUIREMENT in the user's words. Nothing implements it until asked."},
    {"name": "edit_requirement",
     "signature": "edit_requirement(requirement, change) -> {applied, diff_summary}",
     "desc": "RESTATE A REQUIREMENT; the screens, workflows and rules citing it are re-authored against the new wording."},
    {"name": "remove_requirement",
     "signature": "remove_requirement(requirement) -> {applied, diff_summary}",
     "desc": "RETIRE A REQUIREMENT and take it off what cited it."},
    {"name": "edit_product",
     "signature": "edit_product(change) -> {applied, diff_summary}",
     "desc": "CHANGE WHAT THE APP IS CALLED OR IS FOR: name, description, objectives, terminology, personas, locale."},
    {"name": "add_api",
     "signature": "add_api(api) -> {applied, diff_summary}",
     "desc": "DECLARE AN ENDPOINT for an entity, guarded by a permission. Data routes are served by the data engine; anything else needs a handler."},
    {"name": "remove_api",
     "signature": "remove_api(api) -> {applied, diff_summary}",
     "desc": "RETIRE AN ENDPOINT by method and path or id."},
    {"name": "add_integration",
     "signature": "add_integration(integration) -> {applied, diff_summary}",
     "desc": "DECLARE AN INTEGRATION with the NAMES of its secrets (never values)."},
    {"name": "remove_integration",
     "signature": "remove_integration(integration) -> {applied, diff_summary}",
     "desc": "RETIRE AN INTEGRATION by name."},
    {"name": "connect_service",
     "signature": "connect_service(integration) -> {applied, edited_paths, diff_summary, reason?, options?}",
     "desc": "CONNECT AN OUTSIDE SERVICE FOR REAL, not just declare it: \"connect it to our "
             "Outlook\", \"send the emails through our own account\". Outbound email has an "
             "adapter \u2014 the service is recorded in the Blueprint with the NAMES of its "
             "variables, the app is projected to send through it, and the owner sets the key "
             "once on the platform (never here). A service with no adapter is refused with the "
             "reason and the nearest thing that works, and nothing changes. Pass the service in "
             "the user's words; never a credential."},
    {"name": "edit_access",
     "signature": "edit_access(change) -> {applied, edited_paths, diff_summary, reason?}",
     "desc": "CHANGE WHO CAN DO WHAT \u2014 roles, permissions, which roles open which "
             "screen, whether a screen needs a sign-in: \"add a Ward Manager role\", "
             "\"only admins can delete a nurse\", \"make Master Data admin-only\". "
             "Re-decides the Blueprint's roles, permissions and page access and "
             "re-projects the middleware and access maps. On a Blueprint-built app "
             "add_role / remove_role / restrict_page_to_role route here. Pass the "
             "change in the user's words."},
    {"name": "add_login",
     "signature": "add_login(email, person_name?, role?) -> "
                  "{applied, edited_paths, diff_summary, reason?}",
     "desc": "GIVE ONE PERSON A LOGIN: \"set up a login for dave@clinic.com\", "
             "\"my new receptionist needs an account\". The account is created with "
             "NO usable password and a one-time setup link the person opens to "
             "choose their own — never pass a password to this tool and never "
             "repeat one a user offers. Needs the email address they will sign in "
             "with. This is not edit_access: that decides what a ROLE may do, this "
             "decides who exists."},
    {"name": "remove_login",
     "signature": "remove_login(person) -> {applied, edited_paths, diff_summary, reason?}",
     "desc": "STOP ONE PERSON SIGNING IN: \"remove Dave's login\", \"Sarah has "
             "left\". Deactivates the account rather than deleting it, because the "
             "records they created point at it. Needs who, by email or by the name "
             "the login was set up under."},
    {"name": "reset_login",
     "signature": "reset_login(person) -> {applied, edited_paths, diff_summary, reason?}",
     "desc": "GIVE ONE PERSON A WAY BACK IN: \"reset Dave's password\", \"Sarah is "
             "locked out\". Their old password stops working and they get a "
             "one-time link to choose a new one; no password is generated, shown or "
             "stored. Needs who, by email or by the name the login was set up under."},
    {"name": "add_rule",
     "signature": "add_rule(rule) -> {applied, edited_paths, diff_summary, reason?}",
     "desc": "ADD A BUSINESS RULE in the user's words: \"years of experience cannot "
             "exceed 60\". Authored against the entities, recorded in the Blueprint, "
             "projected so it fires on the form. On a Blueprint-built app "
             "create_business_rule routes here."},
    {"name": "edit_rule",
     "signature": "edit_rule(rule, change) -> {applied, edited_paths, diff_summary, reason?}",
     "desc": "CHANGE AN EXISTING BUSINESS RULE: which rule (by name) and what should be different."},
    {"name": "remove_rule",
     "signature": "remove_rule(rule) -> {applied, edited_paths, diff_summary, reason?}",
     "desc": "RETIRE A BUSINESS RULE by name; it stops firing and stays in the history."},
    {"name": "edit_navigation",
     "signature": "edit_navigation(change) -> {applied, edited_paths, diff_summary, reason?}",
     "desc": "CHANGE THE APP'S MENU \u2014 entries, order, labels, icons, group "
             "headings, the page the app opens on: \"put Master Data first\", "
             "\"rename the menu item to Nurse Directory\", \"hide registration "
             "from the sidebar\", \"open on Master Data\". Revises the Blueprint's "
             "navigation and re-projects the shell; no screen is composed. NOT "
             "edit_page (a menu entry is not a control on a screen). Pass the "
             "change in the user's words."},
    {"name": "restyle",
     "signature": "restyle(change) -> {applied, edited_paths, diff_summary, "
                  "changed, decision, reason?}",
     "desc": "CHANGE HOW THE APPLICATION LOOKS \u2014 theme or brand colour, "
             "palette, typography, spacing, density: \"change the theme "
             "colour to green\", \"darker and more compact\". Records the ask "
             "as the binding decision on the design system, re-runs the "
             "design agent against it and re-projects the tokens; every "
             "screen picks the new look up without being re-composed. NOT "
             "edit_page (no single label or control) and NOT compose_route "
             "(no screen is rebuilt). Pass the change in the user's words."},
    {"name": "set_logo",
     "signature": "set_logo(alt?) -> {applied, edited_paths, diff_summary, "
                  "logo, reason?}",
     "desc": "PUT THE OWNER'S LOGO IN THE APPLICATION \u2014 \"put our logo in "
             "the corner\", \"use this as our logo\", \"add our brand mark\". "
             "The image is taken from the file they attached to THIS message; "
             "you do not name it and cannot supply one yourself, so if they "
             "attached nothing this says so and asks for the file. It goes in "
             "the rail's brand block, where the application's initial is, on "
             "every screen. Pass alt only if they said what it should be read "
             "aloud as. NOT restyle \u2014 that is colour and type, and it "
             "cannot carry an image."},
    {"name": "remove_logo",
     "signature": "remove_logo() -> {applied, edited_paths, diff_summary, reason?}",
     "desc": "TAKE THE LOGO BACK OUT \u2014 \"remove the logo\", \"drop our "
             "logo\", \"go back to no logo\". The rail shows the "
             "application's initial again. Takes nothing."},
    {"name": "add_widgets",
     "signature": "add_widgets(route, widgets[], request?) -> {applied, "
                  "edited_paths, diff_summary, reason?}",
     "desc": "ADD NAMED SECTIONS to a screen: \"put upcoming sessions, "
             "quorum status and recent votes on the dashboard\". Records "
             "each widget in the page's contract and then composes the "
             "page again against it, so the Blueprint and the rendered "
             "screen say the same thing \u2014 a patch on the tree alone "
             "would be dropped by the next composition. Pass what each "
             "widget SHOWS, not just its name. NOT for introducing a NEW "
             "DATA-MODEL FIELD: 'add a discount field to offers (and show "
             "it)' is add_field first (it creates the column), THEN edit_page "
             "to display it \u2014 add_widgets only recomposes a screen and "
             "cannot create a column, so the widget would bind to nothing."},
    {"name": "remove_page",
     "signature": "remove_page(route, cascade?, _confirmed?) -> "
                  "{status: 'needs_confirmation'|'ok', ...}",
     "desc": "Take a whole SCREEN out of the application: 'delete the "
             "Wards page'. The route stops resolving, the entry leaves "
             "the menu, and every link to it comes off the screens that "
             "had one \u2014 those screens stop declaring what the link "
             "did. The page is RETIRED, not deleted, so its layout stays "
             "behind it and undo brings it back; its id is never given to "
             "another screen. Refused only when it is the last screen "
             "anyone can arrive at. NOT `remove`, which takes one control "
             "off a screen that stays."},
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
    {"name": "remove_entity",
     "signature": "remove_entity(entity) -> {applied, changes, verify, "
                  "edited_paths} | {status:'needs_confirmation'}",
     "desc": "DROP an entire entity — its table, Drizzle module and barrel "
             "export — 'remove / delete / drop / get rid of the drafts table', "
             "'we don't need the Draft entity anymore'. Target is a whole "
             "ENTITY/TABLE, not a page (that is remove_page) or one column (that "
             "is remove_field). The highest-blast-radius change: the data is gone "
             "and every page whose primary entity it is, every workflow that "
             "operates on it, and every relationship that names it is orphaned. "
             "Returns needs_confirmation with that full cascade first; after it, "
             "the completeness checks surface each orphan to repair. Refuses the "
             "auth/users entity."},
    {"name": "remove_workflow",
     "signature": "remove_workflow(workflow_id) -> {applied, changes, "
                  "verify, edited_paths} | {status:'needs_confirmation'}",
     "desc": "DELETE a workflow file — 'remove / delete / drop / kill / scrap the "
             "DeleteRecord workflow / flow / automation'. Target is a WORKFLOW, "
             "not a page or entity. Every Button/Form that dispatched it stops "
             "resolving, which the workflow-not-defined check then surfaces so the "
             "control is rebound or dropped. To CHANGE a flow's steps instead of "
             "deleting it, use edit_workflow. Reference-breaking, so it confirms "
             "first."},
    {"name": "edit_entity",
     "signature": "edit_entity(entity, new_name?, new_table?) -> {applied, "
                  "changes, verify, edited_paths} | {status:'needs_confirmation'}",
     "desc": "RENAME an entity and/or its table — 'rename the Draft entity to "
             "Post', 'call the Draft entity Post instead', 'the customers table "
             "should be clients'. Moves the registry entry, the Drizzle module "
             "(file, exported const, pgTable name) and the barrel export together. "
             "new_table alone renames just the table. NOT a field rename (that is "
             "edit_field) and NOT a page title change (that is edit_page/rename). "
             "The highest-cascade change: every workflow, page, relationship and "
             "foreign key that named the old entity must move, so it confirms "
             "first and the completeness checks surface each reference. Refuses "
             "the auth/users entity and any rename into that namespace."},
    {"name": "export_data",
     "signature": "export_data(entity?) -> {applied, file, href, sheets, reason}",
     "desc": "GIVE THE OWNER THEIR DATA BACK as a spreadsheet — 'can I get "
             "all this out as a spreadsheet?', 'export the customers', 'back "
             "it up somewhere'. Reads the rows out of the application's own "
             "database and writes the file on this call. `entity` narrows it "
             "to one kind of record; omit it for every kind in one zip, which "
             "is what a backup means. READS ONLY — nothing about the "
             "application changes, so there is nothing to confirm and nothing "
             "to undo. Show the returned markdown link as it is: it is the "
             "download. Sensitive fields are left out of the file by design "
             "and the summary says which."},
    {"name": "import_data",
     "signature": "import_data(entity, confirm?, ignore_columns?[]) -> "
                  "{applied, asked, reason, options, edited_paths}",
     "desc": "LOAD THE DATA THEY ALREADY HAVE from the spreadsheet attached to "
             "this conversation — 'here's our customer spreadsheet, load it in', "
             "'import these suppliers'. Every owner arrives with an existing "
             "business and existing data; without this the first real use of "
             "the app is typing it all in again. Pass only WHICH KIND OF "
             "RECORD the file holds (check list_entities); the file is the one "
             "they attached and is read from disk — never pass rows, and never "
             "transcribe a row into any tool call. "
             "CALLED WITHOUT `confirm` IT WRITES NOTHING: it returns the dry "
             "run — how many rows would land, how many would not and why, and "
             "which column becomes which field. Show that to them verbatim and "
             "wait. When they agree, call it again with confirm=true and the "
             "rows are written under the mapping they were shown. A column the "
             "record has no field for is REFUSED, not guessed at: either "
             "add_field first, or pass it in ignore_columns to leave it out."},
    {"name": "add_field",
     "signature": "add_field(entity, field:{name, type, length?, "
                  "precision?, scale?, default?}) -> {applied, changes, "
                  "verify, edited_paths}",
     "desc": "Add ONE column to an EXISTING entity's data model — the "
             "incremental, non-destructive path for 'add a discount field "
             "to offers', 'give tasks a due date', 'add a phone number to "
             "customers'. Writes exactly two files (the registry field list "
             "+ that entity's Drizzle module), so downstream it lands as a "
             "`drizzle-kit push` (the column is created, existing rows keep "
             "their data) — NEVER a rebuild/reset/reseed. The column is "
             "always nullable so the push can't fail on existing rows. "
             "Use this — NOT rebuild, NOT a definition update — whenever the "
             "ask is one new field on an entity that already exists (check "
             "list_entities). To also SHOW the field on a screen, follow "
             "with edit_page(<that page>, 'show the new discount field'). "
             "Rolled back atomically on failure; refuses a duplicate field "
             "or an unknown entity."},
    {"name": "remove_field",
     "signature": "remove_field(entity, field) -> {applied, changes, "
                  "verify, edited_paths} | {status:'needs_confirmation'}",
     "desc": "DROP one column from an entity's DATA MODEL — 'remove / delete / "
             "drop / get rid of / scrap the middle-name field from customers'. "
             "SCOPE MATTERS: this deletes the column AND ITS DATA. If the ask is "
             "only to stop SHOWING a field on a screen ('take phone off the "
             "signup form', 'hide the notes field') — the column stays — that is "
             "edit_page, NOT this. Writes the registry + that entity's Drizzle "
             "module (a drizzle-kit push). Reference-breaking: a workflow step, "
             "form field or binding that named it now points at nothing, so it "
             "returns needs_confirmation first and the field-ripple checks "
             "surface the references to repair. Refuses the primary key, the "
             "managed timestamps, and a foreign-key column."},
    {"name": "edit_field",
     "signature": "edit_field(entity, field, new_name?, new_type?) -> "
                  "{applied, changes, verify, edited_paths} | "
                  "{status:'needs_confirmation'}",
     "desc": "RENAME and/or RETYPE one column's DATA MODEL — 'rename "
             "customers.fullName to displayName', 'call the age field yearsOld', "
             "'make age a number/text', 'change price to a decimal'. Updates the "
             "registry + the Drizzle column (var, column name, builder). NOT for "
             "changing HOW a field is entered — 'make gender a dropdown', 'use a "
             "date picker for dob', 'show price as currency' is set_field_interaction "
             "(a UI change, same column type). A rename is reference-breaking "
             "(every workflow/form/binding that named the old field must move), so "
             "it returns needs_confirmation first and the ripple checks flag what "
             "still names it. Pass at least one of new_name / new_type; refuses "
             "managed columns."},
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
    if _is_blueprint_app(output_dir) and isinstance(args, dict):
        text = " ".join(str(args.get(k) or "") for k in ("name", "rule_type", "field_name") if args.get(k))
        cfg = args.get("config")
        text = (text + (f" — {json.dumps(cfg)}" if cfg else "")).strip()
        return _smith_rule(output_dir, "add_rule", {"rule": text})
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
    "restyle":                  lambda output_dir, args: _smith_restyle(output_dir, args),
    "set_logo":                 lambda output_dir, args: _smith_set_logo(output_dir, args),
    "remove_logo":              lambda output_dir, args: _smith_remove_logo(output_dir),
    "edit_navigation":          lambda output_dir, args: _smith_edit_navigation(output_dir, args),
    "edit_access":              lambda output_dir, args: _smith_edit_access(output_dir, args),
    "rename_field":             lambda output_dir, args: _smith_field_change(output_dir, "rename_field", args),
    "add_requirement":          lambda output_dir, args: _smith_definition(output_dir, "add_requirement", args),
    "edit_requirement":         lambda output_dir, args: _smith_definition(output_dir, "edit_requirement", args),
    "remove_requirement":       lambda output_dir, args: _smith_definition(output_dir, "remove_requirement", args),
    "edit_product":             lambda output_dir, args: _smith_definition(output_dir, "edit_product", args),
    "add_api":                  lambda output_dir, args: _smith_definition(output_dir, "add_api", args),
    "remove_api":               lambda output_dir, args: _smith_definition(output_dir, "remove_api", args),
    "connect_service":          lambda output_dir, args: _smith_connect_service(output_dir, args),
    "add_integration":          lambda output_dir, args: _smith_definition(output_dir, "add_integration", args),
    "remove_integration":       lambda output_dir, args: _smith_definition(output_dir, "remove_integration", args),
    "add_rule":                 lambda output_dir, args: _smith_rule(output_dir, "add_rule", args),
    "edit_rule":                lambda output_dir, args: _smith_rule(output_dir, "edit_rule", args),
    "remove_rule":              lambda output_dir, args: _smith_rule(output_dir, "remove_rule", args),
    "add_page":                 lambda output_dir, args: _smith_add_page(output_dir, args),
    # Whole-screen composition \u2014 the page_layouts agent, reachable from a
    # conversation. See services/smith/compose.py.
    "compose_route":            lambda output_dir, args: _smith_compose(output_dir, args, "compose_route"),
    "add_widgets":              lambda output_dir, args: _smith_compose(output_dir, args, "add_widgets"),
    "remove_page":              lambda output_dir, args: _smith_remove_page(output_dir, args),
    "add_workflow":             lambda output_dir, args: _smith_add_workflow(output_dir, args),
    "wire_form_to_workflow":    lambda output_dir, args: _smith_wire_form_to_workflow(output_dir, args),
    "use_21st_component":       lambda output_dir, args: _smith_use_21st_component(output_dir, args),
    "set_field_interaction":    lambda output_dir, args: _smith_set_field_interaction(output_dir, args),
    "create_business_rule":     lambda output_dir, args: _smith_create_business_rule(output_dir, args),
    "add_entity":               lambda output_dir, args: _smith_add_entity(output_dir, args),
    "remove_entity":            lambda output_dir, args: _smith_remove_entity(output_dir, args),
    "edit_entity":              lambda output_dir, args: _smith_edit_entity(output_dir, args),
    "remove_workflow":          lambda output_dir, args: _smith_remove_workflow(output_dir, args),
    "add_field":                lambda output_dir, args: _smith_add_field(output_dir, args),
    "revert":                   lambda output_dir, args: _smith_revert(output_dir),
    "write_guide":              lambda output_dir, args: _smith_write_guide(output_dir),
    "spend":                    lambda output_dir, args: _smith_spend(output_dir),
    "import_data":              lambda output_dir, args: _smith_import_data(output_dir, args),
    "export_data":              lambda output_dir, args: _smith_export_data(output_dir, args),
    "add_login":                lambda output_dir, args: _smith_account(output_dir, "add_login", args),
    "remove_login":             lambda output_dir, args: _smith_account(output_dir, "remove_login", args),
    "reset_login":              lambda output_dir, args: _smith_account(output_dir, "reset_login", args),
    "explain_crash":            lambda output_dir, args: _smith_explain_crash(output_dir),
    "explain_slowness":         lambda output_dir, args: _smith_explain_slowness(output_dir),
    "remove_field":             lambda output_dir, args: _smith_remove_field(output_dir, args),
    "edit_field":               lambda output_dir, args: _smith_edit_field(output_dir, args),
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
    # SV-9 — in the catalogue since the initial commit, dispatchable since
    # 2026-09-10. Without this the model was coached to call a tool that
    # fell through to "unknown tool" every time.
    "verify_app":               lambda output_dir, args: _smith_verify_app(output_dir, args),
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


def _is_blueprint_app(output_dir: str) -> bool:
    from pathlib import Path as _P
    return (_P(output_dir) / ".forge" / "blueprint" / "current.json").exists()


def _smith_field_change(output_dir: str, verb: str, args: dict) -> dict:
    from services.smith.field_change import run as _field_run
    if not isinstance(args, dict):
        return {"applied": False, "edited_paths": [], "reason": f"{verb} requires an object arg"}
    field = args.get("field") or args.get("field_name") or ""
    field = str(field.get("name") or "") if isinstance(field, dict) else str(field)
    return _field_run(output_dir, verb, entity=str(args.get("entity") or ""), field=field,
                      new_value=str(args.get("new_value") or args.get("new_name") or ""))


def _smith_connect_service(output_dir: str, args: dict) -> dict:
    from services.smith.email_connect import run as _connect_run
    if not isinstance(args, dict):
        return {"applied": False, "edited_paths": [], "reason": "connect_service requires an object arg"}
    said = str(args.get("integration") or args.get("service") or args.get("request") or "").strip()
    if not said:
        return {"applied": False, "edited_paths": [],
                "reason": "nothing given. Pass integration: the service to connect, in the user's words."}
    return _connect_run(output_dir, service=said)


def _smith_definition(output_dir: str, verb: str, args: dict) -> dict:
    from services.smith.definition_change import run as _def_run
    if not isinstance(args, dict):
        return {"applied": False, "edited_paths": [], "reason": f"{verb} requires an object arg"}
    key = {"add_requirement": "requirement", "edit_requirement": "requirement", "remove_requirement": "requirement",
           "edit_product": "change", "add_api": "api", "remove_api": "api",
           "add_integration": "integration", "remove_integration": "integration"}[verb]
    text = str(args.get(key) or args.get("request") or "").strip()
    if not text:
        return {"applied": False, "edited_paths": [], "reason": f"nothing given. Pass {key}."}
    return _def_run(output_dir, verb, text=text, change=str(args.get("change") or "").strip())


def _smith_edit_access(output_dir: str, args: dict) -> dict:
    from services.smith.access_change import run as _access_run
    if not isinstance(args, dict):
        return {"applied": False, "edited_paths": [], "reason": "edit_access requires an object arg"}
    change = str(args.get("change") or args.get("request") or "").strip()
    if not change:
        return {"applied": False, "edited_paths": [], "reason": "no change described. Pass change: who should be able to do what."}
    return _access_run(output_dir, change)


def _smith_rule(output_dir: str, verb: str, args: dict) -> dict:
    from services.smith.rule_change import run as _rule_run
    if not isinstance(args, dict):
        return {"applied": False, "edited_paths": [], "reason": f"{verb} requires an object arg"}
    rule = str(args.get("rule") or args.get("name") or args.get("request") or "").strip()
    if not rule:
        return {"applied": False, "edited_paths": [], "reason": "no rule named. Pass rule: the rule in the user's words, or its name."}
    return _rule_run(output_dir, verb, rule=rule, change=str(args.get("change") or "").strip())


def _smith_edit_navigation(output_dir: str, args: dict) -> dict:
    """Thin, like the compose tools: `services.smith.navigation_change.run` is
    the one place the menu changes, and `smith_session` reaches it by verb."""
    from services.smith.navigation_change import run as _nav_run

    if not isinstance(args, dict):
        return {"applied": False, "edited_paths": [], "reason": "edit_navigation requires an object arg"}
    change = str(args.get("change") or args.get("request") or "").strip()
    if not change:
        return {"applied": False, "edited_paths": [],
                "reason": "no change described. Pass change: what should be different about the menu."}
    return _nav_run(output_dir, change)


def _smith_restyle(output_dir: str, args: dict) -> dict:
    """Thin on purpose, like the compose tools: `services.smith.restyle.run`
    is the one place a restyle happens, and `smith_session` reaches it by verb."""
    from services.smith.restyle import run as _restyle_run

    if not isinstance(args, dict):
        return {"applied": False, "edited_paths": [], "reason": "restyle requires an object arg"}
    change = str(args.get("change") or args.get("request") or "").strip()
    if not change:
        return {"applied": False, "edited_paths": [],
                "reason": "no change described. Pass change: what should look different, in the user's words."}
    return _restyle_run(output_dir, change)


#: Tools the loop hands this turn's attached files to. See the dispatch site in
#: `agents/smith_agent.py`: the model can see that a file was attached but never
#: the id it is stored under, so a tool that needs the bytes has to be given
#: them rather than asked for them.
TURN_FILE_TOOLS = frozenset({"set_logo"})


def _smith_set_logo(output_dir: str, args: dict) -> dict:
    """The owner's mark, from the file they attached to this turn.

    Thin like the rest: `services.smith.brand_logo_change.run` is the one place
    `designSystem.logo` is written, and the upload route reaches the same
    function. `services.brand_logo.store` is the one place the bytes land.

    `files` is injected by the loop, not by the model — see `TURN_FILE_TOOLS`.
    """
    from services import brand_logo
    from services.smith.brand_logo_change import run as _logo_run

    if not isinstance(args, dict):
        return {"applied": False, "edited_paths": [], "reason": "set_logo requires an object arg"}

    images = [f for f in (args.get("files") or [])
              if isinstance(f, dict) and str(f.get("kind") or "") == "image"]
    if not images:
        return {"applied": False, "edited_paths": [],
                "reason": ("no image came with this message, and I cannot make one. "
                           "Attach the logo file here \u2014 a PNG, JPEG, GIF or WebP \u2014 "
                           "or upload it as the project's logo, and I will put it in "
                           "the corner of every screen.")}
    if len(images) > 1:
        names = ", ".join(str(f.get("filename") or f.get("id")) for f in images)
        return {"applied": False, "edited_paths": [],
                "reason": (f"{len(images)} images came with this message ({names}). "
                           f"Send the logo on its own and I will use it \u2014 I will not "
                           f"guess which of them is the mark.")}

    rec = images[0]
    path = str(rec.get("path") or "")
    if not path:
        return {"applied": False, "edited_paths": [],
                "reason": "I could not read that file any more \u2014 attach it again."}
    try:
        from pathlib import Path as _Path
        body = brand_logo.store(output_dir, str(rec.get("filename") or "logo"),
                                str(rec.get("media_type") or ""),
                                _Path(path).read_bytes())
    except brand_logo.BrandLogoError as exc:
        return {"applied": False, "edited_paths": [], "reason": str(exc)}
    except OSError as exc:
        return {"applied": False, "edited_paths": [],
                "reason": f"I could not read that file: {exc}"}
    return _logo_run(output_dir, logo=body, alt=str(args.get("alt") or ""))


def _smith_remove_logo(output_dir: str) -> dict:
    """Its own tool rather than a flag on `set_logo`, so which of the two is
    meant is read off the sentence by the model — "remove the old logo and use
    this one" is a `set_logo`, and a flag inferred from the word "remove"
    would get it backwards."""
    from services.smith.brand_logo_change import run as _logo_run

    return _logo_run(output_dir, remove=True)


def _smith_compose(output_dir: str, args: dict, verb: str) -> dict:
    """Compose a screen through the agent that already composes screens.

    Smith could see every page and change one label on one of them. The
    composer it needed was `page_layouts`, which the build runs for every
    page and which nothing routed a conversation into \u2014 so asked to build a
    dashboard Smith replied that nothing needed changing, four times, having
    understood the request perfectly.

    Thin on purpose: `services.smith.compose.run` is the one place that loads
    the Blueprint, runs the agent and commits through `apply_change`, and
    `smith_session` reaches the same function by verb. Two entry points doing
    it separately would be two answers to what composing a route means.
    """
    from services.smith.compose import run as _compose_run

    if not isinstance(args, dict):
        return {"applied": False, "edited_paths": [],
                "reason": f"{verb} requires an object arg"}
    route = str(args.get("route") or "").strip()
    if not route:
        return {"applied": False, "edited_paths": [],
                "reason": ("no route given. Pass the path of the screen "
                           "(\"/\", \"/sessions\"); list_pages shows them.")}
    widgets = args.get("widgets") or args.get("sections") or []
    if isinstance(widgets, str):
        widgets = [widgets]
    if verb == "add_widgets" and not widgets:
        return {"applied": False, "edited_paths": [],
                "reason": ("no widgets named. Pass widgets:[...] saying what "
                           "each one shows.")}
    return _compose_run(output_dir, verb, route=route, widgets=widgets,
                        request=str(args.get("request") or ""))


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
    """Take a whole screen out of the application.

    A BLUEPRINT APP REMOVES ITS PAGE THROUGH THE BLUEPRINT. The legacy path
    below deletes the schema file on disk, and a Blueprint application
    regenerates that file from the page the document still declares — so the
    tool reported success and the next projection put the screen back. That is
    the "asked twice and still sees the page" failure this verb exists to end.
    `page_change.run` retires the page itself, and the schema file goes because
    nothing plans it any more.

    Below it, phase 1a — confirmation gate. Refuses to execute unless the LLM

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
    if _is_blueprint_app(output_dir) and isinstance(args, dict):
        from services.smith.engine_blueprint_adapter import load_engine_doc
        from services.smith.page_change import consequences
        from services.smith.page_change import run as _page_run
        if not args.get("_confirmed"):
            said = consequences(load_engine_doc(output_dir) or {}, route)
            if said.get("found"):
                takes = list(said["menu"]) + list(said["links"]) + list(said["launches"])
                if takes:
                    return needs_confirmation_result(
                        "page", route or "?", dependents=takes, removes=[said["route"]])
        return _page_run(output_dir, route=route)
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


def _blueprint_workflow_change(output_dir: str, verb: str, args: dict) -> dict | None:
    """A Blueprint-built app changes its workflows through the Blueprint —
    `services.smith.workflow_change`, the same path the chat verb takes. The
    file seams below edit `workflows/*.json` and `contracts/resource-registry.json`,
    which such an app does not have; they stay for registry-only apps."""
    from pathlib import Path as _P
    if not (_P(output_dir) / ".forge" / "blueprint" / "current.json").exists():
        return None
    from services.smith.workflow_change import run as _wf_run
    return _wf_run(
        output_dir, verb,
        workflow=str(args.get("request") or args.get("workflow") or args.get("workflow_id")
                     or args.get("name") or args.get("id") or "").strip(),
        change=str(args.get("change") or args.get("changes") or "").strip()
        if not isinstance(args.get("changes"), dict) else json.dumps(args.get("changes")),
        route=str(args.get("route") or "").strip(),
    )


def _smith_add_workflow(output_dir: str, args: dict) -> dict:
    """Direct wrapper around :func:`fix_applier._apply_add_workflow`."""
    bp = _blueprint_workflow_change(output_dir, "add_workflow", args)
    if bp is not None:
        return bp
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
    if _is_blueprint_app(output_dir) and isinstance(args, dict):
        from services.smith.entity_change import run as _entity_run
        fields = args.get("fields")
        text = str(args.get("request") or args.get("name") or "").strip()
        if fields:
            text += " with " + (", ".join(f"{f.get('name')} ({f.get('type')})" if isinstance(f, dict) else str(f) for f in fields)
                                if isinstance(fields, list) else str(fields))
        return _entity_run(output_dir, "add_entity", entity=text)
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


def _smith_remove_entity(output_dir: str, args: dict) -> dict:
    if _is_blueprint_app(output_dir) and isinstance(args, dict):
        from services.smith.entity_change import run as _entity_run
        return _entity_run(output_dir, "remove_entity", entity=str(args.get("entity") or args.get("name") or "").strip())
    """Drop an entire entity. Highest blast radius, so it confirms first with
    the true cascade (dependent pages/workflows/relationships)."""
    from services.confirmation_gate import needs_confirmation_result
    from services.fix_applier import _apply_remove_entity
    entity = args.get("entity") or args.get("name") or ""
    if not args.get("_confirmed"):
        deps: list[str] = []
        try:
            from services.remove_entity_seam import dependents
            from services.registry import load_registry
            doc = load_registry(output_dir) or {}
            deps = dependents(doc, entity)
        except Exception:  # noqa: BLE001 — confirmation must not fail on a read
            deps = []
        return needs_confirmation_result(
            "entity", entity, dependents=deps or [f"the {entity} table and its data"],
            cascade=True, removes=deps)
    diagnosis = {
        "artifact": {"kind": "entity", "path": entity},
        "explanation": "",
        "proposedFix": {"seam": "remove_entity", "patch": {"entity": entity}},
    }
    result = _apply_remove_entity(output_dir, diagnosis, git=False)
    result["edited_paths"] = [c["path"] for c in result.get("changes") or [] if c.get("path")]
    return result


def _smith_edit_entity(output_dir: str, args: dict) -> dict:
    """Rename an entity and/or its table. Highest-cascade edit, so it confirms
    first with the dependent pages/workflows/relationships."""
    from services.confirmation_gate import needs_confirmation_result
    from services.fix_applier import _apply_edit_entity
    entity = args.get("entity") or args.get("name") or ""
    new_name = args.get("new_name")
    new_table = args.get("new_table")
    if not args.get("_confirmed"):
        deps: list[str] = []
        try:
            from services.remove_entity_seam import dependents
            from services.registry import load_registry
            deps = dependents(load_registry(output_dir) or {}, entity)
        except Exception:  # noqa: BLE001 — confirmation must not fail on a read
            deps = []
        target = new_name or new_table or entity
        return needs_confirmation_result(
            "entity", f"{entity} → {target}", action="rename",
            dependents=deps or [f"everything that names {entity!r} must move to {target!r}"])
    diagnosis = {
        "artifact": {"kind": "entity", "path": entity},
        "explanation": "",
        "proposedFix": {"seam": "edit_entity", "patch": {
            "entity": entity, "new_name": new_name, "new_table": new_table}},
    }
    result = _apply_edit_entity(output_dir, diagnosis, git=False)
    result["edited_paths"] = [c["path"] for c in result.get("changes") or [] if c.get("path")]
    return result


def _smith_remove_workflow(output_dir: str, args: dict) -> dict:
    """Delete a workflow file. Reference-breaking, so it confirms first."""
    from services.confirmation_gate import needs_confirmation_result
    from services.fix_applier import _apply_remove_workflow
    wid = args.get("workflow_id") or args.get("workflow") or args.get("id") or ""
    bp = _blueprint_workflow_change(output_dir, "remove_workflow", args)
    if bp is not None:
        return bp
    if not args.get("_confirmed"):
        return needs_confirmation_result(
            "workflow", wid,
            dependents=[f"every Button or Form that dispatched {wid!r} stops "
                        f"resolving until it is rebound or removed"])
    diagnosis = {
        "artifact": {"kind": "workflow", "path": wid},
        "explanation": "",
        "proposedFix": {"seam": "remove_workflow", "patch": {"workflow_id": wid}},
    }
    result = _apply_remove_workflow(output_dir, diagnosis, git=False)
    result["edited_paths"] = [c["path"] for c in result.get("changes") or [] if c.get("path")]
    return result


def _smith_account(output_dir: str, verb: str, args: dict) -> dict:
    """add_login / remove_login / reset_login — see services/smith/accounts.py.

    NO PASSWORD IS AN ARGUMENT HERE, by design. The account gets a one-time
    setup link and the person chooses their own password, which the platform's
    own route hashes; a `password` key handed in would be a plaintext
    credential in a tool call that is written to the conversation log, so it is
    ignored rather than honoured.
    """
    from services.smith.accounts import run as _accounts_run
    if not isinstance(args, dict):
        return {"applied": False, "edited_paths": [], "reason": f"{verb} requires an object arg"}
    email = str(args.get("email") or "").strip()
    person = str(args.get("person") or args.get("who") or "").strip()
    if verb == "add_login" and not email:
        return {"applied": False, "edited_paths": [],
                "reason": "no email address given. Pass email: the address the "
                          "person will sign in with."}
    if verb != "add_login" and not (person or email):
        return {"applied": False, "edited_paths": [],
                "reason": "nobody named. Pass person: their email address, or the "
                          "name their login was set up under."}
    return _accounts_run(output_dir, verb, email=email, person=person,
                         name=str(args.get("person_name") or args.get("name") or "").strip(),
                         role=str(args.get("role") or "").strip())


def _smith_revert(output_dir: str) -> dict:
    """Undo the last recorded change and re-project. Takes no arguments: it is
    always the most recent change."""
    from services.smith.revert import run as _revert_run
    return _revert_run(output_dir)


def _smith_write_guide(output_dir: str) -> dict:
    """Write the staff guide from the composed application. Takes no arguments:
    the audiences and the screens are read off the document, and it changes
    nothing about the application."""
    from services.smith.handover import run as _guide_run
    return _guide_run(output_dir)
def _smith_spend(output_dir: str) -> dict:
    """Report what this application has cost to run. Takes no arguments — it is
    always this application — and changes nothing."""
    from services.smith.spend import run as _spend_run
    return _spend_run(output_dir)
def _smith_import_data(output_dir: str, args: dict) -> dict:
    """Load an attached spreadsheet into one kind of record.

    Without `confirm` this is a dry run that writes nothing — the counts, the
    rejects and the column-to-field mapping, for the model to show and the
    owner to agree to. `confirm` applies the import that was described, under
    the mapping that was shown rather than one decided again.
    """
    from services.smith.data_import import run as _import_run
    ignore = [str(c) for c in (args.get("ignore_columns") or []) if str(c).strip()]
    return _import_run(output_dir, str(args.get("entity") or ""),
                       confirm=bool(args.get("confirm")),
                       ignore_columns=ignore)


def _smith_export_data(output_dir: str, args: dict) -> dict:
    """Produce a spreadsheet of the owner's records. Reads only.

    The project id is not an argument of this tool — the handlers are
    `(output_dir, args)` — and the directory's name IS the project's short id,
    which is what the platform's own download URL is keyed by (the same
    derivation `preview_manager` callers use).
    """
    from services.smith.data_export import run as _export_run
    return _export_run(output_dir, str(args.get("entity") or ""))
def _smith_explain_crash(output_dir: str) -> dict:
    """What the running application has reported as crashing. Reads the
    project's incident ledger; changes nothing. Takes no arguments — not
    knowing what broke is why anybody asks."""
    from services.incident_ledger import KIND_CRASH
    from services.smith.incidents import run as _incidents_run
    return _incidents_run(output_dir, kind=KIND_CRASH)


def _smith_explain_slowness(output_dir: str) -> dict:
    """What the running application has timed as too slow, and what cannot be
    done about it. Reads the incident ledger; changes nothing."""
    from services.incident_ledger import KIND_SLOW
    from services.smith.incidents import run as _incidents_run
    return _incidents_run(output_dir, kind=KIND_SLOW)


def _smith_add_field(output_dir: str, args: dict) -> dict:
    """Add one column to an EXISTING entity — the incremental data-model change
    a field-add is supposed to be, instead of a whole-app rebuild (F-01).

    Args: ``{entity: str, field: {name, type, length?, precision?, scale?,
    default?}}``. Also accepts ``name``/``type`` as a flat shorthand.
    """
    from services.fix_applier import _apply_add_field
    field = args.get("field")
    if not isinstance(field, dict):
        # Flat shorthand: {entity, name, type, ...}
        field = {k: args[k] for k in ("name", "type", "label", "length", "precision", "scale", "default")
                 if k in args}
    if _is_blueprint_app(output_dir):
        # The Blueprint seam: the column AND the control on every form that
        # edits the entity and every table that lists it, committed and
        # re-projected — the same path the verb takes in smith_session.
        from services.smith.field_change import run as _field_run
        return _field_run(output_dir, "add_field", entity=str(args.get("entity") or ""),
                          field={k: field.get(k) for k in ("name", "type", "label") if field.get(k)})
    diagnosis = {
        "artifact": {"kind": "field", "path": f"{args.get('entity') or ''}.{field.get('name') or ''}"},
        "explanation": "",
        "proposedFix": {"seam": "add_field", "patch": {
            "entity": args.get("entity") or "",
            "field":  field or {},
        }},
    }
    result = _apply_add_field(output_dir, diagnosis, git=False)
    result["edited_paths"] = [c["path"] for c in result.get("changes") or [] if c.get("path")]
    return result


def _smith_remove_field(output_dir: str, args: dict) -> dict:
    if _is_blueprint_app(output_dir) and isinstance(args, dict):
        return _smith_field_change(output_dir, "remove_field", args)
    """Drop one column from an existing entity. Data-affecting and
    reference-breaking, so it confirms first (unless ``_confirmed``)."""
    from services.confirmation_gate import needs_confirmation_result
    from services.fix_applier import _apply_remove_field
    entity = args.get("entity") or ""
    field = args.get("field") or args.get("field_name") or ""
    if not args.get("_confirmed"):
        return needs_confirmation_result(
            "field", f"{entity}.{field}",
            dependents=[
                f"the column and its data are dropped",
                f"every workflow step, form field and binding that names "
                f"{field!r} stops resolving until it is repaired",
            ])
    diagnosis = {
        "artifact": {"kind": "field", "path": f"{entity}.{field}"},
        "explanation": "",
        "proposedFix": {"seam": "remove_field", "patch": {"entity": entity, "field": field}},
    }
    result = _apply_remove_field(output_dir, diagnosis, git=False)
    result["edited_paths"] = [c["path"] for c in result.get("changes") or [] if c.get("path")]
    return result


def _smith_edit_field(output_dir: str, args: dict) -> dict:
    if _is_blueprint_app(output_dir) and isinstance(args, dict):
        if not (args.get("new_name") or args.get("new_value")):
            return {"applied": False, "edited_paths": [], "reason": "on a Blueprint-built app a field is renamed with new_name; retyping is not supported yet"}
        return _smith_field_change(output_dir, "rename_field", args)
    """Rename and/or retype one column. A rename is reference-breaking, so a
    rename confirms first; a pure retype applies directly."""
    from services.confirmation_gate import needs_confirmation_result
    from services.fix_applier import _apply_edit_field
    entity = args.get("entity") or ""
    field = args.get("field") or args.get("field_name") or ""
    new_name = args.get("new_name")
    new_type = args.get("new_type")
    if new_name and not args.get("_confirmed"):
        return needs_confirmation_result(
            "field", f"{entity}.{field} → {new_name}", action="rename",
            dependents=[
                f"every workflow step, form field and binding that names "
                f"{field!r} must move to {new_name!r} or it stops resolving",
            ])
    diagnosis = {
        "artifact": {"kind": "field", "path": f"{entity}.{field}"},
        "explanation": "",
        "proposedFix": {"seam": "edit_field", "patch": {
            "entity": entity, "field": field,
            "new_name": new_name, "new_type": new_type}},
    }
    result = _apply_edit_field(output_dir, diagnosis, git=False)
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
    bp = _blueprint_workflow_change(output_dir, "edit_workflow", args)
    if bp is not None:
        return bp

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
    if _is_blueprint_app(output_dir) and isinstance(args, dict):
        return _smith_edit_access(output_dir, {"change": f"add a role named {args.get('role_name') or args.get('name') or ''}"})
    """Add a role to plan['actors']. Phase 6."""
    from services.role_seams import add_role_in_file
    return add_role_in_file(output_dir, args.get("role_name") or "")


def _smith_remove_role(output_dir: str, args: dict) -> dict:
    if _is_blueprint_app(output_dir) and isinstance(args, dict):
        return _smith_edit_access(output_dir, {"change": f"remove the role {args.get('role_name') or args.get('name') or ''}"})
    """Remove a role from plan['actors']. Phase 6."""
    from services.role_seams import remove_role_in_file
    return remove_role_in_file(output_dir, args.get("role_name") or "")


def _smith_restrict_page_to_role(output_dir: str, args: dict) -> dict:
    if _is_blueprint_app(output_dir) and isinstance(args, dict):
        return _smith_edit_access(output_dir, {"change": f"only the {args.get('role_name') or ''} role may open {args.get('page_route') or args.get('route') or ''}"})
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


async def _project_id_for_output_dir(db, output_dir: str):
    """The Project row that owns ``output_dir``, or None.

    Exact resolved path first; then by directory name, because some projects
    store relative paths and the mismatch must not read as "no project".
    """
    from pathlib import Path

    from sqlalchemy import select as _select

    from models.project import Project as _Project

    resolved = str(Path(output_dir).resolve())
    project = (await db.execute(
        _select(_Project).where(_Project.output_dir == resolved),
    )).scalar_one_or_none()
    if project is None:
        projects = (await db.execute(_select(_Project))).scalars().all()
        project = next(
            (p for p in projects if p.output_dir
             and Path(p.output_dir).name == Path(resolved).name),
            None,
        )
    return project.id if project is not None else None


def _smith_verify_app(output_dir: str, args: dict) -> dict:
    """Run the Self-Verify Pass (SV-9) on the app in ``output_dir``.

    The same pass the plain-language route fires from ``routers.generate``
    when a message reads as a verify intent; this is the in-loop path, for
    when Smith decides to verify. ``fix`` defaults to true as the catalogue
    promises. Sync wrapper, same shape as :func:`_smith_read_last_verify_run`:
    the SDK dispatches tools synchronously from a threadpool, so a loop is
    created here and driven to completion.
    """
    import asyncio

    from database import async_session

    scope = str(args.get("scope") or "*")
    target = "deploy" if str(args.get("target") or "preview") == "deploy" else "preview"
    fix = args.get("fix", True)
    fix = fix if isinstance(fix, bool) else str(fix).strip().lower() not in ("false", "0", "no")

    async def _run() -> dict:
        from services.self_verify_pass import run_self_verify

        async with async_session() as db:
            project_id = await _project_id_for_output_dir(db, output_dir)
        if project_id is None:
            return {"error": "project_not_found_for_output_dir"}
        return await run_self_verify(
            project_id, target=target, scope=scope, fix=fix,
            invoked_by="user_chat",
        )

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            raise RuntimeError("nested loop")
    except RuntimeError:
        pass
    return asyncio.run(_run())


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
