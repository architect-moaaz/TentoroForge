/** What author-written intent exists that could serve as a spec? */
import { starterRegistry } from "@forge/registry";

let props = 0, withDesc = 0, compWithDesc = 0;
const samples = [];
for (const [name, e] of Object.entries(starterRegistry)) {
  if (e.description) compWithDesc++;
  for (const [p, d] of Object.entries(e.props ?? {})) {
    props++;
    if (d.description) {
      withDesc++;
      if (samples.length < 12) samples.push(`${name}.${p} — "${d.description}"`);
    }
  }
}
console.log(`components: ${Object.keys(starterRegistry).length}, with a description: ${compWithDesc}`);
console.log(`prop descriptors: ${props}, with a description: ${withDesc} (${Math.round(100 * withDesc / props)}%)`);
console.log("\nsamples of author-written prop intent:");
for (const s of samples) console.log("  ", s);
