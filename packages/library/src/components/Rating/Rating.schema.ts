import { z } from "zod";
import { Validators } from "@tentoroforge/schema";
export const RatingProps = z.object({
  name:      z.string().default("rating"),
  label:     z.string().optional(),
  max:       z.number().int().positive().default(5),
  disabled:  z.boolean().optional(),
  /** Declarative prefill from the schema. `value` alone is an INITIAL value,
   *  never a demand to be controlled — see util/useFieldValue.ts. */
  defaultValue: z.number().optional(),
  bind:      z.string().optional(),
  /** Shared validation vocabulary — see Validators in
   *  packages/schema/src/nodes/inputs.ts. */
  validators: Validators.optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type RatingPropsType = z.infer<typeof RatingProps>;
