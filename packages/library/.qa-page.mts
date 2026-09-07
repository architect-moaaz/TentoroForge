import { PageV2 } from "@tentoroforge/schema";
import fs from "node:fs";
const p = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const r = PageV2.safeParse(p);
console.log(process.argv[2], r.success ? "PASS" : "FAIL");
if (!r.success) for (const i of r.error.issues.slice(0,25)) console.log("  " + i.path.join(".") + ": " + i.message);
