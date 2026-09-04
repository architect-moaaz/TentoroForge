/**
 * Validate every projected page against the Page schema the generated app
 * actually loads. This is the regression signal for contract reconciliation:
 * it was 8/18 before the DescriptionList fixes and is 15/18 now.
 *
 *   node --experimental-transform-types --no-warnings \
 *     -r ../library/scripts/cjs-extensionless.cjs scripts/validate-projected-pages.mjs
 */
import { Page } from "/Users/m/Work/code/poc/convestation2app-forge-v1/packages/schema/dist/page.js";
import { readFileSync, readdirSync } from "node:fs";
const dir = "/private/tmp/claude-501/-Users-m-Work-code-poc-convestation2app-forge-v1/e08a3208-e925-48dc-ae15-5bd042432bbf/scratchpad/liverun/chain-app/src/schemas";
const walk = (d) => readdirSync(d, { withFileTypes: true }).flatMap((e) =>
  e.isDirectory() ? walk(`${d}/${e.name}`) : e.name.endsWith(".json") ? [`${d}/${e.name}`] : []);
let ok = 0; const bad = [];
for (const f of walk(dir)) {
  const r = Page.safeParse(JSON.parse(readFileSync(f, "utf8")));
  r.success ? ok++ : bad.push([f.split("/").pop(), r.error.errors[0]?.message?.slice(0, 70)]);
}
console.log(`Page strict-valid: ${ok} | invalid: ${bad.length}`);
bad.slice(0, 3).forEach(([n, m]) => console.log("  ", n, "->", m));
