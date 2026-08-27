// Shared data-engine initialiser. The SSR render path (data-engine-bridge)
// does not pass through the API route where entities are registered, so it
// must populate the registry itself. Idempotent + concurrency-safe.
import { isInitialized, markInitialized, registerEntity } from "./data-engine";
import { aliasesFor } from "./entity-aliases";

let _initPromise: Promise<void> | null = null;

export function ensureDataEngineInitialized(): Promise<void> {
  if (isInitialized()) return Promise.resolve();
  if (_initPromise) return _initPromise;
  _initPromise = (async () => {
    const modules = await Promise.allSettled([
      import("@/db/schema/documents"),
      import("@/db/schema/user"),
    ]);
    for (const result of modules) {
      if (result.status !== "fulfilled") continue;
      for (const [name, value] of Object.entries(result.value)) {
        if (name.endsWith("Relations") || typeof value !== "object" || !value) continue;
        if (typeof value === "function") continue;
        registerEntity(name, value as any, { slug: name, aliases: aliasesFor(name) });
      }
    }
    try {
      const { initializeEventRegistry } = await import("@/lib/event-registry");
      await initializeEventRegistry();
    } catch {
      // workflows optional — data engine works standalone
    }
    markInitialized();
  })();
  return _initPromise;
}
