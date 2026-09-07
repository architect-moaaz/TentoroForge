"""Deterministic Drizzle schema + TypeScript types builder.

Replaces the mechanical part of the LLM schema agent. Given a plan it emits ONLY
per-entity Drizzle tables + inferred types (plus their barrels):

    src/db/schema/<slug>.ts   — pgTable(...) + relations(...)
    src/db/schema/index.ts    — barrel
    src/types/<slug>.ts       — $inferSelect / $inferInsert
    src/types/index.ts        — barrel

Config files (package.json, next.config.ts, tailwind.config.ts,
drizzle.config.ts, src/db/index.ts, src/lib/utils.ts) come from the project
templates + app_emitter.py and are intentionally NOT emitted here.

Conventions mirror agents/schema_agent.py's prompt and the generated apps under
output/: postgres-js driver, `pgTable`, snake_case columns, camelCase TS,
inline `.references(() => other.id)` FKs, per-file `relations()` blocks, and a
`createdAt`/`updatedAt` timestamp pair (defaultNow().notNull()).
"""

import logging
import re
from pathlib import Path
from typing import Any

from services.contract_generator import _to_camel
from services.name_normalizer import name_family
from services.registry_schema_reconcile import pair_fk_columns_to_relationships
from services.resource_registry import build_canonical_registry

# Tables the auth foundation owns (template provides the schema with the
# next-auth/password columns). Plan entities mapping to these are skipped so the
# deterministic builder never clobbers the auth-correct definition.
RESERVED_TABLES = {"users"}

# Reserved auth tables live in the template's own schema module, whose file slug
# differs from the registry's pluralized slug: the template ships
# `src/db/schema/user.ts` exporting `export const users = pgTable("users", …)`.
# A child entity's FK to the reserved table must import the const from THIS file,
# not the registry's "./users" slug (which the builder never writes).
RESERVED_IMPORT_SLUG = {"users": "user"}

# The auth foundation's canonical `users` columns (mirrors the template's
# src/db/schema/user.ts). When the planner models a domain `User` entity with
# extra columns (notably a `role`), the builder MERGES those over this base into a
# SINGLE pgTable("users") so `password`/`email`/`id` stay auth-correct while the
# app-specific columns land — never a second pgTable("users").
_AUTH_USERS_BASE_LINES = [
    '  id: uuid("id").primaryKey().defaultRandom(),',
    '  email: text("email").notNull().unique(),',
    '  password: text("password").notNull(),',
    '  name: text("name"),',
    '  isActive: boolean("is_active").default(true),',
    '  createdAt: timestamp("created_at").defaultNow(),',
]
_AUTH_USERS_BASE_BUILDERS = ["uuid", "text", "boolean", "timestamp"]
# Normalised names already present in the auth base — a domain column matching one
# of these is dropped (the auth-correct definition wins).
_AUTH_USERS_BASE_NAMES = {
    "id", "email", "password", "name", "isactive", "createdat", "updatedat",
}


def _norm_col(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())

logger = logging.getLogger(__name__)


# ─── plan normalisation ───

def _normalize_models(data_models: Any) -> list[dict]:
    """Accept a list of entities OR a legacy dict keyed by entity name."""
    if isinstance(data_models, dict):
        out: list[dict] = []
        for name, spec in data_models.items():
            if isinstance(spec, dict):
                model = dict(spec)
                model.setdefault("name", name)
            else:
                model = {"name": name, "fields": spec or []}
            out.append(model)
        return out
    if isinstance(data_models, list):
        return [m for m in data_models if isinstance(m, dict) and m.get("name")]
    return []


def _rel_get(rel: dict, *keys: str) -> str | None:
    for k in keys:
        v = rel.get(k)
        if v:
            return str(v)
    return None


def _to_snake(name: str) -> str:
    """camelCase / PascalCase → snake_case."""
    s = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    return s.replace("__", "_")


# ─── registry lookups (the single naming authority) ───

def _reg_record(reg_entities: dict, name: str) -> dict:
    """Canonical name family for an entity, read from the registry by name.

    Falls back to a fresh ``name_family`` only if the registry is missing the
    entity — defensive, since the registry is built from the SAME plan, so this
    should not happen in practice.
    """
    rec = reg_entities.get(name)
    if rec:
        return rec
    return name_family(name)


def _reg_table(reg_entities: dict, name: str) -> str:
    """The pgTable const / name for an entity (registry-owned, hint-honoring)."""
    return _reg_record(reg_entities, name)["table"]


def _reg_slug(reg_entities: dict, name: str) -> str:
    """The file/route slug for an entity (registry-owned, hint-honoring)."""
    return _reg_record(reg_entities, name)["slug"]


def _reg_import_slug(reg_entities: dict, name: str) -> str:
    """The file slug to import an entity's schema const FROM.

    Same as ``_reg_slug`` except reserved auth tables (``users``) resolve to the
    template's own module (``./user``), not the registry's pluralized slug — the
    builder never writes a ``users.ts``, so a child FK must import from the file
    the template actually ships.
    """
    table = _reg_table(reg_entities, name)
    if table in RESERVED_IMPORT_SLUG:
        return RESERVED_IMPORT_SLUG[table]
    return _reg_slug(reg_entities, name)


# ─── column type → Drizzle builder ───

# maps a normalised SQL type to (builder_name, extra_args_renderer)
def _builder_for(field: dict) -> tuple[str, str]:
    """Return (drizzle_builder_name, args_string) for a field.

    args_string is the full call arg list e.g. `"title", { length: 255 }`.
    """
    col = _to_snake(field.get("name", ""))
    t = str(field.get("type", "varchar")).lower().strip()

    if "serial" in t:
        return "serial", f'"{col}"'
    if "uuid" in t:
        return "uuid", f'"{col}"'
    if "bool" in t:
        return "boolean", f'"{col}"'
    if "json" in t:  # json / jsonb
        return "jsonb", f'"{col}"'
    if "decimal" in t or "numeric" in t:
        precision = field.get("precision", 12)
        scale = field.get("scale", 2)
        return "decimal", f'"{col}", {{ precision: {precision}, scale: {scale} }}'
    if t == "money" or t == "currency":
        # First-class banking money — decimal(19,4) always. 15 digits of currency
        # + 4 fractional (industry standard for FX + crypto). Plans MUST NOT
        # override precision/scale for `money`; use `decimal`/`numeric` with
        # explicit precision/scale if a different shape is intended. A sibling
        # `<field>_currency` column is emitted by `_emit_entity` (see the
        # `_derive_currency_sibling_name` helper); this branch only owns the
        # AMOUNT column.
        return "decimal", f'"{col}", {{ precision: 19, scale: 4 }}'
    if "double" in t or "float8" in t or "precision" in t or "price" in t or "amount" in t:
        # O10 fix: cover the classes that were silently falling through to integer.
        # `price`, `amount`, and the planner's occasional "double precision"
        # string all belong here. Prior code only matched "double"/"float8"; a plan
        # that typed `price: "double precision"` matched neither and — because
        # "int" is not a substring of any of those — dropped to the varchar branch,
        # which drizzle-kit later emitted as `integer` in some pipelines. Widen the
        # numeric match so money-shaped columns can never land as varchar or int.
        # (`money`/`currency` are handled by the branch above — they get an exact
        # decimal(19,4) + sibling currency column, not doublePrecision.)
        return "doublePrecision", f'"{col}"'
    if t in ("real", "float", "float4"):
        return "real", f'"{col}"'
    if "big" in t and "int" in t:
        return "bigint", f'"{col}", {{ mode: "number" }}'
    if "int" in t:  # integer / int / smallint
        # Semantic guard: field names that inherently hold fractional
        # values (confidence, score, probability, ratio, percent…) get
        # widened to `real` even when the plan typed them as `integer`.
        # Rationale: `integer` truncates a Claude confidence of 0.99 to 1,
        # then a `min:0, max:1` rule on the "1" edge appears passing while
        # every value below 0.5 rounds to 0. This is a source-side fix so
        # LLM-authored typing mistakes don't force per-app patches.
        semantic = str(field.get("semantic") or field.get("semantic_type") or "").lower().strip()
        name_lc = (field.get("name") or "").lower()
        fractional_keywords = ("confidence", "score", "rating", "probability", "ratio", "percent", "percentage")
        looks_fractional = (
            semantic in ("confidence", "probability", "ratio", "percent", "percentage", "score")
            or any(k in name_lc for k in fractional_keywords)
        )
        if looks_fractional and "precision" not in field and "scale" not in field:
            return "real", f'"{col}"'
        return "integer", f'"{col}"'
    if "timestamp" in t or "datetime" in t or t == "date" or "time" in t:
        return "timestamp", f'"{col}"'
    if t == "text":
        return "text", f'"{col}"'
    # varchar / char / string / enum(varchar) / anything else
    length = field.get("length", 255)
    return "varchar", f'"{col}", {{ length: {length} }}'


def _render_default(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return f".default({'true' if value else 'false'})"
    if isinstance(value, (int, float)):
        return f".default({value})"
    sval = str(value)
    if sval.lower() in ("now", "now()", "defaultnow", "current_timestamp"):
        return ".defaultNow()"
    return f'.default("{sval}")'


# ─── main entry ───

def build_schema_files(plan: dict, output_dir: str, registry: dict | None = None) -> dict:
    """Emit per-entity Drizzle schema + types under output_dir.

    Table names, file slugs and FK target tables all come from the Canonical
    Resource Registry (the single naming authority) rather than being re-derived
    here. Pass a prebuilt ``registry`` to reuse the pipeline's; when None it is
    built once from ``plan`` (keeps existing callers working).

    Returns {"generated": [relative paths], "errors": [str]}.
    """
    root = Path(output_dir)
    schema_dir = root / "src" / "db" / "schema"
    types_dir = root / "src" / "types"
    schema_dir.mkdir(parents=True, exist_ok=True)
    types_dir.mkdir(parents=True, exist_ok=True)

    generated: list[str] = []
    errors: list[str] = []

    if registry is None:
        registry = build_canonical_registry(plan)
    reg_entities = registry.get("entities", {})

    models = _normalize_models(plan.get("data_models"))
    # The `users` table is owned by the auth foundation: the template ships
    # src/db/schema/user.ts with the next-auth/password columns that auth.ts and
    # the admin seed depend on. A plan `User` entity maps to the SAME table, so
    # emitting it here creates a second pgTable("users") that clobbers the
    # auth-correct one (dropping `password` → admin seed fails at runtime). Skip
    # any entity that resolves to a reserved auth table; auth owns it.
    reserved_models = [m for m in models if _reg_table(reg_entities, m["name"]) in RESERVED_TABLES]
    if reserved_models:
        models = [m for m in models if _reg_table(reg_entities, m["name"]) not in RESERVED_TABLES]
    relations = plan.get("relations") or []
    by_name = {m["name"]: m for m in models}

    # Resolve relations into: FK ownership + per-entity relation entries.
    #   fk_refs[entity][field_name] = referenced_entity
    #   rel_blocks[entity] = list of rendered relation body lines
    fk_refs: dict[str, dict[str, str]] = {m["name"]: {} for m in models}
    one_rels: dict[str, list[tuple[str, str, str]]] = {m["name"]: [] for m in models}   # (relName, refEntity, fkField)
    coll_rels: dict[str, list[tuple[str, str, bool]]] = {m["name"]: [] for m in models}  # (relName, ownerEntity, is_one)

    for rel in relations:
        if not isinstance(rel, dict):
            continue
        frm = _rel_get(rel, "from", "fromEntity", "source", "parent")
        to = _rel_get(rel, "to", "toEntity", "target", "child")
        fk = _rel_get(rel, "foreignKey", "fk", "foreign_key", "field", "column")
        rtype = (_rel_get(rel, "type", "relation", "kind") or "many-to-one").lower()
        if not frm or not to or not fk:
            continue
        if frm not in by_name or to not in by_name:
            continue

        # Determine which side OWNS the FK column (holds a field named fk).
        def _has_field(entity: str, field: str) -> bool:
            return any(f.get("name") == field for f in by_name[entity].get("fields", []))

        if _has_field(frm, fk):
            owner, referenced = frm, to
        elif _has_field(to, fk):
            owner, referenced = to, frm
        else:
            owner, referenced = frm, to  # default: FK lives on the "from" side

        fk_refs[owner][fk] = referenced
        # owner -> one(referenced)
        one_rels[owner].append((_to_camel(referenced), referenced, fk))
        # referenced -> many(owner)  (or one, for a one-to-one)
        is_one = "one-to-one" in rtype or rtype == "1-1"
        rel_name = _to_camel(owner) if is_one else _reg_table(reg_entities, owner)
        coll_rels[referenced].append((rel_name, owner, is_one))

    # Fill in FK targets the relation loop above could not resolve, so EVERY
    # FK-shaped column emits a real `.references()` (the DB gets referential
    # integrity, not just the UI). Both sources read the SAME canonical registry
    # (built from this plan) so target table const/slug stay exact:
    #   (1) a relationship exists but named no `foreignKey` column — pair the
    #       entity's FK-shaped columns to its relationships by the shared
    #       name-then-elimination algorithm (registry_schema_reconcile.
    #       pair_fk_columns_to_relationships), reused so the two never drift;
    #   (2) an explicit FK whose target is a RESERVED table (User→users) — the
    #       relation loop skips it (the reserved entity isn't in `by_name`), but
    #       the registry column still carries its resolved `fk`.
    # `setdefault` keeps any explicit non-reserved FK the loop already set.
    id_to_name = {rec.get("id"): nm for nm, rec in reg_entities.items() if rec.get("id")}
    for owner_name, refs in fk_refs.items():
        rec = reg_entities.get(owner_name)
        if not isinstance(rec, dict):
            continue
        # (2) explicit registry-column fks (covers reserved targets skipped above)
        for col in rec.get("columns", []):
            if not isinstance(col, dict):
                continue
            tgt_name = id_to_name.get(col.get("fk")) if col.get("fk") else None
            if tgt_name:
                refs.setdefault(col.get("name"), tgt_name)
        # (1) inferred pairings (name match, then 1-and-only-1 elimination)
        for col_name, tgt_id in pair_fk_columns_to_relationships(rec, registry).items():
            tgt_name = id_to_name.get(tgt_id)
            if tgt_name:
                refs.setdefault(col_name, tgt_name)

    # Merge planner domain columns (notably a `role` enum) into the auth-owned
    # `users` table — a SINGLE pgTable("users"), auth base preserved. Skipped when
    # the reserved User entity carries only base/auth columns (template untouched).
    try:
        _emit_merged_users(schema_dir, reserved_models, reg_entities, id_to_name,
                           registry, generated)
    except Exception as e:  # noqa: BLE001 — never fail the whole schema build
        errors.append(f"users(merge): {e}")
        logger.exception("schema_builder: failed to merge users table")

    # IRF-M3-T6: read denormalization stance from app_shape once (default "none"
    # → zero behavior change when the shape isn't set).
    denorm_mode = _denorm_mode_from_plan(plan)

    # Emit each entity.
    for model in models:
        name = model["name"]
        try:
            _emit_entity(
                schema_dir, types_dir, name, model,
                fk_refs.get(name, {}), one_rels.get(name, []), coll_rels.get(name, []),
                generated, reg_entities, denorm_mode,
            )
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
            logger.exception("schema_builder: failed to emit %s", name)

    # Barrels.
    try:
        _emit_schema_barrel(schema_dir, models, reg_entities)
        generated.append("src/db/schema/index.ts")
    except Exception as e:  # noqa: BLE001
        errors.append(f"schema/index.ts: {e}")
    try:
        _emit_types_barrel(types_dir, models, reg_entities)
        generated.append("src/types/index.ts")
    except Exception as e:  # noqa: BLE001
        errors.append(f"types/index.ts: {e}")

    # Slice-3 ledger contract: emit the append-only manifest the Data Engine
    # catch-all reads to reject PUT/DELETE on ledger entities. Always emit
    # (even when the set is empty) so the template's import never 404s the
    # module loader — the runtime cost of an empty Set is zero.
    try:
        rel = _emit_append_only_manifest(root, models, reg_entities)
        generated.append(rel)
    except Exception as e:  # noqa: BLE001
        errors.append(f"src/lib/append-only-entities.ts: {e}")

    # Slice-4 sensitive-columns manifest: the runtime data-engine reads this
    # to (a) compute+encrypt on write and (b) mask-vs-unmask on read. Always
    # emit (even when empty) so the runtime's static import never 404s.
    try:
        rel = _emit_sensitive_columns_manifest(root, models, reg_entities)
        generated.append(rel)
    except Exception as e:  # noqa: BLE001
        errors.append(f"src/lib/sensitive-columns.ts: {e}")

    # SEARCH-1 searchable-columns manifest: the runtime data-engine reads this
    # for op:"search" to build tsvector queries against the emitted `_search`
    # columns. Always emit (even when empty) so the runtime's static import
    # never 404s.
    try:
        rel = _emit_searchable_columns_manifest(root, models, reg_entities)
        generated.append(rel)
    except Exception as e:  # noqa: BLE001
        errors.append(f"src/lib/searchable-columns.ts: {e}")

    # Row-scoping manifest: the runtime data-engine reads this to add an owner
    # or tenant predicate to every read and write. This pipeline builds from a
    # plan, which carries no ``security.ownershipRules`` — so the manifest is
    # empty and nothing is scoped, exactly as it behaved before the manifest
    # existed. The file is still emitted because the runtime imports it
    # statically; declaring rules means moving the app onto the Blueprint
    # projection, which is where ``security.ownershipRules`` lives.
    try:
        rel = _emit_ownership_rules_manifest(root)
        generated.append(rel)
    except Exception as e:  # noqa: BLE001
        errors.append(f"src/lib/ownership-rules.ts: {e}")

    logger.info("schema_builder: %d generated, %d errors", len(generated), len(errors))
    return {"generated": generated, "errors": errors}


def _emit_ownership_rules_manifest(root: Path) -> str:
    """Write an empty ``src/lib/ownership-rules.ts``.

    The module body comes from the Blueprint projection so the two pipelines
    cannot render different lookups for the same manifest.
    """
    from services.blueprint.projection import render_ownership_rules_module

    lib_dir = root / "src" / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    (lib_dir / "ownership-rules.ts").write_text(
        render_ownership_rules_module({}), encoding="utf-8")
    return "src/lib/ownership-rules.ts"


def _emit_append_only_manifest(root: Path, models: list[dict], reg_entities: dict) -> str:
    """Write ``src/lib/append-only-entities.ts`` — the ledger set the Data
    Engine catch-all reads to reject PUT/DELETE on immutable entities.

    Every reachable name a caller might use is registered (entity name,
    table name, slug) so the check never misses because a manifest was keyed
    the wrong way. An empty set is written when no entities are append-only,
    so the template's static import always resolves.
    """
    lib_dir = root / "src" / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)
    names: set[str] = set()
    for m in models:
        if not _is_append_only(m):
            continue
        nm = m.get("name")
        if isinstance(nm, str):
            names.add(nm)
            names.add(nm.lower())
        rec = reg_entities.get(nm) if isinstance(nm, str) else None
        if isinstance(rec, dict):
            for k in ("table", "slug", "id"):
                v = rec.get(k)
                if isinstance(v, str) and v:
                    names.add(v)
                    names.add(v.lower())
    lines_out = [
        "// AUTO-GENERATED by services/schema_builder.py — do not hand-edit.",
        "// Every entity listed here is a ledger: rows INSERTed only, never",
        "// UPDATEd or DELETEd. The Data Engine catch-all in",
        "// src/app/api/data/[...path]/route.ts imports this Set and rejects",
        "// PUT/DELETE with a 405 { error: { code: \"LEDGER_IMMUTABLE\" } }.",
        "//",
        "// The set covers every reachable name a caller might use (entity",
        "// name, table, slug, both cased and lowercase) so a lookup never",
        "// misses because it was keyed the wrong way.",
        "export const APPEND_ONLY_ENTITIES: ReadonlySet<string> = new Set([",
    ]
    for n in sorted(names):
        lines_out.append(f'  "{n}",')
    lines_out.append("]);")
    lines_out.append("")
    lines_out.append("export function isAppendOnly(entity: string): boolean {")
    lines_out.append("  if (!entity) return false;")
    lines_out.append("  return APPEND_ONLY_ENTITIES.has(entity)")
    lines_out.append("    || APPEND_ONLY_ENTITIES.has(String(entity).toLowerCase());")
    lines_out.append("}")
    lines_out.append("")
    (lib_dir / "append-only-entities.ts").write_text("\n".join(lines_out), encoding="utf-8")
    return "src/lib/append-only-entities.ts"


def _emit_sensitive_columns_manifest(root: Path, models: list[dict], reg_entities: dict) -> str:
    """Write ``src/lib/sensitive-columns.ts`` — the manifest the Data Engine
    reads to (a) encrypt + compute a masked value on every write of a
    sensitive column, and (b) decide mask-vs-full-value on every read.

    Manifest shape (TS)::

        export const SENSITIVE_COLUMNS: Record<
          string,                                       // entity name (all reachable forms)
          Record<string, { mask: MaskKind; readers: string[] }>
        > = { ... };

    Every reachable name a caller might use is registered (entity name,
    table name, slug, both cased and lowercase), so the runtime's lookup
    never misses because a manifest was keyed the wrong way. An empty
    object is emitted when the app has no sensitive columns, so the
    template's static import always resolves.

    Precondition: this MUST be called AFTER ``_emit_entity`` runs on every
    model — the loop stashes ``_sensitiveOriginalName`` on each mutated
    field, and we read it here to key the manifest by the ORIGINAL
    (plaintext) column name (which is what the runtime knows).
    """
    lib_dir = root / "src" / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)

    per_entity: dict[str, dict[str, dict[str, Any]]] = {}
    for m in models:
        name = m.get("name")
        if not isinstance(name, str):
            continue
        readers_raw = m.get("sensitiveReaders")
        readers: list[str] = []
        if isinstance(readers_raw, list):
            readers = [
                r.strip() for r in readers_raw
                if isinstance(r, str) and r.strip()
            ]
        cols: dict[str, dict[str, Any]] = {}
        for f in m.get("fields", []):
            if not isinstance(f, dict) or not f.get("sensitive"):
                continue
            orig = f.get("_sensitiveOriginalName") or f.get("name")
            if not isinstance(orig, str) or not orig:
                continue
            mask = f.get("mask")
            if not isinstance(mask, str) or not mask.strip():
                # Default mask kind for account-number-shaped fields is
                # `last4` (matches the validator's guidance in the spec).
                # Callers who want a different default should declare it.
                mask = "last4"
            cols[orig] = {"mask": mask, "readers": list(readers)}
        if not cols:
            continue

        # Every reachable name for this entity — the runtime looks up by
        # whichever form the caller had (entity name, table, slug).
        rec = reg_entities.get(name) if isinstance(reg_entities, dict) else None
        forms: set[str] = {name, name.lower()}
        if isinstance(rec, dict):
            for k in ("table", "slug", "id"):
                v = rec.get(k)
                if isinstance(v, str) and v:
                    forms.add(v)
                    forms.add(v.lower())
        for form in forms:
            per_entity[form] = cols

    lines_out = [
        "// AUTO-GENERATED by services/schema_builder.py — do not hand-edit.",
        "//",
        "// Slice-4 sensitive-columns manifest. The Data Engine reads this at",
        "// both write time (compute masked value + encrypt) and read time",
        "// (mask-by-default; unmask only when the caller's role is in",
        "// `readers` AND the caller passes `unmask: true`).",
        "//",
        "// The manifest is keyed by every reachable name a caller might use",
        "// (entity name / table / slug, both cased and lowercase) so a",
        "// lookup never misses because it was keyed the wrong way.",
        "",
        'export type MaskKind = "last4" | "email" | "phone" | "full";',
        "",
        "export interface SensitiveColumnSpec {",
        "  /** Mask kind used to compute the pre-computed masked value on write. */",
        "  mask: MaskKind;",
        "  /** Role slugs that may request the full unmasked value.",
        '   * Empty [] = nobody unmasks; ["*"] = every authenticated user.',
        "   */",
        "  readers: string[];",
        "}",
        "",
        "export const SENSITIVE_COLUMNS: Record<",
        "  string,",
        "  Record<string, SensitiveColumnSpec>",
        "> = {",
    ]
    for ent in sorted(per_entity):
        lines_out.append(f'  "{ent}": {{')
        for col in sorted(per_entity[ent]):
            spec = per_entity[ent][col]
            readers_ts = "[" + ", ".join(f'"{r}"' for r in spec["readers"]) + "]"
            lines_out.append(
                f'    "{col}": {{ mask: "{spec["mask"]}", readers: {readers_ts} }},'
            )
        lines_out.append("  },")
    lines_out.append("};")
    lines_out.append("")
    lines_out.append("/** True when the entity has ANY sensitive column declared. */")
    lines_out.append("export function hasSensitiveColumns(entity: string): boolean {")
    lines_out.append("  if (!entity) return false;")
    lines_out.append("  return !!(SENSITIVE_COLUMNS[entity]")
    lines_out.append("    || SENSITIVE_COLUMNS[String(entity).toLowerCase()]);")
    lines_out.append("}")
    lines_out.append("")
    lines_out.append("/** Sensitive-column spec map for an entity, or {} when the entity has none. */")
    lines_out.append("export function sensitiveColumnsFor(entity: string): Record<string, SensitiveColumnSpec> {")
    lines_out.append("  if (!entity) return {};")
    lines_out.append("  return SENSITIVE_COLUMNS[entity]")
    lines_out.append("    || SENSITIVE_COLUMNS[String(entity).toLowerCase()]")
    lines_out.append("    || {};")
    lines_out.append("}")
    lines_out.append("")

    (lib_dir / "sensitive-columns.ts").write_text("\n".join(lines_out), encoding="utf-8")
    return "src/lib/sensitive-columns.ts"


def _emit_searchable_columns_manifest(root: Path, models: list[dict], reg_entities: dict) -> str:
    """Write ``src/lib/searchable-columns.ts`` — the manifest ``resolveSearch``
    reads to know which ``_search`` tsvector columns each entity carries.

    Manifest shape (TS)::

        export const SEARCHABLE_COLUMNS: Record<string, string[]> = {
          "documents":   ["content", "title"],
          "extractions": ["field_name"],
          ...
        };

    Keys are ORIGINAL plaintext column names (what a caller specifies as
    ``columns: ["content"]`` on an op:"search" source); the resolver appends
    ``_search`` when building the SQL. Every reachable form of the entity
    name (name, table, slug, cased + lowercase) is registered so a lookup
    from any layer resolves.

    Empty object emitted when the app has no search columns, so the
    runtime's static import always resolves.
    """
    lib_dir = root / "src" / "lib"
    lib_dir.mkdir(parents=True, exist_ok=True)

    per_entity: dict[str, list[str]] = {}
    for m in models:
        name = m.get("name")
        if not isinstance(name, str):
            continue
        cols: list[str] = []
        for f in m.get("fields", []):
            if not _is_search_field(f):
                continue
            fname = f.get("name") or ""
            if not isinstance(fname, str) or not fname:
                continue
            # Manifest stores the ORIGINAL plaintext column name (not the
            # derived `_search` name). A pre-declared `_search` name is
            # normalised back to its base so callers reference a stable key.
            base = fname[: -len("_search")] if fname.endswith("_search") else fname
            if base and base not in cols:
                cols.append(base)
        if not cols:
            continue

        rec = reg_entities.get(name) if isinstance(reg_entities, dict) else None
        forms: set[str] = {name, name.lower()}
        if isinstance(rec, dict):
            for k in ("table", "slug", "id"):
                v = rec.get(k)
                if isinstance(v, str) and v:
                    forms.add(v)
                    forms.add(v.lower())
        for form in forms:
            per_entity[form] = list(cols)

    lines_out = [
        "// AUTO-GENERATED by services/schema_builder.py — do not hand-edit.",
        "//",
        "// SEARCH-1 searchable-columns manifest. Any column declared with",
        "// `search: true` in the plan emits a companion `<name>_search`",
        "// tsvector column (GENERATED ALWAYS AS to_tsvector('english', ...))",
        "// + a GIN index. The Data Engine's op:\"search\" reads this manifest",
        "// to know WHICH `_search` columns to query per entity.",
        "//",
        "// Values are ORIGINAL plaintext column names — the resolver appends",
        "// `_search` when building the SQL. The manifest is keyed by every",
        "// reachable name a caller might use (entity name / table / slug,",
        "// both cased and lowercase) so a lookup never misses.",
        "",
        "export const SEARCHABLE_COLUMNS: Record<string, string[]> = {",
    ]
    for ent in sorted(per_entity):
        cols = per_entity[ent]
        cols_ts = ", ".join(f'"{c}"' for c in cols)
        lines_out.append(f'  "{ent}": [{cols_ts}],')
    lines_out.append("};")
    lines_out.append("")
    lines_out.append("/** True when the entity has ANY searchable column declared. */")
    lines_out.append("export function hasSearchableColumns(entity: string): boolean {")
    lines_out.append("  if (!entity) return false;")
    lines_out.append("  return !!(SEARCHABLE_COLUMNS[entity]")
    lines_out.append("    || SEARCHABLE_COLUMNS[String(entity).toLowerCase()]);")
    lines_out.append("}")
    lines_out.append("")
    lines_out.append("/** Searchable columns for an entity, or [] when none. */")
    lines_out.append("export function searchableColumnsFor(entity: string): string[] {")
    lines_out.append("  if (!entity) return [];")
    lines_out.append("  return SEARCHABLE_COLUMNS[entity]")
    lines_out.append("    || SEARCHABLE_COLUMNS[String(entity).toLowerCase()]")
    lines_out.append("    || [];")
    lines_out.append("}")
    lines_out.append("")

    (lib_dir / "searchable-columns.ts").write_text("\n".join(lines_out), encoding="utf-8")
    return "src/lib/searchable-columns.ts"


# ─── merged users (auth base + planner domain columns) ───

def _emit_merged_users(schema_dir, reserved_models, reg_entities, id_to_name,
                       registry, generated):
    """Emit `src/db/schema/user.ts` merging the planner's domain `User` columns
    (e.g. a `role`) OVER the auth foundation's canonical `users` columns, as a
    single `pgTable("users")`. No-op when the reserved User entity adds no domain
    column beyond the auth base — the template's user.ts is left untouched."""
    if not reserved_models:
        return

    user_name = None
    domain_fields: list[dict] = []
    seen: set[str] = set(_AUTH_USERS_BASE_NAMES)
    for m in reserved_models:
        if _reg_table(reg_entities, m["name"]) != "users":
            continue
        user_name = user_name or m["name"]
        for f in m.get("fields", []):
            if not isinstance(f, dict):
                continue
            fname = f.get("name") or ""
            low = _norm_col(fname)
            if not fname or low in seen:
                continue
            if f.get("primaryKey") or f.get("primary_key"):
                continue
            seen.add(low)
            domain_fields.append(f)

    if not domain_fields:
        return  # only auth/base columns — keep the template's user.ts

    # Resolve any FK on a User domain column from the registry (id → entity name).
    rec = reg_entities.get(user_name) or {}
    fk_by_col: dict[str, str] = {}
    for col in rec.get("columns", []) if isinstance(rec, dict) else []:
        if isinstance(col, dict) and col.get("fk"):
            tgt = id_to_name.get(col.get("fk"))
            if tgt:
                fk_by_col[col.get("name")] = tgt

    used_builders: set[str] = set(_AUTH_USERS_BASE_BUILDERS)
    ref_entities: set[str] = set()
    domain_lines: list[str] = []
    for field in domain_fields:
        fname = field["name"]
        builder, args = _builder_for(field)
        used_builders.add(builder)
        chain = f"{builder}({args})"
        ref_entity = fk_by_col.get(fname)
        if ref_entity and ref_entity != user_name:
            chain += f".references(() => {_reg_table(reg_entities, ref_entity)}.id)"
            ref_entities.add(ref_entity)
        dflt = _render_default(field.get("default"))
        if dflt:
            chain += dflt
        nullable = field.get("nullable")
        if nullable is False or field.get("notNull") or field.get("required"):
            chain += ".notNull()"
        if field.get("unique"):
            chain += ".unique()"
        domain_lines.append(f"  {fname}: {chain},")

    builder_order = [
        "pgTable", "serial", "uuid", "varchar", "char", "text", "integer",
        "bigint", "boolean", "timestamp", "jsonb", "decimal", "real",
        "doublePrecision",
    ]
    imports = ["pgTable"] + [b for b in builder_order
                             if b != "pgTable" and b in used_builders]
    lines = [
        "// Users table — auth foundation base columns MERGED with the app's "
        "domain\n// User columns (role, profile fields). Auth owns id/email/"
        "password; the\n// deterministic schema builder appends the planner's "
        "columns. Single table.",
        f'import {{ {", ".join(imports)} }} from "drizzle-orm/pg-core";',
    ]
    for ref in sorted(ref_entities):
        lines.append(
            f'import {{ {_reg_table(reg_entities, ref)} }} '
            f'from "./{_reg_import_slug(reg_entities, ref)}";')
    lines.append("")
    lines.append('export const users = pgTable("users", {')
    lines.extend(_AUTH_USERS_BASE_LINES)
    lines.extend(domain_lines)
    lines.append("});")
    lines.append("")
    (schema_dir / "user.ts").write_text("\n".join(lines), encoding="utf-8")
    generated.append("src/db/schema/user.ts")


# ─── per-entity emit ───

_TS_TIMESTAMPS = {"createdAt", "updatedAt", "created_at", "updated_at"}


# ─── money: field.type == "money" → decimal(19,4) amount + sibling ISO-4217 currency ───
#
# Any column typed `money` gets TWO real Postgres columns:
#   * the amount:   decimal(19,4).notNull()  (handled by `_builder_for`)
#   * the currency: char(3).notNull().default('USD')  (emitted here)
#
# The sibling name is derived from the amount name:
#   `amount`        → `amount_currency`
#   `price_amount`  → `price_currency`     (trailing `_amount` swapped)
#   `totalAmount`   → `totalCurrency`      (trailing `Amount` swapped, camelCase preserved)
#   `fee`           → `fee_currency`       (no trailing `Amount`/`_amount` → append)
# Idempotent: if the plan already declares the derived sibling name on the same
# entity, the builder does not emit a second one.


def _is_money_type(field: dict) -> bool:
    t = str((field or {}).get("type", "")).lower().strip()
    return t in ("money", "currency")


def _derive_currency_sibling_name(amount_name: str) -> str:
    """`price_amount` → `price_currency`; `totalAmount` → `totalCurrency`; `fee` → `fee_currency`.

    Case + separator convention is preserved: a camelCase source keeps camelCase,
    a snake_case source keeps snake_case. Only the trailing `Amount`/`_amount`
    token is swapped; everything else gets `_currency` appended.
    """
    if not amount_name:
        return "currency"
    if amount_name.endswith("_amount") and len(amount_name) > len("_amount"):
        return amount_name[: -len("_amount")] + "_currency"
    if amount_name.endswith("Amount") and len(amount_name) > len("Amount"):
        return amount_name[: -len("Amount")] + "Currency"
    return amount_name + "_currency"


def _default_currency_literal(field: dict) -> str:
    """The ISO-4217 code the currency sibling defaults to. `defaultCurrency` on
    the field wins (per-column override); otherwise `USD`."""
    dc = (field or {}).get("defaultCurrency") or (field or {}).get("default_currency")
    if isinstance(dc, str) and len(dc.strip()) == 3 and dc.strip().isalpha():
        return dc.strip().upper()
    return "USD"


# ─── IRF-M3-T6: denormalization from plan.app_shape.data.denormalization ───
#
# `none` (default)   → no denorm sibling columns emitted (current behavior).
# `moderate`         → denorm only for FKs targeting `User` — the highest-value
#                       display denorm ("who owns this", "assigned to", …),
#                       kept narrow so we don't bloat every table.
# `aggressive`       → denorm sibling for EVERY FK with a name-shaped target.
# The sibling is a nullable varchar(255); population is the runtime layer's job
# (a trigger or an insert wrapper — out of scope for the schema builder).
_DENORM_MODERATE_TARGETS = {"User"}


def _denorm_mode_from_plan(plan: Any) -> str:
    if not isinstance(plan, dict):
        return "none"
    shape = plan.get("app_shape")
    if not isinstance(shape, dict):
        return "none"
    data = shape.get("data")
    if not isinstance(data, dict):
        return "none"
    v = data.get("denormalization")
    if v in ("none", "moderate", "aggressive"):
        return v
    return "none"


def _denorm_column_name(fk_field: str) -> str:
    """`assigneeId` → `assigneeName`; `owner` → `ownerName`; `user_id` → `user_name`."""
    if fk_field.endswith("Id") and len(fk_field) > 2:
        return fk_field[:-2] + "Name"
    if fk_field.endswith("_id") and len(fk_field) > 3:
        return fk_field[:-3] + "_name"
    return fk_field + "Name"


def _should_emit_denorm(mode: str, target_entity: str) -> bool:
    if mode == "aggressive":
        return True
    if mode == "moderate":
        return target_entity in _DENORM_MODERATE_TARGETS
    return False


# ─── sensitive: field.sensitive == True → `<name>_encrypted` + `<name>_mask` siblings ───
#
# Slice-4 encrypt-at-rest contract. Any string-typed column flagged
# ``sensitive: true`` is rewritten at schema-build time:
#
#   * the original plaintext column is RENAMED to ``<name>_encrypted``
#     (still ``text``; holds a base64 AES-GCM blob at runtime);
#   * a sibling ``<name>_mask`` (text, nullable) is appended, holding the
#     pre-computed masked value so read paths never need the encryption
#     key to display a row.
#
# Idempotent — if the plan already declares the derived ``_encrypted`` or
# ``_mask`` name (unlikely, but a hand-written plan could), that column is
# used as-is and the builder does not double-emit.
#
# The mask column is ALWAYS nullable regardless of the parent's NOT NULL
# state: a freshly-created row without a set sensitive value has no mask,
# and forcing NOT NULL would break the insert. The encrypted column
# inherits the parent's nullability.


def _is_sensitive_field(field: dict) -> bool:
    return isinstance(field, dict) and bool(field.get("sensitive"))


def _sensitive_encrypted_name(name: str) -> str:
    """Derive the encrypted-column name. Idempotent: `foo` → `foo_encrypted`;
    `foo_encrypted` → `foo_encrypted`."""
    if not name:
        return "_encrypted"
    return name if name.endswith("_encrypted") else f"{name}_encrypted"


def _sensitive_mask_name(name: str) -> str:
    """Derive the mask-column name from the *original* column name.
    `accountNumber` → `accountNumber_mask`; `accountNumber_encrypted` →
    `accountNumber_mask` (strip the `_encrypted` suffix first so a plan
    that pre-declared the encrypted name still gets the right mask name)."""
    if not name:
        return "_mask"
    base = name[: -len("_encrypted")] if name.endswith("_encrypted") else name
    return f"{base}_mask"


# ─── search: field.search == True → `<name>_search` tsvector GENERATED + GIN index ───
#
# SEARCH-1 opt-in full-text search contract. Any string-typed column flagged
# ``search: true`` gets a companion column emitted immediately after it:
#
#   * ``<name>_search`` — Postgres ``tsvector``, ``GENERATED ALWAYS AS
#     (to_tsvector('english', coalesce(<name>, ''))) STORED``. Modelled in
#     Drizzle as a customType('tsvector') carrying the SQL expression via
#     ``generatedAlwaysAs`` — Drizzle has no first-class tsvector type, so
#     the customType approach is the least-magic escape hatch.
#   * A GIN index on the ``_search`` column, declared in the pgTable index
#     block (third-arg callback) so drizzle-kit emits the CREATE INDEX.
#
# Idempotent — a column already ending with ``_search`` is left alone; a plan
# that pre-declares the derived name is not double-emitted.
#
# Multi-column-per-entity: two ``search: true`` columns on the same entity
# emit two independent ``_search`` columns + two GIN indexes. A single
# combined index across columns is a follow-up optimisation.
#
# The Data Engine's ``resolveSearch`` (op:"search") reads the manifest at
# src/lib/searchable-columns.ts to know WHICH ``_search`` columns to query
# per entity.


def _is_search_field(field: dict) -> bool:
    return isinstance(field, dict) and bool(field.get("search"))


def _search_column_name(name: str) -> str:
    """Derive the tsvector-column name. Idempotent: `content` → `content_search`;
    `content_search` → `content_search`."""
    if not name:
        return "_search"
    return name if name.endswith("_search") else f"{name}_search"


def _is_append_only(model: dict) -> bool:
    """Slice-3 ledger contract: an entity flagged ``lifecycle == "append_only"``
    is a LEDGER — rows are only INSERTed, never UPDATEd/DELETEd. The schema
    reflects that by omitting the auto-appended ``updatedAt``/``deletedAt``
    columns (a soft-delete column would lie about the ledger's immutability).

    Idempotent w.r.t. planner intent: if the planner explicitly declares an
    ``updatedAt`` on an append-only entity, we still emit it (the plan is
    authoritative for the column set — plan-validator warns separately if the
    combination looks wrong). We ONLY skip the AUTO-APPEND of the pair.
    """
    return isinstance(model, dict) and str(model.get("lifecycle", "")).strip() == "append_only"


def _emit_entity(schema_dir, types_dir, name, model, fk_map, one_rels, coll_rels, generated, reg_entities, denorm_mode: str = "none"):
    table = _reg_table(reg_entities, name)
    slug = _reg_slug(reg_entities, name)
    fields = list(model.get("fields", []))
    append_only = _is_append_only(model)

    # Slice-4 sensitive rewrite: rename `sensitive` fields to `<name>_encrypted`
    # in-place BEFORE `declared` is computed, so downstream checks (FK map,
    # denorm sibling, idempotency) see the final column name. The `_mask`
    # sibling is emitted by the loop below (right after the encrypted column,
    # so the schema reads naturally). Column TYPE is forced to `text` — the
    # validator only lets sensitive land on string-shaped columns, but a
    # `varchar` with a length shorter than the base64 blob would truncate.
    for _f in fields:
        if _is_sensitive_field(_f):
            _orig = _f.get("name", "")
            _f["_sensitiveOriginalName"] = _orig  # remembered for the manifest emitter
            _f["name"] = _sensitive_encrypted_name(_orig)
            _f["type"] = "text"

    declared = {f.get("name") for f in fields}
    used_builders: set[str] = set()
    col_lines: list[str] = []
    # SEARCH-1 side-channel: every ``search: true`` column emits a companion
    # ``_search`` tsvector column here + a GIN index in the pgTable index block
    # below. Track (search_col_name, drizzle_col_prop) pairs so the index-block
    # renderer downstream can reference them by property name.
    search_col_props: list[str] = []
    needs_tsvector_type = False
    needs_sql_import = False

    for field in fields:
        fname = field.get("name", "")
        if not fname:
            continue
        builder, args = _builder_for(field)
        used_builders.add(builder)
        chain = f"{builder}({args})"

        if field.get("primaryKey") or field.get("primary_key"):
            chain += ".primaryKey()"
            if builder == "uuid":
                chain += ".defaultRandom()"
        else:
            # FK reference (inline)
            ref_entity = fk_map.get(fname)
            if ref_entity:
                chain += f".references(() => {_reg_table(reg_entities, ref_entity)}.id)"
            dflt = _render_default(field.get("default"))
            if dflt:
                chain += dflt
            # Required domain fields -> NOT NULL. The planner marks these with
            # `nullable: false` (its convention, see agents/planner.py prompt +
            # real plans e.g. output/7uwywvau/plan.json); `notNull`/`required`
            # are honored as aliases. Only explicit flags are trusted — optional
            # fields (no flag) stay nullable, and this never touches the PK
            # (handled above) or auto-appended lifecycle timestamps. This NOT
            # NULL is what lets the registry report `nullable:false` downstream,
            # which drives the required `*` markers on generated forms.
            nullable = field.get("nullable")
            not_null = field.get("notNull") or field.get("required")
            if nullable is False or not_null:
                chain += ".notNull()"
            if field.get("unique"):
                chain += ".unique()"

        col_lines.append(f"  {fname}: {chain},")

        # Slice-4 sensitive mask sibling: for every sensitive column the loop
        # writes the encrypted column above, then this appends a `<orig>_mask`
        # text column (always nullable — a freshly-inserted row without a set
        # value has no mask). Idempotent — a plan that already declared the
        # derived mask name is left alone. Emitted here (per-column) rather
        # than after the loop so the mask always sits immediately below its
        # encrypted parent in the file.
        if _is_sensitive_field(field):
            orig = field.get("_sensitiveOriginalName") or (
                fname[: -len("_encrypted")] if fname.endswith("_encrypted") else fname
            )
            mask_name = _sensitive_mask_name(orig)
            if mask_name not in declared:
                used_builders.add("text")
                col_lines.append(
                    f'  {mask_name}: text("{_to_snake(mask_name)}"),'
                )
                declared.add(mask_name)

        # SEARCH-1 tsvector sibling: for every `search: true` column, emit an
        # `<orig>_search` tsvector column immediately below. Modelled with
        # Drizzle's `customType<{data:string}>({dataType:()=>"tsvector"})` so
        # drizzle-kit renders `tsvector` in Postgres (Drizzle has no first-class
        # tsvector). GENERATED ALWAYS AS to_tsvector('english', coalesce(<orig>,''))
        # STORED — populated by Postgres, never by the app. Idempotent: skip if
        # the plan already declared the derived name.
        if _is_search_field(field):
            orig = fname[: -len("_search")] if fname.endswith("_search") else fname
            search_name = _search_column_name(orig)
            if search_name not in declared:
                needs_tsvector_type = True
                needs_sql_import = True
                snake_orig = _to_snake(orig)
                snake_search = _to_snake(search_name)
                col_lines.append(
                    f'  {search_name}: tsvector("{snake_search}")'
                    f'.generatedAlwaysAs(sql`to_tsvector(\'english\', '
                    f"coalesce({snake_orig}, ''))`),"
                )
                declared.add(search_name)
                search_col_props.append(search_name)

        # Money sibling: every `money`-typed column auto-emits a `<field>_currency`
        # char(3).notNull().default('USD') sibling, unless the plan already declared
        # one with the derived name (idempotent). This is the DB half of the money
        # contract — Seam 3 (library MoneyInput/MoneyDisplay) is the UI half.
        if _is_money_type(field):
            sib_name = _derive_currency_sibling_name(fname)
            if sib_name not in declared:
                used_builders.add("char")
                default = _default_currency_literal(field)
                col_lines.append(
                    f'  {sib_name}: char("{_to_snake(sib_name)}", {{ length: 3 }})'
                    f'.notNull().default("{default}"),'
                )
                declared.add(sib_name)

        # IRF-M3-T6: denorm sibling column when shape.data.denormalization asks
        # for it. Emitted right after the FK column so the schema reads naturally
        # (assigneeId → assigneeName). Nullable varchar(255); population belongs
        # to the runtime layer.
        ref_entity = fk_map.get(fname)
        if ref_entity and _should_emit_denorm(denorm_mode, ref_entity):
            denorm_name = _denorm_column_name(fname)
            if denorm_name not in declared:
                used_builders.add("varchar")
                col_lines.append(
                    f'  {denorm_name}: varchar("{_to_snake(denorm_name)}", {{ length: 255 }}),'
                )
                declared.add(denorm_name)

    # Append standard timestamps if the entity declared neither.
    #
    # Slice-3 ledger contract: an ``append_only`` entity is a LEDGER —
    # rows never UPDATE, so an ``updatedAt`` column would be a lie the DB
    # would silently maintain. We still emit ``createdAt`` (every row
    # needs an insertion timestamp for the ledger order), but not
    # ``updatedAt``. ``deletedAt`` (soft-delete) is never auto-appended
    # anywhere in this builder, so nothing extra is needed for it —
    # noted here for the future reader.
    if not (declared & _TS_TIMESTAMPS):
        used_builders.add("timestamp")
        col_lines.append('  createdAt: timestamp("created_at").defaultNow().notNull(),')
        if not append_only:
            col_lines.append('  updatedAt: timestamp("updated_at").defaultNow().notNull(),')

    # Referenced tables to import (from FK refs + relation blocks).
    ref_entities: set[str] = set(fk_map.values())
    for _relname, ref_entity, _fk in one_rels:
        ref_entities.add(ref_entity)
    for _relname, owner_entity, _one in coll_rels:
        ref_entities.add(owner_entity)
    ref_entities.discard(name)

    # Slice-4 header: name the sensitive columns at the top of the file so a
    # reader isn't left guessing why `accountNumber_encrypted` + `_mask` exist.
    sensitive_orig_names = [
        f.get("_sensitiveOriginalName") for f in fields
        if _is_sensitive_field(f) and f.get("_sensitiveOriginalName")
    ]

    # Build imports.
    lines: list[str] = []
    if sensitive_orig_names:
        lines.append(
            "// SENSITIVE COLUMNS: "
            + ", ".join(sensitive_orig_names)
            + " — stored AES-GCM-encrypted in <name>_encrypted, with a"
        )
        lines.append(
            "// pre-computed masked value in <name>_mask for the default read"
            " path (see src/lib/sensitive-columns.ts + src/lib/sensitive-crypto.ts)."
        )
    if append_only:
        # Ledger contract — surface it at the top of the file so a future
        # reader (or code review) doesn't wonder why updated_at is missing.
        lines.append(
            "// APPEND-ONLY LEDGER: rows are INSERTed only — never UPDATEd or"
            " DELETEd."
        )
        lines.append(
            "// The Data Engine rejects PUT/DELETE for entities in"
            " src/lib/append-only-entities.ts."
        )
    builder_order = [
        "pgTable", "serial", "uuid", "varchar", "char", "text", "integer",
        "bigint", "boolean", "timestamp", "jsonb", "decimal", "real",
        "doublePrecision",
    ]
    imports = ["pgTable"] + [b for b in builder_order if b != "pgTable" and b in used_builders]
    # SEARCH-1: every entity with a `_search` column needs the `index` helper
    # for its GIN index; add it here so a single-import line covers everything.
    if search_col_props:
        imports.append("index")
        # Local `customType` for the tsvector escape hatch — Drizzle has no
        # first-class tsvector, so we hand-roll it once per file that needs it.
        imports.append("customType")
    lines.append(f'import {{ {", ".join(imports)} }} from "drizzle-orm/pg-core";')

    # SEARCH-1: sql template literal for the GENERATED expression.
    if needs_sql_import:
        lines.append('import { sql } from "drizzle-orm";')

    has_rel = bool(one_rels or coll_rels)
    if has_rel:
        lines.append('import { relations } from "drizzle-orm";')
    for ref in sorted(ref_entities):
        lines.append(f'import {{ {_reg_table(reg_entities, ref)} }} from "./{_reg_import_slug(reg_entities, ref)}";')
    lines.append("")

    # SEARCH-1: local customType declaration for tsvector. Drizzle-kit renders
    # `tsvector` in the CREATE TABLE; runtime reads it as string (never touched
    # by the app — Postgres populates it via the GENERATED expression).
    if needs_tsvector_type:
        lines.append(
            'const tsvector = customType<{ data: string }>({ dataType: () => "tsvector" });'
        )
        lines.append("")

    # Table. When SEARCH-1 has any GIN indexes to declare, use the pgTable
    # 3-arg form so drizzle-kit emits CREATE INDEX ... USING gin.
    if search_col_props:
        lines.append(f'export const {table} = pgTable("{table}", {{')
        lines.extend(col_lines)
        lines.append("}, (t) => ({")
        for prop in search_col_props:
            # Postgres identifier length cap is 63 chars; keep the idx name
            # short + deterministic. `<table>_<prop>_idx` — the prop is already
            # camel/lower matching the drizzle column name.
            idx_name = f"{table}_{prop}_idx"
            lines.append(f'  {prop}Idx: index("{idx_name}").using("gin", t.{prop}),')
        lines.append("}));")
    else:
        lines.append(f'export const {table} = pgTable("{table}", {{')
        lines.extend(col_lines)
        lines.append("});")

    # Relations block.
    if has_rel:
        lines.append("")
        arg = "({ one, many })" if (one_rels and coll_rels) else (
            "({ one })" if one_rels else "({ many })")
        # one-only referenced side that is a one-to-one still uses one
        if not one_rels and any(is_one for _n, _o, is_one in coll_rels):
            arg = "({ one })"
        lines.append(f"export const {table}Relations = relations({table}, {arg} => ({{")
        for rel_name, ref_entity, fk_field in one_rels:
            ref_table = _reg_table(reg_entities, ref_entity)
            lines.append(
                f"  {rel_name}: one({ref_table}, {{ "
                f"fields: [{table}.{fk_field}], references: [{ref_table}.id] }}),"
            )
        for rel_name, owner_entity, is_one in coll_rels:
            owner_table = _reg_table(reg_entities, owner_entity)
            kind = "one" if is_one else "many"
            lines.append(f"  {rel_name}: {kind}({owner_table}),")
        lines.append("}));")

    lines.append("")
    (schema_dir / f"{slug}.ts").write_text("\n".join(lines), encoding="utf-8")
    generated.append(f"src/db/schema/{slug}.ts")

    # Types file.
    tlines = [
        f'import {{ {table} }} from "@/db/schema/{slug}";',
        "",
        f"export type {name} = typeof {table}.$inferSelect;",
        f"export type New{name} = typeof {table}.$inferInsert;",
        "",
    ]
    (types_dir / f"{slug}.ts").write_text("\n".join(tlines), encoding="utf-8")
    generated.append(f"src/types/{slug}.ts")


def _emit_schema_barrel(schema_dir, models, reg_entities):
    lines = [f'export * from "./{_reg_slug(reg_entities, m["name"])}";' for m in models]
    (schema_dir / "index.ts").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _emit_types_barrel(types_dir, models, reg_entities):
    lines = [f'export * from "./{_reg_slug(reg_entities, m["name"])}";' for m in models]
    (types_dir / "index.ts").write_text("\n".join(lines) + "\n", encoding="utf-8")
