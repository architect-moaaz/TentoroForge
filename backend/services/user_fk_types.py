"""Make user-referencing FK columns match the users-table primary-key type.

The auth agent emits `users.id` as `serial` (integer), but the schema agent emits
owner foreign keys (landlordId / ownerId / userId / createdById / authorId …) as
`uuid`. A session `user.id` (an integer) then can't populate a uuid column —
every create that defaults an owner FK fails with
`invalid input syntax for type uuid`.

This rewrites those owner-FK columns from `uuid(...)` to `integer(...)` so they
match `users.id`. Domain FKs (propertyId, tenantId, …) that reference uuid domain
tables are left untouched — only the name-allowlisted user references are changed.
No-op when `users.id` is already uuid.

TODO(spec-d-w2): the ``column.user_fk_role`` planner-precedence branch is
already wired below (see ``_planner_user_fk_roles``), but the planner agent
doesn't yet emit that field. Once the planner emission ships, the legacy
name-list allowlist (``_ACTOR_FK_COLS`` / ``_ACTOR_FK_RE``) and the
fk_semantics domain-classification helper can both be deleted — the
rewriter becomes a pure planner-reader.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from services.fk_semantics import _norm as _fk_norm
from services.fk_semantics import classify_registry

logger = logging.getLogger(__name__)

# camelCase column names that, BY NAME, look like references to the users table (the actor
# role). This is the conservative fallback list; the FK-role authority (fk_semantics) is
# consulted below to EXCLUDE any of these that is actually a DOMAIN FK (references a
# non-users table) — a domain FK's uuid must NEVER be rewritten to integer.
_ACTOR_FK_COLS = (
    "userId", "ownerId", "landlordId", "createdById", "updatedById",
    "authorId", "assigneeId", "managerId", "createdBy", "updatedBy",
)
_ACTOR_FK_RE = re.compile(
    r"^(\s*(?P<col>" + "|".join(_ACTOR_FK_COLS) + r")\s*:\s*)uuid(\()",
)
_USERS_ID_INT = re.compile(r"\bid\s*:\s*(serial|integer|bigserial|bigint)\s*\(")
_PG_IMPORT = re.compile(r'(import\s*\{)([^}]*?)(\}\s*from\s*["\']drizzle-orm/pg-core["\'])')


def _ensure_integer_import(src: str) -> str:
    m = _PG_IMPORT.search(src)
    if not m or re.search(r"\binteger\b", m.group(2)):
        return src
    names = m.group(2).rstrip()
    sep = "" if names.endswith(",") or not names.strip() else ","
    return src[:m.start(2)] + f"{names}{sep} integer " + src[m.end(2):]


def _planner_user_fk_roles(output_dir: str | Path) -> tuple[set[str], set[str]]:
    """(actor_norms, non_actor_norms) from planner-emitted ``column.user_fk_role``
    on the registry (Spec D W2 — additive precedence). ``actor_norms`` are
    columns the planner explicitly marks as user-references (rewrite uuid→
    integer even if the name-list wouldn't have matched); ``non_actor_norms``
    are columns the planner explicitly opts out of the rewrite ("domain" /
    "tenancy" / anything != "actor"). Missing / non-string values fall through
    to the legacy name-list classifier.
    """
    actor: set[str] = set()
    non_actor: set[str] = set()
    try:
        from services.fk_semantics import _load_registry
        reg = _load_registry(str(output_dir)) or {}
    except Exception as e:  # noqa: BLE001
        logger.warning("[user-fk-types] planner-role load skipped: %s", e)
        return actor, non_actor

    for ent in (reg.get("entities") or {}).values():
        if not isinstance(ent, dict):
            continue
        # Prefer canonical columns list (carries per-column planner metadata);
        # fall back to fields dict.
        cols_iter: list[tuple[str, dict]] = []
        cols = ent.get("columns")
        if isinstance(cols, list):
            for c in cols:
                if isinstance(c, dict) and c.get("name"):
                    cols_iter.append((c["name"], c))
        fields = ent.get("fields")
        if isinstance(fields, dict):
            for n, meta in fields.items():
                if isinstance(meta, dict) and n:
                    cols_iter.append((n, meta))
        for name, meta in cols_iter:
            role = meta.get("user_fk_role")
            if not isinstance(role, str) or not role.strip():
                continue
            key = _fk_norm(name)
            if role.strip().lower() == "actor":
                actor.add(key)
            else:
                non_actor.add(key)
    return actor, non_actor


def _domain_fk_cols(output_dir: str | Path) -> set[str]:
    """Normalized names of every column the FK-role authority classifies as a DOMAIN FK
    (references a non-users table). These must be left as uuid even if their NAME matches
    the actor-FK list. Empty when there's no registry to classify (schema-only apps)."""
    try:
        from services.fk_semantics import _load_registry
        reg = _load_registry(str(output_dir))
        if not reg:
            return set()
        domain: set[str] = set()
        for roles in classify_registry(reg, str(output_dir)).values():
            for col, r in roles.items():
                if r.role == "domain":
                    domain.add(_fk_norm(col))
        return domain
    except Exception as e:  # noqa: BLE001 — classification must never break the pass
        logger.warning("[user-fk-types] domain-FK classification skipped: %s", e)
        return set()


def reconcile_user_fk_types(output_dir: str | Path) -> dict:
    base = Path(output_dir)
    sdir = base / "src" / "db" / "schema"
    user_file = sdir / "user.ts"
    if not sdir.is_dir() or not user_file.exists():
        return {"reconciled": False, "reason": "no schema dir / user.ts"}

    if not _USERS_ID_INT.search(user_file.read_text(encoding="utf-8")):
        return {"reconciled": False, "reason": "users.id is not integer-typed"}

    domain_cols = _domain_fk_cols(output_dir)
    # Spec D W2 — planner-authored user_fk_role takes precedence.
    planner_actor, planner_non_actor = _planner_user_fk_roles(output_dir)

    # Planner-authored actor columns override the name allowlist. Widen the
    # regex to also match a raw ``: uuid(`` on any planner-actor column name
    # (case-sensitive column identifier), so a domain-shaped name like
    # ``primaryOwnerRefId`` still gets rewritten when the planner says it's
    # an actor. Falls through if planner_actor is empty (legacy path).
    if planner_actor:
        planner_actor_re = re.compile(
            r"^(\s*(?P<col>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*)uuid(\()"
        )
    else:
        planner_actor_re = None

    def _rewrite(ln: str) -> tuple[str, bool]:
        # 1. Planner-actor precedence — rewrite even if the name isn't in
        #    the legacy allowlist. Skip when planner explicitly opted out.
        if planner_actor_re is not None:
            pm = planner_actor_re.search(ln)
            if pm:
                col_norm = _fk_norm(pm.group("col"))
                if col_norm in planner_actor:
                    return planner_actor_re.sub(r"\g<1>integer\g<3>", ln), True

        m = _ACTOR_FK_RE.search(ln)
        # Never convert a DOMAIN FK — only genuine actor (users) references get uuid→integer.
        if not m:
            return ln, False
        col_norm = _fk_norm(m.group("col"))
        # Planner opt-out silences the legacy classifier for this column.
        if col_norm in planner_non_actor:
            return ln, False
        if col_norm in domain_cols:
            return ln, False
        # Group 1 = "<indent><col>: ", named group 2 = col, group 3 = "(".
        return _ACTOR_FK_RE.sub(r"\g<1>integer\g<3>", ln), True

    changed_cols = 0
    changed_files = 0
    for f in sdir.glob("*.ts"):
        if f.name in ("user.ts", "index.ts", "relations.ts"):
            continue
        src = f.read_text(encoding="utf-8")
        rewritten = [_rewrite(ln) for ln in src.split("\n")]
        n = sum(1 for _, hit in rewritten if hit)
        if n:
            new = _ensure_integer_import("\n".join(ln for ln, _ in rewritten))
            f.write_text(new, encoding="utf-8")
            changed_cols += n
            changed_files += 1

    if changed_cols:
        logger.info("[user-fk-types] rewrote %d owner-FK column(s) uuid→integer across %d file(s)",
                    changed_cols, changed_files)
    return {"reconciled": changed_cols > 0, "columns": changed_cols, "files": changed_files}
