"""V&F 2.0 Layer C — fault context builder (Milestone M2).

Pure builder: given a :class:`ClassifiedFault` + the on-disk
``output_dir``, assemble a :class:`SmithContext` carrying everything
Smith needs to reason about the fault. No LLM calls, no state mutation.
Reading files from ``output_dir`` is fine (it's the only way to get the
page schema/code); no writes.

The context caps every payload (symptom, page code, page schema, console,
network) so a single fault's prompt stays under a couple KB —
prompt-size discipline matters when the whole-run budget is small.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from services.journey_verifier.fault_classifier import ClassifiedFault


# Prompt-size caps. Kept small on purpose — Smith has its own context
# window budget and we're paying for every KB.
_SYMPTOM_MAX = 2000
_PAGE_SCHEMA_MAX = 2000
_PAGE_CODE_MAX = 3000
_CONSOLE_MAX = 10
_NETWORK_MAX = 10


@dataclass(frozen=True)
class SmithContext:
    """Curated slice of the app + evidence for one classified fault."""

    symptom: str                      # stack trace, trimmed to ~2000 chars
    route: str
    page_schema: str | None           # JSON.dumps of the page's schema.json
    page_code: str | None             # contents of the page's .tsx
    console_errors: list[dict] = field(default_factory=list)   # up to 10
    network_failures: list[dict] = field(default_factory=list) # up to 10, status>=400
    related_entities: list[str] = field(default_factory=list)
    recent_edits: list[str] = field(default_factory=list)      # git log lines
    available_tools: list[str] = field(default_factory=list)   # tool subset


# ── Public entry ────────────────────────────────────────────────────────────


def build_fault_context(
    fault: ClassifiedFault,
    output_dir: Path | str,
    *,
    tool_subset: list[str] | None = None,
) -> SmithContext:
    """Assemble a :class:`SmithContext` for ``fault`` from files under
    ``output_dir``.

    Pure w.r.t. inputs — reads from disk but does not write. When
    ``tool_subset`` is None, looks it up via
    ``smith_autofix.TOOL_SUBSETS[fault.seam]`` (best-effort; empty list
    if smith_autofix is unavailable). Pass an explicit list to override.
    """
    out = Path(output_dir)
    raw = fault.raw if isinstance(fault.raw, dict) else {}
    evidence = raw.get("evidence") or {}

    symptom = _extract_symptom(evidence)
    console_errors = _filter_console_errors(evidence.get("console") or [])
    network_failures = _filter_network_failures(evidence.get("network_log") or [])
    page_schema = _read_page_schema(out, fault.route)
    page_code = _read_page_code(out, fault.route)
    related_entities = infer_entities_from_route(fault.route, out)
    recent_edits = git_log_since_last_verify(out)

    if tool_subset is None:
        tool_subset = _lookup_tool_subset(fault.seam)

    return SmithContext(
        symptom=symptom,
        route=fault.route or "",
        page_schema=page_schema,
        page_code=page_code,
        console_errors=console_errors,
        network_failures=network_failures,
        related_entities=related_entities,
        recent_edits=recent_edits,
        available_tools=list(tool_subset or []),
    )


# ── Helpers ─────────────────────────────────────────────────────────────────


def _lookup_tool_subset(seam: str) -> list[str]:
    """Lazy import to avoid a module-load-time cycle with smith_autofix."""
    try:
        from services.journey_verifier.smith_autofix import TOOL_SUBSETS
    except Exception:  # noqa: BLE001
        return []
    return list(TOOL_SUBSETS.get(seam, []))


def _extract_symptom(evidence: dict[str, Any]) -> str:
    """Best-effort human-readable summary — stack first, then body, then status."""
    stack = str(evidence.get("stack_trace") or "").strip()
    if stack:
        return stack[:_SYMPTOM_MAX]
    body = str(evidence.get("body_excerpt") or "").strip()
    if body:
        return body[:_SYMPTOM_MAX]
    status = evidence.get("status")
    if status is not None:
        return f"HTTP {status}"
    return "(no evidence)"


def _filter_console_errors(console: list[Any]) -> list[dict]:
    """Keep only err/error-level entries, up to _CONSOLE_MAX."""
    out: list[dict] = []
    for entry in console:
        if not isinstance(entry, dict):
            continue
        level = str(entry.get("level") or "").lower()
        if level not in ("err", "error"):
            continue
        out.append(entry)
        if len(out) >= _CONSOLE_MAX:
            break
    return out


def _filter_network_failures(network: list[Any]) -> list[dict]:
    """Keep only entries with numeric status >= 400, up to _NETWORK_MAX."""
    out: list[dict] = []
    for entry in network:
        if not isinstance(entry, dict):
            continue
        try:
            status = int(entry.get("status") or 0)
        except (TypeError, ValueError):
            continue
        if status < 400:
            continue
        out.append(entry)
        if len(out) >= _NETWORK_MAX:
            break
    return out


def _route_to_slug(route: str) -> str:
    """Mirror ``route_slug.slugify_route`` w/o its strict validation
    (we're only reading files here, not writing them)."""
    r = (route or "").strip()
    if not r or r == "/":
        return "home"
    return r.lstrip("/")


def _read_page_schema(output_dir: Path, route: str) -> str | None:
    """Return JSON text of the page's schema.json, trimmed. None if missing.

    Tries ``src/schemas/<slug>.json`` first (fast path — that's the
    naming convention the pipeline uses), then falls back to scanning
    the schemas tree for a file whose top-level ``route`` matches.
    """
    if not route:
        return None
    sdir = output_dir / "src" / "schemas"
    if not sdir.is_dir():
        return None
    slug = _route_to_slug(route)
    naive = sdir / (slug + ".json")
    if naive.is_file():
        try:
            return naive.read_text(encoding="utf-8")[:_PAGE_SCHEMA_MAX]
        except OSError:
            return None
    try:
        for fp in sorted(sdir.rglob("*.json")):
            try:
                doc = json.loads(fp.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(doc, dict) and str(doc.get("route") or "") == route:
                try:
                    return fp.read_text(encoding="utf-8")[:_PAGE_SCHEMA_MAX]
                except OSError:
                    return None
    except Exception:  # noqa: BLE001
        return None
    return None


def _read_page_code(output_dir: Path, route: str) -> str | None:
    """Return the .tsx source of the page component, trimmed. None if missing.

    Generated apps typically use a catch-all ``[...slug]`` route, so a
    literal ``src/app/<route>/page.tsx`` won't usually exist. We still
    try both the literal path AND the ``(dashboard)/<route>/page.tsx``
    group-wrapped variant because a few app-foundation pages
    (auth pages, tasks) are emitted as concrete routes.
    """
    if not route:
        return None
    rel = route.lstrip("/") or ""
    candidates = [
        output_dir / "src" / "app" / rel / "page.tsx",
        output_dir / "src" / "app" / "(dashboard)" / rel / "page.tsx",
    ]
    for cand in candidates:
        if cand.is_file():
            try:
                return cand.read_text(encoding="utf-8")[:_PAGE_CODE_MAX]
            except OSError:
                continue
    return None


def infer_entities_from_route(
    route: str,
    output_dir: Path | str | None = None,
) -> list[str]:
    """Best-effort entity slugs from the route path.

    Splits on '/', drops bracketed segments (``[id]``) and the
    ``new``/``edit`` markers. When ``output_dir`` is given and
    ``contracts/plan.json`` exists, cross-checks the extracted names
    against plan entities — if none match, falls back to the raw
    extraction (better to over-report than under-report for Smith's
    context).
    """
    if not route:
        return []
    parts = [
        p for p in route.split("/")
        if p and not p.startswith("[") and p not in ("new", "edit")
    ]
    if not parts:
        return []
    # dedupe, preserve first-seen order
    entities = list(dict.fromkeys(parts))
    if output_dir is None:
        return entities
    plan_entities = _read_plan_entities(Path(output_dir))
    if not plan_entities:
        return entities
    known = {e.lower() for e in plan_entities}
    filtered = [e for e in entities if e.lower() in known]
    return filtered or entities


def _read_plan_entities(output_dir: Path) -> list[str]:
    """Extract entity names from ``contracts/plan.json``. [] on any error."""
    plan = output_dir / "contracts" / "plan.json"
    if not plan.is_file():
        return []
    try:
        doc = json.loads(plan.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    ents = doc.get("entities") if isinstance(doc, dict) else None
    if not isinstance(ents, list):
        return []
    names: list[str] = []
    for e in ents:
        if isinstance(e, dict):
            n = e.get("name") or e.get("slug") or e.get("id")
            if isinstance(n, str) and n:
                names.append(n)
        elif isinstance(e, str):
            names.append(e)
    return names


def git_log_since_last_verify(
    output_dir: Path | str,
    limit: int = 20,
) -> list[str]:
    """Best-effort ``git log --oneline -N`` in output_dir.

    Returns [] on any failure (dir isn't a repo, git unavailable, etc.)
    so callers can treat it as "no recent-edits signal available".
    """
    try:
        r = subprocess.run(
            ["git", "-C", str(output_dir), "log", "--oneline", f"-{limit}"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return []
        return [ln for ln in (r.stdout or "").splitlines() if ln.strip()]
    except (OSError, subprocess.TimeoutExpired):
        return []
