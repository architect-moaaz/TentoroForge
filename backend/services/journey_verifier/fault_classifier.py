"""V&F 2.0 Layer A — fault classifier (Milestone M1).

Pure functions, zero I/O. Given a raw fault dict (the shape produced by
the forge-verify runner: ``{"interaction": {...}, "evidence": {...}, ...}``),
return a :class:`ClassifiedFault` labelled with a canonical class name and
the seam a downstream dispatcher should route to.

The 10-class taxonomy tracks the spec (docs/superpowers/specs/
2026-08-06-vf-self-healing.md §"Architecture — three new layers /
Layer A"). Priority order is critical — many faults present overlapping
signals (a 500 with a drizzle-shaped stack; a 200 with both a network 500
AND a React #31 in the console) — and the first-match walk resolves them
to the highest-priority class.

Priority order (highest first):
  1. Playwright hard timeouts      → page-unresponsive     (smith:render)
  2. 500 with drizzle/unknown-table→ db-schema-mismatch    (deterministic:db-migrate)
  3. 500 generic                    → render-error          (smith:render)
  4. 404 with route IN registry     → catch-all-router-broken (deterministic:router-regen)
  5. 404 with route NOT in registry → missing-page          (deterministic:add-page)
  6. 200 with network 5xx           → data-fetch-failure    (smith:data-fetch)
  7. 200 with React error #31       → binding-crash         (smith:binding)
  8. 200 empty list                 → list-empty-data       (deterministic:rewire-datasource)
  9. 200 form with no submit target → form-not-wired        (deterministic:orphan-wiring)
 10. 401 on an auth flow            → auth-broken           (deterministic:auth-seed)

Everything else → ``class_name="unknown"``, ``seam="residual"``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable


# ── Public dataclass ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ClassifiedFault:
    """One classified fault. See the spec's "Interfaces" section."""

    interaction_id: str
    route: str
    class_name: str            # e.g. "render-error"; "unknown" if no match
    seam: str                  # e.g. "deterministic:add-page"; "residual" fallback
    evidence_slice: str        # short human-readable summary
    needed_context: list[str] = field(default_factory=list)
    raw: dict[str, Any] | None = None  # original fault for the handler


# ── Regex signatures ────────────────────────────────────────────────────────

_RE_UNKNOWN_TABLE = re.compile(
    r"(unknown table|relation \"[^\"]+\" does not exist|does not exist.*relation|"
    r"drizzle.*(no such table|does not exist)|column .*does not exist)",
    re.IGNORECASE,
)
_RE_REACT_31 = re.compile(r"(Minified React error #31|React error.*31\b)", re.IGNORECASE)
_RE_FAILED_TO_LOAD_5XX = re.compile(
    r"Failed to load resource.*(?:status of )?5\d\d",
    re.IGNORECASE,
)


# ── Public entry ────────────────────────────────────────────────────────────


def classify_fault(
    fault: dict[str, Any],
    *,
    route_registry: Iterable[str] | None = None,
) -> ClassifiedFault:
    """Classify a raw fault dict into a canonical class + seam.

    :param fault: FaultRaw-shaped dict from the runner. Reads
        ``interaction`` (id/route/kind/…) and ``evidence`` (status,
        body_excerpt, console, network_log, stack_trace, timed_out,
        rendered_widget_count).
    :param route_registry: optional set/iterable of routes the app
        knows about. Used to distinguish ``missing-page`` (404 and the
        route isn't registered) from ``catch-all-router-broken`` (404
        but the route IS registered — dispatcher is broken). When None,
        every 404 defaults to ``missing-page`` — the safer bet, since
        recreating a page is idempotent and cheap.
    """
    interaction = fault.get("interaction") or {}
    evidence = fault.get("evidence") or {}
    interaction_id = str(
        interaction.get("id")
        or fault.get("interaction_id")
        or fault.get("id")
        or "?"
    )
    route = str(interaction.get("route") or fault.get("route") or "")
    kind = str(interaction.get("kind") or "")
    status = evidence.get("status")
    body = str(evidence.get("body_excerpt") or "")
    stack = str(evidence.get("stack_trace") or "")
    console = evidence.get("console") or []
    network = evidence.get("network_log") or []
    timed_out = bool(evidence.get("timed_out"))
    widget_count = evidence.get("rendered_widget_count")
    rows_returned = evidence.get("rows_returned")

    body_and_stack = f"{stack}\n{body}"

    # ── 1. Timeout ─────────────────────────────────────────────────────────
    if timed_out:
        return _make(
            interaction_id, route, "page-unresponsive", "smith:render",
            _slice(evidence, extra="TIMED OUT"),
            ["page_code", "page_schema", "console"],
            fault,
        )

    # ── 2. 500 with drizzle / unknown-table ────────────────────────────────
    if status == 500 and _RE_UNKNOWN_TABLE.search(body_and_stack):
        return _make(
            interaction_id, route, "db-schema-mismatch", "deterministic:db-migrate",
            _slice(evidence, extra="drizzle: unknown table / column"),
            ["schema", "migrations"],
            fault,
        )

    # ── 3. 500 generic ─────────────────────────────────────────────────────
    if status == 500:
        return _make(
            interaction_id, route, "render-error", "smith:render",
            _slice(evidence),
            ["page_code", "page_schema", "stack"],
            fault,
        )

    # ── 4/5. 404 → router vs missing page ──────────────────────────────────
    if status == 404:
        registry = {r for r in (route_registry or ())}
        if route and registry and route in registry:
            return _make(
                interaction_id, route, "catch-all-router-broken",
                "deterministic:router-regen",
                _slice(evidence, extra=f"route `{route}` present in registry"),
                ["routes_registry"],
                fault,
            )
        # No registry supplied OR route not in it → assume the schema is
        # missing and let add_page recreate it.
        return _make(
            interaction_id, route, "missing-page", "deterministic:add-page",
            _slice(evidence, extra=f"route `{route}` missing"),
            ["plan", "route"],
            fault,
        )

    # ── 10. 401 auth (checked early — status 401 dominates 200-family). ────
    # Placed here (not after the 200 block) so a 401 with an incidental
    # 200 GET later in the network log still classifies as auth-broken.
    if status == 401:
        return _make(
            interaction_id, route, "auth-broken", "deterministic:auth-seed",
            _slice(evidence, extra="HTTP 401 on auth flow"),
            ["seed"],
            fault,
        )

    # From here on we're in the status-200 (or unset) family.

    # ── 6. 200 + network 5xx (data-fetch failure). Console signal OR
    #      any network log entry with 5xx status counts. ─────────────────
    if _has_network_5xx(network) or _console_matches(console, _RE_FAILED_TO_LOAD_5XX):
        return _make(
            interaction_id, route, "data-fetch-failure", "smith:data-fetch",
            _slice(evidence, extra="200 render but data fetch 5xx"),
            ["page_schema", "network", "data_source"],
            fault,
        )

    # ── 7. 200 + React error #31 (binding crash) ──────────────────────────
    if _console_matches(console, _RE_REACT_31):
        return _make(
            interaction_id, route, "binding-crash", "smith:binding",
            _slice(evidence, extra="React error #31 (object rendered as child)"),
            ["page_schema", "page_code", "console"],
            fault,
        )

    # ── 8. 200 + empty list (rendered_widget_count == 0 OR rows == 0)  ─────
    if kind == "list" and (widget_count == 0 or rows_returned == 0):
        return _make(
            interaction_id, route, "list-empty-data",
            "deterministic:rewire-datasource",
            _slice(evidence, extra="list rendered zero rows"),
            ["page_schema", "registry"],
            fault,
        )

    # ── 9. 200 + form with no submit target (form-not-wired) ──────────────
    if kind == "form":
        submit = (interaction.get("submit") or {})
        submit_kind = str(submit.get("kind") or "").lower()
        if submit_kind in ("", "none") and not _has_workflow_post(network):
            return _make(
                interaction_id, route, "form-not-wired",
                "deterministic:orphan-wiring",
                _slice(evidence, extra="form submit dispatches nothing"),
                ["workflows", "form_schema"],
                fault,
            )

    # ── Fallback: unknown class → residual (not dispatched). ──────────────
    return _make(
        interaction_id, route, "unknown", "residual",
        _slice(evidence, extra="no matching pattern"),
        [],
        fault,
    )


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make(
    interaction_id: str,
    route: str,
    class_name: str,
    seam: str,
    evidence_slice: str,
    needed_context: list[str],
    raw: dict[str, Any],
) -> ClassifiedFault:
    return ClassifiedFault(
        interaction_id=interaction_id,
        route=route,
        class_name=class_name,
        seam=seam,
        evidence_slice=evidence_slice,
        needed_context=list(needed_context),
        raw=raw,
    )


def _slice(evidence: dict[str, Any], *, extra: str | None = None) -> str:
    """Short, human-readable one-liner summarising the evidence.

    Mirrors ``verify_summary._format_faults`` but constrained to the
    signals the classifier looked at. Never raises."""
    parts: list[str] = []
    if extra:
        parts.append(extra)
    status = evidence.get("status")
    if status is not None:
        parts.append(f"HTTP {status}")
    stack = str(evidence.get("stack_trace") or "").strip()
    if stack:
        first = stack.splitlines()[0].strip()
        parts.append(f"stack: {first[:180]}")
    elif evidence.get("body_excerpt"):
        parts.append(f"body: {str(evidence['body_excerpt'])[:180]}")
    console = evidence.get("console") or []
    err_texts = [
        str(c.get("text") or "") for c in console
        if str(c.get("level") or "").lower() in ("error", "err")
    ][:2]
    if err_texts:
        parts.append("console: " + " | ".join(t[:100] for t in err_texts))
    return " · ".join(p for p in parts if p) or "(no evidence)"


def _console_matches(console: list[Any], pattern: re.Pattern[str]) -> bool:
    for entry in console or []:
        text = ""
        if isinstance(entry, dict):
            text = str(entry.get("text") or "")
        else:
            text = str(entry)
        if pattern.search(text):
            return True
    return False


def _has_network_5xx(network: list[Any]) -> bool:
    for req in network or []:
        if not isinstance(req, dict):
            continue
        try:
            status = int(req.get("status") or 0)
        except (TypeError, ValueError):
            continue
        if 500 <= status < 600:
            return True
    return False


def _has_workflow_post(network: list[Any]) -> bool:
    for req in network or []:
        if not isinstance(req, dict):
            continue
        method = str(req.get("method") or "").upper()
        url = str(req.get("url") or "")
        if method == "POST" and "/api/workflows/" in url:
            return True
    return False
