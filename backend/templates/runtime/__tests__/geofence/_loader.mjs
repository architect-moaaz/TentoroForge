// Lets the shipped files (which import "./engine" without an extension) run under plain node. Works on Node 20.6+.
import { existsSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, resolve as resolvePath } from "node:path";

export async function resolve(specifier, context, nextResolve) {
  if (specifier.startsWith(".") && context.parentURL && !/\.[mc]?[tj]s$/.test(specifier)) {
    const base = resolvePath(dirname(fileURLToPath(context.parentURL)), specifier);
    for (const ext of [".ts", "/index.ts"]) if (existsSync(base + ext)) return { url: pathToFileURL(base + ext).href, shortCircuit: true };
  }
  return nextResolve(specifier, context);
}
