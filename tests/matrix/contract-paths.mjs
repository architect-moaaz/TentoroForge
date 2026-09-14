/**
 * CONTRACT CHECK 2 — every key the editor can WRITE must have a READER.
 * CONTRACT CHECK 3 — the stored VALUE TYPE must match what the editor renders.
 *
 * These two catch the bug class that check 1 cannot: check 1 asks "does the
 * component read this prop", these ask "do the two ends of a path agree at all".
 *
 * Both are modelled on real defects already confirmed here:
 *   • Design System wrote tokens.system.{density,elevation,radiusScale} — a
 *     group with no reader anywhere. Check 2's shape.
 *   • radius.scale holds the STRING "soft", but TokenEditor renders every
 *     tokens.radius.* row as input[type=number] and writes Number(value) → NaN.
 *     Check 3's shape.
 *
 * Key sets are EXTRACTED FROM SOURCE, not hardcoded, so the check cannot drift
 * from the code it is auditing.
 */
import { readFileSync, existsSync } from "node:fs";

const STYLE_PANEL = "frontend/src/components/properties/StylePanel.tsx";
const STYLE_SLOT_APPLY = "packages/renderer/src/runtime/style-slot.ts";
const RESOLVE_STYLE = "packages/renderer/src/runtime/tokens.ts";
const STYLE_SLOT_SCHEMA = "packages/schema/src/style-slot.ts";
const TOKEN_EDITOR = "frontend/src/components/editor/TokenEditor.tsx";

const read = (p) => (existsSync(p) ? readFileSync(p, "utf-8") : "");

// ---------------------------------------------------------------- CHECK 2 ---
console.log("=".repeat(64));
console.log("CHECK 2 — style keys the panel writes vs keys anything reads");
console.log("=".repeat(64));

const panel = read(STYLE_PANEL);
// writeStyle("<key>", …) and styleKey: "<key>"
const written = new Set();
for (const m of panel.matchAll(/writeStyle\(\s*["'`]([A-Za-z]+)["'`]/g)) written.add(m[1]);
for (const m of panel.matchAll(/styleKey:\s*["'`]([A-Za-z]+)["'`]/g)) written.add(m[1]);
// SizeField label -> key pairs: onCommit={(v) => writeStyle("width", v)}
console.log(`panel can write (${written.size}): ${[...written].sort().join(", ")}`);

const applySrc = read(STYLE_SLOT_APPLY);
const readBySlot = new Set();
for (const m of applySrc.matchAll(/slot\.([A-Za-z]+)/g)) readBySlot.add(m[1]);

const resolveSrc = read(RESOLVE_STYLE);
const readByResolve = new Set();
// STYLE_KEY_TO_CSS map keys
const mapBlock = resolveSrc.match(/STYLE_KEY_TO_CSS[^{]*\{([\s\S]*?)\n\}/);
if (mapBlock) {
  for (const m of mapBlock[1].matchAll(/^\s*([A-Za-z]+)\s*:/gm)) readByResolve.add(m[1]);
}
const readers = new Set([...readBySlot, ...readByResolve]);
console.log(`applyStyleSlot reads (${readBySlot.size}): ${[...readBySlot].sort().join(", ")}`);
console.log(`resolveStyle reads  (${readByResolve.size}): ${[...readByResolve].sort().join(", ")}`);

const orphanWrites = [...written].filter((k) => !readers.has(k));
console.log("");
console.log(`WRITTEN BUT NEVER READ: ${orphanWrites.length}  ${orphanWrites.join(", ") || "(none)"}`);

const schemaSrc = read(STYLE_SLOT_SCHEMA);
const schemaKeys = new Set();
const sBlock = schemaSrc.match(/StyleSlot\w*\s*=\s*z\.object\(\{([\s\S]*?)\n\}\)/);
if (sBlock) for (const m of sBlock[1].matchAll(/^\s*([A-Za-z]+)\s*:/gm)) schemaKeys.add(m[1]);
const unreachable = [...schemaKeys].filter((k) => !written.has(k) && readers.has(k));
console.log(`SCHEMA+READER SUPPORTS but the panel offers NO control: ${unreachable.length}  ${unreachable.join(", ") || "(none)"}`);

// ---------------------------------------------------------------- CHECK 3 ---
console.log("");
console.log("=".repeat(64));
console.log("CHECK 3 — stored token value type vs the input the editor renders");
console.log("=".repeat(64));

const te = read(TOKEN_EDITOR);
// FlatSection/TypographySection calls carry valueType="number" | "text"
const groupInput = {};
for (const m of te.matchAll(/title=\{?["'`](\w+)["'`][\s\S]{0,400}?valueType=["'`](\w+)["'`]/g)) {
  groupInput[m[1].toLowerCase()] = m[2];
}
for (const m of te.matchAll(/path=\{\["(\w+)"\][\s\S]{0,200}?valueType=["'`](\w+)["'`]/g)) {
  groupInput[m[1].toLowerCase()] = m[2];
}
console.log(`editor renders per group: ${JSON.stringify(groupInput)}`);
const coerced = new Set();
for (const m of te.matchAll(/path=\{\["(\w+)"\][\s\S]{0,300}?Number\(value\)/g)) coerced.add(m[1]);
console.log(`groups coerced with Number(value): ${[...coerced].join(", ") || "(none)"}`);

// Compare against tokens actually on disk in real projects.
import { readdirSync } from "node:fs";
const OUT = "C:/Users/user/a2ui/TentoroForge/output";
const conflicts = [];
let scanned = 0;
if (existsSync(OUT)) {
  for (const proj of readdirSync(OUT)) {
    for (const rel of ["src/theme/tokens.custom.json", "app/src/theme/tokens.custom.json"]) {
      const p = `${OUT}/${proj}/${rel}`;
      if (!existsSync(p)) continue;
      scanned++;
      let doc; try { doc = JSON.parse(readFileSync(p, "utf-8")); } catch { continue; }
      for (const [group, vals] of Object.entries(doc)) {
        if (!vals || typeof vals !== "object") continue;
        const expects = groupInput[group.toLowerCase()];
        if (expects !== "number") continue;
        for (const [name, v] of Object.entries(vals)) {
          if (typeof v === "object") continue;
          if (typeof v !== "number" && Number.isNaN(Number(v))) {
            conflicts.push({ project: proj, path: `${group}.${name}`, value: v,
                             rendered: "input[type=number]", coercesTo: "NaN" });
          }
        }
      }
    }
  }
}
console.log("");
console.log(`real token files scanned: ${scanned}`);
console.log(`TYPE CONFLICTS (edit in the Tokens tab yields NaN): ${conflicts.length}`);
for (const c of conflicts) {
  console.log(`   ${c.project}  ${c.path} = ${JSON.stringify(c.value)}  ->  Number() = NaN`);
}
