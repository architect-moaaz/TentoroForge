"""Nothing may serve "/" except the catch-all that serves every page.

MEASURED ON A GENERATED APP. Every node completed, the projection was correct,
the Blueprint was right — and the dev server would not start:

    You cannot define a route with the same specificity as a optional
    catch-all route ("/" and "/[[...slug]]")

The catch-all became OPTIONAL so that "/" would resolve at all (a required
`[...slug]` cannot match an empty path, which is how a single-page app 404ed
on its own landing page). That made it serve "/" too — and the scaffold keeps
its own landing page at `src/app/(dashboard)/page.tsx`.

A ROUTE GROUP CONTRIBUTES NOTHING TO THE URL. `(dashboard)` is organisation,
not a path segment, so that file IS "/". The retirement list covered
`src/app/page.tsx` — where a landing page usually sits — and stopped there.

No test in this repository could have caught it: every one of them reads the
Blueprint, the projection or the file list, and this fault lives in what Next
does with two files that look unrelated.
"""
from pathlib import Path

import pytest

from services.blueprint.assembly import RETIRED_SCAFFOLD_FILES

TEMPLATES = Path(__file__).resolve().parents[2] / "templates"

#: A path segment wrapped in parentheses is a route group: it organises files
#: and adds nothing to the URL. Anything else is a real segment.
def _url_of(rel: str) -> str:
    parts = [p for p in Path(rel).parts[len("src/app".split("/")):]
             if not (p.startswith("(") and p.endswith(")"))]
    parts = [p for p in parts if p != "page.tsx"]
    return "/" + "/".join(parts)


def test_a_route_group_is_not_a_path_segment():
    assert _url_of("src/app/(dashboard)/page.tsx") == "/"
    assert _url_of("src/app/page.tsx") == "/"
    assert _url_of("src/app/(dashboard)/tasks/page.tsx") == "/tasks"
    assert _url_of("src/app/login/page.tsx") == "/login"


def _root_pages(template: Path) -> list[str]:
    """Every scaffold file that would serve "/"."""
    app = template / "src" / "app"
    if not app.is_dir():
        return []
    out = []
    for page in app.rglob("page.tsx"):
        rel = str(page.relative_to(template))
        if "slug" in rel:
            continue   # the catch-all is the one that is allowed to
        if _url_of(rel) == "/":
            out.append(rel)
    return out


@pytest.mark.parametrize("template", ["app-foundation", "standalone-app"])
def test_no_scaffold_page_survives_at_the_root(template):
    """Whatever a template ships at "/" must be retired, or the optional
    catch-all collides with it and the application will not start."""
    root = TEMPLATES / template
    if not root.is_dir():
        pytest.skip(f"{template} is not in this checkout")
    for rel in _root_pages(root):
        assert rel in RETIRED_SCAFFOLD_FILES, (
            f"{template} ships {rel}, which serves '/' — retire it, or Next "
            f"refuses to start beside the optional catch-all")


def test_the_retired_list_names_the_grouped_landing_page():
    """The specific one that shipped a broken app."""
    assert "src/app/(dashboard)/page.tsx" in RETIRED_SCAFFOLD_FILES
    assert "src/app/page.tsx" in RETIRED_SCAFFOLD_FILES
