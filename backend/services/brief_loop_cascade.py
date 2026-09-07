"""Post-`edit_brief` cascade: recompile the design tokens.

Phase 3 addition. When Smith calls edit_brief, the brief.json changes
on disk — but tokens.custom.json (which drives the generated app's
CSS variables) still reflects the old values. This module bridges
brief → design_spec shape and calls the existing design_compiler to
refresh tokens.

Kept minimal — Phase 3 additive doesn't touch page schemas or
regenerate components. Just the token layer, which is the fastest,
most visible cascade the user gets from an aesthetic edit.

Pure module — filesystem only, no LLM. Failures are logged and
swallowed so an edit never breaks Smith's turn.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from schemas.design_brief import DesignBrief

logger = logging.getLogger(__name__)


def brief_to_design_spec_overlay(brief: DesignBrief) -> dict:
    """Project a DesignBrief onto the design_spec shape that
    :func:`services.design_compiler.compile` consumes.

    Only the fields the compiler reads are populated — palette and
    typography. Layout enums (density/radius) are informational and
    handled by other guards. Returns a dict safe to merge over an
    existing design-spec.json.
    """
    p = brief.palette
    t = brief.typography
    return {
        "colorPalette": {
            "brand":   {"500": p.brand},
            "accent":  {"500": p.accent},
            "neutral": {"50": p.neutrals_base, "900": p.foreground_primary},
        },
        "typography": {
            "display": {
                "family": t.display_family,
                "weights": list(t.display_weights),
            },
            "body": {
                "family": t.body_family,
                "weights": list(t.body_weights),
            },
        },
    }


def cascade(output_dir: str | Path) -> dict:
    """Recompile design tokens from the current brief on disk.

    Reads contracts/brief.json + design-spec.json (if any), overlays the
    brief onto the spec, calls design_compiler.compile_to_file → writes
    tokens.custom.json.

    Returns a small dict with what happened; empty on no-op.
    """
    out_dir = Path(output_dir)
    brief_path = out_dir / "contracts" / "brief.json"
    if not brief_path.exists():
        logger.info("[brief-cascade] no brief.json — skipping")
        return {"recompiled": False, "reason": "no brief.json"}

    try:
        brief = DesignBrief.model_validate_json(brief_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[brief-cascade] brief.json unreadable: %s", exc)
        return {"recompiled": False, "reason": f"brief unreadable: {exc}"}

    overlay = brief_to_design_spec_overlay(brief)

    # Merge over existing design-spec if the pipeline authored one; else
    # use the overlay alone.
    spec_path = out_dir / "src" / "contracts" / "design-spec.json"
    design_spec: dict = {}
    if spec_path.exists():
        try:
            design_spec = json.loads(spec_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("[brief-cascade] design-spec.json unreadable: %s", exc)

    # Brief WINS on overlap — this is the Phase 3 contract.
    _deep_merge(design_spec, overlay)

    # `src/theme/`, not `src/app/`. This was the only writer in the platform
    # aiming at `src/app/tokens.custom.json`; every other writer
    # (generate.py, output_projects.py, _debug_schema.py, pipeline_graph.py)
    # and every reader (render-scaffold's loadTokens.ts, the built app's
    # load-custom.ts, feature_slice_schema_agent) uses `src/theme/`. So the
    # cascade compiled the brief, wrote the file, returned
    # `{"recompiled": true}` — and nothing on the platform ever opened it.
    # A brief that changed the palette appeared to apply and applied nothing.
    tokens_path = out_dir / "src" / "theme" / "tokens.custom.json"
    tokens_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from services.design_compiler import compile_to_file
        compile_to_file(design_spec, str(tokens_path))
        logger.info("[brief-cascade] tokens.custom.json recompiled → %s", tokens_path)
        return {
            "recompiled": True,
            "tokens_path": str(tokens_path),
            "brief_summary": brief.summary_line(),
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("[brief-cascade] compile_to_file failed: %s", exc)
        return {"recompiled": False, "reason": f"compile failed: {exc}"}


def _deep_merge(dst: dict, src: dict) -> None:
    """In-place merge — recurses into nested dicts. Not lists.

    Used to overlay the brief's shape onto whatever the pipeline
    originally authored, keeping any fields the brief doesn't touch.
    """
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v


__all__ = ["cascade", "brief_to_design_spec_overlay"]
