import { z } from "zod";
import { Validators } from "@tentoroforge/schema";
export const SliderProps = z.object({
  name:      z.string().default("slider"),
  label:     z.string().optional(),
  min:       z.number().default(0),
  max:       z.number().default(100),
  step:      z.number().default(1),
  range:     z.boolean().default(false),
  showValue: z.boolean().optional(),
  /** Declarative prefill from the schema. `value` alone is an INITIAL value,
   *  never a demand to be controlled — see util/useFieldValue.ts. */
  defaultValue: z.union([z.number(), z.tuple([z.number(), z.number()])]).optional(),
  bind:      z.string().optional(),
  /** Shared validation vocabulary — see Validators in
   *  packages/schema/src/nodes/inputs.ts. Absent here until now, which is why
   *  the Properties panel offered no "required"/min/max on a Slider. */
  validators: Validators.optional(),
  className: z.string().optional(),
  style:     z.record(z.unknown()).optional(),
});
export type SliderPropsType = z.infer<typeof SliderProps>;
