import { z } from "zod";

/**
 * FocusTrap — Spec E Wave 2 accessibility spine.
 *
 * A container that keeps keyboard focus inside itself while mounted.
 * Used by Modal/Drawer/Popover shells so tabbing off the last control
 * loops back to the first, matching WAI-ARIA dialog authoring
 * practices. Auto-restores focus to the previously-focused element on
 * unmount.
 */
export const FocusTrapProps = z.object({
  /**
   * When false the trap is inert (children render but focus is not
   * constrained). Toggling `active` from true→false restores focus.
   */
  active: z.boolean().optional().default(true),
  /**
   * When true, focus the first focusable descendant on mount.
   * Defaults to true — matches dialog conventions.
   */
  autoFocus: z.boolean().optional().default(true),
  /**
   * When true, restore focus to the previously-focused element on
   * unmount. Defaults to true.
   */
  restoreFocus: z.boolean().optional().default(true),
  className: z.string().optional(),
});

export type FocusTrapPropsType = z.infer<typeof FocusTrapProps>;
