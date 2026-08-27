"""SV-STRICT-1 — ComponentContract module + 5W extractor.

Pure function tests. Every test builds its contract-file tree on the
fly in tmp_path so we don't couple to a snapshot of today's generator.

Slots vocabulary (fixed, closed set):
  what  — the promise the component makes
  who   — actor / role that can use it (auth + RBAC)
  where — route + placement (nav location)
  when  — the trigger (click, submit, navigate, timer)
  how   — the mechanism (workflow name, dataSource, action shape)
  why   — the user job it fulfills (Slice 4 fills; empty here)

Every ComponentContract has EXACTLY these six slots. `why` is emitted
as an empty-string WSlot with verifiable=False in this slice — Slice 4
wires BLUEPRINT.md ingestion.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.component_contract import (
    ComponentContract,
    WSlot,
    extract_component_contracts,
    to_dict,
)


# ── Fixture builders (mirrors test_interaction_extractor style) ───────────


def _write(root: Path, rel: str, data: dict | list) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _mk_nav_flow(pages: list[dict], **extra) -> dict:
    return {
        "version": "1.0",
        "initialPage": pages[0]["id"] if pages else None,
        "pages": pages,
        "transitions": [],
        "guards": {},
        "auth_routes": extra.get("auth_routes", []),
        "authGated": extra.get("authGated", False),
    }


def _mk_page(pid: str, route: str, *, shell: bool = True) -> dict:
    return {
        "id": pid, "route": route, "title": pid,
        "schemaFile": f"src/schemas/{pid}.json",
        "layout": None, "params": [], "shell": shell,
    }


def _mk_registry(entities: dict, relations: list | None = None) -> dict:
    return {
        "entities": entities, "relations": relations or [],
        "api_routes": {}, "components": {}, "pages": {},
        "workflow_bindings": {}, "rules": {},
    }


def _mk_plan(workflows: list[dict] | None = None,
             actors: list[dict] | None = None) -> dict:
    return {
        "workflows": workflows or [],
        "actors": actors or [],
    }


@pytest.fixture
def basic_app(tmp_path: Path) -> Path:
    """One authGated page + one public page + a button + a form + a table."""
    _write(tmp_path, "src/contracts/nav-flow.json", _mk_nav_flow([
        _mk_page("login", "/login", shell=False),
        _mk_page("candidates", "/candidates"),
        _mk_page("candidates-new", "/candidates/new"),
    ], authGated=True))
    _write(tmp_path, "src/contracts/plan.json", _mk_plan(
        workflows=[{
            "name": "CreateCandidate",
            "inputs": [{"name": "fullName", "type": "varchar", "required": True}],
            "trigger": {"kind": "form"},
        }],
        actors=[{"role": "recruiter", "self_signup": True}],
    ))
    _write(tmp_path, "registry.json", _mk_registry({
        "Candidate": {
            "fields": {
                "id": {"type": "uuid", "nullable": False, "primaryKey": True},
                "fullName": {"type": "varchar", "nullable": True},
            },
        },
    }))
    _write(tmp_path, "src/schemas/candidates.json", {
        "id": "candidates", "route": "/candidates",
        "dataSources": [{"name": "candidates", "entity": "Candidate", "op": "list"}],
        "root": {"type": "Section", "props": {}, "children": [
            {"type": "Button", "props": {"label": "New Candidate", "navigate": "/candidates/new"}},
            {"type": "Table", "props": {
                "columns": [{"key": "fullName", "label": "Full Name"}],
                "rows": "{{candidates}}",
            }},
        ]},
    })
    _write(tmp_path, "src/schemas/candidates-new.json", {
        "id": "candidates-new", "route": "/candidates/new",
        "dataSources": [],
        "root": {
            "type": "Form",
            "props": {"workflow": "CreateCandidate", "submitLabel": "Create"},
            "children": [
                {"type": "Input", "props": {"name": "fullName", "label": "Full Name",
                                             "validators": {"required": True}}},
                {"type": "Button", "props": {"label": "Create", "submit": True}},
            ],
        },
    })
    return tmp_path


# ── Shape invariants ─────────────────────────────────────────────────────


class TestShapeInvariants:
    def test_empty_dir_returns_empty(self, tmp_path: Path):
        assert extract_component_contracts(tmp_path) == []

    def test_every_contract_has_six_slots(self, basic_app: Path):
        contracts = extract_component_contracts(basic_app)
        assert contracts, "fixture should have produced contracts"
        for c in contracts:
            assert set(c.slots.keys()) == {"what", "who", "where", "when", "how", "why"}, \
                f"{c.id}: slot set mismatch: {sorted(c.slots.keys())}"

    def test_slot_types_are_wslot(self, basic_app: Path):
        for c in extract_component_contracts(basic_app):
            for name, slot in c.slots.items():
                assert isinstance(slot, WSlot), f"{c.id}.{name} is not a WSlot"
                assert slot.slot == name, \
                    f"{c.id}.{name}.slot={slot.slot} should match key"

    def test_slot_source_is_allowed(self, basic_app: Path):
        allowed = {"schema", "plan", "nav-flow", "registry", "blueprint", ""}
        for c in extract_component_contracts(basic_app):
            for name, slot in c.slots.items():
                assert slot.source in allowed, \
                    f"{c.id}.{name}.source={slot.source!r} not in allowed"

    def test_why_slot_is_always_present(self, basic_app: Path):
        # Slice 4 wired BLUEPRINT ingestion — ``why`` may or may not be
        # filled depending on what promises exist in the fixture. What
        # every contract still guarantees: the slot key is present, and
        # (when unfilled) its source is the empty string.
        for c in extract_component_contracts(basic_app):
            why = c.slots["why"]
            assert why.slot == "why"
            if not why.value:
                assert why.verifiable is False
                assert why.source == ""

    def test_component_types_are_closed_set(self, basic_app: Path):
        allowed = {"page", "button", "form", "table", "workflow", "entity", "detail"}
        for c in extract_component_contracts(basic_app):
            assert c.component_type in allowed, f"{c.id}: {c.component_type}"

    def test_sorted_deterministically(self, basic_app: Path):
        a = extract_component_contracts(basic_app)
        b = extract_component_contracts(basic_app)
        assert [c.id for c in a] == [c.id for c in b]

    def test_to_dict_round_trips_slots(self, basic_app: Path):
        contracts = extract_component_contracts(basic_app)
        d = to_dict(contracts[0])
        assert "slots" in d
        assert set(d["slots"].keys()) == {"what", "who", "where", "when", "how", "why"}


# ── Page contracts ───────────────────────────────────────────────────────


class TestPageContracts:
    def test_one_page_contract_per_nav_page(self, basic_app: Path):
        contracts = extract_component_contracts(basic_app)
        pages = [c for c in contracts if c.component_type == "page"]
        routes = {p.route for p in pages}
        assert routes == {"/login", "/candidates", "/candidates/new"}

    def test_page_where_names_route(self, basic_app: Path):
        pages = [c for c in extract_component_contracts(basic_app)
                 if c.component_type == "page"]
        for p in pages:
            assert p.route in p.slots["where"].value

    def test_page_who_reflects_auth(self, basic_app: Path):
        pages = {c.route: c for c in extract_component_contracts(basic_app)
                 if c.component_type == "page"}
        # /login is public (shell=False), /candidates is authGated
        assert "public" in pages["/login"].slots["who"].value.lower()
        assert ("auth" in pages["/candidates"].slots["who"].value.lower()
                or "sign" in pages["/candidates"].slots["who"].value.lower())

    def test_page_who_source_is_nav_flow(self, basic_app: Path):
        pages = [c for c in extract_component_contracts(basic_app)
                 if c.component_type == "page"]
        for p in pages:
            assert p.slots["who"].source == "nav-flow"


# ── Button contracts ─────────────────────────────────────────────────────


class TestButtonContracts:
    def test_button_contract_emitted(self, basic_app: Path):
        buttons = [c for c in extract_component_contracts(basic_app)
                   if c.component_type == "button"]
        # Two buttons in the fixture: "New Candidate" on /candidates,
        # and "Create" (submit) inside the Form on /candidates/new.
        assert len(buttons) >= 1
        labels = {b.label for b in buttons}
        assert "New Candidate" in labels

    def test_button_when_is_on_click(self, basic_app: Path):
        buttons = [c for c in extract_component_contracts(basic_app)
                   if c.component_type == "button"]
        for b in buttons:
            assert "click" in b.slots["when"].value.lower()

    def test_navigate_button_how_names_target(self, basic_app: Path):
        buttons = {b.label: b for b in extract_component_contracts(basic_app)
                   if b.component_type == "button"}
        nb = buttons["New Candidate"]
        assert "/candidates/new" in nb.slots["how"].value
        assert nb.slots["how"].source == "schema"

    def test_button_where_inherits_page_route(self, basic_app: Path):
        buttons = {b.label: b for b in extract_component_contracts(basic_app)
                   if b.component_type == "button"}
        nb = buttons["New Candidate"]
        assert "/candidates" in nb.slots["where"].value

    def test_button_who_inherits_page_auth(self, basic_app: Path):
        # /candidates is authGated, so its buttons are only usable by
        # signed-in users — the contract should say so.
        buttons = {b.label: b for b in extract_component_contracts(basic_app)
                   if b.component_type == "button"}
        nb = buttons["New Candidate"]
        assert ("auth" in nb.slots["who"].value.lower()
                or "sign" in nb.slots["who"].value.lower())


# ── Form contracts ───────────────────────────────────────────────────────


class TestFormContracts:
    def test_form_contract_emitted(self, basic_app: Path):
        forms = [c for c in extract_component_contracts(basic_app)
                 if c.component_type == "form"]
        assert len(forms) == 1

    def test_form_when_is_on_submit(self, basic_app: Path):
        form = [c for c in extract_component_contracts(basic_app)
                if c.component_type == "form"][0]
        assert "submit" in form.slots["when"].value.lower()

    def test_form_how_names_workflow(self, basic_app: Path):
        form = [c for c in extract_component_contracts(basic_app)
                if c.component_type == "form"][0]
        assert "CreateCandidate" in form.slots["how"].value

    def test_form_how_source_is_schema(self, basic_app: Path):
        form = [c for c in extract_component_contracts(basic_app)
                if c.component_type == "form"][0]
        assert form.slots["how"].source == "schema"


# ── Table contracts ──────────────────────────────────────────────────────


class TestTableContracts:
    def test_table_contract_emitted(self, basic_app: Path):
        tables = [c for c in extract_component_contracts(basic_app)
                  if c.component_type == "table"]
        assert len(tables) == 1

    def test_table_when_is_on_render(self, basic_app: Path):
        t = [c for c in extract_component_contracts(basic_app)
             if c.component_type == "table"][0]
        assert "render" in t.slots["when"].value.lower()

    def test_table_how_names_datasource_and_entity(self, basic_app: Path):
        t = [c for c in extract_component_contracts(basic_app)
             if c.component_type == "table"][0]
        assert "candidates" in t.slots["how"].value
        assert "Candidate" in t.slots["how"].value


# ── Workflow contracts ───────────────────────────────────────────────────


class TestWorkflowContracts:
    def test_workflow_contract_per_plan_workflow(self, basic_app: Path):
        wfs = [c for c in extract_component_contracts(basic_app)
               if c.component_type == "workflow"]
        assert len(wfs) == 1
        assert wfs[0].label == "CreateCandidate"

    def test_workflow_when_reflects_trigger(self, basic_app: Path):
        wf = [c for c in extract_component_contracts(basic_app)
              if c.component_type == "workflow"][0]
        assert "form" in wf.slots["when"].value.lower()

    def test_workflow_route_is_none(self, basic_app: Path):
        # Non-visual — workflows don't live at a route.
        wf = [c for c in extract_component_contracts(basic_app)
              if c.component_type == "workflow"][0]
        assert wf.route is None

    def test_workflow_source_is_plan(self, basic_app: Path):
        wf = [c for c in extract_component_contracts(basic_app)
              if c.component_type == "workflow"][0]
        assert wf.slots["how"].source == "plan"


# ── Entity contracts ─────────────────────────────────────────────────────


class TestEntityContracts:
    def test_entity_contract_per_registry_entity(self, basic_app: Path):
        ents = [c for c in extract_component_contracts(basic_app)
                if c.component_type == "entity"]
        assert len(ents) == 1
        assert ents[0].label == "Candidate"

    def test_entity_how_reports_field_count(self, basic_app: Path):
        ent = [c for c in extract_component_contracts(basic_app)
               if c.component_type == "entity"][0]
        # 2 fields declared in the fixture
        assert "2" in ent.slots["how"].value

    def test_entity_source_is_registry(self, basic_app: Path):
        ent = [c for c in extract_component_contracts(basic_app)
               if c.component_type == "entity"][0]
        assert ent.slots["how"].source == "registry"


# ── Detail-route contracts ───────────────────────────────────────────────


class TestDetailContracts:
    def test_detail_route_emits_detail_contract(self, tmp_path: Path):
        _write(tmp_path, "src/contracts/nav-flow.json", _mk_nav_flow([
            _mk_page("candidate-detail", "/candidates/[id]"),
        ], authGated=True))
        _write(tmp_path, "src/contracts/plan.json", _mk_plan())
        _write(tmp_path, "registry.json", _mk_registry({
            "Candidate": {"fields": {"id": {"type": "uuid"}}},
        }))
        _write(tmp_path, "src/schemas/candidate-detail.json", {
            "id": "candidate-detail", "route": "/candidates/[id]",
            "root": {"type": "Section", "props": {}, "children": []},
        })
        contracts = extract_component_contracts(tmp_path)
        details = [c for c in contracts if c.component_type == "detail"]
        assert len(details) == 1
        assert details[0].route == "/candidates/[id]"


# ── Robustness ───────────────────────────────────────────────────────────


class TestRobustness:
    def test_missing_plan_still_emits_pages(self, tmp_path: Path):
        _write(tmp_path, "src/contracts/nav-flow.json", _mk_nav_flow([
            _mk_page("home", "/"),
        ]))
        _write(tmp_path, "registry.json", _mk_registry({}))
        _write(tmp_path, "src/schemas/home.json", {
            "id": "home", "route": "/",
            "root": {"type": "Section", "props": {}, "children": []},
        })
        # No plan.json — should not raise; workflow contracts just absent.
        contracts = extract_component_contracts(tmp_path)
        pages = [c for c in contracts if c.component_type == "page"]
        assert len(pages) == 1

    def test_missing_registry_still_emits_pages(self, tmp_path: Path):
        _write(tmp_path, "src/contracts/nav-flow.json", _mk_nav_flow([
            _mk_page("home", "/"),
        ]))
        _write(tmp_path, "src/schemas/home.json", {
            "id": "home", "route": "/",
            "root": {"type": "Section", "props": {}, "children": []},
        })
        contracts = extract_component_contracts(tmp_path)
        pages = [c for c in contracts if c.component_type == "page"]
        assert len(pages) == 1
        entities = [c for c in contracts if c.component_type == "entity"]
        assert entities == []

    def test_malformed_json_does_not_raise(self, tmp_path: Path):
        p = tmp_path / "src" / "contracts" / "nav-flow.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not valid json", encoding="utf-8")
        # Best-effort: bad JSON → empty result, not a crash.
        assert extract_component_contracts(tmp_path) == []
