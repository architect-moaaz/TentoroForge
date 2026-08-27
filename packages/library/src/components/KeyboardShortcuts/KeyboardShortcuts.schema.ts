import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

/**
 * KeyboardShortcuts — Spec C Slice 7. Renders a legend of the app's
 * keyboard shortcuts (typically inside a dialog opened by "?").
 * Planner emits shortcuts[] from the discovery-declared shortcut set.
 */
export const KeyboardShortcutsProps = z
  .object({
    shortcuts: z
      .array(
        z.object({
          keys: z.string().min(1),  // e.g. "Cmd+K" | "?" | "g h"
          label: z.string().min(1),
          group: z.string().optional(),
        })
      )
      .min(1),
    triggerKey: z.string().min(1).default("?"),
    style: StyleSlot.optional(),
  })
  .strict();

export type KeyboardShortcutsPropsType = z.infer<typeof KeyboardShortcutsProps>;
