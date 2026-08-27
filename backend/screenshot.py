"""Screenshot capture utility using Playwright via npx.

Two modes:
  1. capture_screenshot(output_dir) — starts its own dev server, captures root, kills server
  2. capture_page_screenshot(output_dir, port, route) — reuses existing server, captures a specific route
"""

import asyncio
import logging
import random
import signal
from pathlib import Path

logger = logging.getLogger(__name__)

# Dev server port range (for self-managed server mode)
_PORT_RANGE_START = 3100
_PORT_RANGE_END = 3199

# How long to wait for the dev server to be ready
_SERVER_POLL_INTERVAL = 1.0
_SERVER_TIMEOUT = 30.0

# Extra wait after server is ready for the page to fully render
_RENDER_SETTLE_SECONDS = 3


async def _find_free_port() -> int:
    """Pick a random port in our range."""
    return random.randint(_PORT_RANGE_START, _PORT_RANGE_END)


async def _wait_for_server(port: int, timeout: float = _SERVER_TIMEOUT) -> bool:
    """Poll localhost:{port} until it responds or we time out."""
    import httpx

    url = f"http://localhost:{port}"
    elapsed = 0.0
    async with httpx.AsyncClient(timeout=3) as client:
        while elapsed < timeout:
            try:
                resp = await client.get(url)
                if resp.status_code < 500:
                    return True
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout):
                pass
            await asyncio.sleep(_SERVER_POLL_INTERVAL)
            elapsed += _SERVER_POLL_INTERVAL
    return False


async def capture_screenshot(output_dir: str) -> str | None:
    """
    Start the dev server, screenshot the page, kill the server.

    Returns the path to the screenshot file, or None on failure.
    """
    project_path = Path(output_dir)
    screenshot_path = project_path / "generated_screenshot.png"

    port = await _find_free_port()
    server_proc = None

    try:
        # 1. Start the dev server
        server_proc = await asyncio.create_subprocess_exec(
            "npx", "next", "dev", "--port", str(port),
            cwd=str(project_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            # Use a new process group so we can kill the whole tree
            preexec_fn=lambda: __import__("os").setpgrp(),
        )

        # 2. Wait for the server to be ready
        ready = await _wait_for_server(port)
        if not ready:
            return None

        # 3. Let the page settle (JS hydration, fonts, images)
        await asyncio.sleep(_RENDER_SETTLE_SECONDS)

        # 4. Take screenshot with Playwright
        screenshot_proc = await asyncio.create_subprocess_exec(
            "npx", "playwright", "screenshot",
            "--browser", "chromium",
            "--full-page",
            "--viewport-size", "1440,900",
            f"http://localhost:{port}",
            str(screenshot_path),
            cwd=str(project_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await screenshot_proc.communicate()

        if screenshot_proc.returncode != 0:
            # Try installing Playwright browsers first, then retry
            install_proc = await asyncio.create_subprocess_exec(
                "npx", "playwright", "install", "chromium",
                cwd=str(project_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await install_proc.communicate()

            screenshot_proc = await asyncio.create_subprocess_exec(
                "npx", "playwright", "screenshot",
                "--browser", "chromium",
                "--full-page",
                "--viewport-size", "1440,900",
                f"http://localhost:{port}",
                str(screenshot_path),
                cwd=str(project_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await screenshot_proc.communicate()

        if screenshot_path.exists():
            return str(screenshot_path)

        return None

    finally:
        # 5. Kill the dev server process group
        if server_proc and server_proc.returncode is None:
            try:
                import os

                os.killpg(os.getpgid(server_proc.pid), signal.SIGTERM)
                # Give it a moment to shut down gracefully
                try:
                    await asyncio.wait_for(server_proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    os.killpg(os.getpgid(server_proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass


async def capture_page_screenshot(
    output_dir: str,
    port: int,
    route: str = "/",
    output_name: str | None = None,
    viewport: str = "1440,900",
) -> str | None:
    """Capture a screenshot of a specific route on an already-running preview server.

    Unlike capture_screenshot(), this does NOT start its own dev server.
    It reuses an existing server on the given port.

    Args:
        output_dir: Project output directory (screenshots saved here)
        port: Port of the running preview server
        route: Route to screenshot (e.g., "/dashboard", "/patients/new")
        output_name: Output filename (default: derived from route)
        viewport: Viewport dimensions as "width,height"

    Returns:
        Path to the screenshot file, or None on failure.
    """
    project_path = Path(output_dir)
    screenshots_dir = project_path / "screenshots"
    screenshots_dir.mkdir(exist_ok=True)

    if output_name is None:
        # Convert route to filename: /dashboard → dashboard.png, /patients/new → patients_new.png
        clean = route.strip("/").replace("/", "_") or "root"
        output_name = f"{clean}.png"

    screenshot_path = screenshots_dir / output_name
    url = f"http://localhost:{port}{route}"

    # Verify the server is responding
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(url)
            if resp.status_code >= 500:
                logger.warning("Page %s returned %d — skipping screenshot", route, resp.status_code)
                return None
    except (httpx.ConnectError, httpx.ReadTimeout):
        logger.warning("Preview server not responding on port %d", port)
        return None

    # Wait for page to settle (JS hydration, data fetching)
    await asyncio.sleep(2)

    # Take screenshot with Playwright
    try:
        proc = await asyncio.create_subprocess_exec(
            "npx", "playwright", "screenshot",
            "--browser", "chromium",
            "--full-page",
            "--viewport-size", viewport,
            url,
            str(screenshot_path),
            cwd=str(project_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.wait_for(proc.communicate(), timeout=30)

        if proc.returncode != 0 and not screenshot_path.exists():
            # Try installing browsers first
            install = await asyncio.create_subprocess_exec(
                "npx", "playwright", "install", "chromium",
                cwd=str(project_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await install.communicate()

            # Retry
            proc = await asyncio.create_subprocess_exec(
                "npx", "playwright", "screenshot",
                "--browser", "chromium",
                "--full-page",
                "--viewport-size", viewport,
                url,
                str(screenshot_path),
                cwd=str(project_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=30)

    except asyncio.TimeoutError:
        logger.warning("Screenshot timed out for %s", route)
        return None
    except Exception as e:
        logger.warning("Screenshot failed for %s: %s", route, e)
        return None

    if screenshot_path.exists():
        logger.info("Screenshot captured: %s → %s", route, screenshot_path.name)
        return str(screenshot_path)

    return None


async def capture_key_pages(
    output_dir: str,
    port: int,
    routes: list[str] | None = None,
) -> list[dict]:
    """Capture screenshots of key pages for visual review.

    If routes not provided, discovers them from src/app/**/page.tsx.

    Returns list of {"route": str, "screenshot": str} dicts.
    """
    if routes is None:
        # Auto-discover routes from page files
        app_dir = Path(output_dir) / "src" / "app"
        routes = ["/"]
        if app_dir.exists():
            for page in sorted(app_dir.rglob("page.tsx")):
                if "node_modules" in str(page):
                    continue
                rel = page.relative_to(app_dir)
                parts = list(rel.parent.parts)
                # Skip route groups like (dashboard) — unwrap them
                parts = [p for p in parts if not p.startswith("(") and p != "."]
                if parts:
                    route = "/" + "/".join(p for p in parts if not p.startswith("["))
                    if route not in routes and "[" not in route:
                        routes.append(route)

        # Limit to key pages: dashboard + first 2 entity routes + first form
        if len(routes) > 5:
            key = [r for r in routes if r in ("/", "/dashboard")]
            entity_routes = [r for r in routes if r.count("/") == 1 and r not in key]
            form_routes = [r for r in routes if r.endswith("/new")]
            routes = key + entity_routes[:2] + form_routes[:1]

    results = []
    for route in routes:
        screenshot = await capture_page_screenshot(output_dir, port, route)
        if screenshot:
            results.append({"route": route, "screenshot": screenshot})

    return results
