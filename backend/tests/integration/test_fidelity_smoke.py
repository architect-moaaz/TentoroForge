"""Integration smoke test — fidelity-mode schema pipeline (Task 37).

Exercises the fidelity pipeline's core path end-to-end with the LLM stubbed:
  1. design_compiler.compile_to_file  →  tokens.custom.json on disk
  2. feature_slice_schema_agent.run_feature_slice_schema_agent  →  3 JSON schemas

Asserts every spec §9 success criterion programmatically.

Run:
    cd backend && pytest tests/integration/test_fidelity_smoke.py -v
"""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import AsyncIterator

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent / "fixtures"

_DESIGN_SPEC_PATH   = _FIXTURES_DIR / "design_spec_fintech.json"
_FIXTURE_LIST       = _FIXTURES_DIR / "schema_response_list.json"
_FIXTURE_DETAIL     = _FIXTURES_DIR / "schema_response_detail.json"
_FIXTURE_FORM       = _FIXTURES_DIR / "schema_response_form.json"

_FIXTURE_BY_PAGE: dict[str, Path] = {
    "list":   _FIXTURE_LIST,
    "detail": _FIXTURE_DETAIL,
    "form":   _FIXTURE_FORM,
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_fixture(page_type: str) -> dict:
    return json.loads(_FIXTURE_BY_PAGE[page_type].read_text(encoding="utf-8"))


def _walk_nodes(node: dict):
    """Depth-first generator over every node dict in a schema root tree."""
    if not isinstance(node, dict):
        return
    yield node
    for child in node.get("children", []):
        yield from _walk_nodes(child)


def _all_string_values(obj) -> list[str]:
    """Recursively collect every string value in a nested structure."""
    out: list[str] = []
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            out.extend(_all_string_values(v))
    elif isinstance(obj, list):
        for item in obj:
            out.extend(_all_string_values(item))
    return out


# ---------------------------------------------------------------------------
# LLM stub factory
# ---------------------------------------------------------------------------

def _make_fake_query(captured_prompts: list[str]):
    """Return an async generator stub for claude_agent_sdk.query.

    Inspects the prompt to detect which page_type is being requested, then
    yields a single message whose content block carries the fixture JSON.

    ``captured_prompts`` is a list the caller can pass in to collect every
    prompt the stub receives (used by the fidelity-off test).
    """

    async def fake_query(prompt: str, options=None) -> AsyncIterator:  # type: ignore[return]
        captured_prompts.append(prompt)

        # Detect page_type from the prompt text.  The schema-prompt builder
        # always includes the literal phrase "This is a <page_type> page"
        # in the Page-archetype section — match that exact phrase so we
        # don't accidentally hit "form" inside "Tentoroforge" or "format".
        page_type = "list"  # default
        for pt in ("detail", "form", "list"):
            if f"This is a {pt} page" in prompt:
                page_type = pt
                break

        fixture = _load_fixture(page_type)
        text = json.dumps(fixture)

        class _Block:
            pass

        class _Msg:
            pass

        block = _Block()
        block.text = text  # type: ignore[attr-defined]

        msg = _Msg()
        msg.content = [block]  # type: ignore[attr-defined]

        # Yield a single message (mirrors claude_agent_sdk async generator shape)
        yield msg

    return fake_query


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def _run_pipeline(tmp_path: Path, *, monkeypatch, captured_prompts: list[str]) -> None:
    """Wire up stubs and run compile_to_file + schema agent for one entity."""
    import agents.feature_slice_schema_agent as _agent_mod
    import services.schema_prompt as _sp_mod

    # 1. Stub the LLM
    monkeypatch.setattr(_agent_mod, "query", _make_fake_query(captured_prompts))

    # 2. Stub load_default_tokens to return a small known set (avoids Node subprocess)
    _CANNED_TOKENS = {
        "color": {
            "primary":  {"50": "#eff6ff", "500": "#3b82f6", "600": "#2563eb"},
            "surface":  {"0": "#ffffff",  "1": "#fafafa"},
            "text":     {"primary": "#18181b"},
            "success":  {"500": "#22c55e"},
            "error":    {"500": "#ef4444"},
        },
        "spacing": {
            "4": "1rem",
            "6": "1.5rem",
            "8": "2rem",
            "semantic": {
                "page":    "2rem",
                "card":    "1.25rem",
                "section": "4rem",
                "element": "1rem",
            },
        },
        "radius": {"sm": "0.25rem", "md": "0.5rem", "lg": "0.75rem"},
        "shadow": {"sm": "0 1px 2px", "md": "0 4px 6px"},
        "typography": {
            "font":   {"body": "Inter", "heading": "Inter"},
            "weight": {"body": "400",   "heading": "600"},
            "scale":  {"h1": "2rem",    "body": "0.875rem"},
        },
    }
    # The agent imports load_default_tokens with `from services.schema_prompt
    # import load_default_tokens`, which binds the name into the agent module's
    # own namespace at import time. Patching _sp_mod.load_default_tokens does
    # NOT affect that bound reference — the agent will still call the original.
    # Patch on the agent module directly.
    monkeypatch.setattr(_agent_mod, "load_default_tokens", lambda: _CANNED_TOKENS)

    # 3. Stub _validate_schema_json to skip the Zod/pnpm subprocess entirely
    monkeypatch.setattr(_agent_mod, "_validate_schema_json", lambda schema_dict: None)

    # --- Step A: compile_to_file ---
    from services.design_compiler import compile_to_file

    design_spec = json.loads(_DESIGN_SPEC_PATH.read_text(encoding="utf-8"))
    tokens_out_path = tmp_path / "src" / "theme" / "tokens.custom.json"
    compile_to_file(design_spec, str(tokens_out_path))

    # --- Step B: write design-spec to expected location (schema_prompt reads it) ---
    design_spec_out = tmp_path / "src" / "contracts" / "design-spec.json"
    design_spec_out.parent.mkdir(parents=True, exist_ok=True)
    design_spec_out.write_text(json.dumps(design_spec), encoding="utf-8")

    # --- Step C: run schema agent ---
    plan = {
        "entity": {
            "name": "Account",
            "fields": [
                {"name": "id",      "type": "uuid"},
                {"name": "balance", "type": "currency"},
                {"name": "owner",   "type": "string"},
            ],
        },
        "feature_description": "Customer financial accounts",
        "_output_dir": str(tmp_path),
    }
    domain_context = {"domain": "Finance", "tone": "trustworthy, calm"}

    asyncio.run(
        _agent_mod.run_feature_slice_schema_agent(
            str(tmp_path), plan, domain_context
        )
    )


# ---------------------------------------------------------------------------
# Test 1: happy path — fidelity ON
# ---------------------------------------------------------------------------

class TestFidelitySmokeHappyPath:
    """End-to-end fidelity pipeline smoke test.  Spec §9 success criteria."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        """Run the pipeline once; store artefacts for assertions."""
        import services.schema_prompt as _sp_mod

        # Ensure fidelity is ON for this test
        monkeypatch.setattr(_sp_mod, "FIDELITY_MODE_ENABLED", True)

        self.captured_prompts: list[str] = []
        _run_pipeline(tmp_path, monkeypatch=monkeypatch, captured_prompts=self.captured_prompts)
        self.tmp_path = tmp_path

        # Load all three emitted schemas once
        schemas_dir = tmp_path / "src" / "schemas" / "accounts"
        self.schemas: dict[str, dict] = {
            pt: json.loads((schemas_dir / f"{pt}.json").read_text(encoding="utf-8"))
            for pt in ("list", "detail", "form")
        }

    # -----------------------------------------------------------------------
    # §9 criterion 1: tokens.custom.json exists with full token tree
    # -----------------------------------------------------------------------

    def test_tokens_custom_json_exists(self):
        tokens_path = self.tmp_path / "src" / "theme" / "tokens.custom.json"
        assert tokens_path.exists(), "tokens.custom.json must be written by compile_to_file"

    def test_tokens_custom_json_has_required_top_level_keys(self):
        tokens_path = self.tmp_path / "src" / "theme" / "tokens.custom.json"
        tokens = json.loads(tokens_path.read_text(encoding="utf-8"))
        for key in ("color", "spacing", "radius", "shadow"):
            assert key in tokens and tokens[key], (
                f"tokens.custom.json must have non-empty '{key}' key"
            )

    def test_tokens_color_has_ramp(self):
        tokens_path = self.tmp_path / "src" / "theme" / "tokens.custom.json"
        tokens = json.loads(tokens_path.read_text(encoding="utf-8"))
        primary = tokens["color"].get("primary", {})
        assert len(primary) >= 5, (
            "Primary color ramp must have at least 5 stops (design_compiler generates 11)"
        )

    # -----------------------------------------------------------------------
    # §9 criterion 2: schema files emitted
    # -----------------------------------------------------------------------

    def test_schema_files_exist(self):
        schemas_dir = self.tmp_path / "src" / "schemas" / "accounts"
        for pt in ("list", "detail", "form"):
            f = schemas_dir / f"{pt}.json"
            assert f.exists(), f"Schema file {pt}.json must exist at {f}"

    def test_schema_registry_ts_emitted(self):
        registry = self.tmp_path / "src" / "schemas" / "registry.ts"
        assert registry.exists(), "registry.ts must be regenerated after agent run"
        content = registry.read_text(encoding="utf-8")
        assert "accounts/list" in content
        assert "accounts/detail" in content
        assert "accounts/form" in content

    # -----------------------------------------------------------------------
    # §9 criterion 3: every page schema uses StyleSlot in at least one node
    # -----------------------------------------------------------------------

    def test_every_schema_has_styleslot_usage(self):
        for page_type, schema in self.schemas.items():
            root = schema.get("root", {})
            found = any(
                isinstance(node.get("style"), dict) and node["style"]
                for node in _walk_nodes(root)
            )
            assert found, (
                f"Schema '{page_type}' must have at least one node with a non-empty 'style' dict"
            )

    # -----------------------------------------------------------------------
    # §9 criterion 4: Hero or Section on at least 1 page
    # -----------------------------------------------------------------------

    def test_hero_or_section_appears_on_at_least_one_page(self):
        hero_section_types = {"Hero", "Section"}
        found = False
        for schema in self.schemas.values():
            root = schema.get("root", {})
            if any(node.get("type") in hero_section_types for node in _walk_nodes(root)):
                found = True
                break
        assert found, "At least one schema must contain a Hero or Section node"

    # -----------------------------------------------------------------------
    # §9 criterion 5: form page uses real Input/Select/Textarea/Checkbox/DatePicker
    # -----------------------------------------------------------------------

    def test_form_schema_uses_real_form_inputs(self):
        form_input_types = {"Input", "Select", "Textarea", "Checkbox", "DatePicker"}
        form_schema = self.schemas["form"]
        root = form_schema.get("root", {})
        found_types = {
            node["type"]
            for node in _walk_nodes(root)
            if node.get("type") in form_input_types
        }
        assert found_types, (
            f"form.json must contain at least one of {form_input_types}; "
            f"found none"
        )

    # -----------------------------------------------------------------------
    # §9 criterion 6: schemas reference real token paths; no inline hex/px/rem
    # -----------------------------------------------------------------------

    def test_each_schema_contains_token_refs(self):
        _TOKEN_RE = re.compile(r"^tokens\.")
        for page_type, schema in self.schemas.items():
            all_vals = _all_string_values(schema)
            token_refs = [v for v in all_vals if _TOKEN_RE.match(v)]
            assert token_refs, (
                f"Schema '{page_type}' must contain at least one 'tokens.*' reference"
            )

    def test_schemas_have_no_inline_hex_in_style_values(self):
        _HEX_RE = re.compile(r"#[0-9a-fA-F]{6}")
        _PX_RE  = re.compile(r"\b\d+px\b")
        _REM_RE = re.compile(r"\b\d+(?:\.\d+)?rem\b")

        for page_type, schema in self.schemas.items():
            # Only check values inside 'style' subtrees
            def _collect_style_values(node: dict) -> list[str]:
                vals: list[str] = []
                if isinstance(node.get("style"), dict):
                    vals.extend(_all_string_values(node["style"]))
                for child in node.get("children", []):
                    vals.extend(_collect_style_values(child))
                return vals

            root = schema.get("root", {})
            style_vals = _collect_style_values(root)

            for val in style_vals:
                assert not _HEX_RE.search(val), (
                    f"Schema '{page_type}' has inline hex '{val}' in a style value; "
                    f"use token paths instead"
                )
                assert not _PX_RE.search(val), (
                    f"Schema '{page_type}' has inline px '{val}' in a style value; "
                    f"use token paths instead"
                )
                assert not _REM_RE.search(val), (
                    f"Schema '{page_type}' has inline rem '{val}' in a style value; "
                    f"use token paths instead"
                )

    # -----------------------------------------------------------------------
    # Bonus: schema structure sanity
    # -----------------------------------------------------------------------

    def test_schema_version_and_id_set(self):
        for page_type, schema in self.schemas.items():
            assert schema.get("schemaVersion") == "1", (
                f"Schema '{page_type}' must have schemaVersion '1' (agent default)"
            )
            assert schema.get("id") == f"accounts/{page_type}", (
                f"Schema '{page_type}' must have id 'accounts/{page_type}'"
            )

    def test_schema_has_required_top_level_keys(self):
        for page_type, schema in self.schemas.items():
            for key in ("route", "layout", "meta", "dataSources", "root"):
                assert key in schema, (
                    f"Schema '{page_type}' is missing required key '{key}'"
                )


# ---------------------------------------------------------------------------
# Test 2: FIDELITY_MODE_ENABLED=False — gold-example section absent from prompt
# ---------------------------------------------------------------------------

class TestFidelityFlagOff:
    """Spec §9: FIDELITY_MODE_ENABLED=false reverts to structural-only prompt."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        import services.schema_prompt as _sp_mod

        # Turn fidelity OFF
        monkeypatch.setattr(_sp_mod, "FIDELITY_MODE_ENABLED", False)

        self.captured_prompts: list[str] = []
        _run_pipeline(tmp_path, monkeypatch=monkeypatch, captured_prompts=self.captured_prompts)
        self.tmp_path = tmp_path

        schemas_dir = tmp_path / "src" / "schemas" / "accounts"
        self.schemas: dict[str, dict] = {
            pt: json.loads((schemas_dir / f"{pt}.json").read_text(encoding="utf-8"))
            for pt in ("list", "detail", "form")
        }

    def test_schemas_still_produced_when_fidelity_off(self):
        """The agent must still emit all three schemas even when fidelity is off."""
        schemas_dir = self.tmp_path / "src" / "schemas" / "accounts"
        for pt in ("list", "detail", "form"):
            assert (schemas_dir / f"{pt}.json").exists(), (
                f"Schema '{pt}' must still be produced when FIDELITY_MODE_ENABLED=False"
            )

    def test_prompts_captured_when_fidelity_off(self):
        """Sanity: the stub must have been called (three prompts captured)."""
        assert len(self.captured_prompts) == 3, (
            f"Expected 3 LLM calls (one per page type), got {len(self.captured_prompts)}"
        )

    def test_prompt_omits_gold_standard_example_section(self):
        """Spec §9: with fidelity off, the 'Gold-standard example' section header
        must NOT appear in the prompt — this proves the flag is read by the
        prompt builder."""
        for i, prompt in enumerate(self.captured_prompts):
            assert "Gold-standard example" not in prompt, (
                f"Prompt #{i} contains 'Gold-standard example' but "
                f"FIDELITY_MODE_ENABLED=False — the gate in build_schema_prompt "
                f"is not working"
            )

    def test_token_paths_still_present_in_prompt_when_fidelity_off(self):
        """Token contract is always emitted regardless of fidelity mode."""
        for i, prompt in enumerate(self.captured_prompts):
            assert "tokens." in prompt, (
                f"Prompt #{i} is missing token paths even though fidelity mode is off; "
                f"token contract must always be present"
            )
