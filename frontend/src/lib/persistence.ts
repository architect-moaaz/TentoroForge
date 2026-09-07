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

async function saveFile(projectId: string, relPath: string, content: string): Promise<void> {
  // NOTE: errors are intentionally NOT caught here — callers decide the policy.
  // Write via the short-id project-file endpoint — symmetric with the editor's
  // read path (GET /api/_debug/project-file/{short_id}/{path}). projectId here
  // is the project SHORT id (what VisualEditorWorkspace passes).
  const send = () =>
    fetch(`${API}/api/_debug/project-file/${projectId}/${relPath}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
  let r = await send();
  // RETRY ONCE ON 429, DO NOT REPORT IT AS LOST WORK.
  //
  // The persister debounces at 500ms — 120 writes a minute at a steady edit
  // rate — which was the server's ENTIRE old allowance, so the editor throttled
  // itself and the user saw "COULDN'T SAVE … HTTP 429" with their changes still
  // unsaved. The ceiling has been raised (backend/config.py), but a burst can
  // still clip it, and a rate limit is a "come back in a moment", not a failure:
  // honour the server's own Retry-After and try again before telling anyone.
  if (r.status === 429) {
    const after = Number(r.headers.get("Retry-After"));
    const waitMs = Number.isFinite(after) && after > 0 ? Math.min(after * 1000, 5000) : 1000;
    await new Promise((res) => setTimeout(res, waitMs));
    r = await send();
  }
  // THROW on non-2xx. Previously this only console.warn'd and resolved, so a
  // failed write (401/403/5xx) still let runSave reach markClean() →
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
    const navPages = (artifacts.navFlow as { pages?: Array<{ id?: string; schemaFile?: string }> } | undefined)?.pages ?? [];
    const schemaFileById = new Map<string, string>();
    for (const p of navPages) {
      if (p?.id && p?.schemaFile) schemaFileById.set(p.id, p.schemaFile);
    }
    for (const [pageId, page] of Object.entries(artifacts.pageSchemas)) {
      const path = schemaFileById.get(pageId) ?? `src/schemas/${pageId}.json`;
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
