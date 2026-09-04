/**
 * Report where a component's props are defined twice and disagree.
 *
 * A component can have a strict node shape in this package *and* an
 * independently written props schema in the library. When those disagree the
 * failure is invisible in the worst way: the component renders correctly and
 * fails page validation, or passes validation and drops a prop at render.
 *
 * Direction matters, which is why this reports it. Where the registry knows
 * props the node lacks, deriving `XProps = XNode.shape.props` would *narrow*
 * the registry and delete capability the component genuinely has — so the node
 * has to be widened first, against the component, not against this diff.
 *
 * The registry's breadth is evidence, not proof: some of it is tolerate-and-
 * repair added because generated output kept arriving wrong (see the history of
 * DescriptionList's {label, value}). Unioning blindly cements those repairs
 * into the canonical shape, which is the opposite of the point.
 *
 *   node --experimental-transform-types --no-warnings \
 *     -r ../library/scripts/cjs-extensionless.cjs scripts/contract-drift.mjs [Name…]
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const schema = await import(path.join(here, "../dist/index.js"));
const cat = JSON.parse(
  readFileSync(path.join(here, "../../../backend/contracts/component-catalog.json"), "utf8"),
);
const registry = new Map(
  cat.components.map((c) => [c.name, Object.keys(c.props?.properties ?? {})]),
);

const only = process.argv.slice(2);
const rows = [];
for (const [name, regKeys] of registry) {
  if (only.length && !only.includes(name)) continue;
  const props = schema[`${name}Node`]?.shape?.props;
  const inner = props?._def?.innerType ?? props;
  const nodeKeys = Object.keys(inner?.shape ?? {});
  if (!nodeKeys.length) continue;           // no strict shape: open fallback, cannot drift
  const registryOnly = regKeys.filter((k) => !nodeKeys.includes(k));
  const nodeOnly = nodeKeys.filter((k) => !regKeys.includes(k));
  if (!registryOnly.length && !nodeOnly.length) continue;
  rows.push({ name, registryOnly, nodeOnly });
}

rows.sort((a, b) => b.registryOnly.length - a.registryOnly.length);
console.log(`${rows.length} component(s) defined twice and disagreeing\n`);
for (const r of rows) {
  console.log(r.name);
  if (r.registryOnly.length)
    console.log(`   node lacks : ${r.registryOnly.join(", ")}`);
  if (r.nodeOnly.length)
    console.log(`   registry lacks: ${r.nodeOnly.join(", ")}`);
}
