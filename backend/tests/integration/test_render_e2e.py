"""End-to-end: spin up the scaffold, render a known project page, assert PNG comes back.

Requires:
  - apps/render-scaffold dependencies installed (npm install)
  - A project present in output/<short_id> with at least one schema file
"""
import asyncio
import os
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from services.render_service.server import build_app
from httpx import ASGITransport, AsyncClient


REPO_ROOT = Path(__file__).resolve().parents[3]
SCAFFOLD_DIR = REPO_ROOT / "apps" / "render-scaffold"
SCAFFOLD_PORT = 6503


def _find_test_project() -> tuple[str, str] | None:
    """Find a project in output/ that has at least one schema file. Returns
    (short_id, page_route) or None if no suitable project exists."""
    output_root = REPO_ROOT / "output"
    if not output_root.exists():
        return None
    for proj in sorted(output_root.iterdir()):
        if not proj.is_dir():
            continue
        schemas_dir = proj / "src" / "schemas"
        if not schemas_dir.exists():
            continue
        for entity_dir in schemas_dir.iterdir():
            if not entity_dir.is_dir():
                continue
            for schema_file in entity_dir.glob("*.json"):
                page_route = f"/{entity_dir.name}/{schema_file.stem}"
                return proj.name, page_route
    return None


def _scaffold_deps_present() -> bool:
    """Return True if the scaffold's node_modules are installed (local or hoisted)."""
    # Local node_modules in render-scaffold itself
    if (SCAFFOLD_DIR / "node_modules").exists():
        return True
    # Hoisted workspace root node_modules (contains Next.js as 'next')
    if (REPO_ROOT / "node_modules" / "next").exists():
        return True
    return False


@pytest.fixture(scope="module")
def scaffold_proc():
    """Boot the scaffold dev server for the module's lifetime."""
    if not _scaffold_deps_present():
        pytest.skip("scaffold deps not installed; run npm install at repo root or apps/render-scaffold")
    if _find_test_project() is None:
        pytest.skip("no test project with schemas present in output/")

    # Free the port if anything is on it
    subprocess.run("lsof -ti:6503 | xargs kill -9 2>/dev/null || true", shell=True)
    proc = subprocess.Popen(
        ["npm", "run", "dev"],
        cwd=str(SCAFFOLD_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env={**os.environ},
    )
    # Wait up to 20s for the scaffold to start serving
    for _ in range(40):
        try:
            r = httpx.get(f"http://localhost:{SCAFFOLD_PORT}/", timeout=1.0)
            if r.status_code == 200:
                break
        except Exception:
            pass
        time.sleep(0.5)
    else:
        proc.terminate()
        pytest.skip("scaffold failed to boot within 20s")

    yield proc

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_render_returns_a_png(scaffold_proc):
    project = _find_test_project()
    assert project is not None  # Already skipped above if None
    short_id, page_route = project

    app = build_app(scaffold_url=f"http://localhost:{SCAFFOLD_PORT}")

    # build_app uses old-style @app.on_event decorators rather than a lifespan
    # context manager, so we manually drive startup and shutdown.
    await app.router.startup()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=60.0) as client:
            r = await client.post("/render", json={
                "projectId": short_id,
                "pageRoute": page_route,
                "viewport": "desktop",
            })
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["pngBytes"] > 1000  # At least a kilobyte
            assert body["pngBase64"].startswith("iVBOR")  # PNG magic in base64
    finally:
        await app.router.shutdown()
