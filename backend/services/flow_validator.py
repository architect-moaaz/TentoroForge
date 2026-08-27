"""Navigation flow snapshot validator.

Reads navigation-flow.json and programmatically verifies that the generated code
matches the contract:
- Every route has a page.tsx
- Every API reference has a route.ts
- Every button trigger exists in the page source
- Every redirect has a router.push in the code

This is deterministic validation — not LLM judgment.
"""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


def validate_navigation_flow(output_dir: str) -> dict:
    """Validate generated code against navigation-flow.json.

    Returns:
        {
            "passed": bool,
            "issues": [...],
            "fix_prompt": str | None,
            "stats": { "checked": int, "passed": int, "failed": int }
        }
    """
    root = Path(output_dir)
    flow_file = root / "src" / "contracts" / "navigation-flow.json"

    if not flow_file.exists():
        logger.info("No navigation-flow.json found — skipping flow validation")
        return {"passed": True, "issues": [], "fix_prompt": None,
                "stats": {"checked": 0, "passed": 0, "failed": 0}}

    try:
        flow = json.loads(flow_file.read_text())
    except (json.JSONDecodeError, OSError) as e:
        return {"passed": False, "issues": [f"Invalid navigation-flow.json: {e}"],
                "fix_prompt": None, "stats": {"checked": 0, "passed": 0, "failed": 0}}

    app_dir = root / "src" / "app"
    api_dir = app_dir / "api"
    issues = []
    checked = 0
    passed = 0

    # ── 1. Check entity CRUD flows ──
    entity_flows = flow.get("flows", {}).get("entity_crud", {})
    for entity_name, entity_flow in entity_flows.items():
        for flow_type in ["list", "create", "detail"]:
            flow_def = entity_flow.get(flow_type)
            if not flow_def:
                continue

            route = flow_def.get("route", "")
            if not route or "{" in route:
                # Dynamic route like /pets/{id} — check [id] variant
                route_dir = route.replace("/{id}", "/[id]").lstrip("/")
            else:
                route_dir = route.lstrip("/")

            # Check page exists
            checked += 1
            page_found = _find_page(app_dir, route_dir)
            if page_found:
                passed += 1
                page_content = _read_file(page_found)

                # Check actions defined in the flow
                actions = flow_def.get("actions", {})
                if isinstance(actions, dict):
                    for action_name, action_def in actions.items():
                        if isinstance(action_def, dict):
                            _check_action(action_def, action_name, page_content,
                                         route, entity_name, issues, app_dir, api_dir)
                            checked += 1

                # Check submit handler
                submit = flow_def.get("submit")
                if submit and isinstance(submit, dict):
                    checked += 1
                    api_endpoint = submit.get("api", "")
                    on_success = submit.get("on_success", "")

                    if api_endpoint.startswith("POST ") or api_endpoint.startswith("PUT "):
                        method, api_path = api_endpoint.split(" ", 1)
                        # Check API route exists
                        api_route_dir = api_path.lstrip("/api/").split("?")[0]
                        if not _find_api_route(api_dir, api_route_dir):
                            issues.append(
                                f"[{entity_name}/{flow_type}] Submit API `{api_endpoint}` — "
                                f"route file missing at src/app/api/{api_route_dir}/route.ts"
                            )
                        else:
                            passed += 1

                    # Check redirect on success
                    if "redirect:" in on_success and page_content:
                        redirect_target = on_success.split("redirect:")[1].split("+")[0].strip()
                        if "router.push" not in page_content and "redirect" not in page_content:
                            issues.append(
                                f"[{entity_name}/{flow_type}] on_success says redirect to "
                                f"`{redirect_target}` but no router.push found in page"
                            )

                    # Check toast on success
                    if "toast" in on_success and page_content:
                        if "toast" not in page_content and "sonner" not in page_content:
                            issues.append(
                                f"[{entity_name}/{flow_type}] on_success says show toast "
                                f"but no toast import found in page"
                            )
            else:
                issues.append(
                    f"[{entity_name}/{flow_type}] Route `{route}` defined in flow "
                    f"but no page.tsx found"
                )

    # ── 2. Check dashboard flows ──
    dashboard = flow.get("flows", {}).get("dashboard", {})
    if dashboard:
        dash_route = dashboard.get("route", "/")
        checked += 1
        dash_page = _find_page(app_dir, dash_route.lstrip("/") or "")
        if dash_page:
            passed += 1
            dash_content = _read_file(dash_page)

            # Check stat cards
            widgets = dashboard.get("widgets", {})
            stat_cards = widgets.get("stat_cards", {})
            if stat_cards:
                entities = stat_cards.get("entities", [])
                for entity in entities:
                    checked += 1
                    slug = re.sub(r'(?<!^)(?=[A-Z])', '-', entity).lower()
                    if f"/api/{slug}" in dash_content or f"/{slug}" in dash_content:
                        passed += 1
                    else:
                        issues.append(
                            f"[dashboard] Stat card for `{entity}` defined in flow "
                            f"but no reference to /api/{slug} in dashboard page"
                        )

            # Check quick actions
            quick_actions = widgets.get("quick_actions", [])
            for qa in quick_actions:
                target = qa.get("target", "")
                if target:
                    checked += 1
                    if target in dash_content:
                        passed += 1
                    else:
                        issues.append(
                            f"[dashboard] Quick action `{qa.get('label', '?')}` → `{target}` "
                            f"defined in flow but no link found in dashboard page"
                        )
        else:
            issues.append("[dashboard] Dashboard page not found")

    # ── 3. Check auth flows ──
    auth_flow = flow.get("flows", {}).get("auth", {})
    if auth_flow:
        for auth_type in ["login", "signup"]:
            auth_def = auth_flow.get(auth_type, {})
            route = auth_def.get("route", "")
            if route:
                checked += 1
                if _find_page(app_dir, route.lstrip("/")):
                    passed += 1
                else:
                    issues.append(f"[auth] {auth_type} page at `{route}` not found")

    # ── 4. Check cross-entity navigation ──
    cross_entity = flow.get("flows", {}).get("cross_entity", [])
    for xref in cross_entity:
        from_route = xref.get("from", "")
        to_route = xref.get("to", "")
        if from_route and to_route:
            checked += 1
            from_page = _find_page(app_dir, from_route.replace("/{id}", "/[id]").lstrip("/"))
            if from_page:
                content = _read_file(from_page)
                # Check if the target route is referenced
                to_base = to_route.split("?")[0].split("/{")[0]
                if to_base in content:
                    passed += 1
                else:
                    issues.append(
                        f"[cross-entity] `{from_route}` should link to `{to_route}` "
                        f"but no reference found in page"
                    )

    # ── Build result ──
    result = {
        "passed": len(issues) == 0,
        "issues": issues,
        "stats": {"checked": checked, "passed": passed, "failed": len(issues)},
    }

    if issues:
        lines = [
            f"## NAVIGATION FLOW VALIDATION — {len(issues)} ISSUES\n",
            "The generated pages don't match the navigation-flow.json contract.\n",
        ]
        for i, issue in enumerate(issues, 1):
            lines.append(f"{i}. {issue}")
        lines.append(
            "\nFix these by reading navigation-flow.json and wiring the missing "
            "interactions into the pages. Read the page file, add the missing "
            "button/link/redirect/toast, and verify it matches the flow contract."
        )
        result["fix_prompt"] = "\n".join(lines)
    else:
        result["fix_prompt"] = None

    return result


def _find_page(app_dir: Path, route_dir: str) -> Path | None:
    """Find page.tsx for a route, checking route groups."""
    if not route_dir:
        # Root page
        root_page = app_dir / "page.tsx"
        if root_page.exists():
            return root_page
        # Check route groups
        for gd in app_dir.iterdir():
            if gd.is_dir() and gd.name.startswith("("):
                candidate = gd / "page.tsx"
                if candidate.exists():
                    return candidate
        return None

    # Direct path
    direct = app_dir / route_dir / "page.tsx"
    if direct.exists():
        return direct

    # Check inside route groups
    for gd in app_dir.iterdir():
        if gd.is_dir() and gd.name.startswith("("):
            candidate = gd / route_dir / "page.tsx"
            if candidate.exists():
                return candidate

    return None


def _find_api_route(api_dir: Path, route_dir: str) -> bool:
    """Check if an API route.ts exists."""
    if not api_dir.exists():
        return False
    route_file = api_dir / route_dir / "route.ts"
    if route_file.exists():
        return True
    # Try without trailing segment
    parts = route_dir.split("/")
    if len(parts) > 1:
        parent = api_dir / parts[0] / "route.ts"
        return parent.exists()
    return False


def _read_file(path: Path) -> str:
    """Read file content, return empty string on error."""
    try:
        return path.read_text()
    except (OSError, UnicodeDecodeError):
        return ""


def _check_action(action_def: dict, action_name: str, page_content: str,
                   route: str, entity: str, issues: list,
                   app_dir: Path, api_dir: Path):
    """Check a single action defined in the flow against the page source."""
    target = action_def.get("target", "")
    trigger = action_def.get("trigger", "")
    api = action_def.get("api", "")
    action_type = action_def.get("type", "")

    if not page_content:
        return

    # Check navigation targets exist
    if target and not target.startswith("#"):
        clean_target = target.split("?")[0].replace("/{id}", "/[id]")
        target_page = _find_page(app_dir, clean_target.lstrip("/"))
        if not target_page:
            # Only report if target is a concrete route (not dynamic)
            if "{" not in target:
                issues.append(
                    f"[{entity}/list] Action `{action_name}` targets `{target}` "
                    f"but no page exists"
                )

    # Check trigger button/input exists in page
    if trigger:
        trigger_type, _, trigger_label = trigger.partition(":")
        if trigger_type == "button" and trigger_label:
            # Check for button with this label
            if trigger_label.lower() not in page_content.lower():
                issues.append(
                    f"[{entity}] Action `{action_name}` expects button "
                    f"`{trigger_label}` but text not found in page `{route}`"
                )
        elif trigger_type == "input" and trigger_label:
            if trigger_label.lower() not in page_content.lower() and "search" not in page_content.lower():
                issues.append(
                    f"[{entity}] Action `{action_name}` expects input "
                    f"`{trigger_label}` but not found in page `{route}`"
                )

    # Check API endpoints exist
    if api and api.startswith(("GET ", "POST ", "PUT ", "DELETE ")):
        _, api_path = api.split(" ", 1)
        api_route = api_path.lstrip("/api/").split("?")[0].split("/{")[0]
        if not _find_api_route(api_dir, api_route):
            issues.append(
                f"[{entity}] Action `{action_name}` calls `{api}` "
                f"but API route missing"
            )
