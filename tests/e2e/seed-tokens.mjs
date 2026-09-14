/**
 * Give the scratch project a token set so the Tokens tab has rows to drive.
 *
 * TokenEditor is data-driven: a group with no entries renders its legend and
 * nothing else. A bare scratch project therefore shows six section headers and
 * zero inputs — which is correct behaviour, not a defect, and the sweep rightly
 * recorded HARNESS-BLOCKED rather than reporting it.
 *
 * `radius.scale` is included deliberately: it is a STRING living in a group the
 * editor renders as input[type=number] with Number() coercion, which is the
 * known NaN candidate. Real projects already carry it.
 */
import { writeFileSync } from "node:fs";

const API = process.env.E2E_API ?? "http://localhost:6500";
const ID = process.env.E2E_SCRATCH ?? "e2e-scratch";
const REL = "src/theme/tokens.custom.json";

const tokens = {
  color: {
    primary: { "50": "#eef2ff", "500": "#3b82f6", "600": "#2563eb", "900": "#1e3a8a" },
    surface: { "0": "#ffffff", "1": "#f6f8fb" },
  },
  spacing: { "2": 8, "4": 16, "8": 48 },
  radius: { sm: 4, md: 10, lg: 28, scale: "soft" },
  typography: { fontFamily: { base: "Inter" }, scale: { body: 14, h1: 32 } },
  shadow: { sm: "0 1px 2px rgba(0,0,0,.2)", md: "0 4px 10px rgba(0,0,0,.3)" },
  motion: { fast: "120ms", slow: "400ms" },
};

const url = `${API}/api/_debug/project-file/${ID}/${REL}`;
const res = await fetch(url, {
  method: "POST",
  headers: { "content-type": "application/json" },
  body: JSON.stringify({ content: JSON.stringify(tokens, null, 2) }),
});
console.log(`POST ${REL} -> ${res.status}`);

const back = await fetch(url);
const d = back.ok ? await back.json() : null;
console.log(`GET  ${REL} -> ${back.status}`);
if (d) {
  const leaves = (o) => Object.values(o).reduce(
    (n, v) => n + (v && typeof v === "object" ? leaves(v) : 1), 0);
  console.log(`groups : ${Object.keys(d).join(", ")}`);
  console.log(`leaves : ${leaves(d)}`);
  console.log(`radius.scale (the NaN candidate) : ${JSON.stringify(d.radius?.scale)}`);
}
writeFileSync("tests/e2e/.auth/tokens-seeded.json", JSON.stringify(tokens), "utf-8");
