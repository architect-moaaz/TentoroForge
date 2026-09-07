"""The auth scaffold always ships `schema/user.ts` (the NextAuth `users` table).
When the plan also has a domain "User" entity, the schema agent writes
`schema/users.ts` — a SECOND `users` table. The barrel re-exported both →
`Duplicate export 'users'` → the generated app fails to build. This recurs on any
app with a User entity, so the barrel must dedupe (auth table wins)."""
from pathlib import Path

from services.schema_barrel import reconcile_db_schema_barrel


def _schema(tmp_path: Path, files: dict[str, str]) -> Path:
    sdir = tmp_path / "src" / "db" / "schema"
    sdir.mkdir(parents=True)
    for name, body in files.items():
        (sdir / name).write_text(body, encoding="utf-8")
    return sdir


def test_deduplicates_colliding_users_export(tmp_path):
    _schema(tmp_path, {
        "user.ts": 'export const users = pgTable("users", {});',        # auth scaffold
        "users.ts": 'export const users = pgTable("users", {});',       # domain entity
        "rooms.ts": 'export const rooms = pgTable("rooms", {});',
    })
    res = reconcile_db_schema_barrel(tmp_path)
    barrel = (tmp_path / "src" / "db" / "schema" / "index.ts").read_text(encoding="utf-8")
    # `users` exported exactly once...
    assert barrel.count("users }") + barrel.count("{ users") >= 1
    assert barrel.count('export { users }') == 1
    # ...and it comes from the auth scaffold file, not the domain dup.
    assert 'export { users } from "./user";' in barrel
    assert 'from "./users"' not in barrel
    assert 'export { rooms } from "./rooms";' in barrel
    assert res.get("deduped", 0) >= 1


def test_no_collision_is_unchanged(tmp_path):
    _schema(tmp_path, {
        "rooms.ts": 'export const rooms = pgTable("rooms", {});',
        "guests.ts": 'export const guests = pgTable("guests", {});',
    })
    reconcile_db_schema_barrel(tmp_path)
    barrel = (tmp_path / "src" / "db" / "schema" / "index.ts").read_text(encoding="utf-8")
    assert 'export { rooms } from "./rooms";' in barrel
    assert 'export { guests } from "./guests";' in barrel


def test_multi_symbol_file_keeps_its_fresh_symbols(tmp_path):
    # users.ts collides on `users` but also defines `usersRelations` — that fresh
    # symbol must still be exported (from users.ts).
    _schema(tmp_path, {
        "user.ts": 'export const users = pgTable("users", {});',
        "users.ts": 'export const users = pgTable("users", {});\nexport const usersRelations = relations();',
    })
    reconcile_db_schema_barrel(tmp_path)
    barrel = (tmp_path / "src" / "db" / "schema" / "index.ts").read_text(encoding="utf-8")
    assert 'export { users } from "./user";' in barrel
    assert 'usersRelations' in barrel and '"./users"' in barrel
    assert barrel.count("export { users }") == 1
