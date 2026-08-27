/**
 * Emit the component catalog — the set of components a pattern may use.
 *
 * A2UI authors pattern templates, and the only thing keeping it honest is
 * knowing exactly what exists. That knowledge already lives in the runtime
 * registry (`buildDefaultRegistry`): every entry carries a category, an
 * `acceptsChildren` flag and a Zod props schema. This script projects that
 * registry into JSON so the Python side can put it in a prompt and — more
 * importantly — validate what comes back without a Node toolchain.
 *
 *   npm run emit:catalog --workspace=packages/library
 *
 * Two details this captures that a bare prop list would lose:
 *
 * * **Composition semantics.** The library composes with positional
 *   `children`, not named slots — `SplitView` documents that "the first two
 *   children take the master/detail positions in order". That rule is in the
 *   schema file's doc comment and nowhere else, so the comment is part of the
 *   contract and is exported with the entry.
 * * **Variants.** Register-keyed looks (`Hero.linear`, `Card.workday`) are how
 *   an app differs visually without differing structurally. A pattern picks
 *   structure; the register picks the skin.
 *
 * The output is committed so the backend does not need Node to boot;
 * `test_component_catalog_is_current` fails if it drifts from the registry.
 */
import { writeFileSync, mkdirSync, readFileSync, readdirSync, existsSync } from "node:fs";
import { dirname, resolve, join } from "node:path";
import { zodToJsonSchema } from "zod-to-json-schema";
import { buildDefaultRegistry } from "../src/buildDefaultRegistry";
import * as schemaNodes from "@tentoroforge/schema";

const DEFAULT_OUT = "../../backend/contracts/component-catalog.json";
const out = resolve(process.cwd(), process.argv[2] ?? DEFAULT_OUT);

/** Doc comments keyed by the schema export they precede (`SplitViewProps`). */
function collectDocs(componentsDir: string): Record<string, string> {
  const docs: Record<string, string> = {};
  if (!existsSync(componentsDir)) return docs;
  for (const dir of readdirSync(componentsDir, { withFileTypes: true })) {
    if (!dir.isDirectory()) continue;
    const folder = join(componentsDir, dir.name);
    for (const file of readdirSync(folder)) {
      if (!file.endsWith(".schema.ts") && !file.endsWith(".tsx")) continue;
      const src = readFileSync(join(folder, file), "utf-8");
      // A /** */ block immediately preceding `export const <X>Props`.
      // The doc may sit above the Zod schema (`export const XProps`) or
      // above the component itself (`export function X`); both describe how
      // the thing composes, which is what A2UI needs.
      const re =
        /\/\*\*([\s\S]*?)\*\/\s*export (?:const (\w+)Props\b|function (\w+)\s*\()/g;
      for (let m = re.exec(src); m; m = re.exec(src)) {
        const text = m[1]
          .split("\n")
          .map((l) => l.replace(/^\s*\* ?/, "").trimEnd())
          .join("\n")
          .trim();
        const key = m[2] ?? m[3];
        if (text && key && !docs[key]) docs[key] = text;
      }
    }
  }
  return docs;
}

const docs = collectDocs(resolve(process.cwd(), "src/components"));
const registry = buildDefaultRegistry({});

/**
 * Nodes the renderer dispatches directly, without consulting the registry.
 *
 * `Stack`, `Row`, `Grid` and friends are handled by a switch in the renderer's
 * dispatch, so they never appear in `buildDefaultRegistry` — but they are the
 * layout vocabulary every pattern is built from. Omitting them from the
 * catalog would tell A2UI that `Stack` does not exist, which is how a template
 * ends up nesting Cards to get a column.
 *
 * `acceptsChildren` mirrors the dispatch: the containers pass `children`
 * through, the leaves do not.
 */
const STRUCTURAL: Array<[string, string, boolean]> = [
  ["Stack", "StackNode", true],
  ["Row", "RowNode", true],
  ["Grid", "GridNode", true],
  ["Container", "ContainerNode", true],
  ["Box", "BoxNode", true],
  ["Spacer", "SpacerNode", false],
  ["Text", "TextNode", false],
  ["Image", "ImageNode", false],
];

/** `*Node` schemas describe a whole node; the props live one level in. */
function propsOf(node: any): any {
  const inner = typeof node?.innerType === "function" ? node.innerType() : node;
  return inner?.shape?.props ?? null;
}

const structural = STRUCTURAL.flatMap(([name, exportName, acceptsChildren]) => {
  const props = propsOf((schemaNodes as any)[exportName]);
  if (!props) {
    console.warn(`structural node '${name}' has no ${exportName} schema — skipped`);
    return [];
  }
  let jsonProps: unknown;
  try {
    jsonProps = zodToJsonSchema(props, { $refStrategy: "none" });
  } catch {
    jsonProps = { type: "object", additionalProperties: true };
  }
  return [{
    name,
    category: "structural" as const,
    acceptsChildren,
    doc: "Renderer primitive — dispatched directly, not registered.",
    props: jsonProps,
  }];
});

const components = registry
  .list()
  .map((entry) => {
    let props: unknown;
    try {
      props = zodToJsonSchema(entry.propsSchema as any, { $refStrategy: "none" });
    } catch {
      // A schema that cannot be projected is still a real component; emit it
      // without props rather than dropping it from the catalog and letting
      // A2UI believe it does not exist.
      props = { type: "object", additionalProperties: true };
    }
    const doc = docs[entry.name];
    return {
      name: entry.name,
      category: entry.category,
      acceptsChildren: entry.acceptsChildren,
      ...(doc ? { doc } : {}),
      ...(entry.childContract ? { childContract: entry.childContract } : {}),
      ...(entry.variants ? { variants: Object.keys(entry.variants) } : {}),
      props,
    };
  })
  .concat(structural as any)
  .sort((a, b) => a.name.localeCompare(b.name));

const byCategory: Record<string, number> = {};
for (const c of components) byCategory[c.category] = (byCategory[c.category] ?? 0) + 1;

const catalog = {
  $comment:
    "Generated from packages/library/src/buildDefaultRegistry.tsx by " +
    "scripts/emit-catalog.ts. Do not edit by hand.",
  catalogVersion: 1,
  // Composition is positional: a container renders node.children in order.
  // Node-level `slots` is inert in the renderer; page-level `slots` fills a
  // LayoutTemplate's named holes and is a layout concern, not a pattern one.
  composition: "children",
  counts: { total: components.length, byCategory },
  components,
};

mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, JSON.stringify(catalog, null, 2) + "\n", "utf-8");
console.log(`wrote ${out} — ${components.length} components`);
