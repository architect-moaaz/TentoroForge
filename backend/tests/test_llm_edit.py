"""NT-1 — smart_edit_page: LLM-driven page-schema editor.

The tool replaces the JSON-Patch-based edit_page. It gets:
  * the current page schema on disk
  * the app-map skeleton (so it knows what the app is)
  * the component-contracts registry (so it knows what components exist)
  * the user's intent, verbatim

…and emits a NEW page schema. No deterministic 'authority' guard runs
after, so the LLM's choice sticks.

Tests inject a canned ``query_fn`` so they don't hit the real model.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from services.llm_edit import smart_edit_page


_FIXTURE = Path("/Users/m/Work/code/poc/design2ui-forge-v3/output/bpxr6hsv")
_REGISTRY = Path("/Users/m/Work/code/poc/design2ui-forge-v3/packages/registry/dist/component-contracts.json")


@pytest.fixture
def app_root(tmp_path: Path) -> Path:
    if not _FIXTURE.exists():
        pytest.skip("bpxr6hsv fixture app not present")
    (tmp_path / "contracts").mkdir()
    for name in ("resource-registry.json", "action-contract.json",
                 "generation-dossier.json"):
        shutil.copy(_FIXTURE / "contracts" / name, tmp_path / "contracts" / name)
    shutil.copy(_FIXTURE / "registry.json", tmp_path / "registry.json")
    shutil.copytree(_FIXTURE / "src" / "schemas", tmp_path / "src" / "schemas")
    return tmp_path


def _stub(response: dict):
    """Return a query_fn that ignores the prompt and always returns
    ``response`` as JSON in the model's assistant text."""
    def _fn(system_prompt: str, user_prompt: str) -> str:
        return json.dumps(response)
    return _fn


# --------------------------------------------------------------------------- #
# Happy path: LLM emits a new schema; the applier writes it verbatim.
# --------------------------------------------------------------------------- #

def test_llm_output_is_written_verbatim(app_root, monkeypatch):
    """The LLM says 'CV Upload is a FileUpload' — the file on disk must
    match what the LLM emitted, byte-for-byte after re-parse."""
    target = "src/schemas/candidates/new.json"
    intent = "Make the CV Upload field a FileUpload accepting PDF/DOC/DOCX"

    # A minimal but structurally valid new page — just a Stack with one
    # FileUpload child. The LLM's real output would be much richer;
    # what we're testing is that the applier writes it.
    new_schema = {
        "schemaVersion": "2",
        "id": "candidates-new",
        "route": "/candidates/new",
        "layout": "main",
        "root": {
            "type": "Stack",
            "props": {"gap": "tokens.spacing.6"},
            "children": [
                {"type": "Heading", "props": {"content": "Add Candidate", "level": 1}},
                {"type": "FileUpload", "props": {
                    "name": "cvUploadId",
                    "label": "CV Upload",
                    "accept": ".pdf,.doc,.docx",
                    "validators": {"required": True},
                }},
            ],
        },
    }

    result = smart_edit_page(
        output_dir=str(app_root),
        target_path=target,
        intent=intent,
        query_fn=_stub(new_schema),
    )

    assert result["applied"] is True
    assert target in result["edited_paths"]

    written = json.loads((app_root / target).read_text())
    assert written == new_schema


def test_fileupload_persists_no_authority_clobber(app_root):
    """The whole reason NT exists: on the FK-named cvUploadId column, the
    old deterministic ``apply_semantic_field_types`` guard would have
    forced Select. The new tool MUST leave FileUpload intact."""
    target = "src/schemas/candidates/new.json"
    intent = "Change CV Upload to a FileUpload"
    new_schema = {
        "schemaVersion": "2", "id": "candidates-new",
        "route": "/candidates/new", "layout": "main",
        "root": {"type": "Stack", "props": {}, "children": [
            {"type": "FileUpload", "props": {
                "name": "cvUploadId", "label": "CV Upload", "accept": ".pdf",
            }},
        ]},
    }
    result = smart_edit_page(
        output_dir=str(app_root),
        target_path=target,
        intent=intent,
        query_fn=_stub(new_schema),
    )
    assert result["applied"] is True

    # The FK-named column IS still a FileUpload on disk — no downgrade.
    disk = json.loads((app_root / target).read_text())
    def _walk(node, hits):
        if isinstance(node, dict):
            if node.get("props", {}).get("name") == "cvUploadId":
                hits.append(node.get("type"))
            for v in node.values(): _walk(v, hits)
        elif isinstance(node, list):
            for v in node: _walk(v, hits)
    hits: list = []
    _walk(disk, hits)
    assert hits == ["FileUpload"]


# --------------------------------------------------------------------------- #
# Prompt construction — the LLM must see intent, current schema, app-map,
# and component-contracts.
# --------------------------------------------------------------------------- #

def test_prompt_carries_current_schema_and_intent(app_root):
    """The LLM's user message must include the intent verbatim and the
    current on-disk schema (so it can produce a coherent DIFF, not
    something from scratch)."""
    seen: dict = {}
    def _spy(system_prompt: str, user_prompt: str) -> str:
        seen["system"] = system_prompt
        seen["user"]   = user_prompt
        return json.dumps({
            "schemaVersion": "2", "id": "candidates-new",
            "route": "/candidates/new", "layout": "main",
            "root": {"type": "Stack", "children": []},
        })

    smart_edit_page(
        output_dir=str(app_root),
        target_path="src/schemas/candidates/new.json",
        intent="Add a passport field",
        query_fn=_spy,
    )

    assert "Add a passport field" in seen["user"]
    assert '"cvUploadId"' in seen["user"]  # current schema is in the prompt


def test_prompt_carries_component_registry_index(app_root):
    """The LLM has to know what components exist. Whether we inject the
    full contracts or a compact index is a policy choice — this test
    only asserts that the FileUpload component's NAME appears in the
    prompt, so the LLM can pick it."""
    seen: dict = {}
    def _spy(system_prompt: str, user_prompt: str) -> str:
        seen["user"] = user_prompt
        return json.dumps({
            "schemaVersion": "2", "id": "candidates-new",
            "route": "/candidates/new", "layout": "main",
            "root": {"type": "Stack", "children": []},
        })

    smart_edit_page(
        output_dir=str(app_root),
        target_path="src/schemas/candidates/new.json",
        intent="anything",
        query_fn=_spy,
    )
    assert "FileUpload" in seen["user"]
    assert "Select" in seen["user"]


def test_prompt_carries_app_map(app_root):
    """The LLM sees the app-map so it knows entities/pages/workflows —
    lets it reason about impact + name things correctly."""
    seen: dict = {}
    def _spy(system_prompt: str, user_prompt: str) -> str:
        seen["user"] = user_prompt
        return json.dumps({
            "schemaVersion": "2", "id": "candidates-new",
            "route": "/candidates/new", "layout": "main",
            "root": {"type": "Stack", "children": []},
        })

    smart_edit_page(
        output_dir=str(app_root),
        target_path="src/schemas/candidates/new.json",
        intent="doesn't matter",
        query_fn=_spy,
    )
    assert "# APP MAP" in seen["user"]
    assert "Candidate" in seen["user"]


# --------------------------------------------------------------------------- #
# Validation — bad LLM output must be REJECTED, not written.
# --------------------------------------------------------------------------- #

def test_non_json_response_rejected(app_root):
    def _fn(system_prompt, user_prompt): return "sorry i couldn't do that"
    result = smart_edit_page(
        output_dir=str(app_root),
        target_path="src/schemas/candidates/new.json",
        intent="anything",
        query_fn=_fn,
    )
    assert result["applied"] is False
    assert "json" in result["reason"].lower()


def test_missing_root_rejected(app_root):
    """A response that's valid JSON but doesn't have a 'root' key isn't
    a valid page schema and must be refused before writing."""
    result = smart_edit_page(
        output_dir=str(app_root),
        target_path="src/schemas/candidates/new.json",
        intent="anything",
        query_fn=_stub({"schemaVersion": "2", "id": "x", "route": "/x"}),
    )
    assert result["applied"] is False
    assert "root" in result["reason"].lower()


def test_unknown_component_type_rejected(app_root):
    """The LLM tries to use a component that isn't in the registry —
    the applier must refuse. Otherwise the app renders errors."""
    bogus = {
        "schemaVersion": "2", "id": "candidates-new",
        "route": "/candidates/new", "layout": "main",
        "root": {"type": "Stack", "children": [
            {"type": "TotallyMadeUpComponent", "props": {"foo": "bar"}},
        ]},
    }
    result = smart_edit_page(
        output_dir=str(app_root),
        target_path="src/schemas/candidates/new.json",
        intent="anything",
        query_fn=_stub(bogus),
    )
    assert result["applied"] is False
    assert "TotallyMadeUpComponent" in result["reason"]


# --------------------------------------------------------------------------- #
# Guard behavior — the whole point is 'no clobber'.
# --------------------------------------------------------------------------- #

def test_apply_post_generate_fixes_is_not_called(app_root, monkeypatch):
    """The old ``_apply_page_schema_patch`` called
    ``apply_post_generate_fixes`` after every write, and that's what
    clobbered the FileUpload back to Select. The new tool must NOT call
    it — the LLM's choice is the authority."""
    called: list = []
    def _boom(*args, **kwargs):
        called.append(True)
        return None
    monkeypatch.setattr(
        "services.post_generate_fixes.apply_post_generate_fixes",
        _boom,
    )
    smart_edit_page(
        output_dir=str(app_root),
        target_path="src/schemas/candidates/new.json",
        intent="anything",
        query_fn=_stub({
            "schemaVersion": "2", "id": "candidates-new",
            "route": "/candidates/new", "layout": "main",
            "root": {"type": "Stack", "children": []},
        }),
    )
    assert called == [], "guard suite must NOT run — that was the bug"


# --------------------------------------------------------------------------- #
# Missing files / graceful failure
# --------------------------------------------------------------------------- #

def test_missing_target_returns_not_applied(app_root):
    result = smart_edit_page(
        output_dir=str(app_root),
        target_path="src/schemas/does_not_exist.json",
        intent="anything",
        query_fn=_stub({}),
    )
    assert result["applied"] is False
    assert "not found" in result["reason"].lower()


def test_no_query_fn_returns_not_applied(app_root):
    """No LLM boundary wired — must degrade gracefully, not crash."""
    result = smart_edit_page(
        output_dir=str(app_root),
        target_path="src/schemas/candidates/new.json",
        intent="anything",
        query_fn=None,
    )
    assert result["applied"] is False
