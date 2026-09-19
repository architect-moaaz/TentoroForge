#!/usr/bin/env node
/**
 * The JIT renderer — one page of a generated app, bundled on demand.
 *
 * The editor's canvas used to need the app's dev server (`next dev`, a
 * database, a login). This bundles a page from the app's OWN node_modules
 * with esbuild — the same React, the same UI kit, the same library, the same
 * Tailwind config and tokens — and runs its `load()` against a sample-data
 * stand-in for `@/sdk/server`, generated from the Blueprint's entities. The
 * result is one script and one stylesheet the editor puts in an iframe.
 *
 * Input (stdin JSON):  {appRoot, pageId, pageDir, route, access, entities,
 *                       roles, params, searchParams, shimsDir}
 * Output (stdout JSON): {ok, js, css, ms, inputs, warnings} | {ok:false, error}
 *
 * Everything the bundle needs to resolve (`next/*`, the sample server) is
 * written under <appRoot>/.forge-jit so it resolves the app's React, never
 * the platform's.
 */
import { mkdirSync, readFileSync, writeFileSync, existsSync, copyFileSync, readdirSync } from "fs";
import { createRequire } from "module";
import { dirname, join, resolve } from "path";

async function main() {
  const chunks = [];
  for await (const c of process.stdin) chunks.push(c);
  const input = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  const t0 = Date.now();
  try {
    const out = await build(input);
    process.stdout.write(JSON.stringify({ ok: true, ms: Date.now() - t0, ...out }));
  } catch (e) {
    process.stdout.write(JSON.stringify({ ok: false, error: { message: String(e && e.message || e), detail: String(e && e.stack || "").slice(0, 2000) } }));
    process.exitCode = 2;
  }
}

async function build({ appRoot, pageId, pageDir, route, access, entities, roles, params, searchParams, shimsDir }) {
  const req = createRequire(join(appRoot, "package.json"));
  const esbuild = req("esbuild");
  const work = join(appRoot, ".forge-jit", pageId);
  const shims = join(appRoot, ".forge-jit", "shims");
  mkdirSync(work, { recursive: true });
  mkdirSync(shims, { recursive: true });
  for (const f of readdirSync(shimsDir)) copyFileSync(join(shimsDir, f), join(shims, f));
  writeFileSync(join(shims, "sample-server.ts"), sampleServer(entities || [], roles || []));

  const isPublic = access === "public";
  const entry = join(work, "entry.tsx");
  writeFileSync(entry, `
import React from "react";
import { createRoot } from "react-dom/client";
import { Toaster } from "sonner";
import { PageFrame } from "@/sdk/frame";
${isPublic ? 'import { PublicPageFrame } from "@/components/PublicPageFrame";' : ""}
import { load } from "@/${pageDir.replace(/^src\//, "")}/load";
import View from "@/${pageDir.replace(/^src\//, "")}/view";
import { currentUser, __forgeEntities } from "@/sdk/server";
import { installPreviewFetch } from "./../shims/preview-fetch";

const PARAMS: Record<string, string> = ${JSON.stringify(params || {})};
const SEARCH: Record<string, string | undefined> = ${JSON.stringify(searchParams || {})};
(window as any).__forgeParams = PARAMS;
(window as any).__forgeLocation = ${JSON.stringify(filledRoute(route, params, searchParams))};
installPreviewFetch();

function Boundary({ children }: { children: React.ReactNode }) {
  const [err, setErr] = React.useState<Error | null>(null);
  return <ErrorCatcher onError={setErr} error={err}>{children}</ErrorCatcher>;
}
class ErrorCatcher extends React.Component<{ onError: (e: Error) => void; error: Error | null; children: React.ReactNode }> {
  static getDerivedStateFromError() { return {}; }
  componentDidCatch(e: Error) { this.props.onError(e); window.parent?.postMessage({ type: "forge-editor:error", payload: { message: e.message, file: "view.tsx", line: 0 } }, window.location.origin); }
  render() {
    if (this.props.error) return <div style={{ padding: 24, fontFamily: "system-ui", color: "#991b1b" }}><b>This part could not load.</b><div style={{ marginTop: 6, fontSize: 13 }}>{this.props.error.message}</div></div>;
    return this.props.children;
  }
}

async function render() {
  const root = document.getElementById("root")!;
  const ctx = { params: PARAMS, searchParams: SEARCH, user: await currentUser() };
  let data: any;
  try { data = await load(ctx as any); }
  catch (e: any) {
    window.parent?.postMessage({ type: "forge-editor:error", payload: { message: "What this page loads failed: " + (e?.message ?? e), file: "load.ts", line: 0 } }, window.location.origin);
    data = {};
  }
  if (data === null) {
    createRoot(root).render(<div style={{ padding: 24, fontFamily: "system-ui" }}><b>Not found.</b><div style={{ marginTop: 6, fontSize: 13, color: "#64748b" }}>This page shows one record and none matched — in the app this is the 404 page.</div></div>);
    return;
  }
  const page = <Boundary><View {...data} /></Boundary>;
  const framed = <PageFrame entities={${JSON.stringify(__entityNames(entities))}}>{page}</PageFrame>;
  createRoot(root).render(<>${isPublic ? "<PublicPageFrame>{framed}</PublicPageFrame>" : "{framed}"}<Toaster richColors position="bottom-right" /></>);
}
(window as any).__forgeRender = render;
render();
`);

  const resolvePlugin = {
    name: "forge-jit",
    setup(b) {
      b.onResolve({ filter: /^next\/link$/ }, () => ({ path: join(shims, "link.tsx") }));
      b.onResolve({ filter: /^next\/navigation$/ }, () => ({ path: join(shims, "navigation.tsx") }));
      b.onResolve({ filter: /^next\/image$/ }, () => ({ path: join(shims, "image.tsx") }));
      b.onResolve({ filter: /^next\/(headers|cache|server)$/ }, () => ({ path: join(shims, "empty.ts") }));
      b.onResolve({ filter: /^server-only$/ }, () => ({ path: join(shims, "empty.ts") }));
      b.onResolve({ filter: /^@\/sdk\/server$/ }, () => ({ path: join(shims, "sample-server.ts") }));
      b.onResolve({ filter: /^@\/(auth|lib\/data-engine|lib\/data-engine-bridge|lib\/data-init|db(\/.*)?)$/ }, () => ({ path: join(shims, "empty.ts") }));
      b.onResolve({ filter: /\.css$/ }, (args) => ({ path: args.path, namespace: "forge-css" }));
      b.onLoad({ filter: /.*/, namespace: "forge-css" }, () => ({ contents: "", loader: "js" }));
    },
  };
  const result = await esbuild.build({
    absWorkingDir: appRoot,
    entryPoints: [entry],
    outfile: join(work, "bundle.js"),
    bundle: true,
    write: false,
    format: "iife",
    platform: "browser",
    target: "es2020",
    jsx: "automatic",
    sourcemap: false,
    metafile: true,
    logLevel: "silent",
    define: { "process.env.NODE_ENV": '"development"', "process.env.NEXT_PUBLIC_BASE_PATH": '""', "process.env.NEXT_BASE_PATH": '""' },
    loader: { ".png": "dataurl", ".jpg": "dataurl", ".svg": "dataurl", ".woff2": "dataurl", ".woff": "dataurl" },
    plugins: [resolvePlugin],
  });
  const js = (result.outputFiles.find((f) => f.path.endsWith("bundle.js")) ?? result.outputFiles[0])?.text ?? "";
  if (!js) throw new Error("esbuild produced no script");
  const inputs = Object.keys(result.metafile.inputs).filter((p) => !p.startsWith("<"));
  const warnings = result.warnings.map((w) => w.text).slice(0, 10);
  let css = "";
  try { css = await tailwind(appRoot, req, inputs); }
  catch (e) { warnings.push("The page's styles could not be compiled: " + String(e && e.message || e).slice(0, 300)); }
  return { js, css, inputs: inputs.length, warnings };
}

function filledRoute(route, params, search) {
  const path = String(route || "/").replace(/\[([^\]]+)\]/g, (_, k) => encodeURIComponent((params || {})[k] ?? ""));
  const q = new URLSearchParams(Object.entries(search || {}).filter(([, v]) => v != null)).toString();
  return q ? `${path}?${q}` : path;
}

function __entityNames(entities) {
  return (entities || []).map((e) => e.name);
}

/** The app's own Tailwind (v3, postcss) over its globals and the bundled sources. */
async function tailwind(appRoot, req, inputs) {
  const postcss = req("postcss");
  const tailwindcss = req("tailwindcss");
  let config = {};
  const cfgPath = ["tailwind.config.ts", "tailwind.config.js", "tailwind.config.mjs", "tailwind.config.cjs"].map((f) => join(appRoot, f)).find(existsSync);
  if (cfgPath) {
    try { config = req("tailwindcss/loadConfig")(cfgPath); }
    catch (e) { config = {}; }
  }
  // Only what the bundle actually contains: the page, the kit and library
  // modules it pulls in. The app's own globs would rescan every source and
  // schema on each build, for classes this page never renders.
  const content = inputs.map((p) => resolve(appRoot, p)).filter((p) => /\.(tsx?|jsx?|mjs|cjs)$/.test(p));
  const plugins = [];
  try { plugins.push(req("postcss-import")()); } catch { /* inlined below */ }
  plugins.push(tailwindcss({ ...config, content }));
  try { plugins.push(req("autoprefixer")()); } catch { /* optional */ }
  const globals = ["src/app/globals.css", "app/globals.css", "src/styles/globals.css"].map((f) => join(appRoot, f)).find(existsSync);
  let cssIn = globals ? readFileSync(globals, "utf8") : '@tailwind base;\n@tailwind components;\n@tailwind utilities;\n';
  if (!plugins.some((p) => p.postcssPlugin === "postcss-import") && globals) cssIn = inlineImports(cssIn, dirname(globals));
  const out = await postcss(plugins).process(cssIn, { from: globals ?? join(appRoot, "src/app/globals.css") });
  return out.css;
}

function inlineImports(css, dir) {
  return css.replace(/@import\s+["']([^"']+)["'];?/g, (m, p) => {
    const f = resolve(dir, p);
    return existsSync(f) ? inlineImports(readFileSync(f, "utf8"), dirname(f)) : m;
  });
}

// ---------------------------------------------------------------------------
// Sample data — deterministic rows from the entities' fields (PREVIEW-004)
// ---------------------------------------------------------------------------

const FIRST = ["Amara", "Bao", "Chiara", "Dmitri", "Esi", "Farid", "Greta", "Hiro", "Ines", "Jonas", "Kofi", "Leila"];
const LAST = ["Okafor", "Nguyen", "Rossi", "Volkov", "Mensah", "Haddad", "Lindqvist", "Tanaka", "Moreau", "Weber", "Boateng", "Rahimi"];
const WORDS = ["Quarterly review", "Site visit", "Renewal", "Onboarding", "Follow-up", "Inspection", "Proposal", "Audit", "Launch", "Handover", "Request", "Escalation"];

function sampleServer(entities, roles) {
  const rows = {};
  for (const e of entities) rows[e.name] = Array.from({ length: 8 }, (_, i) => sampleRow(e, i, entities));
  const user = { id: "sample-user", name: "Sample Admin", email: "admin@example.com", role: roles[0] || "admin" };
  return `// Generated by the editor's JIT renderer — sample data in place of @/sdk/server.
export type { Entities, EntityName } from "./../../src/sdk/schema";
export interface SessionUser { id: string; name: string | null; email: string | null; role: string | null }
export interface PageContext { params: Record<string, string>; searchParams: Record<string, string | undefined>; user: SessionUser | null }
export interface Page<T> { rows: T[]; total: number; page: number; limit: number }
export interface SeriesPoint { label: string; value: number }
export type Where<E> = any; export type ListOptions<E> = any; export type NumericField<E> = any;
const ROWS: Record<string, any[]> = ${JSON.stringify(rows)};
export const __forgeEntities = ${JSON.stringify(entities.map((e) => e.name))};
const wait = () => new Promise<void>((r) => setTimeout(r, 30));
function filter(entity: string, opts: any = {}) {
  let out = [...(ROWS[entity] ?? [])];
  if (opts.where) for (const [k, v] of Object.entries(opts.where)) out = out.filter((r) => String(r[k]) === String(v));
  if (opts.search) { const q = String(opts.search).toLowerCase(); out = out.filter((r) => Object.values(r).some((v) => String(v).toLowerCase().includes(q))); }
  if (opts.sort) { const k = opts.sort; const dir = opts.order === "desc" ? -1 : 1; out.sort((a, b) => (a[k] > b[k] ? 1 : a[k] < b[k] ? -1 : 0) * dir); }
  return out;
}
export async function currentUser(): Promise<SessionUser | null> { await wait(); return ${JSON.stringify(user)}; }
export async function listPage(entity: string, opts: any = {}): Promise<Page<any>> {
  await wait();
  const limit = Math.min(Math.max(opts.limit ?? 50, 1), 200); const page = Math.max(opts.page ?? 1, 1);
  const all = filter(entity, opts);
  return { rows: all.slice((page - 1) * limit, page * limit), total: all.length, page, limit };
}
export async function list(entity: string, opts: any = {}): Promise<any[]> { return (await listPage(entity, opts)).rows; }
export async function record(entity: string, id: string | undefined): Promise<any | null> {
  await wait();
  if (!id || /[[\\]]/.test(id)) return null;
  return (ROWS[entity] ?? []).find((r) => r.id === id) ?? (ROWS[entity] ?? [])[0] ?? null;
}
export async function count(entity: string, where?: any): Promise<number> { await wait(); return filter(entity, { where }).length; }
export async function total(entity: string, fn: string, field: string, where?: any): Promise<number> {
  await wait();
  const vals = filter(entity, { where }).map((r) => Number(r[field]) || 0);
  if (!vals.length) return 0;
  if (fn === "sum") return vals.reduce((a, b) => a + b, 0);
  if (fn === "avg") return vals.reduce((a, b) => a + b, 0) / vals.length;
  if (fn === "min") return Math.min(...vals);
  if (fn === "max") return Math.max(...vals);
  return vals.length;
}
export async function series(entity: string, opts: any): Promise<SeriesPoint[]> {
  await wait();
  const groups = new Map<string, number[]>();
  for (const r of ROWS[entity] ?? []) {
    let key = String(r[opts.groupBy] ?? "");
    if (/^\\d{4}-\\d{2}-\\d{2}/.test(key)) key = opts.bucket === "month" ? key.slice(0, 7) : key.slice(0, 10);
    groups.set(key, [...(groups.get(key) ?? []), Number(r[opts.field]) || 0]);
  }
  return [...groups.entries()].map(([label, vals]) => ({ label, value: opts.fn === "sum" ? vals.reduce((a, b) => a + b, 0) : opts.fn === "avg" ? vals.reduce((a, b) => a + b, 0) / vals.length : vals.length }));
}
`;
}

function sampleRow(entity, i, entities) {
  const row = {};
  const fields = entity.fields || [];
  const name = entity.name;
  for (const f of fields) {
    const fname = f.name;
    const type = String(f.type || "string").toLowerCase();
    const opts = f.enumValues || f.options || [];
    const lower = fname.toLowerCase();
    if (lower === "id") row[fname] = `sample-${name.toLowerCase()}-${i + 1}`;
    else if (opts.length) row[fname] = opts[i % opts.length];
    else if (/email/.test(lower)) row[fname] = `${FIRST[i % FIRST.length].toLowerCase()}.${LAST[i % LAST.length].toLowerCase()}@example.com`;
    else if (/phone|tel/.test(lower)) row[fname] = `+1 555 01${String(i).padStart(2, "0")} ${String(1000 + i * 37).slice(0, 4)}`;
    else if (/name|title|subject/.test(lower) && /string|text/.test(type)) row[fname] = /first/.test(lower) ? FIRST[i % FIRST.length] : /last|sur/.test(lower) ? LAST[i % LAST.length] : /full|^name$|person|customer|owner|contact/.test(lower) ? `${FIRST[i % FIRST.length]} ${LAST[i % LAST.length]}` : `${WORDS[i % WORDS.length]} ${i + 1}`;
    else if (/description|notes?|summary|body|comment/.test(lower)) row[fname] = `Sample ${lower} for ${name.toLowerCase()} ${i + 1} — placeholder text shown while designing.`;
    else if (/url|link|website/.test(lower)) row[fname] = `https://example.com/${name.toLowerCase()}/${i + 1}`;
    else if (/status|state|stage/.test(lower)) row[fname] = ["Open", "In progress", "Done", "On hold"][i % 4];
    else if (/^(uuid|id)$/.test(type) || /(^|_)id$|Id$/.test(fname)) {
      const target = (entities || []).find((e) => lower.startsWith(e.name.toLowerCase())) || entities?.[0];
      row[fname] = `sample-${(target ? target.name : name).toLowerCase()}-${(i % 3) + 1}`;
    }
    else if (/int|number|decimal|float|numeric|money|currency|amount|price|count|age|quantity/.test(type) || /amount|price|total|count|qty|age|score/.test(lower)) {
      const base = /age/.test(lower) ? 22 + ((i * 7) % 45) : /price|amount|total|money|currency/.test(lower + type) ? (i + 1) * 125.5 : (i + 1) * 3;
      row[fname] = /int|count|age|qty|quantity/.test(type + lower) ? Math.round(base) : Number(base.toFixed(2));
    }
    else if (/bool/.test(type)) row[fname] = i % 2 === 0;
    else if (/date|time/.test(type) || /at$|date/.test(lower)) {
      const d = new Date(Date.UTC(2026, 8, 1 + ((i * 3) % 27), 9 + (i % 8), (i * 11) % 60));
      row[fname] = /^date$/.test(type) ? d.toISOString().slice(0, 10) : d.toISOString();
    }
    else if (/\[\]|array|list|tags/.test(type + lower)) row[fname] = [WORDS[i % WORDS.length].split(" ")[0], WORDS[(i + 3) % WORDS.length].split(" ")[0]];
    else if (/json|object/.test(type)) row[fname] = {};
    else row[fname] = `${humanise(fname)} ${i + 1}`;
  }
  if (!("id" in row)) row.id = `sample-${name.toLowerCase()}-${i + 1}`;
  return row;
}

function humanise(s) {
  return s.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/[_-]+/g, " ").replace(/^./, (c) => c.toUpperCase());
}

main();
