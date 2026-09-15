"""The design-token contract is one source, and the Blueprint palette reaches it.

Composition never names a colour — it says `variant:"danger"`, and a component
resolves that through `hsl(var(--destructive))`. So the palette reaches the
screen only if the projector fills every `var(--…)` the library reads from the
Blueprint role that feeds it. Before the contract, status colours reached the
app under one name (`--success`) but not the name Badge read
(`--color-success-100`), and `surface` never reached `--card`. These lock the
bridge: change the Blueprint role, and the contract token moves with it.
"""
import json
from pathlib import Path

from services.blueprint.projection import project_design_tokens, _token_contract


_BP = {
    "designSystem": {
        "colors": {
            "primary": "#4F46E5", "background": "#F8FAFC", "surface": "#FFFFFF",
            "textPrimary": "#111827", "textSecondary": "#6B7280",
            "border": "#E2E8F0", "primarySubtle": "#EEF2FF", "accent": "#F59E0B",
            "danger": "#B91C1C", "dangerSubtle": "#FEE2E2",
            "success": "#15803D", "successSubtle": "#DCFCE7",
            "warning": "#B45309", "warningSubtle": "#FEF3C7",
            "info": "#0369A1", "infoSubtle": "#E0F2FE",
        },
        "radius": {"md": "8px"},
    }
}


def _css(tmp_path, bp=_BP):
    project_design_tokens(bp, tmp_path)
    return (tmp_path / "src" / "app" / "tokens.css").read_text()


def test_the_contract_file_exists_and_declares_the_status_shape():
    tokens = {t["token"] for t in (_token_contract().get("colorTokens") or [])}
    assert tokens, "token-contract.json must be readable from the library"
    for role in ("destructive", "success", "warning", "info"):
        for suffix in ("", "-foreground", "-subtle", "-subtle-foreground"):
            assert f"{role}{suffix}" in tokens, f"missing {role}{suffix}"


def test_surface_reaches_card_and_popover(tmp_path):
    css = _css(tmp_path)
    # surface #FFFFFF -> 0 0% 100%, under the names the library actually reads.
    assert "--card: 0 0% 100%;" in css
    assert "--popover: 0 0% 100%;" in css


def test_danger_reaches_destructive_and_its_subtle(tmp_path):
    css = _css(tmp_path)
    assert "--destructive: 0 74% 42%;" in css          # hsl(#B91C1C)
    assert "--destructive-subtle:" in css              # from dangerSubtle
    # subtle-foreground is the solid danger (readable on the tint)
    assert "--destructive-subtle-foreground: 0 74% 42%;" in css


def test_every_status_colour_reaches_a_contract_token(tmp_path):
    css = _css(tmp_path)
    for tok in ("success", "warning", "info"):
        assert f"--{tok}: " in css, f"{tok} did not reach the contract"
        assert f"--{tok}-subtle: " in css


def test_a_foreground_is_computed_for_readability(tmp_path):
    # A dark solid gets white text; a light tint gets dark text — never left to
    # a template default that a tinted palette would render unreadable.
    css = _css(tmp_path)
    assert "--primary-foreground: 0 0% 100%;" in css     # on indigo → white
    lines = {l.split(":")[0].strip(): l for l in css.splitlines() if l.strip().startswith("--")}
    assert "--destructive-foreground" in lines


def test_no_dead_role_named_twin_for_a_consumed_role(tmp_path):
    # danger became --destructive; it must NOT also reappear as a dead --danger
    # that nothing reads (the two-vocabulary smell the contract removes).
    css = _css(tmp_path)
    assert "--danger:" not in css
    assert "--surface:" not in css       # became --card/--popover
    assert "--text-primary:" not in css  # became --foreground


def test_an_app_specific_role_still_passes_through(tmp_path):
    # A colour the shadcn contract has no slot for is not dropped — the rail
    # reads --sidebar-background raw.
    bp = {"designSystem": {"colors": {"sidebarBackground": "#0B1120"}}}
    css = _css(tmp_path, bp)
    assert "--sidebar-background: #0B1120;" in css
