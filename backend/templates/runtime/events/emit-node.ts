/**
 * emit_event workflow node — handler factory.
 *
 * Kept as a dependency-injected factory (no @/db, no bus import) so the
 * standalone test harness can exercise the node with a mock emitter, the
 * same way rule-set.test.mts mocks the engine's handlers. The real
 * registration in workflows/index.ts injects the durable bus
 * (events/bus.ts emitEventAndProcess) plus the runtime's {{ref}}
 * resolvers.
 *
 * Config:
 *   event     — event type to emit ("order.approved"); supports {{refs}}
 *   payload   — field → value map; values support {{refs}} like db_insert
 *   entity    — optional entity slug the event concerns
 *   entityId  — optional entity id; supports {{refs}}
 *
 * Non-fatal by design: a bus failure returns {emitted:false, warning} —
 * never an {error} key, which the engine would escalate into a failed run.
 * An event bus outage must not take the workflow down with it.
 */

export interface EmitEventOpts {
  entity?: string | null;
  entityId?: string | null;
  payload?: Record<string, unknown>;
}

export interface EmitEventDeps {
  /** Insert the event row (and kick processing). Returns the row (or id). */
  emit: (type: string, opts: EmitEventOpts) => Promise<unknown>;
  /** Resolve a single config value ({{var}} templates, sentinels). */
  resolveRef?: (ref: unknown, ctx: unknown) => unknown;
  /** Resolve a field→ref map into a plain payload object. */
  resolveMap?: (map: unknown, ctx: unknown) => Record<string, unknown>;
}

export function makeEmitEventHandler(deps: EmitEventDeps) {
  const rr = deps.resolveRef ?? ((v: unknown) => v);
  const rm =
    deps.resolveMap ??
    ((m: unknown) =>
      m && typeof m === "object" ? { ...(m as Record<string, unknown>) } : {});

  return async (config: unknown, ctx: unknown): Promise<unknown> => {
    const c = (config ?? {}) as Record<string, unknown>;
    const type = String(rr(c.event ?? c.eventType ?? "", ctx) ?? "").trim();
    if (!type) {
      console.warn("[workflow] emit_event: config.event is empty — nothing emitted");
      return { emitted: false, warning: "emit_event: config.event is empty" };
    }
    const payload = rm(c.payload, ctx);
    const entity =
      c.entity != null ? String(rr(c.entity, ctx) ?? "") || null : null;
    const entityId =
      c.entityId != null ? String(rr(c.entityId, ctx) ?? "") || null : null;
    try {
      const row = await deps.emit(type, { entity, entityId, payload });
      return {
        emitted: true,
        event: type,
        eventId: (row as { id?: unknown } | null)?.id ?? null,
      };
    } catch (err) {
      console.warn("[workflow] emit_event failed:", err);
      return { emitted: false, event: type, warning: String(err) };
    }
  };
}
