"""The (dashboard) route files must look schemas up by ROUTE key (the convention
the schema pipeline's registry.ts uses: '/', '/tasks', '/tasks/[id]'), NOT the
stale '<entity>/list|detail|form' keys — otherwise every entity page 404s and the
home page never renders."""
from pathlib import Path

_BASE = Path("templates/app-foundation/src/app/(dashboard)")


def _read(p: str) -> str:
    return (_BASE / p).read_text()


def test_entity_list_uses_route_key_with_home_alias():
    src = _read("[entity]/page.tsx")
    assert "`/${entity}`" in src
    assert 'entity === "home"' in src   # /home → "/" so the home page resolves
    assert "/list`" not in src


def test_detail_and_new_use_route_keys():
    assert "`/${entity}/[id]`" in _read("[entity]/[id]/page.tsx")
    assert "/detail`" not in _read("[entity]/[id]/page.tsx")
    assert "`/${entity}/new`" in _read("[entity]/new/page.tsx")
    assert "/form`" not in _read("[entity]/new/page.tsx")


def test_index_renders_home_schema():
    src = _read("page.tsx")
    assert 'renderSchemaPage("/"' in src   # extra args (searchParams) are fine
    assert "__APP_NAME__" not in src    # the old placeholder stub is gone


def test_list_routes_forward_search_params():
    """Filter chips write their selection to the URL; the page must receive
    it or every filter in the app is decorative."""
    for rel in ("page.tsx", "[entity]/page.tsx"):
        src = _read(rel)
        assert "searchParams" in src, f"{rel} drops the URL filter state"
        assert "await searchParams" in src
