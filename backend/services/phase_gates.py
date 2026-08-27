"""Phase gates — acceptance checks after each SDLC phase.

Each gate verifies that the responsible agent's deliverables are complete.
If gaps are found, the gate returns a targeted prompt for the agent to
re-run with ONLY the missing work — not a full re-generation.

This mimics real SDLC: code review → defects → developer fixes → re-review.
"""

from __future__ import annotations

import re
import logging
from pathlib import Path

from typing import Any

from services.contract_generator import _to_slug, _to_table

logger = logging.getLogger(__name__)


def _iter_plan_pages(plan: dict):
    """Yield ``(route, entity)`` for each page the planner declared.

    Tolerates ``plan["pages"]`` as a LIST of dicts (``{"route"/"path", "entity"}``)
    or a legacy DICT keyed by route. ``entity`` may be ``None``.
    """
    pages = (plan or {}).get("pages")
    if isinstance(pages, dict):
        for route, body in pages.items():
            ent = body.get("entity") if isinstance(body, dict) else None
            yield route, ent
    elif isinstance(pages, list):
        for p in pages:
            if isinstance(p, dict):
                yield (p.get("route") or p.get("path") or ""), p.get("entity")


def _entity_candidate_routes(name: str) -> set[str]:
    """Top-level list-route forms that "belong to" an entity: the old
    singular-kebab match (``/foo`` + ``/foos``), the kebab-plural
    ``_to_slug`` form, and the camelCase-plural ``_to_table`` form."""
    sing = re.sub(r'(?<!^)(?=[A-Z])', '-', name).lower().replace("_", "-")
    return {f"/{sing}", f"/{sing}s", f"/{_to_slug(name)}", f"/{_to_table(name)}"}


# ---------------------------------------------------------------------------
# Contract Agent Gate
# ---------------------------------------------------------------------------

def check_contract_completeness(output_dir: str, plan: dict) -> dict:
    """Verify contracts cover every entity and page from the plan.

    Checks:
    - api-client.ts has functions for every entity
    - app-model.json has pages for every entity (list + detail + create)
    - design-system.tsx exists

    Returns:
        { "passed": bool, "missing": [...], "retry_prompt": str | None }
    """
    root = Path(output_dir)
    contracts_dir = root / "src" / "contracts"
    models = plan.get("data_models", [])
    issues: list[str] = []

    # Check design-system.tsx exists
    if not (contracts_dir / "design-system.tsx").exists():
        issues.append("MISSING: src/contracts/design-system.tsx")

    # Check api-client.ts has functions for every entity
    api_client = contracts_dir / "api-client.ts"
    api_content = ""
    if not api_client.exists():
        issues.append("MISSING: src/contracts/api-client.ts")
    else:
        try:
            api_content = api_client.read_text()
        except (OSError, UnicodeDecodeError):
            issues.append("UNREADABLE: src/contracts/api-client.ts")

    if api_content:
        for model in models:
            name = model.get("name", "")
            if not name:
                continue
            # Check for type export and at least one function
            has_type = bool(re.search(rf'\b{name}\b', api_content))
            has_func = bool(re.search(rf'(get|create|update|delete|list|fetch){name}', api_content, re.IGNORECASE))
            if not has_type or not has_func:
                issues.append(f"api-client.ts missing functions for entity: {name}")

    # Check app-model.json has pages for every entity
    app_model = contracts_dir / "app-model.json"
    if not app_model.exists():
        # Also check root level
        app_model = root / "app-model.json"
    if not app_model.exists():
        issues.append("MISSING: app-model.json (neither in src/contracts/ nor root)")
    else:
        try:
            import json
            model_data = json.loads(app_model.read_text())
            model_pages = model_data.get("pages", [])
            if isinstance(model_pages, list):
                page_routes = {p.get("route", p.get("path", "")) for p in model_pages if isinstance(p, dict)}
                # Entities the app-model pages are tagged with (case-insensitive).
                model_entities = {
                    str(p["entity"]).lower()
                    for p in model_pages
                    if isinstance(p, dict) and p.get("entity")
                }
            elif isinstance(model_pages, dict):
                page_routes = set(model_pages.keys())
                model_entities = {
                    str(b["entity"]).lower()
                    for b in model_pages.values()
                    if isinstance(b, dict) and b.get("entity")
                }
            else:
                page_routes = set()
                model_entities = set()

            # FIDELITY, not COMPLETENESS: the planner decides which entities get
            # a top-level list page (auth entities, friendly routes, and nested
            # sub-resources legitimately have none). Only flag an entity when the
            # planner DECLARED a page for it that app-model then DROPPED.
            for model in models:
                name = model.get("name", "")
                if not name:
                    continue
                candidates = _entity_candidate_routes(name)
                # 1. app-model carries a page tagged with this entity, OR
                # 2. app-model carries one of this entity's list routes → covered.
                if name.lower() in model_entities or (candidates & page_routes):
                    continue
                # 3. Did the planner declare a page for this entity at all?
                declared = False
                for route, ent in _iter_plan_pages(plan):
                    if ent and str(ent).lower() == name.lower():
                        declared = True
                        break
                    if route and route.rstrip("/") in candidates:
                        declared = True
                        break
                # Planner deliberately omitted a page → not a defect.
                if not declared:
                    continue
                # Planner declared a page but app-model has no route for it → drop.
                slug = _to_slug(name)
                issues.append(f"app-model.json missing list page for: {name} (/{slug})")
        except (json.JSONDecodeError, OSError):
            issues.append("INVALID: app-model.json is not valid JSON")

    if not issues:
        return {"passed": True, "missing": [], "retry_prompt": None}

    lines = [
        "## CONTRACT GAPS — FIX THESE NOW\n",
        "The following issues were found in the contract files.\n",
    ]
    for issue in issues:
        lines.append(f"- {issue}")
    lines.append(
        "\nRead the plan again and fix these gaps. "
        "Every entity in the plan must appear in api-client.ts with CRUD functions, "
        "and every entity must have list/detail/create pages in app-model.json."
    )

    return {
        "passed": False,
        "missing": issues,
        "retry_prompt": "\n".join(lines),
    }


# ---------------------------------------------------------------------------
# Auth Agent Gate
# ---------------------------------------------------------------------------

def check_auth_completeness(output_dir: str) -> dict:
    """Verify the auth layer is fully wired — the #1 most critical gate.

    Without auth, EVERY page shows a ClientFetchError and EVERY API call returns 401.
    This gate catches the single most impactful failure mode in the entire pipeline.

    Returns:
        { "passed": bool, "issues": [...], "retry_prompt": str | None }
    """
    root = Path(output_dir)
    issues: list[str] = []

    # 1. NextAuth route handler — THE MOST CRITICAL FILE
    nextauth_route = root / "src" / "app" / "api" / "auth" / "[...nextauth]" / "route.ts"
    if not nextauth_route.exists():
        issues.append(
            "CRITICAL MISSING: src/app/api/auth/[...nextauth]/route.ts — "
            "Without this file, /api/auth/session returns 404, SessionProvider crashes "
            "on every page, and ALL API calls return 401. Create it:\n"
            '  import { handlers } from "@/auth";\n'
            "  export const { GET, POST } = handlers;"
        )

    # 2. Auth config
    auth_config = root / "src" / "auth.ts"
    if not auth_config.exists():
        issues.append(
            "CRITICAL MISSING: src/auth.ts — NextAuth configuration. "
            "Without this, the auth() function doesn't exist and no route can authenticate."
        )
    else:
        try:
            content = auth_config.read_text()
            if "providers" not in content or len(content) < 100:
                issues.append(
                    "BROKEN: src/auth.ts exists but has no providers configured. "
                    "Add CredentialsProvider with email/password authentication."
                )
        except (OSError, UnicodeDecodeError):
            pass

    # 3. Signup route
    signup_route = root / "src" / "app" / "api" / "auth" / "signup" / "route.ts"
    if not signup_route.exists():
        issues.append(
            "MISSING: src/app/api/auth/signup/route.ts — "
            "Users cannot register without this. Create a POST handler that "
            "validates input, hashes password with bcryptjs, inserts into users table."
        )

    # 4. Middleware
    middleware = root / "src" / "middleware.ts"
    if not middleware.exists():
        issues.append(
            "MISSING: src/middleware.ts — Route protection. "
            "Without this, all routes are accessible without login."
        )

    # 5. Login page (check multiple possible locations)
    login_found = False
    for path in [
        root / "src" / "app" / "login" / "page.tsx",
        root / "src" / "app" / "(auth)" / "login" / "page.tsx",
    ]:
        if path.exists():
            login_found = True
            break
    if not login_found:
        issues.append("MISSING: Login page — create at src/app/login/page.tsx")

    # 6. Signup page
    signup_found = False
    for path in [
        root / "src" / "app" / "signup" / "page.tsx",
        root / "src" / "app" / "(auth)" / "signup" / "page.tsx",
    ]:
        if path.exists():
            signup_found = True
            break
    if not signup_found:
        issues.append("MISSING: Signup page — create at src/app/signup/page.tsx")

    if not issues:
        return {"passed": True, "issues": [], "retry_prompt": None}

    lines = [
        "## AUTH LAYER INCOMPLETE — CRITICAL ISSUES\n",
        "The authentication system is broken. Fix ALL issues below.\n",
        "Without a working auth layer, the ENTIRE app is non-functional.\n",
    ]
    for i, issue in enumerate(issues, 1):
        lines.append(f"{i}. {issue}")
    lines.append(
        "\nCreate ALL missing files. Read existing schema to understand the users table. "
        "The app CANNOT function without these files."
    )

    return {
        "passed": False,
        "issues": issues,
        "retry_prompt": "\n".join(lines),
    }


# ---------------------------------------------------------------------------
# Cross-Reference Gate (pages ↔ API routes)
# ---------------------------------------------------------------------------

def check_cross_references(output_dir: str, plan: dict) -> dict:
    """Verify that every API endpoint pages call actually exists.

    This catches the gap where a page fetches /api/services but no services route was generated,
    or dashboard calls /api/invoices/stats but stats route is missing.

    Returns:
        { "passed": bool, "issues": [...], "retry_prompt": str | None }
    """
    root = Path(output_dir)
    app_dir = root / "src" / "app"
    api_dir = app_dir / "api"
    issues: list[str] = []

    if not app_dir.exists():
        return {"passed": True, "issues": [], "retry_prompt": None}

    # Collect all existing API routes
    existing_routes: set[str] = set()
    if api_dir.exists():
        for route_file in api_dir.rglob("route.ts"):
            rel = route_file.parent.relative_to(api_dir)
            # Convert [id] to dynamic segment marker
            route_path = "/api/" + str(rel).replace("[", ":").replace("]", "")
            existing_routes.add(str(rel))

    # Scan pages for fetch("/api/...") calls
    missing_apis: dict[str, list[str]] = {}  # api_path → [pages that call it]

    for page_file in app_dir.rglob("page.tsx"):
        if "node_modules" in str(page_file) or "api" in str(page_file):
            continue
        try:
            content = page_file.read_text()
        except (OSError, UnicodeDecodeError):
            continue

        # Find all /api/... references
        for m in re.finditer(r'["\'/`]/api/([a-z0-9\-]+)(?:/([a-z0-9\-]+))?', content):
            entity = m.group(1)
            sub = m.group(2)

            if entity == "auth":
                continue  # Auth routes checked by auth gate

            # Check if the route exists
            if sub == "stats":
                route_dir = entity + "/stats"
            elif sub and sub != "${id}" and sub not in ("$", "{"):
                route_dir = entity + "/" + sub
            else:
                route_dir = entity

            if route_dir not in existing_routes and entity not in existing_routes:
                page_rel = str(page_file.relative_to(app_dir))
                if route_dir not in missing_apis:
                    missing_apis[route_dir] = []
                if page_rel not in missing_apis[route_dir]:
                    missing_apis[route_dir].append(page_rel)

    for api_path, pages in missing_apis.items():
        pages_str = ", ".join(pages[:3])
        issues.append(
            f"MISSING API: /api/{api_path} — called by {pages_str}. "
            f"Create src/app/api/{api_path}/route.ts"
        )

    if not issues:
        return {"passed": True, "issues": [], "retry_prompt": None}

    lines = [
        f"## CROSS-REFERENCE GAPS — {len(issues)} MISSING API ROUTES\n",
        "Pages reference API endpoints that don't exist. Create them.\n",
    ]
    for i, issue in enumerate(issues, 1):
        lines.append(f"{i}. {issue}")
    lines.append(
        "\nCreate these missing API routes. Read existing routes for patterns. "
        "Each route needs GET/POST handlers that match what the page expects."
    )

    return {
        "passed": False,
        "issues": issues,
        "retry_prompt": "\n".join(lines),
    }


# ---------------------------------------------------------------------------
# API Agent Gate
# ---------------------------------------------------------------------------

def check_api_completeness(output_dir: str, plan: dict) -> dict:
    """Check that every entity has full CRUD + stats API routes.

    Returns:
        {
            "passed": bool,
            "missing": [
                {"entity": "users", "slug": "users", "missing": ["route.ts", "[id]/route.ts", "stats/route.ts"]},
            ],
            "retry_prompt": str | None,  # prompt to send back to API agent
        }
    """
    root = Path(output_dir)
    api_dir = root / "src" / "app" / "api"
    models = plan.get("data_models", [])

    missing_entities: list[dict] = []

    for model in models:
        name = model.get("name", "")
        if not name:
            continue

        # Convert to URL slug: TimeEntry → time-entries, User → users
        slug = re.sub(r'(?<!^)(?=[A-Z])', '-', name).lower()
        # Also try underscore variant: time_entries → time-entries
        slug_alt = name.lower().replace("_", "-")

        entity_dir = api_dir / slug
        if not entity_dir.exists():
            entity_dir = api_dir / slug_alt
        if not entity_dir.exists():
            # Try pluralized forms
            for s in [slug + "s", slug_alt + "s", slug.rstrip("s"), slug_alt.rstrip("s")]:
                if (api_dir / s).exists():
                    entity_dir = api_dir / s
                    break

        gaps = []
        if not (entity_dir / "route.ts").exists():
            gaps.append("route.ts (GET list + POST create)")
        if not (entity_dir / "[id]" / "route.ts").exists():
            gaps.append("[id]/route.ts (GET + PUT + DELETE)")
        if not (entity_dir / "stats" / "route.ts").exists():
            gaps.append("stats/route.ts (GET count)")

        if gaps:
            missing_entities.append({
                "entity": name,
                "slug": slug,
                "fields": [f.get("name", "") for f in model.get("fields", [])],
                "missing": gaps,
            })

    if not missing_entities:
        return {"passed": True, "missing": [], "retry_prompt": None}

    # Build a focused retry prompt
    lines = [
        "## API ROUTES STILL MISSING — FIX THESE NOW\n",
        "The following entities are missing API routes. Create them.\n",
    ]
    for me in missing_entities:
        lines.append(f"### {me['entity']} (fields: {', '.join(me['fields'][:8])})")
        for gap in me["missing"]:
            lines.append(f"  - [ ] src/app/api/{me['slug']}/{gap}")
        lines.append("")

    lines.append(
        "Read the existing schema and create these missing route files.\n"
        "Follow the EXACT same patterns as the routes you already created.\n"
        "Do NOT modify existing files — only create the missing ones."
    )

    return {
        "passed": False,
        "missing": missing_entities,
        "retry_prompt": "\n".join(lines),
    }


# ---------------------------------------------------------------------------
# Page Agent Gate
# ---------------------------------------------------------------------------

def check_page_completeness(output_dir: str, plan: dict) -> dict:
    """Check that pages are complete: root redirect, create buttons, working forms, sidebar links.

    Returns:
        {
            "passed": bool,
            "issues": [...],
            "retry_prompt": str | None,
        }
    """
    root = Path(output_dir)
    app_dir = root / "src" / "app"
    issues: list[str] = []

    # 1. Root redirect
    root_page = app_dir / "page.tsx"
    if not root_page.exists():
        issues.append("MISSING: src/app/page.tsx — create with redirect to /dashboard")

    # 1b. Entity /new pages exist for every data model
    models = plan.get("data_models", [])
    for model in models:
        name = model.get("name", "")
        if not name or name in ("User", "WorkflowTask"):
            continue
        slug = re.sub(r'(?<!^)(?=[A-Z])', '-', name).lower().replace("_", "-")
        # Check in route groups too
        new_page_found = False
        for base in [app_dir, *[gd for gd in app_dir.iterdir() if gd.is_dir() and gd.name.startswith("(")]]:
            if (base / slug / "new" / "page.tsx").exists():
                new_page_found = True
                break
        if not new_page_found:
            issues.append(
                f"MISSING CREATE PAGE: /{slug}/new/page.tsx for entity {name} — "
                f"users cannot create new {name} records without this page"
            )

    # 2. Form TODO stubs
    for page in app_dir.rglob("page.tsx"):
        if "node_modules" in str(page):
            continue
        rel = str(page.relative_to(app_dir))
        if not rel.endswith("new/page.tsx"):
            continue
        try:
            content = page.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        if re.search(r'//\s*TODO|//\s*Handle\s+form|//\s*Handle\s+submit', content):
            entity = rel.split("/")[0]
            issues.append(
                f"BROKEN FORM: {rel} has TODO stub — implement useMutation that "
                f"POSTs to /api/{entity} and redirects to /{entity} on success"
            )

    # 3. List pages missing Create button
    for page in app_dir.rglob("page.tsx"):
        if "node_modules" in str(page):
            continue
        rel = page.relative_to(app_dir)
        parts = rel.parts
        if len(parts) != 2:
            continue
        entity_dir = parts[0]
        if entity_dir in ("dashboard", "login", "signup", "error", "loading"):
            continue
        if entity_dir.startswith("(") or entity_dir.startswith("["):
            continue
        try:
            content = page.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        if not re.search(r'href=["\'].*?/new["\']|Create|New\s|\+\s*New', content):
            issues.append(
                f"MISSING CREATE BUTTON: {rel} — add a Link to /{entity_dir}/new"
            )

    # 4. Dead sidebar links
    sidebar_files = list(app_dir.rglob("sidebar*")) + list(app_dir.rglob("Sidebar*"))
    if (app_dir.parent / "components").exists():
        sidebar_files += list((app_dir.parent / "components").rglob("Sidebar*"))
    for sf in sidebar_files:
        if not sf.is_file() or sf.suffix != ".tsx":
            continue
        try:
            content = sf.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for m in re.finditer(r'href=["\'](/[^"\']*)["\']', content):
            href = m.group(1)
            if href in ("/", "#") or href.startswith("/api/"):
                continue
            page_path = app_dir / href.strip("/") / "page.tsx"
            found = page_path.exists()
            if not found:
                for gd in app_dir.iterdir():
                    if gd.is_dir() and gd.name.startswith("("):
                        if (gd / href.strip("/") / "page.tsx").exists():
                            found = True
                            break
            if not found:
                issues.append(
                    f"DEAD LINK: Sidebar links to {href} but no page exists — "
                    f"either create the page or remove the link"
                )

    if not issues:
        return {"passed": True, "issues": [], "retry_prompt": None}

    lines = [
        "## PAGE ISSUES FOUND — FIX THESE NOW\n",
        f"The following {len(issues)} issues were found after your page generation.\n",
        "Fix ALL of them before finishing.\n",
    ]
    for i, issue in enumerate(issues, 1):
        lines.append(f"{i}. {issue}")

    lines.append(
        "\nFix these issues by editing or creating the necessary files. "
        "Read existing files first to understand the patterns already in use."
    )

    return {
        "passed": False,
        "issues": issues,
        "retry_prompt": "\n".join(lines),
    }


# ---------------------------------------------------------------------------
# Component Agent Gate
# ---------------------------------------------------------------------------

def check_component_completeness(output_dir: str, plan: dict) -> dict:
    """Check that all required components exist: layout, UI base, per-entity."""
    root = Path(output_dir)
    components_dir = root / "src" / "components"
    app_dir = root / "src" / "app"
    issues: list[str] = []

    # 1. Layout components
    sidebar_found = False
    for pattern in ["**/Sidebar*", "**/sidebar*", "**/SideNav*", "**/side-nav*"]:
        if list((root / "src").rglob(pattern)):
            sidebar_found = True
            break
    if not sidebar_found:
        issues.append("MISSING: Sidebar component — create src/components/layout/Sidebar.tsx with links to all pages")

    navbar_found = False
    for pattern in ["**/Navbar*", "**/navbar*", "**/TopBar*", "**/top-bar*", "**/Header*"]:
        if list((root / "src").rglob(pattern)):
            navbar_found = True
            break
    if not navbar_found:
        issues.append("MISSING: Navbar component — create src/components/layout/Navbar.tsx with app name, user menu, logout")

    # 2. Essential UI components
    essential_ui = ["button", "card", "input", "dialog", "badge", "toast", "skeleton", "label"]
    if components_dir.exists():
        ui_dir = components_dir / "ui"
        for comp in essential_ui:
            if not (ui_dir / f"{comp}.tsx").exists():
                issues.append(f"MISSING: src/components/ui/{comp}.tsx — create shadcn/ui {comp} component")

    # 3. Shared components
    shared_checks = [
        ("StatsCard", "dashboard/StatsCard", "Stat card for dashboard with icon, value, label, trend"),
    ]
    if components_dir.exists():
        for name, path, desc in shared_checks:
            found = list(components_dir.rglob(f"{name}*"))
            if not found:
                issues.append(f"MISSING: src/components/{path}.tsx — {desc}")

    # 4. Per-entity Table + Form components
    models = plan.get("data_models", [])
    for model in models:
        name = model.get("name", "")
        if not name:
            continue
        slug = re.sub(r'(?<!^)(?=[A-Z])', '-', name).lower().replace("_", "-")
        fields = [f.get("name", "") for f in model.get("fields", [])]

        table_found = any(
            list(components_dir.rglob(p)) for p in [f"{name}Table*", f"{name}List*"]
        ) if components_dir.exists() else False
        if not table_found:
            issues.append(
                f"MISSING: src/components/{slug}/{name}Table.tsx — "
                f"Data table for {name} with columns: {', '.join(fields[:5])}"
            )

        form_found = any(
            list(components_dir.rglob(p)) for p in [f"{name}Form*"]
        ) if components_dir.exists() else False
        if not form_found:
            issues.append(
                f"MISSING: src/components/{slug}/{name}Form.tsx — "
                f"Create/edit form for {name} with fields: {', '.join(f for f in fields[:5] if f not in ('id', 'createdAt', 'updatedAt'))}"
            )

    if not issues:
        return {"passed": True, "issues": [], "retry_prompt": None}

    lines = [
        f"## COMPONENT ISSUES — {len(issues)} MISSING COMPONENTS\n",
        "Create these missing components. Read existing components for patterns.\n",
    ]
    for i, issue in enumerate(issues, 1):
        lines.append(f"{i}. {issue}")
    lines.append(
        "\nCreate ALL missing components. Use shadcn/ui patterns for UI components. "
        "Entity tables must show real columns. Entity forms must have real fields."
    )

    return {
        "passed": False,
        "issues": issues,
        "retry_prompt": "\n".join(lines),
    }


# ---------------------------------------------------------------------------
# Workflow Integration Gate
# ---------------------------------------------------------------------------

def check_workflow_integration(output_dir: str, plan: dict) -> dict:
    """Verify workflows are fully wired: definitions have steps, pages have buttons.

    Returns:
        { "passed": bool, "issues": [...], "retry_prompt": str | None }
    """
    root = Path(output_dir)
    workflows = plan.get("workflows", [])
    if not workflows:
        return {"passed": True, "issues": [], "retry_prompt": None}

    issues: list[str] = []

    # 0. Check workflow-tasks API route exists (most critical — pages call this)
    api_dir = root / "src" / "app" / "api"
    wf_tasks_route = api_dir / "workflow-tasks" / "route.ts"
    if not wf_tasks_route.exists():
        issues.append(
            "CRITICAL: /api/workflow-tasks/route.ts MISSING — "
            "WorkflowTask is in data_models but API route was never created. "
            "Create it with standard CRUD (GET list + POST create)."
        )

    # 0b. Check at least one API route calls triggerWorkflowEvent
    runtime_integrated = False
    if api_dir.exists():
        for route_file in api_dir.rglob("route.ts"):
            try:
                content = route_file.read_text()
                if "triggerWorkflowEvent" in content or "triggerWorkflow" in content:
                    runtime_integrated = True
                    break
            except (OSError, UnicodeDecodeError):
                continue
    if not runtime_integrated:
        runtime_exists = (root / "src" / "lib" / "workflows").exists()
        if runtime_exists:
            issues.append(
                "NO API ROUTE calls triggerWorkflowEvent() — workflow runtime exists at "
                "src/lib/workflows/ but zero API routes integrate with it. "
                "POST/PUT routes for entities with workflows MUST call triggerWorkflowEvent()."
            )

    # 1. Check workflow JSON files have steps
    workflow_dir = root / "workflows"
    if workflow_dir.exists():
        for wf_file in workflow_dir.glob("*.json"):
            try:
                import json
                wf = json.loads(wf_file.read_text())
                steps = wf.get("steps", [])
                name = wf.get("name", wf_file.stem)
                if len(steps) == 0:
                    issues.append(
                        f"Workflow '{name}' has 0 steps — fill in step definitions "
                        f"in {wf_file.relative_to(root)}"
                    )
            except (json.JSONDecodeError, OSError):
                continue

    # 2. Classify workflows by type and check appropriate endpoints
    app_dir = root / "src" / "app"
    api_dir = app_dir / "api"

    # Approval keywords → needs /approve + /reject endpoints
    approval_keywords = ["approval", "approve", "claim", "refill", "payment plan", "authorize"]
    # Review keywords → needs /review endpoint
    review_keywords = ["review", "verify", "validate"]
    # Automated keywords → no manual endpoints needed
    automated_keywords = ["reminder", "alert", "notification", "automated", "scheduled"]

    for wf in workflows:
        wf_name = wf.get("name", "").lower()

        # Classify this workflow
        is_approval = any(kw in wf_name for kw in approval_keywords)
        is_review = any(kw in wf_name for kw in review_keywords) and not is_approval
        is_automated = any(kw in wf_name for kw in automated_keywords)

        if is_automated:
            continue  # No manual endpoints needed

        if not is_approval and not is_review:
            continue  # Multi-step or unknown — skip

        # Find the entity this workflow applies to
        # Infer from workflow name: InsuranceClaimsProcessingWorkflow → insurance-claims
        entity_slug = None
        for model in plan.get("data_models", []):
            model_name = model.get("name", "").lower()
            if model_name in wf_name.replace("workflow", "").lower():
                entity_slug = re.sub(r'(?<!^)(?=[A-Z])', '-', model.get("name", "")).lower().replace("_", "-")
                break

        if not entity_slug:
            continue

        if is_approval:
            approve_route = api_dir / entity_slug / "[id]" / "approve" / "route.ts"
            if not approve_route.exists():
                issues.append(
                    f"Approval workflow '{wf.get('name', '')}' → entity '{entity_slug}' "
                    f"needs src/app/api/{entity_slug}/[id]/approve/route.ts"
                )

    # 3. Check pages use WorkflowTriggerButton or approve/reject mutations
    if app_dir.exists():
        all_page_content = ""
        for page in app_dir.rglob("page.tsx"):
            if "node_modules" in str(page):
                continue
            try:
                all_page_content += page.read_text().lower()
            except (OSError, UnicodeDecodeError):
                continue

        has_workflow_ui = (
            "workflowtriggerbutton" in all_page_content or
            "approve" in all_page_content or
            "/approve" in all_page_content
        )
        if not has_workflow_ui and len(workflows) > 0:
            issues.append(
                "No pages use WorkflowTriggerButton or have approve/reject buttons. "
                "Detail pages for entities with approval workflows must have approve/reject actions."
            )

    if not issues:
        return {"passed": True, "issues": [], "retry_prompt": None}

    lines = [
        f"## WORKFLOW INTEGRATION ISSUES — {len(issues)} FOUND\n",
        "The following workflow integration problems were detected.\n",
    ]
    for i, issue in enumerate(issues, 1):
        lines.append(f"{i}. {issue}")
    lines.append(
        "\nFix these issues: fill empty workflow JSON steps, "
        "create missing approval API routes, and add approve/reject buttons to detail pages."
    )

    return {
        "passed": False,
        "issues": issues,
        "retry_prompt": "\n".join(lines),
    }


# ---------------------------------------------------------------------------
# UX Toll Gate — verifies domain-appropriate UX
# ---------------------------------------------------------------------------

def check_ux_compliance(output_dir: str, plan: dict, domain: str) -> dict:
    """Verify the generated app matches the domain UX spec.

    Checks:
    - Dashboard has domain-appropriate sections (not just generic stat cards)
    - Detail pages use domain-appropriate layout (tabs, hero, sidebar)
    - Status badges use domain-correct colors and labels
    - Navigation reflects domain workflow groups
    - Domain-specific widgets are present (or at least attempted)
    - Compliance requirements are reflected (data masking, audit trails)

    Returns:
        { "passed": bool, "issues": [...], "retry_prompt": str | None }
    """
    from services.domain_ux_specs import get_domain_ux_spec

    root = Path(output_dir)
    app_dir = root / "src" / "app"
    spec = get_domain_ux_spec(domain)
    issues: list[str] = []

    if not app_dir.exists():
        return {"passed": True, "issues": [], "retry_prompt": None}

    # 1. Dashboard checks
    dash_spec = spec.get("page_archetypes", {}).get("dashboard", {})
    dashboard_files = list(app_dir.rglob("dashboard/page.tsx"))
    if not dashboard_files:
        # Check route groups
        for gd in app_dir.iterdir():
            if gd.is_dir() and gd.name.startswith("("):
                dashboard_files.extend(gd.rglob("page.tsx"))
                break

    if dashboard_files and dash_spec:
        try:
            dash_content = dashboard_files[0].read_text().lower()
        except (OSError, UnicodeDecodeError):
            dash_content = ""

        expected_sections = dash_spec.get("sections", [])
        missing_sections = []
        for section in expected_sections:
            # Normalize section name for search: "priority-alerts" → ["priority", "alert"]
            keywords = section.replace("-", " ").replace("_", " ").split()
            found = any(kw in dash_content for kw in keywords)
            if not found:
                missing_sections.append(section)

        if len(missing_sections) > len(expected_sections) // 2:
            issues.append(
                f"Dashboard is missing domain sections. Expected for {domain}: "
                f"{', '.join(expected_sections)}. Missing: {', '.join(missing_sections)}. "
                f"The dashboard should be a {dash_spec.get('layout', 'standard')} layout: "
                f"{dash_spec.get('hero', '')}"
            )

    # 2. Status semantics check
    status_spec = spec.get("status_semantics", {})
    if status_spec:
        # Check if any page uses domain-specific status values
        all_page_content = ""
        for page in app_dir.rglob("page.tsx"):
            if "node_modules" in str(page):
                continue
            try:
                all_page_content += page.read_text().lower() + "\n"
            except (OSError, UnicodeDecodeError):
                continue

        status_labels_found = 0
        for status_name in status_spec:
            normalized = status_name.replace("_", " ").replace("-", " ")
            if normalized in all_page_content or status_name in all_page_content:
                status_labels_found += 1

        if status_labels_found == 0 and len(status_spec) > 2:
            status_list = ", ".join(status_spec.keys())
            issues.append(
                f"No domain-specific status labels found. {domain} apps should use: "
                f"{status_list}. Apply the status color semantics from the UX spec."
            )

    # 3. Navigation structure check
    nav_spec = spec.get("navigation_flow", {})
    if nav_spec:
        sidebar_groups = nav_spec.get("sidebar_groups", [])
        if sidebar_groups:
            sidebar_files = list(app_dir.rglob("sidebar*")) + list(app_dir.rglob("Sidebar*"))
            if (app_dir.parent / "components").exists():
                sidebar_files += list((app_dir.parent / "components").rglob("Sidebar*"))

            sidebar_content = ""
            for sf in sidebar_files:
                if sf.is_file() and sf.suffix == ".tsx":
                    try:
                        sidebar_content += sf.read_text().lower()
                    except (OSError, UnicodeDecodeError):
                        continue

            if sidebar_content:
                missing_groups = []
                for group in sidebar_groups:
                    if group.lower() not in sidebar_content:
                        missing_groups.append(group)
                if len(missing_groups) > len(sidebar_groups) // 2:
                    issues.append(
                        f"Sidebar navigation doesn't reflect {domain} workflow. "
                        f"Expected groups: {', '.join(sidebar_groups)}. "
                        f"Missing: {', '.join(missing_groups)}."
                    )

    # 4. Detail page layout check
    detail_spec = spec.get("page_archetypes", {}).get("detail", {})
    if detail_spec and detail_spec.get("tabs"):
        expected_tabs = detail_spec["tabs"]
        # Check detail pages for tab usage
        detail_pages = list(app_dir.rglob("[id]/page.tsx"))
        tabs_found = False
        for dp in detail_pages:
            if "node_modules" in str(dp):
                continue
            try:
                content = dp.read_text().lower()
            except (OSError, UnicodeDecodeError):
                continue
            if "tab" in content or "tabs" in content:
                tabs_found = True
                break

        if not tabs_found and len(detail_pages) > 0:
            issues.append(
                f"Detail pages don't use tabbed layout. {domain} detail pages should have tabs: "
                f"{' | '.join(expected_tabs)}. Use a Tabs component to organize entity details."
            )

    # 5. Compliance check
    #
    # Spec D Wave 1 (round 2) — brief-first: consult
    # brief.identity.compliance_flags in addition to the domain spec.
    # When the brief asks for regimes the domain doesn't list (e.g. a
    # SaaS app that must meet SOC2), we still run a generic-keyword
    # check so the gate has something to say. When the brief REPEATS
    # the domain's standard, behavior is unchanged.
    brief_flags: list[str] = []
    try:
        from services.brief_visual_stance import (
            get_compliance_flags,
            load_brief_from,
        )
        brief_flags = get_compliance_flags(load_brief_from(output_dir))
    except Exception:  # noqa: BLE001 — brief is enhancement
        brief_flags = []
    compliance = spec.get("compliance", {})
    requirements = compliance.get("requirements", [])
    standard = compliance.get("standard", "")
    _has_domain_reqs = bool(requirements and standard and standard != "None")
    if _has_domain_reqs or brief_flags:
        # Check for basic compliance indicators
        all_code = ""
        for f in (root / "src").rglob("*.tsx"):
            if "node_modules" in str(f):
                continue
            try:
                all_code += f.read_text().lower() + "\n"
            except (OSError, UnicodeDecodeError):
                continue

        # Derive compliance keywords from the requirements themselves (data-driven)
        # Extract key action words from each requirement string
        relevant_keywords: set[str] = set()
        _COMPLIANCE_KW = (
            "mask", "audit", "role", "session", "timeout", "approval",
            "encrypt", "token", "consent", "retention", "access",
            "log", "trail", "verify", "validate", "segregat",
        )
        for req in requirements:
            req_lower = req.lower()
            for kw in _COMPLIANCE_KW:
                if kw in req_lower:
                    relevant_keywords.add(kw)
        # Brief-requested regimes broaden the search set. Each named regime
        # implies a small canonical keyword bundle so the gate stays useful
        # even when the domain block is silent.
        _FLAG_KEYWORDS: dict[str, tuple[str, ...]] = {
            "hipaa": ("audit", "role", "mask", "access", "log"),
            "sox": ("audit", "approval", "role", "log", "segregat"),
            "gdpr": ("consent", "retention", "access", "encrypt"),
            "pci": ("mask", "encrypt", "token", "audit"),
            "soc2": ("audit", "role", "access", "log", "encrypt"),
            "ferpa": ("role", "access", "audit", "consent"),
        }
        for flag in brief_flags:
            relevant_keywords.update(_FLAG_KEYWORDS.get(flag, ("audit", "role")))
        # Sensible generic default if we still have nothing.
        rel_list = list(relevant_keywords) if relevant_keywords else ["audit", "role"]
        if rel_list:
            found_count = sum(1 for kw in rel_list if kw in all_code)
            if found_count == 0:
                _std_label = standard if standard and standard != "None" else "(brief-requested)"
                _flag_label = (
                    f" + brief-requested: {', '.join(f.upper() for f in brief_flags)}"
                    if brief_flags else ""
                )
                issues.append(
                    f"No {_std_label}{_flag_label} compliance patterns detected. "
                    "Key requirements:\n"
                    + "\n".join(f"    - {r}" for r in requirements[:3])
                )

    if not issues:
        return {"passed": True, "issues": [], "retry_prompt": None}

    lines = [
        f"## UX COMPLIANCE: {domain.upper()} — ISSUES FOUND\n",
        f"The following {len(issues)} UX issues were found. Fix them to match {domain} industry standards.\n",
    ]
    for i, issue in enumerate(issues, 1):
        lines.append(f"{i}. {issue}")

    lines.append(
        f"\nRefer to the UX specification for {domain} and fix these issues. "
        f"Read existing pages first, then apply domain-appropriate patterns."
    )

    return {
        "passed": False,
        "issues": issues,
        "retry_prompt": "\n".join(lines),
    }


# ---------------------------------------------------------------------------
# CTA Hierarchy Gate (post-schema)
# ---------------------------------------------------------------------------

def check_cta_hierarchy(output_dir: str, plan: dict) -> dict:
    """Walk every emitted JSON schema under src/schemas/ and run the
    CTA hierarchy validator. Returns the standard gate-shape dict.

    Loads the design-spec's cta_hierarchy block as the rule source. If the
    spec or hierarchy block is missing, the gate passes silently (nothing
    to enforce). The page's directory name is used as page_type so that
    e.g. form pages skip the primary-min check.
    """
    from pathlib import Path
    import json
    from services.schema_validator import validate_cta_hierarchy

    output = Path(output_dir)
    spec_path = output / "src" / "contracts" / "design-spec.json"
    if not spec_path.exists():
        return {"passed": True, "issues": [], "retry_prompt": ""}
    try:
        spec = json.loads(spec_path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"passed": True, "issues": [], "retry_prompt": ""}
    cta = spec.get("cta_hierarchy")
    if not cta:
        return {"passed": True, "issues": [], "retry_prompt": ""}

    issues: list[str] = []
    schemas_dir = output / "src" / "schemas"
    if not schemas_dir.exists():
        return {"passed": True, "issues": [], "retry_prompt": ""}

    for path in schemas_dir.rglob("*.json"):
        # Skip any auto-generated meta files
        if path.name in ("registry.json", "load.json"):
            continue
        try:
            page = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        # page_type — read from the schema if present, else infer from path stem
        page["page_type"] = page.get("page_type") or path.stem
        # Relative path under schemas_dir → identifier for error messages
        rel = path.relative_to(schemas_dir).with_suffix("")
        for err in validate_cta_hierarchy(page, cta):
            issues.append(f"{rel}: {err}")

    if not issues:
        return {"passed": True, "issues": [], "retry_prompt": ""}

    retry_prompt = (
        "The CTA hierarchy gate found the following violations. Adjust your output "
        "so each page has exactly one primary CTA (variant='primary'), no more than "
        "the per-page cap of secondary CTAs, and no orphan high-variant Buttons.\n\n"
        + "\n".join(f"- {i}" for i in issues)
    )
    return {"passed": False, "issues": issues, "retry_prompt": retry_prompt}


# ---------------------------------------------------------------------------
# Progressive Disclosure Gate (post-schema)
# ---------------------------------------------------------------------------

def check_progressive_disclosure(output_dir: str, plan: dict) -> dict:
    """Walk every emitted JSON schema under src/schemas/ and run the
    progressive-disclosure validator. Returns the standard gate-shape dict.

    Flags Forms with > 7 user-editable fields that are not partitioned into
    an Accordion or Tabs (or TabPanelWithDeepLink) container. Same
    conservative scope as the CTA hierarchy gate: detect + log, no auto-
    retry loop.
    """
    from pathlib import Path
    import json
    from services.schema_validator import validate_progressive_disclosure

    output = Path(output_dir)
    schemas_dir = output / "src" / "schemas"
    if not schemas_dir.exists():
        return {"passed": True, "issues": [], "retry_prompt": ""}

    issues: list[str] = []
    for path in schemas_dir.rglob("*.json"):
        # Skip any auto-generated meta files
        if path.name in ("registry.json", "load.json"):
            continue
        try:
            page = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        # page_type — read from the schema if present, else infer from path stem
        page["page_type"] = page.get("page_type") or path.stem
        # Relative path under schemas_dir → identifier for error messages
        rel = path.relative_to(schemas_dir).with_suffix("")
        for err in validate_progressive_disclosure(page):
            issues.append(f"{rel}: {err}")

    if not issues:
        return {"passed": True, "issues": [], "retry_prompt": ""}

    retry_prompt = (
        "The progressive-disclosure gate found Forms with too many flat "
        "fields. Wrap logical groups in an Accordion (collapsed panels per "
        "group) or Tabs (one tab per group) so readers can scan the form "
        "without overwhelm.\n\n"
        + "\n".join(f"- {i}" for i in issues)
    )
    return {"passed": False, "issues": issues, "retry_prompt": retry_prompt}


# ---------------------------------------------------------------------------
# Pages Coverage Gate (post-schema)
# ---------------------------------------------------------------------------

def check_pages_coverage(output_dir: str, plan: dict) -> dict:
    """Every page in plan.pages must have a schema file on disk.

    Uses nav_flow_emitter._schema_file_from_route to derive the expected
    path — keeps this gate in sync with where nav-flow will look. Pages
    without a route (or with non-dict entries) are skipped.

    Returns: {"passed": bool, "missing": list[str of routes]}.
    """
    from pathlib import Path
    from services.nav_flow_emitter import _schema_file_from_route

    out = Path(output_dir)
    missing: list[str] = []
    for p in (plan or {}).get("pages") or []:
        if not isinstance(p, dict):
            continue
        route = p.get("route")
        if not route:
            continue
        rel = _schema_file_from_route(route)
        if not (out / rel).exists():
            missing.append(route)
    return {"passed": not missing, "missing": missing}
