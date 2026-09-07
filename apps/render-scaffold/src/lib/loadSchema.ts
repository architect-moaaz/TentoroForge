import { promises as fs } from "node:fs";
import path from "node:path";

/**
 * The schema directories to search, in order, for a project root.
 *
 * TWO WRITERS, TWO ROOTS. The Blueprint projection writes
 * `output/<id>/app/src/schemas/`; the editor writes `output/<id>/src/schemas/`.
 * Resolving a single root per project makes one writer's pages invisible —
 * point at `app/` and every editor-authored page 404s, point at the base and
 * every generated page does. So the search is per SCHEMA, across both, and a
 * project using only one of them is simply a search that misses in the other.
 *
 * `app` is tried first: it is the built artifact the app actually ships, and
 * when both hold the same route that is the one the runtime would serve.
 */
function schemaRoots(projectRoot: string): string[] {
  const base = path.basename(projectRoot) === "app"
    ? path.dirname(projectRoot)
    : projectRoot;
  return [
    path.join(base, "app", "src", "schemas"),
    path.join(base, "src", "schemas"),
  ];
}

/**
 * Load a schema JSON from a project's schema directories.
 *
 * Tries, per root:
 *   1. <pagePath>.json            — route-slug layout (one file per page)
 *   2. <pagePath>/list.json       — legacy entity/page-type layout
 *
 * Returns the parsed JSON, or null if no candidate exists.
 */
export async function loadSchema(
  projectRoot: string,
  pagePath: string,
): Promise<unknown | null> {
  for (const schemasRoot of schemaRoots(projectRoot)) {
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
  }
  return null;
}
