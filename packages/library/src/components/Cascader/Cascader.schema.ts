import { z } from "zod";
export type CascaderOptionT = { value: string; label: string; children?: CascaderOptionT[] };
const CascaderOption: z.ZodType<CascaderOptionT> = z.lazy(() =>
  z.object({ value: z.string(), label: z.string(), children: z.array(CascaderOption).optional() })
);
export const CascaderProps = z.object({
  options:     z.array(CascaderOption).default([]),
  placeholder: z.string().optional(),
  bind:        z.string().optional(),
  className:   z.string().optional(),
  style:       z.record(z.unknown()).optional(),
});
export type CascaderPropsType = z.infer<typeof CascaderProps>;
