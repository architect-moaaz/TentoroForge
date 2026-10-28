"""No file of a project is served to someone who has not signed in.

`main.py` kept the first generator's routes, with no sign-in: `/asset?path=`
served any file under a project — the app's `.env.local` with its database
address, signing secret and encryption key — and a published app's address
names its project. forge-v3 answered it with 200 to a signed-out request
(2026-10-26). `/api/generate` started a model run for anyone, `/refine`
changed any project. They are gone; `/asset` serves only a project's public
folder, which the app publishes anyway.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

MAIN = Path(__file__).resolve().parents[2] / "main.py"


@pytest.fixture
def project(tmp_path, monkeypatch):
    import main
    monkeypatch.setattr(main, "OUTPUT_BASE", tmp_path)
    root = tmp_path / "abc12345"
    (root / "app" / "public").mkdir(parents=True)
    (root / "public" / "images").mkdir(parents=True)
    (root / "app" / ".env.local").write_text("DATABASE_URL=postgres://secret\n")
    (root / ".env.local").write_text("SECRET=1\n")
    (root / "app" / "public" / "logo.svg").write_text("<svg/>")
    (root / "public" / "images" / "a.png").write_bytes(b"\x89PNG")
    (root / "public" / ".hidden").write_text("x")
    return root


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["app/.env.local", ".env.local", "public/../app/.env.local",
                                  "public/../.env.local", "public/.hidden", "app/package.json", "/etc/passwd",
                                  "public/../../abc12345/.env.local"])
async def test_nothing_outside_the_public_folder_is_served(client, project, path):
    r = await client.get(f"/api/projects/{project.name}/asset", params={"path": path})
    assert r.status_code == 404, (path, r.status_code)
    assert b"secret" not in r.content and b"SECRET" not in r.content


@pytest.mark.asyncio
async def test_a_public_picture_is_still_served_to_the_editor(client, project):
    r = await client.get(f"/api/projects/{project.name}/asset", params={"path": "public/images/a.png"})
    assert r.status_code == 200 and r.content == b"\x89PNG"
    r = await client.get(f"/api/projects/{project.name}/asset", params={"path": "public/logo.svg"})
    assert r.status_code == 200 and r.content == b"<svg/>"          # the app's own public folder


@pytest.mark.asyncio
async def test_the_first_generators_routes_are_gone(client, project):
    assert (await client.post("/api/generate", json={"figma_url": "x"})).status_code in (404, 405)
    assert (await client.post(f"/api/projects/{project.name}/refine", json={"prompt": "x"})).status_code in (404, 405)
    for path in ("files", "download"):
        r = await client.get(f"/api/projects/{project.name}/{path}")
        assert r.status_code in (401, 403, 404), (path, r.status_code)   # the signed-in routers answer
    r = await client.get(f"/api/projects/{project.name}/file", params={"path": "app/.env.local"})
    assert r.status_code in (401, 403, 404)


def test_main_defines_no_route_but_the_public_folder():
    """A route written on `app` in main.py has no router's sign-in in front of
    it; every route lives in a router."""
    routes = []
    for node in ast.parse(MAIN.read_text()).body:
        for d in getattr(node, "decorator_list", []):
            if isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and getattr(d.func.value, "id", "") == "app" \
                    and d.func.attr in ("get", "post", "put", "patch", "delete", "api_route", "websocket"):
                routes.append(d.args[0].value if d.args else "?")
    assert routes == ["/api/projects/{project_id}/asset"], routes
