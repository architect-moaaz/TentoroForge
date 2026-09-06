// Renders a schema-driven page through the CLIENT Engine, with dataSources resolved
// SERVER-SIDE for correct SSR.
//
// Why the client Engine (not the server SchemaRenderer): the library components
// (MetricTile, Card, Chart, …) are CLIENT components (they use hooks like
// useTokens/useDensity), and the registry holds direct references to them, so the
// server-side SchemaRenderer throws "Attempted to call useTokens() from the server".
//
// Why resolve data here: the Engine fetches dataSources on the client via useEffect,
// so binding expressions ("{{taskStats.total}}") are unresolved in the SSR HTML. We
// resolve them server-side (pure data — no component rendering) and pass them as
// `previewData`, which the Engine uses as its initial data — so the first render is
// already correct.

import { Engine } from "@tentoroforge/engine";
import { resolveCrumbHrefs } from "@tentoroforge/renderer";
import { actorCtx, dataEngine, resolveAggregate, resolveSeries } from "./data-engine-bridge";
import { LiveRefresh } from "./LiveRefresh";
import { FigmaCanvas } from "./FigmaCanvas";
import { WorkflowDispatchProvider } from "./WorkflowDispatchProvider";
import { WizardShell } from "./WizardShell";
import { SchemaPageBoundary } from "./SchemaPageBoundary";
import { AutoRefresh } from "./AutoRefresh";
import { getSchema } from "@/schemas/registry";
import { auth } from "@/auth";
import { notFound } from "next/navigation";
import { promises as fs } from "node:fs";
import path from "node:path";

// Resolve a page schema by route. Prefers the static registry (validated), and
// falls back to reading src/schemas/<route>.json from disk for pages added
// AFTER generation (e.g. via the visual editor) that aren't in the compiled
// registry — so an editor-created page renders instead of 404-ing. Server-only
// (this module is never imported by a client component; the registry is, which
// is why the fs fallback lives here, not in registry.ts).
async function loadPageSchema(name: string): Promise<unknown | null> {
  try {
    return await getSchema(name as never);
  } catch {
    // Not in the compiled registry — fall back to reading the on-disk schema
    // (an editor-added page). A missing file (ENOENT) or malformed JSON here is
    // an EXPECTED condition, not a crash: return null so the caller renders a
    // proper 404 instead of a 500 that takes down the whole app. (Previously
    // the unguarded fs.readFile/JSON.parse threw straight out of the server
    // component — the intermittent "server component 500".)
    try {
      const rel = name === "/" ? "home" : name.replace(/^\/+/, "");
      // Guard against path traversal from a hostile route segment.
      if (rel.includes("..")) return null;
      const file = path.join(process.cwd(), "src", "schemas", `${rel}.json`);
      const raw = await fs.readFile(file, "utf8");
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }
}

// Server-safe wizard predicate. Kept in this server module because
// WizardShell.tsx carries a "use client" directive, and Next 15 refuses
// to let a server component import a function from a client module.
// Pure JSON check — no React, no browser APIs.
function isWizardPage(page: unknown): boolean {
  if (!page || typeof page !== "object") return false;
  const w = (page as { wizard?: { steps?: unknown[] } }).wizard;
  return !!(w && Array.isArray(w.steps) && w.steps.length > 0);
}

/**
 * Which URL params this page is allowed to filter by.
 *
 * The SCHEMA declares the filterable surface (FilterBar chip keys, the keys
 * a SavedView filters on); the URL only supplies values. Anything else in
 * the query string is ignored, so a stray `?role=admin` can never become a
 * database predicate.
 */
function declaredFilterKeys(page: unknown): Set<string> {
  const keys = new Set<string>();
  const walk = (n: unknown): void => {
    if (Array.isArray(n)) return void n.forEach(walk);
    if (!n || typeof n !== "object") return;
    const node = n as Record<string, any>;
    const props = (node.props ?? {}) as Record<string, any>;
    if (node.type === "FilterBar") {
      for (const chip of (props.chips ?? []) as Array<{ key?: string }>) {
        if (chip?.key) keys.add(chip.key);
      }
      if (props.showSearch) keys.add("q");
    }
    if (node.type === "SavedViewsPicker") {
      for (const v of (props.views ?? []) as Array<{ filter?: Record<string, unknown> }>) {
        Object.keys(v?.filter ?? {}).forEach((k) => keys.add(k));
      }
    }
    for (const v of Object.values(node)) walk(v);
  };
  walk(page);
  return keys;
}

/** Merge the URL's declared filters into a dataSource's "k=v&k2=v2" string. */
function withUrlFilters(
  source: Record<string, any>,
  urlFilters: Record<string, string>,
): Record<string, any> {
  if (!Object.keys(urlFilters).length) return source;
  const merged: Record<string, string> = {};
  for (const pair of String(source.filter ?? "").split("&")) {
    const i = pair.indexOf("=");
    if (i > 0) merged[pair.slice(0, i).trim()] = pair.slice(i + 1).trim();
  }
  Object.assign(merged, urlFilters);   // the user's choice wins over the default
  const filter = Object.entries(merged).map(([k, v]) => `${k}=${v}`).join("&");
  return { ...source, filter };
}

export async function renderSchemaPage(
  name: string,
  request?: Request,
  searchParams?: Record<string, string | string[] | undefined>,
): Promise<JSX.Element> {
  let page = await loadPageSchema(name);
  // No schema for this route (missing/corrupt) — render Next's 404 rather than
  // throwing a 500. notFound() throws a special control-flow signal that Next
  // catches, so it must NOT be inside a try/catch that swallows it.
  if (!page) notFound();

  // CRUMB HREF SEAM. page_nav.py writes ancestor hrefs as route-tree keys,
  // so a crumb under a dynamic segment ships as `/conferences/[id]` — a link
  // the catch-all router resolves to a record with id "[id]", i.e. a 404.
  // The concrete id is the same `?id=` the routers already thread through for
  // the detail query. Resolving here (server-side, on a copy) keeps SSR and
  // hydration emitting the same href; a client-side fix would not.
  // `path` is the concrete request path the routers attach; it resolves
  // multi-param crumbs and the literal-match routes (`…/sessions/new`) that
  // carry no id at all. `id` stays as the fallback for callers that only
  // have that.
  let crumbId: string | undefined;
  let crumbPath: string | undefined;
  if (request) {
    try {
      const sp = new URL(request.url).searchParams;
      crumbId = sp.get("id") ?? undefined;
      crumbPath = sp.get("path") ?? undefined;
    } catch { /* non-URL internal request — hrefs get dropped, never faked */ }
  }
  page = resolveCrumbHrefs(page, { id: crumbId, pathname: crumbPath });

  // auth() can throw at request time (unset NEXTAUTH_SECRET, JWT decrypt
  // failure). A page should degrade to "no user" rather than 500 the whole
  // route — the (dashboard) layout already gates access and redirects
  // unauthenticated users to /login.
  let user: Record<string, unknown> | undefined;
  try {
    const session = await auth();
    user = session?.user as Record<string, unknown> | undefined;
  } catch (e) {
    console.error("[schema-page] auth() failed while rendering", name, e);
  }

  // Resolve each dataSource server-side (engine.run = the same DB query the server
  // renderer used). Per-source try/catch so one failing source never blanks the page.
  // FILTER SEAM. FilterBar/SavedViewsPicker write their selection to the URL,
  // but nothing read it back — so every filter chip in every generated app was
  // decorative (live on 5u9du8jt). Only keys the schema declares as filterable
  // are honoured, and only on row-returning sources.
  const _filterable = declaredFilterKeys(page);
  const urlFilters: Record<string, string> = {};
  for (const [k, raw] of Object.entries(searchParams ?? {})) {
    const v = Array.isArray(raw) ? raw[0] : raw;
    if (k !== "q" && _filterable.has(k) && typeof v === "string" && v.trim()) {
      urlFilters[k] = v.trim();
    }
  }

  // The aggregate and series resolvers are called directly here, not through
  // dataEngine.run, so they need the actor handed to them explicitly — an
  // ownership-scoped KPI or chart resolved without one reports zero instead of
  // every tenant's total.
  const engineCtx = actorCtx(user);

  const previewData: Record<string, unknown> = {};
  for (const s0 of ((page as any).dataSources ?? []) as Array<{ name: string; op?: string }>) {
    // Aggregates carry their own scoping filter (the KPI breakdowns); only
    // row-returning sources follow the user's filter selection.
    const s = (s0.op === "list" || !s0.op)
      ? (withUrlFilters(s0 as any, urlFilters) as typeof s0)
      : s0;
    try {
      if (s.op === "aggregate" || s.op === "stats") {
        previewData[s.name] = await resolveAggregate(s as any, engineCtx);   // → { todayCount: 3, … }
      } else if (s.op === "count" || s.op === "sum" || s.op === "avg" || s.op === "min" || s.op === "max") {
        // Scalar KPI aggregates. These previously fell through to the list
        // branch: the tile rendered the UNFILTERED row count, so every
        // breakdown equaled the total (Checked In 10 + Pending 10 of 10).
        // Fetch the rows, apply the "k=v&k2=v2" filter string, reduce.
        const rows = (await dataEngine.run({ ...(s as any), op: "list", filter: undefined }, { request, user })) as any[];
        const fltStr = (s as any).filter;
        let kept = Array.isArray(rows) ? rows : [];
        if (typeof fltStr === "string" && fltStr.trim()) {
          const flt: Record<string, string> = {};
          for (const pair of fltStr.split("&")) {
            const i = pair.indexOf("=");
            if (i > 0) flt[pair.slice(0, i).trim()] = pair.slice(i + 1).trim();
          }
          kept = kept.filter((r) =>
            Object.entries(flt).every(
              ([k, v]) => String(r?.[k] ?? "").toLowerCase() === v.toLowerCase(),
            ),
          );
        }
        // Legacy schemas encoded min as {op:"max", sort:"asc"} — honor it.
        const op = s.op === "max" && (s as any).sort === "asc" ? "min" : s.op;
        if (op === "count") {
          previewData[s.name] = kept.length;
        } else {
          const field = (s as any).field;
          const nums = kept.map((r) => Number(r?.[field])).filter((n) => Number.isFinite(n));
          previewData[s.name] = !nums.length ? 0
            : op === "sum" ? nums.reduce((a, b) => a + b, 0)
            : op === "avg" ? nums.reduce((a, b) => a + b, 0) / nums.length
            : op === "min" ? Math.min(...nums)
            : Math.max(...nums);
        }
      } else if (s.op === "series") {
        previewData[s.name] = await resolveSeries(s as any, engineCtx);      // → [{ label, value }, …] for charts
      } else {
        const res = await dataEngine.run(s as any, { request, user });  // → array
        // Detail/get sources name a SINGLE record (bound as {{project.name}}), so
        // unwrap the one-element array the engine returns — otherwise the binding
        // sees an array and renders nothing.
        const isDetail = s.op === "get" || s.op === "detail" || s.op === "find" || s.op === "one";
        previewData[s.name] = isDetail && Array.isArray(res) ? (res[0] ?? null) : res;
      }
    } catch (e) {
      // DV-BIND-2: elevated to console.error so the failure is visible in the
      // Next dev server output — .warn was scrolling off unnoticed. Include the
      // stack so we can tell "Unknown entity: X" apart from a real DB error.
      console.error(
        `[schema-page] dataSource '${s.name}' (entity=${(s as any).entity}, op=${s.op}) failed to resolve:\n`,
        e instanceof Error ? (e.stack || e.message) : e,
      );
    }
  }

  // Only pass previewData when we actually resolved some — an empty object is
  // still !== undefined, which flips the Engine into preview mode and makes its
  // workflow dispatch inert (so form submits silently no-op). Form/create pages
  // have no dataSources, so they MUST render live to dispatch real workflows.
  const hasPreview = Object.keys(previewData).length > 0;

  // Wizard pages carry a ``wizard`` metadata block emitted by
  // backend/services/wizard_wire.py. Route them through WizardShell so
  // the client-side step machinery runs; the shell hosts its own
  // Engine internally, so we don't double-wrap here.
  if (isWizardPage(page as any)) {
    return <WizardShell page={page as any} />;
  }

  // SchemaPageBoundary catches any render/hydration error thrown by Engine or
  // its children (bad token access, undefined binding, library component
  // NPE) so one dud component doesn't blank the whole page — Next 15's
  // default "Application error, digest=…" screen is what testers were hitting
  // (bug B-020.8). Fallback logs digest server-side and renders in place.
  //
  // AutoRefresh: when the page schema declares a top-level `poll` object,
  // wrap the tree in the client-side driver that re-runs the RSC path on
  // interval. This is how a stateful single-page schema (scan flow: initial
  // → scanning → results) transitions between states without a navigation.
  // See docs/superpowers/patterns/stateful-single-page.md for the shape.
  const engineNode = (
    <Engine
      schema={page as any}
      apiBaseUrl=""
      live
      {...(hasPreview ? { previewData } : {})}
    />
  );
  const pollSpec = (page as any)?.poll;
  const rendered = pollSpec && typeof pollSpec === "object"
    ? <AutoRefresh poll={pollSpec} previewData={hasPreview ? previewData : undefined}>{engineNode}</AutoRefresh>
    : engineNode;
  // R3 live UI: pages with dataSources subscribe to the forge_events SSE
  // tail and re-run this server component when one of their entities
  // changes — push freshness instead of navigation-only. Pages with an
  // explicit `poll` spec keep AutoRefresh as their sole driver (a second
  // refresh channel would just double the churn on stateful scan pages).
  const liveEntities = pollSpec
    ? []
    : Array.from(
        new Set(
          (((page as any).dataSources ?? []) as Array<{ entity?: string }>)
            .map((s) => String(s?.entity ?? "").toLowerCase())
            .filter(Boolean),
        ),
      );
  // Spec E Wave 2 accessibility spine — every schema-rendered route is
  // wrapped in a <main id="main"> landmark so the shell-injected
  // SkipLink can jump into it. `role="main"` is redundant on <main> in
  // modern SR engines but kept explicit for older AT parity.
  //
  // Figma-derived pages escape the dashboard chrome: the design carries
  // its own bg + full-viewport layout, and the shell's sidebar/theme
  // wrapper paints over it. `fixed inset-0` covers both — content
  // renders exactly as authored.
  const figmaDerived = !!(page as any)?._figmaDerived;
  // Steal the root's bg + text-color classes so the escape wrapper matches the
  // design's own palette. Otherwise the shell chrome bleeds through the fixed
  // layer's uncovered edges (bg) and the body's `text-foreground` (light-mode
  // dark text) is inherited by every child that doesn't declare a color.
  const rootClassName = String(
    (page as any)?.root?.props?.className ??
      (page as any)?.props?.className ??
      "",
  );
  const bgMatch = rootClassName.match(/\bbg-\[[^\]]+\]|\bbg-[a-z]+-\d+\b|\bbg-black\b|\bbg-white\b/);
  const textMatch = rootClassName.match(/\btext-\[[^\]]+\]|\btext-[a-z]+-\d+\b|\btext-white\b|\btext-black\b/);
  const rootBg = bgMatch?.[0] ?? "bg-black";
  // Detect dark bg by hex or common tailwind classes — if it looks dark and no
  // explicit text color was declared, default to white so text reads.
  const bgHex = bgMatch?.[0]?.match(/#([0-9a-fA-F]{3,8})/)?.[1];
  const bgIsDark =
    !!bgHex && (parseInt(bgHex.slice(0, 2), 16) || 0) + (parseInt(bgHex.slice(2, 4), 16) || 0) + (parseInt(bgHex.slice(4, 6), 16) || 0) < 300;
  const rootText = textMatch?.[0] ?? (bgIsDark || rootBg === "bg-black" ? "text-white" : "");
  // The frame's own dimensions, recorded at extraction and carried through
  // `figma_layout.compose`. Present only on a page built FROM a design, so
  // every other page renders exactly as before.
  const figmaCanvas = (page as any)?._figmaCanvas as
    | { width: number; height: number; fit?: "scale" | "fluid" }
    | undefined;

  const mainClass = figmaDerived
    ? `fixed inset-0 z-[60] overflow-auto ${rootBg} ${rootText}`.trim()
    : undefined;
  return (
    <WorkflowDispatchProvider>
      <SchemaPageBoundary route={name}>
        <main
          id="main"
          role="main"
          tabIndex={-1}
          className={mainClass}
          data-figma-derived={figmaDerived || undefined}
        >
          {/* Mounted whenever the page declares a filterable surface OR has
              live entities: it drives BOTH the forge:urlstate filter refresh
              and the SSE tail, and self-guards the SSE half on an empty
              entity list. Gating it on liveEntities alone left filters dead
              on poll-spec and non-live pages. */}
          {(liveEntities.length > 0 || _filterable.size > 0) && (
            <LiveRefresh entities={liveEntities} />
          )}
          {figmaCanvas?.width ? (
            <FigmaCanvas width={figmaCanvas.width} height={figmaCanvas.height} fit={figmaCanvas.fit}>
              {rendered}
            </FigmaCanvas>
          ) : (
            rendered
          )}
        </main>
      </SchemaPageBoundary>
    </WorkflowDispatchProvider>
  );
}
