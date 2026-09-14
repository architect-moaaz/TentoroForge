/**
 * Blast-radius check before making Container/Grid props live.
 *
 * Every one of the dead props has a non-undefined registry default, and
 * buildDroppedNode seeds defaults onto dropped nodes. If real page schemas on
 * disk already carry those values, then implementing the props does not "add a
 * capability" — it silently changes the layout of every existing app.
 *
 * Measure before changing.
 */
import { readFileSync, existsSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const OUT = "C:/Users/user/a2ui/TentoroForge/output";
const WATCH = { Container: ["direction", "gap", "padding", "align", "justify", "wrap"],
                Grid: ["rowGap", "columnGap", "padding", "align"] };

const files = [];
function walk(d, depth = 0) {
  if (depth > 6 || !existsSync(d)) return;
  for (const f of readdirSync(d)) {
    const p = join(d, f);
    let s; try { s = statSync(p); } catch { continue; }
    if (s.isDirectory()) { if (!/node_modules|\.next|\.git/.test(f)) walk(p, depth + 1); }
    else if (f.endsWith(".json") && p.includes("schemas")) files.push(p);
  }
}
walk(OUT);

const tally = { Container: { total: 0, withProps: 0, props: {} },
                Grid: { total: 0, withProps: 0, props: {} } };

function visit(n) {
  if (!n || typeof n !== "object") return;
  const t = n.type;
  if (WATCH[t]) {
    tally[t].total++;
    const ps = n.props ?? {};
    let any = false;
    for (const k of WATCH[t]) {
      if (ps[k] !== undefined) { any = true; tally[t].props[k] = (tally[t].props[k] ?? 0) + 1; }
    }
    if (any) tally[t].withProps++;
  }
  for (const ch of (n.children ?? [])) visit(ch);
  for (const arr of Object.values(n.slots ?? {})) if (Array.isArray(arr)) arr.forEach(visit);
}

let parsed = 0;
for (const p of files) {
  let doc; try { doc = JSON.parse(readFileSync(p, "utf-8")); } catch { continue; }
  parsed++;
  if (doc.root) visit(doc.root);
}

console.log(`page schema files parsed: ${parsed}`);
for (const [t, v] of Object.entries(tally)) {
  console.log(`\n${t}: ${v.total} nodes on disk`);
  console.log(`   carrying at least one of the dead props: ${v.withProps}`);
  if (v.total) console.log(`   -> ${Math.round(100 * v.withProps / v.total)}% would change if the props go live`);
  for (const [k, n] of Object.entries(v.props)) console.log(`      ${k.padEnd(11)} set on ${n}`);
}
