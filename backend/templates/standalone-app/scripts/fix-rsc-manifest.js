#!/usr/bin/env node
/**
 * Backfill missing `page_client-reference-manifest.js` files after
 * `next build`.
 *
 * Bug: Next.js 15 App Router intermittently fails to emit this manifest
 * for `page.tsx` files that live at the root of a route group like
 * `(dashboard)/page.tsx` — even though the page compiles fine. Two
 * different failure modes fall out of that:
 *
 *   (a) Vercel's post-build file tracer lstat()s the missing path and
 *       throws ENOENT, killing the deploy. Fixed here by ensuring a
 *       file exists at the expected path.
 *   (b) At runtime, Next reads the manifest to resolve client-component
 *       references. If the file is present but its clientModules are
 *       empty (an early version of this script wrote a bare stub), the
 *       page throws `InvariantError: Expected clientReferenceManifest
 *       to be defined` for any page that has any client children.
 *
 * See vercel/next.js#58272 and duplicates.
 *
 * Fix: for each `page.js` missing its sibling manifest, CLONE a real
 * manifest from any sibling page that has one, rewriting only the top-
 * level global key so this page's runtime lookup hits it. All pages in
 * a Next build share the same client-module graph, so the cloned
 * `clientModules` etc. resolve correctly for the cloned page too.
 *
 * If no page in the build has a manifest at all (fully broken build),
 * we fall back to writing a minimal empty stub — that at least gets
 * past Vercel's tracer, matching the pre-clone behaviour.
 *
 * Idempotent — running twice is a no-op.
 */

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(process.cwd(), ".next", "server", "app");

function collectPages(dir, out) {
  if (!fs.existsSync(dir)) return;
  const entries = fs.readdirSync(dir, { withFileTypes: true });
  for (const entry of entries) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      collectPages(full, out);
    } else if (entry.name === "page.js") {
      const manifest = path.join(dir, "page_client-reference-manifest.js");
      out.push({ dir, manifestPath: manifest, hasManifest: fs.existsSync(manifest) });
    }
  }
}

function pageKey(pageDir) {
  const rel = path.relative(ROOT, pageDir).split(path.sep).join("/");
  return "app/" + (rel ? rel + "/" : "") + "page";
}

// Extract the JSON body from a real Next-emitted manifest file. The
// file's shape is:
//   globalThis.__RSC_MANIFEST=(globalThis.__RSC_MANIFEST||{});
//   globalThis.__RSC_MANIFEST["app/foo/page"]={ ... };
// We want just the "{ ... }" part so we can re-emit it under a
// different key.
function extractManifestBody(text) {
  // Match the last "= { ... };" — the module may register more than
  // one entry (with route groups) but the payload we care about is the
  // one being assigned; take the outermost object literal after the
  // last "]=".
  const marker = "]=";
  const idx = text.lastIndexOf(marker);
  if (idx === -1) return null;
  const start = text.indexOf("{", idx);
  if (start === -1) return null;
  // Balanced brace walk — string-literal-aware so we don't get tripped
  // by "}" inside a string value.
  let depth = 0;
  let inStr = false;
  let strCh = "";
  let esc = false;
  for (let i = start; i < text.length; i++) {
    const ch = text[i];
    if (inStr) {
      if (esc) { esc = false; continue; }
      if (ch === "\\") { esc = true; continue; }
      if (ch === strCh) inStr = false;
      continue;
    }
    if (ch === '"' || ch === "'") { inStr = true; strCh = ch; continue; }
    if (ch === "{") depth++;
    else if (ch === "}") {
      depth--;
      if (depth === 0) return text.slice(start, i + 1);
    }
  }
  return null;
}

function findDonor(pages) {
  // Prefer donors that AREN'T themselves in a route group — they're
  // more likely to have a canonical, well-populated manifest.
  const canonical = pages.filter(
    (p) => p.hasManifest && !path.relative(ROOT, p.dir).includes("("),
  );
  if (canonical.length) return canonical[0];
  return pages.find((p) => p.hasManifest) || null;
}

function emptyStub(key) {
  return (
    "globalThis.__RSC_MANIFEST=(globalThis.__RSC_MANIFEST||{});" +
    "globalThis.__RSC_MANIFEST[" + JSON.stringify(key) + "]=" +
    '{"moduleLoading":{"prefix":"/_next/","crossOrigin":null},' +
    '"clientModules":{},"entryCSSFiles":{},"ssrModuleMapping":{},' +
    '"edgeSSRModuleMapping":{},"rscModuleMapping":{},' +
    '"edgeRscModuleMapping":{}};\n'
  );
}

const pages = [];
collectPages(ROOT, pages);

const missing = pages.filter((p) => !p.hasManifest);
if (missing.length === 0) {
  console.log("[fix-rsc-manifest] no missing manifests");
  process.exit(0);
}

const donor = findDonor(pages);
let donorBody = null;
if (donor) {
  const donorText = fs.readFileSync(donor.manifestPath, "utf8");
  donorBody = extractManifestBody(donorText);
}

const cloned = [];
const stubbed = [];
for (const p of missing) {
  const key = pageKey(p.dir);
  let out;
  if (donorBody) {
    out =
      "globalThis.__RSC_MANIFEST=(globalThis.__RSC_MANIFEST||{});" +
      "globalThis.__RSC_MANIFEST[" + JSON.stringify(key) + "]=" +
      donorBody + ";\n";
    cloned.push(path.relative(process.cwd(), p.manifestPath));
  } else {
    out = emptyStub(key);
    stubbed.push(path.relative(process.cwd(), p.manifestPath));
  }
  fs.writeFileSync(p.manifestPath, out);
}

if (cloned.length) {
  console.log(
    "[fix-rsc-manifest] cloned " + cloned.length + " manifest(s) from " +
    path.relative(process.cwd(), donor.manifestPath) + ":",
  );
  for (const p of cloned) console.log("  - " + p);
}
if (stubbed.length) {
  console.log(
    "[fix-rsc-manifest] wrote empty stub for " + stubbed.length +
    " manifest(s) (no donor available):",
  );
  for (const p of stubbed) console.log("  - " + p);
}
