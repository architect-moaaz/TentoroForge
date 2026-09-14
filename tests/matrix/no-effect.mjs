/**
 * Pair every NO-EFFECT measurement with its AUTHOR-WRITTEN description.
 *
 * The description is the only non-circular spec available: written by the team
 * as intent, independent of the implementation. Classifying from it — blind to
 * the code — is what separates "this control is broken" from "this prop was
 * never meant to be visible". Deriving the expectation by reading the component
 * instead would pass by construction and prove nothing.
 */
import { starterRegistry } from "@forge/registry";
import { readFileSync, writeFileSync } from "node:fs";

const d = JSON.parse(readFileSync("tests/e2e/sweep-props.json", "utf-8"));
const no = d.rows.filter((r) => r.status === "NO-EFFECT");

const out = no.map((r) => ({
  component: r.component,
  prop: r.prop,
  type: r.type,
  control: r.control,
  group: r.group,
  description: starterRegistry[r.component]?.props?.[r.prop]?.description ?? "",
}));

writeFileSync("tests/e2e/no-effect.json", JSON.stringify(out, null, 1), "utf-8");

console.log(`NO-EFFECT props   : ${out.length}`);
console.log(`with a description: ${out.filter((o) => o.description).length}`);
const byType = {};
for (const o of out) byType[o.type] = (byType[o.type] ?? 0) + 1;
console.log(`by type           : ${JSON.stringify(byType)}`);
console.log("");
for (const o of out.slice(0, 16)) {
  console.log(`  ${(o.component + "." + o.prop).padEnd(30)}${String(o.type).padEnd(9)}"${o.description.slice(0, 62)}"`);
}
