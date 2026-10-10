"""Smith reads an app's rows through the URL the app itself carries.

ecom v2 (forge-v3, 2026-10-10): every `read_rows` in a fix turn answered
"The database did not answer: ProgrammingError: invalid dsn: missing '='
after 'postgresql+asyncpg://…'" — the app's `DATABASE_URL` is SQLAlchemy's
spelling, and psycopg2 does not read the driver suffix.
"""
from __future__ import annotations

import types

from services.smith import data_export


def test_the_driver_suffix_is_not_the_databases():
    assert data_export.libpq_url("postgresql+asyncpg://u:p@host:5432/app_x") == "postgresql://u:p@host:5432/app_x"
    assert data_export.libpq_url("postgres://u:p@host/db") == "postgres://u:p@host/db"
    assert data_export.libpq_url("host=localhost dbname=x") == "host=localhost dbname=x"
    assert data_export.libpq_url("") == ""


def test_rows_and_columns_are_read_through_the_libpq_url(monkeypatch):
    seen: list[str] = []

    class _Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, *a, **k): pass
        def fetchall(self): return []
        description = []

    class _Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self): return _Cur()

    fake = types.SimpleNamespace(connect=lambda url: seen.append(url) or _Conn(),
                                 sql=types.SimpleNamespace(SQL=lambda s: types.SimpleNamespace(format=lambda **k: s, join=lambda xs: s),
                                                           Identifier=lambda c: c))
    monkeypatch.setitem(__import__("sys").modules, "psycopg2", fake)
    monkeypatch.setitem(__import__("sys").modules, "psycopg2.sql", fake.sql)
    data_export.existing_columns("postgresql+asyncpg://u:p@h/db", "categories")
    data_export.read_rows("postgresql+asyncpg://u:p@h/db", "categories", ["id"])
    assert seen == ["postgresql://u:p@h/db", "postgresql://u:p@h/db"]
