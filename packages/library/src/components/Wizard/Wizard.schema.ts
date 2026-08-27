import { z } from "zod";
import { StyleSlot } from "@tentoroforge/schema";

/**
 * Wizard — Spec E Wave 3 multi-step form.
 *
 * A wizard is a series of `steps`, each carrying its own `fields`.
 * The runtime component drives step progression (Back/Next), holds
 * form values across steps, shows a review pane before the final
 * submit, and dispatches a workflow with the accumulated payload.
 *
 * Planner emits this when a workflow has many inputs OR when the
 * workflow branches on decisions (approval flows). The deterministic
 * `wizard_page_pass` collapses the workflow's trigger inputs into
 * this shape when the plan declares `page.wizard`.
 */
const WizardField = z
  .object({
    name: z.string().min(1),
    label: z.string().min(1),
    kind: z.enum([
      "text",
      "email",
      "number",
      "textarea",
      "select",
      "checkbox",
      "date",
      "radio",
    ]).default("text"),
    required: z.boolean().optional(),
    placeholder: z.string().optional(),
    options: z
      .array(z.object({ value: z.string(), label: z.string() }))
      .optional(),
  })
  .strict();

const WizardStep = z
  .object({
    id: z.string().min(1),
    title: z.string().min(1),
    description: z.string().optional(),
    fields: z.array(WizardField).default([]),
    // Optional gate: name of a field on this step that must be truthy
    // for Next to activate. Missing / unknown → no gate.
    nextIf: z.string().optional(),
  })
  .strict();

export const WizardProps = z
  .object({
    steps: z.array(WizardStep).min(1),
    /** Workflow name to dispatch with the accumulated values on submit. */
    onComplete: z.string().optional(),
    /** Where to navigate on success. Template-substituted with server response. */
    successRoute: z.string().optional(),
    /** Optional heading rendered above the stepper. */
    title: z.string().optional(),
    /** When true, the review step is skipped and Next submits directly. */
    skipReview: z.boolean().optional(),
    submitLabel: z.string().optional(),
    style: StyleSlot.optional(),
    className: z.string().optional(),
  })
  .strict();

export type WizardPropsType = z.infer<typeof WizardProps>;
export type WizardFieldType = z.infer<typeof WizardField>;
export type WizardStepType = z.infer<typeof WizardStep>;
