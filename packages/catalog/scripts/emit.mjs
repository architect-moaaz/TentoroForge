/**
 * Emit the workflow node catalog to the two places that cannot reach this
 * package at build time: the backend image copies only `backend/`, and the
 * frontend bundles only `frontend/src`. Same seam as the Blueprint schema and
 * the component catalog — one source, generated copies, a test that fails on
 * drift (backend/tests/services/test_workflow_node_catalog.py).
 *
 *   npm run emit --workspace=packages/catalog
 */
import { copyFileSync } from "node:fs";
import { resolve } from "node:path";

const here = resolve(process.cwd());
const src = resolve(here, "workflow-nodes.json");
for (const out of [
  "../../backend/contracts/workflow-node-catalog.json",
  "../../frontend/src/catalog/workflow-nodes.json",
]) {
  copyFileSync(src, resolve(here, out));
  console.log(`wrote ${out}`);
}
