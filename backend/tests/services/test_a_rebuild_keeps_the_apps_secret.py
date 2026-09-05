"""An app keeps its auth secret across rebuilds.

The env writer's own comment said `.env` is only created if absent "so a
re-assembly never rotates a secret out from under a running app". The code
below it wrote fresh secrets to both `.env` and `.env.local` every time. Every
rebuild therefore signed the user out — NextAuth logged
`JWT_SESSION_ERROR: decryption operation failed` for a session issued under
the previous secret — and the person testing the app signed in again after
each run without knowing why.

Secrets are read back from the files that exist, `.env.local` first because
Next gives it precedence, and generated only for an app that has none.
"""
from services.blueprint.assembly import existing_secrets


def test_an_app_with_no_env_gets_nothing_back(tmp_path):
    assert existing_secrets(tmp_path) == {}


def test_secrets_are_read_from_the_file_next_prefers(tmp_path):
    (tmp_path / ".env").write_text("NEXTAUTH_SECRET=old\nAUTH_SECRET=olda\n")
    (tmp_path / ".env.local").write_text("NEXTAUTH_SECRET=local\n")
    kept = existing_secrets(tmp_path)
    assert kept["NEXTAUTH_SECRET"] == "local"
    assert kept["AUTH_SECRET"] == "olda"


def test_only_secrets_are_kept(tmp_path):
    (tmp_path / ".env").write_text("DATABASE_URL=postgres://x\nNEXTAUTH_SECRET=s\n")
    assert existing_secrets(tmp_path) == {"NEXTAUTH_SECRET": "s"}


def test_the_writer_reuses_them():
    """The env body is composed from `existing_secrets`; pin the wiring."""
    import inspect
    from services.blueprint import assembly
    src = inspect.getsource(assembly.assemble)
    assert "kept.get('NEXTAUTH_SECRET') or secrets.token_urlsafe(32)" in src
    assert "kept.get('AUTH_SECRET') or secrets.token_urlsafe(32)" in src
