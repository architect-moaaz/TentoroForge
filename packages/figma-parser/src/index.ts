#!/usr/bin/env node
import { parseJsxToSchema } from "./parse.js";
import { applyCodeConnect } from "./code-connect.js";

export { parseJsxToSchema } from "./parse.js";
export { tailwindToTokens } from "./tailwind-tokens.js";
export { applyCodeConnect } from "./code-connect.js";
export type { ParsedResult, SchemaNode } from "./types.js";

// CLI entry: only runs when executed directly
if (process.argv[1] && process.argv[1].endsWith("index.js")) {
  async function main() {
    const chunks: Buffer[] = [];
    for await (const c of process.stdin) chunks.push(c as Buffer);
    const input = JSON.parse(Buffer.concat(chunks).toString("utf8")) as {
      jsx?: string;
      codeConnect?: Record<string, { libraryName: string; propsTransform: string }>;
    };

    const result = parseJsxToSchema(input.jsx ?? "");

    if (input.codeConnect) {
      // propsTransform arrives as a serialized function string; we reconstruct it
      // In production use-cases code-connect mappings should be pre-resolved objects.
      // For subprocess CLI, we accept {libraryName, propsTransform: "identity"} or
      // a plain record of {libraryName} with no transform (identity assumed).
      const mappings: Parameters<typeof applyCodeConnect>[1] = {};
      for (const [key, val] of Object.entries(input.codeConnect)) {
        mappings[key] = {
          libraryName: val.libraryName,
          propsTransform: (p) => p, // identity for subprocess use
        };
      }
      result.schema.root = applyCodeConnect(result.schema.root, mappings);
    }

    process.stdout.write(JSON.stringify(result));
  }

  main().catch((e) => {
    process.stderr.write(String(e));
    process.exit(1);
  });
}
