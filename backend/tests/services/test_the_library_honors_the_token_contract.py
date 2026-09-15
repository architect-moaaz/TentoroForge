"""The status components read the ONE token contract, not a private dialect.

The library used to speak three token dialects — the shadcn set, bare role
names, and Badge/Alert's numbered `--color-success-100` scale that the projector
never filled, so a status chip wore Tailwind emerald while the button next to it
wore the design's palette. These pins keep the status surfaces (Badge, Alert,
Money) on the contract tokens the projector feeds, so a design's success/danger/
warning reaches them and the two never drift from each other.

Runnable here because it inspects source text; the live proof is the build +
cutover that re-vendors the library and re-emits tokens.css.
"""
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
_LIB = _ROOT / "packages" / "library" / "src"
_CONTRACT = _LIB / "theme" / "token-contract.json"
_TAILWIND = _ROOT / "backend" / "templates" / "app-foundation" / "tailwind.config.ts"


def _contract() -> dict:
    return json.loads(_CONTRACT.read_text("utf-8"))


def test_the_contract_declares_the_locked_status_shape():
    tokens = {t["token"] for t in _contract()["colorTokens"]}
    for role in ("destructive", "success", "warning", "info"):
        for suffix in ("", "-foreground", "-subtle", "-subtle-foreground"):
            assert f"{role}{suffix}" in tokens, f"contract missing {role}{suffix}"


def test_badge_reads_contract_status_tints_not_the_numbered_scale():
    src = (_LIB / "components" / "Badge" / "Badge.tsx").read_text("utf-8")
    assert "bg-success-subtle" in src and "bg-destructive-subtle" in src
    assert "bg-warning-subtle" in src
    # the retired numbered/emerald dialect is gone
    assert "--color-success-100" not in src
    assert "colors.emerald" not in src and "colors.red" not in src


def test_alert_reads_contract_status_tints_and_matches_badge():
    src = (_LIB / "components" / "Alert" / "Alert.tsx").read_text("utf-8")
    for tok in ("success-subtle", "destructive-subtle", "warning-subtle", "info-subtle"):
        assert f"--{tok}" in src, f"Alert does not read --{tok}"
    assert "--color-error-100" not in src and "--color-success-100" not in src


def test_money_required_marker_reads_a_real_token():
    src = (_LIB / "components" / "Money" / "Money.tsx").read_text("utf-8")
    # `text-danger` is not a Tailwind alias (the contract's status is
    # `destructive`), so the asterisk rendered unstyled.
    assert "text-danger" not in src
    assert "text-destructive" in src


def test_tailwind_config_exposes_the_contract_status_aliases():
    src = _TAILWIND.read_text("utf-8")
    # each status carries DEFAULT + subtle + subtle-foreground reading the
    # contract var, and keeps the legacy --color-* as a fallback (not primary).
    for role in ("success", "warning", "info"):
        assert f"var(--{role}," in src, f"tailwind alias for {role} not on contract"
        assert f"var(--{role}-subtle," in src, f"no subtle alias for {role}"
    assert "var(--destructive-subtle," in src
