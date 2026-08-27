import { z } from "zod";

/**
 * RichTextEditor — Spec E Wave 3 mentions/embeds.
 *
 * `mentions.source` names a workflow the runtime can call to fetch the
 * autocomplete pool for `@` triggers (e.g. the "users" workflow returns
 * `[{id, label}]`). `embeds` lists the inline block kinds a user can
 * insert from a `/` menu. The current runtime implementation stubs
 * these — the schema is here so planner emissions round-trip cleanly.
 */
export const RichTextEditorProps = z.object({
  name:        z.string().default("richtext"),
  label:       z.string().optional(),
  value:       z.string().optional(),
  placeholder: z.string().optional(),
  bind:        z.string().optional(),
  className:   z.string().optional(),
  style:       z.record(z.unknown()).optional(),

  // ── Spec E Wave 3 additions ──
  mentions: z
    .object({
      source: z.string().min(1),
      trigger: z.string().default("@"),
    })
    .strict()
    .optional(),
  embeds: z.array(z.enum(["image", "link", "table"])).optional(),
});
export type RichTextEditorPropsType = z.infer<typeof RichTextEditorProps>;
