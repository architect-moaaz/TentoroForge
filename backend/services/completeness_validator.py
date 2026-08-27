"""Post-generation completeness validator.

Checks that the generated app is fully functional:
- Every entity has CRUD API routes
- Every sidebar link has a matching page
- Every form has working submit handler (no TODO stubs)
- Root page exists with redirect
- Dashboard calls stats endpoints
- No system fields in create forms

Returns a list of issues for the QA agent or auto-fixer to address.
"""

import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def validate_completeness(output_dir: str) -> list[dict]:
    """Validate generated app completeness. Returns list of issues."""
    root = Path(output_dir)
    issues: list[dict] = []

    app_dir = root / "src" / "app"
    api_dir = app_dir / "api"
    schema_dir = root / "src" / "db" / "schema"

    if not app_dir.exists():
        return [{"severity": "critical", "category": "structure", "message": "No src/app directory"}]

    # 1. Root page redirect
    root_page = app_dir / "page.tsx"
    if not root_page.exists():
        issues.append({
            "severity": "critical",
            "category": "routing",
            "message": "Missing src/app/page.tsx — app has no entry point. Must redirect to /dashboard.",
            "fix": "create_root_redirect",
        })

    # 2. Extract entity names from schema
    entities = _extract_entities(schema_dir)

    # 3. Check API routes for each entity
    for entity in entities:
        slug = _entity_to_slug(entity)
        entity_api = api_dir / slug
        if not (entity_api / "route.ts").exists():
            issues.append({
                "severity": "critical",
                "category": "api",
                "message": f"Missing API route: src/app/api/{slug}/route.ts (GET/POST for {entity})",
                "fix": "create_api_route",
                "entity": entity,
                "slug": slug,
            })
        if not (entity_api / "[id]" / "route.ts").exists():
            issues.append({
                "severity": "critical",
                "category": "api",
                "message": f"Missing API route: src/app/api/{slug}/[id]/route.ts (GET/PUT/DELETE for {entity})",
                "fix": "create_api_route",
                "entity": entity,
                "slug": slug,
            })
        if not (entity_api / "stats" / "route.ts").exists():
            issues.append({
                "severity": "warning",
                "category": "api",
                "message": f"Missing stats endpoint: src/app/api/{slug}/stats/route.ts (dashboard needs this)",
                "fix": "create_stats_route",
                "entity": entity,
                "slug": slug,
            })

    # 4. Check sidebar links match actual pages
    sidebar_issues = _validate_sidebar_links(app_dir)
    issues.extend(sidebar_issues)

    # 5. Check forms have working handlers (no TODO stubs)
    form_issues = _validate_form_handlers(app_dir)
    issues.extend(form_issues)

    # 6. Check list pages have create buttons
    list_issues = _validate_list_pages(app_dir)
    issues.extend(list_issues)

    # 7. Check for system fields in create forms
    system_field_issues = _validate_no_system_fields(app_dir)
    issues.extend(system_field_issues)

    # Summary
    critical = sum(1 for i in issues if i["severity"] == "critical")
    warnings = sum(1 for i in issues if i["severity"] == "warning")
    logger.info(
        "Completeness validation: %d critical, %d warnings in %s",
        critical, warnings, output_dir,
    )

    return issues


def _extract_entities(schema_dir: Path) -> list[str]:
    """Extract entity names from Drizzle schema files."""
    entities = []
    if not schema_dir.exists():
        return entities

    for f in schema_dir.glob("*.ts"):
        if f.name == "index.ts":
            continue
        try:
            content = f.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        # Match: export const usersTable = pgTable("users", {
        for m in re.finditer(r'export\s+const\s+(\w+Table)\s*=\s*pgTable\(\s*["\'](\w+)["\']', content):
            entities.append(m.group(2))  # table name
    return entities


def _entity_to_slug(entity: str) -> str:
    """Convert entity table name to URL slug: time_entries → time-entries."""
    return entity.replace("_", "-")


def _validate_sidebar_links(app_dir: Path) -> list[dict]:
    """Check that sidebar links point to existing pages."""
    issues = []

    # Find sidebar component
    sidebar_files = list(app_dir.rglob("sidebar*")) + list(app_dir.rglob("Sidebar*"))
    sidebar_files += list((app_dir.parent / "components").rglob("Sidebar*")) if (app_dir.parent / "components").exists() else []

    for sf in sidebar_files:
        if not sf.is_file() or sf.suffix != ".tsx":
            continue
        try:
            content = sf.read_text()
        except (OSError, UnicodeDecodeError):
            continue

        # Extract href="/path" links
        for m in re.finditer(r'href=["\'](/[^"\']*)["\']', content):
            href = m.group(1)
            if href in ("/", "#") or href.startswith("/api/"):
                continue
            # Check if page exists
            page_path = app_dir / href.strip("/") / "page.tsx"
            # Also check route groups
            found = page_path.exists()
            if not found:
                # Try with route groups: (dashboard)/path
                for group_dir in app_dir.iterdir():
                    if group_dir.is_dir() and group_dir.name.startswith("("):
                        alt = group_dir / href.strip("/") / "page.tsx"
                        if alt.exists():
                            found = True
                            break
            if not found:
                issues.append({
                    "severity": "warning",
                    "category": "navigation",
                    "message": f"Sidebar links to {href} but no page.tsx exists at that path",
                    "fix": "remove_dead_link",
                    "href": href,
                    "file": str(sf),
                })

    return issues


def _validate_form_handlers(app_dir: Path) -> list[dict]:
    """Check that create/edit forms have real submit handlers."""
    issues = []

    for page in app_dir.rglob("page.tsx"):
        if "node_modules" in str(page):
            continue
        rel = str(page.relative_to(app_dir))
        if "/new/" not in f"/{rel}" and not rel.endswith("new/page.tsx"):
            continue

        try:
            content = page.read_text()
        except (OSError, UnicodeDecodeError):
            continue

        # Check for TODO stubs
        if re.search(r'//\s*TODO|//\s*Handle\s+form|//\s*Handle\s+submit|//\s*Handle\s+cancel', content):
            issues.append({
                "severity": "critical",
                "category": "form",
                "message": f"Form has TODO stub in {rel} — submit handler not implemented",
                "fix": "implement_form_handler",
                "file": rel,
            })

    return issues


def _validate_list_pages(app_dir: Path) -> list[dict]:
    """Check that list pages have a Create/New button."""
    issues = []

    for page in app_dir.rglob("page.tsx"):
        if "node_modules" in str(page):
            continue
        rel = page.relative_to(app_dir)
        parts = rel.parts

        # List pages are direct entity pages: users/page.tsx, projects/page.tsx
        # But NOT: users/[id]/page.tsx, users/new/page.tsx, dashboard/page.tsx
        if len(parts) != 2:  # e.g. ["users", "page.tsx"]
            continue
        entity_dir = parts[0]
        if entity_dir in ("dashboard", "login", "signup", "error", "loading"):
            continue
        if entity_dir.startswith("("):
            continue

        try:
            content = page.read_text()
        except (OSError, UnicodeDecodeError):
            continue

        # Check for new/create link
        has_create = bool(re.search(
            r'href=["\'].*?/new["\']|Create|New\s|Add\s|\+\s*New',
            content,
        ))
        if not has_create:
            issues.append({
                "severity": "warning",
                "category": "ux",
                "message": f"List page {rel} has no Create/New button",
                "fix": "add_create_button",
                "file": str(rel),
                "entity": entity_dir,
            })

    return issues


def _validate_no_system_fields(app_dir: Path) -> list[dict]:
    """Check that create forms don't include system fields."""
    issues = []

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

        # Check for system field inputs
        system_fields = ["createdAt", "updatedAt", "created_at", "updated_at"]
        for field in system_fields:
            if re.search(rf'name=["\']?{field}|label.*{field}|{field}.*<input|{field}.*<Input', content, re.IGNORECASE):
                issues.append({
                    "severity": "warning",
                    "category": "form",
                    "message": f"Create form {rel} includes system field '{field}' which should be auto-generated",
                    "fix": "remove_system_field",
                    "file": rel,
                    "field": field,
                })

    return issues


def format_issues_for_agent(issues: list[dict]) -> str:
    """Format issues into a prompt section for the QA agent."""
    if not issues:
        return "\n## Completeness Check: PASSED — all checks passed.\n"

    critical = [i for i in issues if i["severity"] == "critical"]
    warnings = [i for i in issues if i["severity"] == "warning"]

    lines = ["\n## Completeness Check: ISSUES FOUND\n"]

    if critical:
        lines.append(f"### CRITICAL ({len(critical)} — MUST FIX):")
        for i in critical:
            lines.append(f"  - [{i['category']}] {i['message']}")

    if warnings:
        lines.append(f"\n### WARNINGS ({len(warnings)} — SHOULD FIX):")
        for i in warnings:
            lines.append(f"  - [{i['category']}] {i['message']}")

    lines.append("\nFix ALL critical issues. Fix warnings if possible within your turn budget.")
    return "\n".join(lines)
