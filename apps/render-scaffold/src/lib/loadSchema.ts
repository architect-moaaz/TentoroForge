import { promises as fs } from "node:fs";
import path from "node:path";

/**
 * Load a schema JSON from a project's src/schemas/ directory.
 *
 * Tries two paths in order:
 *   1. <pagePath>.json            — new route-slug layout (one file per page)
 *   2. <pagePath>/list.json       — legacy entity/page-type layout
 *
 * The new path wins when both exist. The legacy path keeps existing
 * projects rendering untouched.
 *
 * Returns the parsed JSON or null if neither path is found.
 */
export async function loadSchema(
  projectRoot: string,
  pagePath: string,
): Promise<unknown | null> {
  const schemasRoot = path.join(projectRoot, "src", "schemas");
  const candidates = [
    path.join(schemasRoot, `${pagePath}.json`),
    path.join(schemasRoot, pagePath, "list.json"),
  ];
  for (const candidate of candidates) {
    try {
      const raw = await fs.readFile(candidate, "utf8");
      return JSON.parse(raw);
    } catch (err: any) {
      if (err?.code === "ENOENT") continue;
      throw err;
    }
  }
  return null;
}
