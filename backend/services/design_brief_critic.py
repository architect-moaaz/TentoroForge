"""Score generated design output against the brief it should have followed.

The critic is deterministic — it checks for:
  - Antipattern violations (any blocklist label present as substring in
    the rendered CSS/schema output ⇒ hard-reject).
  - Brand-hex adherence (LLM should use brief.palette hexes; count how
    many other hexes leaked in).
  - Signature-move presence (at least one kind name from
    signature_moves must appear somewhere in the generated files).

Pure module; consumers pass in {'schemas': [str], 'tokens_json': dict}
or similar bag-of-artifacts. No filesystem I/O.

This is deliberately NOT an LLM — an LLM critic (Angle B) exists for
narrative-quality feedback; this one gives crisp pass/fail signals the
pipeline can gate on.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from schemas.design_brief import DesignBrief


_HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}")


@dataclass(frozen=True)
class CriticFinding:
    kind: str          # "antipattern" | "brand_leak" | "no_signature_move"
    severity: str      # "block" | "warn"
    detail: str


@dataclass(frozen=True)
class CriticReport:
    passed: bool
    findings: tuple[CriticFinding, ...] = ()
    stats: dict = field(default_factory=dict)


def _brief_hexes(brief: DesignBrief) -> set[str]:
    p = brief.palette
    return {
        p.brand.upper(), p.accent.upper(),
        p.neutrals_base.upper(),
        p.surface_bg.upper(), p.surface_elevated.upper(),
        p.foreground_primary.upper(), p.foreground_muted.upper(),
    }


def critique(
    brief: DesignBrief,
    artifacts: dict,
) -> CriticReport:
    """Score ``artifacts`` (a bag of rendered strings) against ``brief``.

    Args:
        brief: the contract.
        artifacts: dict with any of:
            - ``rendered_text``: flat concatenation of all schema/css/tsx
              source (str). This is the main haystack.
            - ``file_paths``: iterable of file paths that were touched
              (for reporting; not scanned).

    Returns:
        A CriticReport. ``passed`` is False iff any severity=="block"
        finding fired. Warnings do not fail the report.
    """
    text = str(artifacts.get("rendered_text") or "")
    text_l = text.lower()

    findings: list[CriticFinding] = []

    # Antipattern scan — substring match on lowered text.
    ap_hits: list[str] = []
    for ap in brief.anti_patterns:
        if not ap:
            continue
        needle = ap.lower().replace("_", " ")
        if needle in text_l or ap.lower() in text_l:
            ap_hits.append(ap)
    for ap in ap_hits:
        findings.append(CriticFinding(
            kind="antipattern",
            severity="block",
            detail=f"antipattern '{ap}' appears in generated output",
        ))

    # Brand-hex leakage — how many hexes appear that aren't in the brief.
    all_hexes = {h.upper() for h in _HEX_RE.findall(text)}
    approved = _brief_hexes(brief)
    leaked = sorted(all_hexes - approved - {"#000000", "#FFFFFF"})
    if len(leaked) > 5:
        findings.append(CriticFinding(
            kind="brand_leak",
            severity="warn",
            detail=(
                f"{len(leaked)} hexes not in brief palette "
                f"(sample: {', '.join(leaked[:5])}…)"
            ),
        ))

    # Signature move presence — at least one kind name should appear.
    sig_kinds = [m.kind for m in brief.signature_moves]
    matched_kinds = [k for k in sig_kinds if k.lower() in text_l]
    if not matched_kinds:
        findings.append(CriticFinding(
            kind="no_signature_move",
            severity="warn",
            detail=(
                "none of the signature_moves appear in generated output "
                f"(expected any of: {', '.join(sig_kinds)})"
            ),
        ))

    passed = not any(f.severity == "block" for f in findings)
    return CriticReport(
        passed=passed,
        findings=tuple(findings),
        stats={
            "antipattern_hits": len(ap_hits),
            "brand_leak_count": len(leaked),
            "signature_kinds_matched": len(matched_kinds),
            "signature_kinds_expected": len(sig_kinds),
            "total_hexes_in_output": len(all_hexes),
        },
    )


__all__ = ["critique", "CriticReport", "CriticFinding"]
