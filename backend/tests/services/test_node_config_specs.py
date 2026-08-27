"""Tests for services.node_config_specs — the spec registry that
declares which secrets each workflow action type needs.

Slice INT-1. The registry is the single source of truth used to:
  - emit a sectioned .env.local (with the right headers + comments)
  - generate the /settings/integrations page's form fields
  - validate a plan's workflows have somewhere to source their keys

Tests are shape-only: no runtime, no IO. Ensures every entry is
well-formed, provider grouping works, and the union-over-plan helper
returns the right providers for a given workflow set.
"""
from __future__ import annotations

import pytest


# --------------------------------------------------------------------------- #
# Spec shape — every entry must be complete + typed
# --------------------------------------------------------------------------- #

def test_registry_shape_is_valid():
    """Every entry in NODE_CONFIG_SPECS must have the required fields
    with the right types. Missing/extra fields would break downstream
    code that iterates the registry (env scaffolder, UI generator)."""
    from services.node_config_specs import NODE_CONFIG_SPECS, ConfigKey

    assert isinstance(NODE_CONFIG_SPECS, dict), "registry must be a dict"
    assert NODE_CONFIG_SPECS, "registry must not be empty"

    for action_type, keys in NODE_CONFIG_SPECS.items():
        assert isinstance(action_type, str) and action_type, (
            f"action type must be a non-empty string, got {action_type!r}"
        )
        assert isinstance(keys, list), (
            f"{action_type!r}: value must be a list of ConfigKey"
        )
        for entry in keys:
            assert isinstance(entry, ConfigKey), (
                f"{action_type!r}: entries must be ConfigKey dataclasses, "
                f"got {type(entry).__name__}"
            )
            # Required fields
            assert entry.key and isinstance(entry.key, str)
            assert entry.provider and isinstance(entry.provider, str)
            assert entry.label and isinstance(entry.label, str)
            assert entry.kind in ("password", "text", "url"), (
                f"{action_type}/{entry.key}: kind must be password|text|url, "
                f"got {entry.kind!r}"
            )
            assert isinstance(entry.required, bool)
            # Optional fields
            if entry.default is not None:
                assert isinstance(entry.default, str)
            if entry.help_url is not None:
                assert isinstance(entry.help_url, str)
                assert entry.help_url.startswith("http")


def test_no_duplicate_keys_within_action_type():
    """Two entries for the same action type MUST NOT share a key —
    the UI would render duplicate form fields and the resolver would
    have to pick one arbitrarily."""
    from services.node_config_specs import NODE_CONFIG_SPECS

    for action_type, entries in NODE_CONFIG_SPECS.items():
        keys = [e.key for e in entries]
        assert len(keys) == len(set(keys)), (
            f"{action_type!r}: duplicate keys {[k for k in keys if keys.count(k) > 1]}"
        )


def test_env_var_names_are_uppercase_snake_case():
    """POSIX convention. Also ensures we never accidentally ship a
    key like 'resend-api-key' that would fail process.env lookup."""
    import re

    from services.node_config_specs import NODE_CONFIG_SPECS

    ok = re.compile(r"^[A-Z][A-Z0-9_]*$")
    for action_type, entries in NODE_CONFIG_SPECS.items():
        for entry in entries:
            assert ok.match(entry.key), (
                f"{action_type}/{entry.key}: env vars must be "
                f"UPPER_SNAKE_CASE"
            )


# --------------------------------------------------------------------------- #
# Coverage — the real handlers today must all be represented
# --------------------------------------------------------------------------- #

def test_runtime_action_types_covered():
    """Every workflow action type that reads a secret at runtime MUST
    have an entry — otherwise the env scaffolder won't emit its keys
    and the settings UI won't offer a way to configure them."""
    from services.node_config_specs import NODE_CONFIG_SPECS

    # These are the action types whose runtime handlers call process.env
    # (verified against output/3ncq1pky/src/lib/workflows/index.ts + ai.ts):
    #   send_email          → RESEND_API_KEY, FORGE_EMAIL_FROM
    #   ai_generate/etc     → ANTHROPIC_API_KEY (via ai.ts)
    #   file uploads (s3)   → FORGE_S3_BUCKET etc (via storage.ts)
    for at in ("send_email", "ai_generate", "ai_classify", "ai_extract", "ai_decide"):
        assert at in NODE_CONFIG_SPECS, (
            f"action type {at!r} reads secrets at runtime but has no "
            f"registry entry"
        )


def test_send_email_has_resend_key_required():
    from services.node_config_specs import NODE_CONFIG_SPECS

    keys = {e.key: e for e in NODE_CONFIG_SPECS["send_email"]}
    assert "RESEND_API_KEY" in keys, "send_email must declare RESEND_API_KEY"
    assert keys["RESEND_API_KEY"].required is True
    assert keys["RESEND_API_KEY"].kind == "password"
    assert keys["RESEND_API_KEY"].provider == "resend"


def test_ai_actions_share_anthropic_key():
    """All four ai_* handlers share ANTHROPIC_API_KEY. The UI should
    render ONE Anthropic card, not four."""
    from services.node_config_specs import NODE_CONFIG_SPECS

    for at in ("ai_generate", "ai_classify", "ai_extract", "ai_decide"):
        keys = {e.provider for e in NODE_CONFIG_SPECS[at]}
        assert "anthropic" in keys, f"{at}: missing anthropic provider entry"


# --------------------------------------------------------------------------- #
# Vision preset: ai_identify_product (Slice 2 — visual product search)
# --------------------------------------------------------------------------- #

def test_ai_identify_product_is_registered():
    """The vision preset MUST be registered so env_scaffold + integrations UI
    surface its Anthropic key and the planner/binding validator recognise
    the action_type."""
    from services.node_config_specs import NODE_CONFIG_SPECS

    assert "ai_identify_product" in NODE_CONFIG_SPECS, (
        "ai_identify_product preset must be registered in NODE_CONFIG_SPECS"
    )


def test_ai_identify_product_requires_anthropic_key():
    """The preset calls Claude with an image — ANTHROPIC_API_KEY must be
    declared as required so the settings UI marks it with an asterisk and
    binding_validator warns when it's missing."""
    from services.node_config_specs import NODE_CONFIG_SPECS

    keys = {e.key: e for e in NODE_CONFIG_SPECS["ai_identify_product"]}
    assert "ANTHROPIC_API_KEY" in keys, (
        "ai_identify_product must declare ANTHROPIC_API_KEY"
    )
    ak = keys["ANTHROPIC_API_KEY"]
    assert ak.required is True
    assert ak.kind == "password"
    assert ak.provider == "anthropic"


def test_ai_identify_product_uses_anthropic_provider():
    """Shares the Anthropic card with the other ai_* actions — the settings
    page renders a single Anthropic block, not a new provider."""
    from services.node_config_specs import providers_for_action

    provs = providers_for_action("ai_identify_product")
    assert provs == ["anthropic"], (
        f"ai_identify_product should map to just [anthropic], got {provs}"
    )


def test_ai_identify_product_included_when_plan_uses_it():
    """A plan that uses only the vision preset (no other ai_* nodes) must
    still surface the Anthropic settings card."""
    from services.node_config_specs import providers_used_by_plan

    plan = {"workflows": [{"nodes": [
        {"type": "action", "config": {"actionType": "ai_identify_product"}},
    ]}]}
    assert "anthropic" in providers_used_by_plan(plan)


# --------------------------------------------------------------------------- #
# providers_for_action() — used by the env scaffolder
# --------------------------------------------------------------------------- #

def test_providers_for_action_returns_unique_providers():
    from services.node_config_specs import providers_for_action

    provs = providers_for_action("send_email")
    assert "resend" in provs
    assert len(provs) == len(set(provs)), "duplicate providers returned"


def test_providers_for_action_returns_empty_for_unknown_type():
    """A workflow using a custom action type (or one with no secrets like
    db_insert) must return empty — not raise. Env scaffolder skips it."""
    from services.node_config_specs import providers_for_action

    assert providers_for_action("db_insert") == []
    assert providers_for_action("nonexistent_action_type_xyz") == []


# --------------------------------------------------------------------------- #
# providers_used_by_plan() — used by the settings-page emitter
# --------------------------------------------------------------------------- #

def test_providers_used_by_plan_unions_across_workflows():
    """The settings page renders one card per provider USED BY THE PLAN's
    workflows — no clutter for a plan that never sends SMS."""
    from services.node_config_specs import providers_used_by_plan

    plan = {
        "workflows": [
            {"nodes": [
                {"type": "action", "config": {"actionType": "send_email"}},
                {"type": "action", "config": {"actionType": "db_insert"}},
            ]},
            {"nodes": [
                {"type": "action", "config": {"actionType": "ai_generate"}},
            ]},
        ]
    }
    provs = providers_used_by_plan(plan)
    assert "resend" in provs, "send_email → resend missing"
    assert "anthropic" in provs, "ai_generate → anthropic missing"
    assert provs == sorted(set(provs)), "must return deduped + sorted"


def test_providers_used_by_plan_handles_missing_workflows_key():
    """A plan without a 'workflows' key must return [] — not crash."""
    from services.node_config_specs import providers_used_by_plan

    assert providers_used_by_plan({}) == []
    assert providers_used_by_plan({"workflows": []}) == []
    assert providers_used_by_plan({"workflows": None}) == []


def test_providers_used_by_plan_tolerates_malformed_nodes():
    """Real plans in the wild have inconsistent shapes. Must not crash
    on missing/malformed nodes or configs — silently skip them."""
    from services.node_config_specs import providers_used_by_plan

    plan = {
        "workflows": [
            {"nodes": None},
            {},                                    # no nodes key
            {"nodes": [
                None,                              # None entry
                "not-a-dict",                      # wrong type
                {"type": "action"},                # missing config
                {"config": {}},                    # missing actionType
                {"config": {"actionType": "send_email"}},  # valid — should still be picked up
            ]},
        ]
    }
    provs = providers_used_by_plan(plan)
    assert provs == ["resend"], (
        f"expected [resend] from the one valid node, got {provs}"
    )


def test_providers_used_by_plan_reads_planner_step_shape():
    """The planner emits workflows in a `steps` shape (see planner.py)
    that gets translated to `nodes` later. Both shapes must work so the
    helper can run BEFORE or AFTER the translator."""
    from services.node_config_specs import providers_used_by_plan

    plan = {
        "workflows": [
            {"steps": [
                {"type": "action", "config": {"actionType": "send_email"}},
            ]},
        ]
    }
    provs = providers_used_by_plan(plan)
    assert "resend" in provs


# --------------------------------------------------------------------------- #
# keys_for_provider() — used by the UI (one card per provider)
# --------------------------------------------------------------------------- #

def test_keys_for_provider_returns_all_keys_across_action_types():
    """The Resend card shows both RESEND_API_KEY and FORGE_EMAIL_FROM
    even though only one node might use them. Deduped across action types."""
    from services.node_config_specs import keys_for_provider

    keys = keys_for_provider("resend")
    key_names = {k.key for k in keys}
    assert "RESEND_API_KEY" in key_names
    # FORGE_EMAIL_FROM is optional but must still be surfaced
    assert "FORGE_EMAIL_FROM" in key_names


def test_keys_for_provider_returns_empty_for_unknown_provider():
    from services.node_config_specs import keys_for_provider

    assert keys_for_provider("nonexistent-provider") == []


def test_keys_for_provider_deduplicates_across_action_types():
    """ANTHROPIC_API_KEY is used by all four ai_* actions. The Anthropic
    card must show it ONCE, not four times."""
    from services.node_config_specs import keys_for_provider

    keys = keys_for_provider("anthropic")
    key_names = [k.key for k in keys]
    assert len(key_names) == len(set(key_names)), (
        f"duplicate keys in anthropic card: {key_names}"
    )


# --------------------------------------------------------------------------- #
# Storage / S3 / cron coverage
# --------------------------------------------------------------------------- #

def test_s3_provider_has_all_five_keys():
    from services.node_config_specs import keys_for_provider

    keys = {k.key for k in keys_for_provider("s3")}
    assert keys == {
        "FORGE_S3_BUCKET", "FORGE_S3_REGION", "FORGE_S3_PREFIX",
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY",
    }, f"unexpected S3 key set: {keys}"


def test_s3_keys_are_all_optional():
    """Empty bucket → local-disk fallback. Nothing about S3 is REQUIRED at
    generation time — the app runs fine on-disk until the operator opts in."""
    from services.node_config_specs import keys_for_provider

    for k in keys_for_provider("s3"):
        assert k.required is False, f"S3 key {k.key} shouldn't be required"


def test_s3_included_when_plan_uses_generate_document():
    from services.node_config_specs import providers_used_by_plan

    plan = {"workflows": [{"nodes": [{"config": {"actionType": "generate_document"}}]}]}
    assert "s3" in providers_used_by_plan(plan)


def test_cron_included_when_workflow_has_schedule_trigger():
    from services.node_config_specs import providers_used_by_plan

    plan = {"workflows": [{"trigger": {"type": "schedule"}, "nodes": []}]}
    assert "cron" in providers_used_by_plan(plan)

    plan2 = {"workflows": [{
        "nodes": [{"type": "trigger", "config": {"type": "schedule"}}],
    }]}
    assert "cron" in providers_used_by_plan(plan2)


def test_cron_included_when_trigger_lives_in_definition_shape():
    from services.node_config_specs import providers_used_by_plan

    plan = {"workflows": [{"definition": {"trigger": {"type": "schedule"}}}]}
    assert "cron" in providers_used_by_plan(plan)


def test_providers_used_by_app_reads_capabilities_from_file_system(tmp_path):
    """FileUpload used in any page schema pulls S3 into the settings page,
    even if no workflow uses generate_document/file_upload."""
    import json
    from services.node_config_specs import providers_used_by_app

    # Minimal app: plan with no workflows but a schema that uses FileUpload.
    (tmp_path / "src" / "contracts").mkdir(parents=True)
    (tmp_path / "src" / "contracts" / "plan.json").write_text(json.dumps({}))
    (tmp_path / "src" / "schemas").mkdir()
    (tmp_path / "src" / "schemas" / "signup.json").write_text(json.dumps({
        "root": {"children": [{"type": "FileUpload"}]},
    }))

    provs = providers_used_by_app(str(tmp_path))
    assert "s3" in provs


def test_providers_used_by_app_unions_plan_and_capabilities(tmp_path):
    import json
    from services.node_config_specs import providers_used_by_app

    (tmp_path / "src" / "contracts").mkdir(parents=True)
    (tmp_path / "src" / "contracts" / "plan.json").write_text(json.dumps({
        "workflows": [{"nodes": [{"config": {"actionType": "send_email"}}]}],
    }))
    (tmp_path / "src" / "schemas").mkdir()
    (tmp_path / "src" / "schemas" / "signup.json").write_text('{"root":{"children":[{"type":"FileUpload"}]}}')

    provs = providers_used_by_app(str(tmp_path))
    assert "resend" in provs, "workflow signal preserved"
    assert "s3" in provs, "capability signal added"


def test_providers_used_by_app_empty_when_nothing_used(tmp_path):
    import json
    from services.node_config_specs import providers_used_by_app

    (tmp_path / "src" / "contracts").mkdir(parents=True)
    (tmp_path / "src" / "contracts" / "plan.json").write_text(json.dumps({}))
    assert providers_used_by_app(str(tmp_path)) == []
