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
    /**
     * What the user does next: run a workflow, or go somewhere.
     *
     * `workflow` was the only case, strictly, and an empty state whose button
     * links elsewhere is the commoner one — "no jobs yet" wants /jobs/new, not
     * a dispatch. Authoring wrote `{ label, navigate }` on four pages and each
     * was rejected twice over: `workflow` missing, `navigate` not allowed.
     *
     * `navigate` is the library's own word for this (Link.navigate,
     * Button.navigate), so this spells it the same way rather than inventing a
     * third. A union of two exact shapes, not one object with both optional:
     * an action that carries neither is the bug this used to prevent.
     */
    action: z
      .union([
        z.object({
          label: z.string().min(1),
          workflow: z.string().min(1),
        }).strict(),
        z.object({
          label: z.string().min(1),
          navigate: z.string().min(1),
        }).strict(),
      ])
      .optional(),
    style: StyleSlot.optional(),
  })
  .strict();

export type IllustratedEmptyPropsType = z.infer<typeof IllustratedEmptyProps>;
