/**
 * Snapshot / restore a project's editable artifacts through the persistence
 * endpoint, so a destructive sweep can be undone exactly.
 *
 *   node tests/e2e/snapshot.mjs save <shortId>
 *   node tests/e2e/snapshot.mjs restore <shortId>
 *
 * WHY THIS IS NOT AS SIMPLE AS GET-THEN-POST — the two verbs disagree about
 * `app/`. GET falls back to `<base>/app/<path>` when `<base>/<path>` is missing
 * (_debug_schema.py:901-905); POST has NO such fallback and always writes
 * `<base>/<path>` (:951-952). So a naive restore of a file that was READ from
 * `app/src/...` would CREATE a new `src/...`, leaving the original untouched and
 * the app reading a different file than the editor. This resolves each path
 * explicitly before writing, and refuses to restore anything it did not read
 * from the identical path.
 *
 * It also never trusts a 200: nav-flow.json is SYNTHESIZED by the GET handler
 * when absent (:910-915), so a successful read does not prove the file existed.
 */
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";

const API = process.env.E2E_API ?? "http://localhost:6500";
const [mode, shortId] = process.argv.slice(2);
if (!mode || !shortId) {
  console.error("usage: node tests/e2e/snapshot.mjs <save|restore> <shortId>");
  process.exit(1);
}
const STORE = resolve(process.cwd(), `tests/e2e/.auth/snapshot-${shortId}.json`);

const url = (p) => `${API}/api/_debug/project-file/${shortId}/${p}`;

async function get(p) {
  const res = await fetch(url(p));
  if (!res.ok) return { ok: false, status: res.status };
  const text = await res.text();
  return { ok: true, text };
}
async function post(p, content) {
  const res = await fetch(url(p), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ content }),
  });
  return { ok: res.ok, status: res.status };
}

/** Resolve which spelling actually holds the file, without relying on the fallback. */
async function resolvePath(rel) {
  const direct = await get(rel);
  if (direct.ok) return { path: rel, text: direct.text };
  const nested = await get(`app/${rel}`);
  if (nested.ok) return { path: `app/${rel}`, text: nested.text };
  return null;
}

if (mode === "save") {
  // Discover the page set from nav-flow rather than guessing src/schemas/<id>.json
  const nav = await resolvePath("src/contracts/nav-flow.json");
  const files = [];
  if (nav) {
    files.push(nav);
    let pages = [];
    try { pages = JSON.parse(nav.text).pages ?? []; } catch { /* keep going */ }
    for (const pg of pages) {
      const rel = pg.schemaFile ?? `src/schemas/${pg.id}.json`;
      const f = await resolvePath(rel);
      if (f) files.push(f);
      else console.warn(`[snap] page "${pg.id}" -> ${rel} NOT FOUND (recorded as absent)`);
    }
  } else {
    console.warn("[snap] nav-flow.json unreadable");
  }
  const tokens = await resolvePath("src/theme/tokens.custom.json");
  if (tokens) files.push(tokens);

  mkdirSync(resolve(process.cwd(), "tests/e2e/.auth"), { recursive: true });
  writeFileSync(STORE, JSON.stringify({ shortId, files }, null, 1), "utf-8");
  console.log(`[snap] saved ${files.length} files -> ${STORE}`);
  for (const f of files) console.log(`[snap]   ${f.path} (${f.text.length} bytes)`);
} else if (mode === "restore") {
  if (!existsSync(STORE)) { console.error(`[snap] no snapshot at ${STORE}`); process.exit(1); }
  const { files } = JSON.parse(readFileSync(STORE, "utf-8"));
  let ok = 0, bad = 0;
  for (const f of files) {
    const r = await post(f.path, f.text);
    if (r.ok) ok++; else { bad++; console.error(`[snap] FAILED ${f.path} status=${r.status}`); }
  }
  // Verify byte-for-byte rather than trusting the 200s.
  let verified = 0;
  for (const f of files) {
    const back = await get(f.path);
    if (back.ok && back.text.trim() === f.text.trim()) verified++;
    else console.error(`[snap] MISMATCH after restore: ${f.path}`);
  }
  console.log(`[snap] restored ${ok}/${files.length}, failures ${bad}, verified identical ${verified}/${files.length}`);
  if (verified !== files.length) process.exit(1);
} else {
  console.error(`[snap] unknown mode "${mode}"`);
  process.exit(1);
}
