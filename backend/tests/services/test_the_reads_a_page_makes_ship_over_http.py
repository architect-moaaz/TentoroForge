"""A phone app reads what a page reads, over HTTP, and the data route is held.

The SDK's server reads (`list`, `record`, `count`, `total`, `series`, `query`,
widgets, `similar`, `near`, the person) are imported by a page's `load.ts`; a
client that is not a page cannot. The scaffold ships `/api/read/<op>`, which
calls those same functions as the signed-in person. The route's behaviour is
proven on the shipped file by `templates/runtime/__tests__/run-read-tests.sh`;
this proves it reaches every application, as the only thing that reads, and
that `/api/data` no longer answers `limit=abc` or a whole table."""
from __future__ import annotations

from pathlib import Path

from services.blueprint.assembly import copy_scaffold

ROOT = Path(__file__).resolve().parents[2]
ROUTE = ROOT / "templates" / "app-foundation" / "src" / "app" / "api" / "read" / "[op]" / "route.ts"


def test_the_read_route_ships_with_every_application(tmp_path):
    written = copy_scaffold(tmp_path, project_short_id="abc12345")
    assert "src/app/api/read/[op]/route.ts".replace("/", "\\") in written or "src/app/api/read/[op]/route.ts" in written
    assert (tmp_path / "src" / "app" / "api" / "read" / "[op]" / "route.ts").is_file()


def test_the_read_route_changes_nothing():
    src = ROUTE.read_text(encoding="utf-8")
    for write in ("insert(", "update(", "delete(", "triggerWorkflow", "db.execute", "engine.create", "engine.update"):
        assert write not in src, f"a read route calls {write}"
    assert "export async function POST" in src and "export async function GET" in src
    assert "PUT" not in src and "PATCH" not in src and "DELETE" not in src


def test_the_read_route_calls_the_sdks_own_reads_only():
    src = ROUTE.read_text(encoding="utf-8")
    for call in ("sdk.listPage", "sdk.record(", "sdk.recordsById", "sdk.count", "sdk.total", "sdk.series",
                 "sdk.query", "sdk.runWidget", "sdk.similar", "sdk.near", "sdk.currentUser", "sdk.myAccount"):
        assert call in src, call
    # An entity is one the application's own column list has, never an inherited name.
    assert "Object.prototype.hasOwnProperty.call(READABLE_FIELDS, name)" in src


def test_the_data_route_holds_a_page_to_one_to_two_hundred_rows():
    src = (ROOT / "templates" / "data-api-route.ts").read_text(encoding="utf-8")
    assert "Math.min(Math.max(Number.parseInt(url.searchParams.get(\"limit\") || \"50\", 10) || 50, 1), 200)" in src
    assert "parseInt(url.searchParams.get(\"limit\") || \"50\")," not in src
