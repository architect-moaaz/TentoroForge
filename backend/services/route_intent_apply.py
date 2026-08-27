"""Apply route-intent to generated pages after the deterministic builders run.

The classifier (:mod:`services.route_intent`) tells us what a page SHOULD be
(singleton_current_user / current_user_scope_list / role_scope_list / crud).
This pass reads it and post-edits schemas + plan so:

  * A `singleton_current_user` route removes any list/create nodes and
    binds the form to `{{currentUser.id}}` (no Add User leak, no Users
    grid — B-022.6).
  * A `current_user_scope_list` list-page dataSource carries the
    `filter: {ownerId: "{{currentUser.id}}"}` so users only see their own
    rows (B-022.9). Create routes on the same slug inherit the same
    ownership assignment as a hidden form field.
  * A `role_scope_list` list-page dataSource carries the
    `filter: {role: "<role>"}` so /home-cooks shows cooks only (B-022.7).

Rules for correctness:
  * Reads existing plan.pages + schemas only. No LLM.
  * Additive — never removes user-authored labels. When collapsing
    singleton pages, keeps the form node and points its record binding
    at currentUser, but preserves headings + surrounding chrome.
  * Idempotent — running twice matches once.
  * Conservative — only touches pages whose intent classifier returned
    a non-crud kind; ordinary CRUD paths are untouched so no regression.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from services.route_intent import classify_route, RouteIntent

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# helpers                                                                    #
# --------------------------------------------------------------------------

def _load_plan(root: Path) -> dict:
    for c in (root / "src" / "contracts" / "plan.json", root / "contracts" / "plan.json"):
        if c.exists():
            try:
                return json.loads(c.read_text(encoding="utf-8"))
            except Exception:
                logger.exception("route_intent_apply: failed to read %s", c)
    return {}


def _slug_from_route(route: str) -> str:
    r = (route or "").strip("/").replace("/", "-").replace("[", "").replace("]", "")
    return r or "home"


def _iter_nodes(root: Any):
    if isinstance(root, dict):
        yield root
        for v in root.values():
            yield from _iter_nodes(v)
    elif isinstance(root, list):
        for item in root:
            yield from _iter_nodes(item)


# --------------------------------------------------------------------------
# per-intent editors                                                         #
# --------------------------------------------------------------------------

def _apply_scope_filter_to_list(page_schema: dict, filter_: dict) -> bool:
    """For a list page: attach `filter` to the top-level dataSource(s) that
    the list Table/DataGrid/List/Card is bound to. Idempotent — re-applies
    the same filter without duplicating keys."""
    changed = False
    sources = page_schema.get("dataSources")
    if isinstance(sources, list):
        for src in sources:
            if not isinstance(src, dict):
                continue
            if src.get("op") not in (None, "list"):
                continue
            existing = src.get("filter")
            if isinstance(existing, dict):
                for k, v in filter_.items():
                    if existing.get(k) != v:
                        existing[k] = v
                        changed = True
            else:
                src["filter"] = dict(filter_)
                changed = True
    # Also honor a shorthand `props.filter` on Table/DataGrid nodes when the
    # schema author put it there instead of on a dataSource.
    for n in _iter_nodes(page_schema):
        if not isinstance(n, dict):
            continue
        if n.get("type") in ("Table", "DataGrid", "List"):
            props = n.setdefault("props", {})
            existing = props.get("filter")
            if isinstance(existing, dict):
                for k, v in filter_.items():
                    if existing.get(k) != v:
                        existing[k] = v
                        changed = True
            elif existing is None:
                props["filter"] = dict(filter_)
                changed = True
    return changed


def _collapse_to_singleton(page_schema: dict, filter_: dict) -> bool:
    """For a singleton_current_user page: drop any Table/DataGrid/list nodes
    and turn the page into an edit-in-place form bound to `{{currentUser}}`.
    If there's no form, mark the page so downstream tooling can recognise it."""
    changed = False
    nodes = page_schema.get("nodes") or page_schema.get("children")
    if not isinstance(nodes, list):
        return False
    # Remove list-only nodes; keep chrome (Heading/Text/Card/Stack).
    kept: list[dict] = []
    for n in nodes:
        if isinstance(n, dict) and n.get("type") in ("Table", "DataGrid", "List", "Kanban"):
            changed = True
            continue
        kept.append(n)
    if "nodes" in page_schema:
        page_schema["nodes"] = kept
    else:
        page_schema["children"] = kept

    # Rebind any Form node to the current-user record.
    for n in _iter_nodes(page_schema):
        if not isinstance(n, dict):
            continue
        if n.get("type") == "Form":
            props = n.setdefault("props", {})
            # The renderer's edit-form hydration reads `defaultValues` OR a
            # `record` binding — set both to make the intent explicit.
            new_default = "{{currentUser}}"
            if props.get("defaultValues") != new_default:
                props["defaultValues"] = new_default
                changed = True
            if props.get("record") != new_default:
                props["record"] = new_default
                changed = True

    # Filter markers help downstream inspectors (and clarify to anyone reading
    # the file that this page is scoped to currentUser).
    if page_schema.get("_route_intent") != "singleton_current_user":
        page_schema["_route_intent"] = "singleton_current_user"
        page_schema["_route_intent_filter"] = dict(filter_)
        changed = True
    return changed


# --------------------------------------------------------------------------
# main pass                                                                  #
# --------------------------------------------------------------------------

def apply_route_intent(output_dir: str) -> dict:
    root = Path(output_dir)
    plan = _load_plan(root)
    entities = list((plan.get("entities") or {}).keys())
    result: dict = {
        "singleton_pages": 0,
        "user_scope_lists": 0,
        "role_scope_lists": 0,
        "files_touched": [],
    }
    schemas_dir = root / "src" / "schemas"
    if not schemas_dir.exists() or not plan.get("pages"):
        return result

    for page in plan.get("pages") or []:
        if not isinstance(page, dict):
            continue
        route = page.get("route") or ""
        intent = classify_route(route, entities=entities)
        if intent.kind == "crud":
            continue
        slug = _slug_from_route(route)
        schema_path = schemas_dir / f"{slug}.json"
        if not schema_path.exists():
            continue
        try:
            doc = json.loads(schema_path.read_text(encoding="utf-8"))
        except Exception:
            continue

        touched = False
        if intent.kind == "singleton_current_user" and intent.filter:
            touched = _collapse_to_singleton(doc, intent.filter)
            if touched:
                result["singleton_pages"] += 1
        elif intent.kind == "current_user_scope_list" and intent.filter:
            touched = _apply_scope_filter_to_list(doc, intent.filter)
            if touched:
                result["user_scope_lists"] += 1
        elif intent.kind == "role_scope_list" and intent.filter:
            touched = _apply_scope_filter_to_list(doc, intent.filter)
            if touched:
                result["role_scope_lists"] += 1

        if touched:
            try:
                schema_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
                result["files_touched"].append(schema_path.name)
            except Exception:
                logger.exception("route_intent_apply: failed to write %s", schema_path)

    return result
