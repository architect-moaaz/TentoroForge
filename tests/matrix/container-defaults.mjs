import { starterRegistry } from "@forge/registry";
for (const n of ["Container", "Grid"]) {
  console.log(`${n}:`);
  for (const [p, d] of Object.entries(starterRegistry[n].props)) {
    console.log(`   ${p.padEnd(12)} default=${JSON.stringify(d.default)}  ${d.options ? "options=" + d.options.join("|") : ""}`);
  }
}
