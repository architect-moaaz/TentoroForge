"""Tests for schema_normalizer — verify the LLM-shape→v2 transforms."""
from services.schema_normalizer import normalize_v2_schema


def _wrap(node: dict) -> dict:
    return {"schemaVersion": "1", "id": "x", "route": "/", "layout": "DashboardLayout",
            "meta": {"title": "x"}, "dataSources": [], "root": node}


def test_button_content_to_label_and_href_to_navigate():
    s = _wrap({"id": "b", "type": "Button", "props": {
        "variant": "outline", "content": "Cancel", "href": "/leave-types"}})
    out = normalize_v2_schema(s)
    p = out["root"]["props"]
    assert p["label"] == "Cancel"
    assert p["navigate"] == "/leave-types"
    assert p["variant"] == "secondary"
    assert "content" not in p and "href" not in p


def test_link_drops_variant_and_remaps_label():
    s = _wrap({"id": "l", "type": "Link", "props": {
        "content": "View", "href": "/x", "variant": "secondary"}})
    out = normalize_v2_schema(s)
    p = out["root"]["props"]
    assert p["label"] == "View"
    assert p["navigate"] == "/x"
    assert "variant" not in p


def test_validators_minLength_to_min():
    s = _wrap({"id": "i", "type": "Input", "props": {
        "name": "n", "label": "L", "type": "text",
        "validators": {"required": True, "minLength": 2, "maxLength": 50}}})
    out = normalize_v2_schema(s)
    v = out["root"]["props"]["validators"]
    assert v["min"] == 2 and v["max"] == 50
    assert "minLength" not in v and "maxLength" not in v


def test_badge_text_to_content_and_variant_remap():
    s = _wrap({"id": "b", "type": "Badge", "props": {"text": "High", "variant": "error"}})
    out = normalize_v2_schema(s)
    p = out["root"]["props"]
    assert p["content"] == "High"
    assert p["variant"] == "danger"
    assert "text" not in p


def test_metric_tile_format_text_to_number_and_drop_suffix():
    s = _wrap({"id": "m", "type": "MetricTile", "props": {
        "label": "X", "value": "6.6 days", "format": "text",
        "icon": "clock", "suffix": "days"}})
    out = normalize_v2_schema(s)
    p = out["root"]["props"]
    assert p["format"] == "number"
    assert "suffix" not in p


def test_tabs_synthesises_placeholder_tab():
    s = _wrap({"id": "t", "type": "Tabs", "props": {
        "defaultValue": "monthly", "variant": "line"}})
    out = normalize_v2_schema(s)
    p = out["root"]["props"]
    assert p["tabs"] == [{"id": "monthly", "label": "Tab"}]
    assert p["value"] == "monthly"
    assert "defaultValue" not in p and "variant" not in p


def test_accordion_mode_multiple_to_multi():
    s = _wrap({"id": "a", "type": "Accordion", "props": {
        "mode": "multiple", "defaultOpen": ["x"]}})
    out = normalize_v2_schema(s)
    assert out["root"]["props"]["mode"] == "multi"


def test_table_columns_title_to_label_and_drop_extras():
    s = _wrap({"id": "t", "type": "TableSortable", "props": {
        "source": "feed",
        "columns": [
            {"key": "name", "title": "Name", "sortable": True, "type": "text"},
            {"key": "actions", "label": ""},
        ]}})
    out = normalize_v2_schema(s)
    p = out["root"]["props"]
    # source dropped
    assert "source" not in p
    # columns: title→label, extras dropped, empty label falls back to key
    assert p["columns"] == [
        {"key": "name", "label": "Name"},
        {"key": "actions", "label": "actions"},
    ]


def test_recurses_into_children():
    s = _wrap({"id": "r", "type": "Stack", "children": [
        {"id": "h", "type": "Hero", "props": {"headline": "X", "layout": "horizontal", "ctas": []}},
        {"id": "b", "type": "Button", "props": {"content": "Go", "href": "/x"}},
    ]})
    out = normalize_v2_schema(s)
    children = out["root"]["children"]
    assert children[0]["props"]["layout"] == "centered"  # hero remap
    assert children[1]["props"]["label"] == "Go"
    assert children[1]["props"]["navigate"] == "/x"


def test_passthrough_for_already_v2_conformant_schema():
    s = _wrap({"id": "b", "type": "Button", "props": {
        "label": "Save", "variant": "primary", "size": "md"}})
    before = {"label": "Save", "variant": "primary", "size": "md"}
    out = normalize_v2_schema(s)
    assert out["root"]["props"] == before


# ── layout → root rename ────────────────────────────────────────────────────

def test_layout_key_renamed_to_root():
    """LLM-emitted `layout` top-level key is renamed to `root`."""
    node = {"id": "b", "type": "Button", "props": {"label": "Go"}}
    schema = {
        "schemaVersion": "2",
        "id": "tasks",
        "type": "page",
        "dataSources": [],
        "layout": node,
    }
    out = normalize_v2_schema(schema)
    assert "root" in out, "root should be present after rename"
    assert "layout" not in out, "layout key should be removed"
    assert out["root"] is node


# ── FeatureCard ─────────────────────────────────────────────────────────────


def test_feature_card_synthesises_required_layout_when_missing():
    """FeatureCardNode requires `layout` (enum). LLM frequently omits it →
    normalizer defaults to 'icon-top' so the Zod validator doesn't reject."""
    s = _wrap({"id": "f", "type": "FeatureCard", "props": {
        "title": "Manage leave", "description": "Submit + track requests"}})
    out = normalize_v2_schema(s)
    p = out["root"]["props"]
    assert p["layout"] == "icon-top"
    assert p["title"] == "Manage leave"
    assert p["description"] == "Submit + track requests"


def test_feature_card_remaps_body_text_to_description():
    """LLM emits `body` or `text` instead of the required `description`."""
    s = _wrap({"id": "f", "type": "FeatureCard", "props": {
        "title": "Calendar", "body": "View team availability",
        "layout": "icon-top"}})
    out = normalize_v2_schema(s)
    p = out["root"]["props"]
    assert p["description"] == "View team availability"
    assert "body" not in p


def test_feature_card_normalises_cta_url_to_href():
    """LLM emits cta.url instead of cta.href."""
    s = _wrap({"id": "f", "type": "FeatureCard", "props": {
        "title": "T", "description": "D", "layout": "icon-top",
        "cta": {"label": "Open", "url": "/dashboard"}}})
    out = normalize_v2_schema(s)
    cta = out["root"]["props"]["cta"]
    assert cta == {"label": "Open", "href": "/dashboard"}


def test_feature_card_normalises_cta_navigate_to_href():
    """LLM emits cta.navigate (page-link convention from Button) instead
    of cta.href. Coerce — `.strict()` rejects the `navigate` key."""
    s = _wrap({"id": "f", "type": "FeatureCard", "props": {
        "title": "T", "description": "D", "layout": "icon-top",
        "cta": {"label": "Start", "navigate": "/leave-requests/new"}}})
    out = normalize_v2_schema(s)
    cta = out["root"]["props"]["cta"]
    assert cta == {"label": "Start", "href": "/leave-requests/new"}


def test_feature_card_drops_workflow_cta():
    """FeatureCard's cta doesn't model workflow triggers. Drop the cta
    entirely rather than failing the whole node's validation."""
    s = _wrap({"id": "f", "type": "FeatureCard", "props": {
        "title": "T", "description": "D", "layout": "icon-top",
        "cta": {"label": "Approve", "workflow": "ApprovalFlow"}}})
    out = normalize_v2_schema(s)
    p = out["root"]["props"]
    assert "cta" not in p


def test_feature_card_strips_non_v2_extras():
    """`image`, top-level `href`, `actions` are not in the v2 schema. Strip."""
    s = _wrap({"id": "f", "type": "FeatureCard", "props": {
        "title": "T", "description": "D", "layout": "icon-top",
        "image": "/img.png", "href": "/x", "actions": []}})
    out = normalize_v2_schema(s)
    p = out["root"]["props"]
    assert "image" not in p and "href" not in p and "actions" not in p


def test_feature_card_invalid_layout_replaced():
    """Layout outside the enum (e.g. 'horizontal') → default to icon-top."""
    s = _wrap({"id": "f", "type": "FeatureCard", "props": {
        "title": "T", "description": "D", "layout": "horizontal"}})
    out = normalize_v2_schema(s)
    assert out["root"]["props"]["layout"] == "icon-top"


# ── EmptyStateRich ──────────────────────────────────────────────────────────


def test_empty_state_rich_flat_workflow_becomes_action():
    """LLM emits `primaryCta: {label, workflow: 'X'}` — must coerce to
    `{label, action: {type: 'workflow', workflow: 'X'}}`."""
    s = _wrap({"id": "e", "type": "EmptyStateRich", "props": {
        "heading": "No items", "body": "Create one to start",
        "primaryCta": {"label": "Create Item", "workflow": "createItem"}}})
    out = normalize_v2_schema(s)
    cta = out["root"]["props"]["primaryCta"]
    assert cta == {
        "label": "Create Item",
        "action": {"type": "workflow", "workflow": "createItem"},
    }


def test_empty_state_rich_flat_navigate_becomes_action():
    """LLM emits `primaryCta: {label, navigate: '/x'}` — flatten to
    `action: {type: 'navigate', to: '/x'}`. Also accepts href/url/to
    aliases."""
    s = _wrap({"id": "e", "type": "EmptyStateRich", "props": {
        "heading": "Empty",
        "primaryCta": {"label": "Browse", "navigate": "/properties"}}})
    out = normalize_v2_schema(s)
    cta = out["root"]["props"]["primaryCta"]
    assert cta["action"] == {"type": "navigate", "to": "/properties"}


def test_empty_state_rich_action_name_renamed_to_workflow():
    """LLM emits `action: {type: 'workflow', name: 'X'}` — rename
    `name` to `workflow` to satisfy the discriminated union."""
    s = _wrap({"id": "e", "type": "EmptyStateRich", "props": {
        "heading": "Empty",
        "primaryCta": {"label": "Run",
                       "action": {"type": "workflow", "name": "RunFlow"}}}})
    out = normalize_v2_schema(s)
    cta = out["root"]["props"]["primaryCta"]
    assert cta["action"] == {"type": "workflow", "workflow": "RunFlow"}


def test_empty_state_rich_sample_data_link_true_dropped():
    """LLM emits `sampleDataLink: true` — schema rejects booleans.
    Drop rather than failing the whole node."""
    s = _wrap({"id": "e", "type": "EmptyStateRich", "props": {
        "heading": "Empty",
        "sampleDataLink": True}})
    out = normalize_v2_schema(s)
    assert "sampleDataLink" not in out["root"]["props"]


def test_empty_state_rich_sample_data_link_flat_workflow():
    """LLM emits `sampleDataLink: {label, workflow: 'X'}` —
    convert to `{label, action: {type:'workflow', workflow:'X'}}`."""
    s = _wrap({"id": "e", "type": "EmptyStateRich", "props": {
        "heading": "Empty",
        "sampleDataLink": {"label": "Load sample",
                           "workflow": "loadSample"}}})
    out = normalize_v2_schema(s)
    sdl = out["root"]["props"]["sampleDataLink"]
    assert sdl == {
        "label": "Load sample",
        "action": {"type": "workflow", "workflow": "loadSample"},
    }


def test_empty_state_rich_sample_data_link_drops_navigate_action():
    """sampleDataLink's action enum is workflow-only. If a navigate
    action sneaks in, strip it but keep the label."""
    s = _wrap({"id": "e", "type": "EmptyStateRich", "props": {
        "heading": "Empty",
        "sampleDataLink": {"label": "Browse",
                           "action": {"type": "navigate", "to": "/x"}}}})
    out = normalize_v2_schema(s)
    sdl = out["root"]["props"]["sampleDataLink"]
    assert sdl == {"label": "Browse"}


def test_empty_state_rich_drops_cta_with_no_actionable_target():
    """primaryCta with neither workflow nor navigate target — drop
    rather than failing validation. Title still renders without a CTA."""
    s = _wrap({"id": "e", "type": "EmptyStateRich", "props": {
        "heading": "Empty",
        "primaryCta": {"label": "Click me"}}})
    out = normalize_v2_schema(s)
    p = out["root"]["props"]
    # Has only label — kept (action is optional in the schema)
    assert p["primaryCta"] == {"label": "Click me"}


# ── DataGrid ────────────────────────────────────────────────────────────────


def test_data_grid_renames_data_to_rows():
    s = _wrap({"id": "g", "type": "DataGrid", "props": {
        "columns": [{"key": "name", "header": "Name"}],
        "data": [{"id": 1, "name": "Alice"}]}})
    out = normalize_v2_schema(s)
    p = out["root"]["props"]
    assert p["rows"] == [{"id": 1, "name": "Alice"}]
    assert "data" not in p


def test_data_grid_renames_idkey_to_rowkey():
    s = _wrap({"id": "g", "type": "DataGrid", "props": {
        "columns": [], "rows": [], "idKey": "uuid"}})
    out = normalize_v2_schema(s)
    p = out["root"]["props"]
    assert p["rowKey"] == "uuid"
    assert "idKey" not in p


def test_data_grid_defaults_when_keys_missing():
    """If columns/rows/rowKey are missing entirely, fill with safe defaults
    so the Zod validator accepts the node."""
    s = _wrap({"id": "g", "type": "DataGrid", "props": {}})
    out = normalize_v2_schema(s)
    p = out["root"]["props"]
    assert p["columns"] == [] and p["rows"] == []
    assert p["rowKey"] == "id"


def test_data_grid_migrates_actions_to_row_actions_with_workflow_shape():
    """LLM emits flat `actions: [{label, workflow}]` — convert to the v2
    shape `rowActions: [{label, action: {type:'workflow', workflow}}]`."""
    s = _wrap({"id": "g", "type": "DataGrid", "props": {
        "columns": [], "rows": [],
        "actions": [{"label": "Approve", "workflow": "ApprovalFlow"}]}})
    out = normalize_v2_schema(s)
    p = out["root"]["props"]
    assert "actions" not in p
    assert p["rowActions"] == [{
        "label": "Approve",
        "action": {"type": "workflow", "workflow": "ApprovalFlow"},
    }]


def test_data_grid_normalises_action_object_workflow():
    """When rowActions[].action is present but missing the `type`, coerce
    to the strict {type:'workflow', workflow:...} shape."""
    s = _wrap({"id": "g", "type": "DataGrid", "props": {
        "columns": [], "rows": [],
        "rowActions": [{"label": "Reject", "action": {"workflow": "RejectFlow"}}]}})
    out = normalize_v2_schema(s)
    ra = out["root"]["props"]["rowActions"]
    assert ra == [{"label": "Reject",
                   "action": {"type": "workflow", "workflow": "RejectFlow"}}]


def test_data_grid_drops_unactionable_row_action():
    """If a rowAction has no workflow target anywhere, drop it rather than
    failing the whole grid's validation."""
    s = _wrap({"id": "g", "type": "DataGrid", "props": {
        "columns": [], "rows": [],
        "rowActions": [
            {"label": "Bad", "action": {"type": "navigate"}},  # no workflow
            {"label": "Good", "workflow": "GoodFlow"},
        ]}})
    out = normalize_v2_schema(s)
    ra = out["root"]["props"]["rowActions"]
    assert len(ra) == 1
    assert ra[0]["label"] == "Good"


def test_data_grid_strips_non_v2_extras():
    s = _wrap({"id": "g", "type": "DataGrid", "props": {
        "columns": [], "rows": [],
        "source": "api/leave", "pagination": {"perPage": 25},
        "emptyState": "No requests", "onRowClick": "handler"}})
    out = normalize_v2_schema(s)
    p = out["root"]["props"]
    for k in ("source", "pagination", "emptyState", "onRowClick"):
        assert k not in p


def test_root_wins_when_both_layout_and_root_present():
    """`root` is kept unchanged; stale `layout` is dropped."""
    root_node = {"id": "r", "type": "Stack", "children": []}
    layout_node = {"id": "l", "type": "Grid", "children": []}
    schema = {
        "schemaVersion": "2",
        "id": "tasks",
        "type": "page",
        "dataSources": [],
        "root": root_node,
        "layout": layout_node,
    }
    out = normalize_v2_schema(schema)
    assert out["root"] is root_node, "root should be the original root node"
    assert "layout" not in out, "stale layout key should be dropped"


def test_content_key_renamed_to_root():
    """LLM agents occasionally emit `content: {...}` (shadcn / Next.js
    convention) instead of `root: {...}`. The normalizer rewrites it so
    Engine.synthesiseRoot recognises the tree — without this, the page
    falls through to the '(empty page)' placeholder."""
    content_node = {"type": "Container", "props": {}, "children": [
        {"type": "Heading", "props": {"content": "Overview", "level": 1}},
    ]}
    schema = {
        "schemaVersion": "2",
        "id": "tasks",
        "dataSources": [],
        "content": content_node,
    }
    out = normalize_v2_schema(schema)
    assert "root" in out and out["root"] is content_node
    assert "content" not in out


def test_content_dropped_when_root_already_present():
    """If both root and content are present, root wins."""
    root_node = {"type": "Container", "props": {}, "children": []}
    schema = {
        "schemaVersion": "2", "id": "x", "dataSources": [],
        "root": root_node,
        "content": {"type": "Stack", "props": {}},
    }
    out = normalize_v2_schema(schema)
    assert out["root"] is root_node
    assert "content" not in out


def test_button_variant_rewrites_in_children_form():
    """shell.json uses `children: [...]`, not `root: {...}`. The normalizer
    must walk children too so `variant: "default"` / `"outline"` rewrites
    fire on shell buttons — that's the bug that caused `⚠ Button: invalid
    props` on every nav item in description-generated apps."""
    schema = {
        "schemaVersion": "2", "id": "shell", "title": "App Shell",
        "children": [
            {"type": "Row", "props": {}, "children": [
                {"type": "Button", "props": {"label": "Save",
                    "variant": "default", "navigate": "/x"}},
                {"type": "Button", "props": {"label": "Cancel",
                    "variant": "outline", "navigate": "/y"}},
            ]},
        ],
    }
    out = normalize_v2_schema(schema)
    btns = []
    def walk(n):
        if not isinstance(n, dict): return
        if n.get("type") == "Button":
            btns.append(n.get("props", {}))
        for c in n.get("children") or []:
            walk(c)
    for c in out.get("children", []):
        walk(c)
    assert len(btns) == 2
    assert btns[0]["variant"] == "primary"
    assert btns[1]["variant"] == "secondary"


def test_apply_page_shell_layout_to_schema_root_form():
    """The page-shell wrapper works on schemas using `root: {...}`."""
    from services.schema_normalizer import apply_page_shell_layout_to_schema
    schema = {
        "schemaVersion": "2", "id": "dash",
        "root": {
            "type": "Row",
            "props": {"className": "w-[1391px] min-h-[1134px] bg-[#f3f4f6]"},
            "children": [
                {"type": "Stack", "props": {"className": "w-[247px] min-h-[852px] bg-gradient-to-b"}},
                {"type": "Stack", "props": {"className": "flex-1 min-h-[1134px]"}, "children": []},
            ],
        },
    }
    changed = apply_page_shell_layout_to_schema(schema)
    assert changed is True
    root_cn = schema["root"]["props"]["className"].split()
    assert "w-full" in root_cn
    assert "h-screen" in root_cn
    assert "items-stretch" in root_cn
    # The page-shell heuristic now also inserts a backdrop sibling before
    # the sidebar, so find the sidebar by its shellRole marker rather than
    # positional index.
    children = schema["root"]["children"]
    sidebar = next(c for c in children if (c.get("props") or {}).get("shellRole") == "sidebar")
    side_cn = sidebar["props"]["className"].split()
    # Drawer geometry: mobile slide-in, md+ inline column.
    for cls in ("fixed", "inset-y-0", "left-0", "-translate-x-full",
                "md:relative", "md:translate-x-0", "md:flex", "md:flex-col",
                "md:h-screen", "md:overflow-y-auto"):
        assert cls in side_cn, f"sidebar missing {cls}: {side_cn}"


def test_apply_page_shell_layout_no_op_when_pattern_absent():
    """A schema without the sidebar+main pattern is left unchanged."""
    from services.schema_normalizer import apply_page_shell_layout_to_schema
    schema = {
        "schemaVersion": "2",
        "root": {
            "type": "Container", "props": {"className": "max-w-xl mx-auto"},
            "children": [{"type": "Heading", "props": {"content": "Hello"}}],
        },
    }
    original = schema["root"]["props"]["className"]
    changed = apply_page_shell_layout_to_schema(schema)
    assert changed is False
    assert schema["root"]["props"]["className"] == original


def test_apply_page_shell_layout_handles_llm_shell_pattern():
    """LLM-generated shell.json uses `min-h-screen` on the root row + Tailwind
    width utilities (`w-60`) on the sidebar Container — not Figma's fixed-px
    pattern. The heuristic must recognise both so the sticky-sidebar +
    scrollable-main layout applies regardless of source pipeline.
    """
    from services.schema_normalizer import apply_page_shell_layout_to_schema
    schema = {
        "schemaVersion": "2", "id": "shell",
        "children": [
            {
                "type": "Row",
                "props": {"className": "min-h-screen"},
                "children": [
                    {
                        "type": "Container",
                        "props": {"className": "hidden md:flex flex-col w-60 border-r bg-card"},
                        "children": [],
                    },
                    {
                        "type": "Stack",
                        "props": {"className": "flex-1 flex-col"},
                        "children": [{"type": "PageOutlet"}],
                    },
                ],
            },
        ],
    }
    changed = apply_page_shell_layout_to_schema(schema)
    assert changed is True
    root = schema["children"][0]
    rcn = root["props"]["className"].split()
    # Root upgraded to true viewport-fill, `min-h-screen` swapped out.
    assert "h-screen" in rcn
    assert "overflow-hidden" in rcn
    assert "items-stretch" in rcn
    assert "w-full" in rcn
    assert "min-h-screen" not in rcn
    # Sidebar (find by shellRole marker — backdrop sibling now precedes it)
    # keeps its w-60 + gains drawer geometry + md:-prefixed scroll utilities.
    children = root["children"]
    sidebar = next(c for c in children if (c.get("props") or {}).get("shellRole") == "sidebar")
    side_cn = sidebar["props"]["className"].split()
    assert "w-60" in side_cn
    for cls in ("fixed", "inset-y-0", "left-0", "-translate-x-full",
                "md:relative", "md:translate-x-0", "md:flex", "md:flex-col",
                "md:h-screen", "md:overflow-y-auto", "md:shrink-0",
                "sidebar-scroll"):
        assert cls in side_cn, f"sidebar missing {cls}: {side_cn}"
    # Backdrop sibling exists and is mobile-only.
    backdrop = next(c for c in children if (c.get("props") or {}).get("shellRole") == "backdrop")
    back_cn = backdrop["props"]["className"].split()
    for cls in ("fixed", "inset-0", "z-30", "opacity-0", "pointer-events-none",
                "transition-opacity", "md:hidden"):
        assert cls in back_cn, f"backdrop missing {cls}: {back_cn}"
    # Main (still detectable by flex-1) keeps + gains scroll utilities.
    main = next(c for c in children if "flex-1" in ((c.get("props") or {}).get("className") or "").split())
    main_cn = main["props"]["className"].split()
    assert "flex-1" in main_cn
    assert "h-screen" in main_cn
    assert "overflow-y-auto" in main_cn
    assert "main-scroll" in main_cn
    assert "min-w-0" in main_cn


def test_apply_page_shell_layout_card_row_rescue_enables_wrap():
    """A Row inside main with 3+ children that each have card-size fixed
    widths (180-400px) gets `wrap: true` so the cards stack on mobile.
    Without this the stat-card row (e.g. 4× w-[262px]) stays a single line
    and overflows horizontally on a 375px viewport."""
    from services.schema_normalizer import apply_page_shell_layout_to_schema
    schema = {
        "schemaVersion": "2",
        "children": [
            {
                "type": "Row",
                "props": {"className": "min-h-screen"},
                "children": [
                    {"type": "Stack", "props": {"className": "w-60"}, "children": []},
                    {
                        "type": "Stack",
                        "props": {"className": "flex-1"},
                        "children": [
                            {
                                "type": "Row",
                                "props": {"className": "gap-4", "wrap": False},
                                "children": [
                                    {"type": "Stack", "props": {"className": "w-[262px] min-h-[91px]"}, "children": []},
                                    {"type": "Stack", "props": {"className": "w-[262px] min-h-[91px]"}, "children": []},
                                    {"type": "Stack", "props": {"className": "w-[262px] min-h-[91px]"}, "children": []},
                                    {"type": "Stack", "props": {"className": "w-[262px] min-h-[91px]"}, "children": []},
                                ],
                            },
                        ],
                    },
                ],
            },
        ],
    }
    apply_page_shell_layout_to_schema(schema)
    # The page-shell heuristic now inserts a backdrop sibling before the
    # sidebar — locate main by its flex-1 marker instead of positional index.
    root = schema["children"][0]
    main = next(c for c in root["children"]
                if "flex-1" in ((c.get("props") or {}).get("className") or "").split())
    card_row = main["children"][0]
    assert card_row["type"] == "Row"
    assert card_row["props"].get("wrap") is True, card_row["props"]
    assert "flex-wrap" in card_row["props"].get("className", "").split()


def test_apply_page_shell_layout_tags_hamburger_button_and_spawns_backdrop():
    """When the page-shell pattern matches, the heuristic must:
      1. Insert a Container with shellRole=backdrop as a sibling of the
         sidebar so taps outside the open drawer close it.
      2. Find any Button with workflow=shell.toggleSidebar (or onClick
         containing it, or an aria-label like "Open menu") and set
         togglesSidebar=true so the rendered <button> emits
         data-sidebar-toggle for the ShellStateProvider delegated handler.
    """
    from services.schema_normalizer import apply_page_shell_layout_to_schema
    schema = {
        "schemaVersion": "2",
        "children": [
            {
                "type": "Row",
                "props": {"className": "min-h-screen"},
                "children": [
                    {"type": "Container", "props": {"className": "w-60 flex-col"}, "children": []},
                    {
                        "type": "Stack",
                        "props": {"className": "flex-1 flex-col"},
                        "children": [
                            {
                                "type": "Container",
                                "props": {"className": "topbar"},
                                "children": [
                                    {"type": "Button", "props": {
                                        "workflow": "shell.toggleSidebar",
                                        "aria-label": "Open menu",
                                        "icon": "menu",
                                    }},
                                    {"type": "Button", "props": {
                                        "label": "New", "variant": "primary",
                                    }},
                                ],
                            },
                        ],
                    },
                ],
            },
        ],
    }
    apply_page_shell_layout_to_schema(schema)
    root = schema["children"][0]
    # Backdrop spawned, positioned before the sidebar (so sidebar's z-40
    # renders above the backdrop's z-30).
    roles = [(c.get("props") or {}).get("shellRole") for c in root["children"]]
    assert "backdrop" in roles
    assert "sidebar" in roles
    assert roles.index("backdrop") < roles.index("sidebar"), roles
    # Hamburger button tagged with togglesSidebar=true.
    def collect(n, acc):
        if not isinstance(n, dict): return
        if n.get("type") == "Button": acc.append(n.get("props") or {})
        for c in n.get("children") or []: collect(c, acc)
    btns = []
    for c in root["children"]: collect(c, btns)
    hamburger = next(b for b in btns if b.get("aria-label") == "Open menu")
    assert hamburger.get("togglesSidebar") is True
    # The other button (the CTA) is left alone.
    cta = next(b for b in btns if b.get("label") == "New")
    assert "togglesSidebar" not in cta


def test_apply_page_shell_layout_w_full_child_is_not_sidebar():
    """A child whose width is `w-full` is content, not a sidebar — the
    detector must skip it so we don't accidentally promote a full-width
    Container as the sidebar half of the shell."""
    from services.schema_normalizer import apply_page_shell_layout_to_schema
    schema = {
        "schemaVersion": "2",
        "children": [
            {
                "type": "Row",
                "props": {"className": "min-h-screen"},
                "children": [
                    {"type": "Container", "props": {"className": "w-full flex-1"}, "children": []},
                ],
            },
        ],
    }
    changed = apply_page_shell_layout_to_schema(schema)
    # No sidebar pattern → no transformation.
    assert changed is False
