"""Post-generation browser validation using Playwright.

Starts the dev server, traces all pages with a headless browser,
collects console errors, 404s, JS exceptions, and broken interactions.
Returns a structured report for the fix agent.

This closes the gap between "it compiles" and "it works."
"""

import asyncio
import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

MAX_BROWSER_FIX_CYCLES = 2


async def run_browser_validation(output_dir: str, port: int) -> dict:
    """Trace all pages of the generated app via headless browser.

    Args:
        output_dir: Path to the generated app
        port: Port where the dev server is running

    Returns:
        {
            "passed": bool,
            "page_errors": [...],     # per-page errors
            "missing_routes": [...],  # 404 pages
            "missing_apis": [...],    # 404 API calls
            "console_errors": [...],  # JS console errors
            "js_exceptions": [...],   # uncaught exceptions
            "summary": str,
            "fix_prompt": str | None  # prompt to send to fix agent
        }
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning("Playwright not installed — skipping browser validation")
        return {"passed": True, "page_errors": [], "missing_routes": [],
                "missing_apis": [], "console_errors": [], "js_exceptions": [],
                "summary": "Skipped (playwright not installed)", "fix_prompt": None}

    base = f"http://localhost:{port}"

    # Discover pages from the file system
    app_dir = Path(output_dir) / "src" / "app"
    pages = _discover_pages(app_dir)
    if not pages:
        return {"passed": True, "page_errors": [], "missing_routes": [],
                "missing_apis": [], "console_errors": [], "js_exceptions": [],
                "summary": "No pages found", "fix_prompt": None}

    result = {
        "passed": True,
        "page_errors": [],
        "missing_routes": [],
        "missing_apis": [],
        "console_errors": [],
        "js_exceptions": [],
    }

    seen_apis = set()
    seen_errors = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await context.new_page()

        for route in pages:
            url = f"{base}{route}"
            page_console_errors = []
            page_network_errors = []
            page_exceptions = []

            def on_console(msg):
                if msg.type == "error":
                    text = msg.text[:300]
                    if "Failed to load resource" not in text:
                        key = f"console|{route}|{text[:80]}"
                        if key not in seen_errors:
                            seen_errors.add(key)
                            page_console_errors.append(text)

            def on_pageerror(error):
                text = str(error)[:300]
                page_exceptions.append(text)

            def on_response(response):
                if response.status >= 400 and not response.url.endswith(".map"):
                    rel_url = response.url.replace(base, "")
                    if rel_url.startswith("/api/auth/"):
                        return  # Auth errors handled separately
                    key = f"net|{rel_url}|{response.status}"
                    if key not in seen_apis:
                        seen_apis.add(key)
                        page_network_errors.append({
                            "url": rel_url,
                            "status": response.status,
                            "page": route,
                        })

            page.on("console", on_console)
            page.on("pageerror", on_pageerror)
            page.on("response", on_response)

            try:
                resp = await page.goto(url, wait_until="networkidle", timeout=15000)
                status = resp.status if resp else 0

                if status == 404:
                    result["missing_routes"].append(route)

                await page.wait_for_timeout(1500)

                # ── Visual quality checks ──
                try:
                    visual_issues = await page.evaluate("""() => {
                        const issues = [];
                        const body = document.body;
                        const computed = window.getComputedStyle(body);

                        // Check if CSS variables are defined
                        const root = document.documentElement;
                        const rootStyle = window.getComputedStyle(root);
                        const hasPrimary = rootStyle.getPropertyValue('--primary').trim();
                        const hasBackground = rootStyle.getPropertyValue('--background').trim();
                        if (!hasPrimary && !hasBackground) {
                            issues.push('CSS_VARS_MISSING: --primary and --background not defined — design spec CSS not loaded');
                        }

                        // Check if body has default white background (unstyled)
                        const bgColor = computed.backgroundColor;
                        if (bgColor === 'rgba(0, 0, 0, 0)' || bgColor === 'rgb(255, 255, 255)') {
                            // Check if root has background
                            const rootBg = rootStyle.getPropertyValue('--background').trim();
                            if (!rootBg) {
                                issues.push('NO_STYLING: Page has default white background — CSS/Tailwind not applied');
                            }
                        }

                        // Check if any Tailwind classes resolved (look for computed styles)
                        const cards = document.querySelectorAll('[class*="card"], [class*="rounded"]');
                        if (cards.length === 0 && document.querySelectorAll('button, input, a').length > 3) {
                            issues.push('NO_COMPONENTS: Page has buttons/inputs but no styled cards/containers');
                        }

                        // Check for hardcoded gray colors (sign of unstyled page)
                        const allText = body.innerHTML;
                        const hardcodedCount = (allText.match(/bg-gray-|text-gray-|border-gray-/g) || []).length;
                        const cssVarCount = (allText.match(/bg-background|text-foreground|bg-primary|text-primary|bg-card/g) || []).length;
                        if (hardcodedCount > 5 && cssVarCount === 0) {
                            issues.push('HARDCODED_COLORS: Page uses hardcoded gray colors instead of design spec CSS variables');
                        }

                        return issues;
                    }""")

                    for vi in visual_issues:
                        result["page_errors"].append({
                            "page": route,
                            "error": f"VISUAL: {vi}",
                        })
                except Exception:
                    pass  # Visual checks are best-effort

            except Exception as e:
                result["page_errors"].append({
                    "page": route,
                    "error": f"Failed to load: {str(e)[:200]}",
                })

            page.remove_listener("console", on_console)
            page.remove_listener("pageerror", on_pageerror)
            page.remove_listener("response", on_response)

            # Collect results
            for err in page_console_errors:
                result["console_errors"].append({"page": route, "error": err})
            for exc in page_exceptions:
                result["js_exceptions"].append({"page": route, "error": exc})
            for net_err in page_network_errors:
                if net_err["status"] == 404 and net_err["url"].startswith("/api/"):
                    result["missing_apis"].append(net_err)
                else:
                    result["page_errors"].append({
                        "page": route,
                        "error": f"[{net_err['status']}] {net_err['url']}",
                    })

        await browser.close()

    # Determine pass/fail
    critical_count = (
        len(result["missing_routes"]) +
        len(result["missing_apis"]) +
        len(result["js_exceptions"])
    )
    result["passed"] = critical_count == 0

    # Build summary
    parts = []
    if result["missing_routes"]:
        parts.append(f"{len(result['missing_routes'])} pages return 404")
    if result["missing_apis"]:
        parts.append(f"{len(result['missing_apis'])} API routes return 404")
    if result["js_exceptions"]:
        parts.append(f"{len(result['js_exceptions'])} JS exceptions")
    if result["console_errors"]:
        parts.append(f"{len(result['console_errors'])} console errors")
    if result["page_errors"]:
        parts.append(f"{len(result['page_errors'])} page errors")

    result["summary"] = "; ".join(parts) if parts else "All pages load cleanly"

    # Build fix prompt if issues found
    if not result["passed"]:
        result["fix_prompt"] = _build_fix_prompt(result)

    return result


def _discover_pages(app_dir: Path) -> list[str]:
    """Find all routes from the file system."""
    if not app_dir.exists():
        return []

    routes = set()
    for page_file in app_dir.rglob("page.tsx"):
        if "node_modules" in str(page_file):
            continue
        rel = page_file.parent.relative_to(app_dir)
        parts = []
        for part in rel.parts:
            if part.startswith("("):  # route groups like (dashboard)
                continue
            if part.startswith("["):  # dynamic segments — skip
                break
            parts.append(part)
        else:
            route = "/" + "/".join(parts) if parts else "/"
            routes.add(route)

    # Always include root
    routes.add("/")

    return sorted(routes)


def _build_fix_prompt(result: dict) -> str:
    """Build a targeted fix prompt from browser validation results."""
    lines = [
        "## BROWSER VALIDATION FAILED — FIX THESE RUNTIME ISSUES\n",
        "The app compiles but has runtime errors detected by automated browser testing.\n",
    ]

    if result["missing_routes"]:
        lines.append("### Pages returning 404:")
        for route in result["missing_routes"]:
            lines.append(f"  - `{route}` — create the page or fix the route")

    if result["missing_apis"]:
        lines.append("\n### API routes returning 404 (pages call these but they don't exist):")
        for api in result["missing_apis"]:
            lines.append(f"  - `{api['url']}` — called by page `{api['page']}`")

    if result["js_exceptions"]:
        lines.append("\n### JavaScript exceptions (app crashes):")
        for exc in result["js_exceptions"][:10]:
            lines.append(f"  - Page `{exc['page']}`: {exc['error'][:150]}")

    if result["console_errors"]:
        lines.append("\n### Console errors:")
        for err in result["console_errors"][:10]:
            lines.append(f"  - Page `{err['page']}`: {err['error'][:150]}")

    lines.append(
        "\nFix these issues by reading the failing files and applying targeted repairs. "
        "Do NOT rewrite entire files — make minimal changes to fix each specific issue."
    )

    return "\n".join(lines)
