import { notFound } from "next/navigation";
import { promises as fs } from "node:fs";
import path from "node:path";
import { renderSchemaPage } from "@/lib/schema-page";
import { schemas as routesRegistry } from "@/schemas/registry";

/**
 * DV-BIND: dynamic-segment aware catch-all.
 *
 * A URL like ``/drives/c1c84d16`` needs to match a schema stored under
 * ``src/schemas/drives/[id].json``, and the ``c1c84d16`` segment must reach
 * ``dataSources[...].id`` so the server-side detail query loads the right
 * record. The previous template joined every segment verbatim, tried the
 * literal file, and only fell back to notFound — so ``/drives/[some-uuid]``
 * pages rendered with empty ``{{recruitmentDrive.field}}`` bindings.
 *
 * Resolution order for the URL segments ``[a, b, c, …]``:
 *   1. Literal path ``a/b/c.json`` (a real nested page like ``/tasks/board``).
 *   2. Right-to-left, try each segment replaced by ``[id]``:
 *        a/b/[id].json  (id = c)
 *        a/[id]/c.json  (id = b)
 *        [id].json      (id = a)   — top-level dynamic detail
 *   The FIRST match wins.
 *
 * When a match includes an ``[id]`` slot, the corresponding segment is
 * threaded through as ``?id=…`` on the internal Request so
 * ``data-engine-bridge`` picks it up in its URL-searchParams fallback and
 * calls ``engine.findById(entity, id)`` — the code path that unwraps to
 * the single record the DescriptionList binds to.
 */
export default async function Page({
  params,
}: { params: Promise<{ slug?: string[] }> }) {
  const { slug = [] } = await params;
  const parts = slug.length ? slug : ["home"];
  const schemasRoot = path.join(process.cwd(), "src", "schemas");

  const attempts = _pathAttempts(parts);
  let matched: { relPath: string; routeKey: string; id?: string } | null = null;
  // P1-O2: registry is authoritative. A route registered in registry.ts (even
  // if its file lives at an unusual on-disk path) must resolve. fs.access is
  // kept as a backup so files added on disk without a registry entry still work.
  for (const attempt of attempts) {
    if (attempt.routeKey in routesRegistry) {
      matched = attempt;
      break;
    }
  }
  if (!matched) {
    for (const attempt of attempts) {
      try {
        await fs.access(path.join(schemasRoot, `${attempt.relPath}.json`));
        matched = attempt;
        break;
      } catch {
        /* not this one — keep trying */
      }
    }
  }
  if (!matched) notFound();

  // renderSchemaPage looks up the route by its normalized string
  // (``/drives/[id]``), not the on-disk relPath. Convert.
  const request = matched.id !== undefined
    ? new Request(`internal:?id=${encodeURIComponent(matched.id)}`)
    : new Request("internal:");
  return renderSchemaPage(matched.routeKey, request);
}


function _pathAttempts(parts: string[]): Array<{
  relPath: string;
  routeKey: string;
  id?: string;
}> {
  const out: Array<{ relPath: string; routeKey: string; id?: string }> = [];
  // (1) literal — nested static pages like /tasks/board win over id detection.
  out.push({
    relPath: parts.join("/"),
    routeKey: "/" + parts.join("/"),
  });
  // (2) right-to-left, each segment replaced with [id].
  for (let i = parts.length - 1; i >= 0; i--) {
    const swapped = parts.slice();
    const id = swapped[i];
    swapped[i] = "[id]";
    out.push({
      relPath: swapped.join("/"),
      routeKey: "/" + swapped.join("/"),
      id,
    });
  }
  return out;
}
