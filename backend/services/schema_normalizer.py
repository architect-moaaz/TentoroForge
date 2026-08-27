"""Schema normalizer — rewrite LLM-emitted v1-style prop shapes to v2.

The LLM consistently produces near-but-not-quite-v2 prop shapes:
  Button.content      → Button.label
  Button.href         → Button.navigate
  Button.variant=outline → Button.variant=secondary
  Link.content        → Link.label
  Link.href           → Link.navigate
  Badge.text/.label   → Badge.content
  Badge.variant=info|error|secondary → primary|danger|neutral
  Input/Textarea/Select/DatePicker validators.minLength/maxLength → min/max
  Tabs.{defaultValue, variant} → {tabs[], value}  (synthesise placeholder tab)
  Accordion.mode=multiple → multi
  Hero.layout=horizontal/etc → centered
  MetricTile.format=text/string → number
  MetricTile.suffix → drop (not in v2)
  Table/TableSortable column.title → label
  Table/TableSortable column.type/.sortable → drop
  Form Card columns w/ empty label → fall back to key

The runtime registry's lenient validateProps (packages/library/src/registry.ts)
covers these at render time, but normalising at GENERATION time means the
schemas on disk are clean — the editor's strict-parse path also accepts them,
saved schemas don't surprise reviewers, and the lenient runtime path is
defence-in-depth rather than load-bearing.
"""
from __future__ import annotations

from typing import Any


_BUTTON_VARIANT_MAP = {
    "outline": "secondary",
    "solid":   "primary",
    "default": "primary",
}

_BADGE_VARIANT_MAP = {
    "info": "primary",
    "error": "danger",
    "secondary": "neutral",
    "pending": "warning",
    "draft": "neutral",
}

_BADGE_ALLOWED = {"neutral", "primary", "success", "danger", "warning"}
_HERO_LAYOUTS = {"centered", "split", "stacked"}
_METRIC_FORMATS = {"number", "currency", "percent", "duration"}
_VALID_TABLE_COL_KEYS = {"key", "label", "width"}

# Cta accepts only these top-level keys.
_VALID_CTA_KEYS = {"label", "variant", "action"}


def _normalize_cta(cta: dict) -> dict:
    """Drop non-conformant CTA keys and normalise the action shape."""
    out = {k: v for k, v in cta.items() if k in _VALID_CTA_KEYS}
    action = out.get("action")
    if isinstance(action, dict):
        a_type = action.get("type")
        if a_type == "navigate" and isinstance(action.get("to"), str):
            out["action"] = {"type": "navigate", "to": action["to"]}
        elif a_type == "workflow" and isinstance(action.get("name"), str):
            out["action"] = {"type": "workflow", "name": action["name"]}
        else:
            # Unknown action shape — fold to a no-op navigate so the Cta still
            # validates. Hero renders the CTA but the click is harmless.
            out["action"] = {"type": "navigate", "to": "#"}
    elif isinstance(action, str):
        out["action"] = {"type": "navigate", "to": action}
    else:
        out["action"] = {"type": "navigate", "to": "#"}
    if not isinstance(out.get("label"), str) or len(out["label"]) == 0:
        out["label"] = "Action"
    return out


def _is_dict(x: Any) -> bool:
    return isinstance(x, dict)


def _normalize_label_navigate(props: dict) -> None:
    """Button / Link / IconButton / NavLink: content→label, href→navigate."""
    if not isinstance(props.get("label"), str):
        if isinstance(props.get("content"), str):
            props["label"] = props.pop("content")
        elif isinstance(props.get("children"), str):
            props["label"] = props.pop("children")
    props.pop("content", None)
    props.pop("children", None)
    if not isinstance(props.get("navigate"), str) and isinstance(props.get("href"), str):
        props["navigate"] = props.pop("href")
    props.pop("href", None)


def _normalize_validators(props: dict) -> None:
    v = props.get("validators")
    if not isinstance(v, dict):
        return
    if "min" not in v and isinstance(v.get("minLength"), (int, float)):
        v["min"] = v["minLength"]
    if "max" not in v and isinstance(v.get("maxLength"), (int, float)):
        v["max"] = v["maxLength"]
    v.pop("minLength", None)
    v.pop("maxLength", None)


def _normalize_columns(props: dict) -> None:
    cols = props.get("columns")
    if not isinstance(cols, list):
        return
    out: list[dict] = []
    for col in cols:
        if not _is_dict(col):
            continue
        c = dict(col)
        if not isinstance(c.get("label"), str) and isinstance(c.get("title"), str):
            c["label"] = c.pop("title")
        c.pop("title", None)
        if not isinstance(c.get("label"), str) or len(c["label"]) == 0:
            # Empty label fails ColumnDef.label.min(1); fall back to the key.
            c["label"] = c.get("key") if isinstance(c.get("key"), str) and c["key"] else "—"
        # Drop column-level extras the v2 ColumnDef rejects.
        for k in list(c.keys()):
            if k not in _VALID_TABLE_COL_KEYS:
                del c[k]
        out.append(c)
    props["columns"] = out


def _normalize_node(node: Any) -> None:
    if not _is_dict(node):
        return
    t = node.get("type")
    p = node.get("props")
    if isinstance(p, dict):
        if t in ("Button", "Link", "IconButton", "NavLink"):
            _normalize_label_navigate(p)
            if t == "Button" and isinstance(p.get("variant"), str):
                p["variant"] = _BUTTON_VARIANT_MAP.get(p["variant"], p["variant"])
            if t == "Link":
                p.pop("variant", None)  # Link has no variant in v2
        elif t in ("Input", "Textarea", "Select", "DatePicker", "Checkbox"):
            _normalize_validators(p)
            # Form-input nodes require `name` (baseField). LLM omits it for
            # filter-style selects/inputs — synthesise from `label` so the
            # schema parses.
            if not isinstance(p.get("name"), str) or len(p["name"]) == 0:
                lbl = p.get("label") if isinstance(p.get("label"), str) else None
                slug = (lbl or t.lower()).strip().lower().replace(" ", "_")
                p["name"] = "".join(ch for ch in slug if ch.isalnum() or ch == "_") or "field"
            if not isinstance(p.get("label"), str) or len(p["label"]) == 0:
                p["label"] = p["name"].replace("_", " ").title()
        elif t == "Badge":
            # text/label → content
            if not isinstance(p.get("content"), str):
                if isinstance(p.get("text"), str):
                    p["content"] = p.pop("text")
                elif isinstance(p.get("label"), str):
                    p["content"] = p.pop("label")
            p.pop("text", None); p.pop("label", None)
            if isinstance(p.get("content"), str) and len(p["content"]) == 0:
                p["content"] = " "
            # variant remap
            if isinstance(p.get("variant"), str) and p["variant"] not in _BADGE_ALLOWED:
                p["variant"] = _BADGE_VARIANT_MAP.get(p["variant"], "neutral")
        elif t == "Hero":
            if isinstance(p.get("layout"), str) and p["layout"] not in _HERO_LAYOUTS:
                p["layout"] = "centered"
            # CTAs: strip non-conformant keys (params, conditions, args, etc.)
            # and normalise the action shape. Cta union accepts only:
            #   {label, variant?, action: {type:"navigate", to:string}
            #                       | {type:"workflow", name:string}}
            ctas = p.get("ctas")
            if isinstance(ctas, list):
                p["ctas"] = [_normalize_cta(c) for c in ctas if isinstance(c, dict)]
        elif t == "Form":
            # Form's content is in `props.fields`, not children. The LLM sometimes
            # produces `defaultValues` as expressions like {{employee.id}}; the
            # schema accepts arbitrary records there so leave it alone. But
            # `submitWorkflow` / extra keys not in v2 should be stripped — but
            # `workflow` is the canonical name.
            if "submitWorkflow" in p and "workflow" not in p:
                p["workflow"] = p.pop("submitWorkflow")
        elif t == "MetricTile":
            if isinstance(p.get("format"), str) and p["format"] not in _METRIC_FORMATS:
                p["format"] = "number"
            p.pop("suffix", None)  # not in v2 MetricTileNode
        elif t in ("Table", "TableSortable"):
            _normalize_columns(p)
            # Drop top-level extras the v2 TableProps rejects (data, source,
            # emptyState, pagination, defaultSort, filter); render-time
            # binding is via dataSources + bind, not these props.
            for k in ["data", "source", "emptyState", "pagination", "defaultSort", "filter"]:
                p.pop(k, None)
        elif t == "Tabs":
            # If LLM produced {defaultValue, variant} instead of {tabs, value},
            # synthesise a single placeholder tab so the schema parses.
            if not isinstance(p.get("tabs"), list):
                v = p.get("defaultValue") if isinstance(p.get("defaultValue"), str) else "tab1"
                p["tabs"] = [{"id": v, "label": "Tab"}]
                p["value"] = v
                p.pop("defaultValue", None); p.pop("variant", None)
        elif t == "Accordion":
            if p.get("mode") == "multiple":
                p["mode"] = "multi"
            if p.get("mode") not in ("single", "multi"):
                p["mode"] = "single"
        elif t == "FeatureCard":
            # FeatureCardNode requires `title`, `description`, and `layout`
            # (an enum: "icon-top" | "icon-left"). LLM often emits layout-less
            # cards, swaps `description` for `body`/`text`, or `cta` for
            # `link`/`href`. Coerce all known variants to the strict v2 shape.
            if not isinstance(p.get("description"), str):
                for alt in ("body", "text", "subtitle", "summary"):
                    v = p.get(alt)
                    if isinstance(v, str):
                        p["description"] = v
                        p.pop(alt, None)
                        break
            if not isinstance(p.get("description"), str):
                p["description"] = ""  # required field — schema would reject undefined
            if not isinstance(p.get("title"), str):
                # Last-resort title fallback — use `heading` or "Feature"
                p["title"] = (
                    p.get("heading") if isinstance(p.get("heading"), str) else "Feature"
                )
                p.pop("heading", None)
            # layout default — icon-top is the more common library layout
            if p.get("layout") not in ("icon-top", "icon-left"):
                p["layout"] = "icon-top"
            # cta: strict Zod shape is {label, href} only. LLM frequently
            # emits {label, navigate} (route URL) or {label, workflow}
            # (trigger-by-workflow). For navigate/to/url/href — coerce to
            # href. For workflow — FeatureCard doesn't model workflow
            # triggers, so drop the cta (better to render the card without
            # a button than fail validation on the whole node).
            cta = p.get("cta")
            if isinstance(cta, dict):
                label = (
                    cta.get("label") if isinstance(cta.get("label"), str)
                    else cta.get("text") if isinstance(cta.get("text"), str)
                    else None
                )
                href = (
                    cta.get("href") if isinstance(cta.get("href"), str)
                    else cta.get("url") if isinstance(cta.get("url"), str)
                    else cta.get("to") if isinstance(cta.get("to"), str)
                    else cta.get("navigate") if isinstance(cta.get("navigate"), str)
                    else None
                )
                if label and href:
                    p["cta"] = {"label": label, "href": href}
                else:
                    p.pop("cta", None)
            elif cta is not None:
                p.pop("cta", None)
            # Strip extras not in v2 (image, link as bare string, actions, etc.)
            for k in ("image", "link", "actions", "href", "url"):
                p.pop(k, None)
        elif t == "EmptyStateRich":
            # EmptyStateRichNode requires primaryCta.action as a strict
            # discriminated union {type:"navigate"|"workflow"} when set,
            # and sampleDataLink as {label?, action?} (NOT a boolean).
            # LLM commonly emits:
            #   primaryCta: {label, workflow:"X"}                 → flatten to action
            #   primaryCta: {label, navigate:"/x" | href:"/x"}    → flatten to action
            #   primaryCta: {label, action:{type:"workflow", name:"X"}}  → name→workflow
            #   primaryCta: {label, action:{type:"workflow", workflow:"X"}}  → OK as-is
            #   sampleDataLink: true                              → drop (bool invalid)
            #   sampleDataLink: {label, workflow:"X"}             → flatten to action
            def _normalise_cta_obj(cta):
                if not isinstance(cta, dict):
                    return None
                label = cta.get("label") if isinstance(cta.get("label"), str) else None
                action = cta.get("action")
                # Already-nested action — fix up name→workflow if needed.
                if isinstance(action, dict):
                    a_type = action.get("type")
                    if a_type == "workflow":
                        wf = (action.get("workflow") if isinstance(action.get("workflow"), str)
                              else action.get("name") if isinstance(action.get("name"), str)
                              else None)
                        if wf:
                            action = {"type": "workflow", "workflow": wf}
                        else:
                            action = None
                    elif a_type == "navigate":
                        to = (action.get("to") if isinstance(action.get("to"), str)
                              else action.get("href") if isinstance(action.get("href"), str)
                              else action.get("url") if isinstance(action.get("url"), str)
                              else None)
                        action = {"type": "navigate", "to": to} if to else {"type": "navigate"}
                    else:
                        action = None
                else:
                    # Flat shape — synthesise action from sibling keys.
                    wf = cta.get("workflow") if isinstance(cta.get("workflow"), str) else None
                    nav = (cta.get("navigate") if isinstance(cta.get("navigate"), str)
                           else cta.get("href") if isinstance(cta.get("href"), str)
                           else cta.get("to") if isinstance(cta.get("to"), str)
                           else cta.get("url") if isinstance(cta.get("url"), str)
                           else None)
                    if wf:
                        action = {"type": "workflow", "workflow": wf}
                    elif nav:
                        action = {"type": "navigate", "to": nav}
                    else:
                        action = None
                out: dict = {}
                if label:
                    out["label"] = label
                if action:
                    out["action"] = action
                return out or None

            if "primaryCta" in p:
                fixed = _normalise_cta_obj(p["primaryCta"])
                if fixed:
                    p["primaryCta"] = fixed
                else:
                    p.pop("primaryCta", None)

            # sampleDataLink: schema allows only {label?, action?} object
            # with action restricted to workflow type. Coerce or drop.
            sdl = p.get("sampleDataLink")
            if sdl is True or sdl is False:
                # Bool can't carry label/action — drop entirely. The
                # generated UI loses the "Load sample data" link but
                # nothing else fails.
                p.pop("sampleDataLink", None)
            elif isinstance(sdl, dict):
                fixed = _normalise_cta_obj(sdl)
                if fixed:
                    # sampleDataLink's action enum is workflow-only.
                    if fixed.get("action", {}).get("type") != "workflow":
                        fixed.pop("action", None)
                    p["sampleDataLink"] = fixed
                else:
                    p.pop("sampleDataLink", None)
        elif t == "DataGrid":
            # DataGridNode props key the strict shape:
            #   columns: array, rows: array, rowKey: string,
            #   rowActions: [{label, action: {type:"workflow", workflow:str}}]
            # Common LLM mistakes: `data`→rows, `idKey`→rowKey,
            # `actions`→rowActions (with onClick/handler shapes).
            if "data" in p and "rows" not in p:
                p["rows"] = p.pop("data")
            if "idKey" in p and "rowKey" not in p:
                p["rowKey"] = p.pop("idKey")
            if not isinstance(p.get("rowKey"), str) or not p["rowKey"]:
                p["rowKey"] = "id"
            if not isinstance(p.get("rows"), list):
                p["rows"] = []
            if not isinstance(p.get("columns"), list):
                p["columns"] = []
            # Migrate `actions` to `rowActions` and normalise action shape.
            actions = p.pop("actions", None)
            if isinstance(actions, list) and "rowActions" not in p:
                p["rowActions"] = actions
            if isinstance(p.get("rowActions"), list):
                cleaned: list[dict] = []
                for a in p["rowActions"]:
                    if not isinstance(a, dict):
                        continue
                    label = a.get("label") if isinstance(a.get("label"), str) else None
                    if not label:
                        continue
                    act = a.get("action")
                    workflow_name = None
                    if isinstance(act, dict):
                        if isinstance(act.get("workflow"), str):
                            workflow_name = act["workflow"]
                        elif isinstance(act.get("name"), str):
                            workflow_name = act["name"]
                    if not workflow_name and isinstance(a.get("workflow"), str):
                        workflow_name = a["workflow"]
                    if not workflow_name:
                        # Can't synthesise a workflow target; drop this action
                        # rather than letting the whole DataGrid fail validation.
                        continue
                    cleaned.append({
                        "label": label,
                        "action": {"type": "workflow", "workflow": workflow_name},
                    })
                if cleaned:
                    p["rowActions"] = cleaned
                else:
                    p.pop("rowActions", None)
            # Strip extras the v2 DataGridProps rejects.
            for k in ("source", "pagination", "emptyState", "defaultSort",
                      "filter", "onRowClick", "onSelect"):
                p.pop(k, None)
    # Recurse into children
    children = node.get("children")
    if isinstance(children, list):
        for c in children:
            _normalize_node(c)


def normalize_v2_schema(schema: dict) -> dict:
    """Walk a Page schema dict and rewrite known v1-style prop shapes to v2.

    Mutates `schema` in place AND returns it for chaining. Safe to call on
    schemas that are already v2-conformant — known-good shapes pass through
    unchanged.
    """
    if not _is_dict(schema):
        return schema

    # Some LLM prompt iterations emit `layout` instead of `root` for the
    # render tree. The renderer only looks at `root`, so rename it here.
    # If both keys are present, `root` wins (the existing tree is kept intact
    # and the stale `layout` key is dropped).
    if "layout" in schema and "root" not in schema:
        schema["root"] = schema.pop("layout")
    elif "layout" in schema and "root" in schema:
        schema.pop("layout")

    # LLM also emits `content: {...}` (shadcn / Next.js convention) instead
    # of `root: {...}`. Same rewrite as `layout` above. Without this the
    # Engine's synthesiseRoot falls back to the "(empty page)" placeholder
    # because it only looks at `root` / `children` at the top level. That
    # was the cause of every `tasks.json` style empty-render bug in
    # description-generated apps.
    if "content" in schema and "root" not in schema and "children" not in schema:
        if _is_dict(schema.get("content")) and schema["content"].get("type"):
            schema["root"] = schema.pop("content")
    elif "content" in schema and ("root" in schema or "children" in schema):
        # If root/children are already present, content is stale — drop it.
        if _is_dict(schema.get("content")):
            schema.pop("content", None)

    root = schema.get("root")
    if _is_dict(root):
        _normalize_node(root)
    # Recurse for children-style schemas (shell.json uses this form).
    children = schema.get("children")
    if isinstance(children, list):
        for c in children:
            _normalize_node(c)
    return schema


def apply_page_shell_layout_to_schema(schema: dict) -> bool:
    """Apply the page-shell heuristic to a schema dict, whether it uses
    `root: {...}` or `children: [...]`. Returns True if any mutation
    occurred. Wraps the Figma pipeline's `_apply_page_shell_layout`
    so LLM-generated schemas (shell.json, pages with embedded sidebars)
    pick up the same viewport-fill layout as Figma-driven ones.
    """
    # Import lazily to avoid pulling figma deps when the normalizer is
    # used in unit tests that don't touch the Figma pipeline.
    from services.figma_to_schema import _apply_page_shell_layout

    if not _is_dict(schema):
        return False

    if _is_dict(schema.get("root")):
        before = _serialise(schema["root"])
        wrapper = [schema["root"]]
        _apply_page_shell_layout(wrapper)
        schema["root"] = wrapper[0]
        return _serialise(schema["root"]) != before
    if isinstance(schema.get("children"), list):
        before = [_serialise(c) for c in schema["children"]]
        _apply_page_shell_layout(schema["children"])
        return [_serialise(c) for c in schema["children"]] != before
    return False


def _serialise(node: object) -> str:
    """Stable string form for change detection."""
    import json as _json
    return _json.dumps(node, sort_keys=True)
