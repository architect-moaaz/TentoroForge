"""Deterministic seed backstop.

The LLM seed generator (agents/seed_generator.py) can silently fail to write
src/db/seed.ts (agent wedge / timeout / bad output), leaving the generated app
with an EMPTY database and — critically — no user to log in as (auth is gated).

This module guarantees a floor: if seed.ts is missing or trivially small after
the seed agent runs, emit a minimal, valid Drizzle seed.ts that inserts a
default **admin** user into the app's auth table so the app is always loginable
(admin@example.com / admin1234). Realistic multi-table data remains the LLM
agent's job; this is the safety net.
"""
from __future__ import annotations

import re
from pathlib import Path

# A bcrypt hash of "admin1234" (cost 10). Embedded so the seed needs no runtime
# hashing; bcryptjs.compare() — what the generated auth uses — verifies it.
# MUST match backend/templates/runtime/seed.ts's SEED_ADMIN_PASSWORD default so
# both paths (template copy + this backstop) advertise the same credentials.
_ADMIN_PASSWORD = "admin1234"
# Fixed admin PK, mirrored in templates/runtime/seed.ts (ADMIN_UUID) — reseeds
# and redeploys keep a stable admin id so FK references never dangle.
_ADMIN_UUID = "a0000000-0000-4000-8000-0000000000ad"
_ADMIN_BCRYPT = "$2b$10$zLuvJrmJ1/Pf7438yq.uE.bETRFDBbXcEjjwjEcumV5GiKM6WJVW."

_MIN_SEED_BYTES = 200  # smaller than this ⇒ treat as missing/empty


def _strip_block_comment(src: str) -> str:
    return re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)


def _pgtable_bodies(src: str) -> list[tuple[str, str]]:
    """Yield (var_name, body) for each `export const <var> = pgTable("…", { … })`.

    Uses balanced-brace scanning rather than a non-greedy regex so column
    definitions containing nested objects — e.g. `varchar("x", { length: 255 })`
    — don't truncate the body at the first inner `}` (which silently dropped
    every column after the first sized varchar from the seed).
    """
    out: list[tuple[str, str]] = []
    for m in re.finditer(
        r"export\s+const\s+(\w+)\s*=\s*pgTable\(\s*[\"'][^\"']+[\"']\s*,\s*\{",
        src,
    ):
        var = m.group(1)
        start = m.end() - 1  # index of the opening brace
        depth = 0
        for i in range(start, len(src)):
            c = src[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    out.append((var, src[start + 1:i]))
                    break
    return out


def parse_pg_tables(schema_src: str) -> dict[str, list[dict]]:
    """Parse `export const <var> = pgTable("<name>", { ...cols })` blocks.

    Returns {var_name: [{col, type, not_null, has_default, primary_key}]}.
    """
    src = _strip_block_comment(schema_src)
    tables: dict[str, list[dict]] = {}
    for var, body in _pgtable_bodies(src):
        cols: list[dict] = []
        for line in body.split("\n"):
            line = line.strip().rstrip(",")
            cm = re.match(r"(\w+)\s*:\s*(\w+)\(", line)
            if not cm:
                continue
            cols.append({
                "col": cm.group(1),
                "type": cm.group(2),
                "not_null": ".notNull()" in line,
                "has_default": (".default" in line or ".defaultNow()" in line
                                or ".defaultRandom()" in line or ".$default" in line),
                "primary_key": ".primaryKey()" in line,
            })
        tables[var] = cols
    return tables


def find_auth_table(tables: dict[str, list[dict]]) -> str | None:
    """The table the app authenticates against: has a password-ish column AND a
    username/email-ish column."""
    for var, cols in tables.items():
        names = {c["col"].lower() for c in cols}
        has_pw = any("password" in n or n in ("pass", "pwd") for n in names)
        has_login = any(n in ("username", "email", "user_name") or "email" in n for n in names)
        if has_pw and has_login:
            return var
    # Fall back to a table literally named users/user/accounts.
    for var in tables:
        if var.lower() in ("users", "user", "accounts", "account"):
            return var
    return None


def _admin_value(col: dict) -> str | None:
    """TS literal for an admin row's column, or None to omit (nullable/default)."""
    name, typ = col["col"].lower(), col["type"].lower()
    # A role column usually defaults to "user"; override so the seeded admin is
    # actually an admin (checked BEFORE the has_default early-return below).
    if name == "role":
        return '"admin"'
    # Deterministic admin PK — checked before has_default so it overrides
    # defaultRandom(): reseeds keep the same admin id and FKs to it survive.
    if col["primary_key"] and typ == "uuid":
        return f'"{_ADMIN_UUID}"'
    if col["has_default"]:
        return None
    if "password" in name:
        return f'"{_ADMIN_BCRYPT}"'
    if name in ("username", "user_name"):
        return '"admin"'
    if "email" in name:
        return '"admin@example.com"'
    if name.endswith("name") or name == "name" or "full_name" in name:
        return '"Admin User"'
    if name == "role":
        return '"admin"'
    if name in ("status", "state"):
        return '"active"'
    if not col["not_null"]:
        return None  # nullable, no default → omit
    if typ in ("timestamp", "date"):
        return "new Date()"
    if typ in ("boolean", "bool"):
        return "true"
    if typ in ("integer", "serial", "numeric", "real", "doubleprecision", "bigint"):
        return "0"
    if typ in ("jsonb", "json"):
        return "{}"
    if typ == "uuid":
        return "randomUUID()"
    return '"admin"'  # varchar/text/etc.


def _schema_sources(out: Path) -> list[tuple[str, str]]:
    """(import_module, source_text) for every schema source, relative to src/db/
    where seed.ts lives. Prefers the per-entity dir src/db/schema/*.ts — the auth
    `users` table is emitted there by the auth agent, so the single-file schema.ts
    (domain entities only) misses it. Each per-entity file gets its own import path
    ('./schema/user') because '@/db/schema' resolves to schema.ts, NOT the dir."""
    sources: list[tuple[str, str]] = []
    schema_dir = out / "src" / "db" / "schema"
    if schema_dir.is_dir():
        for f in sorted(schema_dir.glob("*.ts")):
            if f.name == "index.ts":
                continue
            try:
                sources.append((f"./schema/{f.stem}", f.read_text(encoding="utf-8")))
            except Exception:
                continue
    single = out / "src" / "db" / "schema.ts"
    if single.exists():
        try:
            sources.append(("./schema", single.read_text(encoding="utf-8")))
        except Exception:
            pass
    return sources


def _find_auth_source(out: Path) -> tuple[str, list[dict], str] | None:
    """(auth_var, cols, import_module) for the first auth table found across all
    schema sources, or None."""
    for import_module, text in _schema_sources(out):
        tables = parse_pg_tables(text)
        var = find_auth_table(tables)
        if var:
            return var, tables[var], import_module
    return None


def render_admin_seed(auth_var: str, cols: list[dict], import_module: str = "./schema") -> str:
    fields = []
    for c in cols:
        v = _admin_value(c)
        if v is not None:
            fields.append(f"    {c['col']}: {v},")
    field_block = "\n".join(fields)
    return f'''// Auto-generated deterministic seed (backstop). Guarantees a login-able
// admin user (admin / {_ADMIN_PASSWORD}) so the app is usable on first run.
import {{ randomUUID }} from "crypto";
import {{ db }} from "./index";
import {{ {auth_var} }} from "{import_module}";

async function seed() {{
  console.log("[seed] inserting default admin user…");
  await db
    .insert({auth_var})
    .values({{
{field_block}
    }})
    .onConflictDoNothing();
  console.log("[seed] ✅ admin ready — login: admin / {_ADMIN_PASSWORD}");
  process.exit(0);
}}

seed().catch((err) => {{
  console.error("[seed] failed:", err);
  process.exit(1);
}});
'''


def ensure_seed_file(output_dir: str | Path) -> str | None:
    """If src/db/seed.ts is missing/trivial, emit a deterministic admin seed.

    Returns the path written, or None if a real seed already exists or no auth
    table could be found.
    """
    out = Path(output_dir)
    seed_path = out / "src" / "db" / "seed.ts"
    if seed_path.exists() and seed_path.stat().st_size >= _MIN_SEED_BYTES:
        return None  # LLM agent produced a real seed — leave it.

    found = _find_auth_source(out)
    if not found:
        return None
    auth_var, cols, import_module = found

    seed_path.parent.mkdir(parents=True, exist_ok=True)
    seed_path.write_text(render_admin_seed(auth_var, cols, import_module), encoding="utf-8")
    return str(seed_path)
