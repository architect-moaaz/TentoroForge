"""First-class user requirement artifact.

Persisted as ``<output_dir>/src/contracts/requirement.json``. This is
the authoritative record of what the user asked for — the plan and the
schemas are DERIVATIONS of this. Every generator, composer, guard, and
Smith turn that wants to know "what did the user actually ask for?"
reads from here.

Shape:

    {
      "original_prompt":  "...",           # verbatim, first-turn text
      "parsed_directives": {               # what services.plan_directive_parser found
        "visual_preset":       "trust-navy",
        "archetype_vocabulary": "analytics-dashboard",
        "row_click_target":    "/subscriptions/[id]",
        "filter_dimensions":   ["Date range", "Plan", "Status"],
        "gauges":              [{...}, {...}],
        "chart_types":         [{...}, ...]
      },
      "amendments": [                      # append-only, per Smith turn
        {"at": "...", "who": "user", "text": "make it more editorial",
         "parsed_directives": {...}}
      ],
      "version": 1
    }

Two things this artifact makes possible that plan.description alone can't:

  1. **Survival.** plan.json is rewritten every regen. requirement.json
     is preserved. If the user edits with Smith and later regenerates,
     the original ask + all amendments carry forward.
  2. **Fidelity checking.** The requirement-fidelity critic (Slice 3)
     can compare the requirement's parsed directives against what
     shipped and drive targeted repairs.

Never raises — a missing / unreadable file returns None so callers can
treat the requirement as optional context.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REQUIREMENT_VERSION = 1
REL_PATH = ("src", "contracts", "requirement.json")


def _iso_now() -> str:
    """UTC now as an ISO-8601 string. Isolated so tests can monkeypatch."""
    return datetime.now(timezone.utc).isoformat()


def path_for(output_dir: str | Path) -> Path:
    """Return the on-disk path for requirement.json under ``output_dir``."""
    return Path(output_dir).joinpath(*REL_PATH)


def build_requirement(prompt: str) -> dict[str, Any]:
    """Compose a fresh requirement dict from the user's prompt.

    Runs the directive parser so the persisted record has both the raw
    text AND the structured directives extracted from it — downstream
    consumers pick whichever shape they need.

    Also runs the requirement-contract extractor
    (:mod:`services.requirement_contract`) to capture USER-NAMED
    routes / components / action-types / landing / negations. These
    ride under ``parsed_directives.contract`` so the fidelity critic
    can hold the LLM to them verbatim (motivating defect: Banking
    Archive gen renamed ``/history`` → ``/batches`` and swapped
    ``ocr_document`` for ``http_call`` — every drift now surfaceable).
    """
    parsed: dict[str, Any] = {}
    try:
        from services.plan_directive_parser import parse_all_directives
        parsed = parse_all_directives(prompt) if isinstance(prompt, str) else {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("[requirement] directive parse failed: %s", exc)
        parsed = {}
    try:
        from services.requirement_contract import extract_contract
        contract = extract_contract(prompt).to_dict() if isinstance(prompt, str) else {}
        if contract:
            parsed["contract"] = contract
    except Exception as exc:  # noqa: BLE001
        logger.warning("[requirement] contract extraction failed: %s", exc)
    return {
        "original_prompt": prompt if isinstance(prompt, str) else "",
        "parsed_directives": parsed,
        "amendments": [],
        "version": REQUIREMENT_VERSION,
    }


def write_requirement(output_dir: str | Path, requirement: dict[str, Any]) -> Path | None:
    """Persist ``requirement`` to ``requirement.json``. Returns the path
    on success, None on failure. Fail-open — never raises.
    """
    if not isinstance(requirement, dict):
        return None
    p = path_for(output_dir)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(requirement, indent=2), encoding="utf-8")
        return p
    except Exception as exc:  # noqa: BLE001
        logger.warning("[requirement] write failed %s: %s", p, exc)
        return None


def load_requirement(output_dir: str | Path) -> dict[str, Any] | None:
    """Read the persisted requirement, or None when missing/unreadable."""
    p = path_for(output_dir)
    if not p.is_file():
        return None
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[requirement] load failed %s: %s", p, exc)
        return None
    return raw if isinstance(raw, dict) else None


def ensure_requirement(output_dir: str | Path, prompt: str) -> dict[str, Any]:
    """Create requirement.json from ``prompt`` when it doesn't already
    exist; return the current requirement dict. Idempotent — a second
    call with the same prompt is a no-op that returns the existing file.

    When the file exists but its ``original_prompt`` differs from
    ``prompt``, the current prompt is treated as a new AMENDMENT
    (append to ``amendments``, not overwrite). This preserves history
    for the fidelity critic.
    """
    existing = load_requirement(output_dir)
    if existing is None:
        req = build_requirement(prompt)
        write_requirement(output_dir, req)
        return req
    # File exists — check whether ``prompt`` is a new amendment.
    if isinstance(prompt, str) and prompt.strip() and \
       prompt.strip() != str(existing.get("original_prompt") or "").strip():
        amend_requirement(output_dir, prompt, who="user")
        return load_requirement(output_dir) or existing
    return existing


def amend_requirement(output_dir: str | Path, text: str,
                       *, who: str = "user") -> dict[str, Any] | None:
    """Append an amendment to ``requirement.amendments``. Runs the
    directive parser on the amendment text so the fidelity critic can
    check the deltas without re-running the parser.

    Returns the updated requirement dict, or None on failure.
    """
    req = load_requirement(output_dir)
    if req is None:
        # No original requirement yet — bootstrap from the amendment
        # text so history has SOMETHING to check against.
        req = build_requirement(text)
        write_requirement(output_dir, req)
        return req
    parsed: dict[str, Any] = {}
    try:
        from services.plan_directive_parser import parse_all_directives
        parsed = parse_all_directives(text) if isinstance(text, str) else {}
    except Exception:  # noqa: BLE001
        parsed = {}
    amendments = req.setdefault("amendments", [])
    if not isinstance(amendments, list):
        amendments = []
        req["amendments"] = amendments
    amendments.append({
        "at": _iso_now(),
        "who": who,
        "text": text if isinstance(text, str) else "",
        "parsed_directives": parsed,
    })
    write_requirement(output_dir, req)
    return req


def render_requirement_for_prompt(requirement: dict[str, Any] | None,
                                    *, max_amendments: int = 5) -> str:
    """Render the requirement as a compact block for LLM prompts (Smith,
    composers, critics). Empty string when the requirement is missing
    or empty. Caps amendments to the most recent ``max_amendments`` to
    keep token cost bounded; older ones live in the on-disk record.
    """
    if not isinstance(requirement, dict):
        return ""
    prompt = str(requirement.get("original_prompt") or "").strip()
    parsed = requirement.get("parsed_directives") or {}
    amendments = requirement.get("amendments") or []
    if not (prompt or parsed or amendments):
        return ""
    lines: list[str] = ["USER REQUIREMENT (authoritative — the shipped app must reflect this):"]
    if prompt:
        lines.append(f"  Original ask:")
        for pl in prompt.splitlines()[:20]:
            lines.append(f"    {pl}")
    if isinstance(parsed, dict) and parsed:
        lines.append("  Parsed directives:")
        for k, v in parsed.items():
            lines.append(f"    - {k}: {v}")
    if isinstance(amendments, list) and amendments:
        tail = amendments[-int(max_amendments):]
        lines.append(f"  Amendments (most recent {len(tail)} of {len(amendments)}):")
        for a in tail:
            who = str(a.get("who") or "?")
            text = str(a.get("text") or "").strip().splitlines()[0][:200]
            lines.append(f"    - [{who}] {text}")
    return "\n".join(lines) + "\n"


__all__ = [
    "REQUIREMENT_VERSION",
    "path_for",
    "build_requirement",
    "write_requirement",
    "load_requirement",
    "ensure_requirement",
    "amend_requirement",
    "render_requirement_for_prompt",
]
