#!/usr/bin/env node
/**
 * The JIT renderer — one page of a generated app, bundled on demand.
 *
 * The editor's canvas used to need the app's dev server (`next dev`, a
 * database, a login). This bundles a page from the app's OWN node_modules
 * with esbuild — the same React, the same UI kit, the same library, the same
 * Tailwind config and tokens — and runs its `load()` against a sample-data
 * stand-in for `@/sdk/server`, generated from the Blueprint's entities.
 *
 * Two commands, JSON on stdin and stdout:
 *
 *   vendor  {appRoot, pages: [{pageDir}], shimsDir, entities, roles}
 *           → {ok, key, js, specifiers, candidates, timings}
 *           Everything the pages import from node_modules, built ONCE per app
 *           into one minified script that fills `window.__forgeVendor`, plus
 *           the Tailwind class candidates those modules contain.
 *
 *   page    {appRoot, pageId, pageDir, route, access, entities, roles, params,
 *            searchParams, shimsDir, vendor: {specifiers, candidates}}
 *           → {ok, js, css, inputs, warnings, timings}
 *           The page's own code, with every vendor import resolved to the
 *           shared script; Tailwind over the page's files and the vendor's
 *           candidates — never a rescan of node_modules.
 *
 * Everything the bundle needs to resolve (`next/*`, the sample server) is
 * written under <appRoot>/.forge-jit so it resolves the app's React, never
 * the platform's.
 */
import { createHash } from "crypto";
import { mkdirSync, readFileSync, writeFileSync, existsSync, copyFileSync, readdirSync } from "fs";
import { createRequire } from "module";
import { dirname, join, resolve } from "path";

async function main() {
  const chunks = [];
  for await (const c of process.stdin) chunks.push(c);
  const input = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  const t0 = Date.now();
  try {
    const out = input.command === "vendor" ? await buildVendor(input) : await buildPage(input);
    process.stdout.write(JSON.stringify({ ok: true, ms: Date.now() - t0, ...out }));
  } catch (e) {
    process.stdout.write(JSON.stringify({ ok: false, error: { message: String(e && e.message || e), detail: String(e && e.stack || "").slice(0, 2000) } }));
    process.exitCode = 2;
  }
}

//: Always vendor, whether or not a page names them: the JSX runtime esbuild
//: injects, React itself, and what the entry uses.
const ALWAYS_VENDOR = ["react", "react/jsx-runtime", "react/jsx-dev-runtime", "react-dom", "react-dom/client", "sonner"];

function prepare(appRoot, shimsDir, entities, roles) {
  const req = createRequire(join(appRoot, "package.json"));
  const shims = join(appRoot, ".forge-jit", "shims");
  mkdirSync(shims, { recursive: true });
  for (const f of readdirSync(shimsDir)) copyFileSync(join(shimsDir, f), join(shims, f));
  writeFileSync(join(shims, "sample-server.ts"), sampleServer(entities || [], roles || []));
  return { req, esbuild: req("esbuild"), shims };
}

/** The resolutions every build shares: Next's modules and the server SDK go to the shims. */
function shimPlugin(shims) {
  return {
    name: "forge-jit-shims",
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
}

const BASE_BUILD = {
  bundle: true, write: false, platform: "browser", target: "es2020", jsx: "automatic", sourcemap: false,
  metafile: true, logLevel: "silent",
  define: { "process.env.NODE_ENV": '"development"', "process.env.NEXT_PUBLIC_BASE_PATH": '""', "process.env.NEXT_BASE_PATH": '""' },
  loader: { ".png": "dataurl", ".jpg": "dataurl", ".svg": "dataurl", ".woff2": "dataurl", ".woff": "dataurl" },
};

function isBare(spec) {
  return !/^(\.|\/|@\/|next\/|server-only$)/.test(spec) && !spec.startsWith("forge-");
}

function isVendorPath(p) {
  // Relative to the app root normally; under a symlinked root esbuild prints
  // the real path, so the test is on the segment, not the start.
  return /(^|\/)(node_modules|vendor)\//.test(p);
}

// ---------------------------------------------------------------------------
// vendor
// ---------------------------------------------------------------------------

async function buildVendor({ appRoot, pages, shimsDir, entities, roles }) {
  const { req, esbuild, shims } = prepare(appRoot, shimsDir, entities, roles);
  const work = join(appRoot, ".forge-jit", "vendor");
  mkdirSync(work, { recursive: true });

  // 1. Discover what the pages import from node_modules, by bundling them once.
  const tDisc = Date.now();
  const probe = join(work, "probe.tsx");
  // Every import is USED: esbuild elides an unused import from a TypeScript
  // file, and an elided page discovers nothing.
  const lines = [
    'import * as f0 from "@/sdk/frame"; import * as f1 from "@/components/PublicPageFrame"; import * as f2 from "sonner"; import * as f3 from "react-dom/client";',
    ...(pages || []).map((p, i) => `import * as v${i} from "@/${p.pageDir.replace(/^src\//, "")}/view"; import * as l${i} from "@/${p.pageDir.replace(/^src\//, "")}/load";`),
    `export const __all = [f0, f1, f2, f3, ${(pages || []).map((_, i) => `v${i}, l${i}`).join(", ")}];`,
  ];
  writeFileSync(probe, lines.join("\n") + "\n");
  const disc = await esbuild.build({ ...BASE_BUILD, absWorkingDir: appRoot, entryPoints: [probe], outfile: join(work, "probe.js"), plugins: [shimPlugin(shims)] });
  const specifiers = new Set(ALWAYS_VENDOR);
  for (const [file, info] of Object.entries(disc.metafile.inputs)) {
    if (isVendorPath(file)) continue; // only what APP code asks for by name
    for (const imp of info.imports || []) {
      if (imp.external || !imp.original || !isBare(imp.original)) continue;
      if (imp.path && isVendorPath(imp.path)) specifiers.add(imp.original);
    }
  }
  const list = [...specifiers].sort();

  // 2. One script that fills window.__forgeVendor with each module's namespace.
  const tBuild = Date.now();
  const entry = join(work, "vendor-entry.js");
  writeFileSync(entry, list.map((s, i) => `import * as m${i} from ${JSON.stringify(s)};`).join("\n")
    + `\nwindow.__forgeVendor = {\n${list.map((s, i) => `  ${JSON.stringify(s)}: m${i},`).join("\n")}\n};\n`);
  const result = await esbuild.build({ ...BASE_BUILD, absWorkingDir: appRoot, entryPoints: [entry], outfile: join(work, "vendor.js"),
    format: "iife", minify: true, plugins: [shimPlugin(shims)] });
  const js = (result.outputFiles.find((f) => f.path.endsWith("vendor.js")) ?? result.outputFiles[0])?.text ?? "";
  if (!js) throw new Error("esbuild produced no vendor script");

  // 3. The Tailwind class candidates the vendor modules contain, once.
  const tCand = Date.now();
  const inputs = Object.keys(result.metafile.inputs).filter((p) => !p.startsWith("<"));
  const candidates = vendorCandidates(appRoot, req, inputs);

  const versions = list.map((s) => { try { return req(`${s.split("/").slice(0, s.startsWith("@") ? 2 : 1).join("/")}/package.json`).version; } catch { return "?"; } });
  const key = createHash("sha1").update(JSON.stringify([list, versions])).digest("hex").slice(0, 16);
  return { key, js, specifiers: list, candidates, inputs: inputs.length,
           timings: { discoverMs: tBuild - tDisc, buildMs: tCand - tBuild, candidatesMs: Date.now() - tCand } };
}

//: Utilities with no dash or variant that a library might still use.
const BARE_UTILITIES = new Set(["flex", "grid", "block", "hidden", "inline", "contents", "relative", "absolute", "fixed", "sticky", "static",
  "container", "truncate", "italic", "underline", "uppercase", "lowercase", "capitalize", "border", "rounded", "shadow", "transition",
  "invisible", "visible", "isolate", "grow", "shrink", "flex-1", "resize", "outline", "ring", "blur", "filter", "backdrop-blur", "antialiased",
  "sr-only", "table", "list-none", "collapse"]);

function vendorCandidates(appRoot, req, inputs) {
  let extractor = null;
  try {
    const { defaultExtractor } = req("tailwindcss/lib/lib/defaultExtractor");
    extractor = defaultExtractor({ tailwindConfig: { separator: ":", prefix: "" } });
  } catch { return ""; }
  const seen = new Set();
  for (const rel of inputs) {
    if (!/\.(m?js|cjs|jsx|tsx?)$/.test(rel)) continue;
    let text;
    try { text = readFileSync(resolve(appRoot, rel), "utf8"); } catch { continue; }
    // Only modules that carry classes at all: React's internals mention
    // "className" as a prop name and yield half a million tokens of nothing.
    if (!/class(Name)?\s*[:=]\s*["'`{]/.test(text) && !/\bcn\(|\bcva\(|\btwMerge\(/.test(text)) continue;
    for (const tok of extractor(text)) {
      if (tok.length > 80 || seen.has(tok)) continue;
      if (/^[a-z!-][\w:./[\]%#()-]*$/.test(tok) && (/[-:[]/.test(tok) || BARE_UTILITIES.has(tok))) seen.add(tok);
    }
  }
  return [...seen].join(" ");
}

// ---------------------------------------------------------------------------
// page
// ---------------------------------------------------------------------------

async function buildPage({ appRoot, pageId, pageDir, route, access, entities, roles, params, searchParams, shimsDir, vendor }) {
  const { req, esbuild, shims } = prepare(appRoot, shimsDir, entities, roles);
  const work = join(appRoot, ".forge-jit", pageId);
  mkdirSync(work, { recursive: true });
  const specifiers = new Set((vendor && vendor.specifiers) || []);

  const isPublic = access === "public";
  const entry = join(work, "entry.tsx");
  writeFileSync(entry, entrySource({ pageDir, route, isPublic, entities, params, searchParams }));

  // Every vendor import becomes a read of the shared script's registry. The
  // shim is CommonJS on purpose: esbuild's interop then serves `default` and
  // named imports from the namespace object at runtime, which is the only way
  // a CommonJS package's names (React's) can be satisfied without knowing them.
  const vendorPlugin = {
    name: "forge-jit-vendor",
    setup(b) {
      b.onResolve({ filter: /.*/ }, (args) => {
        if (args.namespace === "forge-vendor" || !specifiers.has(args.path)) return null;
        return { path: args.path, namespace: "forge-vendor" };
      });
      b.onLoad({ filter: /.*/, namespace: "forge-vendor" }, (args) => ({
        loader: "js",
        contents: `var ns = (window.__forgeVendor || {})[${JSON.stringify(args.path)}];
if (!ns) throw new Error("The shared script is missing " + ${JSON.stringify(args.path)} + " — rebuild the preview.");
var out = { __esModule: true };
for (var k in ns) out[k] = ns[k];
if (!("default" in out)) out.default = ns;
module.exports = out;`,
      }));
    },
  };
  const tEs = Date.now();
  const result = await esbuild.build({ ...BASE_BUILD, absWorkingDir: appRoot, entryPoints: [entry], outfile: join(work, "bundle.js"),
    format: "iife", plugins: [shimPlugin(shims), vendorPlugin] });
  const js = (result.outputFiles.find((f) => f.path.endsWith("bundle.js")) ?? result.outputFiles[0])?.text ?? "";
  if (!js) throw new Error("esbuild produced no script");
  const inputs = Object.keys(result.metafile.inputs).filter((p) => !p.startsWith("<") && !p.startsWith("forge-vendor:"));
  const warnings = result.warnings.map((w) => w.text).slice(0, 10);
  const timings = { esbuildMs: Date.now() - tEs, tailwindMs: 0 };
  let css = "";
  const tTw = Date.now();
  try { css = await tailwind(appRoot, req, inputs, (vendor && vendor.candidates) || ""); }
  catch (e) { warnings.push("The page's styles could not be compiled: " + String(e && e.message || e).slice(0, 300)); }
  timings.tailwindMs = Date.now() - tTw;
  return { js, css, inputs: inputs.length, warnings, timings };
}

function entrySource({ pageDir, route, isPublic, entities, params, searchParams }) {
  const dir = pageDir.replace(/^src\//, "");
  return `
import React from "react";
import { createRoot } from "react-dom/client";
import { Toaster } from "sonner";
import { PageFrame } from "@/sdk/frame";
${isPublic ? 'import { PublicPageFrame } from "@/components/PublicPageFrame";' : ""}
import { load } from "@/${dir}/load";
import View from "@/${dir}/view";
import { currentUser } from "@/sdk/server";
import { installPreviewFetch } from "./../shims/preview-fetch";

const PARAMS: Record<string, string> = ${JSON.stringify(params || {})};
const SEARCH: Record<string, string | undefined> = ${JSON.stringify(searchParams || {})};
(window as any).__forgeParams = PARAMS;
(window as any).__forgeLocation = ${JSON.stringify(filledRoute(route, params, searchParams))};
installPreviewFetch();

class ErrorCatcher extends React.Component<{ children: React.ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(e: Error) { window.parent?.postMessage({ type: "forge-editor:error", payload: { message: e.message, file: "view.tsx", line: 0 } }, "*"); }
  render() {
    if (this.state.error) return <div style={{ padding: 24, fontFamily: "system-ui", color: "#991b1b" }}><b>This part could not load.</b><div style={{ marginTop: 6, fontSize: 13 }}>{this.state.error.message}</div></div>;
    return this.props.children;
  }
}

let root: ReturnType<typeof createRoot> | null = null;
async function render() {
  const host = document.getElementById("root")!;
  root = root ?? createRoot(host);
  const ctx = { params: PARAMS, searchParams: SEARCH, user: await currentUser() };
  let data: any;
  try { data = await load(ctx as any); }
  catch (e: any) {
    window.parent?.postMessage({ type: "forge-editor:error", payload: { message: "What this page loads failed: " + (e?.message ?? e), file: "load.ts", line: 0 } }, "*");
    data = {};
  }
  if (data === null) {
    root.render(<div style={{ padding: 24, fontFamily: "system-ui" }}><b>Not found.</b><div style={{ marginTop: 6, fontSize: 13, color: "#64748b" }}>This page shows one record and none matched — in the app this is the 404 page.</div></div>);
    return;
  }
  const page = <ErrorCatcher><View {...data} /></ErrorCatcher>;
  const framed = <PageFrame entities={${JSON.stringify((entities || []).map((e) => e.name))}}>{page}</PageFrame>;
  root.render(<>${isPublic ? "<PublicPageFrame>{framed}</PublicPageFrame>" : "{framed}"}<Toaster richColors position="bottom-right" /></>);
}
(window as any).__forgeRender = render;
render();
`;
}

function filledRoute(route, params, search) {
  const path = String(route || "/").replace(/\[([^\]]+)\]/g, (_, k) => encodeURIComponent((params || {})[k] ?? ""));
  const q = new URLSearchParams(Object.entries(search || {}).filter(([, v]) => v != null)).toString();
  return q ? `${path}?${q}` : path;
}

/** The app's own Tailwind (v3, postcss) over its globals, the page's files and the vendor's candidates. */
async function tailwind(appRoot, req, inputs, candidates) {
  const postcss = req("postcss");
  const tailwindcss = req("tailwindcss");
  let config = {};
  const cfgPath = ["tailwind.config.ts", "tailwind.config.js", "tailwind.config.mjs", "tailwind.config.cjs"].map((f) => join(appRoot, f)).find(existsSync);
  if (cfgPath) {
    try { config = req("tailwindcss/loadConfig")(cfgPath); } catch { config = {}; }
  }
  // The page's own files (the kit, the frame, the page) — node_modules never,
  // its classes come pre-extracted with the vendor script.
  const files = inputs.map((p) => resolve(appRoot, p)).filter((p) => /\.(tsx?|jsx?|mjs|cjs)$/.test(p) && !isVendorPath(p.slice(appRoot.length + 1)));
  const content = [...files, { raw: candidates || "", extension: "html" }];
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
export type QueryRow = Record<string, string | number | null>;
export interface WidgetData { rows: QueryRow[]; value: number | null }
export interface DateRange { from?: string; to?: string }
export type QueryOptions<E, M> = any; export type Measure<E> = any; export type Dimension<E> = any;
function bucketOf(v: any, bucket: string): string {
  const d = new Date(v);
  if (isNaN(d.getTime())) return String(v ?? "");
  const y = d.getUTCFullYear(), mo = d.getUTCMonth() + 1;
  if (bucket === "year") return String(y);
  if (bucket === "quarter") return y + "-Q" + (Math.floor((mo - 1) / 3) + 1);
  if (bucket === "month") return y + "-" + String(mo).padStart(2, "0");
  if (bucket === "week") { const t = new Date(Date.UTC(y, mo - 1, d.getUTCDate())); const day = t.getUTCDay() || 7; t.setUTCDate(t.getUTCDate() + 4 - day); const y0 = new Date(Date.UTC(t.getUTCFullYear(), 0, 1)); return t.getUTCFullYear() + "-W" + String(Math.ceil((((t.getTime() - y0.getTime()) / 86400000) + 1) / 7)).padStart(2, "0"); }
  return d.toISOString().slice(0, 10);
}
function aggregate(m: any, rows: any[]): number | null {
  const vals = rows.map((r) => r[m.field]).filter((v) => v !== null && v !== undefined);
  const nums = vals.map(Number).filter((n) => !isNaN(n));
  switch (m.aggregation) {
    case "count": return rows.length;
    case "count_distinct": return new Set(vals.map(String)).size;
    case "sum": return nums.reduce((a, b) => a + b, 0);
    case "avg": return nums.length ? Math.round((nums.reduce((a, b) => a + b, 0) / nums.length) * 100) / 100 : null;
    case "min": return nums.length ? Math.min(...nums) : null;
    case "max": return nums.length ? Math.max(...nums) : null;
  }
  return rows.length;
}
function runQuery(entity: string, q: { measures: any[]; dimensions?: any[]; where?: any; sort?: any; limit?: number }): QueryRow[] {
  const dims = (q.dimensions ?? []).map((d: any) => (typeof d === "string" ? { field: d } : d));
  const groups = new Map<string, { vals: any[]; rows: any[] }>();
  for (const r of filter(entity, { where: q.where })) {
    const vals = dims.map((d: any) => (d.bucket ? bucketOf(r[d.field], d.bucket) : r[d.field] ?? null));
    const k = JSON.stringify(vals);
    if (!groups.has(k)) groups.set(k, { vals, rows: [] });
    groups.get(k)!.rows.push(r);
  }
  let out: QueryRow[] = [...groups.values()].map(({ vals, rows }) => {
    const row: QueryRow = {};
    dims.forEach((d: any, i: number) => { row[d.field] = vals[i]; });
    for (const m of q.measures) row[m.key] = aggregate(m, rows);
    return row;
  });
  const bucketed = dims.find((d: any) => d.bucket);
  const by = q.sort?.by ?? (bucketed ? bucketed.field : q.measures[0]?.key);
  const order = q.sort?.order ?? (bucketed && !q.sort ? "asc" : "desc");
  if (by) out.sort((a, b) => ((a[by] ?? "") > (b[by] ?? "") ? 1 : (a[by] ?? "") < (b[by] ?? "") ? -1 : 0) * (order === "desc" ? -1 : 1));
  if (q.limit) out = out.slice(0, q.limit);
  return out;
}
/** Measures by dimensions over the sample rows — the shape the Data Engine returns. */
export async function query(entity: string, opts: any): Promise<QueryRow[]> {
  await wait();
  const measures = Object.entries(opts.measures ?? {}).map(([key, m]: [string, any]) => ({ key, aggregation: m.fn, field: m.field }));
  return runQuery(entity, { measures, dimensions: opts.dimensions, where: opts.where, sort: opts.sort, limit: opts.limit });
}
/** A widget as the Blueprint declares it, over the sample rows. */
export async function runWidget(widget: any, opts: any = {}): Promise<WidgetData> {
  await wait();
  const src = widget.source;
  if (src.op === "list") {
    const rows = await list(src.entity, { where: { ...src.filter, ...(opts.where ?? {}) }, sort: src.sort, order: "desc", limit: src.limit });
    return { rows, value: null };
  }
  const rows = runQuery(src.entity, { measures: src.measures, dimensions: src.dimensions, where: { ...src.filter, ...(opts.where ?? {}) }, sort: src.sort, limit: src.limit });
  const single = !src.dimensions?.length;
  const first = src.measures[0]?.key;
  return { rows, value: single && first ? Number(rows[0]?.[first] ?? 0) : null };
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
