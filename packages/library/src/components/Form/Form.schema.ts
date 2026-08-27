import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

const Field = z.discriminatedUnion("kind", [
  z
    .object({
      kind: z.enum(["text", "email", "number"]),
      name: z.string(),
      label: z.string(),
      required: z.boolean().optional(),
      placeholder: z.string().optional(),
    })
    .strict(),
  z
    .object({
      kind: z.literal("textarea"),
      name: z.string(),
      label: z.string(),
      required: z.boolean().optional(),
      rows: z.number().optional(),
    })
    .strict(),
  z
    .object({
      kind: z.literal("select"),
      name: z.string(),
      label: z.string(),
      required: z.boolean().optional(),
      options: z.array(z.object({ value: z.string(), label: z.string() })),
    })
    .strict(),
  z
    .object({
      kind: z.literal("checkbox"),
      name: z.string(),
      label: z.string(),
    })
    .strict(),
  z
    .object({
      kind: z.literal("date"),
      name: z.string(),
      label: z.string(),
      required: z.boolean().optional(),
    })
    .strict(),
  z
    .object({
      kind: z.literal("radio"),
      name: z.string(),
      label: z.string(),
      required: z.boolean().optional(),
      options: z.array(z.object({ value: z.string(), label: z.string() })),
    })
    .strict(),
  z
    .object({
      kind: z.literal("switch"),
      name: z.string(),
      label: z.string(),
    })
    .strict(),
  // Typed object for jsonb config columns — a fieldset of nested typed sub-fields.
  // `fields` are validated loosely here (array of field objects) to avoid a
  // recursive discriminated-union; the renderer handles each sub-field defensively.
  z
    .object({
      kind: z.literal("object"),
      name: z.string(),
      label: z.string(),
      description: z.string().optional(),
      fields: z.array(z.record(z.unknown())),
    })
    .strict(),
  // Free-form string→value map (add/remove rows) for jsonb columns of unknown shape.
  z
    .object({
      kind: z.literal("keyvalue"),
      name: z.string(),
      label: z.string(),
      description: z.string().optional(),
      valueType: z.enum(["text", "number", "boolean"]).optional(),
    })
    .strict(),
]);

// onSuccess / onError feedback descriptor consumed by runOutcome —
// {toast, navigate}. Declared here so schema validation doesn't strip
// these keys before the Form component receives them (unknown keys are
// dropped, which silently drops the schema-authored navigate target and
// leaves the fallback parentPath() nav in charge — the whole reason a
// form onSuccess.navigate wouldn't fire).
const FormOutcomeAction = z
  .object({
    toast:    z.string().optional(),
    navigate: z.string().optional(),
  })
  .strict()
  .optional();

/**
 * Form props — declarative + container dual-mode.
 *
 * Declarative mode: pass `workflow` + `fields` to get a typed form with
 * fields rendered from the data. Use this when the field set is known
 * up-front and benefits from typed validation.
 *
 * Container mode: leave both `workflow` and `fields` unset and pass child
 * nodes (Input, Textarea, Select, Button) inline. Use this when the form
 * needs custom layout (multi-column, grouped sections, conditional fields)
 * that the declarative shape doesn't express.
 *
 * Schema is non-strict — children-mode forms commonly emit no props at all.
 */
export const FormProps = z.object({
  workflow:      z.string().optional(),
  fields:        z.array(Field).optional(),
  defaultValues: z.record(z.unknown()).optional(),
  submitLabel:   z.string().optional(),
  style:         StyleSlot.optional(),
  className:     z.string().optional(),
  onSuccess:     FormOutcomeAction,
  onError:       FormOutcomeAction,

  // ── Spec E Wave 3 — auto-save + conflict resolution ─────────────
  /**
   * Opt into background auto-save. Debounced by `debounceMs`; on a
   * version-conflict response from the server, `conflictStrategy`
   * decides the follow-up:
   *  - "overwrite": last write wins
   *  - "merge":     server fields we didn't touch are preserved
   *  - "prompt":    the runtime raises a merge dialog (planned)
   */
  autoSave: z
    .object({
      debounceMs:       z.number().int().min(200).max(60_000).default(1500),
      conflictStrategy: z.enum(["overwrite", "merge", "prompt"]).default("merge"),
    })
    .strict()
    .optional(),
});

export type FormPropsType = z.infer<typeof FormProps>;
