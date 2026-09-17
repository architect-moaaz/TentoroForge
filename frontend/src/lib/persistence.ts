"use client";
/**
 * Debounced auto-save of artifacts to the backend.
 *
 * Writes each page schema to src/schemas/<id>.json individually so per-page
 * editing locks work cleanly (the spec's "N page-schema files" constraint).
 * Writes nav-flow.json and tokens.json as single files.
 *
 * 500ms debounce — every dispatch resets the timer. The most recent
 * snapshot wins. Errors are logged to console; we don't fail the user
 * over a transient network blip.
 */
import type { Artifacts } from "@forge/patches";
import { useEditorStore } from "./editor-store";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:6500";

/**
 * Route → schema-file slug, mirroring the backend's `slugify_route`: "/" → "home",
 * `:param` → `[param]`, leading/trailing slashes stripped. This is the same map
 * the generated `src/schemas/registry.ts` uses (route → `import(./<slug>.json)`),
 * so a save keyed off the route lands on the file the running app renders.
 */
export function slugifyRoute(route: string): string {
  if (!route || route === "/") return "home";
  return route
    .replace(/:([A-Za-z0-9_]+)/g, "[$1]")
    .replace(/^\/+|\/+$/g, "")
    .replace(/\/{2,}/g, "/");
}

async function saveFile(projectId: string, relPath: string, content: string): Promise<void> {
  // NOTE: errors are intentionally NOT caught here — callers decide the policy.
  // Write via the short-id project-file endpoint — symmetric with the editor's
  // read path (GET /api/_debug/project-file/{short_id}/{path}). projectId here
  // is the project SHORT id (what VisualEditorWorkspace passes).
  const r = await fetch(`${API}/api/_debug/project-file/${projectId}/${relPath}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  // THROW on non-2xx. Previously this only console.warn'd and resolved, so a
  // failed write (401/403/429/5xx) still let runSave reach markClean() →
  // isDirty=false + a green "Saved" while the edit was actually lost. Throwing
  // keeps isDirty=true and lets callers surface the failure.
  if (!r.ok) throw new Error(`Save failed: ${relPath} → HTTP ${r.status}`);
}

export interface Persister {
  save: (artifacts: Artifacts) => void;
  flush: () => Promise<void>;
  isPending: () => boolean;
}

export function buildPersister(projectId: string, debounceMs = 500): Persister {
  let timer: ReturnType<typeof setTimeout> | null = null;
  let inflight: Promise<void> | null = null;
  // The snapshot captured at the time the timer was set — used by flush().
  let pendingArtifacts: Artifacts | null = null;

  // runSave does NOT catch errors — it re-throws so flush() callers see failures.
  // The debounce path (background save) catches and logs to avoid crashing the page.
  async function runSave(artifacts: Artifacts): Promise<void> {
    // Build a lookup from page id → schemaFile so saves land at the same
    // path nav-flow declared (and where the read path fetched from).
    // Pages without a navFlow entry fall back to `src/schemas/<id>.json`.
    // TWO ID VOCABULARIES. `artifacts.pageSchemas` is keyed by the schema's own
    // id (the Blueprint page id, `PAGE-002`), but nav-flow keys its pages by
    // route slug (`add-data`). Looking the file up by pageSchemas key alone
    // missed every Blueprint-built page, fell back to `src/schemas/PAGE-002.json`
    // — a file nothing reads — and the edit came back on refresh. A page and its
    // nav entry both carry `route`, so match on that when the id misses.
    const navPages = (artifacts.navFlow as {
      pages?: Array<{ id?: string; route?: string; schemaFile?: string }>;
    } | undefined)?.pages ?? [];
    const schemaFileById = new Map<string, string>();
    const schemaFileByRoute = new Map<string, string>();
    for (const p of navPages) {
      if (!p?.schemaFile) continue;
      if (p.id) schemaFileById.set(p.id, p.schemaFile);
      if (p.route) schemaFileByRoute.set(p.route, p.schemaFile);
    }
    for (const [pageId, page] of Object.entries(artifacts.pageSchemas)) {
      const route = (page as { route?: string } | undefined)?.route;
      const path =
        schemaFileById.get(pageId) ??
        (route ? schemaFileByRoute.get(route) : undefined) ??
        // The last resort must match the file the RUNNING app reads — the
        // registry maps a route to `src/schemas/<slugify(route)>.json`, so a
        // page missing from nav-flow (e.g. the /offers list) still saves to the
        // file the preview renders. `src/schemas/<pageId>.json` used the
        // Blueprint id (PAGE-002), a file nothing imports, so the edit never
        // reached the running app (DEFECT-RENAME-NOOP, editor half).
        (route ? `src/schemas/${slugifyRoute(route)}.json` : `src/schemas/${pageId}.json`);
      await saveFile(projectId, path, JSON.stringify(page, null, 2));
    }
    await saveFile(
      projectId,
      "src/contracts/nav-flow.json",
      JSON.stringify(artifacts.navFlow, null, 2),
    );
    // Tokens persist to src/theme/tokens.custom.json — the file the generated
    // app (and the editor's own token fetch) actually reads. The old
    // src/contracts/tokens.json target was a dead file nothing consumed.
    await saveFile(
      projectId,
      "src/theme/tokens.custom.json",
      JSON.stringify(artifacts.tokens, null, 2),
    );
    useEditorStore.getState().markClean();
  }

  function save(artifacts: Artifacts): void {
    pendingArtifacts = artifacts;
    if (timer !== null) {
      clearTimeout(timer);
    }
    timer = setTimeout(() => {
      timer = null;
      const snapshot = pendingArtifacts!;
      pendingArtifacts = null;
      // Fix (Important 1): if a previous save is still in-flight, await it first
      // so the two saves don't race over the same files.
      const previous = inflight;
      inflight = (async () => {
        if (previous !== null) {
          // Absorb errors from the previous inflight so they don't surface here;
          // they have already been handled (either logged or propagated to flush()).
          try { await previous; } catch { /* already handled */ }
        }
        await runSave(snapshot);
      })()
        .catch((e) => {
          // Background (debounce-path) save: log AND surface to the user — a
          // failed autosave must not be silent (isDirty stays true because
          // runSave threw before markClean).
          console.warn("[persist] background save failed", e);
          useEditorStore.getState().setSaveError(
            "Couldn't save your changes — they're still unsaved. " +
            (e instanceof Error ? e.message : String(e)),
          );
        })
        .finally(() => {
          inflight = null;
        });
    }, debounceMs);
  }

  async function flush(): Promise<void> {
    // If a debounce timer is pending, cancel it and run immediately.
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
      const snapshot = pendingArtifacts!;
      pendingArtifacts = null;
      // CHAIN onto any still-running background save rather than starting a
      // concurrent runSave — otherwise the two writes race over the same files
      // and an older snapshot can land last and clobber a newer one. Mirrors the
      // serialization the save() debounce path already does. The flush()-path
      // does NOT swallow the final error — it propagates to the caller (Save
      // button / unmount flush) so the failure is surfaced.
      const previous = inflight;
      const mine: Promise<void> = (async () => {
        if (previous !== null) {
          try { await previous; } catch { /* already handled by its own path */ }
        }
        await runSave(snapshot);
      })();
      inflight = mine;
      // Only clear inflight if it is still THIS promise (a newer save may have
      // replaced it while this one was running).
      void mine.catch(() => {}).finally(() => { if (inflight === mine) inflight = null; });
    }
    const p = inflight;
    if (p !== null) {
      await p;
    }
  }

  function isPending(): boolean {
    return timer !== null || inflight !== null;
  }

  return { save, flush, isPending };
}
