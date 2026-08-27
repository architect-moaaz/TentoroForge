/**
 * Post-build script: reads the compiled starterRegistry from dist/ and writes
 * a minimal props-only JSON snapshot to dist/starter.json.
 *
 * Consumed by backend/services/peer_patcher_helpers.py so the Python layer
 * stays in sync with the JS registry without manual maintenance.
 *
 * Run: node scripts/export.mjs  (after tsc has already produced dist/)
 */
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, resolve, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const pkgRoot = resolve(__dirname, "..");
const distDir = join(pkgRoot, "dist");

// Dynamic import of the compiled starter module. pathToFileURL is required —
// a bare Windows path ("C:\...\starter.js") is read as an unsupported "c:" URL
// scheme by the ESM loader.
const { starterRegistry } = await import(pathToFileURL(join(distDir, "starter.js")).href);

const outPath = join(distDir, "starter.json");
mkdirSync(distDir, { recursive: true });

// Reduce to props-only shape matching the Python _STARTER_REGISTRY format
const minimal = Object.fromEntries(
  Object.entries(starterRegistry).map(([name, entry]) => [
    name,
    {
      props: Object.fromEntries(
        Object.keys(entry.props).map((p) => [p, {}])
      ),
    },
  ])
);

writeFileSync(outPath, JSON.stringify(minimal, null, 2) + "\n");
console.log(`Wrote ${Object.keys(minimal).length} entries → ${outPath}`);
