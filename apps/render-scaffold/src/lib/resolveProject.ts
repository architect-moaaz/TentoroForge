import fs from "node:fs";
import path from "node:path";

const OUTPUT_ROOT = process.env.OUTPUT_ROOT
  ?? path.resolve(process.cwd(), "..", "..", "output");

/**
 * The directory that actually holds the generated application.
 *
 * TWO LAYOUTS, ONE ANSWER. The Blueprint engine projects the app BESIDE the
 * Blueprint it comes from — `generate_via_blueprint` sets
 * `app_root = output/<id>/app`, so schemas land in `output/<id>/app/src/schemas`.
 * This resolver returned `output/<id>`, so every preview looked for
 * `output/<id>/src/schemas/<route>.json`, found nothing, and rendered 404 —
 * for every app built by the Blueprint engine, not just one. Older projects
 * that were projected straight into `output/<id>` still resolve there.
 *
 * Probed on `src`, not on `app` alone: `output/<id>/app` can exist as a
 * template floor before anything is projected into it, and an empty app dir
 * is not where the schemas are.
 */
export function resolveProject(projectId: string): string {
  if (!projectId) throw new Error("invalid project id: empty");
  if (projectId.includes("/") || projectId.includes("..") || projectId.startsWith(".")) {
    throw new Error(`invalid project id: ${projectId}`);
  }
  const root = path.join(OUTPUT_ROOT, projectId);
  const nested = path.join(root, "app");
  if (fs.existsSync(path.join(nested, "src", "schemas"))) return nested;
  return root;
}
