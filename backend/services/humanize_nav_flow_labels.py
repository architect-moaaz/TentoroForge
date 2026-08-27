"""Post-gen: humanize raw class-name labels inside ``src/contracts/nav-flow.json``.

The persona sub-nav row (rendered by ``PersonaChrome`` from
``nav-flow.personas[].screens[].label``) used to render raw page
class-name IDs like ``MemberSchedulePage`` because upstream label
authors (both LLM planners and legacy nav-flow emitters) sometimes
pass the page's Python class name straight through.

This pass rewrites any label matching ``^[A-Z][a-zA-Z0-9]*Page$``
using the route-derived humanizer:

    MemberSchedulePage @ /schedule           → Schedule
    MemberBookingsPage @ /member/bookings    → Bookings
    InstructorAvailabilityPage @ /instructor/availability → Availability

Also runs over ``pages[].title`` and ``personas[].jobs[].label`` for
symmetry — anywhere in nav-flow the same raw-classname leak could
show up in future emitters.

Idempotent: a second pass over already-humanized labels is a no-op.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# A label the plan author never intended a user to read: the page's
# Python class name, e.g. ``MemberSchedulePage``. Anything matching this
# is rewritten to a route-derived humanized label.
_RAW_CLASSNAME_RE = re.compile(r"^[A-Z][a-zA-Z0-9]*Page$")

# Route segments that are dynamic params, not meaningful nouns: Next.js
# ``[id]`` / ``[slug]`` and Express/FastAPI ``:param``, plus catch-all
# ``...rest``. Skipped when picking the last meaningful token from a
# route.
_PARAM_SEGMENT_RE = re.compile(r"^(\[.*\]|:.+|\.{3}.*)$")

# Common all-lowercase acronyms that should render uppercase. Small on
# purpose — a false-positive uppercase mid-word is more jarring than a
# missing acronym.
_ACRONYMS = {"id", "url", "api", "kpi", "sla", "faq", "ip", "ui", "ux",
             "pdf", "csv", "sql", "http", "https", "ssn", "vip"}


def _humanize_route(route: str) -> str:
    """Turn a URL route into a human label using its last meaningful segment.

    Rules:
      1. Drop query string / fragment (defensive).
      2. Walk segments from the end; skip dynamic ``[id]`` / ``:slug``
         / ``...rest`` segments.
      3. Replace ``-``/``_`` with spaces, title-case each word,
         uppercase common acronyms.
      4. ``/`` or empty → ``"Home"``.

    Examples::

        _humanize_route("/schedule")                        == "Schedule"
        _humanize_route("/member/bookings")                 == "Bookings"
        _humanize_route("/instructor/sessions/[id]/roster") == "Roster"
        _humanize_route("/admin/dashboard")                 == "Dashboard"
        _humanize_route("/kpis/api-usage")                  == "API Usage"
    """
    if not route:
        return "Home"
    r = route.split("?", 1)[0].split("#", 1)[0]
    segments = [s for s in r.split("/") if s]
    if not segments:
        return "Home"
    token = None
    for seg in reversed(segments):
        if not _PARAM_SEGMENT_RE.match(seg):
            token = seg
            break
    if token is None:
        return "Home"
    words: list[str] = []
    for w in re.split(r"[-_]+", token):
        if not w:
            continue
        if w.lower() in _ACRONYMS:
            words.append(w.upper())
        else:
            words.append(w[:1].upper() + w[1:].lower())
    return " ".join(words) or "Home"


def _looks_like_raw_classname(s: Any) -> bool:
    return isinstance(s, str) and bool(_RAW_CLASSNAME_RE.match(s))


def _humanized_or_none(label: Any, route: Any) -> str | None:
    """Return a humanized replacement for ``label`` when it's a raw
    class-name; otherwise ``None`` (leave the label alone).

    The replacement is derived from ``route`` when ``route`` yields a
    meaningful token; otherwise a fallback humanization of the label
    itself (stripping the trailing "Page" and camelCase-splitting).
    """
    if not _looks_like_raw_classname(label):
        return None
    if isinstance(route, str) and route:
        candidate = _humanize_route(route)
        if candidate and candidate != "Home":
            return candidate
    # Last resort: strip the "Page" suffix and camelCase-split the rest.
    stripped = re.sub(r"Page$", "", str(label))
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", stripped)
    return spaced.strip() or "Home"


def _repair(nav_flow: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Return the (mutated) nav-flow + a count of labels rewritten.

    Rewrites raw class-name labels in three locations:
      * ``pages[].title``  (source of ``PersonaChrome`` fallback labels)
      * ``personas[].screens[].label`` (the persona sub-nav pills)
      * ``personas[].jobs[].label``    (the persona job groupings)
    """
    changed = 0

    for page in (nav_flow.get("pages") or []):
        if not isinstance(page, dict):
            continue
        title = page.get("title")
        replacement = _humanized_or_none(title, page.get("route"))
        if replacement is not None:
            page["title"] = replacement
            changed += 1

    for persona in (nav_flow.get("personas") or []):
        if not isinstance(persona, dict):
            continue
        for screen in (persona.get("screens") or []):
            if not isinstance(screen, dict):
                continue
            replacement = _humanized_or_none(screen.get("label"), screen.get("route"))
            if replacement is not None:
                screen["label"] = replacement
                changed += 1
        for job in (persona.get("jobs") or []):
            if not isinstance(job, dict):
                continue
            replacement = _humanized_or_none(job.get("label"), job.get("route"))
            if replacement is not None:
                job["label"] = replacement
                changed += 1

    return nav_flow, changed


def run(output_dir: str) -> dict[str, int]:
    """Read ``<output_dir>/src/contracts/nav-flow.json``, rewrite any raw
    class-name labels, and write back if any changed.

    Returns ``{"rewritten": N}``. Missing / malformed nav-flow.json is a
    no-op (returns zero).
    """
    root = Path(output_dir)
    nf_path = root / "src" / "contracts" / "nav-flow.json"
    if not nf_path.exists():
        return {"rewritten": 0}
    try:
        nav_flow = json.loads(nf_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.warning("humanize_nav_flow_labels: failed to read %s: %s", nf_path, e)
        return {"rewritten": 0}
    _, changed = _repair(nav_flow)
    if changed:
        try:
            nf_path.write_text(json.dumps(nav_flow, indent=2), encoding="utf-8")
            logger.info(
                "humanize_nav_flow_labels: rewrote %d raw class-name label(s) in %s",
                changed, nf_path.relative_to(root),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("humanize_nav_flow_labels: failed to write %s: %s", nf_path, e)
            return {"rewritten": 0}
    return {"rewritten": changed}
