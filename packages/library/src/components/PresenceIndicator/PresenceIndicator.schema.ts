import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

/**
 * PresenceIndicator — Spec E Wave 1. Renders the stack of avatars of
 * other users currently viewing the same route. Reads from
 * `usePresence()` in `@forge/renderer` (SSE-backed subscribe to
 * `/api/presence/:route`).
 */
export const PresenceIndicatorProps = z
  .object({
    /**
     * Optional explicit route key. Defaults to the current pathname
     * from `usePathname()` at runtime.
     */
    route: z.string().optional(),
    /** Maximum avatars to render before collapsing into "+N". */
    max: z.number().int().min(1).max(20).default(5),
    /** Size in px of each avatar circle. */
    size: z.number().int().min(16).max(96).default(28),
    /** Show tooltips with user names on hover. */
    showTooltips: z.boolean().default(true),
    style: StyleSlot.optional(),
    className: z.string().optional(),
  })
  .strict();

export type PresenceIndicatorPropsType = z.infer<typeof PresenceIndicatorProps>;
