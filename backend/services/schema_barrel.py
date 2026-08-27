"""Reconcile the generated app's Drizzle schema into a single authoritative barrel.

The pipeline can end up with TWO schema sources:
  * ``src/db/schema.ts``  — a singular pre-generated file (from the plan), and
  * ``src/db/schema/``    — the plural per-entity dir the schema agent writes.

``import ... from "@/db/schema"`` resolves the FILE over the DIR, so consumers
(workflows' ``db_insert``, CRUD routes, data layer) silently get the wrong
(singular) tables — e.g. table ``property`` when the DB/migrations use
``properties`` — and inserts fail with "unknown table".

This consolidates everything into the dir: it regenerates ``schema/index.ts`` to
re-export every table/relation file present in the dir (so ``users`` /
``notifications`` are no longer dropped), carries over any workflow-engine
re-export line that was appended to the old ``schema.ts``, then deletes the
shadow file. Idempotent and safe to run when only the dir (or only the file)
exists.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_EXPORT_CONST = re.compile(r"export\s+const\s+(\w+)")
# Lines in the old schema.ts that re-export from elsewhere (e.g. the workflow
# engine's own schema) and therefore have no dir file to regenerate from.
_REEXPORT_FROM = re.compile(r"""^export\s*\{[^}]*\}\s*from\s*['"](?!\./)[^'"]+['"]\s*;?$""")


def reconcile_db_schema_barrel(output_dir: str | Path) -> dict:
    base = Path(output_dir)
    sdir = base / "src" / "db" / "schema"
    sfile = base / "src" / "db" / "schema.ts"
    if not sdir.is_dir():
        return {"reconciled": False, "reason": "no schema/ dir"}

    # Carry over any non-relative re-exports (workflow tables, etc.) from the
    # shadow file so we don't lose them when we delete it.
    carry: list[str] = []
    if sfile.exists():
        for ln in sfile.read_text(encoding="utf-8").splitlines():
            s = ln.strip()
            if _REEXPORT_FROM.match(s) and s not in carry:
                carry.append(s)

    # Re-export every const from every dir file (tables AND relations), but
    # DEDUPE symbol names across files. The auth scaffold always ships a `users`
    # table (schema/user.ts, required by NextAuth); a plan with a domain "User"
    # entity makes the schema agent write a second `users` table (schema/users.ts).
    # Exporting both is `Duplicate export 'users'` → the app fails to build. The
    # auth-scaffold table wins (auth depends on its exact shape); the colliding
    # domain symbol is dropped from the barrel.
    _AUTH_STEMS = {"user", "account", "session", "verification_token",
                   "verificationtoken", "authenticator"}

    def _prio(f: Path):
        # Foundation/auth files first so their symbols claim the name, then the
        # rest alphabetically for stable output.
        return (0 if f.stem.lower() in _AUTH_STEMS else 1, f.stem)

    lines: list[str] = []
    seen: set[str] = set()
    deduped = 0
    for f in sorted((x for x in sdir.glob("*.ts") if x.name != "index.ts"), key=_prio):
        names = _EXPORT_CONST.findall(f.read_text(encoding="utf-8"))
        fresh = [n for n in names if n not in seen]
        deduped += len(names) - len(fresh)
        if fresh:
            lines.append(f'export {{ {", ".join(fresh)} }} from "./{f.stem}";')
            seen.update(fresh)

    if not lines and not carry:
        return {"reconciled": False, "reason": "no exports found in schema/ dir"}

    # Emit in file-stem order for readability (matches the pre-dedup layout),
    # keeping the auth-first claim already baked into `seen`.
    lines.sort()
    (sdir / "index.ts").write_text("\n".join(lines + carry) + "\n", encoding="utf-8")
    removed = False
    if sfile.exists():
        sfile.unlink()
        removed = True
    if deduped:
        logger.info("[schema-barrel] dropped %d duplicate export(s) (e.g. auth vs domain users)", deduped)
    logger.info("[schema-barrel] consolidated %d dir module(s)%s", len(lines),
                " + removed shadow schema.ts" if removed else "")
    return {"reconciled": True, "removed_shadow": removed, "modules": len(lines),
            "carried": len(carry), "deduped": deduped}
