import { z } from "zod";

export const StepperStep = z.object({
  id:          z.string().optional(),
  label:       z.string(),
  description: z.string().optional(),
  status:      z.enum(["pending", "active", "current", "complete", "done", "error", "skipped"]).optional(),
});

export const StepperProps = z.object({
  steps:       z.array(StepperStep),
  orientation: z.enum(["horizontal", "vertical"]).optional(),
  activeStep:  z.number().optional(),   // index; derives status when a step omits it
  // Current step by id/label instead of index — lets a schema bind the
  // record's live status string ("{{record.status}}") and have the
  // component derive complete/current/pending around the match.
  activeId:    z.string().optional(),
  bind:        z.string().optional(),
  className:   z.string().optional(),
  style:       z.record(z.unknown()).optional(),
});
export type StepperPropsType = z.infer<typeof StepperProps>;
