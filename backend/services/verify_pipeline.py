"""Verify Pipeline — automated quality checks after generation.

Replaces: qa_agent + validator + indexer + visual reviewer
Zero LLM cost. Deterministic. Catches what agents missed.

Steps:
1. npm run build
2. Flow validation (navigation-flow.json vs actual pages)
3. Browser validation (Playwright — pages load, no errors, CSS renders)
4. CSS variable check
5. Deterministic indexer (file system scan → app-model.json)

Returns structured report. If issues found, caller feeds them to Feature Agent.
"""

import asyncio
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)


async def run_verify_pipeline(output_dir: str, plan: dict | None = None, port: int | None = None) -> dict:
    """Run all verification steps.

    Args:
        output_dir: Generated app directory
        port: If provided, run browser validation against this port

    Returns:
        {
            "passed": bool,
            "build": { "passed": bool, "errors": [...] },
            "flow": { "passed": bool, "issues": [...] },
            "browser": { "passed": bool, "issues": [...] },
            "css": { "passed": bool, "issues": [...] },
            "fix_prompt": str | None,  # for Feature Agent if issues found
        }
    """
    result = {
        "passed": True,
        "build": {"passed": True, "errors": []},
        "flow": {"passed": True, "issues": []},
        "browser": {"passed": True, "issues": []},
        "css": {"passed": True, "issues": []},
        "fix_prompt": None,
    }

    # ── Step 1: Build ──
    logger.info("[Verify] Running npm run build...")
    build_result = await _run_build(output_dir)
    result["build"] = build_result
    if not build_result["passed"]:
        result["passed"] = False

    # ── Step 2: Flow validation ──
    logger.info("[Verify] Checking navigation flow...")
    try:
        from services.flow_validator import validate_navigation_flow
        flow_result = validate_navigation_flow(output_dir)
        result["flow"] = {
            "passed": flow_result["passed"],
            "issues": flow_result.get("issues", []),
        }
        if not flow_result["passed"]:
            result["passed"] = False
    except Exception as e:
        logger.warning("[Verify] Flow validation skipped: %s", e)

    # ── Step 2b: Page completeness check ──
    if plan:
        logger.info("[Verify] Checking page completeness...")
        page_result = _check_page_completeness(output_dir, plan)
        if not page_result["passed"]:
            result["passed"] = False
            result["pages"] = page_result

    # ── Step 3: CSS check ──
    logger.info("[Verify] Checking CSS...")
    css_result = _check_css(output_dir)
    result["css"] = css_result
    if not css_result["passed"]:
        result["passed"] = False

    # ── Step 4: Browser validation ──
    if port:
        logger.info("[Verify] Running browser validation on port %d...", port)
        try:
            from services.browser_validator import run_browser_validation
            browser_result = await run_browser_validation(output_dir, port)
            result["browser"] = {
                "passed": browser_result["passed"],
                "issues": (
                    [{"page": r, "error": "404"} for r in browser_result.get("missing_routes", [])] +
                    browser_result.get("page_errors", []) +
                    browser_result.get("js_exceptions", []) +
                    browser_result.get("console_errors", [])
                ),
            }
            if not browser_result["passed"]:
                result["passed"] = False
        except Exception as e:
            logger.warning("[Verify] Browser validation skipped: %s", e)

    # ── Step 5: Generate app-model.json (deterministic indexer) ──
    logger.info("[Verify] Generating app-model.json...")
    try:
        _generate_app_model(output_dir)
    except Exception as e:
        logger.warning("[Verify] Indexer failed: %s", e)

    # ── Build fix prompt if needed ──
    if not result["passed"]:
        result["fix_prompt"] = _build_fix_prompt(result)

    return result


async def _run_build(output_dir: str) -> dict:
    """Run npm run build and parse errors."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "npm", "run", "build",
            cwd=output_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
        output = (stdout or b"").decode() + (stderr or b"").decode()

        if proc.returncode == 0:
            return {"passed": True, "errors": []}

        # Parse errors
        errors = []
        for line in output.split("\n"):
            if "Type error:" in line or "Error:" in line or "Module not found" in line:
                errors.append(line.strip()[:200])

        return {"passed": False, "errors": errors[:20]}
    except asyncio.TimeoutError:
        return {"passed": False, "errors": ["Build timed out after 120s"]}
    except Exception as e:
        return {"passed": False, "errors": [f"Build failed: {str(e)[:200]}"]}


def _check_page_completeness(output_dir: str, plan: dict) -> dict:
    """Check that every entity has list + detail + create pages, and forms have required fields."""
    root = Path(output_dir)
    app_dir = root / "src" / "app"
    models = plan.get("data_models", [])
    issues = []

    for model in models:
        name = model.get("name", "")
        if not name or name in ("User", "WorkflowTask"):
            continue
        slug = re.sub(r'(?<!^)(?=[A-Z])', '-', name).lower()

        # Check pages exist
        for page_type, subpath in [("list", "page.tsx"), ("detail", "[id]/page.tsx"), ("create", "new/page.tsx")]:
            found = False
            for base in [app_dir, *[d for d in app_dir.iterdir() if d.is_dir() and d.name.startswith("(")]]:
                if (base / slug / subpath).exists():
                    page_file = base / slug / subpath
                    found = True
                    # Check create page has form fields
                    if page_type == "create":
                        try:
                            content = page_file.read_text()
                            # Count form inputs
                            input_count = content.count("<Input") + content.count("<Select") + content.count("<Textarea")
                            required_fields = [f for f in model.get("fields", [])
                                              if f.get("name") not in ("id", "createdAt", "updatedAt")
                                              and not f.get("nullable", False)
                                              and not f.get("default")]
                            if input_count < max(2, len(required_fields) // 2):
                                issues.append(
                                    f"{name} create form has {input_count} inputs but schema has "
                                    f"{len(required_fields)} required fields — form is incomplete"
                                )
                        except (OSError, UnicodeDecodeError):
                            pass
                    break
            if not found:
                issues.append(f"MISSING: /{slug}/{subpath} for entity {name}")

    return {"passed": len(issues) == 0, "issues": issues}


def _check_css(output_dir: str) -> dict:
    """Check globals.css for common issues."""
    root = Path(output_dir)
    css_file = root / "src" / "app" / "globals.css"
    issues = []

    if not css_file.exists():
        return {"passed": False, "issues": ["globals.css not found"]}

    try:
        content = css_file.read_text()

        # Check for the border bug
        if "* {\n" in content or "* {" in content:
            # Find what follows * {
            match = re.search(r'\*\s*\{[^}]*\}', content)
            if match:
                block = match.group()
                if "@apply border;" in block and "@apply border-border" not in block:
                    issues.append("CRITICAL: '* { @apply border }' found — should be '* { @apply border-border }'")

        # Check CSS variables are defined
        if "--primary:" not in content:
            issues.append("--primary CSS variable not defined")
        if "--background:" not in content:
            issues.append("--background CSS variable not defined")

        # Check for placeholder values still present
        if "__CSS_" in content:
            issues.append("CSS placeholder values not replaced (e.g., __CSS_PRIMARY__)")

        # Check for hardcoded gray colors in the CSS itself
        if "bg-gray-" in content or "text-gray-" in content:
            issues.append("Hardcoded gray colors in globals.css — use CSS variables")

    except (OSError, UnicodeDecodeError) as e:
        issues.append(f"Cannot read globals.css: {e}")

    return {"passed": len(issues) == 0, "issues": issues}


def _generate_app_model(output_dir: str):
    """Deterministic indexer — scan filesystem and generate app-model.json."""
    root = Path(output_dir)
    app_dir = root / "src" / "app"
    schema_dir = root / "src" / "db" / "schema"

    model: dict = {
        "name": root.name,
        "entities": {},
        "pages": [],
        "routes": [],
    }

    # Scan schema files
    if schema_dir.exists():
        for f in schema_dir.glob("*.ts"):
            if f.name in ("index.ts", "relations.ts"):
                continue
            entity_name = f.stem
            model["entities"][entity_name] = {
                "schema": str(f.relative_to(root)),
                "type": f"src/types/{entity_name}.ts",
            }

    # Scan pages
    if app_dir.exists():
        for page_file in app_dir.rglob("page.tsx"):
            if "node_modules" in str(page_file):
                continue
            rel = page_file.parent.relative_to(app_dir)
            parts = [p for p in rel.parts if not p.startswith("(") and not p.startswith("[")]
            route = "/" + "/".join(parts) if parts else "/"
            model["pages"].append({
                "route": route,
                "file": str(page_file.relative_to(root)),
            })

    # Scan API routes
    api_dir = app_dir / "api"
    if api_dir.exists():
        for route_file in api_dir.rglob("route.ts"):
            if "node_modules" in str(route_file):
                continue
            model["routes"].append(str(route_file.relative_to(root)))

    # Write
    output = root / "app-model.json"
    output.write_text(json.dumps(model, indent=2))


def _build_fix_prompt(result: dict) -> str:
    """Build a targeted fix prompt from verification results."""
    lines = [
        "## VERIFICATION FAILED — FIX THESE ISSUES\n",
    ]

    if not result["build"]["passed"]:
        lines.append("### Build Errors:")
        for err in result["build"]["errors"][:10]:
            lines.append(f"  - {err}")
        lines.append("")

    if not result["flow"]["passed"]:
        lines.append("### Flow Validation Issues:")
        for issue in result["flow"]["issues"][:10]:
            lines.append(f"  - {issue}")
        lines.append("")

    if not result["css"]["passed"]:
        lines.append("### CSS Issues:")
        for issue in result["css"]["issues"]:
            lines.append(f"  - {issue}")
        lines.append("")

    if not result["browser"]["passed"]:
        lines.append("### Browser Issues:")
        for issue in result["browser"]["issues"][:10]:
            if isinstance(issue, dict):
                lines.append(f"  - {issue.get('page', '?')}: {issue.get('error', '?')}")
            else:
                lines.append(f"  - {issue}")
        lines.append("")

    lines.append(
        "Fix these issues. Read the failing files, apply minimal fixes. "
        "Do NOT modify template files (auth, layout, providers, UI components)."
    )

    return "\n".join(lines)
