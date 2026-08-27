"""The ONE authority on what a foreign-key column MEANS.

Every layer used to decide "is this an ownership column?" by matching the column
NAME against a private `_OWNER_FK` set (~8 copies, none agreeing, none reading the
schema). `pets.ownerId` -> the OWNERS table broke all of them: they saw the name
`ownerId`, assumed the users table, and auto-filled the current user's id into a
column that references a domain entity -> FK violation.

This module classifies each column's ROLE from the registry's REAL fk target, so a
genuine FK to a domain table can never again be mistaken for a user-ownership marker.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

RESERVED_USER_SLUGS = {"users", "user"}
_TENANCY_NAMES = {"workspaceid", "tenantid", "orgid", "organizationid", "accountid"}
_ACTOR_NAME_RE = re.compile(
    r"^(recruiter|owner|user|author|creator|assignee|assigned_?to|reviewer|approver|"
    r"manager|actor|(created|updated|submitted|requested|uploaded|reported|posted)_?by)_?id$",
    re.I,
)
# An FK to the USERS table names SOMEONE ELSE (a people-picker), not the acting user:
# you assign a task TO a reviewer, you don't auto-fill it with yourself. These become an
# editable Select of users (role `assignment`), NOT auto-filled. The self/creator ones
# (created_by / owner / author / submitted_by …) stay `actor` (auto-fill from ctx.user).
# The noun sits immediately before the `Id`/`_id` suffix; a lazy prefix lets a
# qualifier lead it (`assignedAssessorId`, `primaryReviewerId`) still classify as a
# people-picker rather than an auto-filled actor. `re.match` anchors at the start,
# so the leading `.*?` is what allows the prefix.
_ASSIGNMENT_NAME_RE = re.compile(
    r".*?(assignee|assigned_?to|reviewer|approver|manager|responsible|supervisor|"
    r"lead|handler|assessor|evaluator|grader|scorer|examiner|interviewer)_?id$",
    re.I,
)


@dataclass(frozen=True)
class FkRole:
    column: str
    role: str            # "domain" | "actor" | "assignment" | "tenancy" | "plain"
    target_slug: str | None = None
    target_table: str | None = None
    required: bool = False


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _resolve_target(reg: dict, fk: str) -> dict | None:
    """Resolve a column.fk value (an entity id/slug/name) to its entity dict."""
    picked, _alts = _resolve_target_verbose(reg, fk)
    return picked


def _resolve_target_verbose(
    reg: dict, fk: str,
) -> tuple[dict | None, list[dict]]:
    """Same as :func:`_resolve_target` but ALSO returns the runner-ups the
    resolver saw. Two failure modes make this worth surfacing:

    - ``_norm`` collision: ``Owner`` and ``owners`` both normalize to
      ``owners``. First match wins silently; the LOSER is the right
      answer maybe half the time.
    - No exact match: the ``fk`` string doesn't hit any identity form.
      Currently returns ``None`` with no signal about closest names.

    Returns ``(picked_entity | None, alternatives)`` where alternatives
    is up to 3 candidates ordered by best-fit score (edit distance on
    the un-normalized name).
    """
    ents = reg.get("entities") or {}
    if not fk:
        return None, []
    want = _norm(fk)
    if not want:
        return None, []
    exact_matches: list[tuple[str, dict]] = []
    near_matches: list[tuple[str, dict, float]] = []
    for name, e in ents.items():
        if not isinstance(e, dict):
            continue
        forms = [f for f in (
            name, e.get("name"), e.get("slug"), e.get("table"),
            e.get("camel"), e.get("id"), e.get("singular"),
        ) if isinstance(f, str) and f]
        if any(_norm(f) == want for f in forms):
            exact_matches.append((name, e))
            continue
        # Not an exact norm match — score by edit-distance ratio on any
        # form so we can surface "did you mean X?" alternatives.
        best_ratio = 0.0
        for f in forms:
            ratio = _similarity_ratio(f.lower(), fk.lower())
            if ratio > best_ratio:
                best_ratio = ratio
        if best_ratio > 0.6:
            near_matches.append((name, e, best_ratio))

    if exact_matches:
        # First exact wins (preserves prior behaviour). Runner-ups are the
        # OTHER exact-match entities — silent ambiguity worth surfacing.
        picked_name, picked = exact_matches[0]
        alts: list[dict] = []
        for other_name, other in exact_matches[1:4]:
            alts.append({
                "target": other.get("name") or other_name,
                "score": 1.0,
                "reason": f"same _norm as picked ({want!r})",
            })
        # If we had EXACT matches, don't pad with fuzzy near-misses —
        # the fuzzy set is noise once the norm has agreed.
        return picked, alts

    # No exact match. Surface closest names so user sees a fixable target.
    near_matches.sort(key=lambda t: t[2], reverse=True)
    alts = [
        {
            "target": e.get("name") or n,
            "score": round(ratio, 2),
            "reason": f"edit-distance match to {fk!r}",
        }
        for n, e, ratio in near_matches[:3]
    ]
    return None, alts


def _similarity_ratio(a: str, b: str) -> float:
    """difflib SequenceMatcher ratio — 0..1. Cheap, stdlib, good enough for
    'did you mean' hints against 10-20 entity names."""
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio()


def _is_users(entity: dict | None) -> bool:
    if not entity:
        return False
    reserved = {_norm(s) for s in RESERVED_USER_SLUGS}
    return any(_norm(entity.get(k)) in reserved
               for k in ("slug", "table", "name", "id"))


def _is_tenancy_entity(entity: dict | None) -> bool:
    if not entity:
        return False
    return _norm(entity.get("slug") or entity.get("table") or "") in {
        "workspaces", "workspace", "tenants", "tenant", "organizations",
        "organization", "orgs", "org", "accounts", "account",
    }


def _resolve_entity(ents: dict, entity_id: str) -> tuple[dict | None, str | None]:
    """(entity_dict, entity_key) for `entity_id`, matched against the dict key or any
    identity form (name/slug/table/camel/id/singular)."""
    entity = ents.get(entity_id)
    if isinstance(entity, dict):
        return entity, entity_id
    want = _norm(entity_id)
    for name, e in ents.items():
        if not isinstance(e, dict):
            continue
        if _norm(name) == want or any(
            _norm(e.get(k)) == want for k in ("name", "slug", "table", "camel", "id", "singular")
        ):
            return e, name
    return None, None


def _entity_idents(entity: dict, entity_key: str | None) -> set[str]:
    forms = {entity_key, entity.get("name"), entity.get("slug"), entity.get("table"),
             entity.get("camel"), entity.get("id"), entity.get("singular")}
    return {_norm(f) for f in forms if f}


def _relation_fk_map(registry: dict, entity: dict, entity_key: str | None) -> dict[str, str]:
    """{norm(fk_column): target_entity_ref} from the registry's top-level relations for
    the FROM side matching this entity. Supports both the Contract-Registry shape
    (`relations`: from_entity/to_entity/foreignKey) and the canonical resource-registry
    shape (`relationships`: from/to/fkColumn)."""
    idents = _entity_idents(entity, entity_key)
    out: dict[str, str] = {}
    rels = list(registry.get("relations") or []) + list(registry.get("relationships") or [])
    for r in rels:
        if not isinstance(r, dict):
            continue
        frm = r.get("from_entity") or r.get("from") or r.get("fromEntity")
        if _norm(frm) not in idents:
            continue
        fk_col = r.get("foreignKey") or r.get("fkColumn") or r.get("fk") or r.get("column")
        to = r.get("to_entity") or r.get("to") or r.get("toEntity")
        if fk_col and to:
            out[_norm(fk_col)] = to
    return out


def _columns_for(entity: dict, registry: dict, entity_key: str | None) -> list[dict]:
    """Normalise an entity into a list of ``{name, type, notNull, primaryKey, fk}`` column
    dicts. Prefers the canonical ``columns`` list (carries the real ``fk`` per column);
    otherwise synthesises columns from the Contract-Registry ``fields`` dict, deriving each
    column's ``fk`` from the registry's relations (foreignKey → to_entity)."""
    cols = entity.get("columns")
    if isinstance(cols, list) and cols:
        return [c for c in cols if isinstance(c, dict) and c.get("name")]

    fields = entity.get("fields")
    if not isinstance(fields, (dict, list)):
        return []
    if isinstance(fields, dict):
        items = list(fields.items())
    else:
        items = [(f.get("name") or f.get("key"), f) for f in fields
                 if isinstance(f, dict) and (f.get("name") or f.get("key"))]

    relmap = _relation_fk_map(registry, entity, entity_key)
    out: list[dict] = []
    for name, meta in items:
        if not name:
            continue
        meta = meta if isinstance(meta, dict) else {}
        not_null = meta.get("notNull") is True or meta.get("nullable") is False
        out.append({
            "name": name,
            "type": meta.get("type"),
            "notNull": not_null,
            "primaryKey": meta.get("primaryKey"),
            "fk": meta.get("fk") or relmap.get(_norm(name)),
            # Spec D W2 — planner-authored role on the column, if any.
            # Preserved verbatim so classify_entity_fks can honor it before
            # falling back to the name-regex classifier.
            "role": meta.get("role"),
        })
    return out


def classify_entity_fks(
    entity_id: str,
    registry: dict,
    plan: dict | None = None,
) -> dict[str, FkRole]:
    """Classify one entity's FK columns.

    Spec D W2 — the classifier now checks the planner-authored role from
    TWO sources before falling back to name/regex classification:
      1. ``plan.entities[].fields[].role`` — via the shared reader
         :func:`services.plan_column_semantics.get_fk_role` (only when
         ``plan`` is supplied by the caller).
      2. ``registry.entities[].fields[].role`` — as before, via
         :func:`_columns_for`.
    Either wins verbatim when it names a value in the closed set
    (``actor`` | ``assignment`` | ``tenancy`` | ``domain``). ``plan``
    takes precedence: the planner is the source of truth, the registry
    is a downstream projection that may or may not have carried the
    ``role`` field forward.
    """
    # Local import — plan_column_semantics imports plan_field_lookup which
    # imports nothing else in the classifier surface, but keeping the
    # import local means fk_semantics has no new hard dependency at
    # module load and existing callers who never pass `plan` pay nothing.
    from services.plan_column_semantics import get_fk_role as _plan_get_fk_role

    ents = registry.get("entities") or {}
    entity, entity_key = _resolve_entity(ents, entity_id)
    if not isinstance(entity, dict):
        return {}

    # The entity's identity forms (name / slug / table / camel …) — any of
    # them can be the key the plan file uses. `get_field` is case-insensitive
    # so passing a form the plan doesn't literally use still resolves.
    plan_lookup_names = [entity_key or entity_id]
    for k in ("name", "slug", "table", "camel", "id", "singular"):
        v = entity.get(k)
        if isinstance(v, str) and v and v not in plan_lookup_names:
            plan_lookup_names.append(v)

    def _planner_role_for(col_name: str) -> str | None:
        # Try each identity form; the reader returns None on any miss.
        if plan is None:
            return None
        for ename in plan_lookup_names:
            r = _plan_get_fk_role(plan, ename, col_name)
            if r:
                return r
        return None

    out: dict[str, FkRole] = {}
    _VALID_PLANNER_ROLES = ("actor", "assignment", "tenancy", "domain")
    for col in _columns_for(entity, registry, entity_key):
        if not isinstance(col, dict) or not col.get("name"):
            continue
        name = col["name"]
        nn = bool(col.get("notNull"))
        fk = col.get("fk")
        low = _norm(name)

        # Spec D W2 — planner-authored role wins over regex classification.
        # PRECEDENCE: plan (source of truth) → registry (projection) →
        # name-regex fallback. The plan reader normalises the value to
        # the closed set for us; the registry-side check does its own
        # closed-set gate below.
        planner_role = _planner_role_for(name)
        if planner_role is None:
            planner_role = col.get("role")
        if isinstance(planner_role, str) and planner_role in _VALID_PLANNER_ROLES:
            target = _resolve_target(registry, fk) if fk else None
            out[name] = FkRole(
                name, planner_role,
                target_slug=(target or {}).get("slug") if target else None,
                target_table=(target or {}).get("table") if target else None,
                required=nn,
            )
            continue

        if fk:
            target = _resolve_target(registry, fk)
            if _is_users(target):
                # FK to users: a self/creator column auto-fills (actor); an assignment
                # column is a people-picker Select of users (assignment).
                role = "assignment" if _ASSIGNMENT_NAME_RE.match(name) else "actor"
            elif _is_tenancy_entity(target):
                role = "tenancy"
            else:
                role = "domain"
            out[name] = FkRole(name, role,
                               target_slug=(target or {}).get("slug") if target else None,
                               target_table=(target or {}).get("table") if target else None,
                               required=nn)
            continue
        # no real FK — fall back to NAME only for non-domain classification
        if low in _TENANCY_NAMES:
            out[name] = FkRole(name, "tenancy", required=nn)
        elif _ACTOR_NAME_RE.match(name):
            out[name] = FkRole(name, "actor", required=nn)
        else:
            out[name] = FkRole(name, "plain", required=nn)
    return out


def _load_registry(output_dir: str) -> dict | None:
    """Load the canonical registry (contracts/resource-registry.json → registry.json)."""
    base = Path(output_dir)
    for rel in ("contracts/resource-registry.json", "registry.json"):
        p = base / rel
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("entities"), dict):
            return data
    return None


def _load_plan_safe(output_dir: str | None) -> dict | None:
    """Return the persisted plan JSON, or ``None`` on any error.

    Spec D W2 — every classifier entry point that has an ``output_dir``
    handy loads the plan through here and threads it into
    :func:`classify_entity_fks` so the planner-authored ``fields[].role``
    beats the name-regex classifier without callers having to remember.
    """
    if not output_dir:
        return None
    try:
        from services.plan_field_lookup import load_plan
        return load_plan(output_dir)
    except Exception:  # noqa: BLE001 — never fail classification because plan I/O hiccuped
        return None


def emit_fk_semantics(output_dir: str) -> str | None:
    """Write ``contracts/fk-semantics.json`` — the backend-consumer artifact.

    Shape: ``{entityId: {col: {role, targetSlug, targetTable, required}}}``.
    Returns the path written, or None when no registry is present.
    """
    reg = _load_registry(output_dir)
    if not reg:
        return None
    allroles = classify_registry(reg, output_dir)
    payload = {
        entity_id: {
            col: {
                "role": r.role,
                "targetSlug": r.target_slug,
                "targetTable": r.target_table,
                "required": r.required,
            }
            for col, r in roles.items()
        }
        for entity_id, roles in allroles.items()
    }
    cdir = Path(output_dir) / "contracts"
    cdir.mkdir(parents=True, exist_ok=True)
    out_path = cdir / "fk-semantics.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Wrote contracts/fk-semantics.json (%d entities)", len(payload))
    return str(out_path)


def emit_fk_roles_module(output_dir: str) -> str | None:
    """Write ``src/lib/fk-roles.ts`` — the runtime FK-role lookup.

    Emits ``FK_ROLES: {table: {column: role}}`` keyed by each entity's REAL table
    name, plus ``fkRole``/``isAutoFillFk``/``isDomainFk`` helpers. Returns the path
    written, or None when no registry is present.
    """
    reg = _load_registry(output_dir)
    if not reg:
        return None
    allroles = classify_registry(reg, output_dir)
    ents = reg.get("entities") or {}

    table_map: dict[str, dict[str, str]] = {}
    for entity_id, roles in allroles.items():
        entity = ents.get(entity_id)
        table = (entity or {}).get("table") or (entity or {}).get("slug") or entity_id
        if not table:
            continue
        bucket = table_map.setdefault(str(table), {})
        for col, r in roles.items():
            bucket[col] = r.role

    entries = ",\n".join(
        "  {}: {{ {} }}".format(
            json.dumps(table),
            ", ".join(f"{json.dumps(c)}: {json.dumps(role)}" for c, role in cols.items()),
        )
        for table, cols in sorted(table_map.items())
    )
    content = (
        "// FK-role authority for the runtime. Generated from the canonical registry\n"
        "// (resource-registry.json) so auto-fill/form-exclusion read the REAL FK role\n"
        "// instead of matching the column NAME. A domain FK (target != users) is never\n"
        "// auto-filled with the current user's id.\n"
        "export const FK_ROLES: Record<string, Record<string, string>> = {\n"
        f"{entries}\n"
        "};\n\n"
        "export function fkRole(table: string, col: string): string {\n"
        '  return FK_ROLES[table]?.[col] || "plain";\n'
        "}\n\n"
        "export function isAutoFillFk(table: string, col: string): boolean {\n"
        '  const r = fkRole(table, col); return r === "actor" || r === "tenancy";\n'
        "}\n\n"
        "export function isDomainFk(table: string, col: string): boolean {\n"
        '  return fkRole(table, col) === "domain";\n'
        "}\n"
    )
    lib_dir = Path(output_dir) / "src" / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    out_path = lib_dir / "fk-roles.ts"
    out_path.write_text(content, encoding="utf-8")
    logger.info("Wrote src/lib/fk-roles.ts (%d tables)", len(table_map))
    return str(out_path)


def _entity_for_table(reg: dict, table: str) -> dict | None:
    """Find the entity whose declared table (or slug/name) matches `table`."""
    want = _norm(table)
    if not want:
        return None
    for name, e in (reg.get("entities") or {}).items():
        if not isinstance(e, dict):
            continue
        for form in (e.get("table"), e.get("slug"), name, e.get("name"),
                     e.get("camel"), e.get("id")):
            if form and _norm(form) == want:
                return e
    return None


def classify_registry(registry: dict, output_dir: str | None = None) -> dict[str, dict[str, FkRole]]:
    """Classify every entity's FK columns.

    Returns ``{entity_id: {column: FkRole}}`` keyed by the registry's entity id
    (the dict key). When ``output_dir`` is given, the emitted Drizzle schema's
    real ``.references()`` targets are consulted as a FALLBACK: any column that the
    registry left ``fk``-less but the schema says references a NON-users table is
    upgraded to ``domain`` (schema is authoritative; a domain classification is
    never downgraded).

    Spec D W2 — when ``output_dir`` is given, ``plan.json`` is also loaded and
    threaded into :func:`classify_entity_fks` so a planner-authored
    ``fields[].role`` beats the name-regex classifier across every entity in
    the registry, not just those whose registry projection happened to
    carry the ``role`` field forward.
    """
    plan = _load_plan_safe(output_dir)
    ents = registry.get("entities") or {}
    out: dict[str, dict[str, FkRole]] = {}
    for entity_id, entity in ents.items():
        if not isinstance(entity, dict):
            continue
        out[entity_id] = classify_entity_fks(entity_id, registry, plan)

    # Decision ledger (REL-S1) — record every FK column with its resolved
    # target + runner-ups. High-confidence single-match picks ship silent
    # (audit trail only); norm-collision runner-ups and no-match cases
    # surface as chips so users can override the pick before shipping.
    if output_dir:
        try:
            from services import decision_ledger as _dl
            for entity_id, entity in ents.items():
                if not isinstance(entity, dict):
                    continue
                # Check bindings first — user may have already resolved
                # a prior run's ambiguity. Skip re-recording if binding
                # short-circuited the resolve. (Bindings only apply to
                # low-confidence picks; high-confidence still record.)
                for col in _columns_for(entity, registry, entity_id):
                    if not isinstance(col, dict) or not col.get("name"):
                        continue
                    fk = col.get("fk")
                    if not fk:
                        continue
                    picked, alts = _resolve_target_verbose(registry, fk)
                    # Confidence: high when exact, no ambiguity;
                    # medium when norm-collision (multiple exact matches);
                    # low when no match at all (only fuzzy alternatives).
                    if picked and not alts:
                        confidence: float | str = _dl.BAND_HIGH
                    elif picked and alts:
                        confidence = _dl.BAND_MEDIUM
                    else:
                        confidence = _dl.BAND_LOW
                    target_display = (
                        (picked.get("name") if picked else None) or
                        (picked.get("slug") if picked else None) or
                        f"unresolved:{fk}"
                    )
                    entity_name = entity.get("name") or entity_id
                    _dl.record_pick(
                        output_dir,
                        kind=_dl.KIND_FK_TARGET,
                        scope=f"entity:{entity_name}",
                        identity=col["name"],
                        target_picked=str(target_display),
                        confidence=confidence,
                        source_emitter="fk_semantics",
                        alternatives=[
                            _dl.make_alternative(
                                target=a["target"],
                                score=float(a.get("score") or 0),
                                reason=str(a.get("reason") or ""),
                            )
                            for a in (alts or [])
                        ],
                        reason=(
                            f"exact norm-match on {fk!r}" if picked and not alts
                            else f"multiple entities share norm {fk!r}" if picked and alts
                            else f"no entity matches {fk!r}; did you mean an alternative?"
                        ),
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[fk-semantics] decision ledger skipped: %s", exc)

    if not output_dir:
        return out

    # Schema `.references()` fallback — {table: {col: target_table}}.
    try:
        from services.registry_schema_reconcile import extract_fk_references
        fk_refs = extract_fk_references(output_dir) or {}
    except Exception as e:  # noqa: BLE001 — schema parse is best-effort
        logger.warning("extract_fk_references skipped: %s", e)
        fk_refs = {}

    if not fk_refs:
        return out

    # Index schema tables (normalized) → {col_norm: target_table}.
    refs_by_norm: dict[str, dict[str, str]] = {}
    for table, cols in fk_refs.items():
        bucket = refs_by_norm.setdefault(_norm(table), {})
        for col, target in (cols or {}).items():
            bucket[_norm(col)] = target

    for entity_id, entity in ents.items():
        if not isinstance(entity, dict):
            continue
        table_norm = _norm(entity.get("table") or entity.get("slug") or entity_id)
        schema_cols = refs_by_norm.get(table_norm)
        if not schema_cols:
            continue
        roles = out.get(entity_id) or {}
        for col in _columns_for(entity, registry, entity_id):
            if not isinstance(col, dict) or not col.get("name"):
                continue
            name = col["name"]
            cur = roles.get(name)
            # Only upgrade columns the registry left fk-less that ended up
            # actor/tenancy/plain — never downgrade an existing domain.
            if cur is not None and cur.role == "domain":
                continue
            if col.get("fk"):
                continue
            target_table = schema_cols.get(_norm(name))
            if not target_table:
                continue
            target_entity = _entity_for_table(registry, target_table)
            if _is_users(target_entity):
                # a real FK to users is an actor (auto-fill) — UNLESS it names an
                # assignment (assignee/reviewer/…), which is a users people-picker.
                if _ASSIGNMENT_NAME_RE.match(name):
                    roles[name] = FkRole(
                        name, "assignment",
                        target_slug=(target_entity or {}).get("slug") if target_entity else None,
                        target_table=(target_entity or {}).get("table") if target_entity else target_table,
                        required=bool(col.get("notNull")),
                    )
                continue
            role = "tenancy" if _is_tenancy_entity(target_entity) else "domain"
            if role == "domain":
                roles[name] = FkRole(
                    name, "domain",
                    target_slug=(target_entity or {}).get("slug") if target_entity else None,
                    target_table=(target_entity or {}).get("table") if target_entity else target_table,
                    required=bool(col.get("notNull")),
                )
        out[entity_id] = roles
    return out


# ── shared consumer helper — the ONE hidden-FK decision ──────────────────────
# Every backend layer that used to hide/exclude FK columns from create/edit forms did
# it by matching the column NAME against a private `_OWNER_FK` set. Those sets disagreed
# and — fatally — hid a real DOMAIN FK (`pets.ownerId → owners`) that should be an
# editable Select. `hidden_fk_columns` replaces them all: a column is hidden ONLY when
# its ROLE is `actor` or `tenancy` (server-filled). A `domain` FK is NEVER hidden.

# Conservative name-based default — the union of every legacy `_OWNER_FK`/`_TENANCY_FK`
# set — used ONLY as a fallback when no registry is available to classify roles, so
# registry-less callers keep their old behavior instead of regressing. Pre-normalised.
_DEFAULT_HIDDEN_FK_NAMES: frozenset[str] = frozenset({
    # user-ownership / actor FKs (name-based)
    "ownerid", "landlordid", "userid", "createdbyid", "updatedbyid", "authorid",
    "assigneeid", "managerid", "createdby", "updatedby",
    # tenancy FKs (name-based)
    "workspaceid", "tenantid", "orgid", "organizationid", "accountid",
})


def default_hidden_fk_norms() -> set[str]:
    """The conservative name-based hidden-FK set (normalised) for registry-less fallback."""
    return set(_DEFAULT_HIDDEN_FK_NAMES)


def _find_entity_key(registry: dict, entity_id: str) -> str | None:
    ents = registry.get("entities") or {}
    if entity_id in ents:
        return entity_id
    _, key = _resolve_entity(ents, entity_id)
    return key


def _entity_roles(entity_id: str, registry: dict, output_dir: str | None) -> dict[str, FkRole]:
    """Roles for one entity. When an ``output_dir`` is given we prefer the CANONICAL
    registry (``contracts/resource-registry.json``, with real ``columns[].fk`` targets)
    loaded from it — the authority must not depend on which (possibly thin, ``fields``-
    shaped) registry dict a caller happened to pass. The schema ``.references()``
    fallback in ``classify_registry`` still catches a domain FK the registry left
    ``fk``-less.

    Spec D W2 — the fallback path (no allroles hit) also threads plan.json
    into ``classify_entity_fks`` so the planner-authored role beats the
    name-regex classifier for consumers coming through ``hidden_fk_columns``.
    """
    plan = _load_plan_safe(output_dir)
    primary = registry
    if output_dir:
        canonical = _load_registry(output_dir)
        if canonical and canonical.get("entities"):
            primary = canonical
        try:
            allroles = classify_registry(primary, output_dir)
        except Exception as e:  # noqa: BLE001 — never let classification fail a build pass
            logger.warning("classify_registry failed in hidden_fk_columns: %s", e)
            allroles = {}
        key = _find_entity_key(primary, entity_id) or _find_entity_key(registry, entity_id)
        if key and allroles.get(key):
            return allroles[key]
    return (classify_entity_fks(entity_id, primary, plan)
            or classify_entity_fks(entity_id, registry, plan))


def hidden_fk_columns(entity_id: str, registry: dict, output_dir: str | None = None) -> set[str]:
    """Normalized column names that must NOT appear as editable form fields — i.e. FK
    columns whose role is ``actor`` or ``tenancy`` (server-filled). Domain FKs are NOT
    hidden (they need a Select). Returns normalized (lowercased, separator-stripped)
    names for membership tests.

    When the entity can't be classified (no registry / entity absent), returns the
    conservative name-based default (`default_hidden_fk_norms`) so registry-less callers
    don't regress; the PRIMARY path is role-based off the registry's real FK targets.
    """
    registry = registry or {}
    roles = _entity_roles(entity_id, registry, output_dir)
    if not roles:
        return set(_DEFAULT_HIDDEN_FK_NAMES)
    return {_norm(col) for col, r in roles.items() if r.role in ("actor", "tenancy")}
