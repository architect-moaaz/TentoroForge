import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

/**
 * IllustratedEmpty — Spec C Slice 9. EmptyState with a monogram-style
 * SVG illustration derived from brand tokens. `kind` picks which of the
 * built-in illustrations to render; `title` + `message` mirror
 * EmptyState. Deterministic — no external assets.
 */
export const IllustratedEmptyProps = z
  .object({
    kind: z
      .enum([
        "list", "search", "filtered", "first-use", "no-data",
        "success", "error", "coming-soon", "no-access", "offline",
      ])
      .default("list"),
    title: z.string().min(1),
    message: z.string().optional(),
    action: z
      .object({
        label: z.string().min(1),
        workflow: z.string().min(1),
      })
      .optional(),
    style: StyleSlot.optional(),
  })
  .strict();

export type IllustratedEmptyPropsType = z.infer<typeof IllustratedEmptyProps>;
