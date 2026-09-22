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
import { mkdirSync, readFileSync, writeFileSync, existsSync, copyFileSync, readdirSync, realpathSync, statSync } from "fs";
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

/** Libraries the vendored engine imports by package name that are not
 *  packages: they ship as loose files under the app's src/lib and Next's
 *  config aliases them (assembly.LOOSE_LIBS). Resolved the same way here, so a
 *  build does not depend on a node_modules above the app that happens to
 *  hold them. */
const LOOSE_LIBS = { "@tentoroforge/feel-lite": "src/lib/feel-lite" };

/** The resolutions every build shares: Next's modules and the server SDK go to the shims. */
function shimPlugin(shims, appRoot) {
  return {
    name: "forge-jit-shims",
    setup(b) {
      for (const [name, rel] of Object.entries(LOOSE_LIBS)) {
        const escaped = name.replace(/[/@.]/g, "\\$&");
        b.onResolve({ filter: new RegExp(`^${escaped}(/.*)?$`) }, (args) => ({ path: resolveLoose(join(appRoot, rel), args.path.slice(name.length)) }));
      }
      b.onResolve({ filter: /^next\/link$/ }, () => ({ path: join(shims, "link.tsx") }));
      b.onResolve({ filter: /^next\/navigation$/ }, () => ({ path: join(shims, "navigation.tsx") }));
      b.onResolve({ filter: /^next\/image$/ }, () => ({ path: join(shims, "image.tsx") }));
      b.onResolve({ filter: /^next-auth\/react$/ }, () => ({ path: join(shims, "next-auth.tsx") }));
      b.onResolve({ filter: /^next\/(headers|cache|server)$/ }, () => ({ path: join(shims, "empty.ts") }));
      b.onResolve({ filter: /^server-only$/ }, () => ({ path: join(shims, "empty.ts") }));
      b.onResolve({ filter: /^@\/sdk\/server$/ }, () => ({ path: join(shims, "sample-server.ts") }));
      b.onResolve({ filter: /^@\/(auth|lib\/data-engine|lib\/data-engine-bridge|lib\/data-init|db(\/.*)?)$/ }, () => ({ path: join(shims, "empty.ts") }));
      b.onResolve({ filter: /\.css$/ }, (args) => ({ path: args.path, namespace: "forge-css" }));
      b.onLoad({ filter: /.*/, namespace: "forge-css" }, () => ({ contents: "", loader: "js" }));
    },
  };
}

/** The file a loose library's specifier names: its index, or a file inside it. */
function resolveLoose(dir, sub) {
  const base = sub ? join(dir, sub) : dir;
  for (const c of [base, `${base}.ts`, `${base}.tsx`, join(base, "index.ts"), join(base, "index.tsx"), join(base, "index.js")]) {
    if (existsSync(c) && !statSync(c).isDirectory()) return c;
  }
  return base;
}

const BASE_BUILD = {
  bundle: true, write: false, platform: "browser", target: "es2020", jsx: "automatic", sourcemap: false,
  metafile: true, logLevel: "silent",
  define: { "process.env.NODE_ENV": '"development"', "process.env.NEXT_PUBLIC_BASE_PATH": '""', "process.env.NEXT_BASE_PATH": '""' },
  loader: { ".png": "dataurl", ".jpg": "dataurl", ".svg": "dataurl", ".woff2": "dataurl", ".woff": "dataurl" },
};

function isBare(spec) {
  return !/^(\.|\/|@\/|next\/|next-auth\/react$|server-only$)/.test(spec) && !spec.startsWith("forge-");
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
  const disc = await esbuild.build({ ...BASE_BUILD, absWorkingDir: appRoot, entryPoints: [probe], outfile: join(work, "probe.js"), plugins: [shimPlugin(shims, appRoot)] });
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
    format: "iife", minify: true, plugins: [shimPlugin(shims, appRoot)] });
  const js = (result.outputFiles.find((f) => f.path.endsWith("vendor.js")) ?? result.outputFiles[0])?.text ?? "";
  if (!js) throw new Error("esbuild produced no vendor script");

  // 3. The Tailwind class candidates the vendor modules contain, once.
  const tCand = Date.now();
  const inputs = Object.keys(result.metafile.inputs).filter((p) => !p.startsWith("<"));
  const candidates = vendorCandidates(appRoot, req, inputs);

  // A package's version names it — except a vendored one (`file:./vendor/…`),
  // which a platform cutover replaces under the same version; its entry
  // file's stamp tells those apart.
  const versions = list.map((s) => {
    const name = s.split("/").slice(0, s.startsWith("@") ? 2 : 1).join("/");
    try {
      const pj = req.resolve(`${name}/package.json`);
      const meta = req(pj);
      if (!/\/vendor\//.test(realpathSync(pj))) return meta.version;
      const st = statSync(join(dirname(realpathSync(pj)), meta.main || "package.json"));
      return `${meta.version}@${Math.round(st.mtimeMs)}:${st.size}`;
    } catch { return "?"; }
  });
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
    format: "iife", plugins: [shimPlugin(shims, appRoot), vendorPlugin] });
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

// A picture at a root-relative address lives in the app's public files. This
// frame is not the app, so it asks the editor for the file and shows what
// comes back.
(() => {
  const waiting = new Map<string, HTMLImageElement[]>();
  const ask = (img: HTMLImageElement) => {
    const s = img.getAttribute("src") || "";
    if (!s.startsWith("/") || s.startsWith("//") || s.startsWith("/api/") || img.dataset.forgeAsset === s) return;
    img.dataset.forgeAsset = s;
    if (!waiting.has(s)) { waiting.set(s, []); window.parent?.postMessage({ type: "forge-editor:asset", payload: { path: s } }, "*"); }
    waiting.get(s)!.push(img);
  };
  window.addEventListener("message", (e) => {
    const d = e.data;
    if (!d || d.type !== "forge-editor:asset-url" || !d.payload) return;
    for (const img of waiting.get(d.payload.path) || []) { if (d.payload.url) img.src = d.payload.url; }
    waiting.delete(d.payload.path);
  });
  const sweep = (root: ParentNode) => root.querySelectorAll?.("img").forEach((i) => ask(i as HTMLImageElement));
  new MutationObserver((muts) => {
    for (const m of muts) {
      if (m.type === "attributes" && (m.target as Element).tagName === "IMG") ask(m.target as HTMLImageElement);
      m.addedNodes.forEach((n) => { if (n.nodeType !== 1) return; if ((n as Element).tagName === "IMG") ask(n as HTMLImageElement); sweep(n as ParentNode); });
    }
  }).observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ["src"] });
  sweep(document);
})();

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

import { sampleServer, sampleRow } from "./jit-samples.mjs";

main();
