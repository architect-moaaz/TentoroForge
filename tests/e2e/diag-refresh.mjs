/**
 * Is the refresh token actually usable?
 *
 * Access tokens live 60 min (config.py:31); refresh tokens live 7 days (:32).
 * The editor nonetheless bounced to /login with 401 on BOTH /auth/me and
 * /auth/refresh. If refresh genuinely fails while the refresh token is still
 * inside its 7-day window, that is a product defect — every user would be
 * logged out hourly. This distinguishes "my saved state is stale" from
 * "refresh is broken".
 *
 * Prints statuses and error bodies only. No token value is ever printed.
 */
import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";

const API = process.env.E2E_API ?? "http://localhost:6500";
const STATE = resolve(process.cwd(), "tests/e2e/.auth/state.json");
if (!existsSync(STATE)) { console.error("no saved state"); process.exit(1); }

const state = JSON.parse(readFileSync(STATE, "utf-8"));
const origin = (state.origins ?? []).find((o) => /localhost/.test(o.origin));
const ls = Object.fromEntries((origin?.localStorage ?? []).map((e) => [e.name, e.value]));

const access = ls.token;
const refresh = ls.refresh_token;
console.log(`origin           : ${origin?.origin}`);
console.log(`access present   : ${!!access} (${access ? access.length : 0} chars)`);
console.log(`refresh present  : ${!!refresh} (${refresh ? refresh.length : 0} chars)`);

/** Decode a JWT's exp without verifying — read-only inspection. */
function expOf(jwt) {
  try {
    const p = JSON.parse(Buffer.from(jwt.split(".")[1], "base64").toString("utf-8"));
    return p.exp ? new Date(p.exp * 1000).toISOString() : "(no exp)";
  } catch { return "(unparseable)"; }
}
if (access) console.log(`access expires   : ${expOf(access)}`);
if (refresh) console.log(`refresh expires  : ${expOf(refresh)}`);
console.log(`now              : ${new Date().toISOString()}`);

const me = await fetch(`${API}/api/auth/me`, { headers: { Authorization: `Bearer ${access}` } });
console.log(`\nGET  /api/auth/me      -> ${me.status}`);

// Try the shapes the client might use; report each without assuming one.
for (const [label, init] of [
  ["body {refresh_token}", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ refresh_token: refresh }) }],
  ["body {refreshToken}", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ refreshToken: refresh }) }],
  ["bearer refresh", { method: "POST", headers: { Authorization: `Bearer ${refresh}` } }],
]) {
  const r = await fetch(`${API}/api/auth/refresh`, init);
  const t = (await r.text()).slice(0, 160).replace(/\s+/g, " ");
  console.log(`POST /api/auth/refresh (${label}) -> ${r.status}  ${t}`);
}
