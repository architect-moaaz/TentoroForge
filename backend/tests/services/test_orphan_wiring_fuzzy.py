"""Fuzzy field-name matching in orphan_wiring_pass.

Pre-change: a form with fields ``[first_name, last_name]`` and a
workflow with inputs ``[firstName, lastName]`` scores 0/2 and stays
orphaned — pure-identity name comparison. Case-inconsistent naming
between the LLM's Form emitter and its Workflow emitter is a common
cause of orphan workflows.

Post-change: names are canonicalized (lowercased, punctuation
stripped) before comparison, and the pipeline builds an explicit
``field_map`` for wire_form_to_workflow so the mirror + guards see
the actual pairing.
"""
from __future__ import annotations

import json
from pathlib import Path


# ─────────────────────────────────────────────────────────────────────
# Normalizer
# ─────────────────────────────────────────────────────────────────────

def test_canonicalize_name_folds_case_and_separators():
    from services.orphan_wiring_pass import _canonicalize_field_name

    # snake ↔ camel
    assert _canonicalize_field_name("firstName") == _canonicalize_field_name("first_name")
    assert _canonicalize_field_name("createdAt") == _canonicalize_field_name("created_at")
    # kebab folds too (some emitters use it)
    assert _canonicalize_field_name("date-of-birth") == _canonicalize_field_name("dateOfBirth")
    # UPPER / mixed
    assert _canonicalize_field_name("CV_URL") == _canonicalize_field_name("cvUrl")
    # Whitespace / punctuation stripped
    assert _canonicalize_field_name("email address") == _canonicalize_field_name("emailAddress")
    # Identity check for exact match still works
    assert _canonicalize_field_name("id") == _canonicalize_field_name("id")


def test_canonicalize_non_string_returns_empty():
    from services.orphan_wiring_pass import _canonicalize_field_name

    assert _canonicalize_field_name(None) == ""
    assert _canonicalize_field_name(42) == ""
    assert _canonicalize_field_name("") == ""


# ─────────────────────────────────────────────────────────────────────
# Scoring — mixed-case names now count
# ─────────────────────────────────────────────────────────────────────

def test_score_credits_fuzzy_matches():
    from services.orphan_wiring_pass import _score_form_for_workflow

    form = {
        "route": "/candidates/new",
        "fields": {"first_name", "last_name", "email"},
    }
    workflow = {
        "processVariables": [
            {"name": "firstName", "required": True},
            {"name": "lastName", "required": True},
            {"name": "email", "required": True},
        ],
    }
    # All 3 required inputs covered — 2 by fuzzy match, 1 by identity.
    assert _score_form_for_workflow(form, workflow) == 1.0


def test_score_still_rejects_completely_unrelated_names():
    from services.orphan_wiring_pass import _score_form_for_workflow

    form = {"route": "/foo", "fields": {"bar", "baz"}}
    workflow = {
        "processVariables": [
            {"name": "somethingElse", "required": True},
        ],
    }
    assert _score_form_for_workflow(form, workflow) == 0.0


# ─────────────────────────────────────────────────────────────────────
# Pairing helper — builds the explicit field_map
# ─────────────────────────────────────────────────────────────────────

def test_build_field_map_pairs_by_canonical_name():
    from services.orphan_wiring_pass import _build_fuzzy_field_map

    form_fields = {"first_name", "last_name", "email_address"}
    workflow_inputs = [
        {"name": "firstName", "required": True},
        {"name": "lastName", "required": True},
        {"name": "emailAddress", "required": True},
    ]
    fm = _build_fuzzy_field_map(form_fields, workflow_inputs)
    assert fm == {
        "first_name": "firstName",
        "last_name": "lastName",
        "email_address": "emailAddress",
    }


def test_build_field_map_identity_pairs_unchanged():
    from services.orphan_wiring_pass import _build_fuzzy_field_map

    form_fields = {"email", "phone"}
    workflow_inputs = [
        {"name": "email"},
        {"name": "phone"},
    ]
    fm = _build_fuzzy_field_map(form_fields, workflow_inputs)
    # Identity pairs are still returned so callers can pass one field_map
    # covering both fuzzy AND identity mappings.
    assert fm == {"email": "email", "phone": "phone"}


def test_build_field_map_omits_unmatched():
    from services.orphan_wiring_pass import _build_fuzzy_field_map

    form_fields = {"first_name", "unrelated_field"}
    workflow_inputs = [
        {"name": "firstName"},
        {"name": "someOtherInput"},
    ]
    fm = _build_fuzzy_field_map(form_fields, workflow_inputs)
    assert fm == {"first_name": "firstName"}


def test_build_field_map_one_form_field_wins_first_canonical_match():
    """If two workflow inputs canonicalize the same way (a data-model
    bug), the first one wins — deterministic; downstream sees the same
    result on every run."""
    from services.orphan_wiring_pass import _build_fuzzy_field_map

    form_fields = {"user_id"}
    workflow_inputs = [
        {"name": "userId"},
        {"name": "user_id"},   # duplicate canonical; first wins
    ]
    fm = _build_fuzzy_field_map(form_fields, workflow_inputs)
    assert fm == {"user_id": "userId"}


# ─────────────────────────────────────────────────────────────────────
# End-to-end wiring on a tmp fake project — the pipeline uses the
# fuzzy map when it dispatches wire_form_to_workflow.
# ─────────────────────────────────────────────────────────────────────

def _write_page(out: Path, route: str, form_field_names: list[str]) -> None:
    """Emit a minimal page schema with one Form + fields under
    src/schemas/ in the nested layout the resolver expects
    (``/candidates/new`` → ``src/schemas/candidates/new.json``)."""
    parts = [p for p in route.strip("/").split("/") if p] or ["index"]
    fields_children = [
        {"component": "Input", "props": {"name": n}, "children": []}
        for n in form_field_names
    ]
    doc = {
        "route": route,
        "root": {
            "component": "Page",
            "props": {},
            "children": [
                {
                    "component": "Form",
                    "props": {},
                    "children": fields_children,
                }
            ],
        },
    }
    p = out / "src" / "schemas"
    for seg in parts[:-1]:
        p = p / seg
    p.mkdir(parents=True, exist_ok=True)
    (p / f"{parts[-1]}.json").write_text(json.dumps(doc), encoding="utf-8")


def _write_workflow(out: Path, name: str, inputs: list[dict]) -> None:
    """Emit a minimal workflow file under workflows/."""
    doc = {
        "name": name,
        "processVariables": inputs,
        "nodes": [],
        "edges": [],
    }
    p = out / "workflows" / f"{name}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")


def test_pipeline_wires_form_when_only_fuzzy_names_match(tmp_path):
    """A form with `first_name` / `last_name` / `email` was previously
    orphaned by a workflow that declared `firstName` / `lastName` /
    `email`. With fuzzy matching enabled the pipeline wires it up and
    emits an explicit field_map so the mirror captures the pairing."""
    from services.orphan_wiring_pass import wire_orphan_workflows

    _write_page(
        tmp_path,
        "/candidates/new",
        ["first_name", "last_name", "email"],
    )
    _write_workflow(
        tmp_path,
        "CreateCandidate",
        [
            {"name": "firstName", "required": True},
            {"name": "lastName", "required": True},
            {"name": "email", "required": True},
        ],
    )
    # Minimal plan.json so the mirror in wire_form_to_workflow doesn't
    # bail with plan_mirror_warning (its own bail is soft, but the wire
    # itself must succeed).
    (tmp_path / "src" / "contracts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "contracts" / "plan.json").write_text(
        json.dumps({
            "pages": [{"name": "NewCandidate", "route": "/candidates/new"}],
            "workflows": [{"name": "CreateCandidate", "inputs": []}],
        }),
        encoding="utf-8",
    )

    out = wire_orphan_workflows(str(tmp_path))
    assert out["wired"], f"pipeline did not wire the form; unresolved={out['unresolved']}"
    assert out["wired"][0]["workflow"] == "CreateCandidate"
    assert out["wired"][0]["page_route"] == "/candidates/new"

    # Form.props.workflow got written.
    page_doc = json.loads(
        (tmp_path / "src" / "schemas" / "candidates" / "new.json").read_text(encoding="utf-8")
    )
    form_node = page_doc["root"]["children"][0]
    assert form_node["component"] == "Form"
    assert form_node["props"]["workflow"] == "CreateCandidate"

    # plan.json.pages[].submit.field_map records the fuzzy pairing.
    plan = json.loads(
        (tmp_path / "src" / "contracts" / "plan.json").read_text(encoding="utf-8")
    )
    submit = plan["pages"][0].get("submit")
    assert submit and submit.get("kind") == "workflow"
    assert submit.get("target") == "CreateCandidate"
    field_map = submit.get("field_map") or {}
    assert field_map.get("first_name") == "firstName"
    assert field_map.get("last_name") == "lastName"
    assert field_map.get("email") == "email"
