import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

/**
 * OptimisticProvider — Spec E Wave 1. A form/action wrapper: when a
 * workflow dispatch happens inside its subtree, the intended state is
 * applied immediately (via the mutation queue) and rolled back on
 * error. Children read the optimistic value through the
 * `useOptimisticState()` hook exported from `@forge/renderer`.
 *
 * The component itself is a lightweight React context provider — no
 * layout impact.
 */
export const OptimisticProviderProps = z
  .object({
    /**
     * Optional resource key this optimistic scope belongs to
     * ("tasks", "orders/42"). Consumers can key off this for cache
     * invalidation on rollback.
     */
    resource: z.string().optional(),
    /**
     * When true, failures automatically show a rollback toast via the
     * UndoManager bus. Default true.
     */
    toastOnRollback: z.boolean().default(true),
    /**
     * Roll back after this many ms if the server never confirms.
     * 0 disables the timeout guard (rely on the fetch itself).
     */
    timeoutMs: z.number().int().min(0).max(120_000).default(15000),
    style: StyleSlot.optional(),
    className: z.string().optional(),
  })
  .strict();

export type OptimisticProviderPropsType = z.infer<typeof OptimisticProviderProps>;
