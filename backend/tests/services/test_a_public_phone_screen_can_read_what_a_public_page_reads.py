"""A public screen of a gated native app can read.

The middleware answered every call without a token with a 401 before `/api/read` ran, so a public phone screen read
nothing, and the 401 made the phone sign the person out. The read route decides for itself who gets what, so for a native
app that has a public page of its own the middleware leaves `/api/read` to answer. A website, and a native app whose only
public pages are the sign-in ones, keep the gate exactly as it was."""
from __future__ import annotations

from services.blueprint.projection import project_middleware


def doc(native: bool, public_page: bool):
    pages = [
        {"id": "PAGE-001", "route": "/login", "pattern": "auth", "auth": "login", "access": "public"},
        {"id": "PAGE-002", "route": "/orders", "pattern": "entity_list", "access": "authenticated"},
    ]
    if public_page:
        pages.append({"id": "PAGE-003", "route": "/menu", "pattern": "entity_list", "access": "public"})
    return {"application": {"name": "A"}, "pages": pages, "data": {"entities": []},
            "mobile": {"native": {"enabled": native}, "store": {"bundleId": "com.acme.a"}} if native is not None else {}}


def matcher(tmp_path, d):
    project_middleware(d, tmp_path)
    return (tmp_path / "src" / "middleware.ts").read_text("utf-8")


def test_a_native_app_with_a_public_page_leaves_the_read_route_to_answer(tmp_path):
    assert "api/read" in matcher(tmp_path, doc(native=True, public_page=True))


def test_a_native_app_whose_only_public_pages_are_sign_in_keeps_the_gate(tmp_path):
    assert "api/read" not in matcher(tmp_path, doc(native=True, public_page=False))


def test_a_website_with_a_public_page_keeps_the_gate_on_the_read_route(tmp_path):
    assert "api/read" not in matcher(tmp_path, doc(native=False, public_page=True))
    assert "api/read" not in matcher(tmp_path, doc(native=None, public_page=True))
