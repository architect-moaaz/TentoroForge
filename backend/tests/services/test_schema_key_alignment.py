"""A page must ask the registry for the URL it actually serves.

The template's group-root page.tsx is authored for a landing at "/" and calls
`renderSchemaPage("/")`. When it ends up at `(<group>)/<seg>/page.tsx` it
serves `/<seg>` — and the schema pipeline registers that page under `/<seg>`,
never under `/`. The lookup then resolves to nothing and the page renders
blank, with the real schema sitting beside it unrequested. That is the
"dashboard is missing" report on opmk18qr: a 58-node dashboard registered at
`/dashboard`, and the route asking for `/`.

`_materialize_route_group_landing` already rewrote this — but only along its
own MOVE path, guarded by `if not group_page.exists() or real.exists()`. When
the page arrives at `<seg>/page.tsx` any other way, the guard returns False on
its first line and the wrong argument ships.

So the rule is restated here as an invariant on the FILE, not on the move: what
a page asks for is derived from where it sits, however it got there.
"""

from pathlib import Path

from services.nav_route_reconcile_guard import align_schema_keys_to_routes


def _page(tmp_path: Path, rel: str, body: str) -> Path:
    p = tmp_path / "src" / "app" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


# The REAL emitted shape — three arguments. An earlier version of this test
# used a single-arg call, so it passed while the regex it guarded could not
# match anything the pipeline actually writes.
CALL = ('export default async function P({ searchParams }) {\n'
        '  return renderSchemaPage("/", undefined, await searchParams);\n}\n')


def test_a_group_nested_page_asks_for_its_own_url(tmp_path):
    """The live opmk18qr shape."""
    p = _page(tmp_path, "(dashboard)/dashboard/page.tsx", CALL)
    res = align_schema_keys_to_routes(str(tmp_path))
    assert 'renderSchemaPage("/dashboard"' in p.read_text(encoding="utf-8")
    assert res["fixed"] == 1


def test_the_group_root_itself_is_left_alone(tmp_path):
    """`(dashboard)/page.tsx` really does serve "/" — route groups add no
    URL segment. Rewriting it would break the one case that was right."""
    p = _page(tmp_path, "(dashboard)/page.tsx", CALL)
    assert align_schema_keys_to_routes(str(tmp_path))["fixed"] == 0
    assert 'renderSchemaPage("/"' in p.read_text(encoding="utf-8")


def test_nested_groups_contribute_no_segments(tmp_path):
    p = _page(tmp_path, "(app)/(shell)/reports/page.tsx", CALL)
    align_schema_keys_to_routes(str(tmp_path))
    assert 'renderSchemaPage("/reports"' in p.read_text(encoding="utf-8")


def test_a_deeper_route_gets_its_full_path(tmp_path):
    p = _page(tmp_path, "(dashboard)/admin/employees/page.tsx", CALL)
    align_schema_keys_to_routes(str(tmp_path))
    assert 'renderSchemaPage("/admin/employees"' in p.read_text(encoding="utf-8")


def test_a_page_already_asking_correctly_is_untouched(tmp_path):
    body = 'return renderSchemaPage("/dashboard", undefined, x);'
    p = _page(tmp_path, "(dashboard)/dashboard/page.tsx", body)
    assert align_schema_keys_to_routes(str(tmp_path))["fixed"] == 0
    assert p.read_text(encoding="utf-8") == body


def test_a_page_asking_for_something_else_is_not_second_guessed(tmp_path):
    """Only the template's "/" default is a known-wrong literal. Any other
    argument is a deliberate choice and none of this pass's business."""
    body = 'return renderSchemaPage("/custom-key");'
    p = _page(tmp_path, "(dashboard)/dashboard/page.tsx", body)
    assert align_schema_keys_to_routes(str(tmp_path))["fixed"] == 0
    assert p.read_text(encoding="utf-8") == body


def test_authoring_drift_still_matches(tmp_path):
    """Single quotes, extra spaces — the literal is the same instruction."""
    p = _page(tmp_path, "(dashboard)/dashboard/page.tsx",
              "return renderSchemaPage( '/' );")
    align_schema_keys_to_routes(str(tmp_path))
    assert 'renderSchemaPage("/dashboard"' in p.read_text(encoding="utf-8")


def test_the_trailing_arguments_are_preserved(tmp_path):
    """Only the first argument is ours. Swallowing `undefined, await
    searchParams` would break every page it 'fixed'."""
    p = _page(tmp_path, "(dashboard)/dashboard/page.tsx", CALL)
    align_schema_keys_to_routes(str(tmp_path))
    body = p.read_text(encoding="utf-8")
    assert 'renderSchemaPage("/dashboard", undefined, await searchParams)' in body


def test_a_single_argument_call_also_works(tmp_path):
    p = _page(tmp_path, "(dashboard)/reports/page.tsx",
              'return renderSchemaPage("/");')
    align_schema_keys_to_routes(str(tmp_path))
    assert 'renderSchemaPage("/reports");' in p.read_text(encoding="utf-8")


def test_a_dynamic_segment_page_is_skipped(tmp_path):
    """`[id]` is a pattern, not a registry key the page can name literally."""
    p = _page(tmp_path, "(dashboard)/employees/[id]/page.tsx", CALL)
    assert align_schema_keys_to_routes(str(tmp_path))["fixed"] == 0


def test_no_app_dir_is_not_an_error(tmp_path):
    assert align_schema_keys_to_routes(str(tmp_path)) == {"fixed": 0, "files": []}


def test_it_reports_which_files_it_corrected(tmp_path):
    _page(tmp_path, "(dashboard)/dashboard/page.tsx", CALL)
    _page(tmp_path, "(dashboard)/reports/page.tsx", CALL)
    res = align_schema_keys_to_routes(str(tmp_path))
    assert res["fixed"] == 2
    assert sorted(res["files"]) == ["/dashboard", "/reports"]
