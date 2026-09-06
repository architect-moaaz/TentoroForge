"""Two applications must never open one database.

`assemble` wrote a module-level constant — `postgres://…/app` — into every
generated `.env.local`. Every application that read that file opened the same
database: `npm run dev`, drizzle-kit, `docker-compose.verify.yml`, a deploy.

WHAT IT LOOKED LIKE WHEN IT BIT. A Figma-specification app was found reading an
expense tracker's `users` table — the only tables in "its" database were
`expenses`, `expense_reports`, `receipts`, `expense_policies`,
`expense_categories`, and not one of its own. Its schema declared a `name`
column the expense app's table does not have, so `db.select()` raised
`column "name" does not exist`, `authorize()` caught it and returned null, and
the login page said **"Invalid email or password"**. The credential was
correct the whole time. A wrong database wearing a wrong-password mask, which
is why this is a test and not a comment.

It also explains the `22P02` class: that table's `id` is `text` while the
scaffold's schema declares `uuid`, so any uuid FK pointed at another app's user
rows fails with "invalid input syntax for type uuid".

WHY THE NAME IS DERIVED, NOT DEFAULTED. `project_short_id` is already a
parameter of the same call. A default that ignores it is how one name came to
serve every application, so there is no longer a shared constant to reach for.

THE TWO PRODUCERS MUST AGREE. `run.sh` computes the database name from the
project directory and used to say it refused to read the file because assembly
wrote `/app`. That workaround protected only the apps started by that script.
Now both compute `app_<sanitised id>` — and if they ever diverge, a
script-started app would migrate one database while `npm run dev` read another,
which is the original bug with extra steps. The last test here pins that.
"""
import re

import pytest

from services.blueprint.assembly import (
    assemble, database_name, default_database_url,
)


# ------------------------------------------------------------ the name itself

def test_two_projects_never_share_a_database():
    assert database_name("wzja848q") != database_name("gowlthzu")


def test_the_name_carries_the_project_id():
    assert "wzja848q" in database_name("wzja848q")


@pytest.mark.parametrize("short_id", ["wzja848q", "forge", "9abc", "a1b2c3d4"])
def test_the_name_is_a_legal_postgres_identifier(short_id):
    """Postgres takes neither a leading digit nor a dash, and the same string
    also has to be a valid docker compose project name."""
    assert re.fullmatch(r"[a-z_][a-z0-9_]*", database_name(short_id))


def test_a_uuid_named_directory_still_yields_a_legal_name():
    """Directories that predate short_id paths are uuids, and a dash is not
    legal in either an identifier or a compose project name."""
    name = database_name("7851ea80-bf91-46a3-9176-22beced5f2f2")
    assert "-" not in name
    assert re.fullmatch(r"[a-z_][a-z0-9_]*", name)


def test_the_url_names_that_database():
    assert default_database_url("wzja848q").endswith("/app_wzja848q")


# ------------------------------------------------- no shared default survives

def test_there_is_no_shared_default_to_reach_for():
    """The constant WAS the defect. Its absence is the fix — a caller that
    wants a url must say which project it is for."""
    import services.blueprint.assembly as A

    assert not hasattr(A, "DEFAULT_DATABASE_URL")


def test_assemble_defaults_the_url_from_the_project(tmp_path):
    """The end-to-end property: what lands in .env.local is this project's
    database, without the caller having to pass anything."""
    doc = {"application": {"name": "X"}, "pages": [], "data": {"entities": []}}
    assemble(doc, tmp_path, project_short_id="wzja848q")

    written = (tmp_path / ".env.local").read_text("utf-8")
    assert "/app_wzja848q" in written
    assert "5432/app\n" not in written


def test_an_explicit_url_still_wins(tmp_path):
    """Deriving is the default, not a lock: a caller with its own Postgres —
    Neon, a container, a test — must still be able to say so."""
    doc = {"application": {"name": "X"}, "pages": [], "data": {"entities": []}}
    assemble(doc, tmp_path, project_short_id="wzja848q",
             database_url="postgres://u:p@example.test:5432/mine")

    assert "example.test:5432/mine" in (tmp_path / ".env.local").read_text("utf-8")


# ------------------------------------------------ the script must not diverge

def test_the_start_script_computes_the_same_name():
    """`run.sh` derives the name from the project directory. If the two ever
    disagree, a script-started app migrates one database while `npm run dev`
    reads another — the original bug, harder to see.

    Asserted against the shell as written rather than by re-implementing it:
    the point is that the file on disk still agrees.
    """
    import inspect

    from services import runtime_injector

    src = inspect.getsource(runtime_injector)
    assert 'DB_NAME="app_$(' in src, "the script no longer builds app_<id>"
    assert "tr -c 'a-z0-9' '_'" in src, "the script's sanitiser changed"
    # Both sides: prefix and substitution, the same two rules as `database_name`.
    assert database_name("wzja848q") == "app_wzja848q"
