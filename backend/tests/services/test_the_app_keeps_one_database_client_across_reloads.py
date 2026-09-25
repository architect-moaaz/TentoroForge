"""The generated app opens one Postgres client per process.

`src/db/index.ts` made a fresh `postgres()` client at module level. Under
`next dev` the module is re-evaluated on every recompile, each evaluation is
a new pool of ten connections, and the old ones stay open: the page
reviewer's crawl of nlwtcyz5 (27 pages, every control pressed) reached
Postgres's hundred and the database answered "too many clients already" to
everything — the reviewer's own copy, the person's app, psql (2026-09-25).
The client is cached on `globalThis` outside production, the pattern Next
documents for exactly this.
"""
from __future__ import annotations

from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[2]


def _caches(src: str) -> bool:
    return ("globalForDb.__forgeSql ?? postgres(connectionString" in src
            and 'process.env.NODE_ENV !== "production") globalForDb.__forgeSql = client' in src)


def test_the_foundation_template_caches_the_client():
    assert _caches((_BACKEND / "templates/app-foundation/src/db/index.ts").read_text())


def test_the_injectors_repair_of_a_pg_client_caches_it_too(tmp_path):
    from services.runtime_injector import _fix_common_agent_mistakes as fix  # noqa: F401
    (tmp_path / "src" / "db").mkdir(parents=True)
    (tmp_path / "src" / "db" / "index.ts").write_text('import { Pool } from "pg";\n')
    fix(tmp_path)
    assert _caches((tmp_path / "src" / "db" / "index.ts").read_text())


def test_the_schema_agent_is_shown_the_cached_client():
    assert _caches((_BACKEND / "agents/schema_agent.py").read_text())
