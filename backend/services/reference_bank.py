# backend/services/reference_bank.py
"""Reference grounding bank — loads curated Page-schema exemplars per
(domain, page_type) for injection into the schema agent's prompt.

The bank is hand-seeded once via scripts/seed_reference_bank.py, then
versioned in git. At gen time, build_schema_prompt() loads up to N exemplars
for the page being generated."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_BANK_ROOT = Path(__file__).resolve().parents[2] / "backend" / "reference_pages"
# Adjust if running from different cwd; the canonical location is
# <repo-root>/backend/reference_pages/. Resolves to absolute path on import.
if not _BANK_ROOT.exists():
    # Fallback: walk up from this file to find backend/reference_pages
    here = Path(__file__).resolve()
    for parent in [here.parent.parent, here.parent.parent.parent]:
        candidate = parent / "reference_pages"
        if candidate.exists():
            _BANK_ROOT = candidate
            break


@dataclass
class Exemplar:
    schema: dict[str, Any]
    score: float
    meta: dict[str, Any]
    domain: str
    page_type: str
    file_stem: str  # e.g. "exemplar_01"


def _load_from_cell(cell: Path, domain: str, page_type: str) -> list[Exemplar]:
    """Load all valid exemplars from a single bank cell directory."""
    exemplars: list[Exemplar] = []
    for schema_file in sorted(cell.glob("exemplar_*.json")):
        if schema_file.name.endswith(".meta.json"):
            continue
        meta_file = schema_file.with_suffix(".meta.json")
        # Tolerate missing or unreadable files — just skip
        try:
            schema = json.loads(schema_file.read_text())
            meta = json.loads(meta_file.read_text()) if meta_file.exists() else {}
        except (json.JSONDecodeError, OSError):
            continue
        score = float(meta.get("score", 0.0))
        exemplars.append(Exemplar(
            schema=schema, score=score, meta=meta,
            domain=domain, page_type=page_type, file_stem=schema_file.stem,
        ))
    exemplars.sort(key=lambda e: e.score, reverse=True)
    return exemplars


def load_exemplars(
    domain: str,
    page_type: str,
    *,
    register: str = "default",
    limit: int = 2,
) -> list[Exemplar]:
    """Load up to `limit` exemplars for the given (register, domain, page_type) cell.

    Resolution order (first non-empty cell wins):
      1. backend/reference_pages/<register>/<domain>/<page_type>/
      2. backend/reference_pages/<register>/general/<page_type>/
      3. backend/reference_pages/default/<domain>/<page_type>/
      4. backend/reference_pages/default/general/<page_type>/
      5. backend/reference_pages/<domain>/<page_type>/        (legacy Phase 14 path)
      6. backend/reference_pages/general/<page_type>/          (legacy Phase 14 path)

    Returns empty list if no cell exists or is empty.
    """
    if not domain or not page_type:
        return []

    candidates = [
        (_BANK_ROOT / register / domain / page_type, domain),
        (_BANK_ROOT / register / "general" / page_type, "general"),
        (_BANK_ROOT / "default" / domain / page_type, domain),
        (_BANK_ROOT / "default" / "general" / page_type, "general"),
        (_BANK_ROOT / domain / page_type, domain),          # legacy
        (_BANK_ROOT / "general" / page_type, "general"),    # legacy
    ]

    for cell, cell_domain in candidates:
        if not cell.exists() or not cell.is_dir():
            continue
        exemplars = _load_from_cell(cell, cell_domain, page_type)
        if exemplars:
            return exemplars[:limit]
    return []


def available_cells() -> list[tuple[str, str]]:
    """List every (domain, page_type) cell that has at least one exemplar.

    Walks only the legacy flat layout (<domain>/<page_type>/) and the
    default/ sub-tree. Returns (domain, page_type) tuples.
    Use available_cells_by_register() for the full register-keyed listing.
    """
    if not _BANK_ROOT.exists():
        return []
    cells: list[tuple[str, str]] = []
    # Registers that use the nested <register>/<domain>/<page_type>/ layout
    _KNOWN_REGISTERS = {"default", "workday", "linear", "stripe", "notion", "figma"}
    for domain_dir in sorted(_BANK_ROOT.iterdir()):
        if not domain_dir.is_dir() or domain_dir.name.startswith("."):
            continue
        # Skip register-keyed subdirs — they're walked by available_cells_by_register()
        if domain_dir.name in _KNOWN_REGISTERS:
            continue
        for type_dir in sorted(domain_dir.iterdir()):
            if not type_dir.is_dir():
                continue
            if any(type_dir.glob("exemplar_*.json")):
                cells.append((domain_dir.name, type_dir.name))
    return cells


def available_cells_by_register() -> list[tuple[str, str, str]]:
    """List every (register, domain, page_type) cell that has at least one exemplar.

    Returns tuples of (register, domain, page_type).
    """
    if not _BANK_ROOT.exists():
        return []
    _KNOWN_REGISTERS = {"default", "workday", "linear", "stripe", "notion", "figma"}
    results: list[tuple[str, str, str]] = []
    for register_dir in sorted(_BANK_ROOT.iterdir()):
        if not register_dir.is_dir() or register_dir.name not in _KNOWN_REGISTERS:
            continue
        for domain_dir in sorted(register_dir.iterdir()):
            if not domain_dir.is_dir() or domain_dir.name.startswith("."):
                continue
            for type_dir in sorted(domain_dir.iterdir()):
                if not type_dir.is_dir():
                    continue
                if any(type_dir.glob("exemplar_*.json")):
                    results.append((register_dir.name, domain_dir.name, type_dir.name))
    return results


def render_exemplars_block(exemplars: list[Exemplar]) -> str:
    """Format a list of exemplars as a prompt block for schema-agent injection."""
    if not exemplars:
        return ""
    lines = [
        "## REFERENCE EXEMPLARS",
        "These are top-tier examples for this domain + page type.",
        "Match this level of polish, structure, and information density. Adapt",
        "the entities and content to this project's brief.",
        "",
    ]
    for i, e in enumerate(exemplars, start=1):
        lines.append(f"### Exemplar {i} (score {e.score:.1f})")
        lines.append("```json")
        lines.append(json.dumps(e.schema, indent=2))
        lines.append("```")
        lines.append("")
    return "\n".join(lines)
