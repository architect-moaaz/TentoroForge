import { readFileSync } from "node:fs";
import { PageV2 } from "../schema/src/page";
import { starterRegistry } from "../registry/src/starter";

const file = process.argv[2];
const page = JSON.parse(readFileSync(file, "utf8"));
const r = PageV2.safeParse(page);
console.log("PageV2 whole-page parse:", r.success ? "OK" : "FAIL");
if (!r.success) {
  for (const i of r.error.issues.slice(0, 40)) console.log("   ", i.path.join("."), "-", i.message);
}
// per-node
function walk(n: any, out: any[]) { out.push(n); for (const c of n.children ?? []) walk(c, out); }
const nodes: any[] = []; walk(page.root, nodes);
console.log("\nper-node isolated PageV2 check (node as root of a minimal page):");
for (const n of nodes) {
  const p = { schemaVersion: "2", id: "t", route: "/t", meta: {}, dataSources: [], root: n };
  const rr = PageV2.safeParse(p);
  console.log(`  ${String(n.type).padEnd(20)} ${rr.success ? "OK" : "FAIL  " + rr.error.issues.slice(0,3).map((i:any)=>i.path.join(".")+": "+i.message).join(" | ")}`);
}
