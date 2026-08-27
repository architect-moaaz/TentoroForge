import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

/**
 * ThemeToggle — Spec C Slice 8. Toggles the document-root
 * data-theme attribute between "light" | "dark" and persists to
 * localStorage. Renders as an icon-button; label is announced to SRs.
 */
export const ThemeToggleProps = z
  .object({
    lightLabel: z.string().min(1).default("Switch to light mode"),
    darkLabel: z.string().min(1).default("Switch to dark mode"),
    storageKey: z.string().min(1).default("forge-theme"),
    style: StyleSlot.optional(),
  })
  .strict();

export type ThemeTogglePropsType = z.infer<typeof ThemeToggleProps>;
