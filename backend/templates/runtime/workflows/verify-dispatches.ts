/**
 * Build-time verification of every control→workflow wire the app ships.
 *
 * Reads `src/contracts/dispatches.json` (written by the projection: each
 * control bound to a workflow and the payload it sends) and dry-runs each
 * through the real engine. Exit 1 with a report when any would refuse.
 *
 *   npx tsx src/lib/workflows/verify-dispatches.ts
 *
 * Run by the build (`assembly.verify_build`) after `next build`; a wire that
 * would refuse at first click refuses the build instead, with the control,
 * the workflow and the step named.
 */
import { promises as fs } from "fs";
import path from "path";
import { dryRunWorkflow, findWorkflow } from "./dry-run";

interface DispatchEntry {
  workflow: string;
  page: string;
  route: string;
  control: string;
  label: string;
  input: Record<string, unknown>;
}

async function main(): Promise<number> {
  const root = process.cwd();
  const manifest = path.join(root, "src/contracts/dispatches.json");
  let entries: DispatchEntry[] = [];
  try {
    entries = (JSON.parse(await fs.readFile(manifest, "utf8")).dispatches ?? []) as DispatchEntry[];
  } catch {
    console.log(JSON.stringify({ ok: true, checked: 0, skipped: "no dispatches manifest" }));
    return 0;
  }
  const results: any[] = [];
  let failed = 0;
  for (const d of entries) {
    const def = await findWorkflow(d.workflow);
    if (!def) {
      failed++;
      results.push({ ...d, ok: false, problems: [{ node: "-", actionType: "-", problem: `workflow ${d.workflow} is not in src/lib/workflows/definitions` }] });
      continue;
    }
    const r = dryRunWorkflow(def, d.input ?? {});
    if (!r.ok) failed++;
    results.push({ ...d, ok: r.ok, checked: r.checked, problems: r.problems });
  }
  const report = { ok: failed === 0, checked: entries.length, failed, results };
  try {
    await fs.mkdir(path.join(root, "contracts"), { recursive: true });
    await fs.writeFile(path.join(root, "contracts/dispatch-report.json"), JSON.stringify(report, null, 2));
  } catch { /* the report on stdout is the contract; the file is a courtesy */ }
  console.log(JSON.stringify(report));
  return failed === 0 ? 0 : 1;
}

main().then((code) => process.exit(code), (e) => { console.error(e); process.exit(2); });
