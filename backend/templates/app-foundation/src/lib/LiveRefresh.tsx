"use client";

/**
 * LiveRefresh — push-based data freshness for schema pages (R3 live UI).
 *
 * Subscribes to /api/events/stream (the SSE tail of the forge_events bus)
 * and calls router.refresh() — re-running the page's server component, so
 * SSR-resolved dataSources re-fetch — whenever an event lands for one of
 * the page's entities. Mounted by schema-page.tsx for every page that
 * declares dataSources; complements AutoRefresh (which stays the driver
 * for pages with an explicit `poll` spec — those keep their contract).
 *
 * Failure posture: silent. If the stream 404s (older app without the
 * route), errors, or the platform caps the connection, EventSource's own
 * retry runs with capped backoff and the page simply behaves as before —
 * fresh on navigation. A refresh is also fired on reconnect, covering any
 * events missed while disconnected.
 */
import { useEffect, useRef } from "react";
import { useRouter } from "next/navigation";

const DEBOUNCE_MS = 600;
const MIN_REFRESH_GAP_MS = 3000;

interface StreamEvent {
  type: string;
  entity: string | null;
  entityId: string | null;
}

export function LiveRefresh({ entities }: { entities: string[] }) {
  const router = useRouter();
  // Router identity changes across renders; keep the latest without
  // re-subscribing the EventSource.
  const routerRef = useRef(router);
  routerRef.current = router;
  const watched = entities
    .map((e) => String(e || "").toLowerCase())
    .filter(Boolean)
    .sort()
    .join(",");

  // FILTER SEAM. FilterBar/SavedViewsPicker write the selection to the URL
  // with history.replaceState, which never re-runs this page's server
  // component — so the filter changed the address bar and nothing else.
  // The library emits `forge:urlstate`; refreshing here re-resolves the
  // dataSources with the new filter. Independent of the SSE subscription
  // below, so it works on pages with no live entities too.
  useEffect(() => {
    const onUrlState = () => routerRef.current.refresh();
    window.addEventListener("forge:urlstate", onUrlState);
    return () => window.removeEventListener("forge:urlstate", onUrlState);
  }, []);

  useEffect(() => {
    if (!watched) return;
    const slugs = new Set(watched.split(","));
    let es: EventSource | null = null;
    let debounce: ReturnType<typeof setTimeout> | null = null;
    let lastRefresh = 0;
    let hadDrop = false;
    let stopped = false;

    const refresh = () => {
      const now = Date.now();
      if (now - lastRefresh < MIN_REFRESH_GAP_MS) return;
      lastRefresh = now;
      routerRef.current.refresh();
    };

    const scheduleRefresh = () => {
      if (debounce) clearTimeout(debounce);
      debounce = setTimeout(refresh, DEBOUNCE_MS);
    };

    const matches = (evt: StreamEvent): boolean => {
      const entity = String(evt.entity ?? "").toLowerCase();
      if (entity && slugs.has(entity)) return true;
      // "<slug>.created" events carry the slug in the type prefix too.
      const prefix = String(evt.type ?? "").split(".")[0].toLowerCase();
      return !!prefix && slugs.has(prefix);
    };

    try {
      es = new EventSource("/api/events/stream");
    } catch {
      return; // ancient browser / route absent — degrade silently
    }

    es.onopen = () => {
      // Reconnect after a drop: refresh once to cover missed events.
      if (hadDrop) {
        hadDrop = false;
        scheduleRefresh();
      }
    };
    es.onerror = () => {
      hadDrop = true; // EventSource retries on its own
    };
    es.onmessage = (msg) => {
      if (stopped) return;
      try {
        const data = JSON.parse(msg.data) as { events?: StreamEvent[] };
        if ((data.events ?? []).some(matches)) scheduleRefresh();
      } catch {
        /* heartbeat / malformed frame — ignore */
      }
    };

    return () => {
      stopped = true;
      if (debounce) clearTimeout(debounce);
      es?.close();
    };
  }, [watched]);

  return null;
}
