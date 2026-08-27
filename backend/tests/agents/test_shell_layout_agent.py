"""Unit tests for shell_layout_agent — pure functions only (no LLM calls)."""
import pytest

from agents.shell_layout_agent import extract_shell, SHELL_LAYOUT_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# extract_shell tests
# ---------------------------------------------------------------------------


def test_extract_shell_from_ir_shell_fence():
    text = """
    Here is the shell:

    ```ir-shell
    {
      "schemaVersion": "2.0",
      "title": "Shell",
      "children": [{"type": "PageOutlet"}]
    }
    ```
    """
    out = extract_shell(text)
    assert out is not None
    assert out["children"][0]["type"] == "PageOutlet"


def test_extract_shell_no_fence_returns_none():
    assert extract_shell("no schema here") is None


def test_extract_shell_invalid_json_returns_none():
    text = "```ir-shell\n{not valid json}\n```"
    assert extract_shell(text) is None


def test_extract_shell_fallback_to_json_fence():
    text = '```json\n{"schemaVersion": "2.0", "children": []}\n```'
    out = extract_shell(text)
    assert out is not None
    assert out["schemaVersion"] == "2.0"


def test_extract_shell_preserves_nested_structure():
    schema = {
        "schemaVersion": "2.0",
        "title": "App Shell",
        "id": "shell",
        "children": [
            {
                "type": "Stack",
                "props": {"className": "min-h-screen flex flex-col"},
                "children": [
                    {
                        "type": "Container",
                        "props": {"data-shell-region": "header"},
                        "children": [
                            {"type": "Text", "props": {"content": "MyApp"}}
                        ],
                    },
                    {"type": "PageOutlet", "id": "page-outlet"},
                ],
            }
        ],
    }
    import json
    text = f"```ir-shell\n{json.dumps(schema, indent=2)}\n```"
    out = extract_shell(text)
    assert out is not None
    assert out["id"] == "shell"
    root = out["children"][0]
    assert root["type"] == "Stack"
    regions = [c.get("props", {}).get("data-shell-region") for c in root["children"]]
    assert "header" in regions


def test_extract_shell_returns_none_for_empty_string():
    assert extract_shell("") is None


def test_extract_shell_bare_fence_without_schema_version_returns_none():
    # A plain ``` fence without schemaVersion should NOT match the fallback
    text = '```json\n{"title": "No version here"}\n```'
    assert extract_shell(text) is None


# ---------------------------------------------------------------------------
# System prompt smoke checks
# ---------------------------------------------------------------------------


def test_system_prompt_mentions_flavors():
    assert "Flavor A" in SHELL_LAYOUT_SYSTEM_PROMPT
    assert "Flavor B" in SHELL_LAYOUT_SYSTEM_PROMPT
    assert "Flavor C" in SHELL_LAYOUT_SYSTEM_PROMPT
    assert "Flavor D" in SHELL_LAYOUT_SYSTEM_PROMPT


def test_system_prompt_mentions_page_outlet():
    assert "PageOutlet" in SHELL_LAYOUT_SYSTEM_PROMPT


def test_system_prompt_mentions_data_shell_region():
    assert "data-shell-region" in SHELL_LAYOUT_SYSTEM_PROMPT


def test_system_prompt_mentions_workflow_auth():
    assert "workflow:auth.signOut" in SHELL_LAYOUT_SYSTEM_PROMPT


def test_system_prompt_mentions_navigate():
    assert "navigate" in SHELL_LAYOUT_SYSTEM_PROMPT


def test_system_prompt_contains_responsive_rules():
    """Shell agent must instruct the LLM to emit responsive shell structure."""
    assert "Responsive Rules" in SHELL_LAYOUT_SYSTEM_PROMPT


def test_system_prompt_requires_sidebar_hidden_md():
    """Sidebar must use hidden md:block so it collapses on mobile."""
    assert "hidden md:block" in SHELL_LAYOUT_SYSTEM_PROMPT


def test_system_prompt_requires_hamburger_md_hidden():
    """Hamburger button must be md:hidden so it only shows on mobile."""
    assert "md:hidden" in SHELL_LAYOUT_SYSTEM_PROMPT


def test_system_prompt_requires_icon_on_nav_items():
    """Visual quality section must instruct LLM to always add icon to nav Buttons."""
    assert "icon" in SHELL_LAYOUT_SYSTEM_PROMPT
    assert "Lucide" in SHELL_LAYOUT_SYSTEM_PROMPT


def test_system_prompt_requires_ghost_variant_for_nav():
    """Visual quality section must specify ghost variant for sidebar nav."""
    assert "ghost" in SHELL_LAYOUT_SYSTEM_PROMPT


def test_system_prompt_forbids_random_src_for_avatar():
    """Avatar guidance must prohibit random src URLs."""
    assert "Do NOT pass `src`" in SHELL_LAYOUT_SYSTEM_PROMPT or \
           "Do not pass `src`" in SHELL_LAYOUT_SYSTEM_PROMPT or \
           "Do NOT pass" in SHELL_LAYOUT_SYSTEM_PROMPT


def test_system_prompt_includes_domain_aesthetic():
    """Domain aesthetic block must map app_type to visual style."""
    assert "Domain Aesthetic" in SHELL_LAYOUT_SYSTEM_PROMPT
    assert "saas" in SHELL_LAYOUT_SYSTEM_PROMPT
    assert "crm" in SHELL_LAYOUT_SYSTEM_PROMPT
    assert "marketing" in SHELL_LAYOUT_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Integration helper — skipped without API key
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.skip(reason="Requires ANTHROPIC_API_KEY; smoke-run manually.")
async def test_generate_shell_to_file_e2e(tmp_path):
    from agents.shell_layout_agent import generate_shell_to_file

    plan = {
        "name": "TestApp",
        "description": "A simple SaaS dashboard.",
        "app_type": "saas",
        "pages": [
            {
                "id": "dashboard",
                "route": "/dashboard",
                "type": "dashboard",
                "name": "Dashboard",
            }
        ],
    }
    nf = {
        "pages": [{"route": "/dashboard", "shell": True, "id": "dashboard", "title": "Dashboard"}],
        "auth_routes": [],
    }
    shell = await generate_shell_to_file(tmp_path, plan, nf)
    assert shell is not None
    assert (tmp_path / "src" / "schemas" / "shell.json").exists()
