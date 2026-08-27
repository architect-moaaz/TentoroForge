import { z } from "zod";

/**
 * FocusRing — Spec E Wave 2 accessibility spine.
 *
 * A style helper. Renders its children unchanged but injects a
 * ``:focus-visible`` outline that reads the app's focus tokens:
 *
 *   --focus-ring-color   (default: currentColor)
 *   --focus-ring-width   (default: 2px)
 *   --focus-ring-offset  (default: 2px)
 *
 * Individual components (Button/Input/Link) already use these tokens
 * in their own CSS; FocusRing is the escape-hatch wrapper for schema-
 * emitted custom elements that would otherwise show no ring.
 */
export const FocusRingProps = z.object({
  /**
   * Colour override — falls back to ``--focus-ring-color``.
   * Accepts any CSS colour or var expression.
   */
  color: z.string().optional(),
  /** Ring width in px — falls back to ``--focus-ring-width``. */
  width: z.number().optional(),
  /** Ring offset in px — falls back to ``--focus-ring-offset``. */
  offset: z.number().optional(),
  className: z.string().optional(),
});

export type FocusRingPropsType = z.infer<typeof FocusRingProps>;
