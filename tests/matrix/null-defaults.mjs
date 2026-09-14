/** How many registry props default to null? Those are the bindProp crash set. */
import { starterRegistry } from "@forge/registry";

const nulls = [];
for (const [name, e] of Object.entries(starterRegistry)) {
  for (const [p, d] of Object.entries(e.props ?? {})) {
    if (d.default === null) nulls.push(`${name}.${p} (type=${d.type}, control=${d.control})`);
  }
}
console.log(`props whose registry default is null: ${nulls.length}`);
for (const n of nulls) console.log("  ", n);
