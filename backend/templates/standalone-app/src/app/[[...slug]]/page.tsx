import { notFound, redirect } from "next/navigation";
import { promises as fs } from "node:fs";
import path from "node:path";
import { renderSchemaPage } from "@/lib/schema-page";
import { entryRoute, schemas as routesRegistry } from "@/schemas/registry";
import CodedRoot, { hasCodeRoot } from "../_root/page";

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
  searchParams,
}: {
  params: Promise<{ slug?: string[] }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { slug = [] } = await params;
  // `/` WRITTEN AS REACT. A coded root page cannot have its own route file
  // (this catch-all already answers `/`), so it lives in the private `_root`
  // module and is rendered from here — before any schema lookup.
  if (slug.length === 0 && hasCodeRoot) {
    return CodedRoot({ params: Promise.resolve({}), searchParams });
  }
  // OPTIONAL, SO IT SERVES "/" TOO. `[...slug]` needs at least one segment,
  // so the root URL matched no route at all and Next answered 404 — while
  // `src/app/page.tsx` is deliberately retired on every assembly, leaving
  // nothing else to serve it. An application whose only page is at "/" — a
  // calculator, a single-screen tool — was unreachable at its own address.
  // The `["home"]` fallback below was written for this case and could never
  // fire, because a required catch-all never yields an empty slug.
  const parts = slug.length ? slug : ["home"];
  const isRoot = slug.length === 0;
  const schemasRoot = path.join(process.cwd(), "src", "schemas");

  // The root's schema is registered under "/" and stored as `home.json`, so
  // the key and the file disagree for this one route and both are tried.
  const attempts = isRoot
    ? [{ relPath: "home", routeKey: "/" }, ..._pathAttempts(parts)]
    : _pathAttempts(parts);
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
  if (!matched && isRoot && entryRoute) {
    // MOST APPLICATIONS DECLARE NO PAGE AT "/". A master-data app is
    // `/add-data` and `/master-data`; nothing is at the root. The scaffold
    // used to ship a landing page there and it had to be retired — a route
    // group contributes nothing to the URL, so `(dashboard)/page.tsx` WAS "/"
    // and collided with this file. That left the root with nothing behind it:
    // a sign-in redirect, and a 404 on the way back from it.
    //
    // `entryRoute` is projected from the Blueprint — the page marked `entry`,
    // or the first thing in the navigation — and is empty when the
    // application genuinely has a page at "/", in which case this never runs
    // and the schema above renders.
    redirect(entryRoute);
  }
  if (!matched) notFound();

  // renderSchemaPage looks up the route by its normalized string
  // (``/drives/[id]``), not the on-disk relPath. Convert.
  //
  // `path` carries the CONCRETE url alongside the id. Breadcrumb ancestor
  // hrefs arrive as route-tree keys (`/conferences/[id]`), and only the real
  // path can turn those back into links that resolve — including on literal
  // matches like `/conferences/<id>/sessions/new`, where no id is threaded at
  // all. See renderer's resolveCrumbHrefs.
  const concretePath = isRoot ? "/" : "/" + parts.join("/");
  const qs = new URLSearchParams({ path: concretePath });
  if (matched.id !== undefined) qs.set("id", matched.id);
  const request = new Request(`internal:?${qs.toString()}`);
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
