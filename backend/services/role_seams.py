"""Role/auth seams for Smith (Phase 6).

Three deterministic seams that operate on the plan.json actor list and
per-page access constraints:

  * add_role(plan, role_name)              — append to plan['actors']
  * remove_role(plan, role_name)           — remove + report affected pages
  * restrict_page_to_role(plan, page, role) — set access.roles on a page

Design
------
Pure resolvers over dict-shaped plans. File-level wrappers
(``add_role_in_file`` etc.) read plan.json + write back atomically —
same pattern used by wire_form_workflow, plan_and_apply, etc.

Covers UAT tests:
  * #14  Add a new user role called Editor
  * #33  Remove the Editor role
  * #48  Add a role field to users, then restrict the admin page to that role
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Pure resolvers                                                              #
# --------------------------------------------------------------------------- #

def normalize_role_name(name: str) -> str:
    """Normalize to Title Case for storage, stripping surrounding
    whitespace. Distinct from role slugs used in access lists (those
    stay verbatim). Empty inputs return an empty string."""
    if not isinstance(name, str):
        return ""
    return name.strip()


def add_role(plan: dict, role_name: str) -> dict:
    """Add a role to plan['actors']. Idempotent — returns unchanged if
    the role already exists (case-insensitive match). Returns::

        {"ok": True, "added": True|False, "actors": [...]}

    Or on invalid input::

        {"ok": False, "error": "..."}
    """
    name = normalize_role_name(role_name)
    if not name:
        return {"ok": False, "error": "role_name required"}

    actors = list(plan.get("actors") or [])
    lc = name.lower()
    if any(str(a).strip().lower() == lc for a in actors):
        return {"ok": True, "added": False, "actors": actors}

    actors.append(name)
    plan["actors"] = actors
    return {"ok": True, "added": True, "actors": actors}


def remove_role(plan: dict, role_name: str) -> dict:
    """Remove ``role_name`` from plan['actors']. Reports pages that
    reference the role via ``access.roles`` so the caller (or the
    confirmation gate) can warn the user.

    Returns::

        {"ok": True, "removed": True|False, "actors": [...], "affected_pages": [...]}
    """
    name = normalize_role_name(role_name)
    if not name:
        return {"ok": False, "error": "role_name required"}

    lc = name.lower()
    actors = list(plan.get("actors") or [])
    survivors = [a for a in actors if str(a).strip().lower() != lc]
    removed = len(survivors) != len(actors)

    if removed:
        plan["actors"] = survivors

    # Scan pages for references.
    affected: list[str] = []
    for page in (plan.get("pages") or []):
        access = (page or {}).get("access") or {}
        roles = access.get("roles") or []
        if any(str(r).strip().lower() == lc for r in roles):
            affected.append(str(page.get("route") or page.get("id") or "?"))

    return {
        "ok":             True,
        "removed":        removed,
        "actors":         survivors if removed else actors,
        "affected_pages": affected,
    }


def restrict_page_to_role(
    plan: dict, page_route: str, role_name: str,
) -> dict:
    """Set ``access.roles = [role_name]`` on the page whose route matches
    ``page_route``. Idempotent — appends the role to an existing list
    if the page is already restricted, otherwise creates the constraint.

    Returns::

        {"ok": True, "page": "...", "roles": [...]}

    Or if the page can't be found::

        {"ok": False, "error": "page not found"}
    """
    role = normalize_role_name(role_name)
    if not role:
        return {"ok": False, "error": "role_name required"}

    pr = str(page_route or "").strip()
    if not pr:
        return {"ok": False, "error": "page_route required"}

    pages = plan.get("pages") or []
    target: Optional[dict] = None
    for p in pages:
        if str(p.get("route") or "").strip() == pr:
            target = p
            break
    if target is None:
        return {"ok": False, "error": f"page not found: {pr}"}

    access = target.setdefault("access", {})
    roles = list(access.get("roles") or [])
    lc = role.lower()
    if not any(str(r).strip().lower() == lc for r in roles):
        roles.append(role)
    access["roles"] = roles

    return {
        "ok":    True,
        "page":  pr,
        "roles": roles,
    }


# --------------------------------------------------------------------------- #
# File-level wrappers                                                         #
# --------------------------------------------------------------------------- #

def _plan_path(output_dir: str) -> Path:
    """Where the generated app's plan.json lives."""
    return Path(output_dir) / "src" / "contracts" / "plan.json"


def _read_plan(output_dir: str) -> Optional[dict]:
    p = _plan_path(output_dir)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("role_seams: failed to read plan.json")
        return None


def _write_plan(output_dir: str, plan: dict) -> bool:
    p = _plan_path(output_dir)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        # Atomic-ish: write to sibling then rename.
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(plan, indent=2, default=str, sort_keys=False),
            encoding="utf-8",
        )
        os.replace(str(tmp), str(p))
        return True
    except Exception:
        logger.exception("role_seams: failed to write plan.json")
        return False


def add_role_in_file(output_dir: str, role_name: str) -> dict:
    plan = _read_plan(output_dir)
    if plan is None:
        return {"ok": False, "error": "plan.json not readable"}
    result = add_role(plan, role_name)
    if not result.get("ok"):
        return result
    if result.get("added") and not _write_plan(output_dir, plan):
        return {"ok": False, "error": "plan.json write failed"}
    return result


def remove_role_in_file(output_dir: str, role_name: str) -> dict:
    plan = _read_plan(output_dir)
    if plan is None:
        return {"ok": False, "error": "plan.json not readable"}
    result = remove_role(plan, role_name)
    if not result.get("ok"):
        return result
    if result.get("removed") and not _write_plan(output_dir, plan):
        return {"ok": False, "error": "plan.json write failed"}
    return result


def restrict_page_to_role_in_file(
    output_dir: str, page_route: str, role_name: str,
) -> dict:
    plan = _read_plan(output_dir)
    if plan is None:
        return {"ok": False, "error": "plan.json not readable"}
    result = restrict_page_to_role(plan, page_route, role_name)
    if not result.get("ok"):
        return result
    if not _write_plan(output_dir, plan):
        return {"ok": False, "error": "plan.json write failed"}
    return result
