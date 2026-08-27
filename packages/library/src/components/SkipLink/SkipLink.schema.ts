import { z } from "zod";

/**
 * SkipLink — Spec E Wave 2 accessibility spine.
 *
 * A keyboard-first "skip to main content" anchor. Visually hidden
 * until it receives focus (usually the first Tab press after page
 * load); at that point it appears in the top-left corner and, when
 * activated, jumps focus to the target region (default: ``#main``).
 *
 * Every generated app receives one via the shell template so users
 * relying on the keyboard don't have to tab past the nav on every
 * page load.
 */
export const SkipLinkProps = z.object({
  /**
   * DOM id of the landmark to jump to. Leading ``#`` is added
   * automatically if omitted. Defaults to ``main`` — the id the
   * shell template stamps on its `<main>` landmark.
   */
  target: z.string().optional().default("main"),
  /**
   * Visible label shown when the link takes focus.
   */
  label: z.string().optional().default("Skip to main content"),
  className: z.string().optional(),
});

export type SkipLinkPropsType = z.infer<typeof SkipLinkProps>;
