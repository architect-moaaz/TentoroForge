import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

// The optional `interaction` block a form field may carry — the field-
// interaction contract the renderer's formInteraction engine reads
// (renderer/src/runtime/formInteraction.ts). The zod Field union lagged the
// TS `Field = FieldSpec & { interaction? }` type and this schema: a select
// whose options come from a resource (a record picker for a `<thing>Id`
// input) was a field the runtime rendered and the schema rejected.
const Interaction = z
  .object({
    computed: z
      .object({ formula: z.string(), readOnly: z.boolean().optional() })
      .strict()
      .optional(),
    optionsFrom: z
      .object({
        source: z.string(),
        value: z.string(),
        label: z.string(),
        filter: z.record(z.string()).optional(),
      })
      .strict()
      .optional(),
    dependsOn: z.array(z.string()).optional(),
    onChange: z
      .object({
        fetch: z
          .object({ resource: z.string(), by: z.string(), from: z.string() })
          .strict(),
        set: z.record(z.string()),
      })
      .strict()
      .optional(),
    visibleIf: z.string().optional(),
    requiredIf: z.string().optional(),
    enabledIf: z.string().optional(),
    readOnlyIf: z.string().optional(),
  })
  .strict();

// Props every field kind carries, whatever its control. Shared so a field
// never loses its whole page to an over-narrow variant: a `required` checkbox
// (a consent tick) and a `hint` under any input are ordinary things a page
// composer asks for — the renderer reads `required` for validation and shows
// `hint` as helper text, so both belong on all kinds, not a curated few.
const fieldBase = {
  name: z.string(),
  label: z.string(),
  required: z.boolean().optional(),
  // Short helper text shown under the control (not the rules-engine hint).
  hint: z.string().optional(),
  interaction: Interaction.optional(),
} as const;

const Field = z.discriminatedUnion("kind", [
  z
    .object({
      kind: z.enum(["text", "email", "number"]),
      ...fieldBase,
      placeholder: z.string().optional(),
    })
    .strict(),
  z
    .object({
      kind: z.literal("textarea"),
      ...fieldBase,
      rows: z.number().optional(),
    })
    .strict(),
  z
    .object({
      kind: z.literal("select"),
      ...fieldBase,
      options: z.array(z.object({ value: z.string(), label: z.string() })),
    })
    .strict(),
  z
    .object({
      kind: z.literal("checkbox"),
      ...fieldBase,
    })
    .strict(),
  z
    .object({
      kind: z.literal("date"),
      ...fieldBase,
    })
    .strict(),
  z
    .object({
      kind: z.literal("radio"),
      ...fieldBase,
      options: z.array(z.object({ value: z.string(), label: z.string() })),
    })
    .strict(),
  z
    .object({
      kind: z.literal("switch"),
      ...fieldBase,
    })
    .strict(),
  // Typed object for jsonb config columns — a fieldset of nested typed sub-fields.
  // `fields` are validated loosely here (array of field objects) to avoid a
  // recursive discriminated-union; the renderer handles each sub-field defensively.
  z
    .object({
      kind: z.literal("object"),
      ...fieldBase,
      description: z.string().optional(),
      fields: z.array(z.record(z.unknown())),
    })
    .strict(),
  // Free-form string→value map (add/remove rows) for jsonb columns of unknown shape.
  z
    .object({
      kind: z.literal("keyvalue"),
      ...fieldBase,
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
  // The entity whose form this is — the model the form-side rules are
  // evaluated for. Derived at projection from the page; a form that says
  // none falls back to the workflow's name, which for a generated app is an
  // id like FLOW-002 and matches no rule.
  entity:        z.string().optional(),
  fields:        z.array(Field).optional(),
  // Fixed arguments dispatched with the form's `workflow`, merged UNDER the
  // user-entered field values (so a field never silently loses to a constant).
  // A composer authors these to carry the context the submit needs but the
  // user doesn't type — the record being acted on ({{write_offs.id}}), a
  // decision constant ("APPROVE"), an approver role. Buttons already declare
  // `args` for exactly this; a Form that dispatches a workflow needs it too,
  // and rejecting it failed the whole page over a prop the renderer can honor.
  args:          z.record(z.unknown()).optional(),
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
