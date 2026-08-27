"""SV-STRICT-4 — promises extractor.

Pulls structured "promise" data (persona jobs, page purposes, workflow
purposes) from the app's contract files. This data fills
:class:`services.component_contract.ComponentContract` ``why`` slots
and drives the promise-vs-delivery gate (:mod:`services.promise_gate`).

Design note
-----------

BLUEPRINT.md is a human-facing rendered VIEW of these same sources — a
lossy transform. Parsing Markdown back would be brittle. So this
module reads the source contracts directly (``product-brief.json``,
``plan.json``, ``nav-flow.json``) and treats them as the authoritative
promise substrate. BLUEPRINT.md and this module are two independent
views of the same underlying data — they can't drift.

Pure function. Best-effort. Missing files degrade cleanly.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PersonaJob:
    """One thing a persona said they want to do in the app."""

    persona_id: str
    persona_name: str
    job_id: str
    job_label: str
    primary_entities: tuple[str, ...] = ()


@dataclass
class Promises:
    """The full promise set for one app."""

    persona_jobs: list[PersonaJob] = field(default_factory=list)
    page_purposes: dict[str, str] = field(default_factory=dict)
    workflow_purposes: dict[str, str] = field(default_factory=dict)


# ── Public entry ─────────────────────────────────────────────────────────


def load_promises(output_dir: str | Path) -> Promises:
    """Read contract files under ``output_dir`` and return the Promises.

    Missing / malformed files yield empty sections — the whole function
    never raises.
    """
    root = Path(output_dir)
    brief = _read_first(root, "product-brief.json")
    plan = _read_first(root, "plan.json")
    nav = _read_first(root, "nav-flow.json")

    return Promises(
        persona_jobs=_persona_jobs_from_brief(brief),
        page_purposes=_page_purposes(plan, nav),
        workflow_purposes=_workflow_purposes(plan),
    )


# ── Helpers ──────────────────────────────────────────────────────────────


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as exc:  # noqa: BLE001
        logger.debug("[blueprint_promises] bad JSON at %s: %s", path, exc)
        return {}


# Contracts land in different roots across pipeline versions:
#   src/contracts/<name>  — legacy layout used by fixtures
#   contracts/<name>      — current pipeline output
#   plan/<name>           — a few older apps kept plan-side copies
_CONTRACT_ROOTS = (
    Path("src") / "contracts",
    Path("contracts"),
    Path("plan"),
)


def _read_first(root: Path, filename: str) -> dict:
    for sub in _CONTRACT_ROOTS:
        data = _read_json(root / sub / filename)
        if data:
            return data
    return {}


def _persona_jobs_from_brief(brief: dict) -> list[PersonaJob]:
    out: list[PersonaJob] = []
    for persona in brief.get("personas") or []:
        if not isinstance(persona, dict):
            continue
        pid = str(persona.get("id") or persona.get("role") or "").strip()
        pname = str(persona.get("name") or pid or "").strip()
        for job in persona.get("jobs") or []:
            if not isinstance(job, dict):
                continue
            label = str(job.get("label") or "").strip()
            if not label:
                continue
            out.append(PersonaJob(
                persona_id=pid,
                persona_name=pname,
                job_id=str(job.get("id") or "").strip(),
                job_label=label,
                primary_entities=tuple(
                    str(e) for e in (job.get("primary_entities") or [])
                    if isinstance(e, str)
                ),
            ))
    return out


def _page_purposes(plan: dict, nav: dict) -> dict[str, str]:
    """Route → one-line purpose. Plan wins over nav-flow-title."""
    out: dict[str, str] = {}
    # 1. Nav-flow titles (baseline).
    for p in (nav.get("pages") or []):
        if not isinstance(p, dict):
            continue
        route = str(p.get("route") or "").strip()
        title = str(p.get("title") or "").strip()
        if route and title:
            out[route] = title
    # 2. Plan descriptions override.
    for p in (plan.get("pages") or []):
        if not isinstance(p, dict):
            continue
        route = str(p.get("route") or "").strip()
        desc = _first_str(p, "description", "purpose")
        if route and desc:
            out[route] = desc
    return out


def _workflow_purposes(plan: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for wf in (plan.get("workflows") or []):
        if not isinstance(wf, dict):
            continue
        name = str(wf.get("name") or "").strip()
        desc = _first_str(wf, "description", "purpose")
        if name and desc:
            out[name] = desc
    return out


def _first_str(d: dict, *keys: str) -> str:
    for k in keys:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""
