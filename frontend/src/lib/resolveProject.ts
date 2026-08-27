import path from "node:path";

/**
 * Resolve the on-disk path for a generated project. Used by the editor's
 * `/api/asset/<projectId>/figma/<file>` route to serve Figma SVG assets
 * extracted by the deterministic mapper.
 *
 * Mirrors apps/render-scaffold/src/lib/resolveProject so the editor and the
 * scaffold preview agree on the layout — schemas reference assets via
 * `/api/asset/<id>/figma/<hash>.svg` and both surfaces resolve them
 * relative to `output/<projectId>/public/figma/`.
 */
const OUTPUT_ROOT = process.env.OUTPUT_ROOT
  ?? path.resolve(process.cwd(), "..", "output");

export function resolveProject(projectId: string): string {
  if (!projectId) throw new Error("invalid project id: empty");
  if (projectId.includes("/") || projectId.includes("..") || projectId.startsWith(".")) {
    throw new Error(`invalid project id: ${projectId}`);
  }
  return path.join(OUTPUT_ROOT, projectId);
}
