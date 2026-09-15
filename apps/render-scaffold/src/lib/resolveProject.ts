import { existsSync } from "node:fs";
import path from "node:path";

const OUTPUT_ROOT = process.env.OUTPUT_ROOT
  ?? path.resolve(process.cwd(), "..", "..", "output");

export function resolveProject(projectId: string): string {
  if (!projectId) throw new Error("invalid project id: empty");
  if (projectId.includes("/") || projectId.includes("..") || projectId.startsWith(".")) {
    throw new Error(`invalid project id: ${projectId}`);
  }
  const root = path.join(OUTPUT_ROOT, projectId);
  // THE APP IS WHERE THE SCHEMAS ARE. The Blueprint engine projects the
  // application into `<output>/app` (beside the Blueprint and contracts), while
  // earlier generators wrote it at the project root. Reading the root for a
  // Blueprint app finds `src/schemas/*` one level too high and every /p/ page
  // 404s. Prefer the `app/` subdir when it holds the projected tree — the same
  // rule the backend's `preview_app_dir` follows.
  const nested = path.join(root, "app");
  if (existsSync(path.join(nested, "src", "schemas")) ||
      existsSync(path.join(nested, "package.json"))) {
    return nested;
  }
  return root;
}
