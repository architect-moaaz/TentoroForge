/**
 * Emit the Living Blueprint JSON Schema for the Python side.
 *
 * The Blueprint is authored once in Zod (PRD §11). Python owns Blueprint
 * mutation (§116) and must validate what it writes — but re-declaring the
 * schema in Python would give two definitions that drift. So this script is
 * the seam: one source, one generated contract.
 *
 *   npm run emit:blueprint-schema --workspace=packages/schema
 *
 * The output is committed so the backend does not need a Node toolchain to
 * boot; `test_blueprint_schema_is_current` fails if it drifts from the Zod
 * source.
 *
 * Paths are resolved from the process cwd (the package directory, when run via
 * npm) rather than from the module's own location — `import.meta.url` is
 * unavailable under the CommonJS compile this runs through, and the package's
 * normal ESM `dist` output uses extensionless imports that bare Node cannot
 * resolve.
 */
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { blueprintJsonSchema, BLUEPRINT_SCHEMA_VERSION } from "../src/blueprint/index";

const DEFAULT_OUT = "../../backend/contracts/blueprint.schema.json";
const out = resolve(process.cwd(), process.argv[2] ?? DEFAULT_OUT);

const schema = {
  $schema: "http://json-schema.org/draft-07/schema#",
  $comment:
    "Generated from packages/schema/src/blueprint by scripts/emit-blueprint-schema.ts. " +
    `Do not edit by hand. Blueprint schema version ${BLUEPRINT_SCHEMA_VERSION}.`,
  ...blueprintJsonSchema(),
};

mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, JSON.stringify(schema, null, 2) + "\n", "utf-8");
console.log(`wrote ${out}`);
