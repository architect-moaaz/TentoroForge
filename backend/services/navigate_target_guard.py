"""Post-gen guard: every button/link `navigate` prop points at a real route.

Root cause this addresses: schema-authored nodes frequently carry
`props.navigate: "/some-route"` that the planner intended but that no page
under `plan.pages[]` actually exposes. The click "does nothing" at runtime
because the target 404s or the frontend has no route registered — B-022.8's
"View details is irresponsive" symptom class. `nav_route_reconcile_guard`
already handles the shell / nav-flow surface; this pass covers the schema-
node surface (row actions, button navigates, link hrefs).

Rules for correctness (not-a-bandaid):
  * Structural — reads only plan.pages routes + schema node bindings.
  * Deterministic — no LLM.
  * Additive/repair-only — never removes user-authored labels. When the
    target doesn't match, tries a nearest-match rewrite; if no reasonable
    match, marks the node with `data-nav-warn="broken"` so the UI still
    shows the button but the mismatch is observable.
  * Skips dynamic bindings — a navigate value containing `{{...}}` is
    interpolated at runtime, so we can't decide statically.
  * Idempotent — running twice is a no-op.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_TEMPLATE_RE = re.compile(r"\{\{[^}]+\}\}")


# --------------------------------------------------------------------------
# helpers                                                                    #
# --------------------------------------------------------------------------

def _load_plan(root: Path) -> dict:
    for c in (root / "src" / "contracts" / "plan.json", root / "contracts" / "plan.json"):
        if c.exists():
            try:
                return json.loads(c.read_text(encoding="utf-8"))
            except Exception:
                logger.exception("navigate_target_guard: failed to read %s", c)
    return {}


def _known_routes(plan: dict) -> set[str]:
    out: set[str] = set()
    for p in plan.get("pages") or []:
        if isinstance(p, dict):
            r = str(p.get("route") or "").strip()
            if r:
                out.add(_canon_route(r))
    return out


def _canon_route(route: str) -> str:
    """Canonicalise for comparison: strip trailing slash, lowercase."""
    r = (route or "").strip().rstrip("/") or "/"
    return r.lower()


def _has_dynamic_binding(route: str) -> bool:
    """A navigate value like `/plants/{{row.id}}` shouldn't be treated as a
    static string. We only static-check literal routes."""
    return bool(_TEMPLATE_RE.search(route))


def _iter_nodes(root: Any):
    if isinstance(root, dict):
        yield root
        for v in root.values():
            yield from _iter_nodes(v)
    elif isinstance(root, list):
        for item in root:
            yield from _iter_nodes(item)


def _target_pattern_matches(nav: str, known: set[str]) -> bool:
    """True if `nav` matches a known route directly, OR matches a known
    dynamic-segment route pattern (e.g. `/plants/abc` matches `/plants/[id]`)."""
    canon = _canon_route(nav)
    if canon in known:
        return True
    parts = canon.strip("/").split("/")
    for k in known:
        kparts = k.strip("/").split("/")
        if len(kparts) != len(parts):
            continue
        ok = True
        for a, b in zip(parts, kparts):
            if b.startswith("[") and b.endswith("]"):
                continue  # dynamic segment matches anything
            if a != b:
                ok = False
                break
        if ok:
            return True
    return False


def _nearest_match(nav: str, known: set[str]) -> str | None:
    """Try to find a known route that's a strict prefix or one-segment
    variant of `nav`. Conservative — only returns when the match feels
    obvious."""
    canon = _canon_route(nav)
    parts = canon.strip("/").split("/")
    if not parts or parts == [""]:
        return None
    # Strip the last segment(s) until we hit a known route.
    for i in range(len(parts) - 1, 0, -1):
        prefix = "/" + "/".join(parts[:i])
        if _target_pattern_matches(prefix, known):
            return prefix
    return None


# --------------------------------------------------------------------------
# main pass                                                                  #
# --------------------------------------------------------------------------

# Keys that carry a navigation target.
_NAVIGATE_KEYS = ("navigate", "href", "url", "to", "linkTo")


def _fix_node(node: dict, known: set[str], result: dict) -> bool:
    """Walk one node's props for a navigate-shaped value. Returns True if the
    node was mutated."""
    if not isinstance(node, dict):
        return False
    props = node.get("props")
    if not isinstance(props, dict):
        return False
    changed = False
    for key in _NAVIGATE_KEYS:
        if key not in props:
            continue
        val = props[key]
        if not isinstance(val, str) or not val.strip():
            continue
        if val.startswith(("mailto:", "tel:", "http://", "https://", "#")):
            continue
        if _has_dynamic_binding(val):
            continue
        if _target_pattern_matches(val, known):
            continue
        # Broken target — try a nearest-match repair.
        near = _nearest_match(val, known)
        if near:
            props[key] = near
            result.setdefault("repaired", []).append({"was": val, "now": near, "type": node.get("type")})
            changed = True
        else:
            # Mark the node so downstream tooling / dev-mode can see the
            # broken target. We don't strip the label — dead buttons that
            # look-alive-but-inert are strictly better than layout gaps.
            props.setdefault("data-nav-warn", "broken")
            result.setdefault("marked", []).append({"target": val, "type": node.get("type")})
            changed = True
    return changed


def apply_navigate_target_guard(output_dir: str) -> dict:
    root = Path(output_dir)
    plan = _load_plan(root)
    known = _known_routes(plan)
    result: dict = {"files_scanned": 0, "files_touched": [], "repaired": [], "marked": []}
    if not known:
        return result
    schemas_dir = root / "src" / "schemas"
    if not schemas_dir.exists():
        return result

    for schema_path in sorted(schemas_dir.glob("*.json")):
        result["files_scanned"] += 1
        try:
            doc = json.loads(schema_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        touched = False
        for node in _iter_nodes(doc):
            if _fix_node(node, known, result):
                touched = True
        if touched:
            try:
                schema_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
                result["files_touched"].append(schema_path.name)
            except Exception:
                logger.exception("navigate_target_guard: failed to write %s", schema_path)

    return result
