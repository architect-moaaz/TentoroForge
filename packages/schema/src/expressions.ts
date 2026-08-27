import { z } from "zod";

export const Expression = z.string().min(1, "expression cannot be empty");
export type Expression = z.infer<typeof Expression>;

export const DataBinding = z
  .object({
    source: z.string().min(1),
    path: z.string().min(1),
  })
  .strict();
export type DataBinding = z.infer<typeof DataBinding>;

const WorkflowHandler = z
  .object({
    workflow: z.string().min(1),
    args: z.record(z.union([Expression, z.number(), z.boolean()])).optional(),
  })
  .strict();

const NavigateHandler = z
  .object({ navigate: z.string().min(1) })
  .strict();

export const EventHandler = z.union([WorkflowHandler, NavigateHandler]);
export type EventHandler = z.infer<typeof EventHandler>;

export const EventName = z.enum(["click", "submit", "change", "blur", "focus"]);
export type EventName = z.infer<typeof EventName>;
