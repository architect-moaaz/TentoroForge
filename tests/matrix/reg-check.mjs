/** Verify the registry is the real descriptor source, not the gutted starter.json shim. */
import { starterRegistry } from "@forge/registry";

const all = Object.values(starterRegistry);
const cats = {}, ctrls = {}, types = {}, groups = {};
let propTotal = 0, withOptions = 0;
const zeroProps = [];

for (const e of all) {
  cats[e.category] = (cats[e.category] ?? 0) + 1;
  const ps = Object.entries(e.props ?? {});
  if (!ps.length) zeroProps.push(e.name);
  for (const [, d] of ps) {
    propTotal++;
    ctrls[d.control] = (ctrls[d.control] ?? 0) + 1;
    types[d.type] = (types[d.type] ?? 0) + 1;
    groups[d.group] = (groups[d.group] ?? 0) + 1;
    if (Array.isArray(d.options)) withOptions++;
  }
}

console.log("entries:", all.length);
console.log("categories:", JSON.stringify(cats));
console.log("total prop descriptors:", propTotal);
console.log("controls:", JSON.stringify(ctrls));
console.log("types:", JSON.stringify(types));
console.log("groups:", JSON.stringify(groups));
console.log("enum props carrying options:", withOptions);
console.log("zero-prop components:", JSON.stringify(zeroProps));
console.log("any entry has `hidden`:", all.some((e) => "hidden" in e));
console.log("sample Button.label:", JSON.stringify(starterRegistry.Button?.props?.label));
console.log("sample slots (Container):", JSON.stringify(starterRegistry.Container?.slots));
