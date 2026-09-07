import { PageV2 } from "../schema/src/page.ts";
import fs from "node:fs";
const f = process.argv[2];
const page = JSON.parse(fs.readFileSync(f, "utf8"));
const r = PageV2.safeParse(page);
console.log(f, r.success ? "PASS" : "FAIL");
if (!r.success) for (const i of r.error.issues) console.log("   ", i.path.join("."), "::", i.message);
