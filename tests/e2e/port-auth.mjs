/**
 * Re-origin the saved session for a different port.
 *
 * Playwright's storageState keys localStorage by ORIGIN, and an origin includes
 * the port — so the session captured against :6501 does not authenticate :6701
 * even though it is the same host, the same user and the same backend. Cookies
 * are host-scoped and carry over; localStorage does not.
 *
 * This copies the existing origin's localStorage onto the target origin. It does
 * not mint, decode or print any credential — it only relabels where the browser
 * should present the one you already created by logging in yourself.
 *
 *   node tests/e2e/port-auth.mjs 6701
 */
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";

const port = process.argv[2] ?? "6701";
const SRC = resolve(process.cwd(), "tests/e2e/.auth/state.json");
const OUT = resolve(process.cwd(), `tests/e2e/.auth/state-${port}.json`);

if (!existsSync(SRC)) {
  console.error(`[port-auth] no saved session at ${SRC} — run save-auth.mjs first`);
  process.exit(1);
}

const state = JSON.parse(readFileSync(SRC, "utf-8"));
const target = `http://localhost:${port}`;
const origins = state.origins ?? [];

const donor = origins.find((o) => /^http:\/\/localhost:\d+$/.test(o.origin));
if (!donor) {
  console.error("[port-auth] no localhost origin with localStorage in the saved state.");
  console.error("[port-auth] origins present:", origins.map((o) => o.origin).join(", ") || "(none)");
  process.exit(1);
}

const already = origins.find((o) => o.origin === target);
if (already) already.localStorage = donor.localStorage;
else origins.push({ origin: target, localStorage: donor.localStorage });

state.origins = origins;
// Cookies are host-scoped, so they already apply across ports — left untouched.
writeFileSync(OUT, JSON.stringify(state), "utf-8");

console.log(`[port-auth] ${donor.origin} -> ${target}`);
console.log(`[port-auth] keys carried: ${donor.localStorage.length}`);
console.log(`[port-auth] wrote ${OUT}`);
