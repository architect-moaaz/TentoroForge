/**
 * Let Node resolve the workspace packages' extensionless dist imports.
 *
 * The sibling packages compile to ESM but emit extensionless relative imports
 * ("./SchemaRenderer"), which Node's ESM resolver rejects. The catalog emitter
 * has to load the library at run time to read the real registry, so those
 * imports must resolve — it never renders anything, it only reads each entry's
 * category, flags and Zod schema.
 *
 * Preloaded via `node -r`. Hooks both loaders and only intervenes on a
 * resolution failure, so a genuinely missing module still throws.
 */
const Module = require("node:module");
const { existsSync } = require("node:fs");
const path = require("node:path");
const { fileURLToPath, pathToFileURL } = require("node:url");

// Workspace sources are a mix of compiled dist (.js) and raw TypeScript;
// Node strips types natively, so both are loadable.
const CANDIDATES = (base) => [
  `${base}.js`, `${base}.ts`, `${base}.tsx`,
  path.join(base, "index.js"), path.join(base, "index.ts"),
];

// --- ESM (the workspace dist packages) -------------------------------------
Module.registerHooks({
  resolve(specifier, context, nextResolve) {
    try {
      return nextResolve(specifier, context);
    } catch (err) {
      if (!specifier.startsWith(".") || !context.parentURL) throw err;
      const base = path.resolve(
        path.dirname(fileURLToPath(context.parentURL)),
        specifier,
      );
      for (const candidate of CANDIDATES(base)) {
        if (existsSync(candidate)) {
          return { url: pathToFileURL(candidate).href, shortCircuit: true };
        }
      }
      throw err;
    }
  },
});

// --- CommonJS (the compiled emitter itself) --------------------------------
const original = Module._resolveFilename;
Module._resolveFilename = function (request, parent, ...rest) {
  try {
    return original.call(this, request, parent, ...rest);
  } catch (err) {
    if (!request.startsWith(".") || !parent || !parent.filename) throw err;
    const base = path.resolve(path.dirname(parent.filename), request);
    for (const candidate of CANDIDATES(base)) {
      if (existsSync(candidate)) return original.call(this, candidate, parent, ...rest);
    }
    throw err;
  }
};
