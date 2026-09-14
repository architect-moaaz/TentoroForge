/**
 * Create (or discard) a throwaway project for the sweep.
 *
 *   node tests/e2e/scratch-project.mjs create
 *   node tests/e2e/scratch-project.mjs verify
 *   node tests/e2e/scratch-project.mjs discard
 *
 * WHY A WHOLE PROJECT AND NOT PAGES IN A REAL ONE. `_resolve_project_base`
 * returns a literal path for an unknown non-UUID id without raising
 * (_debug_schema.py:56-59) and the write handler mkdir -p's into it, so a
 * project directory costs nothing: no DB row, no auth, no LLM, no org
 * membership, and it never appears in the DB-backed project list. The user's
 * six real projects are therefore never opened or written.
 *
 * WHY IT COPIES CONTRACT FILES. Bindings are only testable if
 * GET /api/_debug/preview-data/<id> returns fixtures; that endpoint derives
 * entities from src/contracts/registry.json, app-model.json, or
 * .forge/blueprint/current.json (_debug_schema.py:470-500). A bare scratch
 * project yields {} — and an empty previewData makes EVERY binding look broken,
 * which would be ~43 false reports in one stroke. So the donor project's entity
 * source is copied in and the result is VERIFIED before any sweep runs.
 *
 * WHY THE ROOT IS Container > Stack. An empty page's root falls back to `Text`
 * (Canvas.tsx:70-75), and `Text` is not a starterRegistry key, so validateDrop
 * refuses EVERY palette drop with "parent Text not in registry". Container and
 * Stack are both unrestricted `{type:"list"}` slots.
 */
import { existsSync, mkdirSync, copyFileSync, writeFileSync, rmSync } from "node:fs";
import { dirname, join } from "node:path";

const API = process.env.E2E_API ?? "http://localhost:6500";
const OUTPUT_ROOT = process.env.E2E_OUTPUT_ROOT ?? "C:/Users/user/a2ui/TentoroForge/output";
const DONOR = process.env.E2E_DONOR ?? "gh0mlpbp";
const ID = process.env.E2E_SCRATCH ?? "e2e-scratch";
const DIR = join(OUTPUT_ROOT, ID);

const PAGE_ID = "sweep";
const PAGE = {
  schemaVersion: "2",
  id: PAGE_ID,
  route: "/sweep",
  // One declared dataSource so binding assertions have a resolvable root.
  // Bindings to anything else (form./state./global./row.) cannot resolve in
  // this runtime and are excluded by expression root, never reported as bugs.
  dataSources: [
    { name: "items", entity: "Item", op: "list", limit: 25 },
    { name: "itemStats", entity: "Item", op: "aggregate", metrics: ["count"] },
  ],
  root: {
    id: "sweep-root",
    type: "Container",
    props: { maxWidth: "xl" },
    children: [
      { id: "sweep-stack", type: "Stack", props: { direction: "vertical", gap: "tokens.spacing.6" }, children: [] },
    ],
  },
};

const NAV = {
  version: "1.0",
  initialPage: PAGE_ID,           // auto-selected on load; no click needed
  pages: [{ id: PAGE_ID, route: "/sweep", title: "Sweep", schemaFile: `src/schemas/${PAGE_ID}.json`, params: [], shell: true }],
  transitions: [],
  guards: {},
};

function write(rel, obj) {
  const full = join(DIR, rel);
  mkdirSync(dirname(full), { recursive: true });
  writeFileSync(full, typeof obj === "string" ? obj : JSON.stringify(obj, null, 2), "utf-8");
  console.log(`[scratch]   wrote ${rel}`);
}

const mode = process.argv[2] ?? "create";

if (mode === "discard") {
  if (existsSync(DIR)) { rmSync(DIR, { recursive: true, force: true }); console.log(`[scratch] removed ${DIR}`); }
  else console.log(`[scratch] nothing at ${DIR}`);
  process.exit(0);
}

if (mode === "create") {
  const donorDir = join(OUTPUT_ROOT, DONOR);
  if (!existsSync(donorDir)) { console.error(`[scratch] donor ${donorDir} missing`); process.exit(1); }

  mkdirSync(DIR, { recursive: true });
  write(`src/schemas/${PAGE_ID}.json`, PAGE);
  write("src/contracts/nav-flow.json", NAV);

  // Copy ONLY the entity source — not pages, not schemas. Read-only on the donor.
  let copied = 0;
  for (const rel of [".forge/blueprint/current.json",
                     "src/contracts/registry.json",
                     "src/contracts/design-spec.json",
                     "app-model.json"]) {
    const src = join(donorDir, rel);
    if (!existsSync(src)) continue;
    const dst = join(DIR, rel);
    mkdirSync(dirname(dst), { recursive: true });
    copyFileSync(src, dst);
    console.log(`[scratch]   copied ${rel}`);
    copied++;
  }
  if (!copied) console.warn("[scratch] WARNING: no entity source copied — bindings will not be testable");
  console.log(`[scratch] created ${DIR}`);
}

// ---- verify over HTTP, the way the editor will actually see it -------------
const get = async (p) => {
  const r = await fetch(`${API}/api/_debug/project-file/${ID}/${p}`);
  return { ok: r.ok, status: r.status, text: r.ok ? await r.text() : "" };
};

const nav = await get("src/contracts/nav-flow.json");
const pg = await get(`src/schemas/${PAGE_ID}.json`);
const pd = await fetch(`${API}/api/_debug/preview-data/${ID}`);
const pdBody = pd.ok ? await pd.json() : null;
const pdKeys = pdBody ? Object.keys(pdBody) : [];

console.log("");
console.log(`[verify] nav-flow            : ${nav.status}`);
console.log(`[verify] page schema         : ${pg.status}`);
console.log(`[verify] preview-data        : ${pd.status}  keys=${pdKeys.length}`);
console.log(`[verify] preview-data sample : ${pdKeys.slice(0, 8).join(", ") || "(none)"}`);

const rootType = pg.ok ? (JSON.parse(pg.text).root?.type ?? "?") : "?";
console.log(`[verify] page root type      : ${rootType} ${rootType === "Container" ? "(droppable)" : "(NOT DROPPABLE)"}`);

const bindable = pdKeys.length > 0;
console.log("");
console.log(`[verify] BINDINGS TESTABLE   : ${bindable ? "YES" : "NO — previewData is empty, bindings must not be scored"}`);
if (!bindable) process.exitCode = 2;
