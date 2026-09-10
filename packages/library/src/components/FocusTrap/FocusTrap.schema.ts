import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

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
  /**
   * THE ONE COMPONENT IN THE FAMILY THAT RENDERS A REAL LAYOUT BOX AND COULD
   * NOT BE STYLED.
   *
   * Every sibling in this batch renders `display: contents` and takes its
   * geometry from the node-level style the dispatcher wrapper applies. FocusTrap
   * renders a bare `<div>` — and it had no `style` slot in any layer, only
   * `className`, which the registry did not expose either. So an empty trap
   * measured **960x0**: an invisible strip whose only evidence on the canvas was
   * the empty-node hint, and padding it out was not authorable.
   */
  style: StyleSlot.optional(),
});

export type FocusTrapPropsType = z.infer<typeof FocusTrapProps>;
