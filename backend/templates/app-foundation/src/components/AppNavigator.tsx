"use client";
import * as React from "react";
import { useRouter } from "next/navigation";
import { NavigatorProvider, Engine } from "@tentoroforge/engine";
import { schemas } from "@/schemas/registry";
import { RouteModal } from "./RouteModal";

/**
 * AppNavigator — soft navigation + routed-modal overlay host.
 *
 * Every schema-driven navigation (Table rowHref, Button `navigate`, Link,
 * post-submit redirect) flows through the engine's Navigator, which we provide
 * here. Navigations to a record route — `/[entity]/[id]` (detail) or
 * `/[entity]/new` / `/[entity]/[id]/edit` (form) — open as an overlay
 * (Drawer / Dialog) rendered on top of the current page instead of a full
 * navigation; the URL is synced via history.pushState so it's deep-linkable and
 * the browser Back button closes it. Everything else is a normal router.push.
 *
 * We deliberately do NOT use Next.js parallel/intercepting routes: combined with
 * the (dashboard) route group and the dynamic [entity] segment they break route
 * resolution (render not-found). This client overlay is self-contained and
 * robust across every entity. The child page's data (form dropdowns, the detail
 * record) is resolved client-side by injecting `source` URLs onto the schema's
 * dataSources that point at the app's own /api/data/* CRUD endpoints.
 */

type Overlay = { url: string; routeKey: string; entity: string; id?: string; variant: "dialog" | "drawer" };

const KNOWN_ROUTES = new Set(Object.keys(schemas));

/** Segments this scaffold's own route tree owns as ACTIONS, never as record ids.
 *
 *  `src/app/(dashboard)/[entity]/new/page.tsx` and
 *  `src/app/(dashboard)/[entity]/[id]/edit/page.tsx` are real files shipped with
 *  every generated app, so these are facts about the router — not a guess about
 *  which strings look like ids, and not an exception list that needs a new entry
 *  per app. `TITLES` below is keyed by the same segments and stays in step. */
const ACTION_SEGMENTS = new Set(["new", "edit"]);

/** Decide whether a URL should render as an overlay, and how. Returns null for
 *  ordinary routes (list pages, dashboard, settings) that navigate normally. */
function overlayFor(url: string): Overlay | null {
  if (typeof url !== "string" || !url) return null;
  const path = url.split("?")[0].split("#")[0].replace(/\/+$/, "");
  const segs = path.split("/").filter(Boolean);
  if (segs.length < 2) return null;
  const entity = segs[0];
  const last = segs[segs.length - 1];

  if (last === "new" && `/${entity}/new` in schemas) {
    return { url, routeKey: `/${entity}/new`, entity, variant: "dialog" };
  }
  if (last === "edit" && segs.length >= 3 && `/${entity}/[id]/edit` in schemas) {
    return { url, routeKey: `/${entity}/[id]/edit`, entity, id: segs[segs.length - 2], variant: "dialog" };
  }
  // /[entity]/[id] detail — only when it's a dynamic detail route (not a literal
  // nested page like /tasks/board, which has its own schema key).
  //
  // ACTION_SEGMENTS IS CHECKED HERE, NOT ONLY ABOVE. The `new` and `edit`
  // branches are each guarded by `in schemas`, so when a /new page fails to
  // compose — and the composer fails exactly those pages most often — `new`
  // fell past its own branch into this one, became `id`, and
  // `withClientSources` asked for /api/data/<entity>/new. Postgres casts it to
  // uuid and raises 22P02, so a missing page surfaced as a 500 on a route that
  // was never a record lookup.
  //
  // A missing schema should navigate to the real page route (which exists on
  // disk) or 404 honestly. It must never re-interpret a verb as an identifier.
  if (segs.length === 2 && !ACTION_SEGMENTS.has(last)
      && !(path in KNOWN_ROUTES) && `/${entity}/[id]` in schemas) {
    return { url, routeKey: `/${entity}/[id]`, entity, id: last, variant: "drawer" };
  }
  return null;
}

/** Inject client-fetchable `source` URLs onto dataSources that only carry a
 *  server-side op, so the client Engine can populate the form / record. */
function withClientSources(schema: any, ov: Overlay): any {
  // A LIST SOURCE IS FETCHED BY ITS ENTITY, NOT ITS NAME. The full page
  // resolves `cases2` (a second list of Case) server-side by entity; the
  // overlay asked `/api/data/cases2` and got a 404.
  const sources = (schema?.dataSources ?? []).map((s: any) => {
    if (s.source) return s;
    if (s.op === "list" || s.op === "options") return { ...s, source: `/api/data/${encodeURIComponent(String(s.entity || s.name))}` };
    if ((s.op === "get" || s.op === "detail" || s.op === "one" || s.op === "find") && ov.id) {
      return { ...s, source: `/api/data/${ov.entity}/${encodeURIComponent(ov.id)}` };
    }
    return s;
  });
  return { ...schema, dataSources: sources };
}

const TITLES: Record<string, string> = { new: "Create", edit: "Edit" };

function OverlayContent({ overlay, onClose }: { overlay: Overlay; onClose: () => void }) {
  const [schema, setSchema] = React.useState<any>(null);
  React.useEffect(() => {
    let alive = true;
    const loader = schemas[overlay.routeKey];
    if (!loader) return;
    Promise.resolve(loader()).then((m: any) => {
      if (alive) setSchema(withClientSources(m?.default ?? m, overlay));
    });
    return () => { alive = false; };
  }, [overlay.routeKey, overlay.id]);

  // Derive from routeKey (always set) rather than url — a deep-linked/hydrated
  // overlay can arrive without a url, and `.split` on undefined would white-screen
  // the whole dashboard via the layout instead of just this modal.
  const last = (overlay.url || overlay.routeKey || "").split("/").filter(Boolean).pop() || "";
  const ent = overlay.entity || "";
  const entityLabel = ent.charAt(0).toUpperCase() + ent.slice(1);
  // When the page schema leads with its own Heading (the humanized "Add X" the
  // form builder emits), use THAT as the modal title and strip it from the body
  // — otherwise the modal shows two titles (its chrome + the page heading).
  const rootKids = (schema as any)?.root?.children;
  const leadHeading =
    Array.isArray(rootKids) && rootKids[0]?.type === "Heading" &&
    typeof rootKids[0]?.props?.content === "string"
      ? (rootKids[0].props.content as string)
      : undefined;
  const title = leadHeading
    ?? (last === "new" ? `New ${entityLabel}`
        : last === "edit" ? `Edit ${entityLabel}`
        : `${entityLabel} details`);
  const bodySchema = leadHeading
    ? { ...(schema as any), root: { ...(schema as any).root, children: rootKids.slice(1) } }
    : schema;
  const subtitle = overlay.id ? `#${overlay.id.slice(0, 8)}` : undefined;

  return (
    <RouteModal variant={overlay.variant} title={title} subtitle={subtitle} onClose={onClose}>
      {schema ? (
        <Engine schema={bodySchema} apiBaseUrl="" live />
      ) : (
        <div className="p-6 text-sm text-muted-foreground">Loading…</div>
      )}
    </RouteModal>
  );
}

export function AppNavigator({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [overlay, setOverlay] = React.useState<Overlay | null>(null);

  const open = React.useCallback(
    (url: string) => {
      const ov = overlayFor(url);
      if (!ov) {
        // Ordinary navigation. Close any open overlay first (e.g. a form submit
        // redirecting to the parent collection) and do a real router push.
        setOverlay(null);
        router.push(url);
        return;
      }
      window.history.pushState({ forgeOverlay: true }, "", url);
      setOverlay(ov);
    },
    [router],
  );

  const close = React.useCallback(() => {
    // Pop the overlay's history entry; the popstate handler clears state and
    // restores the underlying list URL.
    if (typeof window !== "undefined") window.history.back();
  }, []);

  // Keep overlay state in sync with the URL for Back/Forward.
  React.useEffect(() => {
    const onPop = () => setOverlay(overlayFor(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const value = React.useMemo(
    () => ({
      push: (url: string) => open(url),
      replace: (url: string) => router.replace(url),
      back: () => close(),
      refresh: () => router.refresh(),
    }),
    [open, close, router],
  );

  return (
    <NavigatorProvider value={value}>
      {children}
      {overlay && <OverlayContent overlay={overlay} onClose={close} />}
    </NavigatorProvider>
  );
}
