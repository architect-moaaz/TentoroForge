"""Smith tools — the model-facing palette.

Focused on the one new thing (list_components) + shape guarantees on the
tool catalog. The read-only inspectors are just re-exports of
fix_agent_tools (which has its own tests) so we don't re-test their guts.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services import smith_tools


# --------------------------------------------------------------------------- #
# TOOL_CATALOG shape
# --------------------------------------------------------------------------- #

def test_catalog_has_expected_slice1_tools():
    names = {t["name"] for t in smith_tools.TOOL_CATALOG}
    # Inspection surface (reused).
    for n in ("recall", "list_workflows", "read_workflow", "read_page",
              "read_column", "analyze_workflow_values", "parse_error",
              "probe_logs", "probe_endpoint"):
        assert n in names, f"missing inspection tool {n}"
    # New for Smith.
    assert "list_components" in names, "Smith needs to see the component library"
    assert "list_pages" in names, "Smith needs to enumerate pages, not guess paths"
    # Terminals.
    for n in ("propose_fix", "answer", "ask_user"):
        assert n in names, f"missing terminal {n}"


# --------------------------------------------------------------------------- #
# list_pages — the page enumerator (slice 2)
# --------------------------------------------------------------------------- #

def test_list_pages_returns_route_and_workflow_refs(tmp_path):
    """Walk src/schemas/ and return route + workflow refs + field count."""
    import json as _json
    schemas = tmp_path / "src" / "schemas"
    schemas.mkdir(parents=True)
    (schemas / "home.json").write_text(_json.dumps({
        "route": "/",
        "content": [{"type": "Text", "props": {"content": "hi"}}],
    }))
    (schemas / "assessments.json").write_text(_json.dumps({
        "route": "/assessments",
        # Real page schemas carry the workflow-ref on props.action.workflow
        # (or props.workflowId) — that's what _walk_workflow_refs looks for.
        "content": [{
            "type": "Button", "props": {"label": "Schedule",
                                        "action": {"workflow": "assessmentschedulingworkflow"}},
        }],
    }))
    result = smith_tools.list_pages_tool(str(tmp_path))
    assert result["available"] is True
    routes = {p["route"]: p for p in result["pages"]}
    assert set(routes) == {"/", "/assessments"}
    assert "assessmentschedulingworkflow" in routes["/assessments"]["workflowRefs"]
    assert result["totalCount"] == 2


def test_list_pages_returns_none_when_dir_missing(tmp_path):
    result = smith_tools.list_pages_tool(str(tmp_path))
    assert result["available"] is False
    assert "schemas/" in (result.get("reason") or "")


def test_list_pages_skips_unreadable_files_gracefully(tmp_path):
    schemas = tmp_path / "src" / "schemas"
    schemas.mkdir(parents=True)
    (schemas / "ok.json").write_text('{"route": "/ok"}')
    (schemas / "broken.json").write_text("this is not json")
    result = smith_tools.list_pages_tool(str(tmp_path))
    assert result["available"] is True
    assert [p["route"] for p in result["pages"]] == ["/ok"]


def test_catalog_entries_all_have_signature_and_desc():
    """The system prompt renders '{name}({sig}) : {desc}' — every entry
    needs both fields present."""
    for t in smith_tools.TOOL_CATALOG:
        assert isinstance(t.get("name"), str) and t["name"], f"bad name: {t}"
        assert isinstance(t.get("signature"), str) and t["signature"], f"bad sig: {t}"
        assert isinstance(t.get("desc"), str) and t["desc"], f"bad desc: {t}"


def test_readonly_handlers_cover_every_inspection_tool_in_catalog():
    """If a tool appears in the catalog but not in READONLY_HANDLERS the agent
    can't dispatch it. Terminals are handled separately by the agent loop."""
    catalog_names = {t["name"] for t in smith_tools.TOOL_CATALOG}
    handler_names = set(smith_tools.READONLY_HANDLERS)
    terminals = {"propose_fix", "answer", "ask_user", "handoff_to_pipeline"}
    missing = (catalog_names - terminals) - handler_names
    assert not missing, f"catalog tools with no handler: {missing}"


def test_direct_specialists_all_registered_no_phantom_tools_in_prompt():
    """Every tool the routing prompt tells Smith to reach for MUST be
    dispatchable. Previously the prompt named add_page/edit_page/etc. but
    they weren't in READONLY_HANDLERS — Smith would call them, the loop
    would 'unknown tool', and he'd fall back to propose_fix (→ coherence
    gate → rejection loop). This test locks the direct-specialist set."""
    handlers = set(smith_tools.READONLY_HANDLERS)
    for name in ("edit_page", "add_page", "add_workflow", "add_entity",
                 "edit_workflow", "impact_analysis", "run_guards"):
        assert name in handlers, (
            f"routing prompt references {name!r} but it's not registered "
            f"— Smith will call it, get 'unknown tool', and give up."
        )


def test_think_records_the_thought_and_no_op_on_empty():
    ok = smith_tools.READONLY_HANDLERS["think"](".", {"thought": "let me plan"})
    assert ok["recorded"] is True
    assert ok["chars"] == len("let me plan")
    bad = smith_tools.READONLY_HANDLERS["think"](".", {"thought": ""})
    assert bad["recorded"] is False


def test_understand_ask_requires_the_five_fields():
    ok = smith_tools.READONLY_HANDLERS["understand_ask"](".", {
        "screen": "Add Candidate",
        "element_label": "Upload CV",
        "current_behavior": "Select dropdown",
        "desired_behavior": "FileUpload",
        "target_file": "src/schemas/candidates/new.json",
    })
    assert ok["recorded"] is True
    u = ok["understanding"]
    assert u["target_file"] == "src/schemas/candidates/new.json"
    assert 0.0 <= u["confidence"] <= 1.0

    missing = smith_tools.READONLY_HANDLERS["understand_ask"](".", {
        "screen": "Add Candidate", "element_label": "Upload CV",
    })
    assert missing["recorded"] is False
    assert "missing required fields" in missing["error"]

    # Escape hatch — low-confidence ask with clarification_needed bypasses.
    clarified = smith_tools.READONLY_HANDLERS["understand_ask"](".", {
        "screen": "Add Candidate",
        "clarification_needed": "Which CV field — the upload or the list picker?",
    })
    assert clarified["recorded"] is True
    assert clarified["understanding"]["clarification_needed"]


def test_new_add_wrappers_pass_shape_through_to_fix_applier(monkeypatch):
    """The add_* wrappers must forward args to fix_applier without
    inventing structure. Uses monkeypatch to trap the outbound
    diagnosis and asserts the seam name + patch fields survived."""
    captured = {}

    def _fake_add_page(output_dir, diagnosis, *, git):
        captured["add_page"] = diagnosis
        return {"applied": True, "changes": [{"path": "p.json"}]}

    def _fake_add_workflow(output_dir, diagnosis, *, git):
        captured["add_workflow"] = diagnosis
        return {"applied": True, "changes": [{"path": "w.json"}]}

    def _fake_add_entity(output_dir, diagnosis, *, git):
        captured["add_entity"] = diagnosis
        return {"applied": True, "changes": [{"path": "e.ts"}]}

    from services import fix_applier
    monkeypatch.setattr(fix_applier, "_apply_add_page", _fake_add_page)
    monkeypatch.setattr(fix_applier, "_apply_add_workflow", _fake_add_workflow)
    monkeypatch.setattr(fix_applier, "_apply_add_entity", _fake_add_entity)

    r1 = smith_tools.READONLY_HANDLERS["add_page"](".", {
        "archetype": "kanban", "entity": "Candidate", "route": "/pipe",
    })
    assert r1["applied"] and r1["edited_paths"] == ["p.json"]
    assert captured["add_page"]["proposedFix"]["seam"] == "add_page"
    assert captured["add_page"]["proposedFix"]["patch"]["archetype"] == "kanban"
    # Empty explanation ⇒ coherence gate never fires.
    assert captured["add_page"]["explanation"] == ""

    r2 = smith_tools.READONLY_HANDLERS["add_workflow"](".", {
        "op": "create", "entity": "Candidate", "name": "CreateCandidate",
    })
    assert r2["applied"] and r2["edited_paths"] == ["w.json"]
    assert captured["add_workflow"]["proposedFix"]["patch"]["op"] == "create"
    assert captured["add_workflow"]["explanation"] == ""

    r3 = smith_tools.READONLY_HANDLERS["add_entity"](".", {
        "name": "Assessor",
        "fields": [{"name": "email", "type": "varchar"}],
    })
    assert r3["applied"] and r3["edited_paths"] == ["e.ts"]
    assert captured["add_entity"]["proposedFix"]["patch"]["name"] == "Assessor"
    assert captured["add_entity"]["explanation"] == ""


# --------------------------------------------------------------------------- #
# list_components — the library catalog reader
# --------------------------------------------------------------------------- #

def test_list_components_finds_repo_catalog_by_default():
    """The real component-contracts.json lives at
    ``packages/registry/dist/component-contracts.json`` (a sibling of
    backend/). No env var needed."""
    result = smith_tools.list_components_tool()
    assert result["available"] is True, result
    assert result["source"].endswith("component-contracts.json")
    # There should be lots of components (Button, Card, Table, Input, …).
    names = {c["name"] for c in result["components"]}
    for expected in ("Button", "Card", "Table", "Input"):
        assert expected in names, f"expected {expected} in catalog, got {sorted(names)[:20]}…"


def test_list_components_respects_env_override(monkeypatch, tmp_path):
    """FORGE_LIBRARY_CATALOG lets tests/deploys point at a specific catalog."""
    fake = tmp_path / "fake.json"
    fake.write_text(json.dumps({
        "MyWidget": {
            "label":  {"type": "string", "optional": False},
            "count":  {"type": "number", "optional": True},
            "variant": {"type": "enum", "enum": ["a", "b"], "optional": True},
        },
    }))
    monkeypatch.setenv("FORGE_LIBRARY_CATALOG", str(fake))
    result = smith_tools.list_components_tool()
    assert result["available"] is True
    assert result["source"] == str(fake)
    assert [c["name"] for c in result["components"]] == ["MyWidget"]
    w = result["components"][0]
    # Required props come first.
    assert w["props"][0]["name"] == "label"
    assert w["props"][0].get("required") is True
    # Enum values surface.
    variant = next(p for p in w["props"] if p["name"] == "variant")
    assert variant["type"] == "enum"
    assert variant["enum"] == ["a", "b"]


def test_list_components_drops_internal_and_layout_props(monkeypatch, tmp_path):
    """className/style/children are noise for Smith — the agent shouldn't
    reason about them."""
    fake = tmp_path / "fake.json"
    fake.write_text(json.dumps({
        "Panel": {
            "title":     {"type": "string", "optional": True},
            "className": {"type": "string", "optional": True},
            "style":     {"type": "object", "optional": True},
            "children":  {"type": "node",   "optional": True},
        },
    }))
    monkeypatch.setenv("FORGE_LIBRARY_CATALOG", str(fake))
    result = smith_tools.list_components_tool()
    panel = result["components"][0]
    prop_names = {p["name"] for p in panel["props"]}
    assert prop_names == {"title"}


def test_list_components_degrades_when_catalog_missing(monkeypatch):
    monkeypatch.setenv("FORGE_LIBRARY_CATALOG", "/nowhere/absent.json")
    # And also block the file-walk fallback by clearing the search path.
    # (In practice the env override wins even when the file is missing —
    # we should see available:False with a reason.)
    result = smith_tools.list_components_tool()
    assert result["available"] is False
    assert isinstance(result.get("reason"), str)


def test_list_components_caps_component_and_prop_counts(monkeypatch, tmp_path):
    """A giant catalog should not blow out the prompt — the tool caps both
    the number of components AND the number of props per component."""
    fake_catalog = {
        f"Comp{i}": {
            f"prop{j}": {"type": "string", "optional": True}
            for j in range(50)  # over the per-component cap
        }
        for i in range(300)  # over the component cap
    }
    fake = tmp_path / "big.json"
    fake.write_text(json.dumps(fake_catalog))
    monkeypatch.setenv("FORGE_LIBRARY_CATALOG", str(fake))
    result = smith_tools.list_components_tool()
    assert result["available"] is True
    assert len(result["components"]) <= smith_tools._MAX_COMPONENT_LIST
    for comp in result["components"]:
        assert len(comp["props"]) <= smith_tools._MAX_PROPS_PER_COMPONENT
    # totalCount reports the RAW size so the model knows how much was elided.
    assert result["totalCount"] == 300


# --------------------------------------------------------------------------- #
# Re-exports  (sanity — Smith should not have to reach into fix_agent_tools)
# --------------------------------------------------------------------------- #

def test_reexports_bind_to_fix_agent_tools():
    """The inspection surface Smith reuses from fix_agent_tools — read_page
    is intentionally NOT in this list because Smith overrides it to add
    the `outline` field for page-schema editing (see the dedicated
    read_page test below)."""
    from services import fix_agent_tools as fixtools
    for name in ("recall", "list_workflows", "read_workflow",
                 "read_column", "analyze_workflow_values_tool",
                 "parse_error_tool", "probe_logs_tool", "probe_endpoint_tool"):
        assert getattr(smith_tools, name) is getattr(fixtools, name), (
            f"{name} not re-exported as-is"
        )


# --------------------------------------------------------------------------- #
# read_page — Smith's version, with outline
# --------------------------------------------------------------------------- #

def test_read_page_augments_with_outline_for_root_key(tmp_path):
    """Real generated pages use `root` as the tree key; Smith's read_page
    adds an `outline` field with jsonPointer paths + component types so
    RFC-6902 ops can be authored without guessing indices."""
    import json as _json
    schemas = tmp_path / "src" / "schemas"
    schemas.mkdir(parents=True)
    (schemas / "app.json").write_text(_json.dumps({
        "route": "/app",
        "root": {
            "type": "Stack",
            "children": [
                {"type": "Card", "props": {"title": "Hello"},
                 "children": [{"type": "Button", "props": {"label": "OK"}}]},
                {"type": "Table", "props": {"dataSource": "widgets"}},
            ],
        },
    }))
    result = smith_tools.read_page(str(tmp_path), "src/schemas/app.json")
    assert result["route"] == "/app"
    outline = result["outline"]
    types = [o["type"] for o in outline]
    assert types == ["Stack", "Card", "Button", "Table"]
    # jsonPointer paths must be usable directly in RFC-6902.
    paths = [o["path"] for o in outline]
    assert paths[0] == "/root"
    assert "/root/children/0" in paths
    assert "/root/children/1" in paths
    # Prop snapshots surface the actionable props (dataSource, label).
    table = next(o for o in outline if o["type"] == "Table")
    assert table["props"]["dataSource"] == "widgets"
    button = next(o for o in outline if o["type"] == "Button")
    assert button["props"]["label"] == "OK"


def test_read_page_falls_back_to_content_key_for_older_schemas(tmp_path):
    import json as _json
    schemas = tmp_path / "src" / "schemas"
    schemas.mkdir(parents=True)
    (schemas / "old.json").write_text(_json.dumps({
        "route": "/old",
        "content": [{"type": "Text", "props": {"content": "hi"}}],
    }))
    result = smith_tools.read_page(str(tmp_path), "src/schemas/old.json")
    outline = result["outline"]
    assert outline and outline[0]["path"].startswith("/content")
    assert outline[0]["type"] == "Text"


def test_read_page_bubbles_up_fix_agent_errors(tmp_path):
    """When the base read_page returns {"error": "..."}, Smith's wrapper
    should pass it through without touching."""
    result = smith_tools.read_page(str(tmp_path), "nonexistent/page.json")
    assert "error" in result
    assert "outline" not in result


def test_a_request_smith_has_no_move_for_is_not_reported_as_no_change():
    """"I don't have that move" and "the state already matches" are different
    facts and had one sentence between them.

    A user asked four times for a dashboard at `/` with five named widgets and
    was told four times that nothing needed changing — once directly after
    Smith had offered to build it and been told "yes please".

    The distinction is the VERB now: a request that is not a rename dispatches
    on its own verb instead of falling through the rename path to a no-op.
    """
    from pathlib import Path as _P

    from services import smith_session
    from services.smith.verbs import REQUIRED_BY_VERB

    # A composition is expressible, and needs a route rather than a label.
    assert "compose_route" in REQUIRED_BY_VERB
    assert REQUIRED_BY_VERB["compose_route"] == {"route"}
    assert "element_label" not in REQUIRED_BY_VERB["compose_route"]

    src = _P(smith_session.__file__).read_text(encoding="utf-8")
    # The turn dispatches on the verb before it reaches the rename path.
    assert 'if verb in ("compose_route", "add_widgets")' in src
    # And a dispatcher that ran and found nothing names what it searched for,
    # so it cannot be mistaken for "I had no move".
    assert "could not find it" in src


def test_the_no_match_message_names_what_was_searched():
    from pathlib import Path as _P

    from services import smith_session

    src = _P(smith_session.__file__).read_text(encoding="utf-8")
    assert "editing the nearest thing" in src
