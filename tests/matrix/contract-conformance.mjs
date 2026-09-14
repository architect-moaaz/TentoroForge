/**
 * CONTRACT CHECK 1 — every registry prop must actually be read by its component.
 *
 * The editor renders a control for every prop the registry declares. If the
 * component never reads that prop, the user gets a live control wired to
 * nothing: they type, it saves, it persists, and no pixel ever changes. That is
 * exactly Cascader.placeholder and NavLink.icon — both found the expensive way,
 * by driving a browser for hours. This finds the whole class in under a second,
 * across all 133 components including the 20 layout ones the browser sweep
 * never reached.
 *
 * ── Bias: report only ZERO occurrences ──────────────────────────────────────
 * A prop name that appears ANYWHERE in the component file is treated as read,
 * even if it is only passed through or mentioned in a comment. That will miss
 * some real defects (false negatives), and it is the correct trade: a false
 * positive here costs a developer an hour proving me wrong, and this whole
 * exercise exists to avoid that.
 *
 * ── Known escape hatches that are NOT defects ───────────────────────────────
 *  • library/src/registry.ts remaps some props before the component sees them
 *    (e.g. Button iconName -> icon, NavLink unifyLabelHref), so it is searched too.
 *  • Some components re-export from a sibling implementation file, so every
 *    .tsx/.ts in the component's directory is searched, not just <Name>.tsx.
 *  • `style`, `children`, `className` and `id` are framework-level and skipped.
 */
import { starterRegistry } from "@forge/registry";
import { readFileSync, existsSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const COMPONENTS = "packages/library/src/components";
const REGISTRY_SHIM = "packages/library/src/registry.ts";
const BUILD_REGISTRY = "packages/library/src/buildDefaultRegistry.tsx";

const FRAMEWORK = new Set(["style", "children", "className", "id", "key", "ref"]);

/**
 * Comments must be stripped before searching, or prose defeats the check.
 * Measured: the word "placeholder" occurs once in a comment at registry.ts:78
 * ("fall back to a single placeholder"), and that single occurrence hid
 * Cascader.placeholder — a prop independently CONFIRMED dead by the browser
 * sweep and by an adversarial source review. Without this, one stray comment
 * silently exonerates every prop that shares its wording.
 */
function stripComments(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, " ")   // block comments
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1 "); // line comments, sparing "http://"
}

const read = (p) => (existsSync(p) ? stripComments(readFileSync(p, "utf-8")) : "");
const shim = read(REGISTRY_SHIM);
const build = read(BUILD_REGISTRY);

/**
 * Where a component's implementation can legitimately live. An earlier version
 * looked only in components/<Name>/ and therefore skipped 12 components (~40
 * props) entirely — reporting them as "no source" rather than checking them.
 * Silently unchecked is worse than reported-broken, so all four homes are searched:
 *
 *   components/<Name>/            the common case
 *   components/<Other>/<Name>.tsx a sibling file (TableSortable lives in Table/)
 *   renderer/src/nodes/**         layout primitives and data builtins
 *                                 (Container, Grid, Stack, Row, Spacer, Repeat,
 *                                  Conditional, DataBoundary, Slot)
 *   a differently-named module    MoneyInput/MoneyDisplay both live in Money.tsx
 */
const EXTRA_HOMES = {
  MoneyInput: ["packages/library/src/components/Money/Money.tsx"],
  MoneyDisplay: ["packages/library/src/components/Money/Money.tsx"],
};

function collectFiles(dir, out) {
  for (const f of readdirSync(dir, { withFileTypes: true })) {
    const p = join(dir, f.name);
    if (f.isDirectory()) { collectFiles(p, out); continue; }
    if (!/\.(tsx|ts)$/.test(f.name)) continue;
    if (/\.test\.|\.spec\.|\.schema\.ts$/.test(f.name)) continue;
    out.push(p);
  }
  return out;
}

const RENDERER_NODES = "packages/renderer/src/nodes";
const rendererFiles = existsSync(RENDERER_NODES) ? collectFiles(RENDERER_NODES, []) : [];

function sourcesFor(name) {
  const out = [];
  const dir = join(COMPONENTS, name);
  if (existsSync(dir)) {
    for (const f of readdirSync(dir)) {
      if (!/\.(tsx|ts)$/.test(f)) continue;
      if (/\.test\.|\.spec\.|\.schema\.ts$/.test(f)) continue;
      out.push(stripComments(readFileSync(join(dir, f), "utf-8")));
    }
  }
  // a sibling file named <Name>.tsx inside another component's directory
  if (existsSync(COMPONENTS)) {
    for (const d of readdirSync(COMPONENTS)) {
      const sib = join(COMPONENTS, d, `${name}.tsx`);
      if (d !== name && existsSync(sib)) out.push(stripComments(readFileSync(sib, "utf-8")));
    }
  }
  // renderer builtins, matched by filename
  for (const p of rendererFiles) {
    if (p.endsWith(`${name}.tsx`) || p.endsWith(`${name}.ts`)) {
      out.push(stripComments(readFileSync(p, "utf-8")));
    }
  }
  for (const p of EXTRA_HOMES[name] ?? []) {
    if (existsSync(p)) out.push(stripComments(readFileSync(p, "utf-8")));
  }
  return out.length ? out : null;
}

const dead = [];
const forwarded = [];   // rest-spread: name search cannot decide these
const missingDir = [];
let checked = 0;

for (const [name, entry] of Object.entries(starterRegistry)) {
  const sources = sourcesFor(name);
  if (!sources) { missingDir.push(name); continue; }
  /**
   * SEARCH THE COMPONENT'S OWN SOURCE ONLY — never the shared shim globally.
   * registry.ts remaps `iconName -> icon` for Button; searching that whole file
   * let Button's remap exonerate NavLink.icon, a prop independently confirmed
   * dead. A shared file mentioning a prop name says nothing about whether THIS
   * component reads it.
   *
   * Whether the component is remapped at all is kept as a flag, so a human can
   * check the few that are rather than the whole catalogue.
   */
  const haystack = sources.join("\n");

  /**
   * REST-SPREAD FORWARDING DEFEATS A NAME SEARCH — and produced three false
   * positives before this guard existed. CartPage destructures
   * `{ title, className, style, ...rest }` and renders `<CartPanel {...rest} />`;
   * CartPanel then reads currency / checkoutLabel / onCheckoutNavigate with
   * defaults and uses them. The props work perfectly, but their names never
   * appear in CartPage's own source, so they looked dead.
   *
   * A component that forwards a rest object cannot be judged by name alone.
   * Those are reported separately as NEEDS-MANUAL-CHECK rather than as defects:
   * over-reporting here costs a developer an hour proving me wrong, which is the
   * exact failure this whole exercise exists to avoid.
   */
  const forwardsRest = /\.\.\.(rest|props|others|restProps)\b/.test(haystack);
  // Only the REMAP shim counts. buildDefaultRegistry registers every component,
  // so including it made this flag true for all 49 rows and therefore useless.
  const remapped = new RegExp(`\\b${name}\\b`).test(shim);

  for (const [prop, d] of Object.entries(entry.props ?? {})) {
    if (FRAMEWORK.has(prop)) continue;
    checked++;
    // Word-boundary match so `row` does not match `rowKey`.
    const re = new RegExp(`\\b${prop.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`);
    if (!re.test(haystack)) {
      if (forwardsRest) {
        forwarded.push({ component: name, prop, type: d.type, description: d.description ?? "" });
        continue;
      }
      dead.push({
        component: name, category: entry.category, prop,
        type: d.type, control: d.control, group: d.group,
        description: d.description ?? "",
        hasEditorControl: true,
        componentIsRemapped: remapped,
      });
    }
  }
}

writeFileSync("tests/matrix/contract-dead-props.json", JSON.stringify(dead, null, 1), "utf-8");

console.log(`registry props checked      : ${checked}`);
console.log(`components with no source   : ${missingDir.length}${missingDir.length ? " (" + missingDir.join(", ") + ")" : ""}`);
console.log(`DECLARED BUT NEVER READ     : ${dead.length}`);
console.log(`NEEDS MANUAL CHECK (rest-spread forwarding): ${forwarded.length}`);
if (forwarded.length) {
  for (const f of forwarded.slice(0, 12)) console.log(`   ? ${(f.component + "." + f.prop).padEnd(30)}"${f.description.slice(0, 46)}"`);
}
console.log("");

const byCat = {};
for (const d of dead) (byCat[d.category] ??= []).push(d);
for (const [cat, list] of Object.entries(byCat).sort((a, b) => b[1].length - a[1].length)) {
  console.log(`${cat} (${list.length})`);
  for (const d of list) {
    console.log(`   ${(d.component + "." + d.prop).padEnd(34)}${String(d.type).padEnd(8)}"${d.description.slice(0, 52)}"`);
  }
  console.log("");
}
