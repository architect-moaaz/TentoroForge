import { z } from "zod";

/**
 * AutoFocus — Spec E Wave 2 accessibility spine.
 *
 * Declarative wrapper: focuses its first focusable descendant on
 * mount. Used inside forms/dialogs where the user should be able to
 * start typing immediately without an extra Tab.
 */
export const AutoFocusProps = z.object({
  /**
   * When false the wrapper is inert (children render, no focus is
   * moved). Defaults to true.
   */
  enabled: z.boolean().optional().default(true),
  /**
   * Optional CSS selector to prefer as the focus target — first
   * match inside the wrapper wins. Falls back to the first
   * focusable descendant when unset or unmatched.
   */
  selector: z.string().optional(),
  /**
   * When true, delays the focus() call by one microtask so it wins
   * against browser scroll-restoration on route change. Default true.
   */
  delayed: z.boolean().optional().default(true),
  className: z.string().optional(),
});

export type AutoFocusPropsType = z.infer<typeof AutoFocusProps>;
