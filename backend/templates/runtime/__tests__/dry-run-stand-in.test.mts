/**
 * The dry run's stand-in for an earlier step's output answers any path.
 *
 * It answered one level: `{{load_rental.rows[0].listingId}}` resolved to
 * nothing and the dry run refused a correct workflow (UAT, 2026-09-18).
 * Loads the real module — it has no imports — and walks paths the way the
 * engine's resolver does, dotted with bracket indices.
 * Run with: npx tsx templates/runtime/__tests__/dry-run-stand-in.test.mts
 */
// Loaded as CommonJS outside an app (no package.json here), so read the export
// through the namespace either way.
import * as standIn from "../workflows/dry-run-stand-in.ts";
const STEP_OUTPUT: unknown = (standIn as any).STEP_OUTPUT ?? (standIn as any).default?.STEP_OUTPUT;

function walk(root: unknown, path: string): unknown {
  const parts = path.split(".").flatMap((p) => {
    const m = /^([A-Za-z_$][\w$]*)((?:\[\d+\])*)$/.exec(p);
    if (!m) return [p];
    return [m[1], ...Array.from(m[2].matchAll(/\[(\d+)\]/g), (x) => Number(x[1]))];
  });
  return parts.reduce<any>((cur, p) => (cur == null ? undefined : cur[p as any]), root);
}

let failed = 0;
function check(label: string, ok: boolean) {
  if (ok) { console.log(`ok   ${label}`); } else { console.log(`FAIL ${label}`); failed++; }
}

const variables = { load_rental: STEP_OUTPUT };
for (const path of ["load_rental.id", "load_rental.rows[0].listingId",
                    "load_rental.rows[0].owner.email", "load_rental.count"]) {
  const v = walk(variables, path);
  check(`${path} is supplied, not empty`, v !== undefined && v !== null && String(v) !== "");
  check(`${path} reads as "dry-run"`, String(v) === "dry-run");
}
check("it interpolates as text", `${walk(variables, "load_rental.rows[0].listingId")}` === "dry-run");

if (failed) { console.log(`${failed} failed`); process.exit(1); }
console.log("all passed");
