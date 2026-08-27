"""Deterministic vitest regression-suite emitter — tests INSIDE the generated app.

Why: a generated app ships with zero tests, so the moment it leaves the
pipeline it has no regression net — any later hand-edit (or platform regen
gap) silently breaks CRUD, workflows, or page bindings. This emitter derives
a small vitest suite from the app's own canonical resource registry
(``contracts/resource-registry.json``) and writes it into
``src/__tests__/generated/`` so the app can verify itself after handoff.

Strategy decision (in-process vs live-HTTP):
    The CRUD round-trip tests import the vendored data engine IN-PROCESS
    (``@/lib/data-engine`` + ``@/lib/data-init``) rather than fetching
    ``/api/data/<slug>`` over HTTP. Rationale: the engine module tree needs
    only ``DATABASE_URL`` (``src/db/index.ts`` reads it at import), whereas
    the HTTP route needs a running ``next dev`` server AND auth middleware
    cooperation. In-process also exercises the exact code path the catch-all
    route and the SSR bridge share (``create/findById/update/remove``), so a
    green run means the app's single CRUD path works. Because
    ``src/db/index.ts`` connects at module-import time, the engine is
    imported DYNAMICALLY inside ``beforeAll`` and the whole describe block is
    ``describe.skipIf(!DATABASE_URL)`` — the suite is runnable with no
    database at all (structural tests still execute).

    Value-synthesis deviation from the naive spec: drizzle ``timestamp()``
    columns default to mode "date" (they require a ``Date`` object; an ISO
    string throws ``value.toISOString is not a function`` inside drizzle), so
    timestamp columns synthesize ``new Date()``; pg ``date`` columns take a
    ``YYYY-MM-DD`` string.

Emitted files (all overwritten every run — they carry an AUTO-GENERATED
header; stale generated files bearing the header are pruned):
    src/__tests__/generated/crud.<slug>.test.ts   one per eligible entity
    src/__tests__/generated/workflows.test.ts     structural checks, always run
    src/__tests__/generated/registry-consistency.test.ts
    src/__tests__/generated/manifest.json         counts + skip reasons
Plus (only if absent — never clobbered): vitest.config.ts, and a
``test`` script / ``vitest`` devDependency injected into package.json.

Never raises: every failure degrades to a reason in the returned dict.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

HEADER = "// AUTO-GENERATED — regenerated every build. Do not edit by hand."
GENERATED_DIR = os.path.join("src", "__tests__", "generated")
# Columns the data engine strips / the DB manages — never synthesized.
SYSTEM_COLUMNS = {"id", "createdAt", "updatedAt", "deletedAt",
                  "created_at", "updated_at", "deleted_at"}
# Auth owns the physical users table (password hash + auth middleware invariants
# aren't in the registry), so its CRUD round-trip is skipped.
RESERVED_TABLES = {"users"}
VITEST_VERSION = "^2.1.9"


# ── canonical key helpers (mirror the app's entity-alias tolerance) ──────────

def _canon(s: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _plural_flip(key: str) -> str:
    if key.endswith("ies"):
        return key[:-3] + "y"
    if key.endswith("s"):
        return key[:-1]
    return key + "s"


def _key_variants(form: Any) -> set[str]:
    """Canonical key + its plurality flip — matches registerEntity's indexing."""
    key = _canon(form)
    if not key:
        return set()
    out = {key, _plural_flip(key)}
    if re.search(r"[^aeiou]y$", key):
        out.add(key[:-1] + "ies")
    return out


# ── registry loading (canonical first, contract-registry fallback) ───────────

def _entity_from_canonical(name: str, rec: dict) -> dict:
    columns = []
    for col in rec.get("columns") or []:
        if not isinstance(col, dict) or not col.get("name"):
            continue
        columns.append({
            "name": col["name"],
            "type": str(col.get("type") or "varchar"),
            "notNull": bool(col.get("notNull")),
            "enum": col.get("enum") if isinstance(col.get("enum"), list) else None,
            "fk": col.get("fk") or None,
        })
    slug = rec.get("slug") or _canon(name)
    return {
        "name": rec.get("name") or name,
        "id": rec.get("id") or slug,
        "slug": slug,
        "table": rec.get("table") or slug,
        "camel": rec.get("camel") or name[:1].lower() + name[1:],
        "columns": columns,
    }


def _entity_from_contract(name: str, rec: dict) -> dict:
    """Fallback shape: registry.json entities {Name: {fields: {f: FieldInfo}}}."""
    columns = []
    for fname, finfo in (rec.get("fields") or {}).items():
        finfo = finfo if isinstance(finfo, dict) else {}
        enum_vals = finfo.get("enum_values")
        columns.append({
            "name": fname,
            "type": str(finfo.get("type") or "varchar"),
            "notNull": finfo.get("nullable") is False,
            "enum": enum_vals if isinstance(enum_vals, list) and enum_vals else None,
            "fk": None,
        })
    kebab = re.sub(r"(?<!^)(?=[A-Z])", "-", name).lower()
    return {
        "name": name,
        "id": kebab,
        "slug": kebab + "s" if not kebab.endswith("s") else kebab,
        "table": kebab.replace("-", "_") + ("s" if not kebab.endswith("s") else ""),
        "camel": name[:1].lower() + name[1:],
        "columns": columns,
    }


def _load_entities(out: Path) -> tuple[list[dict], str | None]:
    """Return (entities, source) — source None when no registry exists."""
    canonical = out / "contracts" / "resource-registry.json"
    if canonical.is_file():
        try:
            reg = json.loads(canonical.read_text(encoding="utf-8"))
            ents = reg.get("entities") or {}
            if isinstance(ents, dict) and ents:
                return ([_entity_from_canonical(n, r) for n, r in sorted(ents.items())
                         if isinstance(r, dict)], "resource-registry")
        except (OSError, ValueError) as e:
            logger.warning("test_suite_emitter: bad resource-registry.json: %s", e)
    contract = out / "registry.json"
    if contract.is_file():
        try:
            reg = json.loads(contract.read_text(encoding="utf-8"))
            ents = reg.get("entities") or {}
            fallback = [_entity_from_contract(n, r) for n, r in sorted(ents.items())
                        if isinstance(r, dict)]
            # contract registry has no per-column FK info — wire it from relations
            by_name = {e["name"]: e for e in fallback}
            for rel in reg.get("relations") or []:
                if not isinstance(rel, dict):
                    continue
                src = by_name.get(rel.get("from_entity"))
                tgt = by_name.get(rel.get("to_entity"))
                fk = rel.get("foreignKey")
                if src and tgt and fk:
                    for col in src["columns"]:
                        if col["name"] == fk:
                            col["fk"] = tgt["id"]
            if fallback:
                return fallback, "registry.json"
        except (OSError, ValueError) as e:
            logger.warning("test_suite_emitter: bad registry.json: %s", e)
    return [], None


# ── value synthesis (TS expressions) ─────────────────────────────────────────

def _ts_string(s: str) -> str:
    return json.dumps(str(s))


def _value_expr(col: dict) -> str:
    """A minimally-valid TS expression for a column, from its registry type."""
    t = col["type"].lower()
    if col.get("enum"):
        return _ts_string(col["enum"][0])
    if "uuid" in t:
        return "crypto.randomUUID()"
    if t in {"boolean", "bool"}:
        return "false"
    if any(k in t for k in ("int", "serial", "decimal", "numeric", "real",
                            "double", "float", "number", "money")):
        return "1"
    if "timestamp" in t or "datetime" in t:
        return "new Date()"  # drizzle timestamp mode "date" needs a Date object
    if t == "date":
        return "new Date().toISOString().slice(0, 10)"
    if "json" in t:
        return "{}"
    return _ts_string(f"test {col['name']}")


def _update_expr(col: dict) -> str:
    """A second, different value for the round-trip update step."""
    t = col["type"].lower()
    if col.get("enum"):
        vals = col["enum"]
        return _ts_string(vals[1] if len(vals) > 1 else vals[0])
    if t in {"boolean", "bool"}:
        return "true"
    if any(k in t for k in ("int", "serial", "decimal", "numeric", "real",
                            "double", "float", "number", "money")):
        return "2"
    if "timestamp" in t or "datetime" in t:
        return "new Date()"
    if t == "date":
        return "new Date().toISOString().slice(0, 10)"
    if "json" in t:
        return '{ "updated": true }'
    return _ts_string(f"updated {col['name']}")


def _mutable_column(ent: dict) -> dict | None:
    """Pick the column the update step mutates — prefer plain text, then enum,
    then numeric/boolean. FKs, uuids and system columns are never mutated."""
    candidates = [c for c in ent["columns"]
                  if c["name"] not in SYSTEM_COLUMNS and not c.get("fk")
                  and "uuid" not in c["type"].lower()]

    def rank(c: dict) -> int:
        t = c["type"].lower()
        if c.get("enum"):
            return 1
        if any(k in t for k in ("varchar", "text", "char", "string")):
            return 0
        if any(k in t for k in ("int", "decimal", "numeric", "real", "double",
                                "float", "number")):
            return 2
        if t in {"boolean", "bool"}:
            return 3
        return 9

    candidates = [c for c in candidates if rank(c) < 9]
    if not candidates:
        return None
    return sorted(candidates, key=lambda c: (rank(c), ent["columns"].index(c)))[0]


# ── FK dependency resolution (mirrors seed_synthesizer's topo pass) ──────────

def _parent_chain(ent: dict, by_id: dict[str, dict]) -> tuple[list[dict], str | None]:
    """Transitive NOT-NULL FK parents in create order (targets first).

    Returns ``(chain, None)`` on success or ``([], reason)`` when the entity's
    CRUD test is unsatisfiable (cycle, missing target, auth-reserved parent).
    Nullable FKs are simply omitted from the insert, so they add no parents.
    """
    chain: list[dict] = []
    seen: set[str] = set()
    stack: set[str] = set()

    def visit(e: dict) -> str | None:
        eid = e["id"]
        if eid in stack:
            return f"FK cycle through '{eid}'"
        if eid in seen:
            return None
        stack.add(eid)
        for col in e["columns"]:
            if not col.get("fk") or not col["notNull"]:
                continue
            target = by_id.get(col["fk"])
            if target is None:
                stack.discard(eid)
                return f"NOT NULL FK '{col['name']}' targets unknown entity '{col['fk']}'"
            if target["table"] in RESERVED_TABLES:
                stack.discard(eid)
                return (f"NOT NULL FK '{col['name']}' targets auth-reserved "
                        f"table '{target['table']}'")
            err = visit(target)
            if err:
                stack.discard(eid)
                return err
        stack.discard(eid)
        seen.add(eid)
        if eid != ent["id"]:
            chain.append(e)
        return None

    err = visit(ent)
    return ([], err) if err else (chain, None)


# ── TS source builders ───────────────────────────────────────────────────────

def _insert_literal(ent: dict, var_of: dict[str, str], indent: str) -> str:
    """Object-literal of NOT-NULL insertable values (FKs point at parent vars)."""
    lines: list[str] = []
    for col in ent["columns"]:
        if col["name"] in SYSTEM_COLUMNS or not col["notNull"]:
            continue
        if col.get("fk"):
            parent_var = var_of.get(col["fk"])
            expr = f"{parent_var}.id" if parent_var else "crypto.randomUUID()"
        else:
            expr = _value_expr(col)
        lines.append(f"{indent}  {json.dumps(col['name'])}: {expr},")
    if not lines:
        return "{}"
    return "{\n" + "\n".join(lines) + f"\n{indent}}}"


def _crud_test_source(ent: dict, chain: list[dict]) -> str:
    """One entity's create → read → update → delete round-trip test."""
    var_of: dict[str, str] = {}
    setup: list[str] = []
    for parent in chain:
        var = "parent" + re.sub(r"[^A-Za-z0-9]", "", parent["name"])
        var_of[parent["id"]] = var
        lit = _insert_literal(parent, var_of, "      ")
        setup.append(
            f"      const {var} = (await engine.create({_ts_string(parent['slug'])}, "
            f"{lit})).data as Record<string, any>;\n"
            f"      created.push([{_ts_string(parent['slug'])}, {var}.id]);")
    insert = _insert_literal(ent, var_of, "      ")

    mut = _mutable_column(ent)
    update_block = ""
    if mut is not None:
        update_block = f"""
      const updated = await engine.update({_ts_string(ent['slug'])}, row.id, {{
        {json.dumps(mut['name'])}: {_update_expr(mut)},
      }});
      expect((updated.data as Record<string, any>)[{json.dumps(mut['name'])}]).not.toBeUndefined();
"""

    setup_block = ("\n".join(setup) + "\n") if setup else ""
    return f"""{HEADER}
// CRUD round-trip for entity "{ent['name']}" (table {ent['table']}), derived
// from contracts/resource-registry.json. Runs only when DATABASE_URL is set
// (in-process data-engine import); FORGE_APP_TESTS_LIVE=0 force-skips.
import {{ describe, it, expect, beforeAll }} from "vitest";

const LIVE = !!process.env.DATABASE_URL && process.env.FORGE_APP_TESTS_LIVE !== "0";

describe.skipIf(!LIVE)("CRUD round-trip: {ent['name']}", () => {{
  let engine: typeof import("@/lib/data-engine");

  beforeAll(async () => {{
    engine = await import("@/lib/data-engine");
    const {{ ensureDataEngineInitialized }} = await import("@/lib/data-init");
    await ensureDataEngineInitialized();
  }});

  it("creates, reads back, updates and deletes a {ent['name']}", async () => {{
    const created: Array<[string, string]> = [];
    try {{
{setup_block}      const res = await engine.create({_ts_string(ent['slug'])}, {insert});
      const row = res.data as Record<string, any>;
      expect(row?.id).toBeTruthy();
      created.push([{_ts_string(ent['slug'])}, row.id]);

      const fetched = await engine.findById({_ts_string(ent['slug'])}, row.id);
      expect(fetched?.id).toBe(row.id);
{update_block}
      await engine.remove({_ts_string(ent['slug'])}, row.id);
      created.pop();
      await expect(engine.findById({_ts_string(ent['slug'])}, row.id)).rejects.toThrow();
    }} finally {{
      for (const [slug, id] of created.reverse()) {{
        try {{ await engine.remove(slug, id); }} catch {{ /* best-effort cleanup */ }}
      }}
    }}
  }}, 30000);
}});
"""


def _workflow_test_source(table_keys: list[str]) -> str:
    """Structural-executability checks over workflows/*.json — always runnable."""
    keys = json.dumps(sorted(table_keys))
    return f"""{HEADER}
// Structural executability of every workflow definition in workflows/*.json:
// entry (trigger) node exists, every edge endpoint resolves to a node, and
// every db_* action targets a table known to the resource registry. Pure JSON
// assertions — no database, always runs.
import {{ describe, it, expect }} from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import {{ fileURLToPath }} from "node:url";

const APP_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const WORKFLOWS_DIR = path.join(APP_ROOT, "workflows");

// Canonical (separator-stripped, plurality-tolerant) registry table keys.
const KNOWN_TABLE_KEYS = new Set<string>({keys});

function canon(s: string): string {{
  return String(s || "").replace(/[^a-z0-9]/gi, "").toLowerCase();
}}
function variants(s: string): string[] {{
  const c = canon(s);
  const flip = c.endsWith("ies") ? c.slice(0, -3) + "y"
    : c.endsWith("s") ? c.slice(0, -1) : c + "s";
  return [c, flip];
}}

const files = fs.existsSync(WORKFLOWS_DIR)
  ? fs.readdirSync(WORKFLOWS_DIR).filter((f) => f.endsWith(".json")).sort()
  : [];

describe("workflow definitions are structurally executable", () => {{
  it.skipIf(files.length > 0)("has no workflows directory (nothing to check)", () => {{
    expect(files.length).toBe(0);
  }});

  for (const file of files) {{
    describe(file, () => {{
      const wf = JSON.parse(fs.readFileSync(path.join(WORKFLOWS_DIR, file), "utf-8"));
      const def = wf.definition ?? wf;
      const nodes: any[] = Array.isArray(def.nodes) ? def.nodes : [];
      const edges: any[] = Array.isArray(def.edges) ? def.edges : [];
      const nodeIds = new Set(nodes.map((n) => n.id));

      it("has an entry (trigger) node", () => {{
        expect(nodes.length).toBeGreaterThan(0);
        const entry = nodes.find((n) => n.type === "trigger" || n.id === "trigger");
        expect(entry, "no trigger node").toBeTruthy();
      }});

      it("every edge endpoint resolves to a node", () => {{
        for (const e of edges) {{
          expect(nodeIds.has(e.source), `edge ${{e.id}} source ${{e.source}}`).toBe(true);
          expect(nodeIds.has(e.target), `edge ${{e.id}} target ${{e.target}}`).toBe(true);
        }}
      }});

      it("every db_* action targets a registry table", () => {{
        for (const n of nodes) {{
          const cfg = n?.data?.config ?? {{}};
          const action = String(cfg.actionType || n.type || "");
          if (!action.startsWith("db_")) continue;
          const table = cfg.table;
          expect(table, `node ${{n.id}} (${{action}}) has no table`).toBeTruthy();
          const ok = variants(String(table)).some((v) => KNOWN_TABLE_KEYS.has(v));
          expect(ok, `node ${{n.id}} targets unknown table "${{table}}"`).toBe(true);
        }}
      }});
    }});
  }}
}});
"""


def _consistency_test_source(entity_keys: list[str]) -> str:
    """Page-schema dataSources must reference registry entities — always runs."""
    keys = json.dumps(sorted(entity_keys))
    return f"""{HEADER}
// Registry consistency: every dataSource in src/schemas/**/*.json must
// reference an entity the resource registry knows (any name form — Pascal,
// slug, table, camel; plurality-tolerant). Pure JSON assertions.
import {{ describe, it, expect }} from "vitest";
import * as fs from "node:fs";
import * as path from "node:path";
import {{ fileURLToPath }} from "node:url";

const APP_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const SCHEMAS_DIR = path.join(APP_ROOT, "src", "schemas");

const KNOWN_ENTITY_KEYS = new Set<string>({keys});

function canon(s: string): string {{
  return String(s || "").replace(/[^a-z0-9]/gi, "").toLowerCase();
}}
function variants(s: string): string[] {{
  const c = canon(s);
  const flip = c.endsWith("ies") ? c.slice(0, -3) + "y"
    : c.endsWith("s") ? c.slice(0, -1) : c + "s";
  return [c, flip];
}}

function walk(dir: string): string[] {{
  if (!fs.existsSync(dir)) return [];
  const out: string[] = [];
  for (const name of fs.readdirSync(dir)) {{
    const p = path.join(dir, name);
    if (fs.statSync(p).isDirectory()) out.push(...walk(p));
    else if (name.endsWith(".json")) out.push(p);
  }}
  return out.sort();
}}

const schemaFiles = walk(SCHEMAS_DIR);

describe("page-schema dataSources reference registry entities", () => {{
  it.skipIf(schemaFiles.length > 0)("has no page schemas (nothing to check)", () => {{
    expect(schemaFiles.length).toBe(0);
  }});

  for (const file of schemaFiles) {{
    it(path.relative(APP_ROOT, file), () => {{
      let schema: any;
      try {{
        schema = JSON.parse(fs.readFileSync(file, "utf-8"));
      }} catch (e) {{
        throw new Error(`invalid JSON: ${{e}}`);
      }}
      const sources: any[] = Array.isArray(schema?.dataSources) ? schema.dataSources : [];
      for (const src of sources) {{
        const entity = src?.entity;
        if (!entity) continue;
        const ok = variants(String(entity)).some((v) => KNOWN_ENTITY_KEYS.has(v));
        expect(ok, `dataSource "${{src?.name}}" references unknown entity "${{entity}}"`).toBe(true);
      }}
    }});
  }}
}});
"""


VITEST_CONFIG = """import { defineConfig } from "vitest/config";
import * as path from "node:path";

export default defineConfig({
  test: {
    environment: "node",
    include: ["src/__tests__/**/*.test.ts"],
    testTimeout: 30000,
    hookTimeout: 30000,
  },
  resolve: {
    alias: { "@": path.resolve(__dirname, "src") },
  },
});
"""


# ── package.json wiring ──────────────────────────────────────────────────────

def _ensure_package_json(out: Path, written: list[str], skipped: list[dict]) -> None:
    pkg_path = out / "package.json"
    if not pkg_path.is_file():
        skipped.append({"file": "package.json", "reason": "missing"})
        return
    try:
        pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        skipped.append({"file": "package.json", "reason": f"unreadable: {e}"})
        return
    changed = False
    dev = pkg.setdefault("devDependencies", {})
    if "vitest" not in dev:
        dev["vitest"] = VITEST_VERSION
        changed = True
    scripts = pkg.setdefault("scripts", {})
    if "test" not in scripts:
        scripts["test"] = "vitest run"
        changed = True
    if changed:
        pkg_path.write_text(json.dumps(pkg, indent=2) + "\n", encoding="utf-8")
        written.append(str(pkg_path))
    else:
        skipped.append({"file": "package.json", "reason": "already wired"})


# ── entry point ──────────────────────────────────────────────────────────────

def emit_test_suite(output_dir: str) -> dict:
    """Emit the vitest regression suite into ``output_dir``. Never raises.

    Returns ``{"written": [...], "skipped": [...], "counts": {...}}``; when no
    registry exists the dict carries a ``reason`` and writes nothing.
    """
    written: list[str] = []
    skipped: list[dict] = []
    counts: dict[str, int] = {"crud_tests": 0, "workflow_files": 0,
                              "schema_files": 0, "entities_skipped": 0}
    try:
        out = Path(output_dir)
        if not out.is_dir():
            return {"written": [], "skipped": [], "counts": counts,
                    "reason": f"output dir not found: {output_dir}"}

        entities, source = _load_entities(out)
        if source is None:
            return {"written": [], "skipped": [], "counts": counts,
                    "reason": "no resource-registry.json or registry.json — nothing to derive"}

        by_id = {e["id"]: e for e in entities}
        gen_dir = out / GENERATED_DIR
        gen_dir.mkdir(parents=True, exist_ok=True)
        emitted_names: set[str] = set()

        def emit(name: str, content: str) -> None:
            path = gen_dir / name
            path.write_text(content, encoding="utf-8")
            written.append(str(path))
            emitted_names.add(name)

        # a) per-entity CRUD round-trips
        for ent in entities:
            if ent["table"] in RESERVED_TABLES:
                counts["entities_skipped"] += 1
                skipped.append({"entity": ent["name"],
                                "reason": "auth-reserved table"})
                continue
            chain, err = _parent_chain(ent, by_id)
            if err:
                counts["entities_skipped"] += 1
                skipped.append({"entity": ent["name"], "reason": err})
                continue
            emit(f"crud.{ent['slug']}.test.ts", _crud_test_source(ent, chain))
            counts["crud_tests"] += 1

        # b) workflow structural tests (registry table keys embedded)
        table_keys: set[str] = set()
        entity_keys: set[str] = set()
        for ent in entities:
            for form in (ent["name"], ent["table"], ent["slug"], ent["camel"],
                         ent["id"]):
                table_keys |= _key_variants(form)
                entity_keys |= _key_variants(form)
        counts["workflow_files"] = len(list((out / "workflows").glob("*.json"))) \
            if (out / "workflows").is_dir() else 0
        emit("workflows.test.ts", _workflow_test_source(sorted(table_keys)))

        # c) page-schema ↔ registry consistency
        schemas_dir = out / "src" / "schemas"
        counts["schema_files"] = len(list(schemas_dir.rglob("*.json"))) \
            if schemas_dir.is_dir() else 0
        emit("registry-consistency.test.ts",
             _consistency_test_source(sorted(entity_keys)))

        # manifest
        manifest = {
            "generator": "test_suite_emitter",
            "source": source,
            "counts": counts,
            "skipped": skipped,
        }
        emit("manifest.json", json.dumps(manifest, indent=2, sort_keys=True) + "\n")

        # prune stale generated files from earlier runs (header-carrying only)
        for existing in gen_dir.iterdir():
            if existing.name in emitted_names or not existing.is_file():
                continue
            try:
                head = existing.read_text(encoding="utf-8", errors="ignore")[:len(HEADER)]
                if head == HEADER:
                    existing.unlink()
            except OSError:
                pass

        # vitest.config.ts — only if absent (never clobber a user config)
        cfg = out / "vitest.config.ts"
        if cfg.exists() or (out / "vitest.config.mts").exists() \
                or (out / "vitest.config.js").exists():
            skipped.append({"file": "vitest.config.ts", "reason": "already present"})
        else:
            cfg.write_text(VITEST_CONFIG, encoding="utf-8")
            written.append(str(cfg))

        _ensure_package_json(out, written, skipped)

        logger.info(
            "test_suite_emitter: %d CRUD test(s), %d entity(ies) skipped, "
            "%d workflow file(s), %d schema file(s) covered (%s)",
            counts["crud_tests"], counts["entities_skipped"],
            counts["workflow_files"], counts["schema_files"], source)
        return {"written": written, "skipped": skipped, "counts": counts}
    except Exception as e:  # noqa: BLE001 — never break generation
        logger.warning("test_suite_emitter failed: %s", e)
        return {"written": written, "skipped": skipped, "counts": counts,
                "reason": f"emitter error: {e}"}
